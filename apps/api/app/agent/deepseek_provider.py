import asyncio
import json

import httpx
from pydantic import ValidationError

from app.agent.base import ProviderResult
from app.core.config import Settings
from app.core.errors import ProviderError
from app.models.graph import GraphDocument
from app.models.knowledge import KnowledgeEvidence
from app.models.patch import LLMPatch
from app.security.redaction import SensitiveDataRedactor

SYSTEM_PROMPT = """你是 SAP 业务流程建模助手。根据 current_graph 和 instruction，只输出 JSON Patch。
必须保留未被指令涉及的节点与连线。禁止输出 Markdown、解释文字或思维过程。
新增节点使用 ref，当前 Patch 内引用新节点时使用 @ref；已有节点使用输入中的永久 ID。
合法节点类型：start、end、task、decision、subprocess。
节点可选 icon：user、building、shield-check、file-text、package、truck、circle-dollar-sign、clipboard-check。
节点可通过 lane_id 归属泳道。创建泳道后使用 @ref 在同一 Patch 中引用。
节点可以包含 sap 元数据：step_type、tcodes、fiori_apps、roles、configuration_points、best_practice_refs 和 gap。
SAP 专业字段必须有当前输入中的证据，无法确认时使用 pending_confirmation，禁止凭记忆捏造 T-Code、Fiori App、配置点或 BAdI。
GAP 只能输出 candidate，不得输出 confirmed、resolved 或 rejected。
合法操作：add_node、remove_node、update_node、add_edge、update_edge、remove_edge、add_lane、update_lane、remove_lane。
update_edge 只能修改连线 label，必须保留永久 ID、source 和 target；改变端点时在同一 Patch 中使用 remove_edge + add_edge。
输出字段必须是 change_summary 和 operations，并严格遵循提供的 JSON Schema。"""


class DeepSeekProvider:
    external = True

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not settings.deepseek_api_key:
            raise ProviderError(
                "PROVIDER_NOT_CONFIGURED",
                "使用 DeepSeek Provider 前必须配置 DEEPSEEK_API_KEY。",
            )
        self.settings = settings
        self.transport = transport

    async def generate_patch(
        self,
        graph: GraphDocument,
        instruction: str,
        locale: str,
        evidence: list[KnowledgeEvidence] | None = None,
    ) -> ProviderResult:
        schema = LLMPatch.model_json_schema()
        user_payload = self._build_user_payload(
            graph,
            instruction,
            locale,
            schema,
            evidence or [],
        )
        attempts = 0
        last_error = ""
        last_failure = "invalid"
        max_attempts = self.settings.llm_max_retries + 1

        try:
            async with asyncio.timeout(self.settings.llm_total_timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=self.settings.llm_timeout_seconds,
                    transport=self.transport,
                ) as client:
                    for attempts in range(1, max_attempts + 1):
                        try:
                            response = await client.post(
                                f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                                headers={
                                    "Authorization": f"Bearer {self.settings.deepseek_api_key}"
                                },
                                json={
                                    "model": self.settings.deepseek_model,
                                    "response_format": {"type": "json_object"},
                                    "temperature": 0.1,
                                    "messages": [
                                        {"role": "system", "content": SYSTEM_PROMPT},
                                        {
                                            "role": "user",
                                            "content": json.dumps(
                                                user_payload, ensure_ascii=False
                                            ),
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
                                last_failure = "rate_limit"
                                last_error = "HTTP_429"
                            elif response.status_code >= 500:
                                last_failure = "unavailable"
                                last_error = f"HTTP_{response.status_code}"
                            elif response.status_code >= 400:
                                raise ProviderError(
                                    "PROVIDER_REQUEST_REJECTED",
                                    "DeepSeek 拒绝了当前请求，请检查模型和接口配置。",
                                    details={"status_code": response.status_code},
                                )
                            else:
                                content = response.json()["choices"][0]["message"][
                                    "content"
                                ]
                                patch = LLMPatch.model_validate_json(content)
                                return ProviderResult(
                                    patch=patch,
                                    provider="deepseek",
                                    model=self.settings.deepseek_model,
                                    attempts=attempts,
                                )
                        except ProviderError:
                            raise
                        except httpx.TimeoutException as exc:
                            last_failure = "timeout"
                            last_error = type(exc).__name__
                        except httpx.TransportError as exc:
                            last_failure = "unavailable"
                            last_error = type(exc).__name__
                        except (KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
                            last_failure = "invalid"
                            last_error = type(exc).__name__

                        if attempts < max_attempts:
                            await asyncio.sleep(
                                self.settings.llm_retry_backoff_seconds
                                * (2 ** (attempts - 1))
                            )
        except TimeoutError as exc:
            raise ProviderError(
                "PROVIDER_TIMEOUT",
                "模型服务响应超时，当前流程未发生更改，请重试。",
                details={"attempts": attempts},
            ) from exc

        error_code, message = {
            "timeout": (
                "PROVIDER_TIMEOUT",
                "模型服务响应超时，当前流程未发生更改，请重试。",
            ),
            "rate_limit": (
                "PROVIDER_RATE_LIMITED",
                "模型服务请求已被限流，请稍后重试。",
            ),
            "unavailable": (
                "PROVIDER_UNAVAILABLE",
                "模型服务暂时不可用，当前流程未发生更改，请稍后重试。",
            ),
            "invalid": (
                "MODEL_OUTPUT_INVALID",
                "DeepSeek 未返回可用的结构化 Patch。",
            ),
        }[last_failure]
        raise ProviderError(
            error_code,
            message,
            details={"attempts": attempts, "reason": last_error},
        )

    @staticmethod
    def _build_user_payload(
        graph: GraphDocument,
        instruction: str,
        locale: str,
        schema: dict[str, object],
        evidence: list[KnowledgeEvidence] | None = None,
    ) -> dict[str, object]:
        redactor = SensitiveDataRedactor()
        graph_data = graph.model_dump(exclude={"layout"}, mode="json")
        return {
            "locale": locale,
            "current_graph": redactor.redact_value(graph_data),
            "instruction": redactor.redact_text(instruction),
            "evidence": redactor.redact_value(
                [item.model_dump(mode="json") for item in evidence or []]
            ),
            "output_schema": schema,
        }
