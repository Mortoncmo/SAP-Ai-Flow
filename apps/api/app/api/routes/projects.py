from functools import lru_cache
from time import perf_counter
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from sqlalchemy.orm import Session

from app.agent.base import LLMProvider
from app.agent.orchestrator import ProcessAgentOrchestrator
from app.agent.result_cache import ModelResultCache
from app.api.routes.flowcharts import get_provider
from app.core.config import Settings, get_settings
from app.core.errors import FlowchartError
from app.db.database import get_db_session
from app.db.models import (
    ExportJobRecord,
    ProcessRecord,
    ProcessRevisionRecord,
    ProjectAuditRecord,
    ProjectMemberRecord,
    ProjectRecord,
)
from app.db.repository import BlueprintRepository
from app.documents.export_service import (
    blueprint_document,
    export_filenames,
    process_export_job,
    render_export,
)
from app.graph.patcher import apply_patch
from app.graph.validator import graph_warnings
from app.knowledge.service import KnowledgeService, get_knowledge_service
from app.models.api import ResponseMetrics
from app.models.graph import GapStatus, GraphDocument, SapContext
from app.models.patch import LLMPatch, NodeChanges, UpdateNodeOperation
from app.models.projects import (
    DraftCreate,
    ExportJobResponse,
    ExportRequest,
    GapDecisionCreate,
    GapDecisionResponse,
    ManualSaveRequest,
    ManualSaveResponse,
    PersistedModifyRequest,
    PersistedModifyResponse,
    ProcessCreate,
    ProcessDetail,
    ProcessSummary,
    ProjectAuditResponse,
    ProjectCreate,
    ProjectMemberResponse,
    ProjectMemberUpsert,
    ProjectResponse,
    ProjectSettingsUpdate,
    ReleaseCreate,
    ReleaseResponse,
    RevisionDetailResponse,
    RevisionResponse,
)
from app.security.auth import ProjectRole, UserContext, get_user_context, require_role

router = APIRouter(prefix="/api/v1", tags=["projects"])


def get_repository(session: Session = Depends(get_db_session)) -> BlueprintRepository:
    return BlueprintRepository(session)


@lru_cache(maxsize=16)
def _configured_model_cache(ttl_seconds: float, max_entries: int) -> ModelResultCache:
    return ModelResultCache(ttl_seconds=ttl_seconds, max_entries=max_entries)


def get_model_result_cache(
    settings: Settings = Depends(get_settings),
) -> ModelResultCache:
    return _configured_model_cache(
        settings.llm_cache_ttl_seconds,
        settings.llm_cache_max_entries,
    )


@router.post("/projects", response_model=ProjectResponse, status_code=201)
def create_project(
    request: ProjectCreate,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> ProjectResponse:
    project = repository.create_project(
        name=request.name,
        customer_name=request.customer_name,
        sap_context=request.sap_context,
        user_id=user.user_id,
    )
    return _project_response(project, ProjectRole.PROJECT_ADMIN)


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> list[ProjectResponse]:
    return [
        _project_response(
            project,
            ProjectRole(repository.require_project_member(project.id, user.user_id).role),
        )
        for project in repository.list_projects(user_id=user.user_id)
    ]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> ProjectResponse:
    project = _authorize_project(repository, project_id, user, ProjectRole.VIEWER)
    role = ProjectRole(repository.require_project_member(project_id, user.user_id).role)
    return _project_response(project, role)


@router.put("/projects/{project_id}", response_model=ProjectResponse)
def update_project_settings(
    project_id: str,
    request: ProjectSettingsUpdate,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> ProjectResponse:
    project = _authorize_project(repository, project_id, user, ProjectRole.PROJECT_ADMIN)
    updated = repository.update_project_settings(
        project=project,
        external_model_enabled=request.external_model_enabled,
        actor_user_id=user.user_id,
    )
    return _project_response(updated, ProjectRole.PROJECT_ADMIN)


@router.get("/projects/{project_id}/audits", response_model=list[ProjectAuditResponse])
def list_project_audits(
    project_id: str,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> list[ProjectAuditResponse]:
    _authorize_project(repository, project_id, user, ProjectRole.PROJECT_ADMIN)
    return [_project_audit_response(item) for item in repository.list_project_audits(project_id)]


@router.get("/projects/{project_id}/members", response_model=list[ProjectMemberResponse])
def list_project_members(
    project_id: str,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> list[ProjectMemberResponse]:
    _authorize_project(repository, project_id, user, ProjectRole.PROJECT_ADMIN)
    return [_member_response(member) for member in repository.list_project_members(project_id)]


@router.post(
    "/projects/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=201,
)
def add_project_member(
    project_id: str,
    request: ProjectMemberUpsert,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> ProjectMemberResponse:
    _authorize_project(repository, project_id, user, ProjectRole.PROJECT_ADMIN)
    member = repository.add_project_member(
        project_id=project_id,
        user_id=request.user_id,
        role=request.role,
        actor_user_id=user.user_id,
    )
    return _member_response(member)


@router.put(
    "/projects/{project_id}/members/{member_user_id}",
    response_model=ProjectMemberResponse,
)
def update_project_member(
    project_id: str,
    member_user_id: str,
    request: ProjectMemberUpsert,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> ProjectMemberResponse:
    _authorize_project(repository, project_id, user, ProjectRole.PROJECT_ADMIN)
    if request.user_id != member_user_id:
        raise FlowchartError(
            "PROJECT_MEMBER_ID_MISMATCH",
            "路径中的成员用户与请求体不一致。",
            status_code=422,
            details={"member_user_id": member_user_id, "request_user_id": request.user_id},
        )
    member = repository.update_project_member(
        project_id=project_id,
        user_id=member_user_id,
        role=request.role,
        actor_user_id=user.user_id,
    )
    return _member_response(member)


@router.delete("/projects/{project_id}/members/{member_user_id}", status_code=204)
def remove_project_member(
    project_id: str,
    member_user_id: str,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> Response:
    _authorize_project(repository, project_id, user, ProjectRole.PROJECT_ADMIN)
    repository.remove_project_member(
        project_id=project_id,
        user_id=member_user_id,
        actor_user_id=user.user_id,
    )
    return Response(status_code=204)


@router.post("/projects/{project_id}/processes", response_model=ProcessDetail, status_code=201)
def create_process(
    project_id: str,
    request: ProcessCreate,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> ProcessDetail:
    project = _authorize_project(repository, project_id, user, ProjectRole.EDITOR)
    process, revision = repository.create_process(
        project=project,
        name=request.name,
        module=request.module,
        process_scope=request.process_scope,
        initial_graph=request.initial_graph,
        user_id=user.user_id,
    )
    return _process_detail(process, GraphDocument.model_validate(revision.graph_json))


@router.get("/projects/{project_id}/processes", response_model=list[ProcessSummary])
def list_processes(
    project_id: str,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> list[ProcessSummary]:
    _authorize_project(repository, project_id, user, ProjectRole.VIEWER)
    return [
        _process_summary(process)
        for process in repository.list_processes(project_id, user_id=user.user_id)
    ]


@router.get("/processes/{process_id}", response_model=ProcessDetail)
def get_process(
    process_id: str,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> ProcessDetail:
    process = _authorize_process(repository, process_id, user, ProjectRole.VIEWER)
    return _process_detail(process, repository.current_graph(process))


@router.post("/processes/{process_id}/save", response_model=ManualSaveResponse)
def save_process(
    process_id: str,
    request: ManualSaveRequest,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> ManualSaveResponse:
    process = _authorize_process(repository, process_id, user, ProjectRole.EDITOR)
    current_graph = repository.current_graph(process)
    graph = GraphDocument.model_validate(request.graph)
    _validate_gap_edit(current_graph, graph)
    revision = repository.save_manual_graph(
        process=process,
        base_revision=request.base_revision,
        graph=graph,
        summary=request.summary,
        user_id=user.user_id,
    )
    return ManualSaveResponse(
        request_id=request.request_id,
        base_revision=request.base_revision,
        result_revision=revision.revision_no,
        graph=graph,
    )


@router.post("/processes/{process_id}/modify", response_model=PersistedModifyResponse)
async def modify_process(
    process_id: str,
    request: PersistedModifyRequest,
    repository: BlueprintRepository = Depends(get_repository),
    provider: LLMProvider = Depends(get_provider),
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    model_cache: ModelResultCache = Depends(get_model_result_cache),
    user: UserContext = Depends(get_user_context),
) -> PersistedModifyResponse:
    process = _authorize_process(repository, process_id, user, ProjectRole.EDITOR)
    project = repository.require_project(process.project_id, user_id=user.user_id)
    repository.ensure_current_revision(process, request.base_revision)
    current_graph = repository.current_graph(process)
    started = perf_counter()
    result = await ProcessAgentOrchestrator(
        provider,
        knowledge_service,
        external_model_enabled=project.external_model_enabled,
        model_cache=model_cache,
        cache_namespace=f"{project.id}:{process.id}",
    ).run(
        current_graph,
        request.instruction,
        request.locale,
    )
    updated = result.graph
    _validate_gap_edit(current_graph, updated)
    repository.save_modified_graph(
        process=process,
        base_revision=request.base_revision,
        graph=updated,
        patch=result.patch,
        user_prompt=request.instruction,
        provider=result.provider,
        model=result.model,
        evidence_refs=list(
            dict.fromkeys(
                [
                    *request.evidence_refs,
                    *[item.evidence_ref for item in result.evidence],
                ]
            )
        ),
        user_id=user.user_id,
    )
    return PersistedModifyResponse(
        request_id=request.request_id,
        base_revision=request.base_revision,
        result_revision=updated.version,
        graph=updated,
        applied_patch=result.patch,
        evidence=result.evidence,
        warnings=[
            *graph_warnings(updated),
            *result.warnings,
        ],
        metrics=ResponseMetrics(
            provider=result.provider,
            model=result.model,
            attempts=result.attempts,
            model_calls=result.model_calls,
            cache_status=result.cache_status,
            latency_ms=int((perf_counter() - started) * 1000),
        ),
    )


@router.get("/processes/{process_id}/revisions", response_model=list[RevisionResponse])
def list_revisions(
    process_id: str,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> list[RevisionResponse]:
    _authorize_process(repository, process_id, user, ProjectRole.VIEWER)
    return [
        _revision_response(revision)
        for revision in repository.list_revisions(process_id, user_id=user.user_id)
    ]


@router.get(
    "/processes/{process_id}/revisions/{revision_no}",
    response_model=RevisionDetailResponse,
)
def get_revision(
    process_id: str,
    revision_no: int,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> RevisionDetailResponse:
    _authorize_process(repository, process_id, user, ProjectRole.VIEWER)
    revision = repository.require_revision(process_id, revision_no)
    return RevisionDetailResponse(
        **_revision_response(revision).model_dump(),
        process_id=process_id,
        graph=GraphDocument.model_validate(revision.graph_json),
    )


@router.get(
    "/processes/{process_id}/releases/{release_no}",
    response_model=RevisionDetailResponse,
)
def get_release(
    process_id: str,
    release_no: int,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> RevisionDetailResponse:
    _authorize_process(repository, process_id, user, ProjectRole.VIEWER)
    revision = repository.require_release(process_id, release_no)
    return RevisionDetailResponse(
        **_revision_response(revision).model_dump(),
        process_id=process_id,
        graph=GraphDocument.model_validate(revision.graph_json),
    )


@router.post("/processes/{process_id}/releases", response_model=ReleaseResponse, status_code=201)
def create_release(
    process_id: str,
    request: ReleaseCreate,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> ReleaseResponse:
    process = _authorize_process(repository, process_id, user, ProjectRole.CONSULTANT_APPROVER)
    project = repository.require_project(process.project_id, user_id=user.user_id)
    _validate_release_graph(
        repository, project, process, repository.current_graph(process), request.base_revision
    )
    revision = repository.publish_release(
        process=process, revision_no=request.base_revision, user_id=user.user_id
    )
    return ReleaseResponse(
        process_id=process.id,
        revision_no=revision.revision_no,
        release_no=revision.release_no or 0,
        lifecycle_state=revision.lifecycle_state,
    )


@router.post(
    "/processes/{process_id}/drafts",
    response_model=RevisionDetailResponse,
    status_code=201,
)
def create_draft(
    process_id: str,
    request: DraftCreate,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> RevisionDetailResponse:
    process = _authorize_process(repository, process_id, user, ProjectRole.EDITOR)
    revision = repository.create_draft_from_revision(
        process=process,
        source_revision_no=request.source_revision,
        user_id=user.user_id,
    )
    return RevisionDetailResponse(
        **_revision_response(revision).model_dump(),
        process_id=process_id,
        graph=GraphDocument.model_validate(revision.graph_json),
    )


@router.post(
    "/processes/{process_id}/gaps/{node_id}/decisions",
    response_model=GapDecisionResponse,
)
def decide_gap(
    process_id: str,
    node_id: str,
    request: GapDecisionCreate,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> GapDecisionResponse:
    process = _authorize_process(repository, process_id, user, ProjectRole.CONSULTANT_APPROVER)
    repository.ensure_current_revision(process, request.base_revision)
    current_graph = repository.current_graph(process)
    node = next((item for item in current_graph.nodes if item.id == node_id), None)
    if node is None:
        raise FlowchartError(
            "NODE_NOT_FOUND", "目标节点不存在。", status_code=404, details={"node_id": node_id}
        )

    from_status = node.sap.gap.status
    to_status = GapStatus(request.to_status)
    allowed = {
        GapStatus.CANDIDATE: {GapStatus.CONFIRMED, GapStatus.REJECTED},
        GapStatus.CONFIRMED: {GapStatus.RESOLVED},
    }
    if to_status not in allowed.get(from_status, set()):
        raise FlowchartError(
            "GAP_INVALID_TRANSITION",
            "GAP 状态转换不符合候选、确认、解决的生命周期。",
            status_code=409,
            details={"from_status": from_status, "to_status": to_status},
        )

    updated_gap = node.sap.gap.model_copy(update={"status": to_status})
    updated_sap = node.sap.model_copy(update={"gap": updated_gap})
    patch = LLMPatch(
        change_summary=f"顾问将 {node.label} 的 GAP 更新为 {to_status}。",
        operations=[
            UpdateNodeOperation(
                op="update_node", id=node.id, changes=NodeChanges(sap=updated_sap)
            )
        ],
    )
    updated_graph = apply_patch(current_graph, patch)
    decision = repository.save_gap_decision(
        process=process,
        base_revision=request.base_revision,
        graph=updated_graph,
        patch=patch,
        node_id=node.id,
        from_status=from_status,
        to_status=to_status,
        comment=request.comment,
        user_id=user.user_id,
    )
    return GapDecisionResponse(
        process_id=process.id,
        node_id=node.id,
        revision_no=updated_graph.version,
        from_status=decision.from_status,
        to_status=decision.to_status,
        comment=decision.comment,
        decided_by=decision.decided_by,
        decided_at=decision.decided_at,
        graph=updated_graph,
    )


@router.post("/processes/{process_id}/exports")
def export_process(
    process_id: str,
    request: ExportRequest,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> Response:
    process = _authorize_process(repository, process_id, user, ProjectRole.VIEWER)
    project = repository.require_project(process.project_id, user_id=user.user_id)
    revision = repository.require_revision(process_id, request.revision_no)
    model = blueprint_document(project, process, revision)
    content, media_type, extension = render_export(model, request.format)
    unicode_filename, fallback_filename = export_filenames(
        process_name=process.name,
        process_id=process.id,
        revision_no=revision.revision_no,
        release_no=revision.release_no,
        extension=extension,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{fallback_filename}"; '
                f"filename*=UTF-8''{quote(unicode_filename)}"
            )
        },
    )


@router.post(
    "/processes/{process_id}/exports/jobs",
    response_model=ExportJobResponse,
    status_code=202,
)
def create_export_job(
    process_id: str,
    request: ExportRequest,
    background_tasks: BackgroundTasks,
    repository: BlueprintRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    user: UserContext = Depends(get_user_context),
) -> ExportJobResponse:
    _authorize_process(repository, process_id, user, ProjectRole.VIEWER)
    repository.require_revision(process_id, request.revision_no)
    job = repository.create_export_job(
        process_id=process_id,
        revision_no=request.revision_no,
        format=request.format,
        user_id=user.user_id,
    )
    if settings.export_execution_mode == "inline":
        background_tasks.add_task(
            process_export_job,
            job.id,
            repository.session.get_bind(),
            retention_hours=settings.export_retention_hours,
            stale_minutes=settings.export_stale_minutes,
            heartbeat_seconds=settings.export_lease_heartbeat_seconds,
        )
    return _export_job_response(job)


@router.get(
    "/processes/{process_id}/exports/jobs/{export_id}",
    response_model=ExportJobResponse,
)
def get_export_job(
    process_id: str,
    export_id: str,
    background_tasks: BackgroundTasks,
    repository: BlueprintRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    user: UserContext = Depends(get_user_context),
) -> ExportJobResponse:
    _authorize_process(repository, process_id, user, ProjectRole.VIEWER)
    job = repository.require_export_job(process_id, export_id)
    if settings.export_execution_mode == "inline" and job.status in {"pending", "running"}:
        background_tasks.add_task(
            process_export_job,
            job.id,
            repository.session.get_bind(),
            retention_hours=settings.export_retention_hours,
            stale_minutes=settings.export_stale_minutes,
            heartbeat_seconds=settings.export_lease_heartbeat_seconds,
        )
    return _export_job_response(job)


@router.get("/processes/{process_id}/exports/jobs/{export_id}/download")
def download_export_job(
    process_id: str,
    export_id: str,
    repository: BlueprintRepository = Depends(get_repository),
    user: UserContext = Depends(get_user_context),
) -> Response:
    _authorize_process(repository, process_id, user, ProjectRole.VIEWER)
    job = repository.require_export_job(process_id, export_id)
    if job.status == "expired":
        raise FlowchartError(
            "EXPORT_EXPIRED",
            "导出文件已过期，请重新生成。",
            status_code=410,
            details={"export_id": export_id},
        )
    if job.status == "failed":
        raise FlowchartError(
            job.error_code or "EXPORT_RENDER_FAILED",
            job.error_message or "蓝图渲染失败，请稍后重试。",
            status_code=409,
            details={"export_id": export_id},
        )
    if job.status != "completed" or job.content is None:
        raise FlowchartError(
            "EXPORT_NOT_READY",
            "导出任务尚未完成。",
            status_code=409,
            details={"export_id": export_id, "status": job.status},
        )
    return Response(
        content=job.content,
        media_type=job.media_type or "application/octet-stream",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{job.fallback_filename or "SAP-Blueprint"}"; '
                f"filename*=UTF-8''{quote(job.filename or 'SAP-Blueprint')}"
            )
        },
    )


def _export_job_response(job: ExportJobRecord) -> ExportJobResponse:
    download_url = (
        f"/api/v1/processes/{job.process_id}/exports/jobs/{job.id}/download"
        if job.status == "completed"
        else None
    )
    return ExportJobResponse(
        export_id=job.id,
        process_id=job.process_id,
        revision_no=job.revision_no,
        format=job.format,
        status=job.status,
        attempt_count=job.attempt_count,
        filename=job.filename,
        content_length=job.content_length,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        expires_at=job.expires_at,
        download_url=download_url,
    )


def _project_response(project: ProjectRecord, current_role: ProjectRole) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        customer_name=project.customer_name,
        sap_context=SapContext.model_validate(project.sap_context),
        external_model_enabled=project.external_model_enabled,
        current_role=current_role,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _project_audit_response(audit: ProjectAuditRecord) -> ProjectAuditResponse:
    return ProjectAuditResponse(
        id=audit.id,
        project_id=audit.project_id,
        action=audit.action,
        before_value=audit.before_value,
        after_value=audit.after_value,
        actor_user_id=audit.actor_user_id,
        created_at=audit.created_at,
    )


def _member_response(member: ProjectMemberRecord) -> ProjectMemberResponse:
    return ProjectMemberResponse(
        project_id=member.project_id,
        user_id=member.user_id,
        role=member.role,
        created_by=member.created_by,
        updated_by=member.updated_by,
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


def _authorize_project(
    repository: BlueprintRepository,
    project_id: str,
    user: UserContext,
    minimum: ProjectRole,
) -> ProjectRecord:
    project = repository.require_project(project_id, user_id=user.user_id)
    member = repository.require_project_member(project_id, user.user_id)
    require_role(ProjectRole(member.role), minimum)
    return project


def _authorize_process(
    repository: BlueprintRepository,
    process_id: str,
    user: UserContext,
    minimum: ProjectRole,
) -> ProcessRecord:
    process = repository.require_process(process_id, user_id=user.user_id)
    member = repository.require_project_member(process.project_id, user.user_id)
    require_role(ProjectRole(member.role), minimum)
    return process


def _validate_gap_edit(current: GraphDocument, updated: GraphDocument) -> None:
    current_statuses = {node.id: node.sap.gap.status for node in current.nodes}
    invalid: list[str] = []
    for node in updated.nodes:
        previous = current_statuses.get(node.id, GapStatus.NONE)
        next_status = node.sap.gap.status
        if previous == next_status:
            continue
        if previous == GapStatus.NONE and next_status == GapStatus.CANDIDATE:
            continue
        invalid.append(f"{node.label}: {previous} -> {next_status}")
    if invalid:
        raise FlowchartError(
            "GAP_DECISION_REQUIRED",
            "GAP 状态只能通过顾问决策接口变更。",
            status_code=409,
            details={"changes": invalid},
        )


def _validate_release_graph(
    repository: BlueprintRepository,
    project: ProjectRecord,
    process: ProcessRecord,
    graph: GraphDocument,
    revision_no: int,
) -> None:
    project_context = SapContext.model_validate(project.sap_context)
    required_values = {
        "project_name": project.name,
        "process_name": process.name,
        "graph_title": graph.title,
        "module": graph.module,
        "process_scope": graph.process_scope,
        "project_sap_edition": project_context.edition,
        "project_sap_release": project_context.release,
        "graph_sap_edition": graph.sap_context.edition,
        "graph_sap_release": graph.sap_context.release,
        "graph_sap_deployment": graph.sap_context.deployment,
        "graph_sap_country": graph.sap_context.country,
    }
    missing_fields = [
        field for field, value in required_values.items() if not str(value).strip()
    ]
    context_mismatch: list[str] = []
    if graph.version != revision_no:
        context_mismatch.append("revision_no")
    if graph.module != process.module:
        context_mismatch.append("module")
    if graph.process_scope != process.process_scope:
        context_mismatch.append("process_scope")
    if not graph.nodes:
        context_mismatch.append("nodes")
    if not any(node.type.value == "start" for node in graph.nodes):
        context_mismatch.append("start_node")
    if not any(node.type.value == "end" for node in graph.nodes):
        context_mismatch.append("end_node")

    invalid_verified: list[str] = []
    invalid_gap_decisions: list[str] = []
    latest_decisions = repository.latest_gap_decisions(process.id, revision_no)
    for node in graph.nodes:
        for item in [*node.sap.tcodes, *node.sap.fiori_apps, *node.sap.configuration_points]:
            if str(item.status) == "verified" and not item.evidence_ref:
                invalid_verified.append(node.label)
        gap_status = node.sap.gap.status
        if gap_status in {GapStatus.CONFIRMED, GapStatus.REJECTED, GapStatus.RESOLVED}:
            latest = latest_decisions.get(node.id)
            if latest is None or latest.to_status != gap_status:
                invalid_gap_decisions.append(node.label)
            if gap_status == GapStatus.RESOLVED and not repository.has_gap_decision(
                process_id=process.id,
                node_id=node.id,
                to_status=GapStatus.CONFIRMED,
                revision_no=revision_no,
            ):
                invalid_gap_decisions.append(f"{node.label}（缺少 confirmed 审计）")
        if gap_status == GapStatus.CONFIRMED and not node.sap.gap.evidence_refs:
            invalid_gap_decisions.append(f"{node.label}（缺少 GAP 证据）")

    if missing_fields or context_mismatch or invalid_verified or invalid_gap_decisions:
        raise FlowchartError(
            "RELEASE_PREFLIGHT_FAILED",
            "发布前检查未通过，请补充必填字段、SAP 证据并完成 GAP 决策审计。",
            status_code=422,
            details={
                "missing_fields": missing_fields,
                "context_mismatch": context_mismatch,
                "verified_without_evidence": invalid_verified,
                "gap_without_decision_audit": invalid_gap_decisions,
            },
        )


def _process_summary(process: ProcessRecord) -> ProcessSummary:
    return ProcessSummary(
        id=process.id,
        project_id=process.project_id,
        name=process.name,
        module=process.module,
        process_scope=process.process_scope,
        status=process.status,
        current_revision=process.current_revision,
        latest_release_no=process.latest_release_no,
        created_at=process.created_at,
        updated_at=process.updated_at,
    )


def _process_detail(process: ProcessRecord, graph: GraphDocument) -> ProcessDetail:
    return ProcessDetail(**_process_summary(process).model_dump(), graph=graph)


def _revision_response(revision: ProcessRevisionRecord) -> RevisionResponse:
    return RevisionResponse(
        revision_no=revision.revision_no,
        release_no=revision.release_no,
        lifecycle_state=revision.lifecycle_state,
        schema_version=revision.schema_version,
        created_by=revision.created_by,
        created_at=revision.created_at,
    )
