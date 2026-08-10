import argparse
import json
from io import BytesIO
from time import monotonic, sleep
from zipfile import ZipFile, is_zipfile

from sqlalchemy import delete

from app.core.config import Settings, get_settings
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
from app.documents.artifact_store import ArtifactStore, build_artifact_store
from app.documents.export_service import load_export_artifact
from app.graph.ids import new_id
from app.models.graph import Edge, GraphDocument, Node, NodeType, Position, SapContext, Swimlane

LONG_DOCUMENT_NODE_COUNT = 80


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exercise export-worker recovery after an interrupted long document task"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")
    wait_parser = subparsers.add_parser("wait-running")
    wait_parser.add_argument("--export-id", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--export-id", required=True)
    args = parser.parse_args()

    settings = get_settings()
    database = Database(settings.database_url, create_schema=False)
    artifact_store = build_artifact_store(settings)
    _require_acceptance_environment(settings, database, artifact_store)

    if args.command == "prepare":
        report = prepare_interruption_job(database)
    elif args.command == "wait-running":
        report = wait_for_running_job(database, args.export_id)
    else:
        report = verify_recovered_job(database, settings, artifact_store, args.export_id)
    print(json.dumps(report, separators=(",", ":")))
    return 0


def _require_acceptance_environment(
    settings: Settings,
    database: Database,
    artifact_store: ArtifactStore | None,
) -> None:
    if settings.export_execution_mode != "worker":
        raise RuntimeError("Interruption acceptance requires worker export execution")
    if database.engine.url.get_backend_name() != "postgresql":
        raise RuntimeError("Interruption acceptance requires PostgreSQL")
    if artifact_store is None or artifact_store.backend == "database":
        raise RuntimeError("Interruption acceptance requires external artifact storage")


def prepare_interruption_job(database: Database) -> dict[str, object]:
    user_id = "ci-rolling-interruption"
    with database.session_factory() as session:
        repository = BlueprintRepository(session)
        project = repository.create_project(
            name="Rolling Interruption Acceptance",
            customer_name=None,
            sap_context=SapContext(),
            user_id=user_id,
            tenant_id="ci",
        )
        process, _revision = repository.create_process(
            project=project,
            name="Rolling Interruption Acceptance",
            module="MM",
            process_scope="P2P",
            initial_graph=long_document_graph(),
            user_id=user_id,
        )
        job = ExportJobRecord(
            id=new_id("export"),
            process_id=process.id,
            revision_no=0,
            format="docx",
            status="pending",
            created_by=user_id,
            created_at=utc_now(),
        )
        session.add(job)
        session.commit()
        return {
            "status": "prepared",
            "export_id": job.id,
            "node_count": LONG_DOCUMENT_NODE_COUNT,
        }


def wait_for_running_job(
    database: Database,
    export_id: str,
    *,
    timeout_seconds: float = 30,
) -> dict[str, object]:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        with database.session_factory() as session:
            job = BlueprintRepository(session).require_export_job_unscoped(export_id)
            heartbeat_advanced = bool(
                job.started_at
                and job.heartbeat_at
                and job.heartbeat_at > job.started_at
            )
            if (
                job.status == "running"
                and job.attempt_count == 1
                and job.claim_token
                and heartbeat_advanced
            ):
                return {
                    "status": "running",
                    "attempt_count": job.attempt_count,
                    "heartbeat_advanced": True,
                }
            if job.status in {"completed", "failed", "expired"}:
                raise RuntimeError(
                    f"Interruption task reached {job.status} before the worker was terminated"
                )
        sleep(0.25)
    raise RuntimeError("Timed out waiting for the interruption task heartbeat")


def verify_recovered_job(
    database: Database,
    settings: Settings,
    artifact_store: ArtifactStore,
    export_id: str,
    *,
    timeout_seconds: float = 90,
) -> dict[str, object]:
    deadline = monotonic() + timeout_seconds
    final: ExportJobRecord | None = None
    while monotonic() < deadline:
        with database.session_factory() as session:
            job = BlueprintRepository(session).require_export_job_unscoped(export_id)
            if job.status in {"completed", "failed", "expired"}:
                session.expunge(job)
                final = job
                break
        sleep(0.25)
    if final is None:
        raise RuntimeError("Timed out waiting for a replacement worker to finish the task")

    try:
        if final.status != "completed" or final.attempt_count != 2:
            raise RuntimeError(
                "Interrupted export was not completed exactly once by a replacement worker"
            )
        if final.claim_token is not None:
            raise RuntimeError("Recovered export retained an active lease")
        if final.content is not None or final.artifact_backend != artifact_store.backend:
            raise RuntimeError("Recovered export did not use external artifact storage")
        content = load_export_artifact(final, settings, artifact_store=artifact_store)
        if not is_zipfile(BytesIO(content)):
            raise RuntimeError("Recovered long-document artifact is not a valid DOCX archive")
        with ZipFile(BytesIO(content)) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")
        if "Rolling Interruption Acceptance" not in document_xml:
            raise RuntimeError("Recovered DOCX does not contain the acceptance document title")

        with database.session_factory() as session:
            repository = BlueprintRepository(session)
            revision = repository.require_revision(final.process_id, final.revision_no)
            node_count = len(GraphDocument.model_validate(revision.graph_json).nodes)
        if node_count != LONG_DOCUMENT_NODE_COUNT:
            raise RuntimeError("Recovered DOCX source graph is not the long-document fixture")

        return {
            "status": "passed",
            "database_backend": database.engine.url.get_backend_name(),
            "artifact_storage": artifact_store.backend,
            "long_document_node_count": node_count,
            "interrupted_attempt_count": final.attempt_count,
            "replacement_completed": True,
            "database_content_empty": final.content is None,
            "content_length": len(content),
        }
    finally:
        cleanup_interruption_job(database, artifact_store, final)


def cleanup_interruption_job(
    database: Database,
    artifact_store: ArtifactStore,
    job: ExportJobRecord,
) -> None:
    if job.artifact_key is not None:
        artifact_store.delete(job.artifact_key)
    with database.session_factory() as session:
        repository = BlueprintRepository(session)
        process = repository.require_process(job.process_id)
        project_id = process.project_id
        session.execute(delete(ExportJobRecord).where(ExportJobRecord.id == job.id))
        session.execute(
            delete(ProcessRevisionRecord).where(ProcessRevisionRecord.process_id == process.id)
        )
        session.execute(delete(ProcessRecord).where(ProcessRecord.id == process.id))
        session.execute(
            delete(ProjectMemberRecord).where(ProjectMemberRecord.project_id == project_id)
        )
        session.execute(delete(ProjectRecord).where(ProjectRecord.id == project_id))
        session.commit()


def long_document_graph() -> GraphDocument:
    lanes = [
        Swimlane(id=f"lane-{index}", label=f"Acceptance Lane {index + 1}")
        for index in range(4)
    ]
    nodes: list[Node] = []
    layout: dict[str, Position] = {}
    for index in range(LONG_DOCUMENT_NODE_COUNT):
        node_id = f"step-{index + 1}"
        if index == 0:
            node_type = NodeType.START
        elif index == LONG_DOCUMENT_NODE_COUNT - 1:
            node_type = NodeType.END
        else:
            node_type = NodeType.TASK
        nodes.append(
            Node(
                id=node_id,
                type=node_type,
                label=f"Long document step {index + 1}",
                description=(
                    "Representative procurement blueprint detail used to validate durable "
                    "worker recovery after an interrupted document render."
                ),
                lane_id=lanes[index % len(lanes)].id,
            )
        )
        layout[node_id] = Position(x=float((index % 10) * 180), y=float((index // 10) * 120))
    edges = [
        Edge(
            id=f"edge-{index + 1}",
            source=nodes[index].id,
            target=nodes[index + 1].id,
        )
        for index in range(len(nodes) - 1)
    ]
    return GraphDocument(
        graph_id=new_id("graph"),
        title="Rolling Interruption Acceptance",
        nodes=nodes,
        edges=edges,
        lanes=lanes,
        layout=layout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
