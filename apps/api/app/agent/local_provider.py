import re

from app.agent.base import ProviderResult
from app.models.graph import GraphDocument, Node, NodeType
from app.models.patch import LLMPatch


class LocalRuleProvider:
    """Deterministic provider for local development and automated tests."""

    async def generate_patch(
        self,
        graph: GraphDocument,
        instruction: str,
        locale: str,
    ) -> ProviderResult:
        del locale
        patch = self._build_patch(graph, instruction.strip())
        return ProviderResult(patch=patch, provider="local", model="rule-engine-v1")

    def _build_patch(self, graph: GraphDocument, instruction: str) -> LLMPatch:
        if not graph.nodes or any(word in instruction for word in ("创建流程", "生成流程", "新建流程")):
            return self._create_flow(instruction)

        match = re.search(r"在(.+?)(?:之后|后面|后)增加(?:一个)?(.+?)(?:节点)?[。.!！]?$", instruction)
        if match:
            anchor = self._find_node(graph, match.group(1))
            label = self._clean_label(match.group(2))
            return self._insert_after(graph, anchor, label)

        match = re.search(r"在(.+?)(?:之前|前面|前)增加(?:一个)?(.+?)(?:节点)?[。.!！]?$", instruction)
        if match:
            anchor = self._find_node(graph, match.group(1))
            label = self._clean_label(match.group(2))
            return self._insert_before(graph, anchor, label)

        match = re.search(r"(?:删除|移除)(.+?)(?:节点)?[。.!！]?$", instruction)
        if match:
            node = self._find_node(graph, match.group(1))
            return LLMPatch(
                change_summary=f"删除“{node.label}”节点及其关联连线。",
                operations=[{"op": "remove_node", "id": node.id}],
            )

        match = re.search(r"(?:把|将)(.+?)(?:改名为|修改为|改成|改为)(.+?)[。.!！]?$", instruction)
        if match:
            node = self._find_node(graph, match.group(1))
            label = self._clean_label(match.group(2))
            return LLMPatch(
                change_summary=f"将“{node.label}”修改为“{label}”。",
                operations=[
                    {"op": "update_node", "id": node.id, "changes": {"label": label}}
                ],
            )

        match = re.search(r"(?:增加|添加)(?:一个)?(.+?)(?:节点)?[。.!！]?$", instruction)
        label = self._clean_label(match.group(1)) if match else self._clean_label(instruction)
        end_node = next((node for node in graph.nodes if node.type == NodeType.END), None)
        if end_node:
            return self._insert_before(graph, end_node, label)
        last_node = graph.nodes[-1]
        return self._insert_after(graph, last_node, label)

    def _create_flow(self, instruction: str) -> LLMPatch:
        candidates: list[tuple[str, NodeType]] = []
        keyword_steps = (
            ("需求", "提交业务需求", NodeType.TASK),
            ("采购", "创建采购申请", NodeType.TASK),
            ("订单", "提交销售订单", NodeType.TASK),
            ("信用", "信用检查", NodeType.DECISION),
            ("审批", "经理审批", NodeType.TASK),
            ("发货", "安排发货", NodeType.TASK),
            ("出库", "仓库出库", NodeType.TASK),
            ("开票", "开具发票", NodeType.TASK),
            ("付款", "客户付款", NodeType.TASK),
        )
        for keyword, label, node_type in keyword_steps:
            if keyword in instruction and all(item[0] != label for item in candidates):
                candidates.append((label, node_type))
        if not candidates:
            candidates = [("处理业务请求", NodeType.TASK), ("确认处理结果", NodeType.TASK)]

        nodes = [("start", "开始", NodeType.START), *[
            (f"step_{index}", label, node_type)
            for index, (label, node_type) in enumerate(candidates, start=1)
        ], ("end", "结束", NodeType.END)]

        operations: list[dict[str, object]] = []
        for ref, label, node_type in nodes:
            operations.append(
                {
                    "op": "add_node",
                    "ref": ref,
                    "node": {"type": node_type.value, "label": label},
                }
            )
        for index in range(len(nodes) - 1):
            edge: dict[str, object] = {
                "source": f"@{nodes[index][0]}",
                "target": f"@{nodes[index + 1][0]}",
            }
            if nodes[index][2] == NodeType.DECISION:
                edge["label"] = "通过"
            operations.append({"op": "add_edge", "edge": edge})
        return LLMPatch(
            change_summary="根据指令创建业务流程骨架。",
            operations=operations,
        )

    def _insert_after(self, graph: GraphDocument, anchor: Node, label: str) -> LLMPatch:
        outgoing = [edge for edge in graph.edges if edge.source == anchor.id]
        preferred = next(
            (edge for edge in outgoing if (edge.label or "") in {"通过", "是", "同意", "Yes"}),
            outgoing[0] if outgoing else None,
        )
        operations: list[dict[str, object]] = [
            {
                "op": "add_node",
                "ref": "new_step",
                "node": {"type": self._guess_type(label).value, "label": label},
            }
        ]
        if preferred:
            operations.append({"op": "remove_edge", "id": preferred.id})
            operations.append(
                {
                    "op": "add_edge",
                    "edge": {
                        "source": anchor.id,
                        "target": "@new_step",
                        "label": preferred.label,
                    },
                }
            )
            operations.append(
                {
                    "op": "add_edge",
                    "edge": {"source": "@new_step", "target": preferred.target},
                }
            )
        else:
            operations.append(
                {
                    "op": "add_edge",
                    "edge": {"source": anchor.id, "target": "@new_step"},
                }
            )
        return LLMPatch(
            change_summary=f"在“{anchor.label}”后增加“{label}”。",
            operations=operations,
        )

    def _insert_before(self, graph: GraphDocument, anchor: Node, label: str) -> LLMPatch:
        incoming = [edge for edge in graph.edges if edge.target == anchor.id]
        operations: list[dict[str, object]] = [
            {
                "op": "add_node",
                "ref": "new_step",
                "node": {"type": self._guess_type(label).value, "label": label},
            }
        ]
        if incoming:
            for edge in incoming:
                operations.append({"op": "remove_edge", "id": edge.id})
                operations.append(
                    {
                        "op": "add_edge",
                        "edge": {
                            "source": edge.source,
                            "target": "@new_step",
                            "label": edge.label,
                        },
                    }
                )
            operations.append(
                {
                    "op": "add_edge",
                    "edge": {"source": "@new_step", "target": anchor.id},
                }
            )
        else:
            operations.append(
                {
                    "op": "add_edge",
                    "edge": {"source": "@new_step", "target": anchor.id},
                }
            )
        return LLMPatch(
            change_summary=f"在“{anchor.label}”前增加“{label}”。",
            operations=operations,
        )

    @staticmethod
    def _find_node(graph: GraphDocument, fragment: str) -> Node:
        needle = fragment.strip("“”\"' ，,的")
        exact = next((node for node in graph.nodes if node.label == needle), None)
        partial = next(
            (node for node in graph.nodes if needle in node.label or node.label in needle),
            None,
        )
        node = exact or partial
        if node is None:
            from app.core.errors import ProviderError

            raise ProviderError(
                "INSTRUCTION_NODE_NOT_FOUND",
                f"没有找到与“{needle}”匹配的节点。",
            )
        return node

    @staticmethod
    def _clean_label(value: str) -> str:
        label = value.strip("“”\"' ，,。.!！")
        for suffix in ("这个节点", "的节点", "节点"):
            if label.endswith(suffix):
                label = label[: -len(suffix)]
        return label.strip() or "新处理步骤"

    @staticmethod
    def _guess_type(label: str) -> NodeType:
        if any(keyword in label for keyword in ("是否", "检查", "判断", "校验")):
            return NodeType.DECISION
        if "开始" == label:
            return NodeType.START
        if label in {"结束", "终止"}:
            return NodeType.END
        if "子流程" in label:
            return NodeType.SUBPROCESS
        return NodeType.TASK
