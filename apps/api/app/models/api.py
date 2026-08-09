from typing import Literal

from pydantic import Field

from app.models.graph import GraphDocument, StrictModel
from app.models.patch import LLMPatch


class ModifyFlowchartRequest(StrictModel):
    request_id: str = Field(min_length=1, max_length=80)
    current_graph: GraphDocument
    instruction: str = Field(min_length=1, max_length=4000)
    locale: str = Field(default="zh-CN", max_length=20)


class ResponseMetrics(StrictModel):
    provider: str
    model: str
    attempts: int = Field(ge=0)
    model_calls: int = Field(ge=0, le=1)
    cache_status: Literal["bypassed", "miss", "hit", "shared"]
    latency_ms: int = Field(ge=0)


class ModifyFlowchartResponse(StrictModel):
    request_id: str
    base_version: int
    graph: GraphDocument
    applied_patch: LLMPatch
    warnings: list[str]
    metrics: ResponseMetrics


class ApiErrorBody(StrictModel):
    code: str
    message: str
    request_id: str | None = None
    details: dict[str, object] = Field(default_factory=dict)


class ApiErrorResponse(StrictModel):
    error: ApiErrorBody
