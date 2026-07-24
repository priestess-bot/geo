from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from geo_core.jobs.postgres import WorkerLease
from geo_core.secrets import EnvelopeCipher, MasterKeyring
from geo_core.semantic_metrics import (
    MetricJudgeCandidate,
    plan_metric_judge_batches,
    resolve_metric_judge_candidates,
)
from geo_core.semantic_metrics.program_output import ParsedMetricJudgeProgramOutput
from geo_core.workflow_c_metric_arbiter_admission import (
    PostgresWorkflowCMetricArbiterAdmissionRepository,
)
from geo_core.workflow_c_metric_parent_admission import MetricArbiterEvaluatorAdmission
from geo_core.workflow_c_metric_judge_worker_contracts import ModelRequestTask


NOW = datetime(2026, 7, 23, 11, 0, tzinfo=UTC)


def test_metric_arbiter_admission_uses_frozen_parent_lease_and_expected_child(
    metric_input_set, metric_suite
) -> None:
    lease = _lease()
    batch = plan_metric_judge_batches(
        input_set=metric_input_set,
        suite=metric_suite,
        observation=metric_input_set.observations[0],
    )[0]
    result = metric_input_set.observations[0].judge_outputs[0]
    resolution = resolve_metric_judge_candidates(
        (
            MetricJudgeCandidate.create(
                candidate_id=str(uuid4()),
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
    connection = _Connection()
    repository = PostgresWorkflowCMetricArbiterAdmissionRepository(cipher=_cipher())

    admitted = repository.admit_in_transaction(
        connection,
        lease=lease,
        parent_input_hash="f" * 64,
        input_set=metric_input_set,
        batch=batch,
        resolution=resolution,
        evaluator=_evaluator(),
        admitted_by=uuid4(),
        admitted_at=NOW,
    )

    assert admitted.child_job_id == UUID(connection.payload["id"])
    assert (
        str(admitted.batch_id)
        == connection.payload["spec_payload"]["metric_model_child"]["batch_id"]
    )
    query, args = connection.calls[0]
    assert "geo_admit_workflow_c_metric_arbiter_child" in query
    assert args[:5] == (
        lease.project_id,
        lease.job_id,
        lease.lease_token,
        lease.fencing_generation,
        "f" * 64,
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


def _evaluator() -> MetricArbiterEvaluatorAdmission:
    option_id = uuid4()
    return MetricArbiterEvaluatorAdmission(
        evaluator_id="arbiter-a",
        runtime_selection_id=option_id,
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash="1" * 64,
        runtime_option_id=option_id,
        runtime_option_hash="2" * 64,
        prompt_binding_id=uuid4(),
        prompt_binding_version=1,
        prompt_frozen_state_id=uuid4(),
        prompt_state_version=1,
        prompt_release_id=uuid4(),
        prompt_release_version=1,
        prompt_release_hash="3" * 64,
        prompt_purpose="monitoring.metric_arbiter",
        prompt_bundle_hash="4" * 64,
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


def _cipher() -> EnvelopeCipher:
    return EnvelopeCipher(MasterKeyring(keys={1: b"a" * 32}, active_version=1))


class _Result:
    def __init__(self, row: tuple[UUID]) -> None:
        self._row = row

    def fetchone(self) -> tuple[UUID]:
        return self._row


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.payload: dict[str, object] = {}

    def execute(self, query: str, args: tuple[object, ...]) -> _Result:
        self.calls.append((query, args))
        payload = args[-1]
        assert isinstance(payload, str)
        import json

        self.payload = json.loads(payload)
        return _Result((UUID(self.payload["id"]),))
