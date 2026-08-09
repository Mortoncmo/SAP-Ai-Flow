import argparse
import logging
import signal
from threading import Event

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_event
from app.db.database import Database, get_database
from app.db.repository import BlueprintRepository
from app.documents.export_service import process_export_job


class ExportJobWorker:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    def run_once(self) -> int:
        with self.database.session_factory() as session:
            repository = BlueprintRepository(session)
            repository.expire_export_jobs()
            candidates = repository.list_export_job_candidates(
                stale_minutes=self.settings.export_stale_minutes,
                limit=self.settings.export_worker_batch_size,
            )

        claimed = 0
        for export_id in candidates:
            if process_export_job(
                export_id,
                self.database.engine,
                retention_hours=self.settings.export_retention_hours,
                stale_minutes=self.settings.export_stale_minutes,
            ):
                claimed += 1
        return claimed

    def run_forever(self, stop_event: Event) -> None:
        log_event(
            logging.INFO,
            "export_worker.started",
            poll_seconds=self.settings.export_worker_poll_seconds,
            batch_size=self.settings.export_worker_batch_size,
        )
        while not stop_event.is_set():
            claimed = self.run_once()
            if claimed == 0:
                stop_event.wait(self.settings.export_worker_poll_seconds)
        log_event(logging.INFO, "export_worker.stopped")


def database_healthcheck(database: Database) -> bool:
    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM export_job LIMIT 1"))
    except SQLAlchemyError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the persistent blueprint export worker")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    if args.healthcheck:
        database = Database(settings.database_url, create_schema=False)
        return 0 if database_healthcheck(database) else 1

    database = get_database()
    stop_event = Event()

    def request_stop(_signum, _frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    ExportJobWorker(database, settings).run_forever(stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
