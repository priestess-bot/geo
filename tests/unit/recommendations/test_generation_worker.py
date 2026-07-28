from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import inspect
from typing import Any, cast
from typing import get_type_hints
from uuid import UUID, uuid4

import pytest

from geo_core.jobs.postgres import JobCancellationRequested, LostJobLease, WorkerLease
from geo_core.model_gateway import (
    ModelCallUnknownOutcome,
    ModelGatewayResult,
    RetryableModelGatewayError,
)
from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.model_gateway.runtime_execution import (
    ModelCallJobAdmitter,
    ModelCallRuntimeLoader,
)
from geo_core.recommendations.generation_contracts import ResolvedGenerationPrompt
from geo_core.recommendations.generation_artifacts import RecommendationTaskArtifactRef
from geo_core.recommendations.generation_ports import (
    RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA,
    RECOMMENDATION_OUTPUT_SCHEMA,
    structured_generation_input,
)
from geo_core.recommendations.generation_worker_contracts import (
    RECOMMENDATION_PARENT_JOB_KIND,
    RECOMMENDATION_PRIMARY_MODEL_JOB_KIND,
    RecommendationChildStatus,
    RecommendationDifyResultRef,
    RecommendationExecutionBackend,
    RecommendationModelOutcome,
    RecommendationModelRole,
    RecommendationModelResultRef,
    RecommendationModelTask,
    RecommendationParentClaim,
)
from geo_core.recommendations.postgres.generation_worker import (
    RecommendationGenerationWorkerRepository,
    RecommendationModelChildHandler,
    RecommendationParentHandler,
)
from geo_core.workflow_runtime import WorkflowExecutionResult
from geo_core.workflow_runtime.contracts import canonical_json_hash as workflow_hash

from .generation_test_support import (
    NOW,
    PROJECT_ID,
    PromptResolverStub,
    arbiter_output,
    generation_spec,
    model_result,
    model_output,
    worker_lease,
)


class _Store:
    def __init__(self) -> None:
        self.connection = object()
        self.deferred: list[tuple[str, dict[str, object], timedelta]] = []
        self.completed: list[tuple[str, dict[str, object]]] = []
        self.failures: list[tuple[str, timedelta | None]] = []
        self.transaction_failures: list[tuple[str, str, timedelta | None]] = []
        self.heartbeats = 0

    @contextmanager
    def fenced_transaction(self, lease: WorkerLease):
        del lease
        yield self.connection

    def heartbeat(self, lease: WorkerLease, *, lease_for: timedelta) -> None:
        del lease, lease_for
        self.heartbeats += 1

    def defer_in_transaction(
        self,
        connection: object,
        lease: WorkerLease,
        *,
        reason_code: str,
        details: dict[str, object],
        retry_delay: timedelta,
    ) -> None:
        assert connection is self.connection
        del lease
        self.deferred.append((reason_code, dict(details), retry_delay))

    def complete_in_transaction(
        self,
        connection: object,
        lease: WorkerLease,
        *,
        result_ref: str,
        details: dict[str, object],
    ) -> None:
        assert connection is self.connection
        del lease
        self.completed.append((result_ref, dict(details)))

    def fail(
        self,
        lease: WorkerLease,
        *,
        error_code: str,
        details: dict[str, object],
        retry_delay: timedelta | None,
    ) -> str:
        del lease
        assert details["classification"] == "recommendation_generation"
        self.failures.append((error_code, retry_delay))
        return "retry_wait" if retry_delay is not None else "failed"

    def fail_in_transaction(
        self,
        connection: object,
        lease: WorkerLease,
        *,
        error_code: str,
        details: dict[str, object],
    ) -> None:
        assert connection is self.connection
        del lease
        assert details["classification"] == "recommendation_model"
        self.transaction_failures.append(("failed", error_code, None))

    def fail_with_retry_in_transaction(
        self,
        connection: object,
        lease: WorkerLease,
        *,
        error_code: str,
        details: dict[str, object],
        retry_delay: timedelta,
    ) -> str:
        assert connection is self.connection
        assert details["classification"] == "recommendation_model"
        status = "retry_wait" if lease.attempt_count < lease.max_attempts else "dead_lettered"
        self.transaction_failures.append((status, error_code, retry_delay))
        return status


class _Repository:
    def __init__(self, claim: RecommendationParentClaim) -> None:
        self.claim = claim
        self.prompts = PromptResolverStub()
        self.parent_loads = 0
        self.child_loads = 0
        self.staged: list[RecommendationModelTask] = []
        self.artifacts: list[RecommendationTaskArtifactRef] = []
        self.finalized: list[object] = []
        self.successes: list[tuple[RecommendationModelTask, RecommendationModelResultRef]] = []
        self.model_failures: list[tuple[RecommendationModelTask, str, str]] = []
        self.woken: list[UUID] = []
        self.workflow_release_id = uuid4()
        self.workflow_release_hash = "7" * 64

    def load_parent(self, lease: WorkerLease) -> RecommendationParentClaim:
        assert lease.job_id != UUID(int=0)
        self.parent_loads += 1
        return self.claim

    def assert_current_inputs(self, spec) -> None:
        assert spec.project_id == PROJECT_ID

    def resolve_prompt(
        self,
        *,
        spec,
        role: RecommendationModelRole,
        structured_input,
        output_schema,
        application_output_schema,
    ) -> ResolvedGenerationPrompt:
        primary = role is RecommendationModelRole.PRIMARY
        return self.prompts.resolve(
            binding=spec.prompt_binding if primary else spec.arbiter_binding,
            route=spec.route if primary else spec.arbiter_route,
            configured_model=(spec.configured_model if primary else spec.arbiter_configured_model),
            model_policy=spec.model_policy if primary else spec.arbiter_model_policy,
            capture_method=(spec.capture_method if primary else spec.arbiter_capture_method),
            search_mode=spec.search_mode if primary else spec.arbiter_search_mode,
            structured_input=structured_input,
            output_schema=output_schema,
            application_output_schema=application_output_schema,
        )

    def resolve_workflow_release(self, *, task_role, prompt):
        assert prompt.binding.project_id == PROJECT_ID
        if task_role is RecommendationModelRole.ARBITER:
            return None
        return self.workflow_release_id, self.workflow_release_hash

    def prepare_model_task(self, task) -> RecommendationTaskArtifactRef:
        artifact = RecommendationTaskArtifactRef(
            uri=f"s3://recommendations/tasks/{task.child_job_id}.json",
            manifest_hash="d" * 64,
            payload_uri=f"s3://recommendations/tasks/{task.child_job_id}.bin",
            payload_hash="f" * 64,
            content_hash="e" * 64,
            byte_size=256,
        )
        self.artifacts.append(artifact)
        return artifact

    def reserve_model_task(self, *, connection, lease, task) -> None:
        assert connection is not None and task.parent_job_id == lease.job_id
        self.staged.append(task)

    def activate_model_task(self, *, connection, lease, task, artifact) -> None:
        assert connection is not None and task.parent_job_id == lease.job_id
        assert artifact == self.artifacts[-1]

    def load_model_task(self, lease: WorkerLease) -> RecommendationModelTask:
        self.child_loads += 1
        return next(task for task in self.staged if task.child_job_id == lease.job_id)

    def record_model_success(self, *, connection, lease, task, reference) -> None:
        assert connection is not None and task.child_job_id == lease.job_id
        self.successes.append((task, reference))

    def record_model_failure(self, *, connection, lease, task, status, error_code) -> None:
        assert connection is not None and task.child_job_id == lease.job_id
        self.model_failures.append((task, status, error_code))

    def wake_parent(self, *, connection, lease, task) -> None:
        assert connection is not None and task.child_job_id == lease.job_id
        self.woken.append(task.parent_job_id)

    def finalize_parent(self, *, connection, lease, result) -> None:
        assert connection is not None and result.recommendation.project_id == lease.project_id
        self.finalized.append(result)


class _Admitter:
    def __init__(self, job: object) -> None:
        self.job = job
        self.requests: list[object] = []

    def load_or_admit_claimed_job(self, request):
        self.requests.append(request)
        return SimpleNamespace(job=self.job)


class _Loader:
    def __init__(self, job: object, application: object, policy: object) -> None:
        self.runtime = SimpleNamespace(job=job, application=application, policy=policy)
        self.loads: list[tuple[UUID, UUID]] = []

    def load(self, *, project_id: UUID, job_id: UUID):
        self.loads.append((project_id, job_id))
        return self.runtime


class _Application:
    def __init__(self, action: ModelGatewayResult | BaseException) -> None:
        self.action = action
        self.commands: list[object] = []

    def execute(self, command, *, policy):
        del policy
        self.commands.append(command)
        if isinstance(self.action, BaseException):
            raise self.action
        return SimpleNamespace(
            result=self.action,
            attempt=SimpleNamespace(spec=SimpleNamespace(id=uuid4())),
            terminal_event=SimpleNamespace(output_hash="9" * 64),
        )


class _WorkflowExecutor:
    def __init__(self, action: WorkflowExecutionResult | BaseException) -> None:
        self.action = action
        self.frozen_calls: list[tuple[UUID, str, object]] = []

    def execute_optional(self, *args, **kwargs):
        raise AssertionError("Recommendation Dify child must not resolve the active binding")

    def execute_frozen(
        self,
        lease,
        request,
        *,
        release_id,
        release_hash,
        validate_output=None,
    ):
        del lease
        self.frozen_calls.append((release_id, release_hash, request))
        if isinstance(self.action, BaseException):
            raise self.action
        if validate_output is not None:
            validate_output(self.action.output)
        return self.action


def test_parent_stages_only_primary_child_and_defers_without_consuming_it() -> None:
    store, repository, handler, parent = _parent_runtime(generation_spec())

    result = handler.handle(parent)

    assert result["status"] == "retry_wait"
    assert repository.parent_loads == 1
    assert repository.child_loads == 0
    assert len(repository.staged) == 1
    task = repository.staged[0]
    assert task.role is RecommendationModelRole.PRIMARY
    assert task.parent_job_id == parent.job_id
    assert task.child_job_id != parent.job_id
    assert task.runtime_selection_id == task.runtime_option_id
    assert task.execution_backend is RecommendationExecutionBackend.DIFY
    assert task.workflow_release_id == repository.workflow_release_id
    assert task.structured_input
    assert store.deferred[0][0] == "waiting_primary"


def test_worker_repository_persists_only_artifact_and_result_references() -> None:
    stage = inspect.signature(
        RecommendationGenerationWorkerRepository.reserve_model_task
    ).parameters
    activate = inspect.signature(
        RecommendationGenerationWorkerRepository.activate_model_task
    ).parameters
    hints = get_type_hints(RecommendationGenerationWorkerRepository.record_model_success)

    assert "artifact" not in stage
    assert "artifact" in activate
    assert "result" not in activate and "execution" not in activate
    assert hints["reference"] == RecommendationModelResultRef | RecommendationDifyResultRef


def test_parent_finalizes_successful_primary_result_without_an_arbiter() -> None:
    spec = generation_spec()
    result = model_result(spec, model_output())
    primary = RecommendationModelOutcome(
        child_job_id=uuid4(),
        role=RecommendationModelRole.PRIMARY,
        status=RecommendationChildStatus.SUCCEEDED,
        result=result,
    )
    store, repository, handler, parent = _parent_runtime(
        spec, claim=RecommendationParentClaim(spec, primary=primary)
    )

    outcome = handler.handle(parent)

    assert outcome["status"] == "succeeded"
    assert repository.finalized[0].model_call_ids == (result.call_log_id,)
    assert store.completed[0][0].startswith("recommendation:")


def test_parent_stages_arbiter_after_primary_and_finalizes_two_call_lineage() -> None:
    spec = generation_spec(with_arbiter=True)
    primary_result = model_result(spec, model_output())
    primary = RecommendationModelOutcome(
        uuid4(),
        RecommendationModelRole.PRIMARY,
        RecommendationChildStatus.SUCCEEDED,
        primary_result,
    )
    store, repository, handler, parent = _parent_runtime(
        spec, claim=RecommendationParentClaim(spec, primary=primary)
    )

    first = handler.handle(parent)

    assert first["status"] == "retry_wait"
    arbiter_task = repository.staged[0]
    assert arbiter_task.role is RecommendationModelRole.ARBITER
    assert arbiter_task.execution_backend is RecommendationExecutionBackend.MODEL_GATEWAY
    assert arbiter_task.workflow_release_id is None
    assert arbiter_task.prompt.binding.purpose == "synthetic_lab.arbiter"
    repository.claim = RecommendationParentClaim(
        spec,
        primary=primary,
        arbiter=RecommendationModelOutcome(
            arbiter_task.child_job_id,
            RecommendationModelRole.ARBITER,
            RecommendationChildStatus.SUCCEEDED,
            model_result(spec, arbiter_output(model_output()), arbiter=True),
        ),
    )

    second = handler.handle(parent)

    assert second["status"] == "succeeded"
    assert len(repository.finalized[0].model_call_ids) == 2
    assert len(store.completed) == 1


def test_parent_handles_pending_failed_and_insufficient_children_without_model_io() -> None:
    spec = generation_spec()
    pending = RecommendationModelOutcome(
        uuid4(), RecommendationModelRole.PRIMARY, RecommendationChildStatus.RETRY_WAIT
    )
    store, _, handler, parent = _parent_runtime(
        spec, claim=RecommendationParentClaim(spec, primary=pending)
    )
    assert handler.handle(parent)["status"] == "retry_wait"
    assert store.deferred[0][0] == "waiting_primary"

    failed = RecommendationModelOutcome(
        uuid4(),
        RecommendationModelRole.PRIMARY,
        RecommendationChildStatus.FAILED,
        error_code="model_contract_failed",
    )
    failed_store, _, failed_handler, failed_parent = _parent_runtime(
        spec, claim=RecommendationParentClaim(spec, primary=failed)
    )
    assert failed_handler.handle(failed_parent)["status"] == "failed"
    assert failed_store.failures == [("model_contract_failed", None)]

    insufficient_store, insufficient_repo, insufficient_handler, insufficient_parent = (
        _parent_runtime(generation_spec(real_observations=1))
    )
    assert insufficient_handler.handle(insufficient_parent)["status"] == "succeeded"
    assert not insufficient_repo.staged
    assert insufficient_repo.finalized[0].recommendation.recommendation_type.value == (
        "insufficient_evidence"
    )
    assert len(insufficient_store.completed) == 1


def test_child_admits_exact_prompt_runtime_executes_once_and_wakes_parent() -> None:
    runtime = _child_runtime()

    outcome = runtime.handler.handle(runtime.lease)

    assert outcome["status"] == "succeeded"
    assert len(runtime.admitter.requests) == 1
    request = runtime.admitter.requests[0]
    assert request.required_purpose == "recommendations.recommendation"
    assert request.runtime_selection_id == runtime.task.runtime_option_id
    assert request.maximum_paid_calls == 1
    assert len(runtime.application.commands) == 1
    command = runtime.application.commands[0]
    assert command.prompt_release_id == runtime.task.prompt.binding.release_id
    assert command.runtime_option_hash == runtime.task.runtime_option_hash
    assert runtime.repository.woken == [runtime.task.parent_job_id]
    assert len(runtime.repository.successes) == 1
    assert len(runtime.store.completed) == 1


def test_child_retry_is_not_woken_and_unknown_outcome_requires_manual_reconciliation() -> None:
    retry = _child_runtime(action=RetryableModelGatewayError("temporary", retry_after_seconds=12))

    retry_result = retry.handler.handle(retry.lease)

    assert retry_result["status"] == "retry_wait"
    assert retry.store.transaction_failures[0][2] == timedelta(seconds=12)
    assert not retry.repository.woken

    unknown = _child_runtime(action=ModelCallUnknownOutcome(uuid4(), provider="openai"))
    unknown_result = unknown.handler.handle(unknown.lease)

    assert unknown_result["status"] == "failed"
    assert unknown.store.transaction_failures[0][1] == "ModelCallUnknownOutcome"
    assert unknown.repository.woken == [unknown.task.parent_job_id]
    assert len(unknown.application.commands) == 1


def test_child_lineage_mismatch_fails_permanently_without_model_call() -> None:
    runtime = _child_runtime(lineage_tampered=True)

    outcome = runtime.handler.handle(runtime.lease)

    assert outcome["status"] == "failed"
    assert runtime.store.transaction_failures[0][1] == "RecommendationGenerationStale"
    assert not runtime.application.commands
    assert runtime.repository.woken == [runtime.task.parent_job_id]


def test_child_refuses_database_fallback_when_governed_result_artifact_is_missing() -> None:
    spec = generation_spec()
    result = replace(
        model_result(spec, model_output()),
        derived_artifact_reference=None,
        derived_artifact_manifest_hash=None,
        derived_artifact_content_hash=None,
    )
    runtime = _child_runtime(action=result)

    outcome = runtime.handler.handle(runtime.lease)

    assert outcome["status"] == "failed"
    assert runtime.store.transaction_failures[0][1] == ("RecommendationGenerationOutputError")
    assert not runtime.repository.successes
    assert runtime.repository.woken == [runtime.task.parent_job_id]


def test_model_task_rejects_direct_load_with_prefixed_prompt_purpose() -> None:
    runtime = _child_runtime()
    object.__setattr__(
        runtime.task.prompt.binding,
        "purpose",
        "evil.recommendations.recommendation",
    )

    with pytest.raises(ValueError, match="exact Prompt purpose"):
        RecommendationModelTask(
            child_job_id=runtime.task.child_job_id,
            parent_job_id=runtime.task.parent_job_id,
            project_id=runtime.task.project_id,
            parent_input_hash=runtime.task.parent_input_hash,
            role=runtime.task.role,
            runtime_selection_id=runtime.task.runtime_selection_id,
            runtime_manifest_id=runtime.task.runtime_manifest_id,
            runtime_manifest_hash=runtime.task.runtime_manifest_hash,
            runtime_option_id=runtime.task.runtime_option_id,
            runtime_option_hash=runtime.task.runtime_option_hash,
            prompt=runtime.task.prompt,
            admitted_by=runtime.task.admitted_by,
            artifact_expires_at=runtime.task.artifact_expires_at,
        )


@pytest.mark.parametrize(
    "signal",
    [JobCancellationRequested("cancelled"), LostJobLease("fenced")],
)
def test_child_propagates_cancel_and_fence_without_terminal_write(signal: BaseException) -> None:
    runtime = _child_runtime(action=signal)

    with pytest.raises(type(signal)):
        runtime.handler.handle(runtime.lease)

    assert not runtime.store.transaction_failures
    assert not runtime.repository.model_failures
    assert not runtime.repository.woken


def _parent_runtime(spec, *, claim=None):
    store = _Store()
    repository = _Repository(claim or RecommendationParentClaim(spec))
    handler = RecommendationParentHandler(
        store=cast(Any, store),
        repository=cast(RecommendationGenerationWorkerRepository, repository),
        clock=lambda: NOW,
    )
    return store, repository, handler, worker_lease(RECOMMENDATION_PARENT_JOB_KIND)


class _ChildRuntime:
    def __init__(
        self,
        *,
        store,
        repository,
        task,
        lease,
        application,
        admitter,
        loader,
        handler,
    ) -> None:
        self.store = store
        self.repository = repository
        self.task = task
        self.lease = lease
        self.application = application
        self.admitter = admitter
        self.loader = loader
        self.handler = handler


def _child_runtime(*, action=None, lineage_tampered: bool = False) -> _ChildRuntime:
    spec = generation_spec()
    parent = worker_lease(RECOMMENDATION_PARENT_JOB_KIND)
    repository = _Repository(RecommendationParentClaim(spec))
    prompt = repository.resolve_prompt(
        spec=spec,
        role=RecommendationModelRole.PRIMARY,
        structured_input={"frozen_evidence_input_hash": spec.evidence.input_hash},
        output_schema=RECOMMENDATION_OUTPUT_SCHEMA,
        application_output_schema=RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA,
    )
    task = RecommendationModelTask(
        child_job_id=uuid4(),
        parent_job_id=parent.job_id,
        project_id=PROJECT_ID,
        parent_input_hash=spec.input_hash,
        role=RecommendationModelRole.PRIMARY,
        runtime_selection_id=spec.runtime_selection_id,
        runtime_manifest_id=spec.runtime_manifest_id,
        runtime_manifest_hash=spec.runtime_manifest_hash,
        runtime_option_id=spec.runtime_option_id,
        runtime_option_hash=spec.runtime_option_hash,
        prompt=prompt,
        admitted_by=uuid4(),
        artifact_expires_at=spec.valid_until,
    )
    repository.staged.append(task)
    lease = worker_lease(
        RECOMMENDATION_PRIMARY_MODEL_JOB_KIND,
        job_id=task.child_job_id,
    )
    job = SimpleNamespace(
        runtime_manifest_id=task.runtime_manifest_id,
        runtime_manifest_hash=("0" * 64 if lineage_tampered else task.runtime_manifest_hash),
        runtime_option_id=task.runtime_option_id,
        runtime_option_hash=task.runtime_option_hash,
        route=task.prompt.route,
        prompt_binding_id=task.prompt.binding.binding_id,
        prompt_release_id=task.prompt.binding.release_id,
        prompt_release_hash=task.prompt.binding.release_hash,
        purpose=task.prompt.binding.purpose,
        prompt_bundle_hash=task.prompt.prompt_bundle_hash,
        output_schema_hash=canonical_json_hash(task.prompt.output_schema),
        application_output_schema_hash=canonical_json_hash(task.prompt.application_output_schema),
        policy_version_id=task.prompt.policy.policy_version_id,
        policy_version_hash=task.prompt.policy.policy_version_hash,
        provider_secret_handle=None,
        job_version=1,
    )
    result = model_result(spec, model_output())
    application = _Application(result if action is None else action)
    admitter = _Admitter(job)
    loader = _Loader(job, application, spec.model_policy)
    store = _Store()
    handler = RecommendationModelChildHandler(
        store=cast(Any, store),
        repository=cast(RecommendationGenerationWorkerRepository, repository),
        model_job_admitter=cast(ModelCallJobAdmitter, admitter),
        model_runtime_loader=cast(ModelCallRuntimeLoader, loader),
        lease_for=timedelta(seconds=30),
        clock=lambda: NOW,
    )
    return _ChildRuntime(
        store=store,
        repository=repository,
        task=task,
        lease=lease,
        application=application,
        admitter=admitter,
        loader=loader,
        handler=handler,
    )


def _dify_child_runtime(
    *,
    action: BaseException | None = None,
    output: dict[str, object] | None = None,
) -> tuple[_ChildRuntime, _WorkflowExecutor]:
    spec = generation_spec()
    parent = worker_lease(RECOMMENDATION_PARENT_JOB_KIND)
    repository = _Repository(RecommendationParentClaim(spec))
    structured_input = structured_generation_input(spec.evidence)
    prompt = repository.resolve_prompt(
        spec=spec,
        role=RecommendationModelRole.PRIMARY,
        structured_input=structured_input,
        output_schema=RECOMMENDATION_OUTPUT_SCHEMA,
        application_output_schema=RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA,
    )
    release_id = uuid4()
    release_hash = "7" * 64
    task = RecommendationModelTask(
        child_job_id=uuid4(),
        parent_job_id=parent.job_id,
        project_id=PROJECT_ID,
        parent_input_hash=spec.input_hash,
        role=RecommendationModelRole.PRIMARY,
        runtime_selection_id=spec.runtime_selection_id,
        runtime_manifest_id=spec.runtime_manifest_id,
        runtime_manifest_hash=spec.runtime_manifest_hash,
        runtime_option_id=spec.runtime_option_id,
        runtime_option_hash=spec.runtime_option_hash,
        prompt=prompt,
        admitted_by=uuid4(),
        artifact_expires_at=spec.valid_until,
        execution_backend=RecommendationExecutionBackend.DIFY,
        structured_input=structured_input,
        workflow_release_id=release_id,
        workflow_release_hash=release_hash,
    )
    repository.staged.append(task)
    lease = worker_lease(RECOMMENDATION_PRIMARY_MODEL_JOB_KIND, job_id=task.child_job_id)
    result_output = output or model_output()
    result = WorkflowExecutionResult(
        output=result_output,
        attempt_id=uuid4(),
        runtime_release_id=release_id,
        runtime_release_hash=release_hash,
        dify_task_id="dify-task",
        dify_run_id="dify-run",
        configured_model=task.prompt.configured_model,
        provider_reported_model=task.prompt.configured_model,
        prompt_tokens=10,
        completion_tokens=20,
        total_steps=3,
        elapsed_seconds=Decimal("1.2"),
        response_hash=workflow_hash(result_output),
    )
    workflows = _WorkflowExecutor(action or result)
    application = _Application(model_result(spec, model_output()))
    store = _Store()
    admitter = _Admitter(object())
    loader = _Loader(object(), application, spec.model_policy)
    handler = RecommendationModelChildHandler(
        store=cast(Any, store),
        repository=cast(RecommendationGenerationWorkerRepository, repository),
        model_job_admitter=cast(ModelCallJobAdmitter, admitter),
        model_runtime_loader=cast(ModelCallRuntimeLoader, loader),
        workflow_executor=workflows,
        lease_for=timedelta(seconds=30),
        clock=lambda: NOW,
    )
    return (
        _ChildRuntime(
            store=store,
            repository=repository,
            task=task,
            lease=lease,
            application=application,
            admitter=admitter,
            loader=loader,
            handler=handler,
        ),
        workflows,
    )
