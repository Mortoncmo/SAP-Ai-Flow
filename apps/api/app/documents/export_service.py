import logging
import re
from datetime import UTC, datetime
from threading import Event, Thread

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.agent.orchestrator import get_document_orchestrator
from app.core.logging import log_event, safe_stack
from app.db.models import ProcessRecord, ProcessRevisionRecord, ProjectRecord
from app.db.repository import BlueprintRepository
from app.documents.blueprint import BlueprintDocumentModel, render_docx, render_markdown
from app.models.graph import GraphDocument


class ExportLeaseHeartbeat:
    def __init__(
        self,
        *,
        export_id: str,
        claim_token: str,
        bind: Engine | Connection,
        interval_seconds: float,
    ) -> None:
        self.export_id = export_id
        self.claim_token = claim_token
        self.bind = bind.engine if isinstance(bind, Connection) else bind
        self.interval_seconds = interval_seconds
        self._stop = Event()
        self._lease_lost = Event()
        self._thread = Thread(
            target=self._run,
            name=f"export-heartbeat-{export_id[-12:]}",
            daemon=True,
        )

    @property
    def lease_lost(self) -> bool:
        return self._lease_lost.is_set()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=min(self.interval_seconds + 1, 5))
        if self._thread.is_alive():
            log_event(
                logging.WARNING,
                "export_job.heartbeat_stop_timeout",
                export_id=self.export_id,
            )

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                with Session(bind=self.bind, expire_on_commit=False) as session:
                    renewed = BlueprintRepository(session).renew_export_job_lease(
                        export_id=self.export_id,
                        claim_token=self.claim_token,
                    )
            except Exception as exc:
                log_event(
                    logging.ERROR,
                    "export_job.heartbeat_failed",
                    export_id=self.export_id,
                    exception_type=type(exc).__name__,
                    stack=safe_stack(exc.__traceback__),
                )
                continue
            if not renewed:
                self._lease_lost.set()
                log_event(
                    logging.WARNING,
                    "export_job.heartbeat_lease_lost",
                    export_id=self.export_id,
                )
                return


def blueprint_document(
    project: ProjectRecord,
    process: ProcessRecord,
    revision: ProcessRevisionRecord,
) -> BlueprintDocumentModel:
    return BlueprintDocumentModel(
        project_name=project.name,
        customer_name=project.customer_name,
        process_name=process.name,
        process_id=process.id,
        revision_no=revision.revision_no,
        release_no=revision.release_no,
        lifecycle_state=revision.lifecycle_state,
        created_by=revision.created_by,
        created_at=revision.created_at.isoformat(),
        graph=GraphDocument.model_validate(revision.graph_json),
    )


def render_export(model: BlueprintDocumentModel, format: str) -> tuple[bytes, str, str]:
    result = get_document_orchestrator().render(
        model,
        format,
        markdown_renderer=render_markdown,
        docx_renderer=render_docx,
    )
    return result.content, result.media_type, result.extension


def export_filenames(
    *,
    process_name: str,
    process_id: str,
    revision_no: int,
    release_no: int | None,
    extension: str,
) -> tuple[str, str]:
    safe_name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", process_name)
    safe_name = re.sub(r"\s+", " ", safe_name).strip(" .") or "flowchart"
    version = f"release-{release_no}" if release_no is not None else f"r{revision_no}"
    exported_at = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return (
        f"SAP-Blueprint-{safe_name}-{version}-{exported_at}.{extension}",
        f"SAP-Blueprint-{process_id}-{version}-{exported_at}.{extension}",
    )


def process_export_job(
    export_id: str,
    bind: Engine | Connection,
    *,
    retention_hours: int,
    stale_minutes: int,
    heartbeat_seconds: float,
) -> bool:
    claim_token: str | None = None
    attempt_count: int | None = None
    with Session(bind=bind, expire_on_commit=False) as session:
        repository = BlueprintRepository(session)
        try:
            claim_token = repository.claim_export_job(export_id, stale_minutes=stale_minutes)
            if claim_token is None:
                return False
            job = repository.require_export_job_unscoped(export_id)
            attempt_count = job.attempt_count
            log_event(
                logging.INFO,
                "export_job.started",
                export_id=export_id,
                attempt_count=attempt_count,
            )
            process = repository.require_process(job.process_id)
            project = repository.require_project(process.project_id)
            revision = repository.require_revision(process.id, job.revision_no)
            model = blueprint_document(project, process, revision)
            session.commit()
            heartbeat = ExportLeaseHeartbeat(
                export_id=export_id,
                claim_token=claim_token,
                bind=bind,
                interval_seconds=heartbeat_seconds,
            )
            heartbeat.start()
            try:
                content, media_type, extension = render_export(model, job.format)
            finally:
                heartbeat.stop()
            unicode_filename, fallback_filename = export_filenames(
                process_name=process.name,
                process_id=process.id,
                revision_no=revision.revision_no,
                release_no=revision.release_no,
                extension=extension,
            )
            completed = repository.complete_export_job(
                export_id=export_id,
                claim_token=claim_token,
                filename=unicode_filename,
                fallback_filename=fallback_filename,
                media_type=media_type,
                content=content,
                retention_hours=retention_hours,
            )
            log_event(
                logging.INFO if completed else logging.WARNING,
                "export_job.completed" if completed else "export_job.lease_lost",
                export_id=export_id,
                attempt_count=attempt_count,
                heartbeat_lease_lost=heartbeat.lease_lost,
            )
        except Exception as exc:
            session.rollback()
            log_event(
                logging.ERROR,
                "export_job.failed",
                export_id=export_id,
                attempt_count=attempt_count,
                exception_type=type(exc).__name__,
                stack=safe_stack(exc.__traceback__),
            )
            if claim_token is not None:
                try:
                    persisted = repository.fail_export_job(
                        export_id=export_id,
                        claim_token=claim_token,
                    )
                    if not persisted:
                        log_event(
                            logging.WARNING,
                            "export_job.failure_lease_lost",
                            export_id=export_id,
                            attempt_count=attempt_count,
                        )
                except Exception as persist_exc:
                    session.rollback()
                    log_event(
                        logging.ERROR,
                        "export_job.failure_persist_failed",
                        export_id=export_id,
                        attempt_count=attempt_count,
                        exception_type=type(persist_exc).__name__,
                        stack=safe_stack(persist_exc.__traceback__),
                    )
    return claim_token is not None
