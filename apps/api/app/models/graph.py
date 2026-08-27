from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NodeType(StrEnum):
    START = "start"
    END = "end"
    TASK = "task"
    DECISION = "decision"
    SUBPROCESS = "subprocess"


class NodeIcon(StrEnum):
    USER = "user"
    BUILDING = "building"
    SHIELD_CHECK = "shield-check"
    FILE_TEXT = "file-text"
    PACKAGE = "package"
    TRUCK = "truck"
    CIRCLE_DOLLAR_SIGN = "circle-dollar-sign"
    CLIPBOARD_CHECK = "clipboard-check"


class SapStepType(StrEnum):
    TRANSACTION = "transaction"
    APPROVAL = "approval"
    VALIDATION = "validation"
    MANUAL = "manual"
    INTEGRATION = "integration"


class MetadataStatus(StrEnum):
    SUGGESTED = "suggested"
    PENDING_CONFIRMATION = "pending_confirmation"
    VERIFIED = "verified"


class GapStatus(StrEnum):
    NONE = "none"
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class Position(StrictModel):
    x: float
    y: float


class SapContext(StrictModel):
    edition: str = Field(default="S/4HANA", min_length=1, max_length=50)
    release: str = Field(default="2023", min_length=1, max_length=30)
    deployment: str = Field(default="private_cloud", min_length=1, max_length=30)
    country: str = Field(default="CN", min_length=1, max_length=20)


class TCodeReference(StrictModel):
    code: str = Field(min_length=1, max_length=40)
    status: MetadataStatus = MetadataStatus.PENDING_CONFIRMATION
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=120)


class FioriAppReference(StrictModel):
    app_id: str | None = Field(default=None, min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    status: MetadataStatus = MetadataStatus.PENDING_CONFIRMATION
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=120)


class ConfigurationPoint(StrictModel):
    label: str = Field(min_length=1, max_length=160)
    status: MetadataStatus = MetadataStatus.PENDING_CONFIRMATION
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=120)


class BestPracticeReference(StrictModel):
    scope_item: str = Field(min_length=1, max_length=40)
    step: str = Field(min_length=1, max_length=160)
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=120)


class GapAssessment(StrictModel):
    status: GapStatus = GapStatus.NONE
    category: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    recommendation: str | None = Field(default=None, max_length=1000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    owner: str | None = Field(default=None, max_length=120)


class SapMetadata(StrictModel):
    step_type: SapStepType | None = None
    tcodes: list[TCodeReference] = Field(default_factory=list, max_length=10)
    fiori_apps: list[FioriAppReference] = Field(default_factory=list, max_length=10)
    roles: list[str] = Field(default_factory=list, max_length=20)
    configuration_points: list[ConfigurationPoint] = Field(default_factory=list, max_length=20)
    best_practice_refs: list[BestPracticeReference] = Field(default_factory=list, max_length=20)
    gap: GapAssessment = Field(default_factory=GapAssessment)


class Node(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    type: NodeType
    label: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    icon: NodeIcon | None = None
    lane_id: str | None = Field(default=None, min_length=1, max_length=80)
    sap: SapMetadata = Field(default_factory=SapMetadata)


class Swimlane(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=80)
    color: str = Field(default="#52796f", pattern="^#[0-9a-fA-F]{6}$")


class Edge(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=200)


class GraphDocument(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    graph_id: str = Field(min_length=1, max_length=80)
    version: int = Field(default=0, ge=0)
    title: str = Field(default="未命名流程", min_length=1, max_length=100)
    module: str = Field(default="MM", min_length=2, max_length=20, pattern="^[A-Z0-9_-]+$")
    process_scope: str = Field(
        default="P2P", min_length=1, max_length=30, pattern="^[A-Za-z0-9_-]+$"
    )
    sap_context: SapContext = Field(default_factory=SapContext)
    direction: str = Field(default="TB", pattern="^(TB|LR)$")
    nodes: list[Node] = Field(default_factory=list, max_length=500)
    edges: list[Edge] = Field(default_factory=list, max_length=1000)
    lanes: list[Swimlane] = Field(default_factory=list, max_length=20)
    layout: dict[str, Position] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_graph(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        payload = dict(value)
        schema_version = payload.get("schema_version", "1.0")
        if schema_version != "1.0":
            return payload

        payload["schema_version"] = "2.0"
        payload.setdefault("module", "MM")
        payload.setdefault("process_scope", "P2P")
        payload.setdefault("sap_context", {})
        payload["nodes"] = [
            {**node, "sap": node.get("sap") or {}}
            if isinstance(node, dict)
            else node
            for node in payload.get("nodes", [])
        ]
        return payload

    @model_validator(mode="after")
    def validate_graph(self) -> "GraphDocument":
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Node IDs must be unique")

        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Edge IDs must be unique")

        known_nodes = set(node_ids)
        lane_ids = [lane.id for lane in self.lanes]
        if len(lane_ids) != len(set(lane_ids)):
            raise ValueError("Swimlane IDs must be unique")
        known_lanes = set(lane_ids)

        for node in self.nodes:
            if node.lane_id is not None and node.lane_id not in known_lanes:
                raise ValueError(f"Node {node.id} references an unknown swimlane")

        for edge in self.edges:
            if edge.source not in known_nodes or edge.target not in known_nodes:
                raise ValueError(f"Edge {edge.id} references an unknown node")
            if edge.source == edge.target:
                raise ValueError(f"Edge {edge.id} cannot connect a node to itself")

        edge_keys = [(edge.source, edge.target, edge.label or "") for edge in self.edges]
        if len(edge_keys) != len(set(edge_keys)):
            raise ValueError("Duplicate edges are not allowed")

        self.layout = {
            node_id: position for node_id, position in self.layout.items() if node_id in known_nodes
        }
        return self


def empty_graph(graph_id: str, title: str = "未命名流程") -> GraphDocument:
    return GraphDocument(graph_id=graph_id, title=title)
