from dataclasses import dataclass

import pytest

from app.agent import orchestrator as orchestrator_module
from app.agent.base import ProviderResult
from app.agent.orchestrator import DocumentAgentOrchestrator, ProcessAgentOrchestrator
from app.agent.result_cache import ModelResultCache
from app.documents.blueprint import BlueprintDocumentModel
from app.models.graph import SapMetadata, TCodeReference
from app.models.knowledge import KnowledgeSearchResponse
from app.models.patch import LLMPatch


@dataclass
class TrackingKnowledgeService:
    response: KnowledgeSearchResponse
    calls: int = 0

    def search(self, _request):
        self.calls += 1
        return self.response


class StaticProvider:
    external = False

    def __init__(self, patch: LLMPatch) -> None:
        self.patch = patch
        self.calls = 0
        self.evidence = []

    async def generate_patch(self, graph, instruction, locale, evidence=None):
        del graph, instruction, locale
        self.calls += 1
        self.evidence = evidence or []
        return ProviderResult(patch=self.patch, provider="static", model="static-v1")


class ExternalStaticProvider(StaticProvider):
    external = True


def _insufficient_response() -> KnowledgeSearchResponse:
    return KnowledgeSearchResponse(
        status="insufficient_evidence",
        evidence=[],
        warnings=["未检索到足够证据，请补充需求或由 SAP 顾问确认。"],
    )


@pytest.mark.asyncio
async def test_process_graph_skips_knowledge_for_diagram_only_edits(order_graph):
    knowledge = TrackingKnowledgeService(_insufficient_response())
    provider = StaticProvider(
        LLMPatch.model_validate(
            {
                "change_summary": "增加财务泳道。",
                "operations": [
                    {
                        "op": "add_lane",
                        "ref": "finance_lane",
                        "lane": {"label": "财务"},
                    }
                ],
            }
        )
    )

    result = await ProcessAgentOrchestrator(
        provider,
        knowledge,
        external_model_enabled=False,
    ).run(order_graph, "增加一个财务泳道", "zh-CN")

    assert result.intent == "diagram_edit"
    assert result.knowledge_status == "not_required"
    assert knowledge.calls == 0
    assert provider.calls == 1
    assert [lane.label for lane in result.graph.lanes] == ["财务"]


@pytest.mark.asyncio
async def test_process_graph_routes_insufficient_evidence_and_pending_review(order_graph):
    knowledge = TrackingKnowledgeService(_insufficient_response())
    provider = StaticProvider(
        LLMPatch.model_validate(
            {
                "change_summary": "增加待确认交易码。",
                "operations": [
                    {
                        "op": "update_node",
                        "id": "submit",
                        "changes": {
                            "sap": {
                                "tcodes": [
                                    {"code": "ME21N", "status": "pending_confirmation"}
                                ]
                            }
                        },
                    }
                ],
            }
        )
    )

    result = await ProcessAgentOrchestrator(
        provider,
        knowledge,
        external_model_enabled=False,
    ).run(order_graph, "为采购订单补充事务码", "zh-CN")

    assert result.intent == "sap_change"
    assert result.knowledge_status == "insufficient_evidence"
    assert knowledge.calls == 1
    assert any("证据不足分支" in warning for warning in result.warnings)
    assert any("发布前必须由顾问复核" in warning for warning in result.warnings)
    submit = next(node for node in result.graph.nodes if node.id == "submit")
    assert submit.sap.tcodes[0].code == "ME21N"


def test_document_graph_runs_pending_confirmation_preflight(order_graph):
    pending_node = order_graph.nodes[1].model_copy(
        update={
            "sap": SapMetadata(
                tcodes=[TCodeReference(code="ME21N")],
            )
        }
    )
    graph = order_graph.model_copy(
        update={"nodes": [order_graph.nodes[0], pending_node, *order_graph.nodes[2:]]}
    )
    model = BlueprintDocumentModel(
        project_name="测试项目",
        customer_name=None,
        process_name="测试流程",
        process_id="process-test",
        revision_no=2,
        release_no=None,
        lifecycle_state="draft",
        created_by="tester",
        created_at="2026-08-09T00:00:00+00:00",
        graph=graph,
    )

    result = DocumentAgentOrchestrator().render(model, "markdown")

    assert result.review_status == "pending_confirmation"
    assert any("不能作为顾问签字版本" in warning for warning in result.warnings)
    assert result.media_type == "text/markdown; charset=utf-8"
    assert "ME21N" in result.content.decode("utf-8")


@pytest.mark.asyncio
async def test_process_graph_caches_external_result_and_revalidates_patch(
    order_graph,
    monkeypatch,
):
    knowledge = TrackingKnowledgeService(_insufficient_response())
    provider = ExternalStaticProvider(
        LLMPatch.model_validate(
            {
                "change_summary": "增加财务泳道。",
                "operations": [
                    {
                        "op": "add_lane",
                        "ref": "finance_lane",
                        "lane": {"label": "财务"},
                    }
                ],
            }
        )
    )
    cache = ModelResultCache(ttl_seconds=60, max_entries=8)
    validations = 0
    validate_patch_evidence = orchestrator_module.validate_patch_evidence

    def track_validation(*args, **kwargs):
        nonlocal validations
        validations += 1
        return validate_patch_evidence(*args, **kwargs)

    monkeypatch.setattr(
        orchestrator_module,
        "validate_patch_evidence",
        track_validation,
    )
    orchestrator = ProcessAgentOrchestrator(
        provider,
        knowledge,
        external_model_enabled=True,
        model_cache=cache,
        cache_namespace="project-a:process-a",
    )

    first = await orchestrator.run(order_graph, "增加一个财务泳道", "zh-CN")
    second = await orchestrator.run(order_graph, "增加一个财务泳道", "zh-CN")
    isolated = await ProcessAgentOrchestrator(
        provider,
        knowledge,
        external_model_enabled=True,
        model_cache=cache,
        cache_namespace="project-b:process-b",
    ).run(order_graph, "增加一个财务泳道", "zh-CN")

    assert first.cache_status == "miss"
    assert first.model_calls == 1
    assert second.cache_status == "hit"
    assert second.model_calls == 0
    assert second.attempts == 0
    assert isolated.cache_status == "miss"
    assert provider.calls == 2
    assert validations == 3
