import json
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.core.config import get_settings
from app.db.database import Database


def test_initial_migration_upgrades_and_downgrades_empty_sqlite(tmp_path, monkeypatch):
    database_url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    try:
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        assert {
            "project",
            "project_member",
            "project_audit_log",
            "process",
            "process_revision",
            "change_log",
            "gap_decision",
            "export_job",
        }.issubset(
            set(inspect(engine).get_table_names())
        )
        export_columns = {column["name"] for column in inspect(engine).get_columns("export_job")}
        assert {"claim_token", "attempt_count", "heartbeat_at"} <= export_columns
        command.downgrade(config, "base")
        assert inspect(engine).get_table_names() == ["alembic_version"]
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_export_worker_lease_migrations_backfill_and_roll_back(tmp_path, monkeypatch):
    database_url = f"sqlite:///{(tmp_path / 'export-worker-migration.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    try:
        command.upgrade(config, "20260809_0005")
        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO export_job (
                        id, process_id, revision_no, format, status, created_by,
                        created_at, started_at
                    ) VALUES (
                        'export-existing', 'process-existing', 0, 'markdown',
                        'running', 'owner-existing', :created_at, :created_at
                    )
                    """
                ),
                {"created_at": datetime.now(UTC)},
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            lease = connection.execute(
                text(
                    "SELECT claim_token, attempt_count, heartbeat_at FROM export_job "
                    "WHERE id = 'export-existing'"
                )
            ).one()
        assert lease[0:2] == (None, 0)
        assert lease.heartbeat_at is not None

        command.downgrade(config, "20260809_0005")
        columns = {column["name"] for column in inspect(engine).get_columns("export_job")}
        assert "claim_token" not in columns
        assert "attempt_count" not in columns
        assert "heartbeat_at" not in columns
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_sqlite_development_startup_upgrades_existing_export_jobs(tmp_path, monkeypatch):
    database_url = f"sqlite:///{(tmp_path / 'development-upgrade.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    try:
        command.upgrade(config, "20260809_0005")
        database = Database(database_url, create_schema=True)
        inspector = inspect(database.engine)
        columns = {column["name"] for column in inspector.get_columns("export_job")}
        indexes = {index["name"] for index in inspector.get_indexes("export_job")}
        assert {"claim_token", "attempt_count", "heartbeat_at"} <= columns
        assert "ix_export_job_status_created_at" in indexes
        assert "ix_export_job_status_heartbeat_at" in indexes
        database.engine.dispose()
    finally:
        get_settings.cache_clear()


def test_project_member_migration_backfills_existing_project_owner(tmp_path, monkeypatch):
    database_url = f"sqlite:///{(tmp_path / 'member-migration.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    now = datetime.now(UTC)

    try:
        command.upgrade(config, "20260809_0002")
        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO project (
                        id, name, customer_name, sap_context, created_by, created_at, updated_at
                    ) VALUES (
                        :id, :name, NULL, :sap_context, :created_by, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": "project-existing",
                    "name": "存量项目",
                    "sap_context": json.dumps({"edition": "S/4HANA", "release": "2023"}),
                    "created_by": "owner-existing",
                    "created_at": now,
                    "updated_at": now,
                },
            )
        command.upgrade(config, "head")
        inspector = inspect(engine)
        project_columns = {column["name"] for column in inspector.get_columns("project")}
        assert "external_model_enabled" in project_columns
        assert "project_audit_log" in inspector.get_table_names()
        with engine.connect() as connection:
            member = connection.execute(
                text(
                    """
                    SELECT user_id, role, created_by
                    FROM project_member
                    WHERE project_id = :project_id
                    """
                ),
                {"project_id": "project-existing"},
            ).one()
            external_model_enabled = connection.execute(
                text(
                    "SELECT external_model_enabled FROM project "
                    "WHERE id = :project_id"
                ),
                {"project_id": "project-existing"},
            ).scalar_one()
        assert member == ("owner-existing", "project_admin", "owner-existing")
        assert external_model_enabled in (False, 0)
        engine.dispose()
    finally:
        get_settings.cache_clear()
