import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.flowcharts import router as flowcharts_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.projects import router as projects_router
from app.core.config import get_settings
from app.core.errors import FlowchartError
from app.core.logging import (
    configure_logging,
    log_event,
    public_validation_errors,
    request_id,
    route_template,
    safe_stack,
)

settings = get_settings()
configure_logging(settings.log_level)
cors_headers = ["Content-Type", "Authorization", "X-Request-ID"]
if settings.app_env == "development":
    cors_headers.append("X-User-ID")

app = FastAPI(
    title="SAP AI Flow API",
    version="0.1.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url=None,
)
app.include_router(health_router)
app.include_router(flowcharts_router)
app.include_router(knowledge_router)
app.include_router(projects_router)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    trace_id = request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = trace_id
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # pragma: no cover - exercised through integration failures
        latency_ms = int((perf_counter() - started) * 1000)
        log_event(
            logging.ERROR,
            "request.failed",
            request_id=trace_id,
            method=request.method,
            route=route_template(request.scope),
            status_code=500,
            latency_ms=latency_ms,
            exception_type=type(exc).__name__,
            stack=safe_stack(exc.__traceback__),
        )
        response = JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "服务处理请求时发生内部错误。",
                    "request_id": trace_id,
                    "details": {},
                }
            },
        )
    response.headers["X-Request-ID"] = trace_id
    log_event(
        logging.INFO,
        "request.completed",
        request_id=trace_id,
        method=request.method,
        route=route_template(request.scope),
        status_code=response.status_code,
        latency_ms=int((perf_counter() - started) * 1000),
    )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=cors_headers,
    expose_headers=["Content-Disposition", "X-Request-ID"],
)


@app.exception_handler(FlowchartError)
async def flowchart_error_handler(request: Request, exc: FlowchartError) -> JSONResponse:
    trace_id = exc.request_id or request.state.request_id
    log_event(
        logging.WARNING if exc.status_code < 500 else logging.ERROR,
        "request.domain_error",
        request_id=trace_id,
        method=request.method,
        route=route_template(request.scope),
        status_code=exc.status_code,
        error_code=exc.code,
        detail_keys=sorted(exc.details),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": trace_id,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    trace_id = request.state.request_id
    errors = public_validation_errors(exc.errors())
    log_event(
        logging.WARNING,
        "request.validation_error",
        request_id=trace_id,
        method=request.method,
        route=route_template(request.scope),
        status_code=422,
        error_types=[item["type"] for item in errors],
        error_locations=[item["loc"] for item in errors],
    )
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "REQUEST_VALIDATION_FAILED",
                "message": "请求数据不符合接口协议。",
                "request_id": trace_id,
                "details": {"errors": errors},
            }
        },
    )
