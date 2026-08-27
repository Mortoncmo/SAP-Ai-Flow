import os

import pytest

from app.models.graph import Edge, GraphDocument, Node, NodeType, Position


@pytest.fixture(scope="session", autouse=True)
def isolated_test_runtime(tmp_path_factory):
    runtime_root = tmp_path_factory.mktemp("sap-ai-flow-runtime")
    overrides = {
        "DATABASE_URL": f"sqlite:///{(runtime_root / 'app.db').as_posix()}",
        "KNOWLEDGE_INDEX_PATH": str(runtime_root / "chroma"),
    }
    previous = {name: os.environ.get(name) for name in overrides}
    os.environ.update(overrides)

    from app.core.config import get_settings
    from app.db.database import get_database
    from app.knowledge.service import get_knowledge_service

    get_settings.cache_clear()
    get_database.cache_clear()
    get_knowledge_service.cache_clear()
    try:
        yield
    finally:
        get_knowledge_service.cache_clear()
        get_database.cache_clear()
        get_settings.cache_clear()
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture
def order_graph() -> GraphDocument:
    return GraphDocument(
        graph_id="graph_test",
        version=2,
        title="订单流程",
        nodes=[
            Node(id="start", type=NodeType.START, label="开始"),
            Node(id="submit", type=NodeType.TASK, label="提交销售订单"),
            Node(id="credit", type=NodeType.DECISION, label="信用检查"),
            Node(id="ship", type=NodeType.TASK, label="仓库出库"),
            Node(id="end", type=NodeType.END, label="结束"),
        ],
        edges=[
            Edge(id="e1", source="start", target="submit"),
            Edge(id="e2", source="submit", target="credit"),
            Edge(id="e3", source="credit", target="ship", label="通过"),
            Edge(id="e4", source="credit", target="end", label="拒绝"),
            Edge(id="e5", source="ship", target="end"),
        ],
        layout={"credit": Position(x=100, y=200)},
    )
