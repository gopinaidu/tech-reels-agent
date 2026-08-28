from __future__ import annotations

import json
from typing import Any

import httpx


class OllamaStructuredLlmError(RuntimeError):
    """Raised when Ollama cannot return usable structured JSON."""


class OllamaStructuredLlmClient:
    """Call a local Ollama server with structured JSON output."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    async def generate_json(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        output_schema: dict[str, Any],
    ) -> dict[str, Any]:
        body = _request_body(
            model=self._model,
            system_prompt=system_prompt,
            input_payload=input_payload,
            output_format=output_schema,
        )
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(f"{self._base_url}/api/chat", json=body)
                if _is_grammar_parse_error(response):
                    fallback_body = _request_body(
                        model=self._model,
                        system_prompt=_json_mode_system_prompt(system_prompt, output_schema),
                        input_payload=input_payload,
                        output_format="json",
                    )
                    response = await client.post(
                        f"{self._base_url}/api/chat",
                        json=fallback_body,
                    )
                response.raise_for_status()
                payload = response.json()
        except httpx.ConnectError as exc:
            raise OllamaStructuredLlmError(
                f"Could not connect to Ollama at {self._base_url}; ensure Ollama is running"
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = _safe_error_detail(exc.response)
            raise OllamaStructuredLlmError(
                f"Ollama structured generation failed with HTTP "
                f"{exc.response.status_code}: {detail}"
            ) from exc
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise OllamaStructuredLlmError("Ollama structured generation failed") from exc

        message = payload.get("message") if isinstance(payload, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise OllamaStructuredLlmError("Ollama response is missing message content")
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError) as exc:
            raise OllamaStructuredLlmError("Ollama returned invalid JSON output") from exc
        if not isinstance(parsed, dict):
            raise OllamaStructuredLlmError("Ollama structured output must be a JSON object")
        return parsed


def _request_body(
    *,
    model: str,
    system_prompt: str,
    input_payload: dict[str, Any],
    output_format: dict[str, Any] | str,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(input_payload, separators=(",", ":")),
            },
        ],
        "stream": False,
        "format": output_format,
        "options": {"temperature": 0},
    }


def _json_mode_system_prompt(system_prompt: str, output_schema: dict[str, Any]) -> str:
    schema = json.dumps(output_schema, separators=(",", ":"))
    return (
        f"{system_prompt}\n\n"
        "Ollama could not compile the response schema as a decoding grammar. "
        "Return exactly one JSON object that conforms to this JSON schema; do not add "
        f"markdown or commentary. JSON schema: {schema}"
    )


def _is_grammar_parse_error(response: httpx.Response) -> bool:
    return response.status_code == 400 and "failed to parse grammar" in response.text.lower()


def _safe_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return response.text.strip()[:500] or "unknown provider error"
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return str(payload["error"])[:500]
    return str(payload)[:500]
