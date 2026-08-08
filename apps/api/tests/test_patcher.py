import pytest

from app.core.errors import PatchError
from app.graph.patcher import apply_patch
from app.models.graph import NodeType, Swimlane
from app.models.patch import LLMPatch


def test_insert_node_with_temporary_reference(order_graph):
    patch = LLMPatch.model_validate(
        {
            "change_summary": "增加经理审批",
            "operations": [
                {
                    "op": "add_node",
                    "ref": "approval",
                    "node": {"type": "task", "label": "经理审批"},
                },
                {"op": "remove_edge", "id": "e3"},
                {
                    "op": "add_edge",
                    "edge": {"source": "credit", "target": "@approval", "label": "通过"},
                },
                {
                    "op": "add_edge",
                    "edge": {"source": "@approval", "target": "ship"},
                },
            ],
        }
    )

    updated = apply_patch(order_graph, patch)

    approval = next(node for node in updated.nodes if node.label == "经理审批")
    assert approval.type == NodeType.TASK
    assert updated.version == 3
    assert any(edge.source == "credit" and edge.target == approval.id for edge in updated.edges)
    assert any(edge.source == approval.id and edge.target == "ship" for edge in updated.edges)
    assert order_graph.version == 2
    assert all(node.label != "经理审批" for node in order_graph.nodes)


def test_remove_node_cascades_edges_and_layout(order_graph):
    patch = LLMPatch.model_validate(
        {
            "change_summary": "删除信用检查",
            "operations": [{"op": "remove_node", "id": "credit"}],
        }
    )

    updated = apply_patch(order_graph, patch)

    assert all(node.id != "credit" for node in updated.nodes)
    assert all(edge.source != "credit" and edge.target != "credit" for edge in updated.edges)
    assert "credit" not in updated.layout


def test_patch_is_atomic_when_reference_is_invalid(order_graph):
    patch = LLMPatch.model_validate(
        {
            "change_summary": "非法引用",
            "operations": [
                {
                    "op": "add_node",
                    "ref": "temporary",
                    "node": {"type": "task", "label": "临时节点"},
                },
                {
                    "op": "add_edge",
                    "edge": {"source": "missing", "target": "@temporary"},
                },
            ],
        }
    )

    with pytest.raises(PatchError) as error:
        apply_patch(order_graph, patch)

    assert error.value.code == "PATCH_NODE_NOT_FOUND"
    assert len(order_graph.nodes) == 5
    assert order_graph.version == 2


def test_patch_creates_lane_and_assigns_node_with_icon(order_graph):
    patch = LLMPatch.model_validate(
        {
            "change_summary": "增加财务泳道并移动信用检查",
            "operations": [
                {
                    "op": "add_lane",
                    "ref": "finance",
                    "lane": {"label": "财务", "color": "#5b7394"},
                },
                {
                    "op": "update_node",
                    "id": "credit",
                    "changes": {"lane_id": "@finance", "icon": "shield-check"},
                },
            ],
        }
    )

    updated = apply_patch(order_graph, patch)

    finance = next(lane for lane in updated.lanes if lane.label == "财务")
    credit = next(node for node in updated.nodes if node.id == "credit")
    assert credit.lane_id == finance.id
    assert credit.icon.value == "shield-check"
    assert order_graph.lanes == []


def test_removing_lane_keeps_nodes_and_clears_assignment(order_graph):
    with_lane = order_graph.model_copy(
        update={
            "lanes": [Swimlane(id="lane_sales", label="销售", color="#52796f")],
            "nodes": [
                node.model_copy(update={"lane_id": "lane_sales"})
                if node.id == "submit"
                else node
                for node in order_graph.nodes
            ],
        }
    )
    with_lane = type(order_graph).model_validate(with_lane.model_dump())
    patch = LLMPatch.model_validate(
        {
            "change_summary": "删除销售泳道",
            "operations": [{"op": "remove_lane", "id": "lane_sales"}],
        }
    )

    updated = apply_patch(with_lane, patch)

    assert updated.lanes == []
    assert next(node for node in updated.nodes if node.id == "submit").lane_id is None
