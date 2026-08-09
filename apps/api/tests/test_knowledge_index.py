import json
from pathlib import Path

import chromadb

from app.knowledge.index import HashedNgramEmbedding, KnowledgeChunk, KnowledgeIndex
from app.knowledge.service import KnowledgeService
from app.models.graph import SapContext
from app.models.knowledge import GapAnalyzeRequest, KnowledgeSearchRequest


def chunk(
    body: str,
    *,
    source_id: str = "kb-test",
    module: str = "MM",
    process_scope: str = "P2P",
    release: str = "2023",
    review_status: str = "approved",
) -> KnowledgeChunk:
    return KnowledgeChunk(
        metadata={
            "source_id": source_id,
            "source_title": f"Test source {source_id}",
            "module": module,
            "process_scope": process_scope,
            "sap_release": release,
            "license_status": "project_provided",
            "review_status": review_status,
        },
        section="Standard steps",
        body=body,
        source_path=f"{source_id}.md",
    )


def dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def test_hashed_embedding_is_deterministic_and_prefers_shared_terms():
    embedding = HashedNgramEmbedding(384)
    query, matching, unrelated = embedding.embed(
        ["创建采购订单 ME21N", "采购订单通过 ME21N 创建", "财务发票校验 MIRO"]
    )

    assert query == embedding.embed(["创建采购订单 ME21N"])[0]
    assert dot(query, matching) > dot(query, unrelated)
    assert abs(dot(query, query) - 1.0) < 1e-9


def test_index_sync_removes_stale_chunks_and_persists(tmp_path: Path):
    index_path = tmp_path / "chroma"
    index = KnowledgeIndex.persistent(
        index_path,
        "knowledge_test",
        128,
        allow_pending=True,
    )
    original = chunk("创建采购订单使用 ME21N。")
    updated = chunk("创建采购订单使用 ME21N，并执行供货源分配。")

    index.sync([original])
    assert index.collection.get(include=[])["ids"] == [original.chunk_id]

    index.sync([updated])
    assert index.collection.get(include=[])["ids"] == [updated.chunk_id]

    reopened = KnowledgeIndex.persistent(
        index_path,
        "knowledge_test",
        128,
        allow_pending=True,
    )
    hits = reopened.search(
        "ME21N 采购订单",
        module="MM",
        process_scope="P2P",
        sap_release="2023",
        top_k=3,
    )
    assert hits[0].chunk_id == updated.chunk_id
    assert hits[0].score > 0


def test_index_filters_module_scope_release_and_pending_content():
    index = KnowledgeIndex(
        chromadb.EphemeralClient(),
        "knowledge_filter_test",
        128,
        allow_pending=False,
    )
    approved = chunk("采购申请使用 ME51N。", source_id="approved")
    pending = chunk(
        "采购订单使用 ME21N。",
        source_id="pending",
        review_status="pending_consultant",
    )
    other_release = chunk("采购订单使用 ME21N。", source_id="other-release", release="2022")

    indexed = index.sync([approved, pending, other_release])
    assert {item.chunk_id for item in indexed} == {approved.chunk_id, other_release.chunk_id}

    current_hits = index.search(
        "采购申请 ME51N",
        module="MM",
        process_scope="P2P",
        sap_release="2023",
        top_k=5,
    )
    old_hits = index.search(
        "采购订单 ME21N",
        module="MM",
        process_scope="P2P",
        sap_release="2022",
        top_k=5,
    )
    wrong_module = index.search(
        "采购申请 ME51N",
        module="SD",
        process_scope="P2P",
        sap_release="2023",
        top_k=5,
    )

    assert [item.chunk_id for item in current_hits] == [approved.chunk_id]
    assert [item.chunk_id for item in old_hits] == [other_release.chunk_id]
    assert wrong_module == []


def test_production_service_returns_no_pending_project_seed():
    root = Path(__file__).resolve().parents[3] / "SAP_Knowledge"
    index = KnowledgeIndex(
        chromadb.EphemeralClient(),
        "knowledge_production_test",
        128,
        allow_pending=False,
    )
    service = KnowledgeService(root, index, allow_pending=False)

    result = service.search(
        KnowledgeSearchRequest(
            query="采购订单 ME21N",
            sap_context=SapContext(release="2023"),
        )
    )

    assert index.collection.count() == 0
    assert result.status == "insufficient_evidence"
    assert result.evidence == []


def test_exact_tcode_query_ranks_j45_without_unrelated_gap_sections():
    root = Path(__file__).resolve().parents[3] / "SAP_Knowledge"
    index = KnowledgeIndex(
        chromadb.EphemeralClient(),
        "knowledge_quality_test",
        384,
        allow_pending=True,
    )
    service = KnowledgeService(root, index, allow_pending=True)

    result = service.search(
        KnowledgeSearchRequest(
            query="创建采购订单 ME21N",
            sap_context=SapContext(release="2023"),
            top_k=5,
        )
    )

    assert result.evidence[0].source_id == "kb-mm-j45-project-seed"
    assert "ME21N" in result.evidence[0].excerpt
    assert all(item.source_id != "kb-mm-common-gaps-project-seed" for item in result.evidence)


def test_fixed_project_evaluation_set_meets_quality_gates():
    fixture_path = Path(__file__).parent / "fixtures" / "knowledge_eval.json"
    evaluation = json.loads(fixture_path.read_text(encoding="utf-8"))
    root = Path(__file__).resolve().parents[3] / "SAP_Knowledge"
    index = KnowledgeIndex(
        chromadb.EphemeralClient(),
        "knowledge_fixed_evaluation",
        384,
        allow_pending=True,
    )
    service = KnowledgeService(root, index, allow_pending=True)

    status_matches = 0
    top_source_matches = 0
    positive_searches = 0
    search_failures: list[str] = []
    for case in evaluation["search_cases"]:
        result = service.search(
            KnowledgeSearchRequest(
                query=case["query"],
                sap_context=SapContext(release="2023"),
                top_k=5,
            )
        )
        if result.status == case["expected_status"]:
            status_matches += 1
        else:
            search_failures.append(
                f"{case['id']}: status={result.status}, expected={case['expected_status']}"
            )

        expected_source = case["expected_top_source"]
        if expected_source is None:
            if result.evidence:
                search_failures.append(
                    f"{case['id']}: expected no evidence, got {result.evidence[0].source_id}"
                )
            continue

        positive_searches += 1
        if result.evidence and result.evidence[0].source_id == expected_source:
            top_source_matches += 1
        else:
            actual = result.evidence[0].source_id if result.evidence else "none"
            search_failures.append(
                f"{case['id']}: top_source={actual}, expected={expected_source}"
            )
        evidence_text = " ".join(item.excerpt for item in result.evidence)
        for term in case["required_terms"]:
            if term not in evidence_text:
                search_failures.append(f"{case['id']}: missing term {term}")

    gap_matches = 0
    gap_failures: list[str] = []
    for case in evaluation["gap_cases"]:
        result = service.analyze_gap(
            GapAnalyzeRequest(
                business_requirement=case["requirement"],
                sap_context=SapContext(release="2023"),
            )
        )
        if result.outcome == case["expected_outcome"]:
            gap_matches += 1
        else:
            gap_failures.append(
                f"{case['id']}: outcome={result.outcome}, expected={case['expected_outcome']}"
            )
        if case["expected_category"] is not None:
            actual_category = result.gap.category if result.gap else None
            if actual_category != case["expected_category"]:
                gap_failures.append(
                    f"{case['id']}: category={actual_category}, "
                    f"expected={case['expected_category']}"
                )
        if result.gap is not None and result.gap.status != "candidate":
            gap_failures.append(f"{case['id']}: non-candidate status={result.gap.status}")

    gates = evaluation["quality_gates"]
    assert status_matches / len(evaluation["search_cases"]) >= gates["search_status_accuracy"], (
        search_failures
    )
    assert top_source_matches / positive_searches >= gates["search_top1_accuracy"], (
        search_failures
    )
    assert gap_matches / len(evaluation["gap_cases"]) >= gates["gap_outcome_accuracy"], (
        gap_failures
    )
    assert not search_failures
    assert not gap_failures
