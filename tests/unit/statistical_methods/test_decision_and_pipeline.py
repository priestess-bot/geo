from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

import pytest

from geo_core.statistical_methods import (
    ComparisonConclusion,
    ComparisonInput,
    FrozenComparisonProtocol,
    StatisticalInterval,
    StatisticalRuleViolation,
    analyze_comparison_family,
    decide_comparison,
    holm_adjust,
)


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    (
        ("0.051", "0.20", ComparisonConclusion.WIN),
        ("-0.20", "-0.051", ComparisonConclusion.LOSS),
        ("-0.03", "0.03", ComparisonConclusion.EQUIVALENT),
        ("-0.06", "0.06", ComparisonConclusion.INCONCLUSIVE),
        ("0.05", "0.10", ComparisonConclusion.INCONCLUSIVE),
        ("-0.10", "-0.05", ComparisonConclusion.INCONCLUSIVE),
    ),
)
def test_five_state_decision_uses_strict_practical_boundaries(
    protocol_factory: Callable[..., FrozenComparisonProtocol],
    input_factory: Callable[..., ComparisonInput],
    low: str,
    high: str,
    expected: ComparisonConclusion,
) -> None:
    protocol = protocol_factory(precision=Decimal("0.04"))
    comparison = input_factory(
        protocol=protocol,
        deltas=(Decimal("0.01"), Decimal("0.02"), Decimal("0.03")),
    )
    interval = StatisticalInterval(
        "adjusted-bootstrap-v1",
        Decimal("0.05"),
        Decimal(low),
        Decimal(high),
    )

    assert decide_comparison(comparison, adjusted_interval=interval) is expected


def test_sample_and_completion_gates_take_precedence_over_direction(
    protocol_factory: Callable[..., FrozenComparisonProtocol],
    input_factory: Callable[..., ComparisonInput],
) -> None:
    protocol = protocol_factory(min_pairs=3)
    interval = StatisticalInterval(
        "adjusted-bootstrap-v1",
        Decimal("0.05"),
        Decimal("0.20"),
        Decimal("0.30"),
    )
    too_few = input_factory(
        protocol=protocol,
        deltas=(Decimal("0.2"), Decimal("0.2")),
    )
    incomplete = input_factory(
        protocol=protocol,
        deltas=(Decimal("0.2"), Decimal("0.2"), Decimal("0.2")),
        planned_pair_count=5,
    )

    assert (
        decide_comparison(too_few, adjusted_interval=interval)
        is ComparisonConclusion.INSUFFICIENT_EVIDENCE
    )
    assert (
        decide_comparison(incomplete, adjusted_interval=interval)
        is ComparisonConclusion.INSUFFICIENT_EVIDENCE
    )


def test_equivalence_requires_frozen_power_and_precision(
    protocol_factory: Callable[..., FrozenComparisonProtocol],
    input_factory: Callable[..., ComparisonInput],
) -> None:
    protocol = protocol_factory(precision=Decimal("0.04"))
    interval = StatisticalInterval(
        "adjusted-bootstrap-v1",
        Decimal("0.05"),
        Decimal("-0.03"),
        Decimal("0.03"),
    )
    low_power = input_factory(
        protocol=replace(protocol, a_priori_design_power=Decimal("0.79")),
        deltas=(Decimal(0), Decimal(0), Decimal(0)),
    )
    imprecise = input_factory(
        protocol=replace(protocol, precision=Decimal("0.02")),
        deltas=(Decimal(0), Decimal(0), Decimal(0)),
    )

    assert (
        decide_comparison(low_power, adjusted_interval=interval)
        is ComparisonConclusion.INCONCLUSIVE
    )
    assert (
        decide_comparison(imprecise, adjusted_interval=interval)
        is ComparisonConclusion.INCONCLUSIVE
    )


def test_family_pipeline_is_order_independent_and_retains_holm_lineage(
    protocol_factory: Callable[..., FrozenComparisonProtocol],
    input_factory: Callable[..., ComparisonInput],
) -> None:
    winner = input_factory(
        protocol=protocol_factory(comparison_id="winner", question_cluster="purchase"),
        deltas=(Decimal("0.20"),) * 8,
        planned_pair_count=10,
    )
    equivalent = input_factory(
        protocol=protocol_factory(
            comparison_id="equivalent",
            question_cluster="trust",
            precision=Decimal("0.01"),
        ),
        deltas=(Decimal(0),) * 8,
        planned_pair_count=10,
    )
    uncertain = input_factory(
        protocol=protocol_factory(comparison_id="uncertain", question_cluster="support"),
        deltas=(
            Decimal("-0.20"),
            Decimal("0.20"),
            Decimal("-0.10"),
            Decimal("0.10"),
            Decimal("-0.05"),
            Decimal("0.05"),
            Decimal(0),
            Decimal(0),
        ),
        planned_pair_count=10,
    )

    first = analyze_comparison_family((winner, equivalent, uncertain))
    second = analyze_comparison_family((uncertain, winner, equivalent))
    results = {item.comparison_id: item for item in first.results}

    assert first.family_hash == second.family_hash
    assert results["winner"].conclusion is ComparisonConclusion.WIN
    assert results["equivalent"].conclusion is ComparisonConclusion.EQUIVALENT
    assert results["uncertain"].conclusion is ComparisonConclusion.INCONCLUSIVE
    assert {item.holm_rank for item in first.results} == {1, 2, 3}
    assert all(item.raw_interval.alpha == Decimal("0.05") for item in first.results)
    assert all(
        item.adjusted_interval.alpha == Decimal("0.05") / Decimal(3) for item in first.results
    )
    assert all(item.completion_ratio == Decimal("0.800000000000") for item in first.results)
    assert all(len(item.result_hash) == 64 for item in first.results)


def test_holm_adjusted_p_values_match_frozen_golden_values() -> None:
    adjustments = holm_adjust(
        {"a": Decimal("0.01"), "b": Decimal("0.03"), "c": Decimal("0.04")},
        family_alpha=Decimal("0.05"),
    )

    assert [
        (
            item.comparison_id,
            item.rank,
            str(item.adjusted_p_value),
            str(item.local_alpha),
            item.rejected,
        )
        for item in adjustments
    ] == [
        ("a", 1, "0.030000000000", "0.016666666667", True),
        ("b", 2, "0.060000000000", "0.025000000000", False),
        ("c", 3, "0.060000000000", "0.050000000000", False),
    ]


def test_family_result_hash_and_simultaneous_interval_are_frozen_golden(
    protocol_factory: Callable[..., FrozenComparisonProtocol],
    input_factory: Callable[..., ComparisonInput],
) -> None:
    winner = input_factory(
        protocol=protocol_factory(comparison_id="winner", question_cluster="purchase"),
        deltas=(Decimal("0.20"),) * 8,
        planned_pair_count=10,
    )
    equivalent = input_factory(
        protocol=protocol_factory(
            comparison_id="equivalent",
            question_cluster="trust",
            precision=Decimal("0.01"),
        ),
        deltas=(Decimal(0),) * 8,
        planned_pair_count=10,
    )
    uncertain = input_factory(
        protocol=protocol_factory(comparison_id="uncertain", question_cluster="support"),
        deltas=(
            Decimal("-0.20"),
            Decimal("0.20"),
            Decimal("-0.10"),
            Decimal("0.10"),
            Decimal("-0.05"),
            Decimal("0.05"),
            Decimal(0),
            Decimal(0),
        ),
        planned_pair_count=10,
    )

    result = analyze_comparison_family((winner, equivalent, uncertain))
    golden = {
        item.comparison_id: (
            str(item.raw_p_value),
            str(item.adjusted_p_value),
            str(item.local_alpha),
            item.adjusted_interval.method,
            str(item.adjusted_interval.alpha),
            str(item.adjusted_interval.low),
            str(item.adjusted_interval.high),
            item.result_hash,
        )
        for item in result.results
    }

    assert result.family_hash == (
        "cdce83d49f8dc58c3243c438f515638099235d9a71ff05191b307276cc234d54"
    )
    assert golden == {
        "equivalent": (
            "1.000000000000",
            "1.000000000000",
            "0.025000000000",
            "paired-bootstrap-percentile-bonferroni-family-v1",
            "0.01666666666666666666666666667",
            "0E-12",
            "0E-12",
            "43925e5f0fb3e6e634e9390bd8002f6c2ff3dec42af10b0fd9caf5eb8e18a4b9",
        ),
        "uncertain": (
            "1.000000000000",
            "1.000000000000",
            "0.050000000000",
            "paired-bootstrap-percentile-bonferroni-family-v1",
            "0.01666666666666666666666666667",
            "-0.081250000000",
            "0.093750000000",
            "06a2cc65fea654914a5c0afb9fe960b8962221afd19aab478bcf125c1606b6b6",
        ),
        "winner": (
            "0.003992015968",
            "0.011976047904",
            "0.016666666667",
            "paired-bootstrap-percentile-bonferroni-family-v1",
            "0.01666666666666666666666666667",
            "0.200000000000",
            "0.200000000000",
            "cfe44dbf2ee8953e202194837e625bf9765c0a35baa61aa02db86c984de5ffe1",
        ),
    }


def test_protocol_seed_changes_with_every_required_seed_identity(
    protocol_factory: Callable[..., FrozenComparisonProtocol],
) -> None:
    base = protocol_factory()

    assert base.seed_hex != protocol_factory(candidate_version="candidate-v3").seed_hex
    assert base.seed_hex != protocol_factory(comparison_id="comparison-two").seed_hex
    assert base.frozen_hash == replace(base).frozen_hash


def test_mixed_capture_method_or_stratum_is_rejected_before_computation(
    protocol_factory: Callable[..., FrozenComparisonProtocol],
    input_factory: Callable[..., ComparisonInput],
) -> None:
    protocol = protocol_factory(capture_method="provider_api")
    valid = input_factory(protocol=protocol, deltas=(Decimal("0.1"),) * 3)
    mixed_pair = replace(valid.pairs[0], capture_method="manual_ui")

    with pytest.raises(StatisticalRuleViolation, match="capture methods"):
        replace(valid, pairs=(mixed_pair, *valid.pairs[1:]))


def test_complete_sampling_source_stratum_hash_is_a_denominator_identity(
    protocol_factory: Callable[..., FrozenComparisonProtocol],
    input_factory: Callable[..., ComparisonInput],
) -> None:
    protocol = protocol_factory()
    valid = input_factory(protocol=protocol, deltas=(Decimal("0.1"),) * 3)
    changed_source = replace(
        protocol.stratum,
        sampling_source_stratum_hash="f" * 64,
    )

    assert changed_source.stratum_hash != protocol.stratum.stratum_hash
    with pytest.raises(StatisticalRuleViolation, match="complete Sampling SourceStratum"):
        replace(valid, sampling_source_stratum_hash="f" * 64)
    with pytest.raises(StatisticalRuleViolation, match="frozen strata"):
        replace(
            valid,
            pairs=(
                replace(
                    valid.pairs[0],
                    sampling_source_stratum_hash="f" * 64,
                ),
                *valid.pairs[1:],
            ),
        )


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("bootstrap_iterations", 700),
        ("bootstrap_method", "paired-bootstrap-percentile-v2"),
        (
            "simultaneous_interval_method",
            "paired-bootstrap-percentile-bonferroni-family-v2",
        ),
    ],
)
def test_family_rejects_mixed_bootstrap_method_contracts(
    override: str,
    value: object,
    protocol_factory: Callable[..., FrozenComparisonProtocol],
    input_factory: Callable[..., ComparisonInput],
) -> None:
    first = input_factory(
        protocol=protocol_factory(comparison_id="first"),
        deltas=(Decimal("0.1"),) * 3,
    )
    second_protocol = protocol_factory(comparison_id="second", **{override: value})
    second = input_factory(
        protocol=second_protocol,
        deltas=(Decimal("0.1"),) * 3,
    )

    with pytest.raises(StatisticalRuleViolation, match="methods must be frozen"):
        analyze_comparison_family((first, second))
