"""Pure domain models for search aggregation.

These dataclasses are intentionally free of FastAPI, HTTP client, and
environment dependencies so they can be used from any runtime or test harness.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class SearchAggregationError(RuntimeError):
    """Raised when a search aggregation operation cannot be completed."""


@dataclass(frozen=True)
class AiOverviewQuery:
    """A request to retrieve an AI Overview for a search query."""

    text: str
    locale: str = "en-US"
    region: str = "US"
    location: str | None = None
    google_domain: str | None = None


@dataclass(frozen=True)
class AiOverviewListItem:
    """A single list entry within an AI Overview block."""

    text: str
    inline_references: list[AiOverviewInlineReference] = field(default_factory=list)


@dataclass(frozen=True)
class AiOverviewBlock:
    """A single block of content extracted from an AI Overview."""

    type: str
    text: str | None = None
    items: list[AiOverviewListItem] | None = None
    inline_references: list[AiOverviewInlineReference] = field(default_factory=list)


@dataclass(frozen=True)
class AiOverviewReference:
    """A source reference cited by an AI Overview."""

    title: str | None = None
    url: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class AiOverviewInlineReference:
    """An inline source badge attached to a specific span of overview text."""

    reference: AiOverviewReference
    highlighted_text: str | None = None


@dataclass(frozen=True)
class AiOverviewResult:
    """Structured result of an AI Overview fetch, including the raw provider response."""

    query: str
    blocks: list[AiOverviewBlock] = field(default_factory=list)
    references: list[AiOverviewReference] = field(default_factory=list)
    raw_response: dict | None = None
