import logging
import re
from datetime import UTC, datetime
from threading import Event, Thread
from time import sleep

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.agent.orchestrator import get_document_orchestrator
from app.core.config import Settings
from app.core.errors import FlowchartError
from app.core.logging import log_event, safe_stack
from app.db.models import ExportJobRecord, ProcessRecord, ProcessRevisionRecord, ProjectRecord
from app.db.repository import BlueprintRepository
from app.documents.artifact_store import (
    ArtifactStorageError,
    ArtifactStore,
    StoredArtifact,
    artifact_sha256,
    build_artifact_store,
    verify_artifact,
)
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


def cleanup_expired_export_artifacts(
    repository: BlueprintRepository,
    artifact_store: ArtifactStore | None,
) -> int:
    repository.expire_export_jobs()
    cleaned = 0
    for job in repository.list_expired_export_artifacts():
        if job.artifact_key is not None:
            if artifact_store is None or artifact_store.backend != job.artifact_backend:
                log_event(
                    logging.ERROR,
                    "export_job.cleanup_storage_unavailable",
                    export_id=job.id,
                    artifact_backend=job.artifact_backend,
                )
                continue
            try:
                artifact_store.delete(job.artifact_key)
            except ArtifactStorageError as exc:
                log_event(
                    logging.ERROR,
                    "export_job.cleanup_failed",
                    export_id=job.id,
                    artifact_backend=job.artifact_backend,
                    exception_type=type(exc).__name__,
                )
                continue
        if repository.clear_export_artifact(job.id):
            cleaned += 1
    return cleaned


def load_export_artifact(
    job: ExportJobRecord,
    settings: Settings,
    *,
    artifact_store: ArtifactStore | None = None,
) -> bytes:
    backend = job.artifact_backend or "database"
    if backend == "database":
        if job.content is None:
            raise _storage_unavailable(job.id)
        content = job.content
    else:
        store = artifact_store or build_artifact_store(settings)
        if store is None or store.backend != backend or job.artifact_key is None:
            raise _storage_unavailable(job.id)
        try:
            content = store.get(job.artifact_key)
        except ArtifactStorageError as exc:
            raise _storage_unavailable(job.id) from exc
    try:
        verify_artifact(
            content,
            expected_length=job.content_length,
            expected_sha256=job.content_sha256,
        )
    except ArtifactStorageError as exc:
        raise _storage_unavailable(job.id) from exc
    return content


def _storage_unavailable(export_id: str) -> FlowchartError:
    return FlowchartError(
        "EXPORT_STORAGE_UNAVAILABLE",
        "导出文件存储暂不可用，请稍后重试。",
        status_code=503,
        details={"export_id": export_id},
    )


def _delete_artifact_safely(
    artifact_store: ArtifactStore | None,
    stored_artifact: StoredArtifact | None,
    *,
    export_id: str,
) -> None:
    if artifact_store is None or stored_artifact is None:
        return
    try:
        artifact_store.delete(stored_artifact.key)
    except ArtifactStorageError as exc:
        log_event(
            logging.ERROR,
            "export_job.compensation_delete_failed",
            export_id=export_id,
            artifact_backend=stored_artifact.backend,
            exception_type=type(exc).__name__,
        )


def process_export_job(
    export_id: str,
    bind: Engine | Connection,
    *,
    retention_hours: int,
    stale_minutes: int,
    heartbeat_seconds: float,
    artifact_store: ArtifactStore | None = None,
    acceptance_render_delay_seconds: float = 0,
) -> bool:
    claim_token: str | None = None
    attempt_count: int | None = None
    stored_artifact: StoredArtifact | None = None
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
                if acceptance_render_delay_seconds:
                    log_event(
                        logging.INFO,
                        "export_job.acceptance_delay",
                        export_id=export_id,
                        delay_seconds=acceptance_render_delay_seconds,
                    )
                    sleep(acceptance_render_delay_seconds)
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
            if artifact_store is not None:
                stored_artifact = artifact_store.put(
                    export_id=export_id,
                    claim_token=claim_token,
                    content=content,
                    media_type=media_type,
                )
            completed = repository.complete_export_job(
                export_id=export_id,
                claim_token=claim_token,
                filename=unicode_filename,
                fallback_filename=fallback_filename,
                media_type=media_type,
                content=content if stored_artifact is None else None,
                retention_hours=retention_hours,
                artifact_backend=(stored_artifact.backend if stored_artifact else "database"),
                artifact_key=stored_artifact.key if stored_artifact else None,
                content_sha256=(
                    stored_artifact.sha256 if stored_artifact else artifact_sha256(content)
                ),
                content_length=(stored_artifact.content_length if stored_artifact else len(content)),
            )
            if not completed:
                _delete_artifact_safely(
                    artifact_store,
                    stored_artifact,
                    export_id=export_id,
                )
                stored_artifact = None
            else:
                stored_artifact = None
            log_event(
                logging.INFO if completed else logging.WARNING,
                "export_job.completed" if completed else "export_job.lease_lost",
                export_id=export_id,
                attempt_count=attempt_count,
                heartbeat_lease_lost=heartbeat.lease_lost,
            )
        except Exception as exc:
            session.rollback()
            _delete_artifact_safely(
                artifact_store,
                stored_artifact,
                export_id=export_id,
            )
            stored_artifact = None
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
