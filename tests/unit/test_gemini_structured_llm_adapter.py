import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from reelagent.intelligence.adapters.gemini import (
    GeminiStructuredLlmClient,
    GeminiStructuredLlmError,
)


def test_gemini_structured_client_sends_schema_and_parses_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "gemini-secret"
        assert request.url.path.endswith("/models/gemini-3.1-flash-lite:generateContent")
        body = json.loads(request.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["generationConfig"]["responseJsonSchema"]["type"] == "object"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": '{"verdict":"supported"}'}]}}
                ]
            },
        )

    client = GeminiStructuredLlmClient(
        api_key=SecretStr("gemini-secret"),
        model="gemini-3.1-flash-lite",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        client.generate_json(
            system_prompt="Verify the claim.",
            input_payload={"claim": "example"},
            output_schema={"type": "object", "properties": {"verdict": {"type": "string"}}},
        )
    )

    assert result == {"verdict": "supported"}


def test_gemini_structured_client_retries_429_once() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": {"message": "quota temporarily exceeded"}})
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}]},
        )

    client = GeminiStructuredLlmClient(
        api_key=SecretStr("gemini-secret"),
        model="gemini-3.1-flash-lite",
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(
        client.generate_json(
            system_prompt="Return JSON.",
            input_payload={"value": 1},
            output_schema={"type": "object"},
        )
    )

    assert result == {"ok": True}
    assert calls == 2


def test_gemini_structured_client_reports_http_status_and_provider_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Invalid JSON schema"}})

    client = GeminiStructuredLlmClient(
        api_key=SecretStr("gemini-secret"),
        model="gemini-3.1-flash-lite",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(
        GeminiStructuredLlmError,
        match="HTTP 400: Invalid JSON schema",
    ):
        asyncio.run(
            client.generate_json(
                system_prompt="Return JSON.",
                input_payload={"value": 1},
                output_schema={"type": "object"},
            )
        )
