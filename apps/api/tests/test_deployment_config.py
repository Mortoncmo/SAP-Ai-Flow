from pathlib import Path

import yaml

from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[3]


def test_docker_context_excludes_local_secrets_dependencies_and_outputs():
    ignored = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert {".env", ".venv", "node_modules", "output", "*.docx", "*.md.txt"} <= ignored


def test_compose_requires_database_password_and_keeps_api_internal():
    compose_path = ROOT / "deploy" / "docker-compose.yml"
    raw = compose_path.read_text(encoding="utf-8")
    compose = yaml.safe_load(raw)
    postgres = compose["services"]["postgres"]
    api = compose["services"]["api"]
    web = compose["services"]["web"]

    assert "sap_blueprint_dev" not in raw
    assert "${POSTGRES_PASSWORD:?" in postgres["environment"]["POSTGRES_PASSWORD"]
    assert "${POSTGRES_PASSWORD:?" in api["environment"]["DATABASE_URL"]
    assert api["environment"]["EXPORT_RETENTION_HOURS"] == "${EXPORT_RETENTION_HOURS:-24}"
    assert api["environment"]["EXPORT_STALE_MINUTES"] == "${EXPORT_STALE_MINUTES:-5}"
    assert api["environment"]["LLM_CACHE_TTL_SECONDS"] == "${LLM_CACHE_TTL_SECONDS:-60}"
    assert api["environment"]["LLM_CACHE_MAX_ENTRIES"] == "${LLM_CACHE_MAX_ENTRIES:-128}"
    assert api["image"] == "sap-ai-flow-api:${SAP_FLOW_IMAGE_TAG:-local}"
    assert web["image"] == "sap-ai-flow-web:${SAP_FLOW_IMAGE_TAG:-local}"
    assert "ports" not in api
    assert api["expose"] == ["8000"]
    assert web["healthcheck"]["test"][0] == "CMD-SHELL"
    assert "/health/ready" in web["healthcheck"]["test"][1]


def test_settings_accept_compose_list_environment_values(monkeypatch):
    monkeypatch.setenv("OIDC_ALGORITHMS", "RS256,ES256")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:8080,https://flow.example.com")

    settings = Settings(_env_file=None)

    assert settings.oidc_algorithms == ["RS256", "ES256"]
    assert settings.cors_origins == ["http://localhost:8080", "https://flow.example.com"]


def test_browser_smoke_passes_cors_origin_in_supported_format():
    script = (ROOT / "scripts" / "browser_smoke.ps1").read_text(encoding="utf-8")

    assert '$env:CORS_ORIGINS = $BaseUrl' in script
    assert "ConvertTo-Json -InputObject @($BaseUrl)" not in script


def test_api_image_and_nginx_keep_delivery_guards_enabled():
    api_dockerfile = (ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    web_dockerfile = (ROOT / "apps" / "web" / "Dockerfile").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")

    assert api_dockerfile.index("USER app") < api_dockerfile.index("CMD [")
    assert "alembic upgrade head" in api_dockerfile
    assert "FROM nginx:1.29-alpine" in web_dockerfile
    assert "client_max_body_size 2m" in nginx
    assert "proxy_read_timeout 45s" in nginx
    assert "proxy_connect_timeout 3s" in nginx


def test_ci_exercises_compose_postgres_backup_and_restore():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "  deploy:" in workflow
    assert "docker compose -f deploy/docker-compose.yml build" in workflow
    assert "http://127.0.0.1:8080/health/ready" in workflow
    assert "pg_dump --clean --if-exists --no-owner" in workflow
    assert "sap_blueprint_restore" in workflow
    assert "20260809_0005 (head)" in workflow
    assert workflow.count("aquasecurity/trivy-action@v0.36.0") == 4
    assert "output/sap-ai-flow-api.cdx.json" in workflow
    assert "output/sap-ai-flow-web.cdx.json" in workflow
    assert workflow.count("actions/checkout@v5") == 3
    assert "actions/setup-python@v6" in workflow
    assert "actions/setup-node@v5" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "severity: CRITICAL" in workflow
    assert "ignore-unfixed: true" in workflow
    assert 'exit-code: "1"' in workflow
    assert "down --volumes --remove-orphans" in workflow
