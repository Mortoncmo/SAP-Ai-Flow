from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NodeType(StrEnum):
    START = "start"
    END = "end"
    TASK = "task"
    DECISION = "decision"
    SUBPROCESS = "subprocess"


class Position(StrictModel):
    x: float
    y: float


class Node(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    type: NodeType
    label: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class Edge(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=200)


class GraphDocument(StrictModel):
    schema_version: str = "1.0"
    graph_id: str = Field(min_length=1, max_length=80)
    version: int = Field(default=0, ge=0)
    title: str = Field(default="未命名流程", min_length=1, max_length=100)
    direction: str = Field(default="TB", pattern="^(TB|LR)$")
    nodes: list[Node] = Field(default_factory=list, max_length=500)
    edges: list[Edge] = Field(default_factory=list, max_length=1000)
    layout: dict[str, Position] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph(self) -> "GraphDocument":
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Node IDs must be unique")

        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Edge IDs must be unique")

        known_nodes = set(node_ids)
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
