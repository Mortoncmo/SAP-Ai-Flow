from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base


class Database:
    def __init__(self, url: str, *, create_schema: bool = True) -> None:
        self.url = url
        if url.startswith("sqlite:///"):
            file_path = Path(url.removeprefix("sqlite:///"))
            file_path.parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        if create_schema:
            Base.metadata.create_all(self.engine)
            if url.startswith("sqlite"):
                self._ensure_sqlite_development_columns()

    def _ensure_sqlite_development_columns(self) -> None:
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        project_columns = (
            {column["name"] for column in inspector.get_columns("project")}
            if "project" in tables
            else set()
        )
        if "project" in tables and "external_model_enabled" not in project_columns:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE project ADD COLUMN external_model_enabled "
                        "BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
        if "project" in tables and "tenant_id" not in project_columns:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE project ADD COLUMN tenant_id "
                        "VARCHAR(80) NOT NULL DEFAULT 'local'"
                    )
                )
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_project_tenant_id "
                        "ON project (tenant_id)"
                    )
                )
        if "process_revision" in tables:
            revision_columns = {
                column["name"] for column in inspect(self.engine).get_columns("process_revision")
            }
            with self.engine.begin() as connection:
                if "drawio_xml" not in revision_columns:
                    connection.execute(text("ALTER TABLE process_revision ADD COLUMN drawio_xml TEXT"))
                if "drawio_sha256" not in revision_columns:
                    connection.execute(
                        text("ALTER TABLE process_revision ADD COLUMN drawio_sha256 VARCHAR(64)")
                    )
        if "export_job" not in tables:
            return
        export_columns = {
            column["name"] for column in inspect(self.engine).get_columns("export_job")
        }
        with self.engine.begin() as connection:
            if "claim_token" not in export_columns:
                connection.execute(text("ALTER TABLE export_job ADD COLUMN claim_token VARCHAR(80)"))
            if "attempt_count" not in export_columns:
                connection.execute(
                    text(
                        "ALTER TABLE export_job ADD COLUMN attempt_count "
                        "INTEGER NOT NULL DEFAULT 0"
                    )
                )
            if "heartbeat_at" not in export_columns:
                connection.execute(
                    text("ALTER TABLE export_job ADD COLUMN heartbeat_at DATETIME")
                )
                connection.execute(
                    text(
                        "UPDATE export_job SET heartbeat_at = started_at "
                        "WHERE status = 'running' AND heartbeat_at IS NULL"
                    )
                )
            if "artifact_backend" not in export_columns:
                connection.execute(
                    text("ALTER TABLE export_job ADD COLUMN artifact_backend VARCHAR(20)")
                )
                connection.execute(
                    text(
                        "UPDATE export_job SET artifact_backend = 'database' "
                        "WHERE status = 'completed' AND content IS NOT NULL"
                    )
                )
            if "artifact_key" not in export_columns:
                connection.execute(
                    text("ALTER TABLE export_job ADD COLUMN artifact_key VARCHAR(512)")
                )
            if "content_sha256" not in export_columns:
                connection.execute(
                    text("ALTER TABLE export_job ADD COLUMN content_sha256 VARCHAR(64)")
                )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_export_job_status_created_at "
                    "ON export_job (status, created_at)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_export_job_status_heartbeat_at "
                    "ON export_job (status, heartbeat_at)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_export_job_status_expires_at "
                    "ON export_job (status, expires_at)"
                )
            )


def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@lru_cache
def get_database() -> Database:
    settings = get_settings()
    return Database(settings.database_url, create_schema=settings.database_auto_create)


def get_db_session() -> Iterator[Session]:
    session = get_database().session_factory()
    try:
        yield session
    finally:
        session.close()
