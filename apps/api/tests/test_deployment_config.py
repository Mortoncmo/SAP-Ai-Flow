from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

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
    worker = compose["services"]["worker"]
    web = compose["services"]["web"]

    assert "sap_blueprint_dev" not in raw
    assert "${POSTGRES_PASSWORD:?" in postgres["environment"]["POSTGRES_PASSWORD"]
    assert "${POSTGRES_PASSWORD:?" in api["environment"]["DATABASE_URL"]
    assert api["environment"]["EXPORT_RETENTION_HOURS"] == "${EXPORT_RETENTION_HOURS:-24}"
    assert api["environment"]["EXPORT_STALE_MINUTES"] == "${EXPORT_STALE_MINUTES:-5}"
    assert api["environment"]["EXPORT_LEASE_HEARTBEAT_SECONDS"] == (
        "${EXPORT_LEASE_HEARTBEAT_SECONDS:-30}"
    )
    assert api["environment"]["EXPORT_STORAGE_BACKEND"] == (
        "${EXPORT_STORAGE_BACKEND:-filesystem}"
    )
    assert api["environment"]["EXPORT_STORAGE_PATH"] == "/app/data/exports"
    assert api["environment"]["EXPORT_S3_SECRET_ACCESS_KEY"] == (
        "${EXPORT_S3_SECRET_ACCESS_KEY:-}"
    )
    assert api["environment"]["EXPORT_EXECUTION_MODE"] == "worker"
    assert api["environment"]["LLM_CACHE_TTL_SECONDS"] == "${LLM_CACHE_TTL_SECONDS:-60}"
    assert api["environment"]["LLM_CACHE_MAX_ENTRIES"] == "${LLM_CACHE_MAX_ENTRIES:-128}"
    assert api["image"] == "sap-ai-flow-api:${SAP_FLOW_IMAGE_TAG:-local}"
    assert web["image"] == "sap-ai-flow-web:${SAP_FLOW_IMAGE_TAG:-local}"
    assert "ports" not in api
    assert api["expose"] == ["8000"]
    assert web["healthcheck"]["test"][0] == "CMD-SHELL"
    assert "/health/ready" in web["healthcheck"]["test"][1]
    assert worker["image"] == api["image"]
    assert worker["command"] == ["python", "-m", "app.workers.export_worker"]
    assert worker["environment"]["EXPORT_EXECUTION_MODE"] == "worker"
    assert worker["environment"]["EXPORT_WORKER_POLL_SECONDS"] == "${EXPORT_WORKER_POLL_SECONDS:-1}"
    assert worker["environment"]["EXPORT_WORKER_BATCH_SIZE"] == "${EXPORT_WORKER_BATCH_SIZE:-8}"
    assert worker["environment"]["EXPORT_LEASE_HEARTBEAT_SECONDS"] == (
        "${EXPORT_LEASE_HEARTBEAT_SECONDS:-30}"
    )
    assert worker["environment"]["EXPORT_STORAGE_BACKEND"] == (
        "${EXPORT_STORAGE_BACKEND:-filesystem}"
    )
    assert worker["environment"]["EXPORT_STORAGE_PATH"] == "/app/data/exports"
    assert worker["environment"]["DATABASE_AUTO_CREATE"] == "false"
    assert worker["depends_on"]["api"]["condition"] == "service_healthy"
    assert worker["healthcheck"]["test"][-1] == "--healthcheck"
    assert "export-data:/app/data/exports" in api["volumes"]
    assert "export-data:/app/data/exports" in worker["volumes"]
    assert "export-data" in compose["volumes"]
    assert web["depends_on"]["worker"]["condition"] == "service_healthy"


def test_settings_accept_compose_list_environment_values(monkeypatch):
    monkeypatch.setenv("OIDC_ALGORITHMS", "RS256,ES256")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:8080,https://flow.example.com")

    settings = Settings(_env_file=None)

    assert settings.oidc_algorithms == ["RS256", "ES256"]
    assert settings.cors_origins == ["http://localhost:8080", "https://flow.example.com"]


def test_settings_reject_heartbeat_interval_that_cannot_safely_renew_lease():
    with pytest.raises(ValidationError, match="EXPORT_LEASE_HEARTBEAT_SECONDS"):
        Settings(
            _env_file=None,
            export_stale_minutes=1,
            export_lease_heartbeat_seconds=21,
        )


def test_settings_require_complete_s3_credentials_and_safe_prefix():
    with pytest.raises(ValidationError, match="must be set together"):
        Settings(_env_file=None, export_s3_access_key_id="access-only")
    with pytest.raises(ValidationError, match="relative object prefix"):
        Settings(_env_file=None, export_s3_prefix="../escape")

    production_database = Settings(
        _env_file=None,
        app_env="production",
        export_execution_mode="worker",
    )
    assert not production_database.export_storage_configured
    production_s3 = Settings(
        _env_file=None,
        app_env="production",
        export_execution_mode="worker",
        export_storage_backend="s3",
        export_s3_bucket="blueprints",
    )
    assert production_s3.export_storage_configured


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
    assert "p['database_backend']=='postgresql'" in workflow
    assert "p['export_execution']=='worker'" in workflow
    assert "p['artifact_storage']=='filesystem'" in workflow
    assert "p['artifact_storage_status']=='ready'" in workflow
    assert "grep -c '^worker$'" in workflow
    assert "Exercise PostgreSQL multi-worker fencing" in workflow
    assert "--scale worker=2 worker" in workflow
    assert "docker inspect --format '{{.State.Health.Status}}'" in workflow
    assert "python -m app.workers.export_worker_acceptance" in workflow
    assert "output/export-worker-acceptance.json" in workflow
    assert "p['parallel_job_count']==12" in workflow
    assert "p['exactly_once_job_count']==12" in workflow
    assert "p['stale_attempt_count']==2" in workflow
    assert "p['stale_write_rejected'] is True" in workflow
    assert "p['fresh_heartbeat_preserved'] is True" in workflow
    assert "p['database_content_empty'] is True" in workflow
    assert "pg_dump --clean --if-exists --no-owner" in workflow
    assert "sap_blueprint_restore" in workflow
    assert "20260810_0008 (head)" in workflow
    assert 'test "$restored_head" = "20260810_0008"' in workflow
    assert workflow.count("aquasecurity/trivy-action@v0.36.0") == 4
    assert "output/sap-ai-flow-api.cdx.json" in workflow
    assert "output/sap-ai-flow-web.cdx.json" in workflow
    assert workflow.count("actions/checkout@v5") == 4
    assert workflow.count("actions/setup-python@v6") == 2
    assert "actions/setup-node@v5" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "severity: CRITICAL" in workflow
    assert "ignore-unfixed: true" in workflow
    assert 'exit-code: "1"' in workflow
    assert "down --volumes --remove-orphans" in workflow


def test_ci_renders_docx_with_libreoffice_poppler_and_chinese_fonts():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "  docx-render:" in workflow
    assert "libreoffice-writer poppler-utils fonts-noto-cjk" in workflow
    assert "scripts/verify_docx_render.py --output-dir output/docx-render-qa" in workflow
    assert "name: docx-render-qa" in workflow
    assert "if-no-files-found: warn" in workflow


def test_capacity_harness_has_release_metrics_and_safety_guards():
    script = (ROOT / "scripts" / "run_capacity_test.ps1").read_text(encoding="utf-8")

    assert "AllowDataCreation" in script
    assert "A Bearer token is required for non-loopback targets" in script
    assert "without credentials, query, or fragment" in script
    assert "EnableExternalModel" in script
    assert "RequireExternalProvider" in script
    assert "RequirePostgreSQL" in script
    assert "database_backend" in script
    assert "MaxErrorRatePercent" in script
    assert "MaxP95Ms" in script
    assert "MaxP99Ms" in script
    assert "model_calls" in script
    assert "reported_model_calls" in script
    assert "cache_status" in script
    assert "capacity-report-" in script
    assert "capacity-samples-" in script
