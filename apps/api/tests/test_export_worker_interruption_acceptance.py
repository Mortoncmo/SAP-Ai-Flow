import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models.graph import NodeType
from app.workers.export_worker_interruption_acceptance import (
    LONG_DOCUMENT_NODE_COUNT,
    long_document_graph,
)


def test_interruption_acceptance_uses_a_valid_long_document_fixture():
    graph = long_document_graph()

    assert len(graph.nodes) == LONG_DOCUMENT_NODE_COUNT
    assert len(graph.edges) == LONG_DOCUMENT_NODE_COUNT - 1
    assert len(graph.lanes) == 4
    assert graph.nodes[0].type == NodeType.START
    assert graph.nodes[-1].type == NodeType.END
    assert all(node.id in graph.layout for node in graph.nodes)
    assert all(
        edge.source == graph.nodes[index].id
        and edge.target == graph.nodes[index + 1].id
        for index, edge in enumerate(graph.edges)
    )


def test_acceptance_render_delay_is_rejected_outside_acceptance_mode():
    with pytest.raises(ValidationError, match="only allowed in acceptance mode"):
        Settings(
            _env_file=None,
            app_env="production",
            export_acceptance_render_delay_seconds=1,
        )

    settings = Settings(
        _env_file=None,
        app_env="acceptance",
        export_acceptance_render_delay_seconds=1,
    )
    assert settings.export_acceptance_render_delay_seconds == 1
