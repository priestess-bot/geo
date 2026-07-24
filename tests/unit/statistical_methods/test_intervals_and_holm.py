from __future__ import annotations

from decimal import Decimal

import pytest

from geo_core.statistical_methods import (
    StatisticalRuleViolation,
    holm_adjust,
    newcombe_difference_interval,
    wilson_interval,
)


def test_wilson_95_interval_matches_frozen_golden_values() -> None:
    interval = wilson_interval(5, 10)

    assert interval.method == "wilson-score-v1"
    assert interval.alpha == Decimal("0.05")
    assert interval.low == Decimal("0.236593090513")
    assert interval.high == Decimal("0.763406909487")
    assert wilson_interval(0, 10).high == Decimal("0.277532799863")
    assert wilson_interval(10, 10).low == Decimal("0.722467200137")


def test_newcombe_difference_is_candidate_minus_baseline_golden() -> None:
    interval = newcombe_difference_interval(6, 10, 3, 10)

    assert interval.method == "newcombe-score-difference-v1"
    assert interval.low == Decimal("-0.117731797277")
    assert interval.high == Decimal("0.601138766054")


def test_newcombe_difference_is_antisymmetric_when_groups_are_swapped() -> None:
    candidate_minus_baseline = newcombe_difference_interval(8, 17, 4, 13)
    baseline_minus_candidate = newcombe_difference_interval(4, 13, 8, 17)

    assert candidate_minus_baseline.low == -baseline_minus_candidate.high
    assert candidate_minus_baseline.high == -baseline_minus_candidate.low


def test_newcombe_difference_requires_two_observed_samples() -> None:
    with pytest.raises(StatisticalRuleViolation, match="two non-empty samples"):
        newcombe_difference_interval(0, 0, 3, 10)


@pytest.mark.parametrize((("successes", "total")), ((-1, 10), (11, 10), (1, 0)))
def test_invalid_proportion_counts_are_rejected(successes: int, total: int) -> None:
    with pytest.raises(StatisticalRuleViolation):
        wilson_interval(successes, total)


def test_holm_step_down_adjustment_and_stop_rule_are_golden() -> None:
    adjustments = holm_adjust(
        {
            "comparison-a": Decimal("0.01"),
            "comparison-b": Decimal("0.04"),
            "comparison-c": Decimal("0.03"),
        },
        family_alpha=Decimal("0.05"),
    )
    by_id = {item.comparison_id: item for item in adjustments}

    assert [item.comparison_id for item in adjustments] == [
        "comparison-a",
        "comparison-c",
        "comparison-b",
    ]
    assert by_id["comparison-a"].adjusted_p_value == Decimal("0.030000000000")
    assert by_id["comparison-a"].local_alpha == Decimal("0.016666666667")
    assert by_id["comparison-a"].rejected is True
    assert by_id["comparison-c"].adjusted_p_value == Decimal("0.060000000000")
    assert by_id["comparison-c"].rejected is False
    assert by_id["comparison-b"].adjusted_p_value == Decimal("0.060000000000")
    assert by_id["comparison-b"].rejected is False


def test_holm_ties_are_ordered_by_stable_comparison_identity() -> None:
    first = holm_adjust(
        {"z": Decimal("0.02"), "a": Decimal("0.02")},
        family_alpha=Decimal("0.05"),
    )
    second = holm_adjust(
        {"a": Decimal("0.02"), "z": Decimal("0.02")},
        family_alpha=Decimal("0.05"),
    )

    assert first == second
    assert [item.comparison_id for item in first] == ["a", "z"]
