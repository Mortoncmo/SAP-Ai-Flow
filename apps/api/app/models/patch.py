from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from app.models.graph import NodeType, StrictModel


class NodeDraft(StrictModel):
    type: NodeType
    label: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class NodeChanges(StrictModel):
    type: NodeType | None = None
    label: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_change(self) -> "NodeChanges":
        if not self.model_fields_set:
            raise ValueError("At least one node field must change")
        return self


class EdgeDraft(StrictModel):
    source: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)
    label: str | None = Field(default=None, max_length=200)


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


class RemoveEdgeOperation(StrictModel):
    op: Literal["remove_edge"]
    id: str


PatchOperation = Annotated[
    Union[
        AddNodeOperation,
        RemoveNodeOperation,
        UpdateNodeOperation,
        AddEdgeOperation,
        RemoveEdgeOperation,
    ],
    Field(discriminator="op"),
]


class LLMPatch(StrictModel):
    change_summary: str = Field(min_length=1, max_length=500)
    operations: list[PatchOperation] = Field(min_length=1, max_length=100)
