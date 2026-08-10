from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

METRICS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

REGISTRY = CollectorRegistry()

HTTP_REQUESTS = Counter(
    "sap_ai_flow_http_requests_total",
    "Completed API HTTP requests.",
    labelnames=("method", "route", "status_code"),
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION = Histogram(
    "sap_ai_flow_http_request_duration_seconds",
    "API HTTP request duration in seconds.",
    labelnames=("method", "route"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30, 60),
    registry=REGISTRY,
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "sap_ai_flow_http_requests_in_progress",
    "API HTTP requests currently being processed.",
    registry=REGISTRY,
)


def request_started() -> None:
    HTTP_REQUESTS_IN_PROGRESS.inc()


def request_finished() -> None:
    HTTP_REQUESTS_IN_PROGRESS.dec()


def observe_request(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    HTTP_REQUESTS.labels(
        method=method,
        route=route,
        status_code=str(status_code),
    ).inc()
    HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(duration_seconds)


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)
