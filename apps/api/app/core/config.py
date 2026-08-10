from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    agent_provider: str = "local"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    llm_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    llm_total_timeout_seconds: float = Field(default=35.0, gt=0, le=120)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_retry_backoff_seconds: float = Field(default=0.25, ge=0, le=5)
    llm_cache_ttl_seconds: float = Field(default=60.0, ge=0, le=600)
    llm_cache_max_entries: int = Field(default=128, ge=0, le=2048)
    export_retention_hours: int = Field(default=24, ge=1, le=720)
    export_stale_minutes: int = Field(default=5, ge=1, le=60)
    export_execution_mode: Literal["inline", "worker"] = "inline"
    export_worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=60)
    export_worker_batch_size: int = Field(default=8, ge=1, le=100)
    export_lease_heartbeat_seconds: float = Field(default=30.0, ge=0.1, le=60)
    database_url: str = "sqlite:///../../output/sap_blueprint.db"
    database_auto_create: bool = True
    knowledge_root: str = ""
    knowledge_index_path: str = ""
    knowledge_collection_name: str = "sap_knowledge_v1"
    knowledge_embedding_dimensions: int = Field(default=384, ge=64, le=2048)
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_algorithms: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["RS256"])
    oidc_user_id_claim: str = "sub"
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"]
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("oidc_algorithms", mode="before")
    @classmethod
    def parse_oidc_algorithms(cls, value: object) -> object:
        if isinstance(value, str):
            return [algorithm.strip().upper() for algorithm in value.split(",") if algorithm.strip()]
        return value

    @field_validator("oidc_algorithms")
    @classmethod
    def validate_oidc_algorithms(cls, value: list[str]) -> list[str]:
        allowed = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EDDSA"}
        normalized = [algorithm.upper() for algorithm in value]
        if not normalized or any(algorithm not in allowed for algorithm in normalized):
            raise ValueError("OIDC_ALGORITHMS must contain only asymmetric JWT algorithms")
        return normalized

    @field_validator("agent_provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"local", "deepseek"}:
            raise ValueError("AGENT_PROVIDER must be 'local' or 'deepseek'")
        return normalized

    @model_validator(mode="after")
    def validate_export_lease_window(self) -> Self:
        stale_seconds = self.export_stale_minutes * 60
        if self.export_lease_heartbeat_seconds * 3 > stale_seconds:
            raise ValueError(
                "EXPORT_LEASE_HEARTBEAT_SECONDS must not exceed one third of "
                "EXPORT_STALE_MINUTES"
            )
        return self

    @property
    def oidc_configured(self) -> bool:
        return bool(
            self.oidc_issuer.strip()
            and self.oidc_audience.strip()
            and self.oidc_jwks_url.strip()
            and self.oidc_user_id_claim.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
