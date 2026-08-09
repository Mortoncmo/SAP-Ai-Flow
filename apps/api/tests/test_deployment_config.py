from pathlib import Path

import yaml

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
    assert "ports" not in api
    assert api["expose"] == ["8000"]
    assert web["healthcheck"]["test"][0] == "CMD-SHELL"
    assert "/health/ready" in web["healthcheck"]["test"][1]


def test_api_image_and_nginx_keep_delivery_guards_enabled():
    api_dockerfile = (ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")

    assert api_dockerfile.index("USER app") < api_dockerfile.index("CMD [")
    assert "alembic upgrade head" in api_dockerfile
    assert "client_max_body_size 2m" in nginx
    assert "proxy_read_timeout 45s" in nginx
    assert "proxy_connect_timeout 3s" in nginx
