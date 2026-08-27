from collections.abc import Iterable

from app.core.errors import PatchError
from app.models.graph import (
    GapStatus,
    GraphDocument,
    MetadataStatus,
    SapMetadata,
)
from app.models.knowledge import KnowledgeEvidence
from app.models.patch import LLMPatch


def validate_patch_evidence(
    current_graph: GraphDocument,
    patch: LLMPatch,
    evidence: list[KnowledgeEvidence],
) -> None:
    retrieved = {item.evidence_ref: item.review_status for item in evidence}
    existing_refs = set(_graph_evidence_refs(current_graph))
    existing_verified_refs = set(_graph_verified_refs(current_graph))
    invalid_refs: set[str] = set()
    invalid_verified: set[str] = set()
    gaps_without_evidence: list[str] = []

    for operation in patch.operations:
        sap: SapMetadata | None = None
        object_label = operation.op
        if operation.op == "add_node":
            sap = operation.node.sap
            object_label = operation.node.label
        elif operation.op == "update_node" and "sap" in operation.changes.model_fields_set:
            sap = operation.changes.sap
            object_label = operation.id
        if sap is None:
            continue

        for reference, status in _professional_references(sap):
            if reference and reference not in retrieved and reference not in existing_refs:
                invalid_refs.add(reference)
            if status == MetadataStatus.VERIFIED:
                if not reference:
                    invalid_verified.add(f"{object_label}:missing_evidence")
                elif not (
                    retrieved.get(reference) == "approved"
                    or reference in existing_verified_refs
                ):
                    invalid_verified.add(reference)

        for reference in sap.gap.evidence_refs:
            if reference not in retrieved and reference not in existing_refs:
                invalid_refs.add(reference)
        if sap.gap.status != GapStatus.NONE and not sap.gap.evidence_refs:
            gaps_without_evidence.append(object_label)

    if invalid_refs or invalid_verified or gaps_without_evidence:
        raise PatchError(
            "PATCH_EVIDENCE_INVALID",
            "模型 Patch 包含未经本次知识检索支持的专业结论。",
            details={
                "unknown_evidence_refs": sorted(invalid_refs),
                "unapproved_verified_refs": sorted(invalid_verified),
                "gaps_without_evidence": gaps_without_evidence,
            },
        )


def _professional_references(
    sap: SapMetadata,
) -> Iterable[tuple[str | None, MetadataStatus | None]]:
    for item in sap.tcodes:
        yield item.evidence_ref, item.status
    for item in sap.fiori_apps:
        yield item.evidence_ref, item.status
    for item in sap.configuration_points:
        yield item.evidence_ref, item.status
    for item in sap.best_practice_refs:
        yield item.evidence_ref, None


def _graph_evidence_refs(graph: GraphDocument) -> Iterable[str]:
    for node in graph.nodes:
        for reference, _ in _professional_references(node.sap):
            if reference:
                yield reference
        yield from node.sap.gap.evidence_refs


def _graph_verified_refs(graph: GraphDocument) -> Iterable[str]:
    for node in graph.nodes:
        for reference, status in _professional_references(node.sap):
            if reference and status == MetadataStatus.VERIFIED:
                yield reference
