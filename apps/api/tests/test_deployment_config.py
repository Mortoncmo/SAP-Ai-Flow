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
    prometheus = compose["services"]["prometheus"]
    alertmanager = compose["services"]["alertmanager"]
    alert_receiver = compose["services"]["alert-drill-receiver"]
    oidc_mock = compose["services"]["oidc-mock"]

    assert "sap_blueprint_dev" not in raw
    assert "EXPORT_ACCEPTANCE_RENDER_DELAY_SECONDS" not in raw
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
    assert api["environment"]["OIDC_TENANT_ID_CLAIM"] == "${OIDC_TENANT_ID_CLAIM:-tid}"
    assert api["environment"]["OIDC_ALLOWED_TENANT_IDS"] == "${OIDC_ALLOWED_TENANT_IDS:-}"
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
    assert prometheus["image"] == "prom/prometheus:v3.5.0"
    assert prometheus["profiles"] == ["monitoring"]
    assert prometheus["depends_on"]["api"]["condition"] == "service_healthy"
    assert prometheus["depends_on"]["alertmanager"]["condition"] == "service_started"
    assert "127.0.0.1:${PROMETHEUS_PORT:-9090}:9090" in prometheus["ports"]
    assert alertmanager["image"] == "prom/alertmanager:v0.28.1"
    assert alertmanager["profiles"] == ["monitoring"]
    assert "127.0.0.1:${ALERTMANAGER_PORT:-9093}:9093" in alertmanager["ports"]
    assert alertmanager["depends_on"]["alert-drill-receiver"]["condition"] == "service_healthy"
    assert alert_receiver["image"] == api["image"]
    assert alert_receiver["profiles"] == ["monitoring"]
    assert alert_receiver["read_only"] is True
    assert "app.monitoring.alert_drill_receiver" in alert_receiver["command"]
    assert "ports" not in alert_receiver
    assert alert_receiver["expose"] == ["8080"]
    assert oidc_mock["image"] == "ghcr.io/navikt/mock-oauth2-server:6.0.0"
    assert oidc_mock["profiles"] == ["oidc-acceptance"]
    assert "interactiveLogin" in oidc_mock["environment"]["JSON_CONFIG"]
    assert "ci-tenant" in oidc_mock["environment"]["JSON_CONFIG"]
    assert oidc_mock["ports"] == ["127.0.0.1:${OIDC_MOCK_PORT:-9080}:8080"]
    assert "prometheus-data" in compose["volumes"]
    assert "alertmanager-data" in compose["volumes"]


def test_settings_accept_compose_list_environment_values(monkeypatch):
    monkeypatch.setenv("OIDC_ALGORITHMS", "RS256,ES256")
    monkeypatch.setenv("OIDC_ALLOWED_TENANT_IDS", "tenant-a,tenant-b,tenant-a")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:8080,https://flow.example.com")

    settings = Settings(_env_file=None)

    assert settings.oidc_algorithms == ["RS256", "ES256"]
    assert settings.oidc_allowed_tenant_ids == ["tenant-a", "tenant-b"]
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


def test_settings_reject_invalid_tenant_identifiers():
    with pytest.raises(ValidationError, match="invalid tenant identifier"):
        Settings(_env_file=None, oidc_allowed_tenant_ids=["tenant-a\nforged"])


def test_browser_smoke_passes_cors_origin_in_supported_format():
    script = (ROOT / "scripts" / "browser_smoke.ps1").read_text(encoding="utf-8")

    assert '$env:CORS_ORIGINS = $BaseUrl' in script
    assert "ConvertTo-Json -InputObject @($BaseUrl)" not in script


def test_api_image_and_nginx_keep_delivery_guards_enabled():
    api_dockerfile = (ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    web_dockerfile = (ROOT / "apps" / "web" / "Dockerfile").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")

    assert api_dockerfile.index("USER app") < api_dockerfile.index("CMD [")
    assert "mkdir -p /app/data/chroma /app/data/exports" in api_dockerfile
    assert "chown -R app:app /app/data" in api_dockerfile
    assert "alembic upgrade head" in api_dockerfile
    assert "FROM nginx:1.29-alpine" in web_dockerfile
    assert "client_max_body_size 2m" in nginx
    assert "proxy_read_timeout 45s" in nginx
    assert "proxy_connect_timeout 3s" in nginx
    assert "location = /internal/metrics" in nginx
    assert "return 404;" in nginx


def test_prometheus_scrape_and_alert_rules_are_low_cardinality_and_threshold_aligned():
    prometheus = yaml.safe_load(
        (ROOT / "deploy" / "monitoring" / "prometheus.yml").read_text(encoding="utf-8")
    )
    alerts = yaml.safe_load(
        (ROOT / "deploy" / "monitoring" / "alerts.yml").read_text(encoding="utf-8")
    )
    alertmanager = yaml.safe_load(
        (ROOT / "deploy" / "monitoring" / "alertmanager.yml").read_text(encoding="utf-8")
    )

    scrape = prometheus["scrape_configs"][0]
    assert scrape["job_name"] == "sap-ai-flow-api"
    assert scrape["metrics_path"] == "/internal/metrics"
    assert scrape["static_configs"][0]["targets"] == ["api:8000"]
    assert prometheus["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"] == [
        "alertmanager:9093"
    ]
    rules = {rule["alert"]: rule for group in alerts["groups"] for rule in group["rules"]}
    assert set(rules) == {
        "SapAiFlowApiUnavailable",
        "SapAiFlowApiHighServerErrorRate",
        "SapAiFlowApiHighP95Latency",
    }
    error_expression = rules["SapAiFlowApiHighServerErrorRate"]["expr"]
    latency_expression = rules["SapAiFlowApiHighP95Latency"]["expr"]
    assert "sap_ai_flow_http_requests_total" in error_expression
    assert 'route=~"/api/.*"' in error_expression
    assert "> 0.01" in error_expression
    assert "sap_ai_flow_http_request_duration_seconds_bucket" in latency_expression
    assert "> 8" in latency_expression
    serialized = (error_expression + latency_expression).lower()
    assert all(label not in serialized for label in ("project_id", "user_id", "tenant_id"))
    assert alertmanager["route"]["receiver"] == "local-drill-webhook"
    assert set(alertmanager["route"]["group_by"]) == {"alertname", "severity"}
    assert alertmanager["route"]["repeat_interval"] == "4h"
    webhook = alertmanager["receivers"][0]["webhook_configs"][0]
    assert webhook == {
        "url": "http://alert-drill-receiver:8080/alerts",
        "send_resolved": True,
    }


def test_ci_exercises_compose_postgres_backup_and_restore():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "  deploy:" in workflow
    assert "docker compose -f deploy/docker-compose.yml build" in workflow
    assert "http://127.0.0.1:8080/health/ready" in workflow
    assert "p['database_backend']=='postgresql'" in workflow
    assert "p['tenant_isolation']=='oidc_claim_allowlist'" in workflow
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
    assert "OIDC_ALLOWED_TENANT_IDS: ci-tenant" in workflow
    assert "COMPOSE_PROFILES: oidc-acceptance" in workflow
    assert "ghcr.io/navikt/mock-oauth2-server:6.0.0" in (
        ROOT / "deploy" / "docker-compose.yml"
    ).read_text(encoding="utf-8")
    assert "Exercise OIDC authorization code and tenant flow" in workflow
    assert "oidc_browser_acceptance.js" in workflow
    assert "output/oidc-acceptance.json" in workflow
    assert "authorization_code_pkce" in workflow
    assert "[REDACTED]" in workflow
    assert "run-code --filename scripts/oidc_browser_acceptance.js" in workflow
    assert "--raw run-code" not in workflow
    assert "OIDC_BROWSER_RESULT" not in workflow
    assert "output/oidc-browser-cli.log" in workflow
    oidc_acceptance = (ROOT / "scripts" / "oidc_browser_acceptance.js").read_text(
        encoding="utf-8"
    )
    assert "new URL(page.url())" not in oidc_acceptance
    assert "new URL(window.location.href)" in oidc_acceptance
    assert "status: 'passed'" in oidc_acceptance
    assert "throw new Error(`[${stage}] on ${pagePath}" in oidc_acceptance
    assert "page.once('dialog'" in oidc_acceptance
    assert "prompt.accept(projectName)" in oidc_acceptance
    assert "output/oidc-failure.png" in oidc_acceptance
    assert "EXPORT_STALE_MINUTES: 1" in workflow
    assert "EXPORT_LEASE_HEARTBEAT_SECONDS: 5" in workflow
    assert "20260810_0009 (head)" in workflow
    assert 'test "$restored_head" = "20260810_0009"' in workflow
    assert workflow.count("aquasecurity/trivy-action@v0.36.0") == 4
    assert "output/sap-ai-flow-api.cdx.json" in workflow
    assert "output/sap-ai-flow-web.cdx.json" in workflow
    assert workflow.count("actions/checkout@v5") == 4
    assert workflow.count("actions/setup-python@v6") == 2
    assert "actions/setup-node@v5" in workflow
    assert workflow.count("actions/upload-artifact@v7") == 4
    assert "Upload OIDC browser failure evidence" in workflow
    assert "tracing-start" in workflow
    assert "tracing-stop" in workflow
    assert ".playwright-cli/traces" in workflow
    assert "output/oidc-failure.png" in workflow
    assert "include-hidden-files: true" in workflow
    assert "severity: CRITICAL" in workflow
    assert "ignore-unfixed: true" in workflow
    assert 'exit-code: "1"' in workflow
    assert "down --volumes --remove-orphans" in workflow
    assert "Validate Prometheus and Alertmanager configuration" in workflow
    assert "promtool" in workflow
    assert "check config /etc/prometheus/prometheus.yml" in workflow
    assert "check rules /etc/prometheus/alerts.yml" in workflow
    assert "amtool" in workflow
    assert "check-config /etc/alertmanager/alertmanager.yml" in workflow
    assert "Exercise Alertmanager notification routing" in workflow
    assert "/api/v2/alerts" in workflow
    assert "output/alertmanager-drill.json" in workflow
    assert "SapAiFlowAcceptanceDrill" in workflow
    assert "deployment-acceptance" in workflow
    assert "Exercise rolling interruption recovery for a long DOCX task" in workflow
    assert "export_worker_interruption_acceptance prepare" in workflow
    assert "EXPORT_ACCEPTANCE_RENDER_DELAY_SECONDS=90" in workflow
    assert "docker kill sap-ai-flow-interrupted-worker" in workflow
    assert "sleep 65" in workflow
    assert "export_worker_interruption_acceptance" in workflow
    assert "output/export-worker-interruption.json" in workflow
    assert "p['long_document_node_count']==80" in workflow
    assert "p['interrupted_attempt_count']==2" in workflow


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


def test_s3_acceptance_harness_has_write_retention_and_redaction_guards():
    script = (ROOT / "scripts" / "verify_s3_storage.py").read_text(encoding="utf-8")
    acceptance = (
        ROOT / "apps" / "api" / "app" / "documents" / "s3_acceptance.py"
    ).read_text(encoding="utf-8")

    assert "--allow-write" in script
    assert "EXPORT_STORAGE_BACKEND must be s3" in script
    assert 'head.get("ServerSideEncryption") != "AES256"' in acceptance
    assert "get_bucket_versioning" in acceptance
    assert "get_bucket_lifecycle_configuration" in acceptance
    assert "S3 probe object is still readable after deletion" in acceptance
    assert '"bucket": store.bucket' not in acceptance
    assert '"prefix": store.prefix' not in acceptance
    assert "_redacted_target_ref" in acceptance
    assert "noncurrent probe versions remain" in acceptance
