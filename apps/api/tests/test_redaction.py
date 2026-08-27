import json

from app.agent.deepseek_provider import DeepSeekProvider
from app.models.graph import GraphDocument, Node
from app.models.knowledge import KnowledgeEvidence
from app.security.redaction import SensitiveDataRedactor


def test_sensitive_data_redactor_handles_text_structures_and_stable_placeholders():
    redactor = SensitiveDataRedactor()
    source = (
        "供应商：华东机密供应商，联系人：张三，邮箱 secret@example.com，"
        "备用邮箱 secret@example.com，电话 13800138000，金额 100万元"
    )
    redacted = redactor.redact_text(source)

    for sensitive_value in (
        "华东机密供应商",
        "张三",
        "secret@example.com",
        "13800138000",
        "100万元",
    ):
        assert sensitive_value not in redacted
    assert redacted.count("[EMAIL_1]") == 2
    assert "[PHONE_1]" in redacted
    assert "[AMOUNT_1]" in redacted

    structured = redactor.redact_value(
        {
            "customer_name": "机密客户",
            "supplier_name": ["供应商甲", "供应商乙"],
            "details": {"email": "buyer@example.com", "amount": 9000},
        }
    )
    assert structured["customer_name"] == "[CUSTOMER_1]"
    assert structured["supplier_name"] == "[SUPPLIER_1]"
    assert structured["details"]["email"] == "[EMAIL_2]"
    assert structured["details"]["amount"] == "[AMOUNT_2]"


def test_deepseek_payload_excludes_raw_sensitive_data_and_layout():
    graph = GraphDocument(
        graph_id="sensitive-graph",
        title="客户：机密客户",
        nodes=[
            Node(
                id="supplier",
                type="task",
                label="供应商：华东机密供应商",
                description="联系人：张三，邮箱 secret@example.com，电话 13800138000",
            )
        ],
        layout={"supplier": {"x": 120, "y": 240}},
    )
    payload = DeepSeekProvider._build_user_payload(
        graph,
        "金额 100万元，联系供应商：华东机密供应商",
        "zh-CN",
        {"type": "object"},
        [
            KnowledgeEvidence(
                evidence_ref="kb-sensitive#supplier",
                source_id="kb-sensitive",
                title="供应商资料",
                section="联系人",
                excerpt="供应商：华东机密供应商，邮箱 secret@example.com",
                source_path="MM/P2P/sensitive.md",
                source_url=None,
                sap_release="2023",
                review_status="approved",
                score=0.9,
            )
        ],
    )
    serialized = json.dumps(payload, ensure_ascii=False)

    for sensitive_value in (
        "机密客户",
        "华东机密供应商",
        "张三",
        "secret@example.com",
        "13800138000",
        "100万元",
    ):
        assert sensitive_value not in serialized
    assert "layout" not in payload["current_graph"]
    assert "[BUSINESS_PARTY_" in serialized
    assert "[EMAIL_" in serialized
    assert "[PHONE_" in serialized
    assert "[AMOUNT_" in serialized
    assert "kb-sensitive#supplier" in serialized


def test_sensitive_data_redactor_removes_authentication_secrets():
    redactor = SensitiveDataRedactor()
    structured = redactor.redact_value(
        {
            "authorization": "Bearer raw-access-token-123456",
            "access_token": "eyJheader123456.payload123456.signature123456",
            "client_secret": "client-secret-value",
            "description": "do not log sk-supersecretvalue123456",
        }
    )
    serialized = json.dumps(structured)
    for secret in (
        "raw-access-token-123456",
        "eyJheader123456.payload123456.signature123456",
        "client-secret-value",
        "sk-supersecretvalue123456",
    ):
        assert secret not in serialized
    assert "[SECRET_" in serialized
