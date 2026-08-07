from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    configured = settings.agent_provider == "local" or bool(settings.deepseek_api_key)
    return {
        "status": "ok" if configured else "not_ready",
        "provider": settings.agent_provider,
    }


@router.get("/api/v1/meta")
def metadata(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {
        "name": "SAP AI Flow",
        "version": "0.1.0",
        "provider": settings.agent_provider,
    }
