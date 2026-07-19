"""F021-aligned metric snapshot records exposed by the F027 export."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from uuid import UUID

from geo_core.project_exports.constants import METRIC_METHOD_VERSION
from geo_core.project_exports.constants import OBSERVATION_MEMBERSHIP_VERSION
from geo_core.project_exports.errors import ProjectExportRuleViolation
from geo_core.project_exports.field_validation import (
    aware_time,
    boolean,
    lineage_ids,
    non_negative_int,
    positive_int,
    ratio,
    required_text,
    sha256,
    uuid_value,
)


_QUANTUM = Decimal("0.000001")
_WILSON_Z = Decimal("1.959963984540054")


@dataclass(frozen=True)
class InvalidReasonCountExportRecord:
    reason: str
    count: int

    def __post_init__(self) -> None:
        required_text(self.reason, "invalid reason")
        positive_int(self.count, "invalid reason count")


@dataclass(frozen=True)
class MetricEstimateExportRecord:
    numerator: int
    denominator: int
    share: Decimal
    ci_low: Decimal
    ci_high: Decimal

    def __post_init__(self) -> None:
        non_negative_int(self.numerator, "estimate numerator")
        non_negative_int(self.denominator, "estimate denominator")
        ratio(self.share, "estimate share")
        ratio(self.ci_low, "estimate ci_low")
        ratio(self.ci_high, "estimate ci_high")
        if self.numerator > self.denominator:
            raise ProjectExportRuleViolation("estimate numerator exceeds denominator")
        expected_share = _share(self.numerator, self.denominator)
        expected_low, expected_high = wilson_interval(self.numerator, self.denominator)
        if self.share != expected_share or (self.ci_low, self.ci_high) != (
            expected_low,
            expected_high,
        ):
            raise ProjectExportRuleViolation("estimate share or Wilson interval is inconsistent")


@dataclass(frozen=True)
class QueryMetricResultExportRecord:
    monitoring_query_id: UUID
    query_text_snapshot: str
    query_cluster_key: str
    expected_sample_count: int
    sampled_sample_count: int
    valid_sample_count: int
    invalid_sample_count: int
    missing_sample_count: int
    meets_threshold: bool
    invalid_reason_counts: tuple[InvalidReasonCountExportRecord, ...]
    confounding_factors: tuple[str, ...]
    recommendation: MetricEstimateExportRecord
    product_mention: MetricEstimateExportRecord
    placement_citation: MetricEstimateExportRecord
    competitor: MetricEstimateExportRecord
    competitive_delta: Decimal

    def __post_init__(self) -> None:
        uuid_value(self.monitoring_query_id, "query result monitoring_query_id")
        required_text(self.query_text_snapshot, "query result text snapshot")
        required_text(self.query_cluster_key, "query result cluster key")
        positive_int(self.expected_sample_count, "query result expected_sample_count")
        for name in (
            "sampled_sample_count",
            "valid_sample_count",
            "invalid_sample_count",
            "missing_sample_count",
        ):
            non_negative_int(getattr(self, name), f"query result {name}")
        boolean(self.meets_threshold, "query result meets_threshold")
        _count_consistency(
            expected=self.expected_sample_count,
            sampled=self.sampled_sample_count,
            valid=self.valid_sample_count,
            invalid=self.invalid_sample_count,
            missing=self.missing_sample_count,
            label="query result",
        )
        if not isinstance(self.invalid_reason_counts, tuple):
            raise ProjectExportRuleViolation("query invalid_reason_counts must be a tuple")
        _unique_reasons(self.invalid_reason_counts, "query invalid reasons")
        _validate_reason_counts(
            self.invalid_reason_counts,
            invalid_sample_count=self.invalid_sample_count,
            label="query invalid reasons",
        )
        if not isinstance(self.confounding_factors, tuple):
            raise ProjectExportRuleViolation("query confounding_factors must be a tuple")
        _unique_text(self.confounding_factors, "query confounding factors")
        for estimate in (
            self.recommendation,
            self.product_mention,
            self.placement_citation,
            self.competitor,
        ):
            if estimate.denominator != self.valid_sample_count:
                raise ProjectExportRuleViolation(
                    "query estimate denominator differs from valid_sample_count"
                )
        _signed_ratio(self.competitive_delta, "query competitive_delta")
        expected_delta = _quantize(
            self.product_mention.share - self.competitor.share
        )
        if self.competitive_delta != expected_delta:
            raise ProjectExportRuleViolation("query competitive_delta is inconsistent")


@dataclass(frozen=True)
class MetricSnapshotExportRecord:
    id: UUID
    project_id: UUID
    campaign_id: UUID
    protocol_id: UUID
    measurement_window: str
    source_stratum_hash: str
    statistics_contract_version: str
    query_cluster_key: str
    analysis_stratum_hash: str
    observation_membership_version: str | None
    observation_membership_count: int | None
    observation_membership_hash: str | None
    minimum_valid_repeats: int
    expected_sample_count: int
    sampled_sample_count: int
    eligible_sample_count: int
    invalid_sample_count: int
    missing_sample_count: int
    sampling_completion_ratio: Decimal
    valid_completion_ratio: Decimal
    query_count: int
    sufficient_query_count: int
    recommendation_share: Decimal
    product_mention_share: Decimal
    placement_citation_share: Decimal
    qualified_destination_coverage: Decimal
    verified_placement_coverage: Decimal
    competitive_delta: Decimal
    recommendation_ci_low: Decimal
    recommendation_ci_high: Decimal
    product_mention_ci_low: Decimal
    product_mention_ci_high: Decimal
    placement_citation_ci_low: Decimal
    placement_citation_ci_high: Decimal
    recommendation_query_min: Decimal
    recommendation_query_max: Decimal
    product_mention_query_min: Decimal
    product_mention_query_max: Decimal
    placement_citation_query_min: Decimal
    placement_citation_query_max: Decimal
    worst_query_id: UUID | None
    invalid_reason_counts: tuple[InvalidReasonCountExportRecord, ...]
    declared_confounding_factors: tuple[str, ...]
    query_results_snapshot: tuple[QueryMetricResultExportRecord, ...]
    selected_destination_ids: tuple[UUID, ...]
    qualified_destination_ids: tuple[UUID, ...]
    verified_destination_ids: tuple[UUID, ...]
    status: str
    confounded_reasons: tuple[str, ...]
    input_hash: str
    result_hash: str
    method_version: str
    computed_at: datetime

    def __post_init__(self) -> None:
        lineage_ids(self)
        uuid_value(self.id, "metric snapshot id")
        uuid_value(self.protocol_id, "metric snapshot protocol_id")
        required_text(self.measurement_window, "metric measurement_window")
        required_text(self.query_cluster_key, "metric query_cluster_key")
        if self.status not in {"complete", "confounded", "insufficient_evidence"}:
            raise ProjectExportRuleViolation("metric status is unsupported")
        sha256(self.source_stratum_hash, "metric source_stratum_hash")
        sha256(self.analysis_stratum_hash, "metric analysis_stratum_hash")
        sha256(self.input_hash, "metric input_hash")
        sha256(self.result_hash, "metric result_hash")
        if self.statistics_contract_version != METRIC_METHOD_VERSION:
            raise ProjectExportRuleViolation(
                f"statistics_contract_version must be {METRIC_METHOD_VERSION!r}"
            )
        if self.method_version != METRIC_METHOD_VERSION:
            raise ProjectExportRuleViolation(
                f"metric method_version must be {METRIC_METHOD_VERSION!r}"
            )
        membership_header = (
            self.observation_membership_version,
            self.observation_membership_count,
            self.observation_membership_hash,
        )
        if any(value is None for value in membership_header) and any(
            value is not None for value in membership_header
        ):
            raise ProjectExportRuleViolation(
                "metric observation membership header is incomplete"
            )
        if self.observation_membership_version is not None:
            if self.observation_membership_version != OBSERVATION_MEMBERSHIP_VERSION:
                raise ProjectExportRuleViolation(
                    "metric observation membership version is invalid"
                )
            non_negative_int(
                self.observation_membership_count,
                "metric observation_membership_count",
            )
            sha256(
                self.observation_membership_hash,
                "metric observation_membership_hash",
            )
        expected_analysis_hash = _canonical_hash(
            {
                "query_cluster_key": self.query_cluster_key,
                "source_stratum_hash": self.source_stratum_hash,
            }
        )
        if self.analysis_stratum_hash != expected_analysis_hash:
            raise ProjectExportRuleViolation("metric analysis_stratum_hash is inconsistent")
        positive_int(self.minimum_valid_repeats, "metric minimum_valid_repeats")
        positive_int(self.expected_sample_count, "metric expected_sample_count")
        for name in (
            "sampled_sample_count",
            "eligible_sample_count",
            "invalid_sample_count",
            "missing_sample_count",
            "sufficient_query_count",
        ):
            non_negative_int(getattr(self, name), f"metric {name}")
        positive_int(self.query_count, "metric query_count")
        _count_consistency(
            expected=self.expected_sample_count,
            sampled=self.sampled_sample_count,
            valid=self.eligible_sample_count,
            invalid=self.invalid_sample_count,
            missing=self.missing_sample_count,
            label="metric snapshot",
        )
        if (
            self.observation_membership_count is not None
            and self.observation_membership_count != self.sampled_sample_count
        ):
            raise ProjectExportRuleViolation(
                "metric observation membership count differs from sampled count"
            )
        if self.sufficient_query_count > self.query_count:
            raise ProjectExportRuleViolation("sufficient_query_count exceeds query_count")
        for name in (
            "sampling_completion_ratio",
            "valid_completion_ratio",
            "recommendation_share",
            "product_mention_share",
            "placement_citation_share",
            "qualified_destination_coverage",
            "verified_placement_coverage",
            "recommendation_ci_low",
            "recommendation_ci_high",
            "product_mention_ci_low",
            "product_mention_ci_high",
            "placement_citation_ci_low",
            "placement_citation_ci_high",
            "recommendation_query_min",
            "recommendation_query_max",
            "product_mention_query_min",
            "product_mention_query_max",
            "placement_citation_query_min",
            "placement_citation_query_max",
        ):
            ratio(getattr(self, name), f"metric {name}")
        _signed_ratio(self.competitive_delta, "metric competitive_delta")
        if self.sampling_completion_ratio != _share(
            self.sampled_sample_count, self.expected_sample_count
        ) or self.valid_completion_ratio != _share(
            self.eligible_sample_count, self.expected_sample_count
        ):
            raise ProjectExportRuleViolation("metric completion ratio is inconsistent")
        if not isinstance(self.invalid_reason_counts, tuple):
            raise ProjectExportRuleViolation("metric invalid_reason_counts must be a tuple")
        _unique_reasons(self.invalid_reason_counts, "metric invalid reasons")
        _validate_reason_counts(
            self.invalid_reason_counts,
            invalid_sample_count=self.invalid_sample_count,
            label="metric invalid reasons",
        )
        for name in ("declared_confounding_factors", "confounded_reasons"):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise ProjectExportRuleViolation(f"metric {name} must be a tuple")
            _unique_text(values, f"metric {name}")
        if not isinstance(self.query_results_snapshot, tuple):
            raise ProjectExportRuleViolation("metric query_results_snapshot must be a tuple")
        query_ids = [item.monitoring_query_id for item in self.query_results_snapshot]
        if len(set(query_ids)) != len(query_ids) or len(query_ids) != self.query_count:
            raise ProjectExportRuleViolation("metric query results must be complete and unique")
        if any(
            item.query_cluster_key != self.query_cluster_key
            for item in self.query_results_snapshot
        ):
            raise ProjectExportRuleViolation("metric query result crosses query cluster")
        if any(
            item.meets_threshold
            != (item.valid_sample_count >= self.minimum_valid_repeats)
            for item in self.query_results_snapshot
        ):
            raise ProjectExportRuleViolation("query threshold result is inconsistent")
        if any(
            not max(3, (item.expected_sample_count * 4 + 4) // 5)
            <= self.minimum_valid_repeats
            <= item.expected_sample_count
            for item in self.query_results_snapshot
        ):
            raise ProjectExportRuleViolation("metric minimum_valid_repeats is inconsistent")
        if sum(item.expected_sample_count for item in self.query_results_snapshot) != self.expected_sample_count:
            raise ProjectExportRuleViolation("query expected counts do not total metric expected count")
        if sum(item.sampled_sample_count for item in self.query_results_snapshot) != self.sampled_sample_count:
            raise ProjectExportRuleViolation("query sampled counts do not total metric sampled count")
        if sum(item.valid_sample_count for item in self.query_results_snapshot) != self.eligible_sample_count:
            raise ProjectExportRuleViolation("query valid counts do not total metric valid count")
        if sum(item.invalid_sample_count for item in self.query_results_snapshot) != self.invalid_sample_count:
            raise ProjectExportRuleViolation("query invalid counts do not total metric invalid count")
        if sum(item.missing_sample_count for item in self.query_results_snapshot) != self.missing_sample_count:
            raise ProjectExportRuleViolation("query missing counts do not total metric missing count")
        if sum(item.meets_threshold for item in self.query_results_snapshot) != self.sufficient_query_count:
            raise ProjectExportRuleViolation("query threshold results do not match sufficient count")
        expected_status = (
            "insufficient_evidence"
            if self.sufficient_query_count < self.query_count
            else ("confounded" if self.confounded_reasons else "complete")
        )
        if self.status != expected_status:
            raise ProjectExportRuleViolation("metric status is inconsistent")
        aggregate_invalid_reasons: dict[str, int] = {}
        for query_result in self.query_results_snapshot:
            for item in query_result.invalid_reason_counts:
                aggregate_invalid_reasons[item.reason] = (
                    aggregate_invalid_reasons.get(item.reason, 0) + item.count
                )
        if aggregate_invalid_reasons != {
            item.reason: item.count for item in self.invalid_reason_counts
        }:
            raise ProjectExportRuleViolation(
                "metric invalid reasons do not aggregate query invalid reasons"
            )
        aggregate_confounders = {
            value
            for query_result in self.query_results_snapshot
            for value in query_result.confounding_factors
        }
        if aggregate_confounders != set(self.declared_confounding_factors):
            raise ProjectExportRuleViolation(
                "metric confounding factors do not aggregate query results"
            )
        _validate_aggregate_estimates(self)
        _destination_sets(self)
        _validate_destination_coverage(self)
        expected_worst_query_id = min(
            self.query_results_snapshot,
            key=lambda item: (
                item.product_mention.share,
                item.recommendation.share,
                item.placement_citation.share,
                str(item.monitoring_query_id),
            ),
        ).monitoring_query_id
        if self.worst_query_id != expected_worst_query_id:
            raise ProjectExportRuleViolation("metric worst_query_id is inconsistent")
        if self.worst_query_id is not None:
            uuid_value(self.worst_query_id, "metric worst_query_id")
            if self.worst_query_id not in set(query_ids):
                raise ProjectExportRuleViolation("metric worst_query_id is not in query results")
        aware_time(self.computed_at, "metric computed_at")


def wilson_interval(numerator: int, denominator: int) -> tuple[Decimal, Decimal]:
    if denominator == 0:
        return Decimal("0.000000"), Decimal("1.000000")
    count = Decimal(denominator)
    proportion = Decimal(numerator) / count
    z_squared = _WILSON_Z * _WILSON_Z
    denominator_term = Decimal(1) + z_squared / count
    center = (proportion + z_squared / (Decimal(2) * count)) / denominator_term
    variance = (
        proportion * (Decimal(1) - proportion) / count
        + z_squared / (Decimal(4) * count * count)
    )
    margin = _WILSON_Z * variance.sqrt() / denominator_term
    return (
        _quantize(max(Decimal(0), center - margin)),
        _quantize(min(Decimal(1), center + margin)),
    )


def _validate_aggregate_estimates(snapshot: MetricSnapshotExportRecord) -> None:
    estimate_fields = (
        (
            "recommendation",
            "recommendation_share",
            "recommendation_ci_low",
            "recommendation_ci_high",
            "recommendation_query_min",
            "recommendation_query_max",
        ),
        (
            "product_mention",
            "product_mention_share",
            "product_mention_ci_low",
            "product_mention_ci_high",
            "product_mention_query_min",
            "product_mention_query_max",
        ),
        (
            "placement_citation",
            "placement_citation_share",
            "placement_citation_ci_low",
            "placement_citation_ci_high",
            "placement_citation_query_min",
            "placement_citation_query_max",
        ),
    )
    for query_field, share_field, low_field, high_field, min_field, max_field in estimate_fields:
        estimates = [
            getattr(item, query_field) for item in snapshot.query_results_snapshot
        ]
        numerator = sum(item.numerator for item in estimates)
        denominator = sum(item.denominator for item in estimates)
        share = _share(numerator, denominator)
        low, high = wilson_interval(numerator, denominator)
        if (
            getattr(snapshot, share_field) != share
            or getattr(snapshot, low_field) != low
            or getattr(snapshot, high_field) != high
            or getattr(snapshot, min_field) != min(item.share for item in estimates)
            or getattr(snapshot, max_field) != max(item.share for item in estimates)
        ):
            raise ProjectExportRuleViolation(
                f"metric aggregate {query_field} estimate is inconsistent"
            )
    competitor_numerator = sum(
        item.competitor.numerator for item in snapshot.query_results_snapshot
    )
    competitor_denominator = sum(
        item.competitor.denominator for item in snapshot.query_results_snapshot
    )
    expected_delta = _quantize(
        snapshot.product_mention_share
        - _share(competitor_numerator, competitor_denominator)
    )
    if snapshot.competitive_delta != expected_delta:
        raise ProjectExportRuleViolation("metric competitive_delta is inconsistent")


def _validate_destination_coverage(snapshot: MetricSnapshotExportRecord) -> None:
    selected = set(snapshot.selected_destination_ids)
    qualified = set(snapshot.qualified_destination_ids)
    verified = set(snapshot.verified_destination_ids)
    qualified_coverage = _share(len(qualified), len(selected))
    verified_coverage = _share(len(verified & qualified), len(qualified))
    if (
        snapshot.qualified_destination_coverage != qualified_coverage
        or snapshot.verified_placement_coverage != verified_coverage
    ):
        raise ProjectExportRuleViolation("metric destination coverage is inconsistent")


def _destination_sets(snapshot: MetricSnapshotExportRecord) -> None:
    sets: dict[str, set[UUID]] = {}
    for name in (
        "selected_destination_ids",
        "qualified_destination_ids",
        "verified_destination_ids",
    ):
        values = getattr(snapshot, name)
        if not isinstance(values, tuple):
            raise ProjectExportRuleViolation(f"metric {name} must be a tuple")
        if len(set(values)) != len(values):
            raise ProjectExportRuleViolation(f"metric {name} must be unique")
        for value in values:
            uuid_value(value, f"metric {name}")
        sets[name] = set(values)
    if not sets["qualified_destination_ids"] <= sets["selected_destination_ids"]:
        raise ProjectExportRuleViolation("qualified destinations must be selected")
    if not sets["verified_destination_ids"] <= sets["qualified_destination_ids"]:
        raise ProjectExportRuleViolation("verified destinations must be qualified")


def _count_consistency(
    *, expected: int, sampled: int, valid: int, invalid: int, missing: int, label: str
) -> None:
    if sampled != valid + invalid or expected != sampled + missing:
        raise ProjectExportRuleViolation(f"{label} sample counts are inconsistent")


def _unique_reasons(
    values: tuple[InvalidReasonCountExportRecord, ...], label: str
) -> None:
    reasons = [item.reason for item in values]
    if len(set(reasons)) != len(reasons):
        raise ProjectExportRuleViolation(f"{label} must be unique")


def _validate_reason_counts(
    values: tuple[InvalidReasonCountExportRecord, ...],
    *,
    invalid_sample_count: int,
    label: str,
) -> None:
    if bool(values) != (invalid_sample_count > 0):
        raise ProjectExportRuleViolation(
            f"{label} must be empty exactly when invalid_sample_count is zero"
        )
    if any(item.count > invalid_sample_count for item in values):
        raise ProjectExportRuleViolation(f"{label} count exceeds invalid_sample_count")


def _unique_text(values: tuple[str, ...], label: str) -> None:
    for value in values:
        required_text(value, label)
    if len(set(values)) != len(values):
        raise ProjectExportRuleViolation(f"{label} must be unique")


def _signed_ratio(value: object, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ProjectExportRuleViolation(f"{label} must be a finite Decimal")
    if not Decimal("-1") <= value <= Decimal("1"):
        raise ProjectExportRuleViolation(f"{label} must be between -1 and 1")
    if value != _quantize(value):
        raise ProjectExportRuleViolation(f"{label} must be quantized to six places")


def _share(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0.000000")
    return _quantize(Decimal(numerator) / Decimal(denominator))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_UP)


def _canonical_hash(value: object) -> str:
    serialized = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
