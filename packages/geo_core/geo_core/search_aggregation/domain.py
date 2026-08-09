"""Pure domain models for search aggregation.

These dataclasses are intentionally free of FastAPI, HTTP client, and
environment dependencies so they can be used from any runtime or test harness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SearchAggregationErrorCode(StrEnum):
    """Actionable failure classes shared by external search providers."""

    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    QUOTA = "quota"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_RESPONSE = "invalid_response"
    PROVIDER_ERROR = "provider_error"


class SearchAggregationError(RuntimeError):
    """Raised when a search aggregation operation cannot be completed.

    The message is deliberately safe for logs. Callers use ``code`` and
    ``retryable`` to decide whether a durable Attempt may be retried; provider
    response bodies and credentials never belong in this exception.
    """

    def __init__(
        self,
        message: str,
        *,
        code: SearchAggregationErrorCode = SearchAggregationErrorCode.PROVIDER_ERROR,
        retryable: bool = False,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = SearchAggregationErrorCode(code)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


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
