"""In-memory mock provider for search aggregation.

Useful for local development and deterministic search-aggregation tests.
"""

from __future__ import annotations

from geo_core.search_aggregation.domain import (
    AiOverviewBlock,
    AiOverviewInlineReference,
    AiOverviewListItem,
    AiOverviewQuery,
    AiOverviewReference,
    AiOverviewResult,
)
from geo_core.search_aggregation.ports import SearchProvider


class MockSearchProvider(SearchProvider):
    """Returns a deterministic, fixed AI Overview for every query."""

    async def fetch_raw_search(self, query: AiOverviewQuery) -> dict[str, object]:
        """Return a mock raw search response for debugging."""
        return {
            "mock": True,
            "query": query.text,
            "locale": query.locale,
            "region": query.region,
            "search_information": {"total_results": 1},
            "organic_results": [
                {
                    "title": f"Mock result for {query.text}",
                    "link": "https://example.com/mock",
                    "snippet": "This is a mock organic result used for debugging.",
                }
            ],
        }

    async def fetch_ai_overview(self, query: AiOverviewQuery) -> AiOverviewResult:
        """Return a mock overview seeded with the query text."""
        return AiOverviewResult(
            query=query.text,
            blocks=[
                AiOverviewBlock(
                    type="paragraph",
                    text=f"This is a mock AI Overview for '{query.text}'.",
                ),
                AiOverviewBlock(
                    type="list",
                    items=[
                        AiOverviewListItem(
                            text="Mock overview point one",
                            inline_references=[
                                AiOverviewInlineReference(
                                    reference=AiOverviewReference(
                                        title="Mock Reference",
                                        url="https://example.com/mock-reference",
                                        source="example.com",
                                    )
                                )
                            ],
                        ),
                        AiOverviewListItem(text="Mock overview point two"),
                    ],
                ),
            ],
            references=[
                AiOverviewReference(
                    title="Mock Reference",
                    url="https://example.com/mock-reference",
                    source="example.com",
                ),
            ],
            raw_response={
                "mock": True,
                "query": query.text,
                "locale": query.locale,
                "region": query.region,
            },
        )
