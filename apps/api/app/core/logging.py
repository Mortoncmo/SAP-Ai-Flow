import json
import logging
import re
import sys
from datetime import UTC, datetime
from traceback import extract_tb
from types import TracebackType
from typing import Any
from uuid import uuid4

from app.security.redaction import redact_log_value

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
LOGGER_NAME = "sap_ai_flow"


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "event_fields", {})
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "event": str(record.msg),
            **redact_log_value(fields),
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def configure_logging(level: str) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    if not any(getattr(handler, "sap_ai_flow_handler", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonLogFormatter())
        handler.sap_ai_flow_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    return logger


def log_event(level: int, event: str, **fields: Any) -> None:
    logging.getLogger(LOGGER_NAME).log(level, event, extra={"event_fields": fields})


def request_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if candidate and REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return f"request_{uuid4().hex}"


def route_template(scope: dict[str, Any]) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path.startswith("/") else "unmatched"


def safe_stack(traceback: TracebackType | None) -> list[dict[str, object]]:
    if traceback is None:
        return []
    frames = extract_tb(traceback)
    return [
        {
            "file": frame.filename.replace("\\", "/").rsplit("/", maxsplit=3)[-1],
            "line": frame.lineno,
            "function": frame.name,
        }
        for frame in frames[-8:]
    ]


def public_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, object]]:
    public: list[dict[str, object]] = []
    for error in errors:
        public.append(
            {
                "type": str(error.get("type", "value_error")),
                "loc": [str(item) if not isinstance(item, int) else item for item in error.get("loc", [])],
                "msg": str(error.get("msg", "请求字段无效。")),
            }
        )
    return public
