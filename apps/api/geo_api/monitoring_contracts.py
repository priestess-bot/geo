"""Stable transport contracts for monitoring and customer GEO reporting."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


PlatformValue = Literal[
    "chatgpt_search",
    "google_ai_overviews",
    "google_ai_mode",
    "google_search",
    "perplexity",
    "perplexity_answer",
    "gemini",
    "bing_search",
    "bing_copilot",
    "claude_ai",
    "other",
]
WindowValue = Literal["baseline", "t28", "t56", "t84", "ad_hoc"]
CaptureMethodValue = Literal[
    "official_report_import",
    "manual_ui",
    "provider_api",
    "proxy_grounded_api",
    "synthetic",
    "unknown",
]
PublicCaptureMethodValue = Literal["manual_ui", "provider_api", "proxy_grounded_api"]
ObservationPlatformValue = Literal[
    "openai", "google", "perplexity", "microsoft", "anthropic", "other"
]
SurfaceKindValue = Literal[
    "consumer_ui",
    "official_report",
    "provider_api",
    "grounded_proxy",
    "internal_benchmark",
    "other",
]
ObservationSurfaceValue = Literal[
    "chatgpt_search",
    "google_search",
    "google_ai_overviews",
    "google_ai_mode",
    "gemini",
    "perplexity_answer",
    "bing_search",
    "bing_copilot",
    "claude_ai",
    "openai_api",
    "google_gemini_api",
    "perplexity_api",
    "anthropic_api",
    "microsoft_foundry_bing_grounding",
    "google_vertex_grounding",
    "google_generative_ai_performance_report",
    "bing_ai_performance_report",
    "internal_benchmark",
    "other",
]
ModelIdentityStateValue = Literal["disclosed", "not_disclosed", "not_applicable"]
ObservationDeviceValue = Literal["desktop", "mobile", "tablet", "api", "internal_worker", "report"]
ClientKindValue = Literal["browser", "native_app", "api", "internal_worker", "report_import"]
SearchModeValue = Literal["disabled", "live_web", "grounded_web", "automatic", "not_applicable"]
SourceStratumContractVersionValue = Literal[
    "geo-observation-source-v2", "geo-observation-source-v3"
]


class ModelIdentityContract(StrictModel):
    state: ModelIdentityStateValue
    value: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_identity(self) -> "ModelIdentityContract":
        if (self.state == "disclosed") != (self.value is not None):
            raise ValueError("disclosed model identity requires exactly one value")
        return self


class SourceStratumContract(StrictModel):
    capture_method: CaptureMethodValue
    platform: ObservationPlatformValue
    platform_detail: str | None = Field(default=None, max_length=500)
    surface: ObservationSurfaceValue
    surface_kind: SurfaceKindValue
    surface_detail: str | None = Field(default=None, max_length=500)
    engine: str = Field(min_length=1, max_length=200)
    configured_model: ModelIdentityContract
    reported_model: ModelIdentityContract
    locale: str = Field(min_length=1, max_length=35)
    region: str = Field(min_length=1, max_length=100)
    language: str = Field(min_length=1, max_length=35)
    device: ObservationDeviceValue
    client_kind: ClientKindValue
    search_enabled: bool
    search_mode: SearchModeValue
    source_contract_version: SourceStratumContractVersionValue = (
        "geo-observation-source-v3"
    )

    @model_validator(mode="after")
    def validate_details(self) -> "SourceStratumContract":
        if self.source_contract_version == "geo-observation-source-v2":
            if self.platform_detail is not None or self.surface_detail is not None:
                raise ValueError("legacy source strata cannot carry detail fields")
            return self
        _normalize_source_details(self)
        return self


class ObservationRunParametersContract(StrictModel):
    engine: str | None = Field(max_length=200)
    locale: str | None = Field(max_length=35)
    region: str | None = Field(max_length=100)
    language: str | None = Field(max_length=35)
    device: ObservationDeviceValue | None
    client_kind: ClientKindValue | None
    search_enabled: bool | None
    search_mode: SearchModeValue | None
    prompt_text: str | None = Field(max_length=20_000)
    follow_up_prompts: list[str] = Field(default_factory=list, max_length=50)
    adapter_name: str | None = Field(default=None, max_length=200)
    adapter_version: str | None = Field(default=None, max_length=200)
    provider_request_id: str | None = Field(default=None, max_length=500)


class AnswerRawEvidenceRequest(StrictModel):
    kind: Literal["answer"]
    answer: str = Field(min_length=1, max_length=2_000_000)


class InlineRawEvidenceRequest(StrictModel):
    kind: Literal["inline_response"]
    inline_response: dict[str, object] = Field(min_length=1)


class ArtifactRawEvidenceRequest(StrictModel):
    kind: Literal["artifact"]
    artifact_uri: str = Field(min_length=8, max_length=4096)
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


RawEvidenceRequest = Annotated[
    AnswerRawEvidenceRequest | InlineRawEvidenceRequest | ArtifactRawEvidenceRequest,
    Field(discriminator="kind"),
]


class ObservationSourceRequest(StrictModel):
    platform: ObservationPlatformValue
    surface: ObservationSurfaceValue
    surface_kind: SurfaceKindValue
    platform_detail: str | None = Field(default=None, max_length=500)
    surface_detail: str | None = Field(default=None, max_length=500)
    configured_model: ModelIdentityContract
    reported_model: ModelIdentityContract
    run: ObservationRunParametersContract
    raw_evidence: RawEvidenceRequest

    @model_validator(mode="after")
    def validate_details(self) -> "ObservationSourceRequest":
        _normalize_source_details(self)
        return self


def _normalize_source_details(
    value: SourceStratumContract | ObservationSourceRequest,
) -> None:
    for name in ("platform_detail", "surface_detail"):
        detail = getattr(value, name)
        normalized = detail.strip() if detail and detail.strip() else None
        if normalized is not None and not normalized.isascii():
            raise ValueError(f"{name} must be non-empty ASCII")
        setattr(value, name, normalized)
    if (value.platform == "other") != (value.platform_detail is not None):
        raise ValueError("platform_detail is required exactly for OTHER")
    if (value.surface == "other") != (value.surface_detail is not None):
        raise ValueError("surface_detail is required exactly for OTHER")


class RawEvidenceResponse(StrictModel):
    kind: Literal["answer", "inline_response", "artifact", "legacy_unknown"]
    answer: str | None = None
    inline_response: dict[str, object] | None = None
    artifact_uri: str | None = None
    artifact_hash: str | None = None
    artifact_verified: bool


class ObservationSourceResponse(StrictModel):
    capture_method: CaptureMethodValue
    platform: ObservationPlatformValue
    surface: ObservationSurfaceValue
    surface_kind: SurfaceKindValue
    platform_detail: str | None
    surface_detail: str | None
    configured_model: ModelIdentityContract
    reported_model: ModelIdentityContract
    run: ObservationRunParametersContract
    raw_evidence: RawEvidenceResponse
    source_contract_version: str
    citations_captured: bool
    source_job_id: UUID | None
    model_call_log_id: UUID | None
    test_only: bool
    publication_eligible: bool
    source_badge: str


class CreateMonitoringProtocolRequest(StrictModel):
    campaign_id: UUID
    market_profile_id: UUID
    name: str = Field(min_length=1, max_length=200)
    platform: PlatformValue
    locale: str = Field(min_length=1, max_length=35)
    device: Literal["desktop", "mobile", "tablet"]
    sample_size: int = Field(ge=3, le=1000)
    minimum_valid_repeats: int = Field(ge=3, le=1000)
    window_days: int = Field(ge=1, le=365)
    source_strata: list[SourceStratumContract] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_statistics_threshold(self) -> "CreateMonitoringProtocolRequest":
        minimum = max(3, (4 * self.sample_size + 4) // 5)
        if not minimum <= self.minimum_valid_repeats <= self.sample_size:
            raise ValueError("minimum valid repeats must meet the frozen 80 percent threshold")
        return self


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
    minimum_valid_repeats: int | None
    window_days: int
    status: Literal["draft", "approved", "frozen"]
    protocol_hash: str | None
    created_at: datetime
    approved_at: datetime | None
    frozen_at: datetime | None
    source_strata: list[SourceStratumContract]
    source_strata_hash: str | None
    statistics_method_version: str | None
    statistics_contract_version: str
    question_set_id: UUID | None
    question_set_hash: str | None
    question_set_bound_by: UUID | None
    question_set_bound_at: datetime | None


class BindQuestionSetRequest(StrictModel):
    campaign_id: UUID
    question_set_id: UUID
    confirmed_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CreateQuerySuggestionRequest(StrictModel):
    campaign_id: UUID
    query_text: str = Field(min_length=1, max_length=4000)
    query_kind: Literal["recommendation", "comparison", "research", "support"]
    rationale: str = Field(min_length=1, max_length=4000)
    query_cluster_key: str = Field(min_length=1, max_length=300)


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
    query_cluster_key: str | None


class ProtocolQueryResponse(StrictModel):
    id: UUID
    project_id: UUID
    protocol_id: UUID
    monitoring_query_id: UUID
    query_text: str
    query_kind: str
    locale: str
    ordinal: int
    query_cluster_key: str | None
    question_set_item_id: UUID | None = None
    question_candidate_id: UUID | None = None


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
    campaign_id: UUID
    capture_method: PublicCaptureMethodValue
    monitoring_query_id: UUID
    measurement_window: WindowValue
    sample_index: int = Field(ge=1)
    result_status: Literal["succeeded", "failed"]
    requested_eligible: bool
    operator_ineligible_reasons: list[str] = Field(default_factory=list, max_length=50)
    url_verification_status: Literal["passed", "failed", "unknown"]
    recommendation_present: bool = False
    primary_product_mentioned: bool = False
    competitor_mentioned: bool = False
    citations: list[ObservationCitationRequest] = Field(max_length=500)
    source: ObservationSourceRequest
    ui_metadata: dict[str, object] = Field(default_factory=dict)
    confounding_factors: list[str] = Field(default_factory=list, max_length=50)
    observed_at: datetime


class ObservationCitationResponse(StrictModel):
    id: UUID
    citation_index: int
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
    requested_eligible: bool
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
    configured_model: str | None
    provider_reported_model: str | None
    ui_surface: str
    ui_metadata: dict[str, object]
    confounding_factors: list[str]
    capture_method: CaptureMethodValue
    source: ObservationSourceResponse
    source_stratum: SourceStratumContract | None
    source_stratum_hash: str | None
    query_cluster_key: str | None
    captured_by: UUID
    observed_at: datetime
    payload_hash: str
    replayed: bool
    created_at: datetime


class OfficialReportRowRequest(StrictModel):
    row_index: int = Field(ge=0)
    row_data: dict[str, object] = Field(min_length=1)
    requested_eligible: bool = True
    operator_ineligible_reasons: list[str] = Field(default_factory=list, max_length=50)


class ImportOfficialReportRequest(StrictModel):
    campaign_id: UUID
    platform: ObservationPlatformValue
    surface: ObservationSurfaceValue
    platform_detail: str | None = Field(default=None, max_length=500)
    surface_detail: str | None = Field(default=None, max_length=500)
    artifact: ArtifactRawEvidenceRequest
    parser_name: str = Field(min_length=1, max_length=200)
    parser_version: str = Field(min_length=1, max_length=200)
    report_period_start: date
    report_period_end: date
    account_ref: str = Field(min_length=1, max_length=500)
    rows: list[OfficialReportRowRequest] = Field(min_length=1, max_length=100_000)


class OfficialReportRowResponse(StrictModel):
    id: UUID
    row_index: int
    row_data: dict[str, object]
    eligible: bool
    ineligible_reasons: list[str]
    row_hash: str
    created_at: datetime


class OfficialReportImportResponse(StrictModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    capture_method: Literal["official_report_import"]
    platform: ObservationPlatformValue
    surface: ObservationSurfaceValue
    platform_detail: str | None
    surface_detail: str | None
    artifact_uri: str
    artifact_hash: str
    parser_name: str
    parser_version: str
    report_period_start: date
    report_period_end: date
    account_ref: str
    payload_hash: str
    imported_by: UUID
    rows: list[OfficialReportRowResponse]
    created_at: datetime
    replayed: bool


class ComputeMetricsRequest(StrictModel):
    campaign_id: UUID
    measurement_window: WindowValue
    source_stratum_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_cluster_key: str = Field(min_length=1, max_length=300)


class BinaryEstimateResponse(StrictModel):
    numerator: int
    denominator: int
    share: float
    ci_low: float
    ci_high: float


class QueryMetricResultResponse(StrictModel):
    monitoring_query_id: UUID
    query_text_snapshot: str
    query_cluster_key: str
    expected_sample_count: int
    sampled_sample_count: int
    valid_sample_count: int
    invalid_sample_count: int
    missing_sample_count: int
    meets_threshold: bool
    invalid_reason_counts: dict[str, int]
    confounding_factors: list[str]
    recommendation: BinaryEstimateResponse
    product_mention: BinaryEstimateResponse
    placement_citation: BinaryEstimateResponse
    competitor: BinaryEstimateResponse
    competitive_delta: float


class MetricResponse(StrictModel):
    id: UUID
    project_id: UUID
    protocol_id: UUID
    campaign_id: UUID
    measurement_window: WindowValue
    capture_method: CaptureMethodValue
    source_stratum: SourceStratumContract | None
    source_stratum_hash: str | None
    statistics_contract_version: str
    query_cluster_key: str | None
    analysis_stratum_hash: str | None
    minimum_valid_repeats: int | None
    expected_sample_count: int
    sampled_sample_count: int | None
    eligible_sample_count: int
    invalid_sample_count: int | None
    missing_sample_count: int | None
    sampling_completion_ratio: float | None
    valid_completion_ratio: float | None
    query_count: int | None
    sufficient_query_count: int | None
    invalid_reason_counts: dict[str, int]
    declared_confounding_factors: list[str]
    query_results: list[QueryMetricResultResponse]
    recommendation_share: float
    recommendation_ci_low: float | None
    recommendation_ci_high: float | None
    product_mention_share: float
    product_mention_ci_low: float | None
    product_mention_ci_high: float | None
    placement_citation_share: float
    placement_citation_ci_low: float | None
    placement_citation_ci_high: float | None
    recommendation_query_min: float | None
    recommendation_query_max: float | None
    product_mention_query_min: float | None
    product_mention_query_max: float | None
    placement_citation_query_min: float | None
    placement_citation_query_max: float | None
    worst_query_id: UUID | None
    selected_destination_ids: list[UUID]
    qualified_destination_ids: list[UUID]
    verified_destination_ids: list[UUID]
    qualified_destination_coverage: float
    verified_placement_coverage: float
    competitive_delta: float
    status: Literal["complete", "confounded", "insufficient_evidence"]
    confounded_reasons: list[str]
    method_version: str
    input_hash: str
    result_hash: str | None
    observation_membership_version: str | None
    observation_membership_hash: str | None
    observation_membership_count: int | None
    computed_at: datetime


class MeasurementWindowResponse(StrictModel):
    protocol_id: UUID
    campaign_id: UUID
    measurement_window: WindowValue
    expected_sample_count: int
    eligible_sample_count: int
    status: Literal["complete", "confounded", "insufficient_evidence"]
    confounded_reasons: list[str]
    computed_at: datetime


class GenerateReportRequest(StrictModel):
    campaign_id: UUID
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
