"""Ports (protocols) for search aggregation providers."""

from __future__ import annotations

from typing import Any, Protocol

from geo_core.search_aggregation.domain import AiOverviewQuery, AiOverviewResult


class SearchProvider(Protocol):
    """Abstract provider capable of fetching search data for a query."""

    async def fetch_ai_overview(self, query: AiOverviewQuery) -> AiOverviewResult:
        """Fetch the AI Overview for ``query``.

        Raises:
            SearchAggregationError: when the provider cannot complete the request.
        """

    async def fetch_raw_search(self, query: AiOverviewQuery) -> dict[str, Any]:
        """Fetch the raw provider response for ``query``.

        This is intended for debugging and validation, not for end-user display.

        Raises:
            SearchAggregationError: when the provider cannot complete the request.
        """
