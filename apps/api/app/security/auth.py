from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

import jwt
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError, PyJWTError

from app.core.config import Settings, get_settings
from app.core.errors import FlowchartError


class ProjectRole(StrEnum):
    VIEWER = "viewer"
    EDITOR = "editor"
    CONSULTANT_APPROVER = "consultant_approver"
    PROJECT_ADMIN = "project_admin"


ROLE_RANK = {
    ProjectRole.VIEWER: 0,
    ProjectRole.EDITOR: 1,
    ProjectRole.CONSULTANT_APPROVER: 2,
    ProjectRole.PROJECT_ADMIN: 3,
}


@dataclass(frozen=True)
class UserContext:
    user_id: str
    tenant_id: str


bearer_scheme = HTTPBearer(auto_error=False)


def get_user_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    settings: Settings = Depends(get_settings),
) -> UserContext:
    if settings.app_env == "development":
        user_id = (x_user_id or "local-user").strip()
        if not user_id:
            raise _unauthenticated()
        return UserContext(user_id=user_id, tenant_id=settings.development_tenant_id)

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthenticated()
    if not settings.oidc_configured:
        raise FlowchartError(
            "AUTH_CONFIGURATION_ERROR",
            "服务端身份认证配置不完整。",
            status_code=503,
        )

    claims = _decode_access_token(credentials.credentials, settings)
    user_id = _identity_claim(claims, settings.oidc_user_id_claim)
    tenant_id = _identity_claim(claims, settings.oidc_tenant_id_claim)
    if user_id is None or tenant_id is None:
        raise _invalid_token()
    if tenant_id not in settings.oidc_allowed_tenant_ids:
        raise _invalid_token()
    return UserContext(user_id=user_id, tenant_id=tenant_id)


def _decode_access_token(token: str, settings: Settings) -> dict[str, object]:
    try:
        signing_key = _jwks_client(settings.oidc_jwks_url.strip()).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=settings.oidc_algorithms,
            audience=settings.oidc_audience.strip(),
            issuer=settings.oidc_issuer.strip(),
            leeway=settings.oidc_clock_skew_seconds,
            options={
                "require": [
                    "exp",
                    "iat",
                    settings.oidc_user_id_claim,
                    settings.oidc_tenant_id_claim,
                ]
            },
        )
    except (PyJWTError, PyJWKClientError, ValueError, TypeError) as exc:
        raise _invalid_token() from exc


def _identity_claim(claims: dict[str, object], claim_name: str) -> str | None:
    value = claims.get(claim_name)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 80
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        return None
    return normalized


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True)


def _unauthenticated() -> FlowchartError:
    return FlowchartError("UNAUTHENTICATED", "缺少有效的用户身份。", status_code=401)


def _invalid_token() -> FlowchartError:
    return FlowchartError("INVALID_ACCESS_TOKEN", "访问令牌无效或已过期。", status_code=401)


def require_role(actual: ProjectRole, minimum: ProjectRole) -> None:
    if ROLE_RANK[actual] < ROLE_RANK[minimum]:
        raise FlowchartError(
            "PROJECT_PERMISSION_DENIED",
            "当前项目角色无权执行此操作。",
            status_code=403,
            details={"required_role": minimum, "current_role": actual},
        )


def require_development_mode(settings: Settings = Depends(get_settings)) -> None:
    if settings.app_env != "development":
        raise FlowchartError(
            "DEVELOPMENT_ROUTE_DISABLED",
            "该接口仅在本地开发环境开放。",
            status_code=404,
        )
