from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import gettempdir

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.errors import FlowchartError
from app.main import app
from app.security import auth

ISSUER = "https://identity.example.test"
AUDIENCE = "sap-ai-flow"
JWKS_URL = f"{ISSUER}/keys"


class StaticSigningKey:
    def __init__(self, key: object) -> None:
        self.key = key


class StaticJwksClient:
    def __init__(self, key: object) -> None:
        self.signing_key = StaticSigningKey(key)

    def get_signing_key_from_jwt(self, _: str) -> StaticSigningKey:
        return self.signing_key


@pytest.fixture
def signing_keys(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = StaticJwksClient(private_key.public_key())
    monkeypatch.setattr(auth, "_jwks_client", lambda _: client)
    return private_key


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "oidc_issuer": ISSUER,
        "oidc_audience": AUDIENCE,
        "oidc_jwks_url": JWKS_URL,
        "oidc_algorithms": ["RS256"],
        "oidc_user_id_claim": "sub",
        "oidc_tenant_id_claim": "tid",
        "oidc_allowed_tenant_ids": ["tenant-alpha"],
        "oidc_clock_skew_seconds": 0,
        "export_execution_mode": "worker",
        "export_storage_backend": "filesystem",
        "export_storage_path": str(Path(gettempdir()) / "sap-ai-flow-test-artifacts"),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def encode_token(private_key, **overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": "consultant-user",
        "tid": "tenant-alpha",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})


def credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_development_identity_keeps_local_header_support():
    settings = Settings(_env_file=None, app_env="development")

    default_user = auth.get_user_context(credentials=None, x_user_id=None, settings=settings)
    explicit_user = auth.get_user_context(
        credentials=None, x_user_id="developer-user", settings=settings
    )

    assert default_user.user_id == "local-user"
    assert default_user.tenant_id == "local"
    assert explicit_user.user_id == "developer-user"
    assert explicit_user.tenant_id == "local"


def test_production_rejects_spoofed_development_header():
    with pytest.raises(FlowchartError) as caught:
        auth.get_user_context(
            credentials=None,
            x_user_id="spoofed-admin",
            settings=production_settings(),
        )

    assert caught.value.status_code == 401
    assert caught.value.code == "UNAUTHENTICATED"


def test_production_requires_complete_oidc_configuration():
    with pytest.raises(FlowchartError) as caught:
        auth.get_user_context(
            credentials=credentials("opaque-token"),
            x_user_id=None,
            settings=production_settings(oidc_jwks_url=""),
        )

    assert caught.value.status_code == 503
    assert caught.value.code == "AUTH_CONFIGURATION_ERROR"


def test_valid_signed_token_resolves_stable_user_id(signing_keys):
    context = auth.get_user_context(
        credentials=credentials(encode_token(signing_keys)),
        x_user_id="ignored-spoof",
        settings=production_settings(),
    )

    assert context.user_id == "consultant-user"
    assert context.tenant_id == "tenant-alpha"


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": datetime.now(UTC) - timedelta(minutes=2)},
        {"iss": "https://wrong-issuer.example.test"},
        {"aud": "wrong-audience"},
        {"sub": ""},
        {"tid": ""},
    ],
)
def test_invalid_token_claims_are_rejected(signing_keys, overrides):
    with pytest.raises(FlowchartError) as caught:
        auth.get_user_context(
            credentials=credentials(encode_token(signing_keys, **overrides)),
            x_user_id=None,
            settings=production_settings(),
        )

    assert caught.value.status_code == 401
    assert caught.value.code == "INVALID_ACCESS_TOKEN"


def test_tenant_claim_must_be_explicitly_allowed(signing_keys):
    with pytest.raises(FlowchartError) as caught:
        auth.get_user_context(
            credentials=credentials(encode_token(signing_keys, tid="tenant-beta")),
            x_user_id=None,
            settings=production_settings(),
        )

    assert caught.value.status_code == 401
    assert caught.value.code == "INVALID_ACCESS_TOKEN"


def test_token_signed_by_unknown_key_is_rejected(signing_keys):
    unknown_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = encode_token(unknown_key)

    with pytest.raises(FlowchartError) as caught:
        auth.get_user_context(
            credentials=credentials(token),
            x_user_id=None,
            settings=production_settings(),
        )

    assert caught.value.status_code == 401
    assert caught.value.code == "INVALID_ACCESS_TOKEN"


def test_project_route_uses_bearer_identity_in_production(signing_keys):
    settings = production_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            spoofed = client.get("/api/v1/projects", headers={"X-User-ID": "spoofed-admin"})
            authorized = client.get(
                "/api/v1/projects",
                headers={"Authorization": f"Bearer {encode_token(signing_keys)}"},
            )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert spoofed.status_code == 401
    assert spoofed.json()["error"]["code"] == "UNAUTHENTICATED"
    assert authorized.status_code == 200


def test_projects_are_isolated_by_oidc_tenant_even_for_the_same_subject(signing_keys):
    settings = production_settings(oidc_allowed_tenant_ids=["tenant-alpha", "tenant-beta"])
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            alpha_headers = {
                "Authorization": f"Bearer {encode_token(signing_keys, tid='tenant-alpha')}"
            }
            beta_headers = {
                "Authorization": f"Bearer {encode_token(signing_keys, tid='tenant-beta')}"
            }
            created = client.post(
                "/api/v1/projects",
                json={"name": "Tenant Alpha Project", "sap_context": {}},
                headers=alpha_headers,
            )
            project_id = created.json()["id"]
            process = client.post(
                f"/api/v1/projects/{project_id}/processes",
                json={"name": "Tenant Alpha Process", "module": "MM", "process_scope": "P2P"},
                headers=alpha_headers,
            )
            process_id = process.json()["id"]

            alpha_projects = client.get("/api/v1/projects", headers=alpha_headers)
            beta_projects = client.get("/api/v1/projects", headers=beta_headers)
            hidden = client.get(f"/api/v1/projects/{project_id}", headers=beta_headers)
            hidden_process = client.get(
                f"/api/v1/processes/{process_id}",
                headers=beta_headers,
            )
            hidden_knowledge = client.post(
                f"/api/v1/projects/{project_id}/knowledge/search",
                json={
                    "module": "MM",
                    "process_scope": "P2P",
                    "query": "采购审批",
                    "sap_context": {},
                    "top_k": 3,
                },
                headers=beta_headers,
            )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert created.status_code == 201
    assert any(item["id"] == project_id for item in alpha_projects.json())
    assert all(item["id"] != project_id for item in beta_projects.json())
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    assert hidden_process.status_code == 404
    assert hidden_process.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    assert hidden_knowledge.status_code == 404
    assert hidden_knowledge.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_development_only_routes_are_hidden_in_production(order_graph):
    settings = production_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            flowchart = client.post(
                "/api/v1/flowcharts/modify",
                json={
                    "request_id": "production-route-test",
                    "current_graph": order_graph.model_dump(mode="json"),
                    "instruction": "增加审批节点",
                    "locale": "zh-CN",
                },
            )
            knowledge = client.post(
                "/api/v1/knowledge/search",
                json={
                    "module": "MM",
                    "process_scope": "P2P",
                    "query": "采购申请审批",
                    "sap_context": {},
                    "top_k": 3,
                },
            )
            gaps = client.post(
                "/api/v1/gaps/analyze",
                json={
                    "module": "MM",
                    "process_scope": "P2P",
                    "business_requirement": "三层预算审批",
                    "sap_context": {},
                },
            )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert {flowchart.status_code, knowledge.status_code, gaps.status_code} == {404}
    assert flowchart.json()["error"]["code"] == "DEVELOPMENT_ROUTE_DISABLED"
    assert knowledge.json()["error"]["code"] == "DEVELOPMENT_ROUTE_DISABLED"
    assert gaps.json()["error"]["code"] == "DEVELOPMENT_ROUTE_DISABLED"


def test_readiness_requires_oidc_configuration_in_production():
    app.dependency_overrides[get_settings] = lambda: production_settings(oidc_jwks_url="")
    try:
        with TestClient(app) as client:
            not_ready = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    app.dependency_overrides[get_settings] = lambda: production_settings()
    try:
        with TestClient(app) as client:
            ready = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert not_ready.status_code == 503
    assert not_ready.json()["status"] == "not_ready"
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ok",
        "provider": "local",
        "authentication": "oidc",
        "tenant_isolation": "oidc_claim_allowlist",
        "database": "ready",
        "database_backend": "sqlite",
        "export_execution": "worker",
        "artifact_storage": "filesystem",
        "artifact_storage_status": "ready",
    }


def test_readiness_requires_an_explicit_tenant_allowlist_in_production():
    app.dependency_overrides[get_settings] = lambda: production_settings(
        oidc_allowed_tenant_ids=[]
    )
    try:
        with TestClient(app) as client:
            response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["tenant_isolation"] == "oidc_claim_allowlist"


def test_readiness_rejects_inline_export_execution_in_production():
    app.dependency_overrides[get_settings] = lambda: production_settings(
        export_execution_mode="inline"
    )
    try:
        with TestClient(app) as client:
            response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 503
    assert response.json()["export_execution"] == "inline"


def test_readiness_rejects_database_artifact_storage_in_production():
    app.dependency_overrides[get_settings] = lambda: production_settings(
        export_storage_backend="database"
    )
    try:
        with TestClient(app) as client:
            response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 503
    assert response.json()["artifact_storage"] == "database"
    assert response.json()["artifact_storage_status"] == "unavailable"


def test_oidc_algorithms_reject_symmetric_or_unsigned_tokens():
    with pytest.raises(ValueError, match="asymmetric JWT algorithms"):
        production_settings(oidc_algorithms=["HS256", "none"])
