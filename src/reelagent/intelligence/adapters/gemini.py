from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from pydantic import SecretStr


class GeminiStructuredLlmError(RuntimeError):
    """Raised when Gemini cannot return usable structured JSON."""


class GeminiStructuredLlmClient:
    """Call Gemini generateContent with JSON-schema constrained output."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    async def generate_json(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        output_schema: dict[str, Any],
    ) -> dict[str, Any]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent"
        )
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": json.dumps(input_payload, separators=(",", ":"))}
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": output_schema,
            },
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key.get_secret_value(),
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await _post_with_one_retry(client, url=url, headers=headers, body=body)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            response = exc.response
            detail = _safe_provider_error(response)
            raise GeminiStructuredLlmError(
                f"Gemini structured generation failed with HTTP {response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise GeminiStructuredLlmError(
                f"Gemini structured generation failed with network error: {exc.__class__.__name__}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise GeminiStructuredLlmError("Gemini structured generation returned an invalid response") from exc

        text = _extract_text(payload)
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise GeminiStructuredLlmError("Gemini returned invalid JSON output") from exc
        if not isinstance(parsed, dict):
            raise GeminiStructuredLlmError("Gemini structured output must be a JSON object")
        return parsed


async def _post_with_one_retry(
    client: httpx.AsyncClient,
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> httpx.Response:
    response = await client.post(url, headers=headers, json=body)
    if response.status_code == 429 or response.status_code >= 500:
        await asyncio.sleep(0.5)
        response = await client.post(url, headers=headers, json=body)
    return response


def _safe_provider_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:500] if text else "no provider error details"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()[:500]
    return "no provider error details"


def _extract_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise GeminiStructuredLlmError("Gemini response must be a JSON object")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise GeminiStructuredLlmError("Gemini response is missing candidates")
    first = candidates[0]
    if not isinstance(first, dict):
        raise GeminiStructuredLlmError("Gemini candidate is invalid")
    content = first.get("content")
    if not isinstance(content, dict) or not isinstance(content.get("parts"), list):
        raise GeminiStructuredLlmError("Gemini response is missing content parts")
    for part in content["parts"]:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            return str(part["text"])
    raise GeminiStructuredLlmError("Gemini response is missing output text")
