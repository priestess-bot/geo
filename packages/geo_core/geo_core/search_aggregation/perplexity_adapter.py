"""Perplexity adapter for search aggregation via OpenRouter.

Uses ``httpx`` to call OpenRouter's chat completions endpoint with a Perplexity
Sonar model. Perplexity models have built-in web search, so unlike the OpenAI
web_search tool path, no ``tools`` parameter is required.

Important naming note: this is Perplexity hosted through OpenRouter. It uses the
same OpenRouter API key and endpoint as ``OpenRouterWebSearchProvider``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from geo_core.search_aggregation.domain import (
    AiOverviewBlock,
    AiOverviewQuery,
    AiOverviewReference,
    AiOverviewResult,
    SearchAggregationError,
)
from geo_core.search_aggregation.ports import SearchProvider


class PerplexityOpenRouterProvider(SearchProvider):
    """Fetch AI answers with web citations through Perplexity models on OpenRouter."""

    _BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        model: str = "perplexity/sonar",
        http_referer: str = "https://geo.local",
        app_title: str = "GEO Search Demo",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key:
            raise SearchAggregationError("OpenRouter API key is required.")
        self._api_key = api_key
        self._model = model
        self._http_referer = http_referer
        self._app_title = app_title
        self._timeout = timeout_seconds

    async def fetch_ai_overview(self, query: AiOverviewQuery) -> AiOverviewResult:
        """Call OpenRouter with a Perplexity model and normalize the answer."""
        payload = await self._fetch_openrouter(query)
        answer_text = _extract_answer_text(payload)
        citations = _extract_citations(payload)

        blocks: list[AiOverviewBlock] = []
        if answer_text:
            blocks.append(AiOverviewBlock(type="paragraph", text=answer_text))

        return AiOverviewResult(
            query=query.text,
            blocks=blocks,
            references=citations,
            raw_response=payload,
        )

    async def fetch_raw_search(self, query: AiOverviewQuery) -> dict[str, Any]:
        """Return the raw OpenRouter/Perplexity response for debugging."""
        return await self._fetch_openrouter(query)

    async def _fetch_openrouter(self, query: AiOverviewQuery) -> dict[str, Any]:
        """Call OpenRouter chat completions and return the raw JSON response."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self._http_referer,
            "X-Title": self._app_title,
        }
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": query.text}],
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._BASE_URL, headers=headers, json=body)
        except httpx.NetworkError as exc:
            raise SearchAggregationError(f"Network error contacting OpenRouter: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise SearchAggregationError(f"OpenRouter request timed out: {exc}") from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SearchAggregationError(
                f"OpenRouter returned HTTP {exc.response.status_code}"
            ) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise SearchAggregationError("OpenRouter returned invalid JSON.") from exc


def _extract_answer_text(payload: dict[str, Any]) -> str | None:
    """Return ``choices[0].message.content`` if present."""
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, str):
        return None
    return content.strip() or None


def _extract_annotations(payload: dict[str, Any]) -> list[Any]:
    """Return ``choices[0].message.annotations`` if it is a list."""
    if not isinstance(payload, dict):
        return []
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return []
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return []
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return []
    annotations = message.get("annotations")
    return annotations if isinstance(annotations, list) else []


def _extract_citations(payload: dict[str, Any]) -> list[AiOverviewReference]:
    """Return deduplicated references from Perplexity/OpenRouter annotations.

    Perplexity models hosted on OpenRouter currently return citations through
    ``choices[0].message.annotations`` with ``type: "url_citation"``, the same
    shape used by the OpenAI web_search tool path. The native Perplexity API
    also supports a top-level ``citations`` array of URL strings, so both
    sources are normalized here.
    """
    if not isinstance(payload, dict):
        return []

    references: list[AiOverviewReference] = []
    seen_urls: set[str] = set()

    # OpenRouter-hosted Perplexity returns citations as message annotations.
    annotations = _extract_annotations(payload)
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        if annotation.get("type") != "url_citation":
            continue
        citation = annotation.get("url_citation")
        if not isinstance(citation, dict):
            continue
        url = _as_optional_str(citation.get("url"))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        references.append(
            AiOverviewReference(
                title=_as_optional_str(citation.get("title")),
                url=url,
                source=_source_from_url(url),
            )
        )

    # Native Perplexity API may return a flat citations array.
    citations = payload.get("citations")
    if isinstance(citations, list):
        for citation in citations:
            if not isinstance(citation, str):
                continue
            url = citation.strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            references.append(
                AiOverviewReference(
                    title=None,
                    url=url,
                    source=_source_from_url(url),
                )
            )

    return references


def _source_from_url(url: str) -> str | None:
    """Return the hostname of ``url`` as the source label."""
    try:
        hostname = urlparse(url).hostname
        if hostname:
            return hostname.replace("www.", "")
    except ValueError:
        pass
    return None


def _as_optional_str(value: Any) -> str | None:
    """Coerce a JSON value to ``str`` or ``None``."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)
