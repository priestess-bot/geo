"""Frozen five-state comparison decisions for monitoring metrics."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from geo_core.monitoring.domain import MonitoringRuleViolation
from geo_core.monitoring.statistics_models import (
    ComparisonConclusion,
    ComparisonDecision,
    FrozenComparisonCriteria,
)


SIX_PLACES = Decimal("0.000001")


def evaluate_comparison(
    *,
    criteria: FrozenComparisonCriteria,
    adjusted_ci_low: Decimal,
    adjusted_ci_high: Decimal,
    valid_pair_count: int,
    planned_pair_count: int,
    achieved_power: Decimal | None,
) -> ComparisonDecision:
    """Apply the frozen five-state decision contract to a corrected interval."""

    _validate_comparison_inputs(
        adjusted_ci_low=adjusted_ci_low,
        adjusted_ci_high=adjusted_ci_high,
        valid_pair_count=valid_pair_count,
        planned_pair_count=planned_pair_count,
        achieved_power=achieved_power,
    )
    completion_ratio = _ratio(valid_pair_count, planned_pair_count)
    interval_half_width = (adjusted_ci_high - adjusted_ci_low) / Decimal(2)
    sample_size_met = valid_pair_count >= criteria.min_pairs
    completion_met = (
        Decimal(valid_pair_count)
        >= criteria.minimum_completion_ratio * Decimal(planned_pair_count)
    )
    power_met = achieved_power is not None and achieved_power >= criteria.power
    precision_met = interval_half_width <= criteria.precision

    if not sample_size_met or not completion_met:
        conclusion = ComparisonConclusion.INSUFFICIENT_EVIDENCE
    elif adjusted_ci_low > criteria.delta:
        conclusion = ComparisonConclusion.WIN
    elif adjusted_ci_high < -criteria.delta:
        conclusion = ComparisonConclusion.LOSS
    elif (
        adjusted_ci_low >= -criteria.delta
        and adjusted_ci_high <= criteria.delta
        and power_met
        and precision_met
    ):
        conclusion = ComparisonConclusion.EQUIVALENT
    else:
        conclusion = ComparisonConclusion.INCONCLUSIVE

    return ComparisonDecision(
        conclusion=conclusion,
        adjusted_ci_low=adjusted_ci_low,
        adjusted_ci_high=adjusted_ci_high,
        valid_pair_count=valid_pair_count,
        planned_pair_count=planned_pair_count,
        completion_ratio=completion_ratio,
        interval_half_width=interval_half_width,
        achieved_power=achieved_power,
        sample_size_met=sample_size_met,
        completion_met=completion_met,
        power_met=power_met,
        precision_met=precision_met,
        criteria=criteria,
    )


def classify_comparison(
    *,
    criteria: FrozenComparisonCriteria,
    adjusted_ci_low: Decimal,
    adjusted_ci_high: Decimal,
    valid_pair_count: int,
    planned_pair_count: int,
    achieved_power: Decimal | None,
) -> ComparisonConclusion:
    return evaluate_comparison(
        criteria=criteria,
        adjusted_ci_low=adjusted_ci_low,
        adjusted_ci_high=adjusted_ci_high,
        valid_pair_count=valid_pair_count,
        planned_pair_count=planned_pair_count,
        achieved_power=achieved_power,
    ).conclusion


def _validate_comparison_inputs(
    *,
    adjusted_ci_low: Decimal,
    adjusted_ci_high: Decimal,
    valid_pair_count: int,
    planned_pair_count: int,
    achieved_power: Decimal | None,
) -> None:
    for value, label in (
        (adjusted_ci_low, "comparison adjusted interval lower bound"),
        (adjusted_ci_high, "comparison adjusted interval upper bound"),
    ):
        if not isinstance(value, Decimal) or not value.is_finite():
            raise MonitoringRuleViolation(f"{label} must be a finite Decimal")
    if adjusted_ci_low > adjusted_ci_high:
        raise MonitoringRuleViolation("comparison adjusted interval is reversed")
    if (
        not isinstance(valid_pair_count, int)
        or isinstance(valid_pair_count, bool)
        or not isinstance(planned_pair_count, int)
        or isinstance(planned_pair_count, bool)
        or not 0 <= valid_pair_count <= planned_pair_count
        or planned_pair_count < 1
    ):
        raise MonitoringRuleViolation("comparison pair counts are inconsistent")
    if achieved_power is not None and (
        not isinstance(achieved_power, Decimal)
        or not achieved_power.is_finite()
        or not Decimal(0) <= achieved_power <= Decimal(1)
    ):
        raise MonitoringRuleViolation("comparison achieved power must be in [0, 1]")


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0.000000")
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        SIX_PLACES, rounding=ROUND_HALF_UP
    )
