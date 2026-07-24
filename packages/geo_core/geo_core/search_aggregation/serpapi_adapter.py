"""SerpAPI-backed implementation of ``SearchProvider``.

Uses ``httpx`` (already a project dependency) to call SerpAPI's Google Search
endpoint and normalizes the ``ai_overview`` payload into domain objects.
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


class SerpApiSearchProvider(SearchProvider):
    """Fetch Google AI Overviews through SerpAPI."""

    _BASE_URL = "https://serpapi.com/search.json"

    def __init__(self, api_key: str, timeout_seconds: float = 30.0) -> None:
        if not api_key:
            raise SearchAggregationError("SerpAPI key is required.")
        self._api_key = api_key
        self._timeout = timeout_seconds

    async def fetch_ai_overview(self, query: AiOverviewQuery) -> AiOverviewResult:
        """Call SerpAPI and normalize the AI Overview portion of the response."""
        payload = await self._fetch_serpapi(query)
        overview_payload = _find_overview_payload(payload)

        # Some locales/queries return only a page_token in the first response;
        # a second call to the google_ai_overview engine resolves the content.
        if overview_payload is not None and _is_page_token_only(overview_payload):
            page_token = str(overview_payload.get("page_token"))
            resolved = await self._fetch_ai_overview_page(page_token)
            overview_payload = _find_overview_payload(resolved) or overview_payload

        blocks, references = _extract_blocks_and_references(overview_payload)
        return AiOverviewResult(
            query=query.text,
            blocks=blocks,
            references=references,
            raw_response=payload,
        )

    async def fetch_raw_search(self, query: AiOverviewQuery) -> dict[str, Any]:
        """Return the raw SerpAPI response for debugging."""
        return await self._fetch_serpapi(query)

    async def _fetch_serpapi(self, query: AiOverviewQuery) -> dict[str, Any]:
        """Call SerpAPI and return the raw JSON response."""
        # SerpAPI expects two-letter language/region codes (e.g. hl=en, gl=us).
        language = _serpapi_language(query.locale)
        region = _serpapi_region(query.region)
        params: dict[str, Any] = {
            "engine": "google",
            "q": query.text,
            "api_key": self._api_key,
            "hl": language,
            "gl": region,
        }
        if query.location:
            params["location"] = query.location
        if query.google_domain:
            params["google_domain"] = query.google_domain
        return await self._fetch_serpapi_url(self._BASE_URL, params)

    async def _fetch_ai_overview_page(self, page_token: str) -> dict[str, Any]:
        """Resolve a Google AI Overview page token through SerpAPI."""
        params = {
            "engine": "google_ai_overview",
            "page_token": page_token,
            "api_key": self._api_key,
        }
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


def _find_overview_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return the AI Overview-ish payload, preferring ``ai_overview``.

    Falls back to ``answer_box`` when SerpAPI places the result there.
    """
    if not isinstance(payload, dict):
        return None
    if "ai_overview" in payload:
        overview = payload["ai_overview"]
        if isinstance(overview, dict):
            return overview
    if "answer_box" in payload:
        answer_box = payload["answer_box"]
        if isinstance(answer_box, dict):
            return answer_box
    return None


def _is_page_token_only(overview: dict[str, Any] | None) -> bool:
    """Return True when the overview payload is just a page_token placeholder."""
    if not isinstance(overview, dict):
        return False
    keys = set(overview.keys())
    return "page_token" in overview and keys <= {"page_token", "serpapi_link"}


def _extract_blocks_and_references(
    overview: dict[str, Any] | None,
) -> tuple[list[AiOverviewBlock], list[AiOverviewReference]]:
    """Normalize the overview payload into domain blocks and references."""
    blocks: list[AiOverviewBlock] = []
    references: list[AiOverviewReference] = []
    if not isinstance(overview, dict):
        return blocks, references

    # Extract the top-level references first so blocks can resolve inline indexes.
    raw_references = overview.get("references")
    if isinstance(raw_references, list):
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

    text_blocks = overview.get("text_blocks")
    if isinstance(text_blocks, list):
        for item in text_blocks:
            if not isinstance(item, dict):
                continue
            block_type = str(item.get("type", "paragraph")).lower()
            text = _overview_text(item)
            items = _overview_list_items(item, references)
            inline_refs = _extract_inline_references(item, references)
            blocks.append(
                AiOverviewBlock(
                    type=block_type,
                    text=text,
                    items=items,
                    inline_references=inline_refs,
                )
            )
    elif "answer" in overview or "snippet" in overview:
        # Fallback for answer_box-style payloads.
        answer = _as_optional_str(overview.get("answer"))
        snippet = _as_optional_str(overview.get("snippet"))
        inline_refs = _extract_inline_references(overview, references)
        if answer:
            blocks.append(
                AiOverviewBlock(type="paragraph", text=answer, inline_references=inline_refs)
            )
        elif snippet:
            blocks.append(
                AiOverviewBlock(type="paragraph", text=snippet, inline_references=inline_refs)
            )
        list_items = _overview_list_items(overview, references)
        if list_items:
            blocks.append(AiOverviewBlock(type="list", items=list_items))

    return blocks, references


def _overview_text(item: dict[str, Any]) -> str | None:
    """Extract display text from an overview block, preferring ``snippet``."""
    return _as_optional_str(item.get("snippet") or item.get("text"))


def _overview_list_items(
    item: dict[str, Any],
    references: list[AiOverviewReference],
) -> list[AiOverviewListItem] | None:
    """Extract list items from an overview block, preserving per-item inline refs.

    SerpAPI represents list items either as plain strings or as objects with a
    ``snippet`` field and their own ``snippet_links`` / ``reference_indexes``.
    """
    raw_list = item.get("list")
    if not isinstance(raw_list, list):
        plain_items = _as_optional_str_list(item.get("items"))
        if not plain_items:
            return None
        return [AiOverviewListItem(text=text) for text in plain_items]

    items: list[AiOverviewListItem] = []
    for entry in raw_list:
        if isinstance(entry, dict):
            text = _overview_text(entry)
            if text:
                inline_refs = _extract_inline_references(entry, references)
                items.append(AiOverviewListItem(text=text, inline_references=inline_refs))
        elif entry is not None:
            text = str(entry).strip()
            if text:
                items.append(AiOverviewListItem(text=text))
    return items or None


def _extract_inline_references(
    item: dict[str, Any],
    references: list[AiOverviewReference],
) -> list[AiOverviewInlineReference]:
    """Return the inline source badges for a single overview block.

    SerpAPI provides ``snippet_links`` directly and/or ``reference_indexes`` that
    point into the top-level ``references`` array. ``snippet_highlighted_words``
    tells us which span of text each badge belongs to.
    """
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
            # Skip snippet_links that duplicate a reference already resolved via
            # reference_indexes to avoid two badges for the same source.
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


def _as_optional_str_list(value: Any) -> list[str] | None:
    """Coerce a JSON list-of-strings value or ``None``."""
    if not isinstance(value, list):
        return None
    items = [str(item).strip() for item in value if item is not None]
    return items or None


def _serpapi_language(locale: str) -> str:
    """Return the two-letter language code SerpAPI expects for ``hl``."""
    normalized = locale.strip().lower().replace("_", "-")
    return normalized.split("-")[0] if normalized else "en"


def _serpapi_region(region: str) -> str:
    """Return the two-letter region code SerpAPI expects for ``gl``."""
    normalized = region.strip().lower()
    return normalized.split("-")[0] if normalized else "us"
