from dataclasses import dataclass
from typing import Protocol

from app.models.graph import GraphDocument
from app.models.patch import LLMPatch


@dataclass(frozen=True)
class ProviderResult:
    patch: LLMPatch
    provider: str
    model: str
    attempts: int = 1


class LLMProvider(Protocol):
    async def generate_patch(
        self,
        graph: GraphDocument,
        instruction: str,
        locale: str,
    ) -> ProviderResult: ...
