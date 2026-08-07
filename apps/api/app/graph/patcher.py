from copy import deepcopy

from app.core.errors import PatchError
from app.graph.ids import new_id
from app.models.graph import Edge, GraphDocument, Node
from app.models.patch import LLMPatch


def apply_patch(current: GraphDocument, patch: LLMPatch) -> GraphDocument:
    working = current.model_copy(deep=True)
    refs: dict[str, str] = {}

    for index, operation in enumerate(patch.operations):
        try:
            if operation.op == "add_node":
                if operation.ref in refs:
                    raise PatchError(
                        "PATCH_DUPLICATE_REFERENCE",
                        f"临时引用 @{operation.ref} 重复。",
                    )
                node_id = new_id("node")
                refs[operation.ref] = node_id
                working.nodes.append(
                    Node(
                        id=node_id,
                        type=operation.node.type,
                        label=operation.node.label,
                        description=operation.node.description,
                    )
                )
            elif operation.op == "remove_node":
                _require_node(working, operation.id)
                working.nodes = [node for node in working.nodes if node.id != operation.id]
                working.edges = [
                    edge
                    for edge in working.edges
                    if edge.source != operation.id and edge.target != operation.id
                ]
                working.layout.pop(operation.id, None)
            elif operation.op == "update_node":
                node = _require_node(working, operation.id)
                changes = operation.changes.model_dump(exclude_unset=True)
                updated = node.model_copy(update=changes)
                working.nodes = [updated if item.id == node.id else item for item in working.nodes]
            elif operation.op == "add_edge":
                source = _resolve_reference(operation.edge.source, refs)
                target = _resolve_reference(operation.edge.target, refs)
                _require_node(working, source)
                _require_node(working, target)
                if source == target:
                    raise PatchError("PATCH_SELF_EDGE", "不允许节点连接自身。")
                candidate = (source, target, operation.edge.label or "")
                existing = {(edge.source, edge.target, edge.label or "") for edge in working.edges}
                if candidate in existing:
                    raise PatchError("PATCH_DUPLICATE_EDGE", "不允许添加重复连线。")
                working.edges.append(
                    Edge(
                        id=new_id("edge"),
                        source=source,
                        target=target,
                        label=operation.edge.label,
                    )
                )
            elif operation.op == "remove_edge":
                if not any(edge.id == operation.id for edge in working.edges):
                    raise PatchError(
                        "PATCH_EDGE_NOT_FOUND",
                        f"连线 {operation.id} 不存在。",
                    )
                working.edges = [edge for edge in working.edges if edge.id != operation.id]
        except PatchError as exc:
            exc.details["operation_index"] = index
            raise

    try:
        return GraphDocument.model_validate(
            {
                **working.model_dump(),
                "version": current.version + 1,
            }
        )
    except ValueError as exc:
        raise PatchError(
            "PATCH_GRAPH_INVALID",
            "Patch 应用后图结构无效。",
            details={"reason": str(exc)},
        ) from exc


def _resolve_reference(value: str, refs: dict[str, str]) -> str:
    if not value.startswith("@"):
        return value
    ref = value[1:]
    if ref not in refs:
        raise PatchError(
            "PATCH_REFERENCE_NOT_FOUND",
            f"临时引用 @{ref} 不存在或尚未声明。",
            details={"reference": value},
        )
    return refs[ref]


def _require_node(graph: GraphDocument, node_id: str) -> Node:
    node = next((item for item in graph.nodes if item.id == node_id), None)
    if node is None:
        raise PatchError(
            "PATCH_NODE_NOT_FOUND",
            f"节点 {node_id} 不存在。",
            details={"node_id": node_id},
        )
    return node
