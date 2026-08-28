from __future__ import annotations

from typing import Literal

from pydantic import SecretStr

from reelagent.config import Settings
from reelagent.intelligence.adapters.gemini import GeminiStructuredLlmClient
from reelagent.intelligence.adapters.ollama import OllamaStructuredLlmClient
from reelagent.intelligence.adapters.openai import OpenAiStructuredLlmClient
from reelagent.intelligence.ports import StructuredLlmClient


class LlmRuntimeConfigurationError(RuntimeError):
    """Raised when the configured LLM provider cannot be constructed."""


def build_structured_llm_client(
    settings: Settings,
    *,
    model: str,
) -> StructuredLlmClient:
    provider: Literal["gemini", "openai", "ollama"] = settings.llm_provider
    if provider == "ollama":
        return OllamaStructuredLlmClient(
            model=model,
            base_url=settings.ollama_base_url,
        )
    if provider == "gemini":
        if not _has_secret(settings.gemini_api_key):
            raise LlmRuntimeConfigurationError(
                "GEMINI_API_KEY is required when LLM_PROVIDER=gemini"
            )
        return GeminiStructuredLlmClient(api_key=settings.gemini_api_key, model=model)
    if not _has_secret(settings.openai_api_key):
        raise LlmRuntimeConfigurationError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
    return OpenAiStructuredLlmClient(api_key=settings.openai_api_key, model=model)


def _has_secret(value: SecretStr | None) -> bool:
    return value is not None and bool(value.get_secret_value().strip())
