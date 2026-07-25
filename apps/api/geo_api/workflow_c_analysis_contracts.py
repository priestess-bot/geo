"""Strict Internal API contracts for semantic metrics, comparisons and drift."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceLocatorContract(StrictModel):
    kind: Literal["answer_span", "citation", "fact"]
    reference_id: str = Field(min_length=1, max_length=500)
    version: str | None = Field(default=None, max_length=200)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)
    redacted_quote_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class ComputeSemanticMetricsRequest(StrictModel):
    sampling_run_id: UUID
    sampling_run_version: int = Field(ge=1)
    suite_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    metric_protocol_id: UUID
    metric_protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_snapshot_id: UUID
    fact_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_release_id: UUID
    prompt_release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_version_id: UUID
    corpus_version_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CreateMetricProtocolRequest(StrictModel):
    definition: dict[str, object]
    supersedes_protocol_id: UUID | None = None


class MetricProtocolTransitionRequest(StrictModel):
    expected_aggregate_version: int = Field(ge=1)
    reason: str | None = Field(default=None, min_length=1, max_length=2_000)


class MetricProtocolDecisionRequest(MetricProtocolTransitionRequest):
    reason: str = Field(min_length=1, max_length=2_000)


class MetricProtocolResponse(StrictModel):
    id: UUID
    project_id: UUID
    series_id: UUID
    version: int
    supersedes_protocol_id: UUID | None
    status: Literal["draft", "in_review", "approved", "retired"]
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    definition: dict[str, object]
    created_by: str
    submitted_by: str | None
    approved_by: str | None
    retired_by: str | None
    decision_reason: str | None
    aggregate_version: int
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    approved_at: datetime | None
    retired_at: datetime | None


class MetricProtocolPageResponse(StrictModel):
    items: list[MetricProtocolResponse]
    total: int


class CreateStatisticalProtocolRequest(StrictModel):
    definition: dict[str, object]
    supersedes_protocol_id: UUID | None = None


class StatisticalProtocolTransitionRequest(StrictModel):
    expected_aggregate_version: int = Field(ge=1)
    reason: str | None = Field(default=None, min_length=1, max_length=2_000)


class StatisticalProtocolDecisionRequest(StatisticalProtocolTransitionRequest):
    reason: str = Field(min_length=1, max_length=2_000)


class StatisticalProtocolResponse(StrictModel):
    id: UUID
    project_id: UUID
    series_id: UUID
    version: int
    supersedes_protocol_id: UUID | None
    kind: Literal["comparison_plan", "drift_protocol"]
    status: Literal["draft", "in_review", "approved", "retired"]
    definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    definition: dict[str, object]
    created_by: str
    submitted_by: str | None
    approved_by: str | None
    retired_by: str | None
    decision_reason: str | None
    aggregate_version: int
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    approved_at: datetime | None
    retired_at: datetime | None


class StatisticalProtocolPageResponse(StrictModel):
    items: list[StatisticalProtocolResponse]
    total: int


class EnqueueSemanticMetricsRequest(StrictModel):
    sampling_run_id: UUID
    metric_protocol_id: UUID
    max_attempts: int = Field(default=3, ge=1, le=10)


class SemanticMetricsJobAccepted(StrictModel):
    job_id: UUID
    status: Literal["queued"] = "queued"
    status_url: str
    manifest_id: UUID
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    replayed: bool


class EnqueueComparisonJobRequest(StrictModel):
    comparison_plan_id: UUID
    baseline_metric_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_metric_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_attempts: int = Field(default=3, ge=1, le=10)


class EnqueueDriftJobRequest(StrictModel):
    drift_protocol_id: UUID
    baseline_metric_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_metric_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_attempts: int = Field(default=3, ge=1, le=10)


class StatisticalAnalysisJobAccepted(StrictModel):
    job_id: UUID
    status: Literal["queued"] = "queued"
    status_url: str
    spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    replayed: bool


class MetricIntervalResponse(StrictModel):
    method: str
    confidence_level: str | None
    low: str
    high: str


class SemanticMetricResultResponse(StrictModel):
    metric_key: str
    metric_version: str
    value_kind: str
    input_set_hash: str
    stratum: dict[str, str]
    stratum_hash: str
    numerator: str
    denominator: int
    estimate: str
    interval: MetricIntervalResponse
    valid_input_count: int
    invalid_input_count: int
    missing_input_count: int
    status: Literal["complete", "insufficient_evidence"]
    judge_version: str | None
    judge_version_hash: str | None
    rule_versions: dict[str, str]
    rule_versions_hash: str
    evidence_locators: list[EvidenceLocatorContract]
    breakdown: dict[str, str]
    result_hash: str


class QuestionPerformanceResponse(StrictModel):
    question_id: str
    question_cluster: str
    score: str
    planned_slot_count: int


class ClusterPerformanceResponse(StrictModel):
    question_cluster: str
    score: str
    planned_slot_count: int


class NegativeGainResponse(StrictModel):
    compared_question_count: int
    affected_question_count: int
    mean_negative_gain: str
    range_low: str
    range_high: str
    worst_question_id: str | None
    worst_question_delta: str | None


class PerformanceResponse(StrictModel):
    questions: list[QuestionPerformanceResponse]
    clusters: list[ClusterPerformanceResponse]
    worst_question_id: str
    worst_question_score: str
    worst_cluster: str
    worst_cluster_score: str
    negative_gain: NegativeGainResponse | None


class SemanticMetricSnapshotResponse(StrictModel):
    project_id: UUID
    input_set_hash: str
    suite_hash: str
    stratum_hash: str
    results: list[SemanticMetricResultResponse]
    performance: PerformanceResponse
    computed_at: datetime
    snapshot_hash: str


class SemanticMetricSnapshotPageResponse(StrictModel):
    items: list[SemanticMetricSnapshotResponse]
    total: int


class AnalyzeComparisonFamilyRequest(StrictModel):
    comparison_plan_id: UUID
    comparison_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_metric_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_metric_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class StatisticalIntervalResponse(StrictModel):
    method: str
    alpha: str
    low: str
    high: str


class ComparisonResultResponse(StrictModel):
    comparison_id: str
    family: str
    protocol_frozen_hash: str
    input_hash: str
    stratum_hash: str
    valid_pair_count: int
    planned_pair_count: int
    completion_ratio: str
    point_estimate: str
    raw_interval: StatisticalIntervalResponse
    adjusted_interval: StatisticalIntervalResponse
    raw_p_value: str
    adjusted_p_value: str
    holm_rank: int
    local_alpha: str
    a_priori_design_power: str
    power_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    power_method_version: str
    conclusion: Literal["win", "equivalent", "loss", "inconclusive", "insufficient_evidence"]
    seed_hex: str
    bootstrap_iterations: int
    result_hash: str


class ComparisonFamilyResponse(StrictModel):
    project_id: UUID
    family: str
    alpha: str
    correction_method: str
    results: list[ComparisonResultResponse]
    family_hash: str


class ComparisonFamilyPageResponse(StrictModel):
    items: list[ComparisonFamilyResponse]
    total: int


class ComputeDriftRequest(StrictModel):
    drift_protocol_id: UUID
    drift_protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_metric_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_metric_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class DriftReportResponse(StrictModel):
    project_id: UUID
    model_drift: list[dict[str, object]]
    source_drift: list[dict[str, object]]
    effect_drift: list[dict[str, object]]
    unmatched_baseline_strata: list[str]
    unmatched_current_strata: list[str]
    baseline_input_hash: str
    current_input_hash: str
    method_version: str
    protocol_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    report_hash: str


class DriftReportPageResponse(StrictModel):
    items: list[DriftReportResponse]
    total: int
