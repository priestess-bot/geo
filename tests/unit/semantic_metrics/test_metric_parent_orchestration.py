from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from geo_core.jobs.postgres import WorkerLease
from geo_core.secrets import EnvelopeCipher, MasterKeyring
from geo_core.semantic_metrics import (
    MetricJudgeCandidate,
    SelectedMetricJudgeBatch,
    plan_metric_judge_batches,
    resolve_metric_judge_candidates,
)
from geo_core.semantic_metrics.program_output import ParsedMetricJudgeProgramOutput
from geo_core.semantic_metrics.program_output import MetricJudgeKind
from geo_core.workflow_c_metric_parent_admission import (
    MetricArbiterEvaluatorAdmission,
    MetricJudgeEvaluatorAdmission,
)
from geo_core.workflow_c_metric_parent_orchestration import (
    PersistedMetricBatch,
    PostgresWorkflowCMetricParentOrchestrator,
)
from geo_core.workflow_c_metric_parent_specs import MetricModelProgramAdmission
from geo_core.workflow_c_metric_judge_worker_contracts import ModelRequestTask
from geo_core.workflow_c_semantic_specs import SemanticMetricMetadata


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def test_metric_parent_first_admits_judges_and_defers(metric_input_set, metric_suite) -> None:
    store, progress = _Store(), _Progress(batches=())
    orchestrator = _orchestrator(store, progress)
    judge_admission = _JudgeAdmission()
    orchestrator._judge_admission = judge_admission

    result = orchestrator.execute(
        lease=_lease(),
        parent_input_hash="f" * 64,
        metadata=_metadata(),
        input_set=metric_input_set,
        suite=metric_suite,
        program=_program(metric_suite),
    )

    assert result["status"] == "waiting_for_metric_judges"
    assert judge_admission.calls == 1
    assert store.deferred == ["metric_judges_admitted"]
    assert not store.failed


def test_metric_parent_admits_arbiter_for_complete_disagreement_and_defers(
    metric_input_set, metric_suite
) -> None:
    lease = _lease()
    plan = _plans(metric_input_set, metric_suite)[0]
    batch = _running_batch(plan)
    progress = _Progress(batches=(batch,), resolution=_disagreement(metric_input_set))
    store = _Store()
    orchestrator = _orchestrator(store, progress)
    arbiter_admission = _ArbiterAdmission()
    orchestrator._arbiter_admission = arbiter_admission

    result = orchestrator.execute(
        lease=lease,
        parent_input_hash="f" * 64,
        metadata=_metadata(),
        input_set=metric_input_set,
        suite=metric_suite,
        program=_program(metric_suite),
    )

    assert result["status"] == "waiting_for_metric_judges"
    assert arbiter_admission.calls == [(plan, "arbiter-a")]
    assert store.deferred == ["metric_judges_pending"]


def test_metric_parent_merges_only_after_every_batch_is_completed(
    metric_input_set, metric_suite
) -> None:
    lease = _lease()
    plans = _plans(metric_input_set, metric_suite)
    completed = tuple(_completed_batch(plan) for plan in plans)
    selected = tuple(
        SelectedMetricJudgeBatch(batch=plan, candidate=_candidate(plan, index))
        for index, plan in enumerate(plans, 1)
    )
    store, progress = (
        _Store(),
        _Progress(batches=completed, selected=tuple(item.candidate for item in selected)),
    )
    orchestrator = _orchestrator(store, progress)
    persisted: list[tuple[SelectedMetricJudgeBatch, ...]] = []

    def persist(**kwargs):
        persisted.append(tuple(kwargs["selected"]))
        return {
            "status": "complete",
            "job_id": str(lease.job_id),
            "snapshot_hash": "a" * 64,
        }

    orchestrator._persist = persist

    result = orchestrator.execute(
        lease=lease,
        parent_input_hash="f" * 64,
        metadata=_metadata(),
        input_set=metric_input_set,
        suite=metric_suite,
        program=_program(metric_suite),
    )

    assert result["status"] == "complete"
    assert persisted == [selected]
    assert not store.deferred and not store.failed


def test_metric_parent_terminal_batch_fails_parent_without_snapshot(
    metric_input_set, metric_suite
) -> None:
    plan = _plans(metric_input_set, metric_suite)[0]
    failed = PersistedMetricBatch(
        batch_id=uuid4(),
        observation_id=plan.observation.id,
        ordinal=plan.ordinal,
        plans_hash=plan.input_hash,
        status="failed",
        selected_candidate_id=None,
        selected_output_hash=None,
        arbiter_child_job_id=None,
    )
    store, progress = _Store(), _Progress(batches=(failed,))
    orchestrator = _orchestrator(store, progress)

    result = orchestrator.execute(
        lease=_lease(),
        parent_input_hash="f" * 64,
        metadata=_metadata(),
        input_set=metric_input_set,
        suite=metric_suite,
        program=_program(metric_suite),
    )

    assert result["status"] == "failed"
    assert store.failed == ["metric_batch_terminal"]
    assert not store.deferred


def _orchestrator(
    store: "_Store", progress: "_Progress"
) -> PostgresWorkflowCMetricParentOrchestrator:
    value = PostgresWorkflowCMetricParentOrchestrator(
        store=store,
        cipher=EnvelopeCipher(MasterKeyring(keys={1: b"k" * 32}, active_version=1)),
        lease_for=timedelta(seconds=60),
        clock=lambda: NOW,
    )
    value._progress = progress
    return value


def _metadata() -> SemanticMetricMetadata:
    return SemanticMetricMetadata(
        run_id=uuid4(),
        source_stratum_hash="e" * 64,
        capture_method="provider_api",
        warning_ratio=0,
        test_only=False,
        synthetic=False,
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


def _program(metric_suite) -> MetricModelProgramAdmission:
    judge_release = metric_suite.judge_version
    return MetricModelProgramAdmission(
        admitted_by=uuid4(),
        admitted_at=NOW,
        judges=(_judge("judge-a", judge_release), _judge("judge-b", judge_release)),
        arbiter=_arbiter(),
    )


def _judge(evaluator_id: str, release) -> MetricJudgeEvaluatorAdmission:
    option_id = uuid4()
    return MetricJudgeEvaluatorAdmission(
        evaluator_id=evaluator_id,
        runtime_selection_id=option_id,
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash="1" * 64,
        runtime_option_id=option_id,
        runtime_option_hash="2" * 64,
        prompt_binding_id=uuid4(),
        prompt_binding_version=1,
        prompt_frozen_state_id=uuid4(),
        prompt_state_version=1,
        prompt_release_id=release.prompt_release_id,
        prompt_release_version=1,
        prompt_release_hash=release.prompt_release_hash,
        prompt_purpose="monitoring.metric_judge",
        prompt_bundle_hash="3" * 64,
        request=_request("judge"),
    )


def _arbiter() -> MetricArbiterEvaluatorAdmission:
    option_id = uuid4()
    return MetricArbiterEvaluatorAdmission(
        evaluator_id="arbiter-a",
        runtime_selection_id=option_id,
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash="4" * 64,
        runtime_option_id=option_id,
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
        request=_request("arbiter"),
    )


def _request(kind: str) -> ModelRequestTask:
    return ModelRequestTask(
        messages=({"role": "system", "content": "Return JSON."},),
        configured_model=f"review-provider/{kind}-v1",
        temperature=0.1,
        max_output_tokens=256,
        output_schema={"type": "object"},
        application_output_schema={"type": "object"},
        seed=1,
        tool_mode=None,
        search_mode=None,
        deadline_at=None,
    )


def _plans(metric_input_set, metric_suite):
    return tuple(
        batch
        for observation in metric_input_set.observations
        for batch in plan_metric_judge_batches(
            input_set=metric_input_set, suite=metric_suite, observation=observation
        )
    )


def _running_batch(plan) -> PersistedMetricBatch:
    return PersistedMetricBatch(
        batch_id=uuid4(),
        observation_id=plan.observation.id,
        ordinal=plan.ordinal,
        plans_hash=plan.input_hash,
        status="running",
        selected_candidate_id=None,
        selected_output_hash=None,
        arbiter_child_job_id=None,
    )


def _completed_batch(plan) -> PersistedMetricBatch:
    return PersistedMetricBatch(
        batch_id=uuid4(),
        observation_id=plan.observation.id,
        ordinal=plan.ordinal,
        plans_hash=plan.input_hash,
        status="completed",
        selected_candidate_id=uuid4(),
        selected_output_hash="f" * 64,
        arbiter_child_job_id=None,
    )


def _disagreement(metric_input_set):
    result = metric_input_set.observations[0].judge_outputs[0]
    return resolve_metric_judge_candidates(
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
                    results=(result,), overall_status="warning", output_locale="en-AU"
                ),
            ),
        )
    )


def _candidate(plan, index: int) -> MetricJudgeCandidate:
    output = ParsedMetricJudgeProgramOutput(
        results=tuple(
            replace(_output_for_plan(plan, item), metric_id=item.metric_id) for item in plan.plans
        ),
        overall_status="pass",
        output_locale="en-AU",
    )
    return MetricJudgeCandidate.create(
        candidate_id=str(uuid4()), evaluator_id=f"judge-{index}", output=output
    )


def _output_for_plan(batch, plan):
    if plan.metric_kind is MetricJudgeKind.FACT:
        reference = plan.metric_id.removeprefix("fact:")
        return next(
            output
            for output in batch.observation.judge_outputs
            if output.kind.value == plan.metric_kind.value
            and any(
                f"{locator.reference_id}@{locator.version}" == reference
                for locator in output.locators
                if locator.kind.value == "fact"
            )
        )
    if plan.metric_kind is MetricJudgeKind.CITATION_ENTAILMENT:
        reference = plan.metric_id.removeprefix("citation:")
        return next(
            output
            for output in batch.observation.judge_outputs
            if output.kind.value == plan.metric_kind.value
            and any(
                locator.reference_id == reference
                for locator in output.locators
                if locator.kind.value == "citation"
            )
        )
    return next(
        output
        for output in batch.observation.judge_outputs
        if output.kind.value == plan.metric_kind.value
    )


class _JudgeAdmission:
    def __init__(self) -> None:
        self.calls = 0

    def admit_in_transaction(self, *_args, **_kwargs):
        self.calls += 1
        return ()


class _ArbiterAdmission:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str]] = []

    def admit_in_transaction(self, *_args, **kwargs):
        self.calls.append((kwargs["batch"], kwargs["evaluator"].evaluator_id))
        return SimpleNamespace()


class _Progress:
    def __init__(self, *, batches, resolution=None, selected=()) -> None:
        self._batches = batches
        self._resolution = resolution
        self._selected = iter(selected)

    def batches_in_transaction(self, *_args, **_kwargs):
        return self._batches

    def arbiter_child_status_in_transaction(self, *_args, **_kwargs):
        return None

    def judge_resolution_in_transaction(self, *_args, **_kwargs):
        return self._resolution

    def selected_candidate_in_transaction(self, *_args, **_kwargs):
        return next(self._selected)


class _Store:
    def __init__(self) -> None:
        self.deferred: list[str] = []
        self.failed: list[str] = []

    @contextmanager
    def fenced_transaction(self, _lease):
        yield object()

    def defer_in_transaction(self, _connection, _lease, *, reason_code, **_kwargs) -> None:
        self.deferred.append(reason_code)

    def fail_in_transaction(self, _connection, _lease, *, error_code, **_kwargs) -> None:
        self.failed.append(error_code)
