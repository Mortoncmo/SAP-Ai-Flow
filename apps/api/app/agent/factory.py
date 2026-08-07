from app.agent.base import LLMProvider
from app.agent.deepseek_provider import DeepSeekProvider
from app.agent.local_provider import LocalRuleProvider
from app.core.config import Settings


def create_provider(settings: Settings) -> LLMProvider:
    if settings.agent_provider == "deepseek":
        return DeepSeekProvider(settings)
    return LocalRuleProvider()
