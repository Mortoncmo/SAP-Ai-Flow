from collections import defaultdict, deque

from app.models.graph import GraphDocument, NodeType


def graph_warnings(graph: GraphDocument) -> list[str]:
    warnings: list[str] = []
    start_ids = {node.id for node in graph.nodes if node.type == NodeType.START}
    end_ids = {node.id for node in graph.nodes if node.type == NodeType.END}

    if not start_ids:
        warnings.append("流程缺少开始节点。")
    if not end_ids:
        warnings.append("流程缺少结束节点。")

    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        outgoing[edge.source].append(edge.target)
        incoming[edge.target].append(edge.source)

    isolated = [
        node.label
        for node in graph.nodes
        if not incoming[node.id] and not outgoing[node.id] and len(graph.nodes) > 1
    ]
    if isolated:
        warnings.append(f"存在孤立节点：{'、'.join(isolated[:5])}。")

    if start_ids:
        reachable = set(start_ids)
        queue = deque(start_ids)
        while queue:
            current = queue.popleft()
            for target in outgoing[current]:
                if target not in reachable:
                    reachable.add(target)
                    queue.append(target)
        unreachable = [node.label for node in graph.nodes if node.id not in reachable]
        if unreachable:
            warnings.append(f"存在从开始节点不可达的节点：{'、'.join(unreachable[:5])}。")

    for node in graph.nodes:
        if node.type == NodeType.DECISION and len(outgoing[node.id]) < 2:
            warnings.append(f"判断节点“{node.label}”少于两条出边。")

    if _has_cycle(graph):
        warnings.append("流程中存在回路，请确认是否为预期的业务回退。")

    return warnings


def _has_cycle(graph: GraphDocument) -> bool:
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        outgoing[edge.source].append(edge.target)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        if any(visit(target) for target in outgoing[node_id]):
            return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node.id) for node in graph.nodes if node.id not in visited)
