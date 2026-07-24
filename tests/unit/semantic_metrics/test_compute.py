from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from geo_core.semantic_metrics import (
    FrozenMetricSuite,
    MetricInputSet,
    MetricKey,
    MetricStatus,
    compute_semantic_metric_snapshot,
)


NOW = datetime(2026, 7, 23, 11, 0, tzinfo=UTC)


def test_complete_metric_inventory_has_frozen_lineage_and_expected_values(
    metric_input_set: MetricInputSet,
    metric_suite: FrozenMetricSuite,
) -> None:
    snapshot = compute_semantic_metric_snapshot(
        input_set=metric_input_set,
        suite=metric_suite,
        computed_at=NOW,
    )
    results = {item.metric_key: item for item in snapshot.results}

    assert set(results) == set(MetricKey)
    assert len(results) == 18
    assert _value(results, MetricKey.BRAND_MENTION) == (Decimal("2"), 5, Decimal("0.4"))
    assert _value(results, MetricKey.PRODUCT_MENTION) == (Decimal("3"), 5, Decimal("0.6"))
    assert _value(results, MetricKey.RECOMMENDATION) == (Decimal("2"), 5, Decimal("0.4"))
    assert _value(results, MetricKey.RECOMMENDATION_STRENGTH) == (
        Decimal("1.8"),
        5,
        Decimal("0.36"),
    )
    assert _value(results, MetricKey.COMPETITOR_MENTION) == (
        Decimal("3"),
        5,
        Decimal("0.6"),
    )
    assert _value(results, MetricKey.COMPETITOR_RELATIVE_POSITION) == (
        Decimal("0"),
        5,
        Decimal("0"),
    )
    assert _value(results, MetricKey.SENTIMENT) == (
        Decimal("-0.2"),
        5,
        Decimal("-0.04"),
    )
    assert dict(results[MetricKey.SENTIMENT].breakdown) == {
        "battery_life": Decimal(1),
        "missing_primary_product": Decimal(1),
    }
    assert _value(results, MetricKey.FACT_ACCURACY) == (Decimal("3"), 10, Decimal("0.3"))
    assert _value(results, MetricKey.EXPLICIT_CONFLICT) == (Decimal("2"), 10, Decimal("0.2"))
    assert _value(results, MetricKey.KEY_FACT_OMISSION) == (Decimal("3"), 10, Decimal("0.3"))
    assert _value(results, MetricKey.SUBJECT_MIXUP) == (Decimal("1"), 5, Decimal("0.2"))
    assert _value(results, MetricKey.CITATION_ENTAILMENT) == (
        Decimal("3"),
        4,
        Decimal("0.75"),
    )
    assert _value(results, MetricKey.CITATION_POSITION) == (
        Decimal("3"),
        4,
        Decimal("0.75"),
    )
    assert _value(results, MetricKey.CITATION_ORDER) == (Decimal("2"), 5, Decimal("0.4"))
    assert results[MetricKey.CITATION_ORDER].status is MetricStatus.INSUFFICIENT_EVIDENCE
    assert _value(results, MetricKey.VERIFIED_URL_HIT) == (Decimal("2"), 4, Decimal("0.5"))
    assert _value(results, MetricKey.SOURCE_DOMAIN_DIVERSITY) == (
        Decimal("4"),
        4,
        Decimal("4"),
    )
    assert _value(results, MetricKey.SOURCE_TYPE_DIVERSITY) == (
        Decimal("3"),
        4,
        Decimal("3"),
    )
    assert _value(results, MetricKey.APPROVED_CORPUS_ABSORPTION) == (
        Decimal("1.8"),
        5,
        Decimal("0.36"),
    )

    for definition in metric_suite.definitions:
        result = results[definition.key]
        assert result.metric_version == definition.version
        assert result.input_set_hash == metric_input_set.input_set_hash
        assert result.stratum == metric_input_set.stratum.dimensions
        assert result.stratum_hash == metric_input_set.stratum.stratum_hash
        assert dict(result.rule_versions) == metric_suite.rule_versions.canonical_value()
        assert result.rule_versions_hash == metric_suite.rule_versions.versions_hash
        assert result.judge_version == (
            metric_suite.judge_version.version if definition.judge_kind is not None else None
        )
        assert result.judge_version_hash == (
            metric_suite.judge_version.version_hash if definition.judge_kind is not None else None
        )
        assert len(result.result_hash) == 64


def test_worst_question_cluster_and_negative_gain_remain_visible(
    metric_input_set: MetricInputSet,
    metric_suite: FrozenMetricSuite,
) -> None:
    snapshot = compute_semantic_metric_snapshot(
        input_set=metric_input_set,
        suite=metric_suite,
        computed_at=NOW,
    )
    performance = snapshot.performance

    assert performance.worst_question_id == "q2"
    assert performance.worst_question_score == Decimal("0.000000")
    assert performance.worst_cluster == "trust"
    assert performance.worst_cluster_score == Decimal("0.000000")
    assert performance.negative_gain is not None
    assert performance.negative_gain.compared_question_count == 2
    assert performance.negative_gain.affected_question_count == 2
    assert performance.negative_gain.worst_question_id == "q2"
    assert performance.negative_gain.worst_question_delta == Decimal("-0.800000")
    assert performance.negative_gain.range_low == Decimal("-0.800000")
    assert performance.negative_gain.range_high == Decimal("-0.066667")


def test_recomputation_hashes_do_not_depend_on_computation_time(
    metric_input_set: MetricInputSet,
    metric_suite: FrozenMetricSuite,
) -> None:
    first = compute_semantic_metric_snapshot(
        input_set=metric_input_set,
        suite=metric_suite,
        computed_at=NOW,
    )
    second = compute_semantic_metric_snapshot(
        input_set=metric_input_set,
        suite=metric_suite,
        computed_at=NOW + timedelta(days=1),
    )

    assert [item.result_hash for item in first.results] == [
        item.result_hash for item in second.results
    ]
    assert first.snapshot_hash == second.snapshot_hash
    assert first.computed_at != second.computed_at


def _value(results, key: MetricKey) -> tuple[Decimal, int, Decimal]:
    result = results[key]
    return result.numerator, result.denominator, result.estimate
