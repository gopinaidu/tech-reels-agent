import asyncio
from typing import Any

import httpx
from pydantic import SecretStr

from reelagent.verification.adapters import SerperVerificationSearchClient


class _StructuredClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses

    async def generate_json(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        output_schema: dict[str, Any],
    ) -> dict[str, Any]:
        return self.responses.pop(0)


def test_serper_retries_fallback_query_when_generated_query_has_no_trusted_results() -> None:
    llm = _StructuredClient(
        [{"research_query": "Apache Kafka message ordering guarantees within partition documentation"}]
    )
    post_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            payload = request.read().decode()
            post_queries.append(payload)
            if len(post_queries) == 1:
                return httpx.Response(
                    200,
                    json={
                        "organic": [
                            {
                                "title": "Kafka ordering guarantees",
                                "link": "https://stackoverflow.com/questions/46127716/kafka-ordering-guarantees",
                                "snippet": "Community discussion.",
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "organic": [
                        *[
                            {
                                "title": f"Untrusted result {index}",
                                "link": f"https://example{index}.com/kafka",
                                "snippet": "Untrusted result.",
                            }
                            for index in range(7)
                        ],
                        {
                            "title": "Introduction | Apache Kafka",
                            "link": "https://kafka.apache.org/documentation/",
                            "snippet": (
                                "Kafka guarantees that any consumer of a given topic-partition "
                                "will always read that partition's events in exactly the same order."
                            ),
                        },
                    ]
                },
            )
        if str(request.url) == "https://kafka.apache.org/documentation/":
            return httpx.Response(503)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = SerperVerificationSearchClient(
        api_key=SecretStr("serper-secret"),
        llm_client=llm,
        transport=httpx.MockTransport(handler),
    )

    hits = asyncio.run(
        client.search("Kafka preserves message ordering within a partition.", limit=5)
    )

    assert len(post_queries) == 2
    assert len(hits) == 1
    assert str(hits[0].url) == "https://kafka.apache.org/documentation/"
    assert "same order" in hits[0].snippet


def test_serper_does_not_retry_when_generated_query_has_trusted_result() -> None:
    llm = _StructuredClient(
        [{"research_query": "Apache Kafka partition ordering documentation"}]
    )
    post_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        if request.method == "POST":
            post_count += 1
            return httpx.Response(
                200,
                json={
                    "organic": [
                        {
                            "title": "Introduction | Apache Kafka",
                            "link": "https://kafka.apache.org/documentation/",
                            "snippet": "Kafka preserves ordering within a topic-partition.",
                        }
                    ]
                },
            )
        return httpx.Response(503)

    client = SerperVerificationSearchClient(
        api_key=SecretStr("serper-secret"),
        llm_client=llm,
        transport=httpx.MockTransport(handler),
    )

    hits = asyncio.run(
        client.search("Kafka preserves message ordering within a partition.", limit=5)
    )

    assert post_count == 1
    assert len(hits) == 1
