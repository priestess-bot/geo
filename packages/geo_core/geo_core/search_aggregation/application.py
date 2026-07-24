"""Application service that coordinates AI Overview retrieval."""

from __future__ import annotations

from typing import Any

from geo_core.search_aggregation.domain import AiOverviewQuery, AiOverviewResult
from geo_core.search_aggregation.ports import SearchProvider


class SearchAggregationService:
    """Thin orchestrator over a ``SearchProvider``.

    Keeps the HTTP/API surface decoupled from the chosen search provider.
    """

    def __init__(self, provider: SearchProvider) -> None:
        self._provider = provider

    async def get_google_ai_overview(self, query: AiOverviewQuery) -> AiOverviewResult:
        """Return the Google AI Overview for ``query``."""
        return await self._provider.fetch_ai_overview(query)

    async def get_google_raw_search(self, query: AiOverviewQuery) -> dict[str, Any]:
        """Return the raw provider search response for ``query``.

        Intended for debugging and validating what the provider returns.
        """
        return await self._provider.fetch_raw_search(query)
