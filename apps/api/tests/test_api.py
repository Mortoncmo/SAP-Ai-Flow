from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_local_provider_modifies_graph(order_graph):
    response = client.post(
        "/api/v1/flowcharts/modify",
        json={
            "request_id": "request-test",
            "current_graph": order_graph.model_dump(mode="json"),
            "instruction": "在信用检查后增加经理审批",
            "locale": "zh-CN",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["base_version"] == 2
    assert payload["graph"]["version"] == 3
    assert any(node["label"] == "经理审批" for node in payload["graph"]["nodes"])
    assert payload["metrics"]["provider"] == "local"


def test_invalid_request_uses_stable_error_shape(order_graph):
    payload = {
        "request_id": "request-test",
        "current_graph": order_graph.model_dump(mode="json"),
        "instruction": "",
    }
    response = client.post("/api/v1/flowcharts/modify", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_FAILED"
