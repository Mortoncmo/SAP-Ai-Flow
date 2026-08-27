from time import perf_counter

from fastapi import APIRouter, Depends

from app.agent.base import LLMProvider
from app.agent.factory import create_provider
from app.core.config import Settings, get_settings
from app.core.errors import FlowchartError
from app.graph.patcher import apply_patch
from app.graph.validator import graph_warnings
from app.models.api import ModifyFlowchartRequest, ModifyFlowchartResponse, ResponseMetrics
from app.security.auth import require_development_mode

router = APIRouter(prefix="/api/v1/flowcharts", tags=["flowcharts"])


def get_provider(settings: Settings = Depends(get_settings)) -> LLMProvider:
    return create_provider(settings)


@router.post("/modify", response_model=ModifyFlowchartResponse)
async def modify_flowchart(
    request: ModifyFlowchartRequest,
    _: None = Depends(require_development_mode),
    provider: LLMProvider = Depends(get_provider),
) -> ModifyFlowchartResponse:
    started = perf_counter()
    try:
        result = await provider.generate_patch(
            request.current_graph,
            request.instruction,
            request.locale,
            [],
        )
        updated = apply_patch(request.current_graph, result.patch)
    except FlowchartError as exc:
        exc.request_id = request.request_id
        raise

    latency_ms = int((perf_counter() - started) * 1000)
    return ModifyFlowchartResponse(
        request_id=request.request_id,
        base_version=request.current_graph.version,
        graph=updated,
        applied_patch=result.patch,
        warnings=graph_warnings(updated),
        metrics=ResponseMetrics(
            provider=result.provider,
            model=result.model,
            attempts=result.attempts,
            model_calls=int(getattr(provider, "external", True)),
            cache_status="bypassed",
            latency_ms=latency_ms,
        ),
    )
