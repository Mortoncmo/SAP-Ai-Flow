import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.api.routes.flowcharts import get_provider
from app.core.logging import JsonLogFormatter, request_id
from app.main import app


def log_payloads(captured: str) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for line in captured.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "event" in payload:
            payloads.append(payload)
    return payloads


def test_json_formatter_redacts_secret_fields_and_tokens():
    record = logging.LogRecord("sap_ai_flow", logging.INFO, __file__, 1, "security.event", (), None)
    record.event_fields = {
        "authorization": "Bearer raw-access-token-123456",
        "api_key": "sk-supersecretvalue123456",
        "note": "token Bearer another-secret-token-123456",
        "email": "consultant@example.com",
    }

    serialized = JsonLogFormatter().format(record)
    for raw_value in (
        "raw-access-token-123456",
        "sk-supersecretvalue123456",
        "another-secret-token-123456",
        "consultant@example.com",
    ):
        assert raw_value not in serialized
    assert "[SECRET_" in serialized
    assert "[EMAIL_" in serialized


def test_request_id_accepts_safe_values_and_rejects_log_injection():
    assert request_id("trace-123") == "trace-123"
    generated = request_id("trace-123\nforged-event")
    assert generated.startswith("request_")
    assert "\n" not in generated


def test_chroma_http_api_is_not_exposed():
    exposed_paths = {getattr(route, "path", "") for route in app.routes}
    assert not any(path.startswith("/api/v2") for path in exposed_paths)


def formatted_logs(caplog) -> str:
    formatter = JsonLogFormatter()
    return "\n".join(
        formatter.format(record) for record in caplog.records if record.name == "sap_ai_flow"
    )


@pytest.fixture
def app_logs(caplog):
    logger = logging.getLogger("sap_ai_flow")
    caplog.handler.setLevel(logging.INFO)
    logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


def test_request_log_uses_route_template_without_headers_or_query(app_logs):
    client = TestClient(app)
    response = client.get(
        "/health/live?email=secret@example.com",
        headers={
            "Authorization": "Bearer raw-access-token-123456",
            "X-Request-ID": "trace-health-1",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-health-1"
    captured = formatted_logs(app_logs)
    assert "secret@example.com" not in captured
    assert "raw-access-token-123456" not in captured
    completed = next(item for item in log_payloads(captured) if item["event"] == "request.completed")
    assert completed == {
        "timestamp": completed["timestamp"],
        "level": "info",
        "event": "request.completed",
        "request_id": "trace-health-1",
        "method": "GET",
        "route": "/health/live",
        "status_code": 200,
        "latency_ms": completed["latency_ms"],
    }


def test_internal_metrics_use_route_templates_without_resource_ids_or_queries():
    client = TestClient(app)
    resource_id = "project_metrics_secret_123"
    query_secret = "metrics-secret@example.com"

    missing = client.get(
        f"/api/v1/projects/{resource_id}?email={query_secret}",
        headers={"X-User-ID": "metrics-user"},
    )
    metrics = client.get("/internal/metrics")

    assert missing.status_code == 404
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert "sap_ai_flow_http_requests_total" in metrics.text
    assert "sap_ai_flow_http_request_duration_seconds_bucket" in metrics.text
    assert "sap_ai_flow_http_requests_in_progress" in metrics.text
    assert "sap_ai_flow_http_requests_in_progress 0.0" in metrics.text
    assert 'route="/api/v1/projects/{project_id}"' in metrics.text
    assert 'status_code="404"' in metrics.text
    assert resource_id not in metrics.text
    assert query_secret not in metrics.text
    assert "/internal/metrics" not in app.openapi()["paths"]


def test_validation_errors_do_not_echo_original_request_input(app_logs):
    client = TestClient(app)
    response = client.post(
        "/api/v1/flowcharts/modify",
        json={
            "request_id": "validation-sensitive",
            "instruction": "联系 secret@example.com，金额 100 万元",
        },
        headers={"X-Request-ID": "trace-validation-1"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["request_id"] == "trace-validation-1"
    errors = response.json()["error"]["details"]["errors"]
    assert errors
    assert all("input" not in item and "ctx" not in item for item in errors)
    serialized_response = response.text
    captured = formatted_logs(app_logs)
    assert "secret@example.com" not in serialized_response
    assert "100 万元" not in serialized_response
    assert "secret@example.com" not in captured
    assert "100 万元" not in captured


def test_unhandled_provider_error_returns_generic_response_and_safe_log(order_graph, app_logs):
    class ExplodingProvider:
        external = False

        async def generate_patch(self, *_args, **_kwargs):
            raise RuntimeError(
                "upstream leaked secret@example.com and Bearer raw-access-token-123456"
            )

    app.dependency_overrides[get_provider] = lambda: ExplodingProvider()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/flowcharts/modify",
            json={
                "request_id": "provider-failure",
                "current_graph": order_graph.model_dump(mode="json"),
                "instruction": "增加审批",
                "locale": "zh-CN",
            },
            headers={
                "X-Request-ID": "trace-provider-1",
                "Origin": "http://localhost:5173",
            },
        )
    finally:
        app.dependency_overrides.pop(get_provider, None)

    assert response.status_code == 500
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "服务处理请求时发生内部错误。",
            "request_id": "trace-provider-1",
            "details": {},
        }
    }
    captured = formatted_logs(app_logs)
    assert "secret@example.com" not in captured
    assert "raw-access-token-123456" not in captured
    failed = next(item for item in log_payloads(captured) if item["event"] == "request.failed")
    assert failed["exception_type"] in {"RuntimeError", "ExceptionGroup"}
    assert failed["route"] == "/api/v1/flowcharts/modify"
    assert failed["request_id"] == "trace-provider-1"
    assert isinstance(failed["stack"], list)
