from __future__ import annotations

from uuid import UUID

import pytest

from geo_core.alerts import AlertRuleKind
import geo_core.workflow_c_alert_admission as admission


PROJECT_ID = UUID("52000000-0000-4000-8000-000000000001")
CURRENT_HASH = "a" * 64
BASELINE_HASH = "b" * 64
COHORT = {"surface": "provider_api"}
COHORT_HASH = admission._canonical_hash(COHORT)


def _selector(**changes: object) -> admission.AlertEvaluationSelector:
    values: dict[str, object] = {
        "alert_rule_id": UUID("52000000-0000-4000-8000-000000000002"),
        "source_hash": CURRENT_HASH,
    }
    values.update(changes)
    return admission.AlertEvaluationSelector(**values)  # type: ignore[arg-type]


def _semantic(*, estimate: str, stratum: str = "stratum-1") -> dict[str, object]:
    return {
        "metric_suite_hash": "suite-1",
        "source_stratum_hash": stratum,
        "payload": {
            "computed_at": "2026-07-24T08:00:00+00:00",
            "results": [
                {
                    "metric_key": "mention_rate",
                    "estimate": estimate,
                    "denominator": 10,
                    "valid_input_count": 8,
                    "invalid_input_count": 1,
                    "missing_input_count": 1,
                    "status": "complete",
                }
            ],
        },
    }


def test_semantic_resolvers_freeze_threshold_completion_and_baseline_values() -> None:
    threshold = admission._threshold_input(
        _semantic(estimate="0.4"),
        parameters={"metric_key": "mention_rate"},
        selector=_selector(),
        project_id=PROJECT_ID,
    )
    assert threshold.values == {
        "schema_version": "alert-input-threshold-v1",
        "metric_key": "mention_rate",
        "observed_value": "0.4",
    }

    completion = admission._completion_input(
        _semantic(estimate="0.4"),
        selector=_selector(source_item_key="mention_rate"),
        project_id=PROJECT_ID,
    )
    assert completion.values["planned_count"] == 10
    assert completion.values["valid_count"] == 8
    assert completion.values["snapshot_captured_at"] == "2026-07-24T08:00:00+00:00"

    baseline = admission._baseline_input(
        _semantic(estimate="0.7"),
        _semantic(estimate="0.4"),
        parameters={"metric_key": "mention_rate"},
        selector=_selector(baseline_source_hash=BASELINE_HASH),
        project_id=PROJECT_ID,
    )
    assert baseline.values["baseline_value"] == "0.7"
    assert baseline.values["current_value"] == "0.4"
    assert tuple(item.sha256 for item in baseline.evidence) == (
        BASELINE_HASH,
        CURRENT_HASH,
    )


def test_baseline_resolver_rejects_mixed_source_strata() -> None:
    with pytest.raises(admission.WorkflowCAlertAdmissionError, match="mix metric or source"):
        admission._baseline_input(
            _semantic(estimate="0.7", stratum="stratum-1"),
            _semantic(estimate="0.4", stratum="stratum-2"),
            parameters={"metric_key": "mention_rate"},
            selector=_selector(baseline_source_hash=BASELINE_HASH),
            project_id=PROJECT_ID,
        )


def test_comparison_resolver_uses_one_frozen_question_locator() -> None:
    resolved = admission._negative_question_input(
        {
            "payload": {
                "results": [
                    {
                        "comparison_id": "question-1",
                        "point_estimate": "-0.2",
                        "adjusted_interval": {"low": "-0.3", "high": "-0.1"},
                    }
                ]
            }
        },
        parameters={"metric_key": "recommendation_gain"},
        selector=_selector(source_item_key="question-1"),
        project_id=PROJECT_ID,
    )

    assert resolved.values["question_id"] == "question-1"
    assert resolved.values["interval_high"] == "-0.1"


@pytest.mark.parametrize(
    ("kind", "collection", "baseline_key", "current_key", "expected_keys"),
    (
        (
            AlertRuleKind.MODEL_DRIFT,
            "model_drift",
            "baseline_models",
            "current_models",
            ("baseline_models", "current_models"),
        ),
        (
            AlertRuleKind.SOURCE_DRIFT,
            "source_drift",
            "baseline_compositions",
            "current_compositions",
            ("baseline_composition_hashes", "current_composition_hashes"),
        ),
    ),
)
def test_drift_resolvers_bind_one_hashed_cohort(
    kind: AlertRuleKind,
    collection: str,
    baseline_key: str,
    current_key: str,
    expected_keys: tuple[str, str],
) -> None:
    resolved = admission._drift_input(
        {
            "payload": {
                collection: [
                    {
                        "cohort": COHORT,
                        baseline_key: ["d" * 64],
                        current_key: ["e" * 64],
                    }
                ]
            }
        },
        kind=kind,
        selector=_selector(source_item_key=COHORT_HASH),
        project_id=PROJECT_ID,
    )

    assert resolved.values["stratum_hash"] == COHORT_HASH
    assert resolved.values[expected_keys[0]] == ["d" * 64]
    assert resolved.values[expected_keys[1]] == ["e" * 64]
