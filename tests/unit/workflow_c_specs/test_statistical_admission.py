from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from geo_core.sampling import CaptureMethod, LocationControl, SamplingSourceStratum
from geo_core.semantic_metrics._validation import canonical_hash as semantic_hash
from geo_core.workflow_c_statistical_admission import (
    PostgresWorkflowCStatisticalAdmissionError,
    _ApprovedProtocol,
    _comparison_inputs,
    _drift_inputs,
    _snapshot,
)
from geo_core.workflow_c_statistical_protocols import (
    ComparisonPlanDefinition,
    DriftProtocolDefinition,
)


def test_snapshot_reconstructs_comparison_inputs_from_frozen_lineage() -> None:
    baseline = _metric_snapshot(score="0.2", snapshot_seed="baseline")
    candidate = _metric_snapshot(score="0.7", snapshot_seed="candidate")
    protocol = _ApprovedProtocol(
        id=uuid4(),
        definition_hash=_comparison_plan().definition_hash,
        definition=_comparison_plan(),
    )

    inputs = _comparison_inputs(
        protocol=protocol,
        baseline=baseline,
        candidate=candidate,
    )

    assert len(inputs) == 1
    assert inputs[0].planned_pair_count == 1
    assert inputs[0].pairs[0].baseline == Decimal("0.2")
    assert inputs[0].pairs[0].candidate == Decimal("0.7")
    assert inputs[0].protocol.protocol_hash == protocol.definition_hash
    assert inputs[0].protocol.baseline_version == f"snapshot:{baseline.snapshot_hash}"


def test_comparison_keeps_planned_denominator_but_suppresses_low_evidence_pairs() -> None:
    baseline = replace(
        _metric_snapshot(score="0.2", snapshot_seed="baseline"),
        evidence_status="insufficient_evidence",
    )
    candidate = _metric_snapshot(score="0.7", snapshot_seed="candidate")
    definition = _comparison_plan()

    result = _comparison_inputs(
        protocol=_ApprovedProtocol(uuid4(), definition.definition_hash, definition),
        baseline=baseline,
        candidate=candidate,
    )[0]

    assert result.planned_pair_count == 1
    assert result.pairs == ()


def test_comparison_rejects_capture_denominator_or_question_inventory_mixing() -> None:
    baseline = _metric_snapshot(score="0.2", snapshot_seed="baseline")
    candidate = replace(
        _metric_snapshot(score="0.7", snapshot_seed="candidate"),
        source_stratum_hash="f" * 64,
    )
    definition = _comparison_plan()

    with pytest.raises(
        PostgresWorkflowCStatisticalAdmissionError,
        match="cannot mix SourceStratum",
    ):
        _comparison_inputs(
            protocol=_ApprovedProtocol(uuid4(), definition.definition_hash, definition),
            baseline=baseline,
            candidate=candidate,
        )


def test_drift_applies_frozen_per_cluster_minimum_and_keeps_protocol_lineage() -> None:
    baseline = _metric_snapshot(score="0.2", snapshot_seed="baseline")
    current = _metric_snapshot(score="0.7", snapshot_seed="current")
    strict = DriftProtocolDefinition(minimum_question_count=2)

    with pytest.raises(
        PostgresWorkflowCStatisticalAdmissionError,
        match="below the frozen per-cluster",
    ):
        _drift_inputs(
            protocol=_ApprovedProtocol(uuid4(), strict.definition_hash, strict),
            baseline=baseline,
            current=current,
        )

    allowed = DriftProtocolDefinition(minimum_question_count=1)
    before, after = _drift_inputs(
        protocol=_ApprovedProtocol(uuid4(), allowed.definition_hash, allowed),
        baseline=baseline,
        current=current,
    )
    assert before[0].effect == Decimal("0.2")
    assert after[0].effect == Decimal("0.7")
    assert before[0].stratum.source_composition_hash == baseline.sampling_suite_hash


def test_snapshot_rejects_payload_hash_or_semantic_stratum_corruption() -> None:
    row = _snapshot_row(score="0.2", snapshot_seed="baseline")
    row["snapshot_hash"] = "0" * 64
    with pytest.raises(
        PostgresWorkflowCStatisticalAdmissionError,
        match="payload hash is corrupt",
    ):
        _snapshot(row)

    row = _snapshot_row(score="0.2", snapshot_seed="baseline")
    payload = dict(row["payload"])
    results = [dict(item) for item in payload["results"]]
    results[0]["stratum"] = {**results[0]["stratum"], "region": "US"}
    payload["results"] = results
    result_value = dict(payload)
    result_value.pop("computed_at")
    row["snapshot_hash"] = semantic_hash(result_value)
    row["payload"] = payload
    with pytest.raises(
        PostgresWorkflowCStatisticalAdmissionError,
        match="result stratum lineage is corrupt",
    ):
        _snapshot(row)


def _metric_snapshot(*, score: str, snapshot_seed: str):
    return _snapshot(_snapshot_row(score=score, snapshot_seed=snapshot_seed))


def _snapshot_row(*, score: str, snapshot_seed: str) -> dict[str, object]:
    source = _source()
    sampling_suite_hash = semantic_hash({"sampling_suite": "shared"})
    source_dimensions = {
        "provider": source.platform,
        "reported_model": source.reported_model,
        "capture_method": source.capture_method.value,
        "locale": source.locale,
        "region": source.region,
        "source_composition_hash": sampling_suite_hash,
        "sampling_source_stratum_hash": source.stratum_hash,
        "question_cluster": "all",
    }
    payload: dict[str, object] = {
        "input_set_hash": semantic_hash({"input": snapshot_seed}),
        "suite_hash": semantic_hash({"metric_suite": "v1"}),
        "stratum_hash": semantic_hash(source_dimensions),
        "results": [
            {
                "metric_key": "brand_mention",
                "stratum": source_dimensions,
                "stratum_hash": semantic_hash(source_dimensions),
            }
        ],
        "performance": {
            "questions": [
                {
                    "question_id": "question-1",
                    "question_cluster": "purchase",
                    "score": score,
                    "planned_slot_count": 10,
                }
            ],
            "clusters": [
                {
                    "question_cluster": "purchase",
                    "score": score,
                    "planned_slot_count": 10,
                }
            ],
            "worst_question_id": "question-1",
            "worst_question_score": score,
            "worst_cluster": "purchase",
            "worst_cluster_score": score,
            "negative_gain": None,
        },
        "computed_at": "2026-07-24T00:00:00+00:00",
    }
    result_value = dict(payload)
    result_value.pop("computed_at")
    suite_payload = {
        "schema_version": 1,
        "suite": {
            "question_set_hash": semantic_hash({"question_set": "v1"}),
            "questions": [
                {
                    "question_id": "question-1",
                    "question_version": "v1",
                    "text_hash": "9" * 64,
                }
            ],
            "source_stratum": source.canonical_value(),
        },
        "frozen_by": "operator",
        "frozen_at": "2026-07-24T00:00:00+00:00",
    }
    return {
        "snapshot_hash": semantic_hash(result_value),
        "input_set_hash": payload["input_set_hash"],
        "metric_suite_hash": payload["suite_hash"],
        "source_stratum_hash": source.stratum_hash,
        "capture_method": source.capture_method.value,
        "evidence_status": "complete",
        "payload": payload,
        "sampling_suite_hash": sampling_suite_hash,
        "suite_source_stratum_hash": source.stratum_hash,
        "suite_capture_method": source.capture_method.value,
        "sampling_suite_payload": suite_payload,
    }


def _source() -> SamplingSourceStratum:
    return SamplingSourceStratum(
        platform="openai",
        surface="responses",
        configured_model="gpt-5",
        reported_model="gpt-5-2026-07-01",
        capture_method=CaptureMethod.PROVIDER_API,
        adapter_release="openai-v1",
        locale="en-AU",
        region="AU",
        language="en",
        search_mode="grounded",
        account_cohort="not_applicable",
        egress_policy_category="not_applicable",
        location_control=LocationControl.COUNTRY,
        location_evidence_hash="8" * 64,
        requested_country="AU",
        requested_region=None,
        requested_locale="en-AU",
        requested_language="en",
        effective_country="AU",
        effective_region=None,
        effective_locale=None,
        effective_language=None,
    )


def _comparison_plan() -> ComparisonPlanDefinition:
    return ComparisonPlanDefinition(
        family="primary",
        question_clusters=("purchase",),
        alpha=Decimal("0.05"),
        delta=Decimal("0.05"),
        target_power=Decimal("0.80"),
        precision=Decimal("0.10"),
        min_pairs=3,
        power_plan_hash="7" * 64,
        a_priori_design_power=Decimal("0.90"),
        bootstrap_iterations=100,
    )
