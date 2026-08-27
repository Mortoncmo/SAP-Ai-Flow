import re

from app.agent.base import ProviderResult
from app.models.graph import Edge, GraphDocument, Node, NodeIcon, NodeType, Swimlane
from app.models.knowledge import KnowledgeEvidence
from app.models.patch import LLMPatch


class LocalRuleProvider:
    """Deterministic provider for local development and automated tests."""

    external = False

    async def generate_patch(
        self,
        graph: GraphDocument,
        instruction: str,
        locale: str,
        evidence: list[KnowledgeEvidence] | None = None,
    ) -> ProviderResult:
        del locale
        patch = self._build_patch(graph, instruction.strip(), evidence or [])
        return ProviderResult(patch=patch, provider="local", model="rule-engine-v1")

    def _build_patch(
        self,
        graph: GraphDocument,
        instruction: str,
        evidence: list[KnowledgeEvidence],
    ) -> LLMPatch:
        if "泳道" in instruction:
            return self._build_swimlane_patch(graph, instruction)

        if self._looks_like_edge_instruction(instruction):
            return self._build_edge_patch(graph, instruction)

        if not graph.nodes or any(word in instruction for word in ("创建流程", "生成流程", "新建流程")):
            return self._create_flow(instruction, evidence)

        match = re.search(
            r"(?:给|为)(.+?)(?:增加|添加|设置|使用)(.+?)图标[。.!！]?$",
            instruction,
        )
        if match:
            node = self._find_node(graph, match.group(1))
            icon = self._parse_icon(match.group(2))
            return LLMPatch(
                change_summary=f"为“{node.label}”设置图标。",
                operations=[
                    {"op": "update_node", "id": node.id, "changes": {"icon": icon.value}}
                ],
            )

        match = re.search(r"(?:移除|删除|清除)(.+?)的?图标[。.!！]?$", instruction)
        if match:
            node = self._find_node(graph, match.group(1))
            return LLMPatch(
                change_summary=f"移除“{node.label}”的图标。",
                operations=[{"op": "update_node", "id": node.id, "changes": {"icon": None}}],
            )

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

    @staticmethod
    def _looks_like_edge_instruction(instruction: str) -> bool:
        content = instruction.strip()
        return "连线" in content or bool(
            re.match(r"^(?:请帮我|帮我|请)?\s*(?:连接|连结)", content)
        )

    def _build_edge_patch(self, graph: GraphDocument, instruction: str) -> LLMPatch:
        content = instruction.strip()
        prefix = r"^(?:请帮我|帮我|请)?\s*"
        separator = r"(?:到|至|→|->|与|和)"

        match = re.search(
            prefix
            + r"(?:把|将)?(.+?)"
            + separator
            + r"(.+?)的?连线(?:的)?标签(?:改为|修改为|改成|设置为)(.+?)[。.!！]?$",
            content,
        )
        if match:
            edge = self._find_edge(graph, match.group(1), match.group(2))
            label = match.group(3).strip("“”\"' ，,。.!！") or None
            return LLMPatch(
                change_summary=f"将“{self._edge_name(graph, edge)}”的标签修改为“{label or '无'}”。",
                operations=[
                    {"op": "update_edge", "id": edge.id, "changes": {"label": label}}
                ],
            )

        match = re.search(
            prefix
            + r"(?:删除|移除)(.+?)"
            + separator
            + r"(.+?)的?连线[。.!！]?$",
            content,
        )
        if match:
            edge = self._find_edge(graph, match.group(1), match.group(2))
            return LLMPatch(
                change_summary=f"删除“{self._edge_name(graph, edge)}”连线。",
                operations=[{"op": "remove_edge", "id": edge.id}],
            )

        match = re.search(
            prefix
            + r"(?:连接|连结)(.+?)"
            + separator
            + r"(.+?)(?:的?连线)?[。.!！]?$",
            content,
        )
        if match:
            source = self._find_node(graph, match.group(1))
            target = self._find_node(graph, match.group(2))
            if source.id == target.id:
                from app.core.errors import ProviderError

                raise ProviderError(
                    "INSTRUCTION_EDGE_SELF_REFERENCE",
                    "不允许节点连接自身。",
                )
            if any(
                edge.source == source.id and edge.target == target.id
                for edge in graph.edges
            ):
                from app.core.errors import ProviderError

                raise ProviderError(
                    "INSTRUCTION_EDGE_ALREADY_EXISTS",
                    f"“{source.label}”到“{target.label}”的连线已经存在。",
                )
            return LLMPatch(
                change_summary=f"连接“{source.label}”到“{target.label}”。",
                operations=[
                    {
                        "op": "add_edge",
                        "edge": {"source": source.id, "target": target.id},
                    }
                ],
            )

        from app.core.errors import ProviderError

        raise ProviderError(
            "INSTRUCTION_EDGE_INVALID",
            "没有识别出连线操作，请使用“连接开始到结束”等表达。",
        )

    def _find_edge(
        self,
        graph: GraphDocument,
        source_fragment: str,
        target_fragment: str,
    ) -> Edge:
        source = self._find_node(graph, source_fragment)
        target = self._find_node(graph, target_fragment)
        matches = [
            edge
            for edge in graph.edges
            if edge.source == source.id and edge.target == target.id
        ]
        if not matches:
            from app.core.errors import ProviderError

            raise ProviderError(
                "INSTRUCTION_EDGE_NOT_FOUND",
                f"没有找到“{source.label}”到“{target.label}”的连线。",
            )
        if len(matches) > 1:
            from app.core.errors import ProviderError

            raise ProviderError(
                "INSTRUCTION_EDGE_AMBIGUOUS",
                f"“{source.label}”到“{target.label}”存在多条连线，请先在画布中确认。",
            )
        return matches[0]

    @staticmethod
    def _edge_name(graph: GraphDocument, edge: Edge) -> str:
        source = next(node.label for node in graph.nodes if node.id == edge.source)
        target = next(node.label for node in graph.nodes if node.id == edge.target)
        return f"{source}到{target}"

    def _build_swimlane_patch(self, graph: GraphDocument, instruction: str) -> LLMPatch:
        match = re.search(
            r"(?:把|将)(.+?)(?:移到|移动到|放到)(.+?)泳道[。.!！]?$",
            instruction,
        )
        if match:
            node = self._find_node(graph, match.group(1))
            lane = self._find_lane(graph, match.group(2))
            return LLMPatch(
                change_summary=f"将“{node.label}”移动到“{lane.label}”泳道。",
                operations=[
                    {"op": "update_node", "id": node.id, "changes": {"lane_id": lane.id}}
                ],
            )

        match = re.search(
            r"(?:把|将)(.+?)泳道(?:改名为|修改为|改成|改为)(.+?)[。.!！]?$",
            instruction,
        )
        if match:
            lane = self._find_lane(graph, match.group(1))
            label = self._clean_label(match.group(2))
            return LLMPatch(
                change_summary=f"将“{lane.label}”泳道改名为“{label}”。",
                operations=[
                    {"op": "update_lane", "id": lane.id, "changes": {"label": label}}
                ],
            )

        match = re.search(r"(?:删除|移除)(.+?)泳道[。.!！]?$", instruction)
        if match:
            lane = self._find_lane(graph, match.group(1))
            return LLMPatch(
                change_summary=f"删除“{lane.label}”泳道，保留其中节点。",
                operations=[{"op": "remove_lane", "id": lane.id}],
            )

        labels = self._parse_lane_labels(instruction)
        if labels:
            existing = {lane.label for lane in graph.lanes}
            new_labels = [label for label in labels if label not in existing]
            if not new_labels:
                from app.core.errors import ProviderError

                raise ProviderError(
                    "INSTRUCTION_LANE_ALREADY_EXISTS",
                    "指令中的泳道已经存在。",
                )
            if len(graph.lanes) + len(new_labels) > 20:
                from app.core.errors import ProviderError

                raise ProviderError(
                    "INSTRUCTION_LANE_LIMIT_EXCEEDED",
                    "泳道总数不能超过 20 条。",
                )
            operations = [
                {
                    "op": "add_lane",
                    "ref": f"new_lane_{index}",
                    "lane": {
                        "label": label,
                        "color": self._lane_color(len(graph.lanes) + index - 1),
                    },
                }
                for index, label in enumerate(new_labels, start=1)
            ]
            return LLMPatch(
                change_summary=f"增加泳道：{'、'.join(new_labels)}。",
                operations=operations,
            )

        from app.core.errors import ProviderError

        raise ProviderError(
            "INSTRUCTION_SWIMLANE_INVALID",
            "没有识别出泳道操作，请使用“增加三个泳道：销售、物流、财务”等表达。",
        )

    @staticmethod
    def _parse_lane_labels(instruction: str) -> list[str]:
        content = instruction.strip(" 。.!！")
        content = re.sub(r"^(?:请帮我|帮我|请)", "", content).strip()
        create_match = re.match(r"^(?:增加|添加|新增|创建|新建)", content)
        quantity_prefix = re.match(
            r"^[一二两三四五六七八九十百\d]+(?:个|条)?泳道",
            content,
        )
        labeled_prefix = re.match(r"^泳道\s*[:：]", content)
        listed_suffix = re.search(
            r"[、,，;；].+[一二两三四五六七八九十百\d]+(?:个|条)?泳道$",
            content,
        )
        if not any((create_match, quantity_prefix, labeled_prefix, listed_suffix)):
            return []
        if create_match:
            content = content[create_match.end() :].strip()

        prefix = re.match(
            r"^[一二两三四五六七八九十百\d]+(?:个|条)?泳道\s*[:：,，、]?\s*(.+)$",
            content,
        )
        if prefix:
            content = prefix.group(1)
        else:
            content = re.sub(
                r"^[一二两三四五六七八九十百\d]+(?:个|条)?(?=\S)",
                "",
                content,
            )
            content = re.sub(r"^(?:泳道|名为)\s*[:：]?\s*", "", content)
            content = re.sub(
                r"(?:[一二两三四五六七八九十百\d]+(?:个|条)?)?(?:的)?泳道$",
                "",
                content,
            )

        content = re.sub(r"^(?:分别为|分别是|包括|包含)\s*", "", content).strip()
        values = re.split(r"[、,，;；/]+|(?:以及|和)", content)
        labels: list[str] = []
        for value in values:
            label = value.strip("“”\"' ：:，,。.!！的")
            if label and label not in labels:
                labels.append(label)
        return labels

    def _create_flow(
        self,
        instruction: str,
        evidence: list[KnowledgeEvidence],
    ) -> LLMPatch:
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
        if any(keyword in instruction.upper() for keyword in ("P2P", "采购到付款", "直接物料")):
            return self._create_p2p_flow(evidence)

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
                    "node": {
                        "type": node_type.value,
                        "label": label,
                        "icon": self._guess_icon(label),
                        "sap": self._sap_metadata(label),
                    },
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

    def _create_p2p_flow(self, evidence: list[KnowledgeEvidence]) -> LLMPatch:
        j45_evidence = next(
            (
                item
                for item in evidence
                if item.source_id == "kb-mm-j45-project-seed"
                and "transaction mapping" in item.section.lower()
            ),
            None,
        )
        evidence_ref = j45_evidence.evidence_ref if j45_evidence else None
        metadata_status = (
            "verified"
            if j45_evidence and j45_evidence.review_status == "approved"
            else "pending_confirmation"
        )
        lanes = [
            ("requester", "需求部门", "#52796f"),
            ("approval", "审批人", "#7b668f"),
            ("buyer", "采购部门", "#5b7394"),
            ("warehouse", "仓库", "#547f86"),
            ("finance", "财务", "#a36f3f"),
        ]
        steps = [
            ("start", "开始", NodeType.START, "requester", None, None, None),
            ("pr", "创建采购申请", NodeType.TASK, "requester", "transaction", "ME51N", "Requester"),
            ("approval", "采购申请审批", NodeType.TASK, "approval", "approval", "ME54N", "Approver"),
            ("po", "创建采购订单", NodeType.TASK, "buyer", "transaction", "ME21N", "Purchaser"),
            ("gr", "货物接收", NodeType.TASK, "warehouse", "transaction", "MIGO", "Warehouse Clerk"),
            ("ir", "发票校验", NodeType.TASK, "finance", "validation", "MIRO", "Accounts Payable"),
            ("end", "结束", NodeType.END, "finance", None, None, None),
        ]
        operations: list[dict[str, object]] = [
            {
                "op": "add_lane",
                "ref": f"lane_{ref}",
                "lane": {"label": label, "color": color},
            }
            for ref, label, color in lanes
        ]
        for ref, label, node_type, lane_ref, step_type, tcode, role in steps:
            sap = self._sap_metadata(label)
            if step_type:
                sap = {
                    **sap,
                    "step_type": step_type,
                    "tcodes": [
                        {
                            "code": tcode,
                            "status": metadata_status,
                            "evidence_ref": evidence_ref,
                        }
                    ],
                    "roles": [role],
                    "best_practice_refs": [
                        {
                            "scope_item": "J45",
                            "step": label,
                            "evidence_ref": evidence_ref,
                        }
                    ],
                }
            operations.append(
                {
                    "op": "add_node",
                    "ref": ref,
                    "node": {
                        "type": node_type.value,
                        "label": label,
                        "icon": self._guess_icon(label),
                        "lane_id": f"@lane_{lane_ref}",
                        "sap": sap,
                    },
                }
            )
        for index in range(len(steps) - 1):
            operations.append(
                {
                    "op": "add_edge",
                    "edge": {
                        "source": f"@{steps[index][0]}",
                        "target": f"@{steps[index + 1][0]}",
                        "label": "通过" if steps[index][0] == "approval" else None,
                    },
                }
            )
        return LLMPatch(
            change_summary="创建 SAP MM/P2P 采购到付款流程骨架，专业字段均标记为待确认。",
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
                "node": {
                    "type": self._guess_type(label).value,
                    "label": label,
                    "icon": self._guess_icon(label),
                    "lane_id": anchor.lane_id,
                    "sap": self._sap_metadata(label),
                },
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
                "node": {
                    "type": self._guess_type(label).value,
                    "label": label,
                    "icon": self._guess_icon(label),
                    "lane_id": anchor.lane_id,
                    "sap": self._sap_metadata(label),
                },
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
    def _find_lane(graph: GraphDocument, fragment: str) -> Swimlane:
        needle = fragment.strip("“”\"' ，,的")
        lane = next(
            (
                item
                for item in graph.lanes
                if item.label == needle or needle in item.label or item.label in needle
            ),
            None,
        )
        if lane is None:
            from app.core.errors import ProviderError

            raise ProviderError(
                "INSTRUCTION_LANE_NOT_FOUND",
                f"没有找到与“{needle}”匹配的泳道。",
            )
        return lane

    @staticmethod
    def _clean_label(value: str) -> str:
        label = value.strip("“”\"' ，,。.!！")
        for suffix in ("这个节点", "的节点", "节点"):
            label = label.removesuffix(suffix)
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

    @staticmethod
    def _guess_icon(label: str) -> str | None:
        mappings = (
            (("审批", "确认", "检查", "校验"), NodeIcon.CLIPBOARD_CHECK),
            (("信用", "风控"), NodeIcon.SHIELD_CHECK),
            (("订单", "申请", "发票", "单据"), NodeIcon.FILE_TEXT),
            (("仓库", "库存", "物料"), NodeIcon.PACKAGE),
            (("发货", "运输", "交付"), NodeIcon.TRUCK),
            (("付款", "金额", "收款"), NodeIcon.CIRCLE_DOLLAR_SIGN),
            (("经理", "用户", "人员"), NodeIcon.USER),
            (("公司", "组织", "部门"), NodeIcon.BUILDING),
        )
        for keywords, icon in mappings:
            if any(keyword in label for keyword in keywords):
                return icon.value
        return None

    @staticmethod
    def _sap_metadata(label: str) -> dict[str, object]:
        return {
            "step_type": None,
            "tcodes": [],
            "fiori_apps": [],
            "roles": [],
            "configuration_points": [],
            "best_practice_refs": [],
            "gap": {
                "status": "none",
                "category": None,
                "description": None,
                "recommendation": None,
                "confidence": None,
                "evidence_refs": [],
                "owner": None,
            },
        }

    @staticmethod
    def _parse_icon(value: str) -> NodeIcon:
        normalized = value.strip("“”\"' ，,")
        mappings = {
            "人员": NodeIcon.USER,
            "用户": NodeIcon.USER,
            "经理": NodeIcon.USER,
            "组织": NodeIcon.BUILDING,
            "公司": NodeIcon.BUILDING,
            "建筑": NodeIcon.BUILDING,
            "盾牌": NodeIcon.SHIELD_CHECK,
            "安全": NodeIcon.SHIELD_CHECK,
            "风控": NodeIcon.SHIELD_CHECK,
            "文件": NodeIcon.FILE_TEXT,
            "单据": NodeIcon.FILE_TEXT,
            "文档": NodeIcon.FILE_TEXT,
            "包裹": NodeIcon.PACKAGE,
            "物料": NodeIcon.PACKAGE,
            "仓库": NodeIcon.PACKAGE,
            "卡车": NodeIcon.TRUCK,
            "运输": NodeIcon.TRUCK,
            "货车": NodeIcon.TRUCK,
            "金额": NodeIcon.CIRCLE_DOLLAR_SIGN,
            "付款": NodeIcon.CIRCLE_DOLLAR_SIGN,
            "财务": NodeIcon.CIRCLE_DOLLAR_SIGN,
            "审批": NodeIcon.CLIPBOARD_CHECK,
            "检查": NodeIcon.CLIPBOARD_CHECK,
            "勾选": NodeIcon.CLIPBOARD_CHECK,
        }
        for keyword, icon in mappings.items():
            if keyword in normalized:
                return icon
        from app.core.errors import ProviderError

        raise ProviderError(
            "INSTRUCTION_ICON_NOT_SUPPORTED",
            f"暂不支持“{normalized}”图标。",
        )

    @staticmethod
    def _lane_color(index: int) -> str:
        return ("#52796f", "#5b7394", "#a36f3f", "#7b668f", "#547f86")[index % 5]
