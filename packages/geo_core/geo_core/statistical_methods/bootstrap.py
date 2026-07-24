"""Deterministic paired percentile bootstrap with frozen hash-derived seed."""

from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
import random

from geo_core.statistical_methods.contracts import (
    BootstrapEstimate,
    PairedObservation,
    StatisticalInterval,
    StatisticalRuleViolation,
    canonical_hash,
    decimal_value,
)


TWELVE_PLACES = Decimal("0.000000000001")


def paired_bootstrap(
    pairs: tuple[PairedObservation, ...],
    *,
    seed_hex: str,
    iterations: int,
    alpha: Decimal,
    method: str = "paired-bootstrap-percentile-v1",
) -> BootstrapEstimate:
    if not pairs:
        raise StatisticalRuleViolation("paired bootstrap requires at least one valid pair")
    if iterations < 100:
        raise StatisticalRuleViolation("paired bootstrap requires at least 100 iterations")
    if len(seed_hex) != 64 or any(item not in "0123456789abcdef" for item in seed_hex):
        raise StatisticalRuleViolation("paired bootstrap seed must be SHA-256")
    if (
        not isinstance(alpha, Decimal)
        or not alpha.is_finite()
        or not Decimal(0) < alpha < Decimal(1)
    ):
        raise StatisticalRuleViolation("paired bootstrap alpha must be in (0, 1)")
    ordered = tuple(sorted(pairs))
    deltas = tuple(item.delta for item in ordered)
    point = sum(deltas, Decimal(0)) / Decimal(len(deltas))
    rng = random.Random(int(seed_hex, 16))
    distribution = [
        sum((deltas[rng.randrange(len(deltas))] for _ in deltas), Decimal(0)) / Decimal(len(deltas))
        for _ in range(iterations)
    ]
    distribution.sort()
    low = _percentile(distribution, alpha / Decimal(2))
    high = _percentile(distribution, Decimal(1) - alpha / Decimal(2))
    less_or_equal_zero = sum(value <= 0 for value in distribution)
    greater_or_equal_zero = sum(value >= 0 for value in distribution)
    tail_count = min(less_or_equal_zero, greater_or_equal_zero)
    p_value = min(
        Decimal(1),
        Decimal(2 * (tail_count + 1)) / Decimal(iterations + 1),
    )
    distribution_hash = canonical_hash([decimal_value(value) for value in distribution])
    return BootstrapEstimate(
        point_estimate=_quantize(point),
        interval=StatisticalInterval(
            method=method,
            alpha=alpha,
            low=_quantize(low),
            high=_quantize(high),
        ),
        two_sided_p_value=_quantize(p_value),
        seed_hex=seed_hex,
        iterations=iterations,
        distribution_hash=distribution_hash,
    )


def _percentile(values: list[Decimal], probability: Decimal) -> Decimal:
    position = probability * Decimal(len(values) - 1)
    lower_index = int(position.to_integral_value(rounding=ROUND_FLOOR))
    upper_index = min(lower_index + 1, len(values) - 1)
    fraction = position - Decimal(lower_index)
    return values[lower_index] + (values[upper_index] - values[lower_index]) * fraction


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWELVE_PLACES, rounding=ROUND_HALF_UP)
