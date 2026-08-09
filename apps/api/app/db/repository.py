from datetime import UTC, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import FlowchartError
from app.db.models import (
    ChangeLogRecord,
    ExportJobRecord,
    GapDecisionRecord,
    ProcessRecord,
    ProcessRevisionRecord,
    ProjectAuditRecord,
    ProjectMemberRecord,
    ProjectRecord,
    utc_now,
)
from app.graph.ids import new_id
from app.models.graph import GraphDocument, SapContext
from app.models.patch import LLMPatch
from app.security.redaction import redact_log_text, redact_log_value


class BlueprintRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_project(
        self,
        *,
        name: str,
        customer_name: str | None,
        sap_context: SapContext,
        user_id: str,
        external_model_enabled: bool = False,
    ) -> ProjectRecord:
        project = ProjectRecord(
            id=new_id("project"),
            name=name,
            customer_name=customer_name,
            sap_context=sap_context.model_dump(mode="json"),
            external_model_enabled=external_model_enabled,
            created_by=user_id,
        )
        member = ProjectMemberRecord(
            project_id=project.id,
            user_id=user_id,
            role="project_admin",
            created_by=user_id,
            updated_by=user_id,
        )
        self.session.add(project)
        self._flush()
        self.session.add(member)
        self._commit()
        return project

    def update_project_settings(
        self,
        *,
        project: ProjectRecord,
        external_model_enabled: bool,
        actor_user_id: str,
    ) -> ProjectRecord:
        before = {"external_model_enabled": project.external_model_enabled}
        after = {"external_model_enabled": external_model_enabled}
        if before == after:
            return project
        project.external_model_enabled = external_model_enabled
        project.updated_at = utc_now()
        audit = ProjectAuditRecord(
            id=new_id("project-audit"),
            project_id=project.id,
            action="external_model_policy_updated",
            before_value=before,
            after_value=after,
            actor_user_id=actor_user_id,
        )
        self.session.add(audit)
        self._commit()
        return project

    def list_project_audits(self, project_id: str) -> list[ProjectAuditRecord]:
        return list(
            self.session.scalars(
                select(ProjectAuditRecord)
                .where(ProjectAuditRecord.project_id == project_id)
                .order_by(ProjectAuditRecord.created_at.desc(), ProjectAuditRecord.id.desc())
            )
        )

    def list_projects(self, *, user_id: str) -> list[ProjectRecord]:
        self._backfill_legacy_owner_memberships(user_id)
        query = (
            select(ProjectRecord)
            .join(ProjectMemberRecord, ProjectMemberRecord.project_id == ProjectRecord.id)
            .where(ProjectMemberRecord.user_id == user_id)
            .order_by(ProjectRecord.created_at)
        )
        return list(self.session.scalars(query))

    def require_project(self, project_id: str, *, user_id: str | None = None) -> ProjectRecord:
        project = self.session.get(ProjectRecord, project_id)
        if project is None:
            raise FlowchartError(
                "PROJECT_NOT_FOUND", "项目不存在。", status_code=404, details={"project_id": project_id}
            )
        if user_id is not None:
            self.require_project_member(project_id, user_id)
        return project

    def require_project_member(self, project_id: str, user_id: str) -> ProjectMemberRecord:
        project = self.session.get(ProjectRecord, project_id)
        if project is None:
            raise FlowchartError(
                "PROJECT_NOT_FOUND", "项目不存在。", status_code=404, details={"project_id": project_id}
            )
        member = self.session.scalar(
            select(ProjectMemberRecord).where(
                ProjectMemberRecord.project_id == project_id,
                ProjectMemberRecord.user_id == user_id,
            )
        )
        if member is None and project.created_by == user_id:
            member_count = self.session.scalar(
                select(func.count())
                .select_from(ProjectMemberRecord)
                .where(ProjectMemberRecord.project_id == project_id)
            )
            if not member_count:
                member = ProjectMemberRecord(
                    project_id=project_id,
                    user_id=user_id,
                    role="project_admin",
                    created_by=user_id,
                    updated_by=user_id,
                )
                self.session.add(member)
                self._commit()
        if member is None:
            raise FlowchartError(
                "PROJECT_NOT_FOUND", "项目不存在。", status_code=404, details={"project_id": project_id}
            )
        return member

    def _backfill_legacy_owner_memberships(self, user_id: str) -> None:
        legacy_projects = self.session.scalars(
            select(ProjectRecord)
            .outerjoin(
                ProjectMemberRecord,
                ProjectMemberRecord.project_id == ProjectRecord.id,
            )
            .where(
                ProjectRecord.created_by == user_id,
                ProjectMemberRecord.project_id.is_(None),
            )
        )
        members = [
            ProjectMemberRecord(
                project_id=project.id,
                user_id=user_id,
                role="project_admin",
                created_by=user_id,
                updated_by=user_id,
            )
            for project in legacy_projects
        ]
        if members:
            self.session.add_all(members)
            self._commit()

    def list_project_members(self, project_id: str) -> list[ProjectMemberRecord]:
        self.require_project(project_id)
        query = (
            select(ProjectMemberRecord)
            .where(ProjectMemberRecord.project_id == project_id)
            .order_by(ProjectMemberRecord.created_at, ProjectMemberRecord.user_id)
        )
        return list(self.session.scalars(query))

    def add_project_member(
        self, *, project_id: str, user_id: str, role: str, actor_user_id: str
    ) -> ProjectMemberRecord:
        self.require_project(project_id)
        if self.session.get(ProjectMemberRecord, (project_id, user_id)) is not None:
            raise FlowchartError(
                "PROJECT_MEMBER_EXISTS",
                "该用户已经是项目成员。",
                status_code=409,
                details={"project_id": project_id, "user_id": user_id},
            )
        member = ProjectMemberRecord(
            project_id=project_id,
            user_id=user_id,
            role=role,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self.session.add(member)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise FlowchartError(
                "PROJECT_MEMBER_EXISTS",
                "该用户已经是项目成员。",
                status_code=409,
                details={"project_id": project_id, "user_id": user_id},
            ) from exc
        except SQLAlchemyError as exc:
            self.session.rollback()
            self._raise_database_write_failed(exc)
        return member

    def update_project_member(
        self, *, project_id: str, user_id: str, role: str, actor_user_id: str
    ) -> ProjectMemberRecord:
        member = self.require_project_member(project_id, user_id)
        if member.role == "project_admin" and role != "project_admin":
            self._ensure_another_project_admin(project_id, user_id)
        member.role = role
        member.updated_by = actor_user_id
        member.updated_at = utc_now()
        self._commit()
        return member

    def remove_project_member(
        self, *, project_id: str, user_id: str, actor_user_id: str
    ) -> None:
        member = self.require_project_member(project_id, user_id)
        if member.role == "project_admin":
            self._ensure_another_project_admin(project_id, user_id)
        self.session.delete(member)
        self._commit()

    def _ensure_another_project_admin(self, project_id: str, excluded_user_id: str) -> None:
        count = self.session.scalar(
            select(func.count())
            .select_from(ProjectMemberRecord)
            .where(
                ProjectMemberRecord.project_id == project_id,
                ProjectMemberRecord.role == "project_admin",
                ProjectMemberRecord.user_id != excluded_user_id,
            )
        )
        if not count:
            raise FlowchartError(
                "LAST_PROJECT_ADMIN",
                "项目必须至少保留一名项目管理员。",
                status_code=409,
                details={"project_id": project_id, "user_id": excluded_user_id},
            )

    def create_process(
        self,
        *,
        project: ProjectRecord,
        name: str,
        module: str,
        process_scope: str,
        initial_graph: GraphDocument | None,
        user_id: str,
    ) -> tuple[ProcessRecord, ProcessRevisionRecord]:
        graph = initial_graph or GraphDocument(
            graph_id=new_id("graph"),
            title=name,
            module=module,
            process_scope=process_scope,
            sap_context=SapContext.model_validate(project.sap_context),
        )
        process = ProcessRecord(
            id=new_id("process"),
            project_id=project.id,
            name=name,
            module=graph.module,
            process_scope=graph.process_scope,
            status="DRAFT",
            current_revision=graph.version,
            created_by=user_id,
        )
        revision = ProcessRevisionRecord(
            id=new_id("revision"),
            process_id=process.id,
            revision_no=graph.version,
            lifecycle_state="DRAFT",
            schema_version=graph.schema_version,
            graph_json=graph.model_dump(mode="json"),
            created_by=user_id,
        )
        self.session.add_all([process, revision])
        self._commit()
        return process, revision

    def list_processes(self, project_id: str, *, user_id: str) -> list[ProcessRecord]:
        self.require_project(project_id, user_id=user_id)
        query = (
            select(ProcessRecord)
            .where(ProcessRecord.project_id == project_id)
            .order_by(ProcessRecord.created_at)
        )
        return list(self.session.scalars(query))

    def require_process(self, process_id: str, *, user_id: str | None = None) -> ProcessRecord:
        process = self.session.get(ProcessRecord, process_id)
        if process is None:
            raise FlowchartError(
                "PROCESS_NOT_FOUND", "流程不存在。", status_code=404, details={"process_id": process_id}
            )
        if user_id is not None:
            self.require_project(process.project_id, user_id=user_id)
        return process

    def require_revision(self, process_id: str, revision_no: int) -> ProcessRevisionRecord:
        query = select(ProcessRevisionRecord).where(
            ProcessRevisionRecord.process_id == process_id,
            ProcessRevisionRecord.revision_no == revision_no,
        )
        revision = self.session.scalar(query)
        if revision is None:
            raise FlowchartError(
                "REVISION_NOT_FOUND",
                "流程修订不存在。",
                status_code=404,
                details={"process_id": process_id, "revision_no": revision_no},
            )
        return revision

    def require_release(self, process_id: str, release_no: int) -> ProcessRevisionRecord:
        query = select(ProcessRevisionRecord).where(
            ProcessRevisionRecord.process_id == process_id,
            ProcessRevisionRecord.release_no == release_no,
        )
        revision = self.session.scalar(query)
        if revision is None:
            raise FlowchartError(
                "RELEASE_NOT_FOUND",
                "流程发布版本不存在。",
                status_code=404,
                details={"process_id": process_id, "release_no": release_no},
            )
        return revision

    def current_graph(self, process: ProcessRecord) -> GraphDocument:
        revision = self.require_revision(process.id, process.current_revision)
        return GraphDocument.model_validate(revision.graph_json)

    def latest_gap_decisions(
        self, process_id: str, revision_no: int
    ) -> dict[str, GapDecisionRecord]:
        rows = self.session.scalars(
            select(GapDecisionRecord)
            .where(
                GapDecisionRecord.process_id == process_id,
                GapDecisionRecord.revision_no <= revision_no,
            )
            .order_by(
                GapDecisionRecord.node_id,
                GapDecisionRecord.revision_no.desc(),
                GapDecisionRecord.decided_at.desc(),
            )
        )
        latest: dict[str, GapDecisionRecord] = {}
        for decision in rows:
            latest.setdefault(decision.node_id, decision)
        return latest

    def has_gap_decision(
        self,
        *,
        process_id: str,
        node_id: str,
        to_status: str,
        revision_no: int,
    ) -> bool:
        decision_id = self.session.scalar(
            select(GapDecisionRecord.id)
            .where(
                GapDecisionRecord.process_id == process_id,
                GapDecisionRecord.node_id == node_id,
                GapDecisionRecord.to_status == to_status,
                GapDecisionRecord.revision_no <= revision_no,
            )
            .limit(1)
        )
        return decision_id is not None

    def list_revisions(self, process_id: str, *, user_id: str | None = None) -> list[ProcessRevisionRecord]:
        self.require_process(process_id, user_id=user_id)
        query = (
            select(ProcessRevisionRecord)
            .where(ProcessRevisionRecord.process_id == process_id)
            .order_by(ProcessRevisionRecord.revision_no.desc())
        )
        return list(self.session.scalars(query))

    def save_modified_graph(
        self,
        *,
        process: ProcessRecord,
        base_revision: int,
        graph: GraphDocument,
        patch: LLMPatch,
        user_prompt: str,
        provider: str,
        model: str,
        evidence_refs: list[str],
        user_id: str,
    ) -> ProcessRevisionRecord:
        self.ensure_current_revision(process, base_revision)
        revision = ProcessRevisionRecord(
            id=new_id("revision"),
            process_id=process.id,
            revision_no=graph.version,
            lifecycle_state="DRAFT",
            schema_version=graph.schema_version,
            graph_json=graph.model_dump(mode="json"),
            created_by=user_id,
        )
        change = ChangeLogRecord(
            id=new_id("change"),
            process_id=process.id,
            base_revision=base_revision,
            result_revision=graph.version,
            user_prompt=redact_log_text(user_prompt),
            normalized_patch=redact_log_value(patch.model_dump(mode="json")),
            decision_summary=redact_log_text(patch.change_summary, max_length=500),
            evidence_refs=evidence_refs,
            provider=provider,
            model=model,
            created_by=user_id,
        )
        process.current_revision = graph.version
        process.status = "DRAFT"
        process.updated_at = utc_now()
        self.session.add_all([revision, change])
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            self.raise_revision_conflict(process, base_revision, cause=exc)
        except SQLAlchemyError as exc:
            self.session.rollback()
            self._raise_database_write_failed(exc)
        return revision

    def save_manual_graph(
        self,
        *,
        process: ProcessRecord,
        base_revision: int,
        graph: GraphDocument,
        summary: str,
        user_id: str,
    ) -> ProcessRevisionRecord:
        self.ensure_current_revision(process, base_revision)
        if graph.version != base_revision + 1:
            raise FlowchartError(
                "INVALID_RESULT_REVISION",
                "手工保存的图版本必须比基准修订号大 1。",
                status_code=422,
                details={"base_revision": base_revision, "graph_version": graph.version},
            )
        revision = ProcessRevisionRecord(
            id=new_id("revision"),
            process_id=process.id,
            revision_no=graph.version,
            lifecycle_state="DRAFT",
            schema_version=graph.schema_version,
            graph_json=graph.model_dump(mode="json"),
            created_by=user_id,
        )
        change = ChangeLogRecord(
            id=new_id("change"),
            process_id=process.id,
            base_revision=base_revision,
            result_revision=graph.version,
            user_prompt="画布手工保存",
            normalized_patch={"kind": "manual_save"},
            decision_summary=redact_log_text(summary, max_length=500),
            evidence_refs=[],
            provider="human",
            model="manual",
            created_by=user_id,
        )
        process.current_revision = graph.version
        process.status = "DRAFT"
        process.updated_at = utc_now()
        self.session.add_all([revision, change])
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            self.raise_revision_conflict(process, base_revision, cause=exc)
        except SQLAlchemyError as exc:
            self.session.rollback()
            self._raise_database_write_failed(exc)
        return revision

    def publish_release(
        self, *, process: ProcessRecord, revision_no: int, user_id: str
    ) -> ProcessRevisionRecord:
        self.ensure_current_revision(process, revision_no)
        revision = self.require_revision(process.id, revision_no)
        if revision.release_no is not None:
            raise FlowchartError(
                "REVISION_ALREADY_RELEASED",
                "该修订已经发布。",
                status_code=409,
                details={"release_no": revision.release_no},
            )
        release_no = (process.latest_release_no or 0) + 1
        revision.release_no = release_no
        revision.lifecycle_state = "APPROVED"
        process.latest_release_no = release_no
        process.status = "APPROVED"
        process.updated_at = utc_now()
        self._commit()
        return revision

    def create_draft_from_revision(
        self,
        *,
        process: ProcessRecord,
        source_revision_no: int,
        user_id: str,
    ) -> ProcessRevisionRecord:
        self.ensure_current_revision(process, source_revision_no)
        source = self.require_revision(process.id, source_revision_no)
        if source.release_no is None:
            raise FlowchartError(
                "SOURCE_NOT_RELEASED",
                "只有已发布修订才能复制为新草稿。",
                status_code=409,
                details={"revision_no": source_revision_no},
            )
        graph = GraphDocument.model_validate(source.graph_json).model_copy(
            deep=True, update={"version": source_revision_no + 1}
        )
        revision = ProcessRevisionRecord(
            id=new_id("revision"),
            process_id=process.id,
            revision_no=graph.version,
            lifecycle_state="DRAFT",
            schema_version=graph.schema_version,
            graph_json=graph.model_dump(mode="json"),
            created_by=user_id,
        )
        change = ChangeLogRecord(
            id=new_id("change"),
            process_id=process.id,
            base_revision=source_revision_no,
            result_revision=graph.version,
            user_prompt="从发布版本创建新草稿",
            normalized_patch={"kind": "draft_from_release", "source_revision": source_revision_no},
            decision_summary=f"从发布版本 {source.release_no} 创建草稿修订 {graph.version}。",
            evidence_refs=[],
            provider="human",
            model="manual",
            created_by=user_id,
        )
        process.current_revision = graph.version
        process.status = "DRAFT"
        process.updated_at = utc_now()
        self.session.add_all([revision, change])
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            self.raise_revision_conflict(process, source_revision_no, cause=exc)
        except SQLAlchemyError as exc:
            self.session.rollback()
            self._raise_database_write_failed(exc)
        return revision

    def save_gap_decision(
        self,
        *,
        process: ProcessRecord,
        base_revision: int,
        graph: GraphDocument,
        patch: LLMPatch,
        node_id: str,
        from_status: str,
        to_status: str,
        comment: str,
        user_id: str,
    ) -> GapDecisionRecord:
        self.ensure_current_revision(process, base_revision)
        revision = ProcessRevisionRecord(
            id=new_id("revision"),
            process_id=process.id,
            revision_no=graph.version,
            lifecycle_state="DRAFT",
            schema_version=graph.schema_version,
            graph_json=graph.model_dump(mode="json"),
            created_by=user_id,
        )
        change = ChangeLogRecord(
            id=new_id("change"),
            process_id=process.id,
            base_revision=base_revision,
            result_revision=graph.version,
            user_prompt=redact_log_text(f"GAP 决策：{comment}"),
            normalized_patch=redact_log_value(patch.model_dump(mode="json")),
            decision_summary=f"顾问将节点 {node_id} 的 GAP 从 {from_status} 更新为 {to_status}。",
            evidence_refs=[],
            provider="human",
            model="manual",
            created_by=user_id,
        )
        decision = GapDecisionRecord(
            id=new_id("gap-decision"),
            process_id=process.id,
            node_id=node_id,
            revision_no=graph.version,
            from_status=from_status,
            to_status=to_status,
            comment=redact_log_text(comment, max_length=1000),
            decided_by=user_id,
        )
        process.current_revision = graph.version
        process.status = "DRAFT"
        process.updated_at = utc_now()
        self.session.add_all([revision, change, decision])
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            self.raise_revision_conflict(process, base_revision, cause=exc)
        except SQLAlchemyError as exc:
            self.session.rollback()
            self._raise_database_write_failed(exc)
        return decision

    def create_export_job(
        self,
        *,
        process_id: str,
        revision_no: int,
        format: str,
        user_id: str,
    ) -> ExportJobRecord:
        self.expire_export_jobs()
        job = ExportJobRecord(
            id=new_id("export"),
            process_id=process_id,
            revision_no=revision_no,
            format=format,
            status="pending",
            created_by=user_id,
        )
        self.session.add(job)
        self._commit()
        return job

    def require_export_job(self, process_id: str, export_id: str) -> ExportJobRecord:
        job = self.require_export_job_unscoped(export_id)
        if job.process_id != process_id:
            raise FlowchartError(
                "EXPORT_NOT_FOUND",
                "导出任务不存在。",
                status_code=404,
                details={"export_id": export_id},
            )
        if job.status == "completed" and self._export_job_expired(job):
            job.status = "expired"
            job.content = None
            job.content_length = None
            self._commit()
        return job

    def require_export_job_unscoped(self, export_id: str) -> ExportJobRecord:
        job = self.session.get(ExportJobRecord, export_id)
        if job is None:
            raise FlowchartError(
                "EXPORT_NOT_FOUND",
                "导出任务不存在。",
                status_code=404,
                details={"export_id": export_id},
            )
        return job

    def list_export_job_candidates(self, *, stale_minutes: int, limit: int) -> list[str]:
        stale_before = utc_now() - timedelta(minutes=stale_minutes)
        return list(
            self.session.scalars(
                select(ExportJobRecord.id)
                .where(
                    or_(
                        ExportJobRecord.status == "pending",
                        and_(
                            ExportJobRecord.status == "running",
                            ExportJobRecord.started_at < stale_before,
                        ),
                    )
                )
                .order_by(ExportJobRecord.created_at, ExportJobRecord.id)
                .limit(limit)
            )
        )

    def claim_export_job(self, export_id: str, *, stale_minutes: int) -> str | None:
        now = utc_now()
        stale_before = now - timedelta(minutes=stale_minutes)
        claim_token = new_id("export-claim")
        result = self.session.execute(
            update(ExportJobRecord)
            .where(
                ExportJobRecord.id == export_id,
                or_(
                    ExportJobRecord.status == "pending",
                    and_(
                        ExportJobRecord.status == "running",
                        ExportJobRecord.started_at < stale_before,
                    ),
                ),
            )
            .values(
                status="running",
                claim_token=claim_token,
                attempt_count=ExportJobRecord.attempt_count + 1,
                started_at=now,
                completed_at=None,
                expires_at=None,
                error_code=None,
                error_message=None,
            )
        )
        self._commit()
        return claim_token if result.rowcount else None

    def expire_export_jobs(self) -> None:
        self.session.execute(
            update(ExportJobRecord)
            .where(
                ExportJobRecord.status == "completed",
                ExportJobRecord.expires_at <= utc_now(),
            )
            .values(status="expired", content=None, content_length=None)
        )
        self._commit()

    def complete_export_job(
        self,
        *,
        export_id: str,
        claim_token: str,
        filename: str,
        fallback_filename: str,
        media_type: str,
        content: bytes,
        retention_hours: int,
    ) -> bool:
        completed_at = utc_now()
        result = self.session.execute(
            update(ExportJobRecord)
            .where(
                ExportJobRecord.id == export_id,
                ExportJobRecord.status == "running",
                ExportJobRecord.claim_token == claim_token,
            )
            .values(
                status="completed",
                claim_token=None,
                filename=filename,
                fallback_filename=fallback_filename,
                media_type=media_type,
                content=content,
                content_length=len(content),
                error_code=None,
                error_message=None,
                completed_at=completed_at,
                expires_at=completed_at + timedelta(hours=retention_hours),
            )
        )
        self._commit()
        return bool(result.rowcount)

    def fail_export_job(self, *, export_id: str, claim_token: str) -> bool:
        result = self.session.execute(
            update(ExportJobRecord)
            .where(
                ExportJobRecord.id == export_id,
                ExportJobRecord.status == "running",
                ExportJobRecord.claim_token == claim_token,
            )
            .values(
                status="failed",
                claim_token=None,
                content=None,
                content_length=None,
                error_code="EXPORT_RENDER_FAILED",
                error_message="蓝图渲染失败，请稍后重试。",
                completed_at=utc_now(),
            )
        )
        self._commit()
        return bool(result.rowcount)

    @staticmethod
    def _export_job_expired(job: ExportJobRecord) -> bool:
        if job.expires_at is None:
            return False
        expires_at = job.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= utc_now()

    def _flush(self) -> None:
        try:
            self.session.flush()
        except SQLAlchemyError as exc:
            self.session.rollback()
            self._raise_database_write_failed(exc)

    def _commit(self) -> None:
        try:
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            self._raise_database_write_failed(exc)

    @staticmethod
    def _raise_database_write_failed(cause: SQLAlchemyError) -> None:
        raise FlowchartError(
            "DATABASE_WRITE_FAILED",
            "数据库写入失败，未保存任何更改，请稍后重试。",
            status_code=503,
        ) from cause

    def ensure_current_revision(self, process: ProcessRecord, expected: int) -> None:
        if process.current_revision != expected:
            self.raise_revision_conflict(process, expected)

    @staticmethod
    def raise_revision_conflict(
        process: ProcessRecord, expected: int, *, cause: Exception | None = None
    ) -> None:
        error = FlowchartError(
            "REVISION_CONFLICT",
            "流程已被更新，请刷新后重试。",
            status_code=409,
            details={"expected_revision": expected, "current_revision": process.current_revision},
        )
        if cause is not None:
            raise error from cause
        raise error
