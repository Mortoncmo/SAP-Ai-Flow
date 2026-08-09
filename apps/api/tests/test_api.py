from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import get_database
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_safe_503_when_database_is_unavailable():
    class UnavailableEngine:
        def connect(self):
            raise SQLAlchemyError("postgresql://user:secret-password@private-host/database")

    class UnavailableDatabase:
        engine = UnavailableEngine()

    app.dependency_overrides[get_database] = lambda: UnavailableDatabase()
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_database, None)

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "provider": "local",
        "authentication": "development",
        "database": "unavailable",
    }
    assert "secret-password" not in response.text


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


def test_local_provider_adds_updates_and_removes_edges_without_changing_other_objects(
    order_graph,
):
    graph = order_graph.model_dump(mode="json")
    original_node_ids = [node["id"] for node in graph["nodes"]]

    added = client.post(
        "/api/v1/flowcharts/modify",
        json={
            "request_id": "request-edge-add",
            "current_graph": graph,
            "instruction": "连接开始到结束",
            "locale": "zh-CN",
        },
    )
    assert added.status_code == 200, added.text
    graph = added.json()["graph"]
    direct = next(
        edge
        for edge in graph["edges"]
        if edge["source"] == "start" and edge["target"] == "end"
    )

    updated = client.post(
        "/api/v1/flowcharts/modify",
        json={
            "request_id": "request-edge-update",
            "current_graph": graph,
            "instruction": "把开始到结束的连线标签改为快速通道",
            "locale": "zh-CN",
        },
    )
    assert updated.status_code == 200, updated.text
    graph = updated.json()["graph"]
    changed = next(edge for edge in graph["edges"] if edge["id"] == direct["id"])
    assert changed["label"] == "快速通道"

    removed = client.post(
        "/api/v1/flowcharts/modify",
        json={
            "request_id": "request-edge-remove",
            "current_graph": graph,
            "instruction": "删除开始到结束的连线",
            "locale": "zh-CN",
        },
    )
    assert removed.status_code == 200, removed.text
    result = removed.json()["graph"]
    assert all(edge["id"] != direct["id"] for edge in result["edges"])
    assert [node["id"] for node in result["nodes"]] == original_node_ids
    assert result["lanes"] == graph["lanes"]


def test_local_provider_rejects_duplicate_missing_and_ambiguous_edges(order_graph):
    graph = order_graph.model_dump(mode="json")
    duplicate = client.post(
        "/api/v1/flowcharts/modify",
        json={
            "request_id": "request-edge-duplicate",
            "current_graph": graph,
            "instruction": "连接信用检查到仓库出库",
            "locale": "zh-CN",
        },
    )
    assert duplicate.status_code == 502
    assert duplicate.json()["error"]["code"] == "INSTRUCTION_EDGE_ALREADY_EXISTS"

    missing = client.post(
        "/api/v1/flowcharts/modify",
        json={
            "request_id": "request-edge-missing",
            "current_graph": graph,
            "instruction": "删除开始到结束的连线",
            "locale": "zh-CN",
        },
    )
    assert missing.status_code == 502
    assert missing.json()["error"]["code"] == "INSTRUCTION_EDGE_NOT_FOUND"

    graph["edges"].append(
        {
            "id": "e3_alternative",
            "source": "credit",
            "target": "ship",
            "label": "备选",
        }
    )
    ambiguous = client.post(
        "/api/v1/flowcharts/modify",
        json={
            "request_id": "request-edge-ambiguous",
            "current_graph": graph,
            "instruction": "把信用检查到仓库出库的连线标签改为已批准",
            "locale": "zh-CN",
        },
    )
    assert ambiguous.status_code == 502
    assert ambiguous.json()["error"]["code"] == "INSTRUCTION_EDGE_AMBIGUOUS"


def test_local_provider_creates_mm_p2p_blueprint_with_pending_sap_metadata():
    response = client.post(
        "/api/v1/flowcharts/modify",
        json={
            "request_id": "request-p2p-blueprint",
            "current_graph": {
                "schema_version": "2.0",
                "graph_id": "empty-p2p",
                "version": 0,
                "title": "P2P 流程",
                "module": "MM",
                "process_scope": "P2P",
                "sap_context": {},
                "direction": "LR",
                "nodes": [],
                "edges": [],
                "lanes": [],
                "layout": {},
            },
            "instruction": "创建直接物料 P2P 流程",
            "locale": "zh-CN",
        },
    )

    assert response.status_code == 200, response.text
    graph = response.json()["graph"]
    assert graph["schema_version"] == "2.0"
    assert [lane["label"] for lane in graph["lanes"]] == [
        "需求部门",
        "审批人",
        "采购部门",
        "仓库",
        "财务",
    ]
    purchase_order = next(node for node in graph["nodes"] if node["label"] == "创建采购订单")
    assert purchase_order["sap"]["step_type"] == "transaction"
    assert purchase_order["sap"]["tcodes"][0] == {
        "code": "ME21N",
        "status": "pending_confirmation",
        "evidence_ref": None,
    }


def test_ten_sequential_modifications_preserve_unrelated_ids(order_graph):
    graph = order_graph.model_dump(mode="json")
    original_node_ids = {node["label"]: node["id"] for node in graph["nodes"]}
    stable_edge_ids = {"e1", "e2", "e4", "e5"}
    instructions = (
        "增加一个财务泳道",
        "增加一个合规泳道",
        "把信用检查移动到财务泳道",
        "给信用检查增加盾牌图标",
        "在信用检查后增加经理审批",
        "把经理审批改名为部门审批",
        "在仓库出库前增加库存确认",
        "给仓库出库增加卡车图标",
        "把提交销售订单改名为创建销售订单",
        "删除合规泳道",
    )

    for index, instruction in enumerate(instructions, start=1):
        response = client.post(
            "/api/v1/flowcharts/modify",
            json={
                "request_id": f"request-ten-rounds-{index}",
                "current_graph": graph,
                "instruction": instruction,
                "locale": "zh-CN",
            },
        )
        assert response.status_code == 200, f"{instruction}: {response.text}"
        graph = response.json()["graph"]

    assert graph["version"] == order_graph.version + len(instructions)
    current_nodes = {node["id"]: node for node in graph["nodes"]}
    assert set(original_node_ids.values()).issubset(current_nodes)
    assert current_nodes[original_node_ids["开始"]]["label"] == "开始"
    assert current_nodes[original_node_ids["结束"]]["label"] == "结束"
    assert current_nodes[original_node_ids["提交销售订单"]]["label"] == "创建销售订单"
    assert current_nodes[original_node_ids["信用检查"]]["icon"] == "shield-check"
    assert current_nodes[original_node_ids["仓库出库"]]["icon"] == "truck"
    assert {edge["id"] for edge in graph["edges"]}.issuperset(stable_edge_ids)
    assert [lane["label"] for lane in graph["lanes"]] == ["财务"]
    assert order_graph.version == 2
    assert [node.label for node in order_graph.nodes] == [
        "开始",
        "提交销售订单",
        "信用检查",
        "仓库出库",
        "结束",
    ]
