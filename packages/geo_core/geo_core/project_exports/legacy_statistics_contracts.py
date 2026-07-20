"""Lossless Admin-only projection for legacy metric snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from geo_core.project_exports.constants import LEGACY_STATISTICS_CONTRACT_VERSION
from geo_core.project_exports.errors import ProjectExportRuleViolation
from geo_core.project_exports.field_validation import (
    aware_time,
    lineage_ids,
    non_negative_int,
    optional_sha256,
    ratio,
    required_text,
    sha256,
    uuid_value,
)
from geo_core.project_exports.statistics_contracts import MetricSnapshotExportRecord


@dataclass(frozen=True)
class LegacyMetricSnapshotExportRecord:
    """The common export shape with every statistics-v2-only value left null."""

    id: UUID
    project_id: UUID
    campaign_id: UUID
    protocol_id: UUID
    measurement_window: str
    source_stratum_hash: str | None
    statistics_contract_version: str
    query_cluster_key: None
    analysis_stratum_hash: None
    observation_membership_version: None
    observation_membership_count: None
    observation_membership_hash: None
    minimum_valid_repeats: None
    expected_sample_count: int
    sampled_sample_count: None
    eligible_sample_count: int
    invalid_sample_count: None
    missing_sample_count: None
    sampling_completion_ratio: None
    valid_completion_ratio: None
    query_count: None
    sufficient_query_count: None
    recommendation_share: Decimal
    product_mention_share: Decimal
    placement_citation_share: Decimal
    qualified_destination_coverage: Decimal
    verified_placement_coverage: Decimal
    competitive_delta: Decimal
    recommendation_ci_low: None
    recommendation_ci_high: None
    product_mention_ci_low: None
    product_mention_ci_high: None
    placement_citation_ci_low: None
    placement_citation_ci_high: None
    recommendation_query_min: None
    recommendation_query_max: None
    product_mention_query_min: None
    product_mention_query_max: None
    placement_citation_query_min: None
    placement_citation_query_max: None
    worst_query_id: None
    invalid_reason_counts: None
    declared_confounding_factors: None
    query_results_snapshot: None
    selected_destination_ids: None
    qualified_destination_ids: None
    verified_destination_ids: None
    status: str
    confounded_reasons: tuple[str, ...]
    input_hash: str
    result_hash: None
    method_version: str
    computed_at: datetime

    def __post_init__(self) -> None:
        lineage_ids(self)
        uuid_value(self.id, "legacy metric snapshot id")
        uuid_value(self.protocol_id, "legacy metric protocol_id")
        required_text(self.measurement_window, "legacy metric measurement_window")
        if self.statistics_contract_version != LEGACY_STATISTICS_CONTRACT_VERSION:
            raise ProjectExportRuleViolation("legacy metric statistics contract is invalid")
        optional_sha256(self.source_stratum_hash, "legacy metric source_stratum_hash")
        non_negative_int(self.expected_sample_count, "legacy metric expected_sample_count")
        non_negative_int(self.eligible_sample_count, "legacy metric eligible_sample_count")
        for name in (
            "recommendation_share",
            "product_mention_share",
            "placement_citation_share",
            "qualified_destination_coverage",
            "verified_placement_coverage",
        ):
            ratio(getattr(self, name), f"legacy metric {name}")
        if (
            not isinstance(self.competitive_delta, Decimal)
            or not self.competitive_delta.is_finite()
            or not Decimal("-1") <= self.competitive_delta <= Decimal("1")
        ):
            raise ProjectExportRuleViolation("legacy metric competitive_delta is invalid")
        required_text(self.status, "legacy metric status")
        if not isinstance(self.confounded_reasons, tuple):
            raise ProjectExportRuleViolation("legacy metric confounded_reasons must be a tuple")
        if len(set(self.confounded_reasons)) != len(self.confounded_reasons):
            raise ProjectExportRuleViolation("legacy metric confounded_reasons must be unique")
        for value in self.confounded_reasons:
            required_text(value, "legacy metric confounded reason")
        sha256(self.input_hash, "legacy metric input_hash")
        required_text(self.method_version, "legacy metric method_version")
        aware_time(self.computed_at, "legacy metric computed_at")


AnyMetricSnapshotExportRecord = LegacyMetricSnapshotExportRecord | MetricSnapshotExportRecord
