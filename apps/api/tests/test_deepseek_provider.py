import asyncio
import json

import httpx
import pytest

from app.agent.deepseek_provider import DeepSeekProvider
from app.core.config import Settings
from app.core.errors import ProviderError


def provider_settings(**changes: object) -> Settings:
    values: dict[str, object] = {
        "deepseek_api_key": "test-key",
        "llm_timeout_seconds": 1,
        "llm_total_timeout_seconds": 5,
        "llm_max_retries": 2,
        "llm_retry_backoff_seconds": 0,
    }
    values.update(changes)
    return Settings(**values)


def valid_response(request: httpx.Request) -> httpx.Response:
    content = json.dumps(
        {
            "change_summary": "为信用检查增加图标。",
            "operations": [
                {
                    "op": "update_node",
                    "id": "credit",
                    "changes": {"icon": "shield-check"},
                }
            ],
        },
        ensure_ascii=False,
    )
    return httpx.Response(
        200,
        request=request,
        json={"choices": [{"message": {"content": content}}]},
    )


@pytest.mark.asyncio
async def test_deepseek_retries_timeouts_then_returns_valid_patch(order_graph):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ReadTimeout("slow provider", request=request)
        return valid_response(request)

    provider = DeepSeekProvider(
        provider_settings(),
        transport=httpx.MockTransport(handler),
    )
    result = await provider.generate_patch(order_graph, "增加图标", "zh-CN")

    assert calls == 3
    assert result.attempts == 3
    assert result.patch.operations[0].op == "update_node"


@pytest.mark.asyncio
async def test_deepseek_retries_rate_limit_then_succeeds(order_graph):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, request=request)
        return valid_response(request)

    provider = DeepSeekProvider(
        provider_settings(),
        transport=httpx.MockTransport(handler),
    )
    result = await provider.generate_patch(order_graph, "增加图标", "zh-CN")

    assert calls == 2
    assert result.attempts == 2


@pytest.mark.asyncio
async def test_deepseek_does_not_retry_authentication_failures(order_graph):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, request=request)

    provider = DeepSeekProvider(
        provider_settings(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderError) as raised:
        await provider.generate_patch(order_graph, "增加图标", "zh-CN")

    assert calls == 1
    assert raised.value.code == "PROVIDER_AUTH_FAILED"


@pytest.mark.asyncio
async def test_deepseek_reports_exhausted_transient_failure_without_payload(order_graph):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request, text="sensitive upstream body")

    provider = DeepSeekProvider(
        provider_settings(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderError) as raised:
        await provider.generate_patch(order_graph, "增加图标", "zh-CN")

    assert calls == 3
    assert raised.value.code == "PROVIDER_UNAVAILABLE"
    assert raised.value.details == {"attempts": 3, "reason": "HTTP_503"}
    assert "sensitive upstream body" not in str(raised.value.details)


@pytest.mark.asyncio
async def test_deepseek_total_deadline_stops_a_slow_attempt(order_graph):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.1)
        return valid_response(request)

    provider = DeepSeekProvider(
        provider_settings(llm_total_timeout_seconds=0.02),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderError) as raised:
        await provider.generate_patch(order_graph, "增加图标", "zh-CN")

    assert calls == 1
    assert raised.value.code == "PROVIDER_TIMEOUT"
    assert raised.value.details == {"attempts": 1}


@pytest.mark.asyncio
async def test_deepseek_classifies_exhausted_invalid_output(order_graph):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    provider = DeepSeekProvider(
        provider_settings(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderError) as raised:
        await provider.generate_patch(order_graph, "增加图标", "zh-CN")

    assert calls == 3
    assert raised.value.code == "MODEL_OUTPUT_INVALID"
    assert raised.value.details["attempts"] == 3
