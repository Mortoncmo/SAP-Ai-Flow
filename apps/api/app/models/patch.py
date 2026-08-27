from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.models.graph import NodeIcon, NodeType, SapMetadata, StrictModel


class NodeDraft(StrictModel):
    type: NodeType
    label: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    icon: NodeIcon | None = None
    lane_id: str | None = Field(default=None, min_length=1, max_length=100)
    sap: SapMetadata = Field(default_factory=SapMetadata)


class NodeChanges(StrictModel):
    type: NodeType | None = None
    label: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    icon: NodeIcon | None = None
    lane_id: str | None = Field(default=None, min_length=1, max_length=100)
    sap: SapMetadata = Field(default_factory=SapMetadata)

    @model_validator(mode="after")
    def require_change(self) -> "NodeChanges":
        if not self.model_fields_set:
            raise ValueError("At least one node field must change")
        return self


class EdgeDraft(StrictModel):
    source: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)
    label: str | None = Field(default=None, max_length=200)


class EdgeChanges(StrictModel):
    label: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def require_change(self) -> "EdgeChanges":
        if not self.model_fields_set:
            raise ValueError("At least one edge field must change")
        return self


class LaneDraft(StrictModel):
    label: str = Field(min_length=1, max_length=80)
    color: str = Field(default="#52796f", pattern="^#[0-9a-fA-F]{6}$")


class LaneChanges(StrictModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern="^#[0-9a-fA-F]{6}$")

    @model_validator(mode="after")
    def require_change(self) -> "LaneChanges":
        if not self.model_fields_set:
            raise ValueError("At least one swimlane field must change")
        return self


class AddNodeOperation(StrictModel):
    op: Literal["add_node"]
    ref: str = Field(pattern="^[a-z][a-z0-9_]{0,63}$")
    node: NodeDraft


class RemoveNodeOperation(StrictModel):
    op: Literal["remove_node"]
    id: str


class UpdateNodeOperation(StrictModel):
    op: Literal["update_node"]
    id: str
    changes: NodeChanges


class AddEdgeOperation(StrictModel):
    op: Literal["add_edge"]
    ref: str | None = Field(default=None, pattern="^[a-z][a-z0-9_]{0,63}$")
    edge: EdgeDraft


class UpdateEdgeOperation(StrictModel):
    op: Literal["update_edge"]
    id: str
    changes: EdgeChanges


class RemoveEdgeOperation(StrictModel):
    op: Literal["remove_edge"]
    id: str


class AddLaneOperation(StrictModel):
    op: Literal["add_lane"]
    ref: str = Field(pattern="^[a-z][a-z0-9_]{0,63}$")
    lane: LaneDraft


class UpdateLaneOperation(StrictModel):
    op: Literal["update_lane"]
    id: str
    changes: LaneChanges


class RemoveLaneOperation(StrictModel):
    op: Literal["remove_lane"]
    id: str


PatchOperation = Annotated[
    AddNodeOperation
    | RemoveNodeOperation
    | UpdateNodeOperation
    | AddEdgeOperation
    | UpdateEdgeOperation
    | RemoveEdgeOperation
    | AddLaneOperation
    | UpdateLaneOperation
    | RemoveLaneOperation,
    Field(discriminator="op"),
]


class LLMPatch(StrictModel):
    change_summary: str = Field(min_length=1, max_length=500)
    operations: list[PatchOperation] = Field(min_length=1, max_length=100)
