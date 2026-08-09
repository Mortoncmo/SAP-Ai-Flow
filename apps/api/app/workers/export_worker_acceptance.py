import json
from time import monotonic, sleep

from sqlalchemy import delete

from app.core.config import get_settings
from app.db.database import Database
from app.db.models import (
    ExportJobRecord,
    ProcessRecord,
    ProcessRevisionRecord,
    ProjectMemberRecord,
    ProjectRecord,
)
from app.db.repository import BlueprintRepository
from app.graph.ids import new_id
from app.models.graph import Edge, GraphDocument, Node, NodeType, SapContext, Swimlane


def main() -> int:
    settings = get_settings()
    if settings.export_execution_mode != "worker":
        raise RuntimeError("Export worker acceptance requires EXPORT_EXECUTION_MODE=worker")

    database = Database(settings.database_url, create_schema=False)
    user_id = "ci-export-worker"
    project_id: str | None = None
    process_id: str | None = None
    export_id: str | None = None
    try:
        with database.session_factory() as session:
            repository = BlueprintRepository(session)
            project = repository.create_project(
                name="Export Worker Acceptance",
                customer_name=None,
                sap_context=SapContext(),
                user_id=user_id,
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
            job = repository.create_export_job(
                process_id=process.id,
                revision_no=0,
                format="markdown",
                user_id=user_id,
            )
            export_id = job.id

        deadline = monotonic() + 30
        final: ExportJobRecord | None = None
        while monotonic() < deadline:
            with database.session_factory() as session:
                final = session.get(ExportJobRecord, export_id)
                if final is not None and final.status in {"completed", "failed"}:
                    break
            sleep(0.25)

        if final is None or final.status != "completed":
            raise RuntimeError(
                f"Export worker did not complete the acceptance job: {getattr(final, 'status', None)}"
            )
        if final.attempt_count != 1 or final.claim_token is not None:
            raise RuntimeError(
                "Export worker acceptance expected one fenced attempt and a released lease"
            )
        if final.content is None or final.content_length != len(final.content):
            raise RuntimeError("Export worker acceptance produced no durable content")
        rendered = final.content.decode("utf-8")
        if "# Export Worker Acceptance" not in rendered or "## 3. 流程步骤" not in rendered:
            raise RuntimeError("Export worker acceptance produced unexpected Markdown")

        print(
            json.dumps(
                {
                    "status": "passed",
                    "database_backend": database.engine.url.get_backend_name(),
                    "export_execution": settings.export_execution_mode,
                    "attempt_count": final.attempt_count,
                    "content_length": final.content_length,
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        if project_id is not None:
            with database.session_factory() as session:
                if export_id is not None:
                    session.execute(delete(ExportJobRecord).where(ExportJobRecord.id == export_id))
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


if __name__ == "__main__":
    raise SystemExit(main())
