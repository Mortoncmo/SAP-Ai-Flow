from datetime import datetime
from typing import Literal

from pydantic import Field

from app.models.api import ResponseMetrics
from app.models.graph import GraphDocument, SapContext, StrictModel
from app.models.knowledge import KnowledgeEvidence
from app.models.patch import LLMPatch


class ProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    customer_name: str | None = Field(default=None, max_length=100)
    sap_context: SapContext = Field(default_factory=SapContext)


class ProjectResponse(StrictModel):
    id: str
    name: str
    customer_name: str | None
    sap_context: SapContext
    external_model_enabled: bool
    current_role: Literal["viewer", "editor", "consultant_approver", "project_admin"]
    created_at: datetime
    updated_at: datetime


class ProjectSettingsUpdate(StrictModel):
    external_model_enabled: bool


class ProjectAuditResponse(StrictModel):
    id: str
    project_id: str
    action: str
    before_value: dict[str, object]
    after_value: dict[str, object]
    actor_user_id: str
    created_at: datetime


class ProjectMemberUpsert(StrictModel):
    user_id: str = Field(min_length=1, max_length=80)
    role: Literal["viewer", "editor", "consultant_approver", "project_admin"]


class ProjectMemberResponse(StrictModel):
    project_id: str
    user_id: str
    role: Literal["viewer", "editor", "consultant_approver", "project_admin"]
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class ProcessCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    module: str = Field(default="MM", min_length=2, max_length=20)
    process_scope: str = Field(default="P2P", min_length=1, max_length=30)
    initial_graph: GraphDocument | None = None


class ProcessSummary(StrictModel):
    id: str
    project_id: str
    name: str
    module: str
    process_scope: str
    status: str
    current_revision: int
    latest_release_no: int | None
    created_at: datetime
    updated_at: datetime


class ProcessDetail(ProcessSummary):
    graph: GraphDocument


class PersistedModifyRequest(StrictModel):
    request_id: str = Field(min_length=1, max_length=80)
    base_revision: int = Field(ge=0)
    instruction: str = Field(min_length=1, max_length=4000)
    locale: str = Field(default="zh-CN", max_length=20)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class PersistedModifyResponse(StrictModel):
    request_id: str
    base_revision: int
    result_revision: int
    graph: GraphDocument
    applied_patch: LLMPatch
    evidence: list[KnowledgeEvidence]
    warnings: list[str]
    metrics: ResponseMetrics


class ManualSaveRequest(StrictModel):
    request_id: str = Field(min_length=1, max_length=80)
    base_revision: int = Field(ge=0)
    graph: GraphDocument
    summary: str = Field(default="保存画布修订", min_length=1, max_length=500)


class ManualSaveResponse(StrictModel):
    request_id: str
    base_revision: int
    result_revision: int
    graph: GraphDocument


class DrawioSaveRequest(StrictModel):
    request_id: str = Field(min_length=1, max_length=80)
    base_revision: int = Field(ge=0)
    base_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    xml: str = Field(min_length=1, max_length=5_000_000)
    xml_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    graph: GraphDocument
    summary: str = Field(default="保存 Draw.io 修订", min_length=1, max_length=500)


class DrawioRevisionResponse(StrictModel):
    process_id: str
    revision_no: int
    xml: str | None
    xml_sha256: str | None
    graph: GraphDocument


class RevisionResponse(StrictModel):
    revision_no: int
    release_no: int | None
    lifecycle_state: str
    schema_version: str
    created_by: str
    created_at: datetime


class RevisionDetailResponse(RevisionResponse):
    process_id: str
    graph: GraphDocument


class ReleaseCreate(StrictModel):
    base_revision: int = Field(ge=0)


class ReleaseResponse(StrictModel):
    process_id: str
    revision_no: int
    release_no: int
    lifecycle_state: str


class GapDecisionCreate(StrictModel):
    base_revision: int = Field(ge=0)
    to_status: Literal["confirmed", "rejected", "resolved"]
    comment: str = Field(min_length=1, max_length=1000)


class GapDecisionResponse(StrictModel):
    process_id: str
    node_id: str
    revision_no: int
    from_status: str
    to_status: str
    comment: str
    decided_by: str
    decided_at: datetime
    graph: GraphDocument


class ExportRequest(StrictModel):
    revision_no: int = Field(ge=0)
    format: Literal["markdown", "docx"]


class ExportJobResponse(StrictModel):
    export_id: str
    process_id: str
    revision_no: int
    format: Literal["markdown", "docx"]
    status: Literal["pending", "running", "completed", "failed", "expired"]
    attempt_count: int
    filename: str | None
    content_length: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime | None
    download_url: str | None


class DraftCreate(StrictModel):
    source_revision: int = Field(ge=0)
