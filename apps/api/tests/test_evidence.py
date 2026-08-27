import pytest

from app.core.errors import PatchError
from app.graph.evidence import validate_patch_evidence
from app.models.graph import GraphDocument
from app.models.knowledge import KnowledgeEvidence
from app.models.patch import LLMPatch


def knowledge_evidence(*, review_status: str = "approved") -> KnowledgeEvidence:
    return KnowledgeEvidence(
        evidence_ref="kb-mm-j45#standard-steps",
        source_id="kb-mm-j45",
        title="J45",
        section="Standard steps",
        excerpt="创建采购订单使用 ME21N。",
        source_path="MM/P2P/Process_J45.md",
        source_url=None,
        sap_release="2023",
        review_status=review_status,
        score=0.95,
    )


def patch_with_tcode(*, status: str, evidence_ref: str | None) -> LLMPatch:
    return LLMPatch.model_validate(
        {
            "change_summary": "增加采购订单步骤。",
            "operations": [
                {
                    "op": "add_node",
                    "ref": "po",
                    "node": {
                        "type": "task",
                        "label": "创建采购订单",
                        "sap": {
                            "tcodes": [
                                {
                                    "code": "ME21N",
                                    "status": status,
                                    "evidence_ref": evidence_ref,
                                }
                            ]
                        },
                    },
                }
            ],
        }
    )


def empty_graph() -> GraphDocument:
    return GraphDocument(graph_id="evidence-test")


def test_verified_metadata_requires_matching_approved_evidence():
    patch = patch_with_tcode(
        status="verified",
        evidence_ref="kb-mm-j45#standard-steps",
    )
    validate_patch_evidence(empty_graph(), patch, [knowledge_evidence()])

    with pytest.raises(PatchError) as pending_error:
        validate_patch_evidence(
            empty_graph(),
            patch,
            [knowledge_evidence(review_status="pending_consultant")],
        )
    assert pending_error.value.code == "PATCH_EVIDENCE_INVALID"
    assert pending_error.value.details["unapproved_verified_refs"] == [
        "kb-mm-j45#standard-steps"
    ]


def test_unknown_reference_and_gap_without_evidence_are_rejected():
    unknown = patch_with_tcode(
        status="pending_confirmation",
        evidence_ref="invented-source#me21n",
    )
    with pytest.raises(PatchError) as unknown_error:
        validate_patch_evidence(empty_graph(), unknown, [knowledge_evidence()])
    assert unknown_error.value.details["unknown_evidence_refs"] == [
        "invented-source#me21n"
    ]

    gap_patch = LLMPatch.model_validate(
        {
            "change_summary": "增加 GAP 候选。",
            "operations": [
                {
                    "op": "add_node",
                    "ref": "approval",
                    "node": {
                        "type": "task",
                        "label": "动态审批",
                        "sap": {
                            "gap": {
                                "status": "candidate",
                                "description": "需要项目维度动态审批",
                            }
                        },
                    },
                }
            ],
        }
    )
    with pytest.raises(PatchError) as gap_error:
        validate_patch_evidence(empty_graph(), gap_patch, [knowledge_evidence()])
    assert gap_error.value.details["gaps_without_evidence"] == ["动态审批"]


def test_pending_metadata_without_evidence_is_allowed():
    validate_patch_evidence(
        empty_graph(),
        patch_with_tcode(status="pending_confirmation", evidence_ref=None),
        [],
    )
