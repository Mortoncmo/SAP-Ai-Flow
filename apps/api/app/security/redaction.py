import re
from collections.abc import Mapping, Sequence
from typing import Any

SENSITIVE_KEYS = {
    "authorization": "SECRET",
    "access_token": "SECRET",
    "refresh_token": "SECRET",
    "id_token": "SECRET",
    "api_key": "SECRET",
    "client_secret": "SECRET",
    "password": "SECRET",
    "cookie": "SECRET",
    "set-cookie": "SECRET",
    "customer_name": "CUSTOMER",
    "supplier_name": "SUPPLIER",
    "vendor_name": "SUPPLIER",
    "contact_name": "PERSON",
    "email": "EMAIL",
    "phone": "PHONE",
    "mobile": "PHONE",
    "amount": "AMOUNT",
}

TEXT_PATTERNS = (
    (
        "SECRET",
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    ),
    (
        "SECRET",
        re.compile(r"\b(?:sk|dsk)-[A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
    ),
    (
        "SECRET",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "EMAIL",
        re.compile(r"(?<![\w.+-])[\w.+-]+@[a-z0-9.-]+\.[a-z]{2,}(?![\w.-])", re.IGNORECASE),
    ),
    (
        "PHONE",
        re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"),
    ),
    (
        "PHONE",
        re.compile(r"(?<!\d)(?:\+?\d{1,3}[- ]?)?(?:\d[- ]?){7,12}(?!\d)"),
    ),
    (
        "AMOUNT",
        re.compile(
            r"(?<!\w)(?:¥|￥|\$|USD|CNY|RMB)?\s?\d+(?:,\d{3})*(?:\.\d+)?\s?"
            r"(?:元|万元|美元|人民币|USD|CNY|RMB)(?!\w)",
            re.IGNORECASE,
        ),
    ),
    (
        "BUSINESS_PARTY",
        re.compile(
            r"(?:(?:供应商|客户|联系人|员工)(?:名称|姓名|编码|编号)\s*[:：]?|"
            r"(?:供应商|客户|联系人|员工)\s*[:：])\s*"
            r"[\u4e00-\u9fffA-Za-z0-9._-]{2,40}"
        ),
    ),
)


class SensitiveDataRedactor:
    def __init__(self) -> None:
        self._placeholders: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}

    def redact_text(self, value: str, *, max_length: int | None = None) -> str:
        result = value
        for category, pattern in TEXT_PATTERNS:
            result = pattern.sub(
                lambda match, current_category=category: self._placeholder(
                    current_category,
                    match.group(0),
                ),
                result,
            )
        if max_length is not None and len(result) > max_length:
            return f"{result[:max_length]}…"
        return result

    def redact_value(self, value: Any, *, key: str | None = None) -> Any:
        category = SENSITIVE_KEYS.get((key or "").lower())
        if category and value is not None and value != "":
            return self._placeholder(category, str(value))
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, Mapping):
            return {
                item_key: self.redact_value(item_value, key=str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            return [self.redact_value(item) for item in value]
        return value

    def _placeholder(self, category: str, raw_value: str) -> str:
        normalized = raw_value.strip().lower()
        identity = (category, normalized)
        existing = self._placeholders.get(identity)
        if existing:
            return existing
        next_count = self._counts.get(category, 0) + 1
        self._counts[category] = next_count
        placeholder = f"[{category}_{next_count}]"
        self._placeholders[identity] = placeholder
        return placeholder


def redact_log_value(value: Any) -> Any:
    return SensitiveDataRedactor().redact_value(value)


def redact_log_text(value: str, *, max_length: int = 2000) -> str:
    return SensitiveDataRedactor().redact_text(value, max_length=max_length)
