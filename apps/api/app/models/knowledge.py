from typing import Literal

from pydantic import Field

from app.models.graph import GapAssessment, SapContext, StrictModel


class KnowledgeSearchRequest(StrictModel):
    module: str = Field(default="MM", min_length=2, max_length=20)
    process_scope: str = Field(default="P2P", min_length=1, max_length=30)
    query: str = Field(min_length=1, max_length=1000)
    sap_context: SapContext = Field(default_factory=SapContext)
    top_k: int = Field(default=5, ge=1, le=10)


class KnowledgeEvidence(StrictModel):
    evidence_ref: str
    source_id: str
    title: str
    section: str
    excerpt: str
    source_path: str
    source_url: str | None = None
    sap_release: str | None = None
    review_status: str
    score: float = Field(ge=0, le=1)


class KnowledgeSearchResponse(StrictModel):
    status: Literal["results", "insufficient_evidence"]
    evidence: list[KnowledgeEvidence]
    warnings: list[str]


class GapAnalyzeRequest(StrictModel):
    module: str = Field(default="MM", min_length=2, max_length=20)
    process_scope: str = Field(default="P2P", min_length=1, max_length=30)
    business_requirement: str = Field(min_length=1, max_length=2000)
    sap_context: SapContext = Field(default_factory=SapContext)


class GapAnalyzeResponse(StrictModel):
    outcome: Literal["candidate", "no_candidate", "insufficient_evidence"]
    gap: GapAssessment | None = None
    evidence: list[KnowledgeEvidence]
    warnings: list[str]
