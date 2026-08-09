from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from app.agent.base import LLMProvider, ProviderResult
from app.agent.local_provider import LocalRuleProvider
from app.agent.result_cache import CacheStatus, ModelResultCache, build_model_cache_key
from app.documents.blueprint import BlueprintDocumentModel, render_docx, render_markdown
from app.graph.evidence import validate_patch_evidence
from app.graph.patcher import apply_patch
from app.graph.validator import graph_warnings
from app.knowledge.service import KnowledgeService
from app.models.graph import GapStatus, GraphDocument, MetadataStatus
from app.models.knowledge import KnowledgeEvidence, KnowledgeSearchRequest
from app.models.patch import LLMPatch

ProcessIntent = Literal["diagram_edit", "sap_change"]
KnowledgeStatus = Literal["not_required", "results", "insufficient_evidence"]
DocumentReviewStatus = Literal["ready", "pending_confirmation"]

_STRUCTURAL_TERMS = (
    "泳道",
    "swimlane",
    "lane",
    "连线",
    "连接线",
    "边标签",
    "edge",
    "图标",
    "icon",
    "布局",
    "layout",
)
_PROFESSIONAL_TERMS = (
    "sap",
    "t-code",
    "tcode",
    "事务码",
    "fiori",
    "配置",
    "badi",
    "best practice",
    "j45",
    "gap",
    "增强",
)


class ProcessWorkflowState(TypedDict, total=False):
    current_graph: GraphDocument
    instruction: str
    locale: str
    external_model_enabled: bool
    intent: ProcessIntent
    knowledge_required: bool
    knowledge_status: KnowledgeStatus
    evidence: list[KnowledgeEvidence]
    warnings: list[str]
    effective_provider: LLMProvider
    provider_result: ProviderResult
    cache_status: CacheStatus
    model_calls: int
    updated_graph: GraphDocument


class DocumentWorkflowState(TypedDict, total=False):
    model: BlueprintDocumentModel
    format: str
    markdown_renderer: Callable[[BlueprintDocumentModel], str]
    docx_renderer: Callable[[BlueprintDocumentModel], bytes]
    review_status: DocumentReviewStatus
    warnings: list[str]
    content: bytes
    media_type: str
    extension: str


@dataclass(frozen=True)
class ProcessOrchestrationResult:
    graph: GraphDocument
    patch: LLMPatch
    evidence: list[KnowledgeEvidence]
    warnings: list[str]
    provider: str
    model: str
    attempts: int
    model_calls: int
    cache_status: CacheStatus
    intent: ProcessIntent
    knowledge_status: KnowledgeStatus


@dataclass(frozen=True)
class DocumentOrchestrationResult:
    content: bytes
    media_type: str
    extension: str
    review_status: DocumentReviewStatus
    warnings: list[str]


class ProcessAgentOrchestrator:
    def __init__(
        self,
        provider: LLMProvider,
        knowledge_service: KnowledgeService,
        *,
        external_model_enabled: bool,
        model_cache: ModelResultCache | None = None,
        cache_namespace: str = "",
    ) -> None:
        self.provider = provider
        self.knowledge_service = knowledge_service
        self.external_model_enabled = external_model_enabled
        self.model_cache = model_cache
        self.cache_namespace = cache_namespace
        self.workflow = self._build_workflow()

    async def run(
        self,
        graph: GraphDocument,
        instruction: str,
        locale: str,
    ) -> ProcessOrchestrationResult:
        output = cast(
            ProcessWorkflowState,
            await self.workflow.ainvoke(
                ProcessWorkflowState(
                    current_graph=graph,
                    instruction=instruction,
                    locale=locale,
                    external_model_enabled=self.external_model_enabled,
                    knowledge_status="not_required",
                    evidence=[],
                    warnings=[],
                )
            ),
        )
        provider_result = output["provider_result"]
        return ProcessOrchestrationResult(
            graph=output["updated_graph"],
            patch=provider_result.patch,
            evidence=output["evidence"],
            warnings=output["warnings"],
            provider=provider_result.provider,
            model=provider_result.model,
            attempts=(
                0 if output["cache_status"] == "hit" else provider_result.attempts
            ),
            model_calls=output["model_calls"],
            cache_status=output["cache_status"],
            intent=output["intent"],
            knowledge_status=output["knowledge_status"],
        )

    def _build_workflow(self):
        workflow = StateGraph(ProcessWorkflowState)
        workflow.add_node("classify_intent", self._classify_intent)
        workflow.add_node("retrieve_knowledge", self._retrieve_knowledge)
        workflow.add_node("mark_insufficient", self._mark_insufficient)
        workflow.add_node("select_provider", self._select_provider)
        workflow.add_node("generate_patch", self._generate_patch)
        workflow.add_node("validate_patch", self._validate_patch)
        workflow.add_node("mark_pending_confirmation", self._mark_pending_confirmation)
        workflow.add_edge(START, "classify_intent")
        workflow.add_conditional_edges(
            "classify_intent",
            self._route_knowledge,
            {"retrieve": "retrieve_knowledge", "skip": "select_provider"},
        )
        workflow.add_conditional_edges(
            "retrieve_knowledge",
            self._route_evidence,
            {"insufficient": "mark_insufficient", "ready": "select_provider"},
        )
        workflow.add_edge("mark_insufficient", "select_provider")
        workflow.add_edge("select_provider", "generate_patch")
        workflow.add_edge("generate_patch", "validate_patch")
        workflow.add_conditional_edges(
            "validate_patch",
            self._route_confirmation,
            {"pending": "mark_pending_confirmation", "ready": END},
        )
        workflow.add_edge("mark_pending_confirmation", END)
        return workflow.compile()

    @staticmethod
    def _classify_intent(state: ProcessWorkflowState) -> dict[str, object]:
        normalized = state["instruction"].lower()
        has_professional_term = any(term in normalized for term in _PROFESSIONAL_TERMS)
        diagram_edit = not has_professional_term and any(
            term in normalized for term in _STRUCTURAL_TERMS
        )
        return {
            "intent": "diagram_edit" if diagram_edit else "sap_change",
            "knowledge_required": not diagram_edit,
        }

    @staticmethod
    def _route_knowledge(state: ProcessWorkflowState) -> str:
        return "retrieve" if state["knowledge_required"] else "skip"

    def _retrieve_knowledge(self, state: ProcessWorkflowState) -> dict[str, object]:
        graph = state["current_graph"]
        result = self.knowledge_service.search(
            KnowledgeSearchRequest(
                module=graph.module,
                process_scope=graph.process_scope,
                query=state["instruction"],
                sap_context=graph.sap_context,
                top_k=5,
            )
        )
        return {
            "knowledge_status": result.status,
            "evidence": result.evidence,
            "warnings": [*state["warnings"], *result.warnings],
        }

    @staticmethod
    def _route_evidence(state: ProcessWorkflowState) -> str:
        return (
            "insufficient"
            if state["knowledge_status"] == "insufficient_evidence"
            else "ready"
        )

    @staticmethod
    def _mark_insufficient(state: ProcessWorkflowState) -> dict[str, object]:
        return {
            "warnings": [
                *state["warnings"],
                "编排已进入证据不足分支；新增专业字段只能保持待确认状态。",
            ]
        }

    def _select_provider(self, state: ProcessWorkflowState) -> dict[str, object]:
        warnings = list(state["warnings"])
        effective_provider = self.provider
        if getattr(self.provider, "external", True) and not state["external_model_enabled"]:
            effective_provider = LocalRuleProvider()
            warnings.append("项目未启用外部模型，本次修改已使用本地规则 Provider。")
        return {"effective_provider": effective_provider, "warnings": warnings}

    async def _generate_patch(self, state: ProcessWorkflowState) -> dict[str, object]:
        provider = state["effective_provider"]

        async def call_provider() -> ProviderResult:
            return await provider.generate_patch(
                state["current_graph"],
                state["instruction"],
                state["locale"],
                state["evidence"],
            )

        if (
            self.model_cache is not None
            and self.cache_namespace
            and getattr(provider, "external", True)
        ):
            lookup = await self.model_cache.get_or_create(
                build_model_cache_key(
                    namespace=self.cache_namespace,
                    provider=provider,
                    graph=state["current_graph"],
                    instruction=state["instruction"],
                    locale=state["locale"],
                    evidence=state["evidence"],
                ),
                call_provider,
            )
            return {
                "provider_result": lookup.result,
                "cache_status": lookup.status,
                "model_calls": lookup.model_calls,
            }

        result = await call_provider()
        return {
            "provider_result": result,
            "cache_status": "bypassed",
            "model_calls": int(getattr(provider, "external", True)),
        }

    @staticmethod
    def _validate_patch(state: ProcessWorkflowState) -> dict[str, object]:
        patch = state["provider_result"].patch
        validate_patch_evidence(state["current_graph"], patch, state["evidence"])
        return {"updated_graph": apply_patch(state["current_graph"], patch)}

    @staticmethod
    def _route_confirmation(state: ProcessWorkflowState) -> str:
        return "pending" if _has_pending_review(state["updated_graph"]) else "ready"

    @staticmethod
    def _mark_pending_confirmation(state: ProcessWorkflowState) -> dict[str, object]:
        return {
            "warnings": [
                *state["warnings"],
                "流程包含待确认 SAP 元数据或 GAP 候选，发布前必须由顾问复核。",
            ]
        }


class DocumentAgentOrchestrator:
    def __init__(self) -> None:
        self.workflow = self._build_workflow()

    def render(
        self,
        model: BlueprintDocumentModel,
        format: str,
        *,
        markdown_renderer: Callable[[BlueprintDocumentModel], str] | None = None,
        docx_renderer: Callable[[BlueprintDocumentModel], bytes] | None = None,
    ) -> DocumentOrchestrationResult:
        output = cast(
            DocumentWorkflowState,
            self.workflow.invoke(
                DocumentWorkflowState(
                    model=model,
                    format=format,
                    markdown_renderer=markdown_renderer or render_markdown,
                    docx_renderer=docx_renderer or render_docx,
                    warnings=[],
                )
            ),
        )
        return DocumentOrchestrationResult(
            content=output["content"],
            media_type=output["media_type"],
            extension=output["extension"],
            review_status=output["review_status"],
            warnings=output["warnings"],
        )

    def _build_workflow(self):
        workflow = StateGraph(DocumentWorkflowState)
        workflow.add_node("preflight", self._preflight)
        workflow.add_node("mark_pending_confirmation", self._mark_pending_confirmation)
        workflow.add_node("render", self._render)
        workflow.add_edge(START, "preflight")
        workflow.add_conditional_edges(
            "preflight",
            self._route_preflight,
            {"pending": "mark_pending_confirmation", "ready": "render"},
        )
        workflow.add_edge("mark_pending_confirmation", "render")
        workflow.add_edge("render", END)
        return workflow.compile()

    @staticmethod
    def _preflight(state: DocumentWorkflowState) -> dict[str, object]:
        graph = state["model"].graph
        review_status: DocumentReviewStatus = (
            "pending_confirmation" if _has_pending_review(graph) else "ready"
        )
        return {
            "review_status": review_status,
            "warnings": [*state["warnings"], *graph_warnings(graph)],
        }

    @staticmethod
    def _route_preflight(state: DocumentWorkflowState) -> str:
        return "pending" if state["review_status"] == "pending_confirmation" else "ready"

    @staticmethod
    def _mark_pending_confirmation(state: DocumentWorkflowState) -> dict[str, object]:
        return {
            "warnings": [
                *state["warnings"],
                "导出内容包含待确认 SAP 元数据或 GAP 候选，不能作为顾问签字版本。",
            ]
        }

    @staticmethod
    def _render(state: DocumentWorkflowState) -> dict[str, object]:
        if state["format"] == "markdown":
            return {
                "content": state["markdown_renderer"](state["model"]).encode("utf-8"),
                "media_type": "text/markdown; charset=utf-8",
                "extension": "md",
            }
        return {
            "content": state["docx_renderer"](state["model"]),
            "media_type": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            "extension": "docx",
        }


@lru_cache
def get_document_orchestrator() -> DocumentAgentOrchestrator:
    return DocumentAgentOrchestrator()


def _has_pending_review(graph: GraphDocument) -> bool:
    for node in graph.nodes:
        professional_items = [
            *node.sap.tcodes,
            *node.sap.fiori_apps,
            *node.sap.configuration_points,
        ]
        if any(item.status != MetadataStatus.VERIFIED for item in professional_items):
            return True
        if any(not item.evidence_ref for item in node.sap.best_practice_refs):
            return True
        if node.sap.gap.status == GapStatus.CANDIDATE:
            return True
    return False
