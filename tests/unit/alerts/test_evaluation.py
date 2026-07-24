from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from geo_core.alerts import (
    ALERT_EVALUATOR_VERSION,
    AlertEvidenceReference,
    AlertRuleKind,
    AlertRuleVersion,
    AlertRuleViolation,
    AlertScope,
    AlertSeverity,
    evaluate_alert_rule,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
PROJECT_ID = UUID("51000000-0000-4000-8000-000000000001")
STRATUM_HASH = "b" * 64


@dataclass(frozen=True)
class EvaluationCase:
    kind: AlertRuleKind
    parameters: dict[str, object]
    values: dict[str, object]
    reasons: tuple[str, ...]


CASES = (
    EvaluationCase(
        AlertRuleKind.THRESHOLD,
        {
            "schema_version": "alert-rule-threshold-v1",
            "metric_key": "recommendation_rate",
            "operator": "lt",
            "threshold": "0.5",
        },
        {
            "schema_version": "alert-input-threshold-v1",
            "metric_key": "recommendation_rate",
            "observed_value": "0.31",
        },
        ("threshold_crossed",),
    ),
    EvaluationCase(
        AlertRuleKind.BASELINE_DELTA,
        {
            "schema_version": "alert-rule-baseline-delta-v1",
            "metric_key": "mention_rate",
            "direction": "decrease",
            "minimum_delta": "0.1",
        },
        {
            "schema_version": "alert-input-baseline-delta-v1",
            "metric_key": "mention_rate",
            "baseline_value": "0.72",
            "current_value": "0.55",
        },
        ("baseline_decrease",),
    ),
    EvaluationCase(
        AlertRuleKind.NEGATIVE_QUESTION,
        {
            "schema_version": "alert-rule-negative-question-v1",
            "metric_key": "recommendation_gain",
            "maximum_delta": "-0.1",
            "require_interval_below_zero": True,
        },
        {
            "schema_version": "alert-input-negative-question-v1",
            "metric_key": "recommendation_gain",
            "question_id": "best-accounting-platform-au",
            "delta": "-0.21",
            "interval_low": "-0.3",
            "interval_high": "-0.12",
        },
        ("negative_question",),
    ),
    EvaluationCase(
        AlertRuleKind.COMPLETION_FRESHNESS,
        {
            "schema_version": "alert-rule-completion-freshness-v1",
            "minimum_completion_ratio": "0.8",
            "maximum_age_seconds": 3600,
        },
        {
            "schema_version": "alert-input-completion-freshness-v1",
            "planned_count": 10,
            "valid_count": 7,
            "invalid_count": 1,
            "missing_count": 2,
            "snapshot_captured_at": NOW - timedelta(hours=2),
        },
        ("insufficient_samples", "stale_snapshot"),
    ),
    EvaluationCase(
        AlertRuleKind.MODEL_DRIFT,
        {
            "schema_version": "alert-rule-model-drift-v1",
            "minimum_changed_models": 2,
        },
        {
            "schema_version": "alert-input-model-drift-v1",
            "stratum_hash": STRATUM_HASH,
            "baseline_models": ["model-v1"],
            "current_models": ["model-v2"],
        },
        ("model_drift",),
    ),
    EvaluationCase(
        AlertRuleKind.SOURCE_DRIFT,
        {
            "schema_version": "alert-rule-source-drift-v1",
            "minimum_changed_compositions": 2,
        },
        {
            "schema_version": "alert-input-source-drift-v1",
            "stratum_hash": STRATUM_HASH,
            "baseline_composition_hashes": ["c" * 64],
            "current_composition_hashes": ["d" * 64],
        },
        ("source_drift",),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.kind.value)
def test_all_rule_kinds_produce_explainable_versioned_triggers(
    case: EvaluationCase,
) -> None:
    evaluation = _evaluate(case)

    assert evaluation.matched is True
    assert evaluation.reason_codes == case.reasons
    assert evaluation.evaluator_version == ALERT_EVALUATOR_VERSION
    assert evaluation.parameter_schema_version == case.parameters["schema_version"]
    assert evaluation.input_schema_version == case.values["schema_version"]
    assert evaluation.trigger_snapshot is not None
    assert evaluation.trigger_snapshot.values["reason_codes"] == case.reasons
    assert evaluation.trigger_snapshot.values["input_hash"] == evaluation.input_hash
    assert evaluation.evidence[0].locator == "results[0].interval"
    assert len(evaluation.input_hash) == len(evaluation.evaluation_hash) == 64


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.kind.value)
def test_unknown_parameter_and_input_fields_fail_closed(case: EvaluationCase) -> None:
    parameters = {**case.parameters, "unfrozen_override": True}
    with pytest.raises(AlertRuleViolation, match="unknown=.*unfrozen_override"):
        _evaluate(EvaluationCase(case.kind, parameters, case.values, case.reasons))

    values = {**case.values, "unexpected_projection": "value"}
    with pytest.raises(AlertRuleViolation, match="unknown=.*unexpected_projection"):
        _evaluate(EvaluationCase(case.kind, case.parameters, values, case.reasons))


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.kind.value)
def test_schema_versions_are_not_forward_compatible_by_accident(
    case: EvaluationCase,
) -> None:
    parameters = {**case.parameters, "schema_version": f"{case.parameters['schema_version']}-future"}
    with pytest.raises(AlertRuleViolation, match="schema version is unsupported"):
        _evaluate(EvaluationCase(case.kind, parameters, case.values, case.reasons))

    values = {**case.values, "schema_version": f"{case.values['schema_version']}-future"}
    with pytest.raises(AlertRuleViolation, match="schema version is unsupported"):
        _evaluate(EvaluationCase(case.kind, case.parameters, values, case.reasons))


def test_threshold_and_baseline_boundaries_use_frozen_operators() -> None:
    threshold = CASES[0]
    equal = {**threshold.values, "observed_value": "0.5"}
    assert not _evaluate(EvaluationCase(threshold.kind, threshold.parameters, equal, ())).matched

    inclusive_parameters = {**threshold.parameters, "operator": "lte"}
    assert _evaluate(
        EvaluationCase(threshold.kind, inclusive_parameters, equal, ("threshold_crossed",))
    ).matched

    baseline = CASES[1]
    boundary = {**baseline.values, "current_value": "0.62"}
    assert _evaluate(EvaluationCase(baseline.kind, baseline.parameters, boundary, baseline.reasons)).matched


def test_negative_question_requires_the_frozen_interval_condition() -> None:
    case = CASES[2]
    touches_zero = {**case.values, "interval_high": "0"}
    assert not _evaluate(EvaluationCase(case.kind, case.parameters, touches_zero, ())).matched

    no_interval_rule = {**case.parameters, "require_interval_below_zero": False}
    assert _evaluate(
        EvaluationCase(case.kind, no_interval_rule, touches_zero, case.reasons)
    ).matched
    inconsistent = {**case.values, "interval_low": "-0.1"}
    with pytest.raises(AlertRuleViolation, match="interval is inconsistent"):
        _evaluate(EvaluationCase(case.kind, case.parameters, inconsistent, case.reasons))


def test_completion_distinguishes_sample_shortage_from_freshness() -> None:
    case = CASES[3]
    exact_boundary = {
        **case.values,
        "valid_count": 8,
        "invalid_count": 1,
        "missing_count": 1,
        "snapshot_captured_at": NOW - timedelta(seconds=3600),
    }
    boundary = _evaluate(EvaluationCase(case.kind, case.parameters, exact_boundary, ()))
    assert not boundary.matched

    insufficient_only = {**exact_boundary, "valid_count": 7, "missing_count": 2}
    assert _evaluate(
        EvaluationCase(case.kind, case.parameters, insufficient_only, ("insufficient_samples",))
    ).reason_codes == ("insufficient_samples",)

    stale_only = {**exact_boundary, "snapshot_captured_at": NOW - timedelta(seconds=3601)}
    assert _evaluate(
        EvaluationCase(case.kind, case.parameters, stale_only, ("stale_snapshot",))
    ).reason_codes == ("stale_snapshot",)

    both = _evaluate(case)
    assert both.reason_codes == ("insufficient_samples", "stale_snapshot")
    assert both.trigger_snapshot is not None
    assert both.trigger_snapshot.values["insufficient_samples"] is True
    assert both.trigger_snapshot.values["stale_snapshot"] is True


@pytest.mark.parametrize("index", [4, 5])
def test_drift_threshold_counts_added_and_removed_members(index: int) -> None:
    case = CASES[index]
    assert _evaluate(case).matched
    too_high_key = (
        "minimum_changed_models"
        if case.kind is AlertRuleKind.MODEL_DRIFT
        else "minimum_changed_compositions"
    )
    parameters = {**case.parameters, too_high_key: 3}
    assert not _evaluate(EvaluationCase(case.kind, parameters, case.values, ())).matched


def test_evidence_locator_and_input_consistency_are_mandatory() -> None:
    case = CASES[0]
    with pytest.raises(AlertRuleViolation, match="requires locators"):
        evaluate_alert_rule(
            rule_version=_rule(case),
            scope=_scope(),
            input_values=case.values,
            evidence=(_evidence(locator=None),),
            evaluated_at=NOW,
        )
    mismatch = {**case.values, "metric_key": "another_metric"}
    with pytest.raises(AlertRuleViolation, match="does not match"):
        _evaluate(EvaluationCase(case.kind, case.parameters, mismatch, case.reasons))


@pytest.mark.parametrize(
    ("case", "expected_input_hash", "expected_evaluation_hash"),
    [
        (
            CASES[0],
            "15fbc3b56299fe794f21369337156057483ec41e096ddbd82fce538b20da89ad",
            "ee5cf5c22f18ab3079dba057fc705094161e3853b5d41eb254671d9bf4c80cef",
        ),
        (
            CASES[1],
            "358690849f69dd37564811f531d6665bf96ad1f9e0ce35392610f67521637751",
            "68aa6e9d15eb4ebb568790827de015ba5989ccd58be058c14b0194dc017d0b54",
        ),
        (
            CASES[2],
            "e616f11bf51dcfd81866f0ffe567329e9bd0ee5d02449ef439e49b239a0011ea",
            "759d2fa6f29045e3a58c95732d17dec26ff2357d4e6b6c5ba38e434ee2506b93",
        ),
        (
            CASES[3],
            "bbde6e811080ac285b961250b99b70c9300ba3252062401deb0f34eea7aa22e2",
            "32f36524c307069b3190a16622f6d02aaaa80480a9a62678b2580bd89feecba2",
        ),
        (
            CASES[4],
            "72ea066c21e9e8d7f137c0ae1c511610c006feb72d85d285894e283d6da91c3f",
            "b5b0ef415de2014e60416300ca20659936993a8dd0bbb06bf7b909681ccd81b5",
        ),
        (
            CASES[5],
            "525dd76ba827ab52b7aa60ba0ef11dee8b962c02f4c25c0a1c22678506408311",
            "2a8a40ddb755ab4544825e1504a51eab1ab61d7dde13e235a56987fc2d99618f",
        ),
    ],
    ids=[case.kind.value for case in CASES],
)
def test_evaluation_hashes_are_frozen_golden_values(
    case: EvaluationCase,
    expected_input_hash: str,
    expected_evaluation_hash: str,
) -> None:
    evaluation = _evaluate(case)
    assert (evaluation.input_hash, evaluation.evaluation_hash) == (
        expected_input_hash,
        expected_evaluation_hash,
    )


def test_hashes_ignore_mapping_order_but_change_with_observation() -> None:
    case = CASES[0]
    reordered = dict(reversed(tuple(case.values.items())))
    first = _evaluate(case)
    replay = _evaluate(EvaluationCase(case.kind, case.parameters, reordered, case.reasons))
    changed = _evaluate(
        EvaluationCase(
            case.kind,
            case.parameters,
            {**case.values, "observed_value": "0.30"},
            case.reasons,
        )
    )

    assert replay.input_hash == first.input_hash
    assert replay.evaluation_hash == first.evaluation_hash
    assert changed.input_hash != first.input_hash
    assert changed.evaluation_hash != first.evaluation_hash


def _evaluate(case: EvaluationCase):
    return evaluate_alert_rule(
        rule_version=_rule(case),
        scope=_scope(),
        input_values=case.values,
        evidence=(_evidence(),),
        evaluated_at=NOW,
    )


def _rule(case: EvaluationCase) -> AlertRuleVersion:
    return AlertRuleVersion(
        id=UUID("52000000-0000-4000-8000-000000000001"),
        project_id=PROJECT_ID,
        rule_key=f"fixture-{case.kind.value}",
        version=1,
        kind=case.kind,
        severity=AlertSeverity.WARNING,
        parameters=case.parameters,
        frozen_by="admin-fixture",
        frozen_at=NOW - timedelta(days=1),
    )


def _scope() -> AlertScope:
    return AlertScope(
        project_id=PROJECT_ID,
        resource_kind="semantic_metric_snapshot",
        resource_key="snapshot:fixture",
        dimensions=(("capture_method", "provider_api"), ("region", "AU")),
    )


def _evidence(locator: str | None = "results[0].interval") -> AlertEvidenceReference:
    return AlertEvidenceReference(
        kind="metric_snapshot",
        resource_id="snapshot:fixture",
        version="semantic-metrics-v1",
        sha256="a" * 64,
        locator=locator,
    )
