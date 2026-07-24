"""Wilson single-proportion and Newcombe score-difference intervals."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from statistics import NormalDist

from geo_core.statistical_methods.contracts import (
    StatisticalInterval,
    StatisticalRuleViolation,
)


TWELVE_PLACES = Decimal("0.000000000001")


def wilson_interval(
    successes: int,
    total: int,
    *,
    alpha: Decimal = Decimal("0.05"),
) -> StatisticalInterval:
    _counts(successes, total)
    _alpha(alpha)
    if total == 0:
        return StatisticalInterval(
            method="wilson-score-v1",
            alpha=alpha,
            low=Decimal(0),
            high=Decimal(1),
        )
    n = Decimal(total)
    share = Decimal(successes) / n
    z = _z(alpha)
    z_squared = z * z
    adjustment = Decimal(1) + z_squared / n
    center = (share + z_squared / (Decimal(2) * n)) / adjustment
    margin = (
        z
        * (share * (Decimal(1) - share) / n + z_squared / (Decimal(4) * n * n)).sqrt()
        / adjustment
    )
    return StatisticalInterval(
        method="wilson-score-v1",
        alpha=alpha,
        low=_quantize(max(Decimal(0), center - margin)),
        high=_quantize(min(Decimal(1), center + margin)),
    )


def newcombe_difference_interval(
    candidate_successes: int,
    candidate_total: int,
    baseline_successes: int,
    baseline_total: int,
    *,
    alpha: Decimal = Decimal("0.05"),
) -> StatisticalInterval:
    """Newcombe method 10 interval for candidate minus baseline proportions."""

    _counts(candidate_successes, candidate_total)
    _counts(baseline_successes, baseline_total)
    if candidate_total == 0 or baseline_total == 0:
        raise StatisticalRuleViolation(
            "Newcombe difference intervals require two non-empty samples"
        )
    candidate = wilson_interval(candidate_successes, candidate_total, alpha=alpha)
    baseline = wilson_interval(baseline_successes, baseline_total, alpha=alpha)
    candidate_share = Decimal(candidate_successes) / Decimal(candidate_total)
    baseline_share = Decimal(baseline_successes) / Decimal(baseline_total)
    difference = candidate_share - baseline_share

    # Newcombe's method 10 combines the Wilson score distances in quadrature.
    # Directly subtracting the two interval endpoints is a different, more
    # conservative construction and must not be labelled as method 10.
    lower_margin = (
        (candidate_share - candidate.low) ** 2 + (baseline.high - baseline_share) ** 2
    ).sqrt()
    upper_margin = (
        (candidate.high - candidate_share) ** 2 + (baseline_share - baseline.low) ** 2
    ).sqrt()
    return StatisticalInterval(
        method="newcombe-score-difference-v1",
        alpha=alpha,
        low=_quantize(max(Decimal(-1), difference - lower_margin)),
        high=_quantize(min(Decimal(1), difference + upper_margin)),
    )


def _z(alpha: Decimal) -> Decimal:
    return Decimal(str(NormalDist().inv_cdf(float(Decimal(1) - alpha / Decimal(2)))))


def _counts(successes: int, total: int) -> None:
    if (
        not isinstance(successes, int)
        or isinstance(successes, bool)
        or not isinstance(total, int)
        or isinstance(total, bool)
        or not 0 <= successes <= total
    ):
        raise StatisticalRuleViolation("proportion counts are inconsistent")


def _alpha(alpha: Decimal) -> None:
    if (
        not isinstance(alpha, Decimal)
        or not alpha.is_finite()
        or not Decimal(0) < alpha < Decimal(1)
    ):
        raise StatisticalRuleViolation("interval alpha must be a finite Decimal in (0, 1)")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWELVE_PLACES, rounding=ROUND_HALF_UP)
