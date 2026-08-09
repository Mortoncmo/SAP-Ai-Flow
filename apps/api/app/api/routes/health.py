from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.database import Database, get_database

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(
    response: Response,
    settings: Settings = Depends(get_settings),
    database: Database = Depends(get_database),
) -> dict[str, str]:
    provider_configured = settings.agent_provider == "local" or bool(settings.deepseek_api_key)
    auth_configured = settings.app_env == "development" or settings.oidc_configured
    export_configured = (
        settings.app_env == "development" or settings.export_execution_mode == "worker"
    )
    database_available = _database_available(database)
    configured = provider_configured and auth_configured and export_configured and database_available
    if not configured:
        response.status_code = 503
    return {
        "status": "ok" if configured else "not_ready",
        "provider": settings.agent_provider,
        "authentication": "development" if settings.app_env == "development" else "oidc",
        "database": "ready" if database_available else "unavailable",
        "database_backend": make_url(settings.database_url).get_backend_name(),
        "export_execution": settings.export_execution_mode,
    }


def _database_available(database: Database) -> bool:
    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


@router.get("/api/v1/meta")
def metadata(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {
        "name": "SAP AI Flow",
        "version": "0.1.0",
        "provider": settings.agent_provider,
        "authentication": "development" if settings.app_env == "development" else "oidc",
        "export_execution": settings.export_execution_mode,
    }
