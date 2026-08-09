from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_knowledge_search_returns_grounded_j45_evidence():
    response = client.post(
        "/api/v1/knowledge/search",
        json={
            "module": "MM",
            "process_scope": "P2P",
            "query": "创建采购订单 ME21N",
            "sap_context": {"edition": "S/4HANA", "release": "2023"},
            "top_k": 5,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "results"
    assert any("ME21N" in item["excerpt"] for item in payload["evidence"])
    assert all(item["review_status"] == "pending_consultant" for item in payload["evidence"])
    assert any("待确认" in warning for warning in payload["warnings"])


def test_knowledge_search_excludes_other_releases():
    response = client.post(
        "/api/v1/knowledge/search",
        json={
            "query": "ME21N",
            "sap_context": {"edition": "S/4HANA", "release": "2022"},
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "insufficient_evidence"
    assert payload["evidence"] == []
    assert any("Release" in warning for warning in payload["warnings"])


def test_gap_analysis_only_returns_candidate_with_evidence():
    response = client.post(
        "/api/v1/gaps/analyze",
        json={
            "business_requirement": "跨部门多级审批，需要按项目和预算动态分配审批人",
            "sap_context": {"edition": "S/4HANA", "release": "2023"},
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["outcome"] == "candidate"
    assert payload["gap"]["status"] == "candidate"
    assert payload["gap"]["evidence_refs"]
    assert payload["gap"]["status"] != "confirmed"
    assert any("候选" in warning for warning in payload["warnings"])
