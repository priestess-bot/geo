"""SerpAPI-backed Bing Copilot adapter.

Uses SerpAPI's ``engine=bing_copilot`` endpoint to fetch AI-generated answers
from Bing and normalizes them into the same domain model as Google AI Overview.
"""

from __future__ import annotations

from typing import Any

import httpx

from geo_core.search_aggregation.domain import (
    AiOverviewBlock,
    AiOverviewInlineReference,
    AiOverviewListItem,
    AiOverviewQuery,
    AiOverviewReference,
    AiOverviewResult,
    SearchAggregationError,
)
from geo_core.search_aggregation.ports import SearchProvider


class SerpApiBingCopilotProvider(SearchProvider):
    """Fetch Bing Copilot answers through SerpAPI."""

    _BASE_URL = "https://serpapi.com/search.json"

    def __init__(self, api_key: str, timeout_seconds: float = 30.0) -> None:
        if not api_key:
            raise SearchAggregationError("SerpAPI key is required.")
        self._api_key = api_key
        self._timeout = timeout_seconds

    async def fetch_ai_overview(self, query: AiOverviewQuery) -> AiOverviewResult:
        """Call SerpAPI Bing Copilot and normalize the response."""
        payload = await self._fetch_serpapi(query)
        blocks, references = _extract_bing_copilot_blocks_and_references(payload)
        return AiOverviewResult(
            query=query.text,
            blocks=blocks,
            references=references,
            raw_response=payload,
        )

    async def fetch_raw_search(self, query: AiOverviewQuery) -> dict[str, Any]:
        """Return the raw SerpAPI Bing Copilot response for debugging."""
        return await self._fetch_serpapi(query)

    async def _fetch_serpapi(self, query: AiOverviewQuery) -> dict[str, Any]:
        """Call SerpAPI Bing Copilot and return the raw JSON response."""
        params: dict[str, Any] = {
            "engine": "bing_copilot",
            "q": query.text,
            "api_key": self._api_key,
        }
        if query.location:
            params["location"] = query.location
        if query.region:
            params["cc"] = query.region.lower()
        if query.locale:
            params["setlang"] = _bing_language(query.locale)
        return await self._fetch_serpapi_url(self._BASE_URL, params)

    async def _fetch_serpapi_url(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a SerpAPI URL and return the raw JSON response."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params)
        except httpx.NetworkError as exc:
            raise SearchAggregationError(f"Network error contacting SerpAPI: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise SearchAggregationError(f"SerpAPI request timed out: {exc}") from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SearchAggregationError(
                f"SerpAPI returned HTTP {exc.response.status_code}"
            ) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise SearchAggregationError("SerpAPI returned invalid JSON.") from exc


def _extract_bing_copilot_blocks_and_references(
    payload: dict[str, Any],
) -> tuple[list[AiOverviewBlock], list[AiOverviewReference]]:
    """Normalize a Bing Copilot payload into domain blocks and references."""
    blocks: list[AiOverviewBlock] = []
    references = _extract_bing_references(payload.get("references"))

    header = _as_optional_str(payload.get("header"))
    if header:
        blocks.append(AiOverviewBlock(type="paragraph", text=header))

    text_blocks = payload.get("text_blocks")
    if isinstance(text_blocks, list):
        for item in text_blocks:
            if not isinstance(item, dict):
                continue
            block = _bing_text_block_to_domain(item, references)
            if block:
                blocks.append(block)

    return blocks, references


def _extract_bing_references(raw_references: Any) -> list[AiOverviewReference]:
    """Normalize Bing Copilot references into domain references."""
    references: list[AiOverviewReference] = []
    if not isinstance(raw_references, list):
        return references
    for ref in raw_references:
        if not isinstance(ref, dict):
            continue
        references.append(
            AiOverviewReference(
                title=_as_optional_str(ref.get("title")),
                url=_as_optional_str(ref.get("link") or ref.get("url")),
                source=_as_optional_str(ref.get("source") or ref.get("displayed_link")),
            )
        )
    return references


def _bing_text_block_to_domain(
    item: dict[str, Any], references: list[AiOverviewReference]
) -> AiOverviewBlock | None:
    """Convert a single Bing Copilot text block to a domain block."""
    block_type = str(item.get("type", "paragraph")).lower()
    text = _as_optional_str(item.get("snippet") or item.get("text"))
    inline_refs = _extract_bing_inline_references(item, references)

    if block_type == "heading":
        if text:
            return AiOverviewBlock(type="heading", text=text, inline_references=inline_refs)
        return None

    if block_type == "list":
        items = _extract_bing_list_items(item, references)
        if items:
            return AiOverviewBlock(type="list", items=items, inline_references=inline_refs)
        if text:
            return AiOverviewBlock(type="paragraph", text=text, inline_references=inline_refs)
        return None

    if block_type == "table":
        # The current contract does not model table data; render the snippet as a paragraph.
        if text:
            return AiOverviewBlock(type="paragraph", text=text, inline_references=inline_refs)
        return None

    # Default to paragraph.
    if text:
        return AiOverviewBlock(type="paragraph", text=text, inline_references=inline_refs)
    return None


def _extract_bing_list_items(
    item: dict[str, Any], references: list[AiOverviewReference]
) -> list[AiOverviewListItem] | None:
    """Extract list items from a Bing Copilot list block."""
    raw_list = item.get("list")
    if not isinstance(raw_list, list):
        return None

    items: list[AiOverviewListItem] = []
    for entry in raw_list:
        if not isinstance(entry, dict):
            continue
        text = _as_optional_str(entry.get("snippet") or entry.get("text"))
        if not text:
            continue
        inline_refs = _extract_bing_inline_references(entry, references)
        items.append(AiOverviewListItem(text=text, inline_references=inline_refs))

    return items or None


def _extract_bing_inline_references(
    item: dict[str, Any], references: list[AiOverviewReference]
) -> list[AiOverviewInlineReference]:
    """Return inline source badges for a Bing Copilot block."""
    inline: list[AiOverviewInlineReference] = []
    seen: set[int] = set()

    highlighted_words = item.get("snippet_highlighted_words") or []
    if not isinstance(highlighted_words, list):
        highlighted_words = []

    reference_indexes = item.get("reference_indexes")
    if isinstance(reference_indexes, list):
        for offset, idx in enumerate(reference_indexes):
            try:
                index = int(idx)
            except (TypeError, ValueError):
                continue
            if index in seen or index < 0 or index >= len(references):
                continue
            seen.add(index)
            highlighted = (
                _as_optional_str(highlighted_words[offset])
                if offset < len(highlighted_words)
                else None
            )
            inline.append(
                AiOverviewInlineReference(
                    reference=references[index],
                    highlighted_text=highlighted,
                )
            )

    snippet_links = item.get("snippet_links")
    if isinstance(snippet_links, list):
        for link in snippet_links:
            if not isinstance(link, dict):
                continue
            url = _as_optional_str(link.get("link") or link.get("url"))
            if not url:
                continue
            if any(ref.reference.url == url for ref in inline):
                continue
            inline.append(
                AiOverviewInlineReference(
                    reference=AiOverviewReference(
                        title=_as_optional_str(link.get("title")),
                        url=url,
                        source=_as_optional_str(link.get("source") or link.get("displayed_link")),
                    ),
                    highlighted_text=_as_optional_str(link.get("highlighted_text")),
                )
            )

    return inline


def _as_optional_str(value: Any) -> str | None:
    """Coerce a JSON value to ``str`` or ``None``."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _bing_language(locale: str) -> str:
    """Return the language code SerpAPI Bing expects for ``setlang``."""
    normalized = locale.strip().lower().replace("_", "-")
    return normalized.split("-")[0] if normalized else "en"
