"""Stable transport contracts for monitoring and customer GEO reporting."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


PlatformValue = Literal[
    "chatgpt_search",
    "google_ai_overviews",
    "google_search",
    "perplexity",
    "gemini",
    "other",
]
WindowValue = Literal["baseline", "t28", "t56", "t84", "ad_hoc"]


class CreateMonitoringProtocolRequest(StrictModel):
    campaign_id: UUID
    market_profile_id: UUID
    name: str = Field(min_length=1, max_length=200)
    platform: PlatformValue
    locale: str = Field(min_length=1, max_length=35)
    device: Literal["desktop", "mobile", "tablet"]
    sample_size: int = Field(ge=1, le=1000)
    window_days: int = Field(ge=1, le=365)


class MonitoringProtocolResponse(StrictModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    market_profile_id: UUID
    name: str
    platform: PlatformValue
    locale: str
    device: Literal["desktop", "mobile", "tablet"]
    sample_size: int
    window_days: int
    status: Literal["draft", "approved", "frozen"]
    protocol_hash: str | None
    created_at: datetime
    approved_at: datetime | None
    frozen_at: datetime | None


class CreateQuerySuggestionRequest(StrictModel):
    query_text: str = Field(min_length=1, max_length=4000)
    query_kind: Literal["recommendation", "comparison", "research", "support"]
    rationale: str = Field(min_length=1, max_length=4000)


class QuerySuggestionResponse(StrictModel):
    id: UUID
    project_id: UUID
    protocol_id: UUID
    query_text: str
    query_kind: str
    rationale: str
    status: Literal["suggested", "approved", "rejected"]
    monitoring_query_id: UUID | None
    created_at: datetime


class ProtocolQueryResponse(StrictModel):
    id: UUID
    project_id: UUID
    protocol_id: UUID
    monitoring_query_id: UUID
    query_text: str
    query_kind: str
    locale: str
    ordinal: int


class VerifiedCitationTargetResponse(StrictModel):
    submission_id: UUID
    destination_id: UUID
    destination_key: str
    publication_channel: str
    url: str
    verified_at: datetime


class ObservationCitationRequest(StrictModel):
    url: str = Field(min_length=8, max_length=4096)
    title: str | None = Field(default=None, max_length=1000)
    submission_id: UUID | None = None


class ImportObservationRequest(StrictModel):
    monitoring_query_id: UUID
    measurement_window: WindowValue
    sample_index: int = Field(ge=1)
    result_status: Literal["succeeded", "failed"]
    eligible: bool
    ineligible_reasons: list[str] = Field(default_factory=list, max_length=50)
    url_verification_status: Literal["passed", "failed", "unknown"]
    recommendation_present: bool = False
    primary_product_mentioned: bool = False
    competitor_mentioned: bool = False
    raw_answer: str | None = None
    raw_result: dict[str, object] = Field(default_factory=dict)
    citations: list[ObservationCitationRequest] = Field(default_factory=list, max_length=500)
    artifact_uri: str | None = Field(default=None, max_length=4096)
    artifact_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    configured_model: str = Field(min_length=1, max_length=300)
    provider_reported_model: str | None = Field(default=None, max_length=300)
    ui_surface: str = Field(min_length=1, max_length=300)
    ui_metadata: dict[str, object] = Field(default_factory=dict)
    confounding_factors: list[str] = Field(default_factory=list, max_length=50)
    observed_at: datetime


class ObservationCitationResponse(StrictModel):
    id: UUID
    url: str
    title: str | None
    verification_status: Literal["passed", "failed", "unknown"]
    destination_id: UUID | None
    submission_id: UUID | None
    verified_placement: bool


class MonitoringObservationResponse(StrictModel):
    id: UUID
    project_id: UUID
    protocol_id: UUID
    campaign_id: UUID
    monitoring_query_id: UUID
    measurement_window: WindowValue
    sample_index: int
    result_status: Literal["succeeded", "failed"]
    eligible: bool
    ineligible_reasons: list[str]
    url_verification_status: Literal["passed", "failed", "unknown"]
    recommendation_present: bool
    primary_product_mentioned: bool
    competitor_mentioned: bool
    raw_answer: str | None
    raw_result: dict[str, object]
    citations: list[ObservationCitationResponse]
    artifact_uri: str | None
    artifact_hash: str | None
    configured_model: str
    provider_reported_model: str | None
    ui_surface: str
    ui_metadata: dict[str, object]
    confounding_factors: list[str]
    observed_at: datetime
    payload_hash: str
    replayed: bool
    created_at: datetime


class ComputeMetricsRequest(StrictModel):
    measurement_window: WindowValue


class MetricResponse(StrictModel):
    id: UUID
    project_id: UUID
    protocol_id: UUID
    campaign_id: UUID
    measurement_window: WindowValue
    expected_sample_count: int
    eligible_sample_count: int
    recommendation_share: float
    product_mention_share: float
    placement_citation_share: float
    qualified_destination_coverage: float
    verified_placement_coverage: float
    competitive_delta: float
    status: Literal["complete", "confounded"]
    confounded_reasons: list[str]
    method_version: str
    computed_at: datetime


class MeasurementWindowResponse(StrictModel):
    protocol_id: UUID
    campaign_id: UUID
    measurement_window: WindowValue
    expected_sample_count: int
    eligible_sample_count: int
    status: Literal["complete", "confounded"]
    confounded_reasons: list[str]
    computed_at: datetime


class GenerateReportRequest(StrictModel):
    metric_snapshot_id: UUID
    title: str = Field(min_length=1, max_length=500)


class MonitoringReportResponse(StrictModel):
    id: UUID
    project_id: UUID
    protocol_id: UUID
    campaign_id: UUID
    metric_snapshot_id: UUID
    title: str
    body: str
    methodology_statement: str
    report_hash: str
    status: Literal["draft", "approved"]
    generated_at: datetime
    approved_at: datetime | None


class VerifiedUrlResponse(StrictModel):
    campaign_id: UUID
    protocol_ids: list[UUID]
    url: str
    title: str | None
    destination_id: UUID | None
    first_verified_at: datetime
    observation_count: int


class CustomerGeoSummaryResponse(StrictModel):
    project_id: UUID
    campaign_id: UUID | None
    frozen_protocol_count: int
    measurement_window_count: int
    verified_url_count: int
    approved_report_count: int
    latest_metrics: list[MetricResponse]
    interpretation: str
