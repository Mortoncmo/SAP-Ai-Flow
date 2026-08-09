from fastapi import APIRouter, Depends, Response

from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(response: Response, settings: Settings = Depends(get_settings)) -> dict[str, str]:
    provider_configured = settings.agent_provider == "local" or bool(settings.deepseek_api_key)
    auth_configured = settings.app_env == "development" or settings.oidc_configured
    configured = provider_configured and auth_configured
    if not configured:
        response.status_code = 503
    return {
        "status": "ok" if configured else "not_ready",
        "provider": settings.agent_provider,
        "authentication": "development" if settings.app_env == "development" else "oidc",
    }


@router.get("/api/v1/meta")
def metadata(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {
        "name": "SAP AI Flow",
        "version": "0.1.0",
        "provider": settings.agent_provider,
        "authentication": "development" if settings.app_env == "development" else "oidc",
    }
