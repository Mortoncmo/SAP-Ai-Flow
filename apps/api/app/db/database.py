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
        if "project" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("project")}
        if "external_model_enabled" not in columns:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE project ADD COLUMN external_model_enabled "
                        "BOOLEAN NOT NULL DEFAULT 0"
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
