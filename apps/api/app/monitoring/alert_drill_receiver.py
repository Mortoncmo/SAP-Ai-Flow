import json
import os
import re
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import Any

MAX_BODY_BYTES = 1024 * 1024
MAX_EVENTS = 100
SAFE_ALERT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
ALLOWED_SEVERITIES = {"critical", "warning", "info"}
ALLOWED_STATUSES = {"firing", "resolved"}


def summarize_webhook(payload: object) -> list[dict[str, str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("alerts"), list):
        raise ValueError("Alertmanager webhook payload must contain an alerts list")

    webhook_status = _allowed_value(payload.get("status"), ALLOWED_STATUSES)
    summaries: list[dict[str, str]] = []
    for alert in payload["alerts"]:
        if not isinstance(alert, dict):
            continue
        labels = alert.get("labels")
        labels = labels if isinstance(labels, dict) else {}
        alert_name = str(labels.get("alertname", ""))
        if not SAFE_ALERT_NAME.fullmatch(alert_name):
            alert_name = "invalid"
        summaries.append(
            {
                "alertname": alert_name,
                "severity": _allowed_value(labels.get("severity"), ALLOWED_SEVERITIES)
                or "unknown",
                "status": _allowed_value(alert.get("status"), ALLOWED_STATUSES)
                or webhook_status
                or "unknown",
            }
        )
    if not summaries:
        raise ValueError("Alertmanager webhook payload contains no valid alerts")
    return summaries


def _allowed_value(value: object, allowed: set[str]) -> str:
    candidate = str(value or "").lower()
    return candidate if candidate in allowed else ""


class DrillState:
    def __init__(self) -> None:
        self._events: list[dict[str, str]] = []
        self._lock = Lock()

    def record(self, events: list[dict[str, str]]) -> None:
        received_at = datetime.now(UTC).isoformat()
        with self._lock:
            self._events.extend({"received_at": received_at, **event} for event in events)
            self._events = self._events[-MAX_EVENTS:]

    def report(self) -> dict[str, object]:
        with self._lock:
            events = [dict(event) for event in self._events]
        return {"status": "ok", "event_count": len(events), "events": events}


class AlertDrillHandler(BaseHTTPRequestHandler):
    state = DrillState()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._write_json(200, {"status": "ok"})
            return
        if self.path == "/events":
            self._write_json(200, self.state.report())
            return
        self._write_json(404, {"status": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/alerts":
            self._write_json(404, {"status": "not_found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > MAX_BODY_BYTES:
                raise ValueError("request body length is invalid")
            payload: Any = json.loads(self.rfile.read(content_length))
            events = summarize_webhook(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._write_json(400, {"status": "invalid"})
            return
        self.state.record(events)
        self._write_json(202, {"status": "accepted", "accepted": len(events)})

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _write_json(self, status_code: int, payload: dict[str, object]) -> None:
        content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    host = os.getenv("ALERT_DRILL_HOST", "0.0.0.0")
    port = int(os.getenv("ALERT_DRILL_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), AlertDrillHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
