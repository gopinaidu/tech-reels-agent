"""Typed application configuration for ReelAgent."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_TOPIC_GROUPS: dict[str, tuple[str, ...]] = {
    "ai": ("LLM", "AI agent", "generative AI", "inference", "RAG"),
    "backend": ("distributed systems", "microservices", "backend", "event driven"),
    "data": ("database", "PostgreSQL", "MongoDB", "Redis", "vector database"),
    "streaming": ("Kafka", "streaming", "event processing", "Flink"),
    "languages": ("Java", "Python", "Go", "Rust", "JVM"),
    "cloud": ("Kubernetes", "Docker", "AWS", "Azure", "GCP", "serverless"),
    "architecture": ("system design", "scalability", "reliability", "performance"),
}


class Settings(BaseSettings):
    """Application settings loaded from environment variables and optional local .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str | None = None

    llm_provider: Literal["gemini", "openai", "ollama"] = "gemini"
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    brave_search_api_key: SecretStr | None = None
    serper_api_key: SecretStr | None = None
    topic_intelligence_model: str = "gemini-3.1-flash-lite"
    topic_intelligence_min_score: int = Field(default=65, ge=0, le=100)
    verification_model: str = "gemini-3.1-flash-lite"
    script_writer_model: str = "gemini-3.1-flash-lite"
    verification_search_provider: Literal["serper", "brave"] = "serper"
    verification_search_limit: int = Field(default=5, ge=1, le=10)

    tts_provider: str | None = None
    tts_api_key: SecretStr | None = None

    youtube_client_id: SecretStr | None = None
    youtube_client_secret: SecretStr | None = None
    youtube_refresh_token: SecretStr | None = None

    object_storage_endpoint: str | None = None
    object_storage_bucket: str | None = None
    object_storage_access_key: SecretStr | None = None
    object_storage_secret_key: SecretStr | None = None

    discovery_topic_groups: dict[str, tuple[str, ...]] = Field(
        default_factory=lambda: dict(_DEFAULT_TOPIC_GROUPS)
    )
    hn_trending_limit: int = Field(default=20, ge=0, le=100)
    hn_targeted_limit_per_query: int = Field(default=5, ge=1, le=25)
    hn_targeted_total_limit: int = Field(default=40, ge=1, le=100)
    hn_targeted_max_concurrency: int = Field(default=5, ge=1, le=10)
    hn_targeted_min_points: int = Field(default=10, ge=0)
    hn_targeted_min_comments: int = Field(default=5, ge=0)
    hn_targeted_freshness_days: int = Field(default=7, ge=1, le=30)
    hn_discovery_limit: int = Field(default=20, ge=1, le=100)
    hn_evidence_comment_limit: int = Field(default=12, ge=0, le=30)
    hn_evidence_comment_scan_limit: int = Field(default=80, ge=1, le=500)

    max_revision_cycles: int = Field(default=2, ge=0, le=10)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings instance."""

    return Settings()
