"""Deterministic Holm family-wise multiple-comparison correction."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_UP

from geo_core.statistical_methods.contracts import (
    HolmAdjustment,
    StatisticalRuleViolation,
)


TWELVE_PLACES = Decimal("0.000000000001")


def holm_adjust(
    p_values: Mapping[str, Decimal],
    *,
    family_alpha: Decimal,
) -> tuple[HolmAdjustment, ...]:
    if not p_values:
        raise StatisticalRuleViolation("Holm correction requires a non-empty family")
    if (
        not isinstance(family_alpha, Decimal)
        or not family_alpha.is_finite()
        or not (Decimal(0) < family_alpha < Decimal(1))
    ):
        raise StatisticalRuleViolation("Holm family alpha must be in (0, 1)")
    normalized: list[tuple[str, Decimal]] = []
    for raw_id, p_value in p_values.items():
        comparison_id = raw_id.strip().lower()
        if not comparison_id or not isinstance(p_value, Decimal) or not p_value.is_finite():
            raise StatisticalRuleViolation("Holm comparison identity and p-value are required")
        if not Decimal(0) <= p_value <= Decimal(1):
            raise StatisticalRuleViolation("Holm p-values must be in [0, 1]")
        normalized.append((comparison_id, p_value))
    if len({item[0] for item in normalized}) != len(normalized):
        raise StatisticalRuleViolation("Holm comparison ids must be unique")
    ordered = sorted(normalized, key=lambda item: (item[1], item[0]))
    family_size = len(ordered)
    prior_adjusted = Decimal(0)
    continue_rejecting = True
    results: list[HolmAdjustment] = []
    for index, (comparison_id, p_value) in enumerate(ordered, start=1):
        remaining = family_size - index + 1
        local_alpha = family_alpha / Decimal(remaining)
        adjusted = min(Decimal(1), max(prior_adjusted, Decimal(remaining) * p_value))
        rejected = continue_rejecting and p_value <= local_alpha
        if not rejected:
            continue_rejecting = False
        results.append(
            HolmAdjustment(
                comparison_id=comparison_id,
                rank=index,
                raw_p_value=_quantize(p_value),
                adjusted_p_value=_quantize(adjusted),
                local_alpha=_quantize(local_alpha),
                rejected=rejected,
            )
        )
        prior_adjusted = adjusted
    return tuple(results)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWELVE_PLACES, rounding=ROUND_HALF_UP)
