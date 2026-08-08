import json

import httpx
from pydantic import ValidationError

from app.agent.base import ProviderResult
from app.core.config import Settings
from app.core.errors import ProviderError
from app.models.graph import GraphDocument
from app.models.patch import LLMPatch

SYSTEM_PROMPT = """你是 SAP 业务流程建模助手。根据 current_graph 和 instruction，只输出 JSON Patch。
必须保留未被指令涉及的节点与连线。禁止输出 Markdown、解释文字或思维过程。
新增节点使用 ref，当前 Patch 内引用新节点时使用 @ref；已有节点使用输入中的永久 ID。
合法节点类型：start、end、task、decision、subprocess。
节点可选 icon：user、building、shield-check、file-text、package、truck、circle-dollar-sign、clipboard-check。
节点可通过 lane_id 归属泳道。创建泳道后使用 @ref 在同一 Patch 中引用。
合法操作：add_node、remove_node、update_node、add_edge、remove_edge、add_lane、update_lane、remove_lane。
输出字段必须是 change_summary 和 operations，并严格遵循提供的 JSON Schema。"""


class DeepSeekProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.deepseek_api_key:
            raise ProviderError(
                "PROVIDER_NOT_CONFIGURED",
                "使用 DeepSeek Provider 前必须配置 DEEPSEEK_API_KEY。",
            )
        self.settings = settings

    async def generate_patch(
        self,
        graph: GraphDocument,
        instruction: str,
        locale: str,
    ) -> ProviderResult:
        schema = LLMPatch.model_json_schema()
        graph_data = graph.model_dump(exclude={"layout"}, mode="json")
        user_payload = {
            "locale": locale,
            "current_graph": graph_data,
            "instruction": instruction,
            "output_schema": schema,
        }
        attempts = 0
        last_error = ""
        max_attempts = self.settings.llm_max_retries + 1

        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
            for attempts in range(1, max_attempts + 1):
                try:
                    response = await client.post(
                        f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {self.settings.deepseek_api_key}"},
                        json={
                            "model": self.settings.deepseek_model,
                            "response_format": {"type": "json_object"},
                            "temperature": 0.1,
                            "messages": [
                                {"role": "system", "content": SYSTEM_PROMPT},
                                {
                                    "role": "user",
                                    "content": json.dumps(user_payload, ensure_ascii=False),
                                },
                            ],
                        },
                    )
                    if response.status_code in {401, 403}:
                        raise ProviderError(
                            "PROVIDER_AUTH_FAILED",
                            "DeepSeek 认证失败，请检查 API Key。",
                        )
                    if response.status_code == 429:
                        raise ProviderError("PROVIDER_RATE_LIMITED", "DeepSeek 请求已被限流。")
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
                    patch = LLMPatch.model_validate_json(content)
                    return ProviderResult(
                        patch=patch,
                        provider="deepseek",
                        model=self.settings.deepseek_model,
                        attempts=attempts,
                    )
                except ProviderError:
                    raise
                except (httpx.HTTPError, KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
                    last_error = type(exc).__name__

        raise ProviderError(
            "MODEL_OUTPUT_INVALID",
            "DeepSeek 未返回可用的结构化 Patch。",
            details={"attempts": attempts, "reason": last_error},
        )
