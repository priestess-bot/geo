from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

import pytest

from geo_core.monitoring.domain import MonitoringRuleViolation
from geo_core.monitoring.statistics import classify_comparison, evaluate_comparison
from geo_core.monitoring.statistics_models import (
    ComparisonConclusion,
    ComparisonDecision,
    FrozenComparisonCriteria,
)


CRITERIA = FrozenComparisonCriteria(
    delta=Decimal("0.05"),
    power=Decimal("0.80"),
    precision=Decimal("0.04"),
    min_pairs=8,
    alpha=Decimal("0.05"),
    family="recommendation-primary",
)


@pytest.mark.parametrize(
    ("ci_low", "ci_high", "valid", "planned", "achieved_power", "expected"),
    (
        ("0.051", "0.200", 10, 10, "0.50", ComparisonConclusion.WIN),
        ("-0.200", "-0.051", 10, 10, "0.50", ComparisonConclusion.LOSS),
        ("-0.030", "0.030", 10, 10, "0.80", ComparisonConclusion.EQUIVALENT),
        ("-0.060", "0.060", 10, 10, "0.99", ComparisonConclusion.INCONCLUSIVE),
        ("0.040", "0.060", 10, 10, "0.99", ComparisonConclusion.INCONCLUSIVE),
        ("0.050", "0.100", 10, 10, "0.99", ComparisonConclusion.INCONCLUSIVE),
        ("-0.100", "-0.050", 10, 10, "0.99", ComparisonConclusion.INCONCLUSIVE),
        ("0.051", "0.200", 7, 7, "0.99", ComparisonConclusion.INSUFFICIENT_EVIDENCE),
        ("0.051", "0.200", 7, 10, "0.99", ComparisonConclusion.INSUFFICIENT_EVIDENCE),
    ),
)
def test_five_state_comparison_contract(
    ci_low: str,
    ci_high: str,
    valid: int,
    planned: int,
    achieved_power: str,
    expected: ComparisonConclusion,
) -> None:
    decision = evaluate_comparison(
        criteria=CRITERIA,
        adjusted_ci_low=Decimal(ci_low),
        adjusted_ci_high=Decimal(ci_high),
        valid_pair_count=valid,
        planned_pair_count=planned,
        achieved_power=Decimal(achieved_power),
    )

    assert decision.conclusion is expected
    assert (
        classify_comparison(
            criteria=CRITERIA,
            adjusted_ci_low=Decimal(ci_low),
            adjusted_ci_high=Decimal(ci_high),
            valid_pair_count=valid,
            planned_pair_count=planned,
            achieved_power=Decimal(achieved_power),
        )
        is expected
    )


@pytest.mark.parametrize("achieved_power", (Decimal("0.79"), None))
def test_equivalence_requires_frozen_power(achieved_power: Decimal | None) -> None:
    decision = evaluate_comparison(
        criteria=CRITERIA,
        adjusted_ci_low=Decimal("-0.03"),
        adjusted_ci_high=Decimal("0.03"),
        valid_pair_count=10,
        planned_pair_count=10,
        achieved_power=achieved_power,
    )

    assert decision.conclusion is ComparisonConclusion.INCONCLUSIVE
    assert decision.power_met is False


def test_equivalence_requires_frozen_precision() -> None:
    decision = evaluate_comparison(
        criteria=CRITERIA,
        adjusted_ci_low=Decimal("-0.05"),
        adjusted_ci_high=Decimal("0.05"),
        valid_pair_count=10,
        planned_pair_count=10,
        achieved_power=Decimal("0.90"),
    )

    assert decision.conclusion is ComparisonConclusion.INCONCLUSIVE
    assert decision.interval_half_width == Decimal("0.05")
    assert decision.precision_met is False
    assert (
        evaluate_comparison(
            criteria=replace(CRITERIA, precision=Decimal("0.05")),
            adjusted_ci_low=Decimal("-0.05"),
            adjusted_ci_high=Decimal("0.05"),
            valid_pair_count=10,
            planned_pair_count=10,
            achieved_power=Decimal("0.90"),
        ).conclusion
        is ComparisonConclusion.EQUIVALENT
    )


def test_exact_eighty_percent_completion_meets_the_frozen_gate() -> None:
    decision = evaluate_comparison(
        criteria=CRITERIA,
        adjusted_ci_low=Decimal("-0.03"),
        adjusted_ci_high=Decimal("0.03"),
        valid_pair_count=8,
        planned_pair_count=10,
        achieved_power=Decimal("0.80"),
    )

    assert decision.conclusion is ComparisonConclusion.EQUIVALENT
    assert decision.completion_ratio == Decimal("0.800000")
    assert decision.sample_size_met is True
    assert decision.completion_met is True


def test_criteria_and_decision_hashes_are_canonical_and_reproducible() -> None:
    equivalent_decimal_spelling = replace(
        CRITERIA,
        delta=Decimal("0.0500"),
        power=Decimal("0.800"),
        alpha=Decimal("0.050"),
    )
    changed_alpha = replace(CRITERIA, alpha=Decimal("0.01"))
    first = evaluate_comparison(
        criteria=CRITERIA,
        adjusted_ci_low=Decimal("-0.03"),
        adjusted_ci_high=Decimal("0.03"),
        valid_pair_count=10,
        planned_pair_count=10,
        achieved_power=Decimal("0.80"),
    )
    second = evaluate_comparison(
        criteria=equivalent_decimal_spelling,
        adjusted_ci_low=Decimal("-0.0300"),
        adjusted_ci_high=Decimal("0.0300"),
        valid_pair_count=10,
        planned_pair_count=10,
        achieved_power=Decimal("0.800"),
    )

    assert CRITERIA.canonical_hash() == equivalent_decimal_spelling.canonical_hash()
    assert CRITERIA.canonical_hash() != changed_alpha.canonical_hash()
    assert first.canonical_hash() == second.canonical_hash()
    criteria_value = first.canonical_value()["criteria"]
    assert isinstance(criteria_value, dict)
    assert criteria_value["correction_method"] == "holm"


@pytest.mark.parametrize(
    "changes",
    (
        {"conclusion": ComparisonConclusion.WIN},
        {"completion_ratio": Decimal("1")},
        {"interval_half_width": Decimal("0.01")},
        {"power_met": False},
    ),
)
def test_persisted_decision_cannot_claim_inconsistent_derived_values(
    changes: dict[str, object],
) -> None:
    decision = evaluate_comparison(
        criteria=CRITERIA,
        adjusted_ci_low=Decimal("-0.03"),
        adjusted_ci_high=Decimal("0.03"),
        valid_pair_count=8,
        planned_pair_count=10,
        achieved_power=Decimal("0.80"),
    )

    with pytest.raises(MonitoringRuleViolation):
        _replace_decision(decision, changes)


@pytest.mark.parametrize(
    "factory",
    (
        lambda: replace(CRITERIA, delta=Decimal("-0.01")),
        lambda: replace(CRITERIA, power=Decimal("0")),
        lambda: replace(CRITERIA, precision=Decimal("0")),
        lambda: replace(CRITERIA, min_pairs=0),
        lambda: replace(CRITERIA, alpha=Decimal("1")),
        lambda: replace(CRITERIA, family=" "),
        lambda: replace(CRITERIA, minimum_completion_ratio=Decimal("1.01")),
    ),
)
def test_invalid_frozen_criteria_are_rejected(
    factory: Callable[[], FrozenComparisonCriteria],
) -> None:
    with pytest.raises(MonitoringRuleViolation):
        factory()


@pytest.mark.parametrize(
    ("ci_low", "ci_high", "valid", "planned", "achieved_power"),
    (
        (Decimal("0.2"), Decimal("0.1"), 8, 10, Decimal("0.8")),
        (Decimal("0.1"), Decimal("0.2"), 11, 10, Decimal("0.8")),
        (Decimal("0.1"), Decimal("0.2"), 8, 10, Decimal("1.1")),
    ),
)
def test_invalid_comparison_evidence_is_rejected(
    ci_low: Decimal,
    ci_high: Decimal,
    valid: int,
    planned: int,
    achieved_power: Decimal,
) -> None:
    with pytest.raises(MonitoringRuleViolation):
        evaluate_comparison(
            criteria=CRITERIA,
            adjusted_ci_low=ci_low,
            adjusted_ci_high=ci_high,
            valid_pair_count=valid,
            planned_pair_count=planned,
            achieved_power=achieved_power,
        )


def _replace_decision(
    decision: ComparisonDecision, changes: dict[str, object]
) -> ComparisonDecision:
    if "conclusion" in changes:
        conclusion = changes["conclusion"]
        assert isinstance(conclusion, ComparisonConclusion)
        return replace(decision, conclusion=conclusion)
    if "completion_ratio" in changes:
        completion_ratio = changes["completion_ratio"]
        assert isinstance(completion_ratio, Decimal)
        return replace(decision, completion_ratio=completion_ratio)
    if "interval_half_width" in changes:
        interval_half_width = changes["interval_half_width"]
        assert isinstance(interval_half_width, Decimal)
        return replace(decision, interval_half_width=interval_half_width)
    power_met = changes["power_met"]
    assert isinstance(power_met, bool)
    return replace(decision, power_met=power_met)
