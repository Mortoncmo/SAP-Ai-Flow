import json
from datetime import timedelta
from time import monotonic, sleep

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.database import Database
from app.db.models import (
    ExportJobRecord,
    ProcessRecord,
    ProcessRevisionRecord,
    ProjectMemberRecord,
    ProjectRecord,
    utc_now,
)
from app.db.repository import BlueprintRepository
from app.documents.artifact_store import build_artifact_store
from app.documents.export_service import load_export_artifact
from app.graph.ids import new_id
from app.models.graph import Edge, GraphDocument, Node, NodeType, SapContext, Swimlane

PARALLEL_JOB_COUNT = 12


def main() -> int:
    settings = get_settings()
    if settings.export_execution_mode != "worker":
        raise RuntimeError("Export worker acceptance requires EXPORT_EXECUTION_MODE=worker")

    database = Database(settings.database_url, create_schema=False)
    artifact_store = build_artifact_store(settings)
    user_id = "ci-export-worker"
    project_id: str | None = None
    process_id: str | None = None
    export_ids: list[str] = []
    stale_export_id: str | None = None
    stale_claim_token: str | None = None
    fresh_heartbeat_export_id: str | None = None
    fresh_heartbeat_claim_token: str | None = None
    try:
        with database.session_factory() as session:
            repository = BlueprintRepository(session)
            project = repository.create_project(
                name="Export Worker Acceptance",
                customer_name=None,
                sap_context=SapContext(),
                user_id=user_id,
                tenant_id="ci",
            )
            project_id = project.id
            graph = GraphDocument(
                graph_id=new_id("graph"),
                title="Export Worker Acceptance",
                nodes=[
                    Node(id="start", type=NodeType.START, label="开始", lane_id="owner"),
                    Node(id="end", type=NodeType.END, label="结束", lane_id="owner"),
                ],
                edges=[Edge(id="edge", source="start", target="end")],
                lanes=[Swimlane(id="owner", label="验收负责人")],
            )
            process, _revision = repository.create_process(
                project=project,
                name="Export Worker Acceptance",
                module="MM",
                process_scope="P2P",
                initial_graph=graph,
                user_id=user_id,
            )
            process_id = process.id

            now = utc_now()
            pending_jobs = [
                ExportJobRecord(
                    id=new_id("export"),
                    process_id=process.id,
                    revision_no=0,
                    format="markdown",
                    status="pending",
                    created_by=user_id,
                    created_at=now,
                )
                for _ in range(PARALLEL_JOB_COUNT)
            ]
            stale_claim_token = new_id("export-claim")
            stale_job = ExportJobRecord(
                id=new_id("export"),
                process_id=process.id,
                revision_no=0,
                format="markdown",
                status="running",
                claim_token=stale_claim_token,
                attempt_count=1,
                created_by=user_id,
                created_at=now,
                started_at=now - timedelta(minutes=settings.export_stale_minutes + 1),
                heartbeat_at=now - timedelta(minutes=settings.export_stale_minutes + 1),
            )
            fresh_heartbeat_claim_token = new_id("export-claim")
            fresh_heartbeat_job = ExportJobRecord(
                id=new_id("export"),
                process_id=process.id,
                revision_no=0,
                format="markdown",
                status="running",
                claim_token=fresh_heartbeat_claim_token,
                attempt_count=1,
                created_by=user_id,
                created_at=now - timedelta(minutes=settings.export_stale_minutes + 1),
                started_at=now - timedelta(minutes=settings.export_stale_minutes + 1),
                heartbeat_at=now,
            )
            fresh_heartbeat_export_id = fresh_heartbeat_job.id
            session.add_all([*pending_jobs, stale_job, fresh_heartbeat_job])
            session.commit()
            export_ids = [job.id for job in pending_jobs]
            stale_export_id = stale_job.id

        all_export_ids = [*export_ids, stale_export_id]
        final = _wait_for_jobs(database, all_export_ids)
        pending_final = [final[export_id] for export_id in export_ids]
        stale_final = final[stale_export_id]

        if any(job.status != "completed" for job in final.values()):
            statuses = {export_id: job.status for export_id, job in final.items()}
            raise RuntimeError(f"Export workers did not complete all acceptance jobs: {statuses}")
        if any(job.attempt_count != 1 or job.claim_token is not None for job in pending_final):
            raise RuntimeError("Parallel export jobs were not completed exactly once")
        if stale_final.attempt_count != 2 or stale_final.claim_token is not None:
            raise RuntimeError("Stale export job was not fenced and reclaimed exactly once")

        with database.session_factory() as session:
            repository = BlueprintRepository(session)
            fresh_heartbeat = repository.require_export_job_unscoped(
                fresh_heartbeat_export_id
            )
            if (
                fresh_heartbeat.status != "running"
                or fresh_heartbeat.attempt_count != 1
                or fresh_heartbeat.claim_token != fresh_heartbeat_claim_token
            ):
                raise RuntimeError("Fresh export heartbeat was incorrectly reclaimed")
            fresh_heartbeat_preserved = repository.fail_export_job(
                export_id=fresh_heartbeat_export_id,
                claim_token=fresh_heartbeat_claim_token,
            )
            if not fresh_heartbeat_preserved:
                raise RuntimeError("Fresh heartbeat acceptance task could not be finalized")

        total_content_length = 0
        for job in final.values():
            content = load_export_artifact(job, settings, artifact_store=artifact_store)
            if job.content_length != len(content):
                raise RuntimeError(f"Export worker produced no durable content for {job.id}")
            if settings.export_storage_backend != "database" and job.content is not None:
                raise RuntimeError(f"Export worker persisted database content for {job.id}")
            if job.artifact_backend != settings.export_storage_backend:
                raise RuntimeError(f"Export worker used an unexpected backend for {job.id}")
            rendered = content.decode("utf-8")
            if "# Export Worker Acceptance" not in rendered or "## 3. 流程步骤" not in rendered:
                raise RuntimeError(f"Export worker produced unexpected Markdown for {job.id}")
            total_content_length += job.content_length

        with database.session_factory() as session:
            repository = BlueprintRepository(session)
            stale_write_completed = repository.complete_export_job(
                export_id=stale_export_id,
                claim_token=stale_claim_token,
                filename="stale.md",
                fallback_filename="stale.md",
                media_type="text/markdown",
                content=b"stale",
                retention_hours=settings.export_retention_hours,
            )
            stale_write_failed = repository.fail_export_job(
                export_id=stale_export_id,
                claim_token=stale_claim_token,
            )
        if stale_write_completed or stale_write_failed:
            raise RuntimeError("A stale export lease overwrote the reclaimed worker result")

        print(
            json.dumps(
                {
                    "status": "passed",
                    "database_backend": database.engine.url.get_backend_name(),
                    "export_execution": settings.export_execution_mode,
                    "artifact_storage": settings.export_storage_backend,
                    "database_content_empty": all(job.content is None for job in final.values()),
                    "parallel_job_count": len(pending_final),
                    "exactly_once_job_count": sum(
                        job.attempt_count == 1 for job in pending_final
                    ),
                    "stale_attempt_count": stale_final.attempt_count,
                    "stale_write_rejected": True,
                    "fresh_heartbeat_preserved": True,
                    "content_length": total_content_length,
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        if project_id is not None:
            with database.session_factory() as session:
                artifact_keys = list(
                    session.scalars(
                        select(ExportJobRecord.artifact_key).where(
                            ExportJobRecord.process_id == process_id,
                            ExportJobRecord.artifact_key.is_not(None),
                        )
                    )
                )
                if artifact_store is not None:
                    for artifact_key in artifact_keys:
                        artifact_store.delete(artifact_key)
                if export_ids or stale_export_id is not None:
                    session.execute(
                        delete(ExportJobRecord).where(
                            ExportJobRecord.id.in_(
                                [
                                    *export_ids,
                                    *([stale_export_id] if stale_export_id else []),
                                    *(
                                        [fresh_heartbeat_export_id]
                                        if fresh_heartbeat_export_id
                                        else []
                                    ),
                                ]
                            )
                        )
                    )
                if process_id is not None:
                    session.execute(
                        delete(ProcessRevisionRecord).where(
                            ProcessRevisionRecord.process_id == process_id
                        )
                    )
                    session.execute(delete(ProcessRecord).where(ProcessRecord.id == process_id))
                session.execute(
                    delete(ProjectMemberRecord).where(
                        ProjectMemberRecord.project_id == project_id
                    )
                )
                session.execute(delete(ProjectRecord).where(ProjectRecord.id == project_id))
                session.commit()


def _wait_for_jobs(
    database: Database,
    export_ids: list[str],
) -> dict[str, ExportJobRecord]:
    deadline = monotonic() + 45
    final: dict[str, ExportJobRecord] = {}
    while monotonic() < deadline:
        with database.session_factory() as session:
            jobs = list(
                session.scalars(
                    select(ExportJobRecord).where(ExportJobRecord.id.in_(export_ids))
                )
            )
            final = {job.id: job for job in jobs}
            if len(final) == len(export_ids) and all(
                job.status in {"completed", "failed"} for job in final.values()
            ):
                return final
        sleep(0.25)
    statuses = {
        export_id: getattr(final.get(export_id), "status", "missing")
        for export_id in export_ids
    }
    raise RuntimeError(f"Timed out waiting for export worker acceptance jobs: {statuses}")


if __name__ == "__main__":
    raise SystemExit(main())
