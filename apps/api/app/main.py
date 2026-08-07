from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.flowcharts import router as flowcharts_router
from app.api.routes.health import router as health_router
from app.core.config import get_settings
from app.core.errors import FlowchartError

settings = get_settings()

app = FastAPI(
    title="SAP AI Flow API",
    version="0.1.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID"],
)
app.include_router(health_router)
app.include_router(flowcharts_router)


@app.exception_handler(FlowchartError)
async def flowchart_error_handler(_: Request, exc: FlowchartError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": exc.request_id,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "REQUEST_VALIDATION_FAILED",
                "message": "请求数据不符合接口协议。",
                "request_id": None,
                "details": {"errors": exc.errors()},
            }
        },
    )
