"""Immutable statistics-v2 result models and canonical projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from uuid import UUID

from geo_core.monitoring.domain import (
    LEGACY_STATISTICS_CONTRACT_VERSION,
    METRIC_METHOD_VERSION,
    OBSERVATION_MEMBERSHIP_VERSION,
    SHA256_PATTERN,
    STATISTICS_CONTRACT_VERSION,
    MeasurementWindow,
    MonitoringRuleViolation,
    canonical_hash,
)
from geo_core.monitoring.source_contract import SourceStratumKey


ReasonCounts = tuple[tuple[str, int], ...]


class ComparisonConclusion(StrEnum):
    """Allowed terminal conclusions for a frozen metric comparison."""

    WIN = "win"
    EQUIVALENT = "equivalent"
    LOSS = "loss"
    INCONCLUSIVE = "inconclusive"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class FrozenComparisonCriteria:
    """Decision thresholds frozen before any comparison observations are inspected."""

    delta: Decimal
    power: Decimal
    precision: Decimal
    min_pairs: int
    alpha: Decimal
    family: str
    correction_method: str = "holm"
    minimum_completion_ratio: Decimal = Decimal("0.80")

    def __post_init__(self) -> None:
        _require_finite_decimal(self.delta, "comparison delta")
        _require_finite_decimal(self.power, "comparison power")
        _require_finite_decimal(self.precision, "comparison precision")
        _require_finite_decimal(self.alpha, "comparison alpha")
        _require_finite_decimal(
            self.minimum_completion_ratio, "comparison minimum completion ratio"
        )
        if self.delta < 0:
            raise MonitoringRuleViolation("comparison delta must be non-negative")
        if not Decimal(0) < self.power <= Decimal(1):
            raise MonitoringRuleViolation("comparison power must be in (0, 1]")
        if self.precision <= 0:
            raise MonitoringRuleViolation("comparison precision must be positive")
        if not isinstance(self.min_pairs, int) or isinstance(self.min_pairs, bool) or self.min_pairs < 1:
            raise MonitoringRuleViolation("comparison min_pairs must be a positive integer")
        if not Decimal(0) < self.alpha < Decimal(1):
            raise MonitoringRuleViolation("comparison alpha must be in (0, 1)")
        if not Decimal(0) < self.minimum_completion_ratio <= Decimal(1):
            raise MonitoringRuleViolation(
                "comparison minimum completion ratio must be in (0, 1]"
            )
        if not self.family.strip():
            raise MonitoringRuleViolation("comparison family is required")
        if not self.correction_method.strip():
            raise MonitoringRuleViolation("comparison correction method is required")

    @property
    def target_power(self) -> Decimal:
        return self.power

    @property
    def maximum_interval_half_width(self) -> Decimal:
        return self.precision

    @property
    def minimum_valid_pairs(self) -> int:
        return self.min_pairs

    def canonical_value(self) -> dict[str, object]:
        return {
            "delta": _canonical_decimal(self.delta),
            "power": _canonical_decimal(self.power),
            "precision": _canonical_decimal(self.precision),
            "min_pairs": self.min_pairs,
            "alpha": _canonical_decimal(self.alpha),
            "family": self.family.strip(),
            "correction_method": self.correction_method.strip().lower(),
            "minimum_completion_ratio": _canonical_decimal(self.minimum_completion_ratio),
        }

    def canonical_hash(self) -> str:
        return canonical_hash(self.canonical_value())


@dataclass(frozen=True)
class ComparisonDecision:
    """Auditable outcome derived from an adjusted interval and frozen criteria."""

    conclusion: ComparisonConclusion
    adjusted_ci_low: Decimal
    adjusted_ci_high: Decimal
    valid_pair_count: int
    planned_pair_count: int
    completion_ratio: Decimal
    interval_half_width: Decimal
    achieved_power: Decimal | None
    sample_size_met: bool
    completion_met: bool
    power_met: bool
    precision_met: bool
    criteria: FrozenComparisonCriteria

    def __post_init__(self) -> None:
        if not isinstance(self.conclusion, ComparisonConclusion):
            raise MonitoringRuleViolation("comparison conclusion is invalid")
        if not isinstance(self.criteria, FrozenComparisonCriteria):
            raise MonitoringRuleViolation("comparison criteria are invalid")
        for value, label in (
            (self.adjusted_ci_low, "comparison adjusted interval lower bound"),
            (self.adjusted_ci_high, "comparison adjusted interval upper bound"),
            (self.completion_ratio, "comparison completion ratio"),
            (self.interval_half_width, "comparison interval half-width"),
        ):
            _require_finite_decimal(value, label)
        if self.achieved_power is not None:
            _require_finite_decimal(self.achieved_power, "comparison achieved power")
            if not Decimal(0) <= self.achieved_power <= Decimal(1):
                raise MonitoringRuleViolation("comparison achieved power must be in [0, 1]")
        if self.adjusted_ci_low > self.adjusted_ci_high:
            raise MonitoringRuleViolation("comparison adjusted interval is reversed")
        if (
            not isinstance(self.valid_pair_count, int)
            or isinstance(self.valid_pair_count, bool)
            or not isinstance(self.planned_pair_count, int)
            or isinstance(self.planned_pair_count, bool)
            or not 0 <= self.valid_pair_count <= self.planned_pair_count
            or self.planned_pair_count < 1
        ):
            raise MonitoringRuleViolation("comparison pair counts are inconsistent")
        expected_completion_ratio = (
            Decimal(self.valid_pair_count) / Decimal(self.planned_pair_count)
        ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        expected_half_width = (self.adjusted_ci_high - self.adjusted_ci_low) / Decimal(2)
        expected_sample_size_met = self.valid_pair_count >= self.criteria.min_pairs
        expected_completion_met = (
            Decimal(self.valid_pair_count)
            >= self.criteria.minimum_completion_ratio * Decimal(self.planned_pair_count)
        )
        expected_power_met = (
            self.achieved_power is not None and self.achieved_power >= self.criteria.power
        )
        expected_precision_met = expected_half_width <= self.criteria.precision
        derived_values = (
            self.completion_ratio == expected_completion_ratio,
            self.interval_half_width == expected_half_width,
            self.sample_size_met is expected_sample_size_met,
            self.completion_met is expected_completion_met,
            self.power_met is expected_power_met,
            self.precision_met is expected_precision_met,
        )
        if not all(derived_values):
            raise MonitoringRuleViolation("comparison decision fields are inconsistent")
        expected_conclusion = _comparison_conclusion(
            criteria=self.criteria,
            adjusted_ci_low=self.adjusted_ci_low,
            adjusted_ci_high=self.adjusted_ci_high,
            sample_size_met=expected_sample_size_met,
            completion_met=expected_completion_met,
            power_met=expected_power_met,
            precision_met=expected_precision_met,
        )
        if self.conclusion is not expected_conclusion:
            raise MonitoringRuleViolation("comparison conclusion is inconsistent")

    def canonical_value(self) -> dict[str, object]:
        return {
            "conclusion": self.conclusion.value,
            "adjusted_ci_low": _canonical_decimal(self.adjusted_ci_low),
            "adjusted_ci_high": _canonical_decimal(self.adjusted_ci_high),
            "valid_pair_count": self.valid_pair_count,
            "planned_pair_count": self.planned_pair_count,
            "completion_ratio": _canonical_decimal(self.completion_ratio),
            "interval_half_width": _canonical_decimal(self.interval_half_width),
            "achieved_power": (
                _canonical_decimal(self.achieved_power)
                if self.achieved_power is not None
                else None
            ),
            "sample_size_met": self.sample_size_met,
            "completion_met": self.completion_met,
            "power_met": self.power_met,
            "precision_met": self.precision_met,
            "criteria": self.criteria.canonical_value(),
            "criteria_hash": self.criteria.canonical_hash(),
        }

    def canonical_hash(self) -> str:
        return canonical_hash(self.canonical_value())


@dataclass(frozen=True)
class BinaryEstimate:
    numerator: int
    denominator: int
    share: Decimal
    ci_low: Decimal
    ci_high: Decimal

    def __post_init__(self) -> None:
        if not 0 <= self.numerator <= self.denominator:
            raise MonitoringRuleViolation("binary estimate counts are inconsistent")
        if not (
            Decimal(0) <= self.share <= Decimal(1)
            and Decimal(0) <= self.ci_low <= self.ci_high <= Decimal(1)
        ):
            raise MonitoringRuleViolation("binary estimate values are outside [0, 1]")

    def canonical_value(self) -> dict[str, object]:
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "share": float(self.share),
            "ci_low": float(self.ci_low),
            "ci_high": float(self.ci_high),
        }


@dataclass(frozen=True)
class QueryMetricResult:
    monitoring_query_id: UUID
    query_text_snapshot: str
    query_cluster_key: str
    expected_sample_count: int
    sampled_sample_count: int
    valid_sample_count: int
    invalid_sample_count: int
    missing_sample_count: int
    meets_threshold: bool
    invalid_reason_counts: ReasonCounts
    confounding_factors: tuple[str, ...]
    recommendation: BinaryEstimate
    product_mention: BinaryEstimate
    placement_citation: BinaryEstimate
    competitor: BinaryEstimate
    competitive_delta: Decimal

    def __post_init__(self) -> None:
        if self.expected_sample_count < 1:
            raise MonitoringRuleViolation("query result requires a frozen denominator")
        if (
            self.valid_sample_count + self.invalid_sample_count != self.sampled_sample_count
            or self.sampled_sample_count + self.missing_sample_count != self.expected_sample_count
        ):
            raise MonitoringRuleViolation("query sample counts are inconsistent")
        if any(count < 1 for _, count in self.invalid_reason_counts):
            raise MonitoringRuleViolation("invalid reason counts must be positive")
        if (self.invalid_sample_count == 0) != (not self.invalid_reason_counts):
            raise MonitoringRuleViolation(
                "invalid query samples and reason counts must be present together"
            )
        if not Decimal(-1) <= self.competitive_delta <= Decimal(1):
            raise MonitoringRuleViolation("query competitive delta is outside [-1, 1]")

    def canonical_value(self) -> dict[str, object]:
        return {
            "monitoring_query_id": str(self.monitoring_query_id),
            "query_text_snapshot": self.query_text_snapshot,
            "query_cluster_key": self.query_cluster_key,
            "expected_sample_count": self.expected_sample_count,
            "sampled_sample_count": self.sampled_sample_count,
            "valid_sample_count": self.valid_sample_count,
            "invalid_sample_count": self.invalid_sample_count,
            "missing_sample_count": self.missing_sample_count,
            "meets_threshold": self.meets_threshold,
            "invalid_reason_counts": dict(self.invalid_reason_counts),
            "confounding_factors": list(self.confounding_factors),
            "recommendation": self.recommendation.canonical_value(),
            "product_mention": self.product_mention.canonical_value(),
            "placement_citation": self.placement_citation.canonical_value(),
            "competitor": self.competitor.canonical_value(),
            "competitive_delta": float(self.competitive_delta),
        }


@dataclass(frozen=True)
class MetricSnapshot:
    id: UUID
    project_id: UUID
    protocol_id: UUID
    campaign_id: UUID
    measurement_window: MeasurementWindow
    source_stratum: SourceStratumKey | None
    source_stratum_hash: str | None
    expected_sample_count: int
    eligible_sample_count: int
    recommendation_share: Decimal
    product_mention_share: Decimal
    placement_citation_share: Decimal
    qualified_destination_coverage: Decimal
    verified_placement_coverage: Decimal
    competitive_delta: Decimal
    status: str
    confounded_reasons: tuple[str, ...]
    input_hash: str
    method_version: str
    computed_at: datetime
    statistics_contract_version: str = LEGACY_STATISTICS_CONTRACT_VERSION
    query_cluster_key: str | None = None
    analysis_stratum_hash: str | None = None
    minimum_valid_repeats: int | None = None
    sampled_sample_count: int | None = None
    invalid_sample_count: int | None = None
    missing_sample_count: int | None = None
    sampling_completion_ratio: Decimal | None = None
    valid_completion_ratio: Decimal | None = None
    query_count: int | None = None
    sufficient_query_count: int | None = None
    invalid_reason_counts: ReasonCounts = ()
    declared_confounding_factors: tuple[str, ...] = ()
    query_results: tuple[QueryMetricResult, ...] = ()
    recommendation_ci_low: Decimal | None = None
    recommendation_ci_high: Decimal | None = None
    product_mention_ci_low: Decimal | None = None
    product_mention_ci_high: Decimal | None = None
    placement_citation_ci_low: Decimal | None = None
    placement_citation_ci_high: Decimal | None = None
    recommendation_query_min: Decimal | None = None
    recommendation_query_max: Decimal | None = None
    product_mention_query_min: Decimal | None = None
    product_mention_query_max: Decimal | None = None
    placement_citation_query_min: Decimal | None = None
    placement_citation_query_max: Decimal | None = None
    worst_query_id: UUID | None = None
    selected_destination_ids: tuple[UUID, ...] = ()
    qualified_destination_ids: tuple[UUID, ...] = ()
    verified_destination_ids: tuple[UUID, ...] = ()
    result_hash: str | None = None
    observation_membership_version: str | None = None
    observation_membership_hash: str | None = None
    observation_membership_count: int | None = None

    def __post_init__(self) -> None:
        if self.statistics_contract_version == LEGACY_STATISTICS_CONTRACT_VERSION:
            return
        if self.statistics_contract_version != STATISTICS_CONTRACT_VERSION:
            raise MonitoringRuleViolation("metric statistics contract is unsupported")
        required = (
            self.query_cluster_key,
            self.analysis_stratum_hash,
            self.minimum_valid_repeats,
            self.sampled_sample_count,
            self.invalid_sample_count,
            self.missing_sample_count,
            self.sampling_completion_ratio,
            self.valid_completion_ratio,
            self.query_count,
            self.sufficient_query_count,
        )
        if any(value is None for value in required) or self.source_stratum is None:
            raise MonitoringRuleViolation("statistics-v2 metric fields are incomplete")
        if self.method_version != METRIC_METHOD_VERSION:
            raise MonitoringRuleViolation("metric method version does not match statistics-v2")
        if self.status not in {"complete", "confounded", "insufficient_evidence"}:
            raise MonitoringRuleViolation("metric status is invalid")
        query_reason_counts: dict[str, int] = {}
        for query in self.query_results:
            for reason, count in query.invalid_reason_counts:
                query_reason_counts[reason] = query_reason_counts.get(reason, 0) + count
        if tuple(sorted(query_reason_counts.items())) != self.invalid_reason_counts:
            raise MonitoringRuleViolation("metric invalid reasons do not match per-query results")
        if (self.invalid_sample_count == 0) != (not self.invalid_reason_counts):
            raise MonitoringRuleViolation(
                "invalid metric samples and reason counts must be present together"
            )
        if self.result_hash is not None and self.result_hash != canonical_hash(self.result_value()):
            raise MonitoringRuleViolation("metric result hash does not match its output")
        membership_values = (
            self.observation_membership_version,
            self.observation_membership_hash,
            self.observation_membership_count,
        )
        if any(value is not None for value in membership_values) and any(
            value is None for value in membership_values
        ):
            raise MonitoringRuleViolation("metric observation membership is incomplete")
        if self.observation_membership_version is not None:
            if self.observation_membership_version != OBSERVATION_MEMBERSHIP_VERSION:
                raise MonitoringRuleViolation(
                    "metric observation membership version is unsupported"
                )
            if not SHA256_PATTERN.fullmatch(self.observation_membership_hash or ""):
                raise MonitoringRuleViolation(
                    "metric observation membership hash must be lowercase SHA-256"
                )
            if (
                self.observation_membership_count is None
                or self.observation_membership_count < 0
                or self.observation_membership_count != self.sampled_sample_count
            ):
                raise MonitoringRuleViolation("metric observation membership count is inconsistent")

    def result_value(self) -> dict[str, object]:
        value: dict[str, object] = {
            "statistics_contract_version": self.statistics_contract_version,
            "method_version": self.method_version,
            "input_hash": self.input_hash,
            "source_stratum": (
                self.source_stratum.canonical_value() if self.source_stratum else None
            ),
            "source_stratum_hash": self.source_stratum_hash,
            "query_cluster_key": self.query_cluster_key,
            "analysis_stratum_hash": self.analysis_stratum_hash,
            "measurement_window": self.measurement_window.value,
            "minimum_valid_repeats": self.minimum_valid_repeats,
            "expected_sample_count": self.expected_sample_count,
            "sampled_sample_count": self.sampled_sample_count,
            "eligible_sample_count": self.eligible_sample_count,
            "invalid_sample_count": self.invalid_sample_count,
            "missing_sample_count": self.missing_sample_count,
            "sampling_completion_ratio": _number(self.sampling_completion_ratio),
            "valid_completion_ratio": _number(self.valid_completion_ratio),
            "query_count": self.query_count,
            "sufficient_query_count": self.sufficient_query_count,
            "invalid_reason_counts": dict(self.invalid_reason_counts),
            "declared_confounding_factors": list(self.declared_confounding_factors),
            "query_results": [item.canonical_value() for item in self.query_results],
            "recommendation_share": float(self.recommendation_share),
            "recommendation_ci_low": _number(self.recommendation_ci_low),
            "recommendation_ci_high": _number(self.recommendation_ci_high),
            "product_mention_share": float(self.product_mention_share),
            "product_mention_ci_low": _number(self.product_mention_ci_low),
            "product_mention_ci_high": _number(self.product_mention_ci_high),
            "placement_citation_share": float(self.placement_citation_share),
            "placement_citation_ci_low": _number(self.placement_citation_ci_low),
            "placement_citation_ci_high": _number(self.placement_citation_ci_high),
            "recommendation_query_min": _number(self.recommendation_query_min),
            "recommendation_query_max": _number(self.recommendation_query_max),
            "product_mention_query_min": _number(self.product_mention_query_min),
            "product_mention_query_max": _number(self.product_mention_query_max),
            "placement_citation_query_min": _number(self.placement_citation_query_min),
            "placement_citation_query_max": _number(self.placement_citation_query_max),
            "qualified_destination_coverage": float(self.qualified_destination_coverage),
            "verified_placement_coverage": float(self.verified_placement_coverage),
            "competitive_delta": float(self.competitive_delta),
            "worst_query_id": str(self.worst_query_id) if self.worst_query_id else None,
            "selected_destination_ids": list(map(str, self.selected_destination_ids)),
            "qualified_destination_ids": list(map(str, self.qualified_destination_ids)),
            "verified_destination_ids": list(map(str, self.verified_destination_ids)),
            "status": self.status,
            "confounded_reasons": list(self.confounded_reasons),
        }
        if self.observation_membership_version is not None:
            value.update(
                {
                    "observation_membership_version": self.observation_membership_version,
                    "observation_membership_hash": self.observation_membership_hash,
                    "observation_membership_count": self.observation_membership_count,
                }
            )
        return value


def analysis_stratum_hash(source_stratum_hash: str, query_cluster_key: str) -> str:
    return canonical_hash(
        {
            "query_cluster_key": query_cluster_key,
            "source_stratum_hash": source_stratum_hash,
        }
    )


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _require_finite_decimal(value: object, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise MonitoringRuleViolation(f"{label} must be a finite Decimal")


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _comparison_conclusion(
    *,
    criteria: FrozenComparisonCriteria,
    adjusted_ci_low: Decimal,
    adjusted_ci_high: Decimal,
    sample_size_met: bool,
    completion_met: bool,
    power_met: bool,
    precision_met: bool,
) -> ComparisonConclusion:
    if not sample_size_met or not completion_met:
        return ComparisonConclusion.INSUFFICIENT_EVIDENCE
    if adjusted_ci_low > criteria.delta:
        return ComparisonConclusion.WIN
    if adjusted_ci_high < -criteria.delta:
        return ComparisonConclusion.LOSS
    if (
        adjusted_ci_low >= -criteria.delta
        and adjusted_ci_high <= criteria.delta
        and power_met
        and precision_met
    ):
        return ComparisonConclusion.EQUIVALENT
    return ComparisonConclusion.INCONCLUSIVE
