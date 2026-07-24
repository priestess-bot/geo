from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from geo_core.statistical_methods import (
    DriftObservation,
    QuestionEffect,
    StatisticalStratum,
    compute_drift_report,
    summarize_negative_gain,
)


def test_positive_average_cannot_hide_a_negative_question_or_cluster() -> None:
    report = summarize_negative_gain(
        (
            QuestionEffect("q1", "purchase", Decimal("0.50"), Decimal("0.40"), Decimal("0.60")),
            QuestionEffect("q2", "purchase", Decimal("0.30"), Decimal("0.10"), Decimal("0.50")),
            QuestionEffect("q3", "support", Decimal("-0.40"), Decimal("-0.60"), Decimal("-0.20")),
        )
    )

    assert report.average_effect == Decimal("0.133333333333")
    assert report.affected_question_count == 1
    assert report.mean_negative_gain == Decimal("-0.400000000000")
    assert report.negative_range_low == Decimal("-0.600000000000")
    assert report.negative_range_high == Decimal("-0.200000000000")
    assert report.worst_question_id == "q3"
    assert report.worst_question_effect == Decimal("-0.40")
    assert report.worst_cluster == "support"
    assert report.worst_cluster_effect == Decimal("-0.400000000000")
    assert len(report.result_hash) == 64


def test_model_source_and_effect_drift_are_reported_separately() -> None:
    stable_api = _stratum(capture_method="provider_api", cluster="purchase")
    changed_baseline = _stratum(capture_method="provider_api", cluster="support")
    changed_current = replace(
        changed_baseline,
        reported_model="model-v2",
        source_composition_hash="d" * 64,
    )
    stable_manual = _stratum(capture_method="manual_ui", cluster="purchase")
    baseline = (
        DriftObservation("b-api-1", stable_api, Decimal("0.10")),
        DriftObservation("b-api-2", stable_api, Decimal("0.20")),
        DriftObservation("b-change", changed_baseline, Decimal("0.20")),
        DriftObservation("b-ui", stable_manual, Decimal("0.30")),
    )
    current = (
        DriftObservation("c-api", stable_api, Decimal("0.30")),
        DriftObservation("c-change", changed_current, Decimal("-0.10")),
        DriftObservation("c-ui", stable_manual, Decimal("0.10")),
    )

    report = compute_drift_report(baseline=baseline, current=current)

    assert len(report.model_drift) == 1
    assert report.model_drift[0].baseline_models == ("model-v1",)
    assert report.model_drift[0].current_models == ("model-v2",)
    assert len(report.source_drift) == 1
    assert report.source_drift[0].baseline_compositions == ("c" * 64,)
    assert report.source_drift[0].current_compositions == ("d" * 64,)
    assert len(report.effect_drift) == 2
    effects = {item.stratum.capture_method: item for item in report.effect_drift}
    assert effects["provider_api"].baseline_mean == Decimal("0.150000000000")
    assert effects["provider_api"].current_mean == Decimal("0.300000000000")
    assert effects["provider_api"].effect_delta == Decimal("0.150000000000")
    assert effects["manual_ui"].effect_delta == Decimal("-0.200000000000")
    assert changed_baseline.stratum_hash in report.unmatched_baseline_strata
    assert changed_current.stratum_hash in report.unmatched_current_strata


def test_drift_hash_is_order_independent_and_never_combines_capture_methods() -> None:
    api = _stratum(capture_method="provider_api", cluster="purchase")
    ui = _stratum(capture_method="manual_ui", cluster="purchase")
    baseline = (
        DriftObservation("b-api", api, Decimal("0.10")),
        DriftObservation("b-ui", ui, Decimal("0.20")),
    )
    current = (
        DriftObservation("c-api", api, Decimal("0.30")),
        DriftObservation("c-ui", ui, Decimal("0.40")),
    )

    first = compute_drift_report(baseline=baseline, current=current)
    second = compute_drift_report(
        baseline=tuple(reversed(baseline)),
        current=tuple(reversed(current)),
    )

    assert first.report_hash == second.report_hash
    assert {item.stratum.capture_method for item in first.effect_drift} == {
        "provider_api",
        "manual_ui",
    }
    assert all(item.baseline_count == item.current_count == 1 for item in first.effect_drift)


def _stratum(*, capture_method: str, cluster: str) -> StatisticalStratum:
    return StatisticalStratum(
        provider="openai",
        reported_model="model-v1",
        capture_method=capture_method,
        locale="en-AU",
        region="AU",
        source_composition_hash="c" * 64,
        sampling_source_stratum_hash=(
            "d" if capture_method == "provider_api" else "e"
        ) * 64,
        question_cluster=cluster,
    )
