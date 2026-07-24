"""Frozen five-state practical-effect decision contract."""

from __future__ import annotations

from decimal import Decimal

from geo_core.statistical_methods.contracts import (
    ComparisonConclusion,
    ComparisonInput,
    StatisticalInterval,
)


def decide_comparison(
    comparison: ComparisonInput,
    *,
    adjusted_interval: StatisticalInterval,
) -> ComparisonConclusion:
    protocol = comparison.protocol
    valid_count = len(comparison.pairs)
    completion_met = Decimal(valid_count) >= protocol.minimum_completion_ratio * Decimal(
        comparison.planned_pair_count
    )
    if valid_count < protocol.min_pairs or not completion_met:
        return ComparisonConclusion.INSUFFICIENT_EVIDENCE
    if adjusted_interval.low > protocol.delta:
        return ComparisonConclusion.WIN
    if adjusted_interval.high < -protocol.delta:
        return ComparisonConclusion.LOSS
    power_met = protocol.a_priori_design_power >= protocol.target_power
    precision_met = adjusted_interval.half_width <= protocol.precision
    if (
        adjusted_interval.low >= -protocol.delta
        and adjusted_interval.high <= protocol.delta
        and power_met
        and precision_met
    ):
        return ComparisonConclusion.EQUIVALENT
    return ComparisonConclusion.INCONCLUSIVE
