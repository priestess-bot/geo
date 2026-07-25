from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from uuid import uuid4

from geo_core.jobs.postgres import WorkerLease
from geo_core.statistical_methods import (
    ComparisonInput,
    DriftObservation,
    FrozenComparisonProtocol,
    PairedObservation,
    StatisticalStratum,
)
from geo_core.semantic_metrics import (
    DeterministicRuleVersions,
    FrozenMetricSuite,
    JudgeVersion,
    MetricDefinition,
    MetricInputSet,
    MetricKey,
    MetricObservation,
    MetricValueKind,
    PlannedMetricSlot,
    SemanticStratum,
    SubjectInventory,
)
from geo_core.workflow_c_semantic_specs import semantic_inputs
from geo_core.workflow_c_metric_parent_specs import metric_model_program_admission
from geo_core.workflow_c_statistical_specs import comparison_inputs, drift_inputs
from geo_core.workflow_c_job_specs import WorkflowCJobSpec


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def test_comparison_worker_spec_reconstructs_the_exact_frozen_input() -> None:
    comparison = _comparison()
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "workflow_c.analysis.comparison",
        "comparison": {
            "inputs": [_comparison_value(comparison)],
        },
    }

    reconstructed = comparison_inputs(_spec("workflow_c.analysis.comparison", payload))

    assert reconstructed == (comparison,)
    assert reconstructed[0].input_hash == comparison.input_hash
    assert reconstructed[0].protocol.frozen_hash == comparison.protocol.frozen_hash


def test_drift_worker_spec_keeps_snapshot_identity_outside_observation_denominator() -> None:
    stratum = _stratum()
    baseline = DriftObservation("baseline-1", stratum, Decimal("0.2"))
    current = DriftObservation("current-1", stratum, Decimal("0.5"))
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "workflow_c.analysis.drift",
        "drift": {
            "source_snapshot_hash": "1" * 64,
            "target_snapshot_hash": "2" * 64,
            "baseline": [_drift_value(baseline)],
            "current": [_drift_value(current)],
        },
    }

    protocol_hash, source, target, restored_baseline, restored_current = drift_inputs(
        _spec("workflow_c.analysis.drift", payload)
    )

    assert protocol_hash is None
    assert (source, target) == ("1" * 64, "2" * 64)
    assert restored_baseline == (baseline,)
    assert restored_current == (current,)


def test_semantic_worker_spec_reconstructs_every_frozen_metric_input() -> None:
    metric_input_set, metric_suite = _semantic_inputs_fixture()
    run_id = uuid4()
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "workflow_c.analysis.semantic_metrics",
        "semantic_metrics": {
            "run_id": str(run_id),
            "source_stratum_hash": "f" * 64,
            "capture_method": "provider_api",
            "warning_ratio": "0.2",
            "test_only": False,
            "synthetic": False,
            "input_set": metric_input_set.canonical_value(),
            "suite": _suite_value(metric_suite),
        },
    }

    metadata, reconstructed_input, reconstructed_suite = semantic_inputs(
        _spec("workflow_c.analysis.semantic_metrics", payload)
    )

    assert metadata.run_id == run_id
    assert metadata.warning_ratio == Decimal("0.2")
    assert reconstructed_input == metric_input_set
    assert reconstructed_suite == metric_suite


def test_semantic_worker_spec_optionally_freezes_metric_model_program() -> None:
    metric_input_set, metric_suite = _semantic_inputs_fixture()
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "workflow_c.analysis.semantic_metrics",
        "semantic_metrics": {
            "run_id": str(uuid4()),
            "source_stratum_hash": "f" * 64,
            "capture_method": "provider_api",
            "warning_ratio": "0.2",
            "test_only": False,
            "synthetic": False,
            "input_set": metric_input_set.canonical_value(),
            "suite": _suite_value(metric_suite),
            "metric_model_program": _metric_model_program(metric_suite),
        },
    }

    metadata, restored_input, restored_suite = semantic_inputs(
        _spec("workflow_c.analysis.semantic_metrics", payload)
    )
    program = metric_model_program_admission(_spec("workflow_c.analysis.semantic_metrics", payload))

    assert metadata.capture_method == "provider_api"
    assert restored_input == metric_input_set and restored_suite == metric_suite
    assert program is not None
    assert [item.evaluator_id for item in program.judges] == ["judge-a", "judge-b"]
    assert program.arbiter.evaluator_id == "arbiter-a"


def _comparison() -> ComparisonInput:
    stratum = _stratum()
    protocol = FrozenComparisonProtocol(
        protocol_hash="a" * 64,
        question_set_hash="b" * 64,
        baseline_version="baseline-v1",
        candidate_version="candidate-v2",
        metric_key="recommendation",
        metric_method_version="metric-v1",
        comparison_id="comparison-one",
        family="primary-family",
        stratum=stratum,
        alpha=Decimal("0.05"),
        delta=Decimal("0.05"),
        target_power=Decimal("0.80"),
        precision=Decimal("0.10"),
        min_pairs=3,
        power_plan_hash="e" * 64,
        a_priori_design_power=Decimal("0.90"),
        power_method_version="a-priori-design-power-v1",
        minimum_completion_ratio=Decimal("0.80"),
        bootstrap_iterations=100,
        bootstrap_method="paired-bootstrap-percentile-v1",
        correction_method="holm-v1",
        simultaneous_interval_method="paired-bootstrap-percentile-bonferroni-family-v1",
    )
    pairs = tuple(
        PairedObservation(
            pair_id=f"pair-{number}",
            question_id=f"question-{number}",
            question_cluster=stratum.question_cluster,
            stratum_hash=stratum.stratum_hash,
            sampling_source_stratum_hash=stratum.sampling_source_stratum_hash,
            capture_method=stratum.capture_method,
            baseline=Decimal("0"),
            candidate=Decimal("0.1"),
        )
        for number in range(1, 4)
    )
    return ComparisonInput(
        protocol=protocol,
        sampling_source_stratum_hash=stratum.sampling_source_stratum_hash,
        planned_pair_count=3,
        pairs=pairs,
    )


def _stratum() -> StatisticalStratum:
    return StatisticalStratum(
        provider="openai",
        reported_model="model-v1",
        capture_method="provider_api",
        locale="en-AU",
        region="AU",
        source_composition_hash="c" * 64,
        sampling_source_stratum_hash="d" * 64,
        question_cluster="purchase",
    )


def _comparison_value(value: ComparisonInput) -> dict[str, object]:
    protocol = dict(value.protocol.canonical_value())
    protocol.pop("seed_hex")
    return {
        "protocol": protocol,
        "sampling_source_stratum_hash": value.sampling_source_stratum_hash,
        "planned_pair_count": value.planned_pair_count,
        "pairs": [item.canonical_value() for item in value.pairs],
    }


def _drift_value(value: DriftObservation) -> dict[str, object]:
    return {
        "observation_id": value.observation_id,
        "stratum": value.stratum.canonical_value(),
        "effect": str(value.effect),
    }


def _suite_value(value: FrozenMetricSuite) -> dict[str, object]:
    return {
        "definitions": [
            {
                "key": item.key.value,
                "version": item.version,
                "value_kind": item.value_kind.value,
                "judge_kind": item.judge_kind.value if item.judge_kind is not None else None,
            }
            for item in value.definitions
        ],
        "judge_version": value.judge_version.canonical_value(),
        "rule_versions": value.rule_versions.canonical_value(),
        "minimum_valid_completion": str(value.minimum_valid_completion),
    }


def _metric_model_program(metric_suite: FrozenMetricSuite) -> dict[str, object]:
    return {
        "admitted_by": str(uuid4()),
        "admitted_at": NOW.isoformat(),
        "judges": [
            _metric_evaluator("judge-a", metric_suite.judge_version.prompt_release_id, "9" * 64),
            _metric_evaluator("judge-b", metric_suite.judge_version.prompt_release_id, "9" * 64),
        ],
        "arbiter": _metric_evaluator("arbiter-a", uuid4(), "a" * 64),
    }


def _metric_evaluator(
    evaluator_id: str, prompt_release_id, prompt_release_hash: str
) -> dict[str, object]:
    option_id = uuid4()
    return {
        "evaluator_id": evaluator_id,
        "runtime_selection_id": str(option_id),
        "runtime_manifest_id": str(uuid4()),
        "runtime_manifest_hash": "1" * 64,
        "runtime_option_id": str(option_id),
        "runtime_option_hash": "2" * 64,
        "prompt_binding_id": str(uuid4()),
        "prompt_binding_version": 1,
        "prompt_frozen_state_id": str(uuid4()),
        "prompt_state_version": 1,
        "prompt_release_id": str(prompt_release_id),
        "prompt_release_version": 1,
        "prompt_release_hash": prompt_release_hash,
        "prompt_purpose": "monitoring.metric_arbiter"
        if evaluator_id == "arbiter-a"
        else "monitoring.metric_judge",
        "prompt_bundle_hash": "3" * 64,
        "request": {
            "messages": [{"role": "system", "content": "Return JSON."}],
            "configured_model": "review-provider/model-v1",
            "temperature": 0.1,
            "max_output_tokens": 256,
            "output_schema": {"type": "object"},
            "application_output_schema": {"type": "object"},
            "seed": 1,
            "tool_mode": None,
            "search_mode": None,
            "deadline_at": None,
        },
    }


def _semantic_inputs_fixture() -> tuple[MetricInputSet, FrozenMetricSuite]:
    input_set = MetricInputSet(
        stratum=SemanticStratum((("capture_method", "provider_api"), ("locale", "en-AU"))),
        planned_slots=(PlannedMetricSlot("slot-1", "question-1", "purchase"),),
        observations=(
            MetricObservation(
                id=uuid4(),
                slot_id="slot-1",
                payload_hash="7" * 64,
                question_id="question-1",
                question_cluster="purchase",
                answer_text="Advinsys is mentioned in this answer.",
            ),
        ),
        subjects=SubjectInventory(
            primary_subject_key="advinsys",
            brand_aliases=("Advinsys",),
            product_aliases=("Advinsys Suite",),
            competitors=(),
        ),
        approved_facts=(),
        verified_urls=("https://example.com",),
        approved_corpus_version="corpus-v1",
        approved_corpus_hash="8" * 64,
    )
    suite = FrozenMetricSuite(
        definitions=(
            MetricDefinition(
                MetricKey.BRAND_MENTION,
                "semantic-metric-v1",
                MetricValueKind.BINARY_RATE,
            ),
        ),
        judge_version=JudgeVersion(
            key="metric-judge",
            version="metric-judge-v1",
            prompt_release_id=uuid4(),
            prompt_release_hash="9" * 64,
            model_identity="review-provider/model-v1",
            schema_version="metric-judge-output-v1",
        ),
        rule_versions=DeterministicRuleVersions(
            subject="subject-rule-v1",
            url="url-rule-v1",
            citation_order="citation-order-v1",
            denominator="denominator-rule-v1",
            mention="mention-rule-v1",
        ),
    )
    return input_set, suite


def _spec(kind: str, payload: dict[str, object]) -> WorkflowCJobSpec:
    return WorkflowCJobSpec(
        project_id=uuid4(),
        job_id=uuid4(),
        kind=kind,
        spec_hash=_hash(payload),
        payload=payload,
        created_at=NOW,
    )


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _unused_lease(kind: str) -> WorkerLease:
    return WorkerLease(
        job_id=uuid4(),
        project_id=uuid4(),
        kind=kind,
        worker_id="test",
        lease_token=uuid4(),
        fencing_generation=1,
        attempt_count=1,
        max_attempts=3,
    )
