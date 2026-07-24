"""Transport contracts for the search aggregation endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SearchAggregationStrictModel(BaseModel):
    """Base model for public API contracts that reject unknown fields."""

    model_config = ConfigDict(extra="forbid")


class AiOverviewListItemContract(SearchAggregationStrictModel):
    """A single list entry within an AI Overview block."""

    text: str
    inline_references: list[AiOverviewReferenceContract] = Field(default_factory=list)


class AiOverviewBlockContract(SearchAggregationStrictModel):
    """A single content block from a Google AI Overview."""

    type: str
    text: str | None = None
    items: list[AiOverviewListItemContract] | None = None
    inline_references: list[AiOverviewReferenceContract] = Field(default_factory=list)


class AiOverviewReferenceContract(SearchAggregationStrictModel):
    """A source reference cited by a Google AI Overview."""

    title: str | None = None
    url: str | None = None
    source: str | None = None
    highlighted_text: str | None = None


class GoogleAiOverviewRequest(SearchAggregationStrictModel):
    """Request a structured Google AI Overview for a search query."""

    query: str = Field(min_length=1, max_length=500)
    location: str | None = Field(
        default=None,
        description="Full location string for SerpAPI (e.g. 'London, England, United Kingdom').",
    )
    gl: str | None = Field(
        default=None,
        description="Two-letter country code for SerpAPI gl parameter (e.g. 'us', 'uk').",
    )
    hl: str | None = Field(
        default=None,
        description="Language code for SerpAPI hl parameter (e.g. 'en', 'zh-cn').",
    )
    google_domain: str | None = Field(
        default=None,
        description="Google domain for SerpAPI (e.g. 'google.com', 'google.co.uk').",
    )


class GoogleAiOverviewResponse(SearchAggregationStrictModel):
    """Structured Google AI Overview response."""

    query: str
    blocks: list[AiOverviewBlockContract]
    references: list[AiOverviewReferenceContract]
    has_overview: bool
