import asyncio
import json
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from hashlib import sha256
from threading import Lock
from time import monotonic
from typing import Literal

from app.agent.base import LLMProvider, ProviderResult
from app.models.graph import GraphDocument
from app.models.knowledge import KnowledgeEvidence

CacheStatus = Literal["bypassed", "miss", "hit", "shared"]


@dataclass(frozen=True)
class CacheLookup:
    result: ProviderResult
    status: CacheStatus
    model_calls: int


@dataclass(frozen=True)
class _CacheEntry:
    result: ProviderResult
    expires_at: float


@dataclass
class _InFlight:
    task: asyncio.Task[ProviderResult]
    waiters: int = 0


class ModelResultCache:
    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_entries: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._inflight: dict[tuple[str, int], _InFlight] = {}
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds > 0 and self.max_entries > 0

    async def get_or_create(
        self,
        key: str,
        factory: Callable[[], Awaitable[ProviderResult]],
    ) -> CacheLookup:
        if not self.enabled:
            return CacheLookup(await factory(), "bypassed", 1)

        flight_key = (key, id(asyncio.get_running_loop()))
        with self._lock:
            now = self.clock()
            self._discard_expired(now)
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
                return CacheLookup(_clone_result(entry.result), "hit", 0)

            flight = self._inflight.get(flight_key)
            if flight is None:
                flight = _InFlight(task=asyncio.create_task(factory()))
                self._inflight[flight_key] = flight
                status: CacheStatus = "miss"
                model_calls = 1
            else:
                status = "shared"
                model_calls = 0
            flight.waiters += 1

        try:
            result = await asyncio.shield(flight.task)
        finally:
            with self._lock:
                current = self._inflight.get(flight_key)
                if current is flight:
                    flight.waiters -= 1
                    if flight.task.done():
                        self._inflight.pop(flight_key, None)
                        if not flight.task.cancelled() and flight.task.exception() is None:
                            self._store(key, flight.task.result(), self.clock())
                    elif flight.waiters == 0:
                        self._inflight.pop(flight_key, None)
                        flight.task.cancel()

        return CacheLookup(_clone_result(result), status, model_calls)

    def _discard_expired(self, now: float) -> None:
        expired = [
            key for key, entry in self._entries.items() if entry.expires_at <= now
        ]
        for key in expired:
            self._entries.pop(key, None)

    def _store(self, key: str, result: ProviderResult, now: float) -> None:
        self._discard_expired(now)
        self._entries.pop(key, None)
        while len(self._entries) >= self.max_entries:
            self._entries.popitem(last=False)
        self._entries[key] = _CacheEntry(
            result=_clone_result(result),
            expires_at=now + self.ttl_seconds,
        )


def build_model_cache_key(
    *,
    namespace: str,
    provider: LLMProvider,
    graph: GraphDocument,
    instruction: str,
    locale: str,
    evidence: list[KnowledgeEvidence],
) -> str:
    payload = {
        "namespace": namespace,
        "provider": _provider_identity(provider),
        "graph": graph.model_dump(mode="json"),
        "instruction": instruction,
        "locale": locale,
        "evidence": [item.model_dump(mode="json") for item in evidence],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _provider_identity(provider: LLMProvider) -> str:
    explicit = getattr(provider, "cache_identity", None)
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    identity = f"{type(provider).__module__}.{type(provider).__qualname__}"
    settings = getattr(provider, "settings", None)
    if settings is None:
        return identity
    model = str(getattr(settings, "deepseek_model", "")).strip()
    base_url = str(getattr(settings, "deepseek_base_url", "")).strip().rstrip("/")
    return f"{identity}:{base_url}:{model}"


def _clone_result(result: ProviderResult) -> ProviderResult:
    return ProviderResult(
        patch=result.patch.model_copy(deep=True),
        provider=result.provider,
        model=result.model,
        attempts=result.attempts,
    )
