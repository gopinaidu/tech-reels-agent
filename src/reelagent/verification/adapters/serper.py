from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, HttpUrl, SecretStr

from reelagent.intelligence.ports import StructuredLlmClient
from reelagent.verification.adapters.search import VerificationSearchHit
from reelagent.verification.trust import AuthoritativeDomain, domains_for_query, is_trusted_url

_SERPER_SEARCH_URL = "https://google.serper.dev/search"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_.+-]*")
_MAX_PAGE_TEXT_CHARS = 100_000
_MAX_EVIDENCE_SUMMARY_CHARS = 2_000
_MAX_TOKEN_OCCURRENCES = 5
_MAX_SEARCH_TERMS = 8
_MAX_RANKING_CANDIDATES = 10
_SEARCH_STOP_WORDS = frozenset(
    {
        "and",
        "are",
        "can",
        "does",
        "for",
        "from",
        "has",
        "have",
        "into",
        "its",
        "that",
        "the",
        "their",
        "this",
        "through",
        "with",
        "supports",
        "support",
        "using",
        "used",
    }
)

_QUERY_PROMPT = """Create one concise web research query for verifying a technical claim.
Keep the technology/product name and distinctive technical terms.
Prefer terms likely to surface official technical documentation.
Do not use search operators such as site:, OR, quotes, or minus filters.
Return only the schema fields requested.
"""

_RANKING_PROMPT = """Rank already-trusted official search candidates for one factual claim.
Select the candidates most likely to contain direct technical evidence for the claim.
Use only candidate title, snippet, and URL relevance; do not decide whether the claim is true.
Prefer specific reference or concept pages over generic documentation home pages.
Return selected candidate indices in strongest-first order.
"""


class _ResearchQuery(BaseModel, frozen=True):
    research_query: str = Field(min_length=3, max_length=250)


class _CandidateRanking(BaseModel, frozen=True):
    selected_indices: list[int] = Field(min_length=1, max_length=5)


class SerperVerificationSearchError(RuntimeError):
    """Raised when Serper search fails unexpectedly."""


class SerperVerificationSearchClient:
    """Find trusted evidence with Serper, optionally assisted by a structured LLM."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        llm_client: StructuredLlmClient | None = None,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._llm_client = llm_client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    async def search(self, query: str, *, limit: int) -> tuple[VerificationSearchHit, ...]:
        if limit < 1 or limit > 10:
            raise ValueError("limit must be between 1 and 10")

        domains = domains_for_query(query)
        if not domains:
            return ()

        trusted_hosts = frozenset(host for domain in domains for host in domain.hosts)
        source_kinds = {
            host: domain.source_kind
            for domain in domains
            for host in domain.hosts
        }
        fallback_query = _build_search_query(query, domains)
        search_query = await self._generate_research_query(query, fallback_query)
        headers = {
            "X-API-KEY": self._api_key.get_secret_value(),
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            results = await _search_serper(client, headers, search_query)
            candidates = _trusted_candidates(results, trusted_hosts)

            if not candidates and search_query != fallback_query:
                fallback_results = await _search_serper(client, headers, fallback_query)
                candidates = _trusted_candidates(fallback_results, trusted_hosts)

            if not candidates:
                return ()

            ranked = await self._rank_candidates(query, candidates, limit)

            hits: list[VerificationSearchHit] = []
            tokens = _tokens(query)
            for item in ranked[:limit]:
                url = item["link"]
                title = item["title"]
                search_snippet = item.get("snippet", "").strip()
                page_text = await _fetch_page_text(client, url)
                page_excerpt = _relevant_excerpt(page_text, tokens) if page_text else ""
                snippet = _combine_evidence_text(search_snippet, page_excerpt)
                if not snippet:
                    continue

                host = (urlparse(url).hostname or "").lower()
                hits.append(
                    VerificationSearchHit(
                        title=title.strip()[:300],
                        url=HttpUrl(url),
                        snippet=snippet,
                        source_kind=source_kinds[host],
                    )
                )

        return tuple(hits)

    async def _generate_research_query(self, claim: str, fallback: str) -> str:
        if self._llm_client is None:
            return fallback
        try:
            raw = await self._llm_client.generate_json(
                system_prompt=_QUERY_PROMPT,
                input_payload={"claim": claim, "fallback_query": fallback},
                output_schema=_ResearchQuery.model_json_schema(),
            )
            generated = _ResearchQuery.model_validate(raw).research_query.strip()
        except Exception:
            return fallback
        return generated if not _contains_search_operator(generated) else fallback

    async def _rank_candidates(
        self,
        claim: str,
        candidates: list[dict[str, str]],
        limit: int,
    ) -> list[dict[str, str]]:
        if self._llm_client is None or len(candidates) <= 1:
            return candidates
        payload_candidates = [
            {
                "index": index,
                "title": item["title"],
                "url": item["link"],
                "snippet": item.get("snippet", "")[:500],
            }
            for index, item in enumerate(candidates)
        ]
        try:
            raw = await self._llm_client.generate_json(
                system_prompt=_RANKING_PROMPT,
                input_payload={
                    "claim": claim,
                    "max_results": limit,
                    "candidates": payload_candidates,
                },
                output_schema=_CandidateRanking.model_json_schema(),
            )
            ranking = _CandidateRanking.model_validate(raw).selected_indices
        except Exception:
            return candidates

        ordered: list[dict[str, str]] = []
        seen: set[int] = set()
        for index in ranking:
            if index in seen or index < 0 or index >= len(candidates):
                continue
            seen.add(index)
            ordered.append(candidates[index])
        for index, item in enumerate(candidates):
            if index not in seen:
                ordered.append(item)
        return ordered


async def _search_serper(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    search_query: str,
) -> list[Any]:
    payload = {"q": search_query, "num": _MAX_RANKING_CANDIDATES}
    try:
        response = await client.post(
            _SERPER_SEARCH_URL,
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as exc:
        detail = _response_detail(exc.response)
        raise SerperVerificationSearchError(
            f"Serper search returned HTTP {exc.response.status_code}: {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise SerperVerificationSearchError(
            f"Serper search transport failed: {type(exc).__name__}"
        ) from exc
    except ValueError as exc:
        raise SerperVerificationSearchError("Serper search returned invalid JSON") from exc

    results = body.get("organic", [])
    return results if isinstance(results, list) else []


def _trusted_candidates(
    results: list[Any],
    trusted_hosts: frozenset[str],
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        url = item.get("link")
        title = item.get("title")
        snippet = item.get("snippet")
        if not isinstance(url, str) or not isinstance(title, str) or not title.strip():
            continue
        if url in seen or not is_trusted_url(url, trusted_hosts):
            continue
        seen.add(url)
        candidates.append(
            {
                "link": url,
                "title": title,
                "snippet": snippet if isinstance(snippet, str) else "",
            }
        )
    return candidates


def _build_search_query(
    query: str,
    domains: tuple[AuthoritativeDomain, ...],
) -> str:
    terms: list[str] = []
    seen: set[str] = set()

    for domain in domains:
        _append_search_term(domain.name, terms, seen)

    for token in _WORD_RE.findall(query.lower().replace("-", " ")):
        if len(token) < 3 or token in _SEARCH_STOP_WORDS or token in seen:
            continue
        _append_search_term(token, terms, seen)
        if len(terms) >= _MAX_SEARCH_TERMS:
            break

    _append_search_term("documentation", terms, seen)
    return " ".join(terms)


def _append_search_term(term: str, terms: list[str], seen: set[str]) -> None:
    normalized = term.strip().lower()
    if not normalized or normalized in seen:
        return
    seen.add(normalized)
    terms.append(term.strip())


def _contains_search_operator(query: str) -> bool:
    lowered = query.lower()
    return "site:" in lowered or " or " in lowered or '"' in query


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:300] or "no response body"

    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()[:300]
    return response.text.strip()[:300] or "no response body"


def _combine_evidence_text(search_snippet: str, page_excerpt: str) -> str:
    search_snippet = _WS_RE.sub(" ", search_snippet).strip()
    page_excerpt = _WS_RE.sub(" ", page_excerpt).strip()

    if search_snippet and page_excerpt:
        if page_excerpt in search_snippet or search_snippet in page_excerpt:
            combined = search_snippet if len(search_snippet) >= len(page_excerpt) else page_excerpt
        else:
            combined = f"Search snippet: {search_snippet}\nPage excerpt: {page_excerpt}"
    else:
        combined = search_snippet or page_excerpt
    return combined[:_MAX_EVIDENCE_SUMMARY_CHARS]


def _tokens(text: str) -> tuple[str, ...]:
    seen: set[str] = set()
    tokens: list[str] = []
    for token in _WORD_RE.findall(text.lower()):
        if len(token) < 3 or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tuple(tokens)


async def _fetch_page_text(client: httpx.AsyncClient, url: str) -> str:
    try:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return ""
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "text/plain" not in content_type:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", response.text))
    normalized = _WS_RE.sub(" ", text).strip()
    return normalized[:_MAX_PAGE_TEXT_CHARS]


def _relevant_excerpt(text: str, tokens: tuple[str, ...]) -> str:
    if len(text) <= _MAX_EVIDENCE_SUMMARY_CHARS:
        return text
    if not tokens:
        return text[:_MAX_EVIDENCE_SUMMARY_CHARS]

    lowered = text.lower()
    candidates: list[tuple[int, int]] = []
    for token in tokens:
        search_from = 0
        for _ in range(_MAX_TOKEN_OCCURRENCES):
            position = lowered.find(token, search_from)
            if position < 0:
                break
            start = max(0, position - 500)
            end = min(len(text), start + _MAX_EVIDENCE_SUMMARY_CHARS)
            window = lowered[start:end]
            score = sum(1 for query_token in tokens if query_token in window)
            candidates.append((score, start))
            search_from = position + len(token)

    if not candidates:
        return text[:_MAX_EVIDENCE_SUMMARY_CHARS]

    _, best_start = max(candidates, key=lambda item: (item[0], item[1]))
    best_end = min(len(text), best_start + _MAX_EVIDENCE_SUMMARY_CHARS)
    best_start = max(0, best_end - _MAX_EVIDENCE_SUMMARY_CHARS)
    return text[best_start:best_end]
