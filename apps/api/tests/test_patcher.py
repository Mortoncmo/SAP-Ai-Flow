import pytest

from app.core.errors import PatchError
from app.graph.patcher import apply_patch
from app.models.graph import NodeType
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
