from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from geo_core.jobs.postgres import WorkerLease
from geo_core.secrets import EnvelopeCipher, MasterKeyring
from geo_core.semantic_metrics import (
    MetricJudgeCandidate,
    plan_metric_judge_batches,
    resolve_metric_judge_candidates,
)
from geo_core.semantic_metrics.program_output import ParsedMetricJudgeProgramOutput
from geo_core.workflow_c_metric_judge_worker_contracts import ModelRequestTask
from geo_core.workflow_c_metric_parent_admission import (
    MetricArbiterEvaluatorAdmission,
    MetricJudgeEvaluatorAdmission,
    MetricJudgeParentAdmission,
    PostgresWorkflowCMetricJudgeParentAdmissionRepository,
    WorkflowCMetricParentAdmissionError,
    build_metric_arbiter_child_payload,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def test_metric_parent_admission_creates_secret_free_child_specs_and_encrypted_tasks(
    metric_input_set, metric_suite
) -> None:
    lease = _lease()
    admission = MetricJudgeParentAdmission(
        run_id=uuid4(),
        input_set=metric_input_set,
        suite=metric_suite,
        evaluators=(_evaluator(metric_suite, "judge-b"), _evaluator(metric_suite, "judge-a")),
        admitted_by=uuid4(),
        admitted_at=NOW,
    )
    connection = _Connection()
    repository = PostgresWorkflowCMetricJudgeParentAdmissionRepository(cipher=_cipher())

    admitted = repository.admit_in_transaction(
        connection,
        lease=lease,
        parent_input_hash="f" * 64,
        admission=admission,
    )

    payload = connection.payload
    assert len(admitted) == len(metric_input_set.observations)
    assert all(item.child_count == 2 for item in admitted)
    assert [
        child["evaluator_id"] for child in payload[0]["children"]
    ] == ["judge-a", "judge-b"]
    for batch in payload:
        assert batch["plans_hash"] != ""
        assert batch["input_set_hash"] == metric_input_set.input_set_hash
        assert batch["metric_suite_hash"] == metric_suite.suite_hash
        for child in batch["children"]:
            spec = child["spec_payload"]
            assert set(spec) == {"schema_version", "kind", "metric_model_child"}
            assert set(spec["metric_model_child"]) == {
                "child_job_id",
                "parent_job_id",
                "batch_id",
                "role",
                "parent_input_hash",
                "task_hash",
            }
            assert child["task_hash"] == spec["metric_model_child"]["task_hash"]
            assert metric_input_set.observations[0].answer_text not in json.dumps(spec)
            assert child["task_ciphertext"] != ""
            assert child["task_data_nonce"] != ""


def test_metric_parent_admission_requires_two_distinct_judges(metric_input_set, metric_suite) -> None:
    with pytest.raises(WorkflowCMetricParentAdmissionError, match="at least two"):
        MetricJudgeParentAdmission(
            run_id=uuid4(),
            input_set=metric_input_set,
            suite=metric_suite,
            evaluators=(_evaluator(metric_suite, "judge-a"),),
            admitted_by=uuid4(),
            admitted_at=NOW,
        )


def test_metric_arbiter_child_keeps_disagreeing_candidates_inside_encrypted_task(
    metric_input_set, metric_suite
) -> None:
    lease = _lease()
    batch = plan_metric_judge_batches(
        input_set=metric_input_set,
        suite=metric_suite,
        observation=metric_input_set.observations[0],
    )[0]
    first_result = metric_input_set.observations[0].judge_outputs[0]
    candidate_a_id, candidate_b_id = uuid4(), uuid4()
    candidate_a = MetricJudgeCandidate.create(
        candidate_id=str(candidate_a_id),
        evaluator_id="judge-a",
        output=ParsedMetricJudgeProgramOutput(
            results=(first_result,), overall_status="pass", output_locale="en-AU"
        ),
    )
    candidate_b = MetricJudgeCandidate.create(
        candidate_id=str(candidate_b_id),
        evaluator_id="judge-b",
        output=ParsedMetricJudgeProgramOutput(
            results=(replace(first_result, label="no"),),
            overall_status="warning",
            output_locale="en-AU",
        ),
    )
    resolution = resolve_metric_judge_candidates((candidate_b, candidate_a))

    payload = build_metric_arbiter_child_payload(
        cipher=_cipher(),
        lease=lease,
        parent_input_hash="f" * 64,
        input_set=metric_input_set,
        batch=batch,
        resolution=resolution,
        evaluator=_arbiter_evaluator("arbiter-a"),
        admitted_by=uuid4(),
        admitted_at=NOW,
    )

    spec = payload["spec_payload"]
    assert isinstance(spec, dict)
    assert spec["kind"] == "workflow_c.metric_arbiter"
    reference = spec["metric_model_child"]
    assert isinstance(reference, dict)
    assert reference["role"] == "arbiter"
    assert reference["task_hash"] == payload["task_hash"]
    serialized = json.dumps(spec, sort_keys=True)
    assert str(candidate_a_id) not in serialized
    assert metric_input_set.observations[0].answer_text not in serialized
    assert payload["task_ciphertext"] != ""


def test_metric_arbiter_child_rejects_an_agreed_judge_set(metric_input_set, metric_suite) -> None:
    batch = plan_metric_judge_batches(
        input_set=metric_input_set,
        suite=metric_suite,
        observation=metric_input_set.observations[0],
    )[0]
    output = ParsedMetricJudgeProgramOutput(
        results=(metric_input_set.observations[0].judge_outputs[0],),
        overall_status="pass",
        output_locale="en-AU",
    )
    agreed = resolve_metric_judge_candidates(
        (
            MetricJudgeCandidate.create(
                candidate_id=str(uuid4()), evaluator_id="judge-a", output=output
            ),
            MetricJudgeCandidate.create(
                candidate_id=str(uuid4()), evaluator_id="judge-b", output=output
            ),
        )
    )

    with pytest.raises(WorkflowCMetricParentAdmissionError, match="forbidden"):
        build_metric_arbiter_child_payload(
            cipher=_cipher(),
            lease=_lease(),
            parent_input_hash="f" * 64,
            input_set=metric_input_set,
            batch=batch,
            resolution=agreed,
            evaluator=_arbiter_evaluator("arbiter-a"),
            admitted_by=uuid4(),
            admitted_at=NOW,
        )


def test_metric_arbiter_child_requires_database_candidate_uuid_identities(
    metric_input_set, metric_suite
) -> None:
    batch = plan_metric_judge_batches(
        input_set=metric_input_set,
        suite=metric_suite,
        observation=metric_input_set.observations[0],
    )[0]
    result = metric_input_set.observations[0].judge_outputs[0]
    disagreement = resolve_metric_judge_candidates(
        (
            MetricJudgeCandidate.create(
                candidate_id="not-a-uuid",
                evaluator_id="judge-a",
                output=ParsedMetricJudgeProgramOutput(
                    results=(result,), overall_status="pass", output_locale="en-AU"
                ),
            ),
            MetricJudgeCandidate.create(
                candidate_id=str(uuid4()),
                evaluator_id="judge-b",
                output=ParsedMetricJudgeProgramOutput(
                    results=(replace(result, label="no"),),
                    overall_status="warning",
                    output_locale="en-AU",
                ),
            ),
        )
    )

    with pytest.raises(WorkflowCMetricParentAdmissionError, match="identity must be a UUID"):
        build_metric_arbiter_child_payload(
            cipher=_cipher(),
            lease=_lease(),
            parent_input_hash="f" * 64,
            input_set=metric_input_set,
            batch=batch,
            resolution=disagreement,
            evaluator=_arbiter_evaluator("arbiter-a"),
            admitted_by=uuid4(),
            admitted_at=NOW,
        )


def _evaluator(metric_suite, evaluator_id: str) -> MetricJudgeEvaluatorAdmission:
    runtime_option_id = uuid4()
    return MetricJudgeEvaluatorAdmission(
        evaluator_id=evaluator_id,
        runtime_selection_id=runtime_option_id,
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash="1" * 64,
        runtime_option_id=runtime_option_id,
        runtime_option_hash="2" * 64,
        prompt_binding_id=uuid4(),
        prompt_binding_version=1,
        prompt_frozen_state_id=uuid4(),
        prompt_state_version=1,
        prompt_release_id=metric_suite.judge_version.prompt_release_id,
        prompt_release_version=1,
        prompt_release_hash=metric_suite.judge_version.prompt_release_hash,
        prompt_purpose="monitoring.metric_judge",
        prompt_bundle_hash="3" * 64,
        request=ModelRequestTask(
            messages=({"role": "system", "content": "Return JSON."},),
            configured_model="review-provider/model-v1",
            temperature=0.2,
            max_output_tokens=256,
            output_schema={"type": "object"},
            application_output_schema={"type": "object"},
            seed=1,
            tool_mode=None,
            search_mode=None,
            deadline_at=None,
        ),
    )


def _arbiter_evaluator(evaluator_id: str) -> MetricArbiterEvaluatorAdmission:
    runtime_option_id = uuid4()
    return MetricArbiterEvaluatorAdmission(
        evaluator_id=evaluator_id,
        runtime_selection_id=runtime_option_id,
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash="4" * 64,
        runtime_option_id=runtime_option_id,
        runtime_option_hash="5" * 64,
        prompt_binding_id=uuid4(),
        prompt_binding_version=1,
        prompt_frozen_state_id=uuid4(),
        prompt_state_version=1,
        prompt_release_id=uuid4(),
        prompt_release_version=1,
        prompt_release_hash="6" * 64,
        prompt_purpose="monitoring.metric_arbiter",
        prompt_bundle_hash="7" * 64,
        request=ModelRequestTask(
            messages=({"role": "system", "content": "Return JSON."},),
            configured_model="review-provider/arbiter-v1",
            temperature=0.1,
            max_output_tokens=256,
            output_schema={"type": "object"},
            application_output_schema={"type": "object"},
            seed=1,
            tool_mode=None,
            search_mode=None,
            deadline_at=None,
        ),
    )


def _lease() -> WorkerLease:
    return WorkerLease(
        job_id=uuid4(),
        project_id=uuid4(),
        kind="workflow_c.analysis.semantic_metrics",
        worker_id="metric-parent-test",
        lease_token=uuid4(),
        fencing_generation=1,
        attempt_count=1,
        max_attempts=3,
    )


def _cipher() -> EnvelopeCipher:
    return EnvelopeCipher(MasterKeyring(keys={1: b"k" * 32}, active_version=1))


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _Connection:
    payload: list[dict[str, object]]

    def execute(self, query: str, params: tuple[object, ...]) -> _Cursor:
        assert "geo_admit_workflow_c_metric_judge_batches" in query
        value = params[-1]
        assert isinstance(value, str)
        self.payload = json.loads(value)
        return _Cursor(
            [
                {"batch_id": UUID(item["id"]), "child_count": len(item["children"])}
                for item in self.payload
            ]
        )
