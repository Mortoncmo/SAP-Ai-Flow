import asyncio

import pytest

from app.agent.base import ProviderResult
from app.agent.result_cache import ModelResultCache
from app.models.patch import LLMPatch


def _result(summary: str = "cached patch") -> ProviderResult:
    return ProviderResult(
        patch=LLMPatch.model_validate(
            {
                "change_summary": summary,
                "operations": [
                    {
                        "op": "add_lane",
                        "ref": "cached_lane",
                        "lane": {"label": "缓存泳道"},
                    }
                ],
            }
        ),
        provider="external-test",
        model="external-test-v1",
    )


@pytest.mark.asyncio
async def test_cache_hit_ttl_and_lru_eviction():
    now = [100.0]
    calls: dict[str, int] = {"a": 0, "b": 0, "c": 0}
    cache = ModelResultCache(
        ttl_seconds=10,
        max_entries=2,
        clock=lambda: now[0],
    )

    async def load(key: str) -> ProviderResult:
        calls[key] += 1
        return _result(key)

    first = await cache.get_or_create("a", lambda: load("a"))
    cached = await cache.get_or_create("a", lambda: load("a"))
    await cache.get_or_create("b", lambda: load("b"))
    await cache.get_or_create("c", lambda: load("c"))
    evicted = await cache.get_or_create("a", lambda: load("a"))

    assert first.status == "miss"
    assert cached.status == "hit"
    assert cached.model_calls == 0
    assert evicted.status == "miss"
    assert calls == {"a": 2, "b": 1, "c": 1}

    now[0] += 11
    expired = await cache.get_or_create("a", lambda: load("a"))
    assert expired.status == "miss"
    assert calls["a"] == 3


@pytest.mark.asyncio
async def test_cache_coalesces_concurrent_calls():
    cache = ModelResultCache(ttl_seconds=60, max_entries=8)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def load() -> ProviderResult:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return _result()

    tasks = [
        asyncio.create_task(cache.get_or_create("same-key", load)) for _ in range(8)
    ]
    await started.wait()
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*tasks)

    assert calls == 1
    assert [result.status for result in results].count("miss") == 1
    assert [result.status for result in results].count("shared") == 7
    assert sum(result.model_calls for result in results) == 1


@pytest.mark.asyncio
async def test_cache_does_not_store_failures():
    cache = ModelResultCache(ttl_seconds=60, max_entries=8)
    calls = 0

    async def load() -> ProviderResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary provider failure")
        return _result()

    with pytest.raises(RuntimeError, match="temporary provider failure"):
        await cache.get_or_create("retry-key", load)

    retry = await cache.get_or_create("retry-key", load)
    cached = await cache.get_or_create("retry-key", load)
    assert retry.status == "miss"
    assert cached.status == "hit"
    assert calls == 2


@pytest.mark.asyncio
async def test_cache_cancels_provider_when_last_waiter_leaves():
    cache = ModelResultCache(ttl_seconds=60, max_entries=8)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def load() -> ProviderResult:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return _result()

    lookup = asyncio.create_task(cache.get_or_create("cancel-key", load))
    await started.wait()
    lookup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await lookup
    await asyncio.wait_for(cancelled.wait(), timeout=1)
