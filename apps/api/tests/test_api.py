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


def test_local_provider_creates_lane_and_moves_node(order_graph):
    create_response = client.post(
        "/api/v1/flowcharts/modify",
        json={
            "request_id": "request-lane-create",
            "current_graph": order_graph.model_dump(mode="json"),
            "instruction": "增加一个财务泳道",
            "locale": "zh-CN",
        },
    )
    created_graph = create_response.json()["graph"]
    finance = next(lane for lane in created_graph["lanes"] if lane["label"] == "财务")

    move_response = client.post(
        "/api/v1/flowcharts/modify",
        json={
            "request_id": "request-lane-move",
            "current_graph": created_graph,
            "instruction": "把信用检查移动到财务泳道",
            "locale": "zh-CN",
        },
    )

    assert create_response.status_code == 200, create_response.text
    assert move_response.status_code == 200, move_response.text
    credit = next(node for node in move_response.json()["graph"]["nodes"] if node["id"] == "credit")
    assert credit["lane_id"] == finance["id"]


def test_local_provider_sets_supported_node_icon(order_graph):
    response = client.post(
        "/api/v1/flowcharts/modify",
        json={
            "request_id": "request-node-icon",
            "current_graph": order_graph.model_dump(mode="json"),
            "instruction": "给信用检查增加盾牌图标",
            "locale": "zh-CN",
        },
    )

    assert response.status_code == 200, response.text
    credit = next(node for node in response.json()["graph"]["nodes"] if node["id"] == "credit")
    assert credit["icon"] == "shield-check"


def test_local_provider_creates_multiple_lanes_without_adding_process_nodes(order_graph):
    original_node_ids = [node.id for node in order_graph.nodes]
    instructions = (
        "三个泳道，销售、物流、财务",
        "增加泳道：销售、物流、财务",
        "新增销售、物流、财务三个泳道",
        "请帮我增加三个泳道：销售、物流、财务",
    )

    for index, instruction in enumerate(instructions):
        response = client.post(
            "/api/v1/flowcharts/modify",
            json={
                "request_id": f"request-multiple-lanes-{index}",
                "current_graph": order_graph.model_dump(mode="json"),
                "instruction": instruction,
                "locale": "zh-CN",
            },
        )

        assert response.status_code == 200, response.text
        graph = response.json()["graph"]
        assert [lane["label"] for lane in graph["lanes"]] == ["销售", "物流", "财务"]
        assert [node["id"] for node in graph["nodes"]] == original_node_ids


def test_unrecognized_swimlane_instruction_never_falls_back_to_process_node(order_graph):
    response = client.post(
        "/api/v1/flowcharts/modify",
        json={
            "request_id": "request-invalid-lane",
            "current_graph": order_graph.model_dump(mode="json"),
            "instruction": "调整一下泳道",
            "locale": "zh-CN",
        },
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "INSTRUCTION_SWIMLANE_INVALID"
