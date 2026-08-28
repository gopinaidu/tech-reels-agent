import asyncio
import json

import httpx

from reelagent.intelligence.adapters.ollama import OllamaStructuredLlmClient


def test_ollama_structured_client_sends_schema_and_parses_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://127.0.0.1:11434/api/chat")
        body = json.loads(request.content)
        assert body["model"] == "llama3.2:latest"
        assert body["stream"] is False
        assert body["format"]["type"] == "object"
        assert body["options"]["temperature"] == 0
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": '{"verdict":"supported"}',
                }
            },
        )

    client = OllamaStructuredLlmClient(
        model="llama3.2:latest",
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


def test_ollama_retries_in_json_mode_when_schema_grammar_cannot_be_parsed() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            assert isinstance(body["format"], dict)
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": 400,
                        "message": "Failed to initialize samplers: failed to parse grammar",
                        "type": "invalid_request_error",
                    }
                },
            )
        assert body["format"] == "json"
        system_message = body["messages"][0]["content"]
        assert "Return exactly one JSON object" in system_message
        assert '"verdict"' in system_message
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": '{"verdict":"supported"}',
                }
            },
        )

    client = OllamaStructuredLlmClient(
        model="llama3.2:latest",
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
    assert len(requests) == 2
