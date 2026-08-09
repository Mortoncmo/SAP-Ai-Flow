
from app.core.errors import PatchError
from app.graph.ids import new_id
from app.models.graph import Edge, GraphDocument, Node, Swimlane
from app.models.patch import LLMPatch


def apply_patch(current: GraphDocument, patch: LLMPatch) -> GraphDocument:
    working = current.model_copy(deep=True)
    refs: dict[str, str] = {}

    for index, operation in enumerate(patch.operations):
        try:
            if operation.op == "add_node":
                _require_unused_reference(operation.ref, refs)
                node_id = new_id("node")
                refs[operation.ref] = node_id
                lane_id = _resolve_optional_reference(operation.node.lane_id, refs)
                if lane_id is not None:
                    _require_lane(working, lane_id)
                working.nodes.append(
                    Node(
                        id=node_id,
                        type=operation.node.type,
                        label=operation.node.label,
                        description=operation.node.description,
                        icon=operation.node.icon,
                        lane_id=lane_id,
                        sap=operation.node.sap,
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
                if "lane_id" in changes and changes["lane_id"] is not None:
                    changes["lane_id"] = _resolve_reference(changes["lane_id"], refs)
                    _require_lane(working, changes["lane_id"])
                updated = Node.model_validate({**node.model_dump(mode="python"), **changes})
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
            elif operation.op == "add_lane":
                _require_unused_reference(operation.ref, refs)
                lane_id = new_id("lane")
                refs[operation.ref] = lane_id
                working.lanes.append(
                    Swimlane(
                        id=lane_id,
                        label=operation.lane.label,
                        color=operation.lane.color,
                    )
                )
            elif operation.op == "update_lane":
                lane = _require_lane(working, operation.id)
                updated = lane.model_copy(
                    update=operation.changes.model_dump(exclude_unset=True)
                )
                working.lanes = [updated if item.id == lane.id else item for item in working.lanes]
            elif operation.op == "remove_lane":
                lane = _require_lane(working, operation.id)
                working.lanes = [item for item in working.lanes if item.id != lane.id]
                working.nodes = [
                    node.model_copy(update={"lane_id": None})
                    if node.lane_id == lane.id
                    else node
                    for node in working.nodes
                ]
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


def _resolve_optional_reference(value: str | None, refs: dict[str, str]) -> str | None:
    return _resolve_reference(value, refs) if value is not None else None


def _require_unused_reference(ref: str, refs: dict[str, str]) -> None:
    if ref in refs:
        raise PatchError(
            "PATCH_DUPLICATE_REFERENCE",
            f"临时引用 @{ref} 重复。",
        )


def _require_node(graph: GraphDocument, node_id: str) -> Node:
    node = next((item for item in graph.nodes if item.id == node_id), None)
    if node is None:
        raise PatchError(
            "PATCH_NODE_NOT_FOUND",
            f"节点 {node_id} 不存在。",
            details={"node_id": node_id},
        )
    return node


def _require_lane(graph: GraphDocument, lane_id: str) -> Swimlane:
    lane = next((item for item in graph.lanes if item.id == lane_id), None)
    if lane is None:
        raise PatchError(
            "PATCH_LANE_NOT_FOUND",
            f"泳道 {lane_id} 不存在。",
            details={"lane_id": lane_id},
        )
    return lane
