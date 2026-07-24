from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import timedelta
import hashlib
from uuid import UUID, uuid4

import pytest

from geo_core.jobs.postgres import JobCancellationRequested, LostJobLease, WorkerLease
from geo_core.model_gateway.contracts import ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.execution_contracts import (
    FrozenEvidence,
    FrozenPromptRef,
    StyleProfileBuildOutput,
    StyleProfileBuildTask,
    SyntheticExecutionStale,
)
from geo_core.synthetic_lab.execution_application import SyntheticExecutionApplication
from geo_core.synthetic_lab.execution_worker import SyntheticExecutionHandler
from geo_core.synthetic_lab.postgres_worker import build_synthetic_worker_handlers
from geo_core.synthetic_lab.memory import (
    InMemorySyntheticLabStore,
    InMemorySyntheticLabUnitOfWorkFactory,
)
from geo_core.synthetic_lab.ports import (
    LabPrincipal,
    LabRole,
    RuntimeInputSnapshot,
    StaticRuntimeInputPort,
    SyntheticLabPersistenceError,
)


PROJECT_ID = UUID("30000000-0000-0000-0000-000000000001")


class FakeStore:
    def __init__(self) -> None:
        self.heartbeats = 0
        self.signal_on_heartbeat: BaseException | None = None
        self.completed: list[tuple[object, WorkerLease, str, object]] = []
        self.failures: list[tuple[str, object, timedelta | None]] = []
        self.connection = object()

    def heartbeat(self, lease: WorkerLease, *, lease_for: timedelta) -> None:
        del lease, lease_for
        self.heartbeats += 1
        if self.signal_on_heartbeat is not None:
            raise self.signal_on_heartbeat

    @contextmanager
    def fenced_transaction(self, lease: WorkerLease):
        del lease
        yield self.connection

    def complete_in_transaction(
        self,
        connection,
        lease,
        *,
        result_ref: str,
        details,
    ) -> None:
        self.completed.append((connection, lease, result_ref, details))

    def fail(
        self,
        lease,
        *,
        error_code: str,
        details,
        retry_delay: timedelta | None,
    ) -> str:
        del lease
        self.failures.append((error_code, details, retry_delay))
        return "retry_wait" if retry_delay is not None else "failed"


class FakeRepository:
    def __init__(self, task: StyleProfileBuildTask) -> None:
        self.task = task
        self.finalized: list[tuple[object, object, object, object, object]] = []

    def load(self, lease: WorkerLease):
        del lease
        return self.task

    def finalize(self, *, connection, lease, task, output, runtime) -> None:
        self.finalized.append((connection, lease, task, output, runtime))


class FakeRuntimePort:
    def __init__(self, current: RuntimeInputSnapshot) -> None:
        self.value = current
        self.calls = 0

    def current(self, frozen: RuntimeInputSnapshot) -> RuntimeInputSnapshot:
        del frozen
        self.calls += 1
        return self.value


class FakePrompts:
    def __init__(self) -> None:
        self.calls = 0
        self.error: BaseException | None = None

    def assert_current(self, frozen: FrozenPromptRef) -> None:
        del frozen
        self.calls += 1
        if self.error is not None:
            raise self.error


class FakeExecutor:
    def __init__(self, output: StyleProfileBuildOutput) -> None:
        self.output = output
        self.error: BaseException | None = None

    def run(self, *, lease, task, checkpoint):
        del lease, task
        checkpoint()
        if self.error is not None:
            raise self.error
        checkpoint()
        return self.output


def test_worker_checkpoints_and_atomically_finalizes_under_fence() -> None:
    runtime = _runtime()

    result = runtime.handler.handle(runtime.lease)

    assert result["status"] == "succeeded"
    assert runtime.store.heartbeats == 4
    assert runtime.runtime.calls == 4
    assert runtime.prompts.calls == 4
    assert len(runtime.repository.finalized) == 1
    assert len(runtime.store.completed) == 1
    assert runtime.repository.finalized[0][0] is runtime.store.connection
    assert runtime.store.completed[0][0] is runtime.store.connection
    assert runtime.store.completed[0][3]["task_input_hash"] == runtime.task.input_hash


def test_worker_fails_permanently_when_fact_snapshot_is_no_longer_current() -> None:
    runtime = _runtime()
    runtime.runtime.value = replace(runtime.task.runtime_inputs, facts_current_approved=False)

    result = runtime.handler.handle(runtime.lease)

    assert result["status"] == "failed"
    assert runtime.store.failures == [
        ("synthetic_runtime_stale", {"classification": "stale_input"}, None)
    ]
    assert not runtime.repository.finalized
    assert not runtime.store.completed


def test_worker_fails_permanently_when_prompt_binding_changes() -> None:
    runtime = _runtime()
    runtime.prompts.error = SyntheticExecutionStale("do not persist this detail")

    result = runtime.handler.handle(runtime.lease)

    assert result["status"] == "failed"
    assert runtime.store.failures[0] == (
        "synthetic_runtime_stale",
        {"classification": "stale_input"},
        None,
    )


@pytest.mark.parametrize(
    "signal",
    (
        JobCancellationRequested("cancelled fixture"),
        LostJobLease("fenced fixture"),
    ),
)
def test_worker_propagates_cancel_and_fence_without_terminal_write(signal: BaseException) -> None:
    runtime = _runtime()
    runtime.store.signal_on_heartbeat = signal

    with pytest.raises(type(signal)):
        runtime.handler.handle(runtime.lease)

    assert not runtime.store.failures
    assert not runtime.repository.finalized
    assert not runtime.store.completed


def test_worker_never_persists_unknown_exception_message() -> None:
    runtime = _runtime()
    runtime.executor.error = RuntimeError("PII secret@example.test token=top-secret")

    result = runtime.handler.handle(runtime.lease)

    assert result["status"] == "retry_wait"
    error_code, details, retry = runtime.store.failures[0]
    assert error_code == "synthetic_execution_internal"
    assert details == {"classification": "RuntimeError"}
    assert retry == timedelta(seconds=30)
    assert "secret@example.test" not in repr(runtime.store.failures)


def test_legacy_revision_job_cannot_run_the_whole_review_case_executor() -> None:
    runtime = _runtime(kind="candidate_revision")

    result = runtime.handler.handle(runtime.lease)

    assert result["status"] == "failed"
    assert runtime.store.failures[0][0] == "synthetic_execution_contract"
    assert not runtime.repository.finalized


def test_execution_enqueue_atomically_stages_job_exact_task_outbox_and_receipt() -> None:
    task = _task()
    store = InMemorySyntheticLabStore()
    app = SyntheticExecutionApplication(InMemorySyntheticLabUnitOfWorkFactory(store))
    prompts = FakePrompts()
    principal = LabPrincipal(
        project_id=PROJECT_ID,
        actor_id=task.requested_by,
        roles=frozenset({LabRole.OPERATOR}),
    )
    outbox_id = uuid4()

    first = app.enqueue(
        principal=principal,
        task=task,
        outbox_id=outbox_id,
        runtime_inputs=StaticRuntimeInputPort(task.runtime_inputs),
        prompts=prompts,  # type: ignore[arg-type]
        idempotency_key="style-profile-execution-v1",
    )
    replay = app.enqueue(
        principal=principal,
        task=task,
        outbox_id=outbox_id,
        runtime_inputs=StaticRuntimeInputPort(task.runtime_inputs),
        prompts=prompts,  # type: ignore[arg-type]
        idempotency_key="style-profile-execution-v1",
    )

    assert first.result.kind == "style.profile.build"
    assert first.result.input_hash == task.input_hash
    assert replay.replayed is True
    assert store.job_count(PROJECT_ID) == 1
    assert store.outbox_count(PROJECT_ID) == 1
    assert store.command_count(PROJECT_ID) == 1
    assert store.get_execution_task(project_id=PROJECT_ID, job_id=task.job_id) == task


def test_execution_enqueue_commit_failure_leaves_no_runnable_or_unstaged_job() -> None:
    task = _task()
    store = InMemorySyntheticLabStore()
    store.fail_next_commit()
    app = SyntheticExecutionApplication(InMemorySyntheticLabUnitOfWorkFactory(store))
    principal = LabPrincipal(
        project_id=PROJECT_ID,
        actor_id=task.requested_by,
        roles=frozenset({LabRole.OPERATOR}),
    )

    with pytest.raises(SyntheticLabPersistenceError, match="simulated"):
        app.enqueue(
            principal=principal,
            task=task,
            outbox_id=uuid4(),
            runtime_inputs=StaticRuntimeInputPort(task.runtime_inputs),
            prompts=FakePrompts(),  # type: ignore[arg-type]
            idempotency_key="style-profile-execution-fail",
        )

    assert store.job_count(PROJECT_ID) == 0
    assert store.outbox_count(PROJECT_ID) == 0
    assert store.get_execution_task(project_id=PROJECT_ID, job_id=task.job_id) is None


@dataclass(frozen=True)
class _WorkerRuntime:
    handler: SyntheticExecutionHandler
    lease: WorkerLease
    task: StyleProfileBuildTask
    store: FakeStore
    repository: FakeRepository
    runtime: FakeRuntimePort
    prompts: FakePrompts
    executor: FakeExecutor


def _runtime(*, kind: str = "style.profile.build") -> _WorkerRuntime:
    task = _task()
    lease = WorkerLease(
        job_id=task.job_id,
        project_id=PROJECT_ID,
        kind=kind,
        worker_id="synthetic-test-worker",
        lease_token=uuid4(),
        fencing_generation=1,
        attempt_count=1,
        max_attempts=3,
    )
    store = FakeStore()
    repository = FakeRepository(task)
    runtime = FakeRuntimePort(task.runtime_inputs)
    prompts = FakePrompts()
    output = StyleProfileBuildOutput(
        project_id=PROJECT_ID,
        profile_version_id=task.profile_version_id,
        profile_hash=_hash("built-profile"),
        artifact_hash=_hash("profile-artifact"),
        model_call_ids=(uuid4(),),
    )
    executor = FakeExecutor(output)
    handler = SyntheticExecutionHandler(
        store=store,  # type: ignore[arg-type]
        repository=repository,
        runtime_inputs=runtime,
        prompts=prompts,  # type: ignore[arg-type]
        executor=executor,  # type: ignore[arg-type]
        lease_for=timedelta(minutes=2),
    )
    return _WorkerRuntime(handler, lease, task, store, repository, runtime, prompts, executor)


def _task() -> StyleProfileBuildTask:
    runtime = RuntimeInputSnapshot(
        project_id=PROJECT_ID,
        fact_snapshot_id=uuid4(),
        fact_snapshot_hash=_hash("facts-v1"),
        profile_version_id=uuid4(),
        profile_hash=_hash("profile-draft-v1"),
        prompt_release_id=uuid4(),
        prompt_release_hash=_hash("profile-prompt-v1"),
        facts_current_approved=True,
        profile_frozen=True,
        prompt_frozen=True,
    )
    prompt = FrozenPromptRef(
        project_id=PROJECT_ID,
        binding_id=uuid4(),
        binding_version=1,
        frozen_state_id=uuid4(),
        frozen_state_version=1,
        release_id=runtime.prompt_release_id,
        release_version=1,
        release_hash=runtime.prompt_release_hash,
        program_kind=ProgramKind.STYLE_PROFILE,
        purpose="synthetic_lab.style_profile",
        route=ModelRoute(
            provider="openai",
            adapter_release_id="openai-adapter-v1",
            adapter_release_hash=_hash("adapter-v1"),
            model_release_id="judge-v1",
            model_release_hash=_hash("model-v1"),
        ),
        configured_model="judge-v1",
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash=_hash("runtime-manifest-v1"),
        runtime_option_id=uuid4(),
        runtime_option_hash=_hash("runtime-option-v1"),
        model_policy=ModelPolicy(),
        model_policy_hash=_hash("policy-v1"),
    )
    return StyleProfileBuildTask(
        project_id=PROJECT_ID,
        job_id=uuid4(),
        model_job_version=1,
        requested_by=uuid4(),
        profile_version_id=runtime.profile_version_id,
        profile_id=uuid4(),
        version_number=1,
        channel="reddit",
        locale="en-AU",
        corpus_hash=_hash("corpus-v1"),
        approved_sample_count=200,
        sample_manifest_hash=_hash("sample-manifest-v1"),
        sample_style_evidence=(
            FrozenEvidence(
                ref="sample-manifest:1",
                subject_id="style:reddit",
                summary="Approved anonymous Australian English style evidence.",
            ),
        ),
        runtime_inputs=runtime,
        prompt=prompt,
    )


def test_shared_worker_builder_registers_only_non_browser_execution_kinds() -> None:
    runtime = _runtime()
    child_repository = _FakeChildRepository()
    handlers = build_synthetic_worker_handlers(
        store=runtime.store,
        connection_factory=lambda: None,
        runtime_inputs=runtime.runtime,
        prompts=runtime.prompts,  # type: ignore[arg-type]
        child_calls=runtime.executor,  # type: ignore[arg-type]
        child_lifecycle=child_repository,
        child_repository=child_repository,
        child_model_gateway=runtime.executor,  # type: ignore[arg-type]
        lease_for=timedelta(minutes=2),
    )

    assert set(handlers) == {
        "style.profile.build",
        "review.case.run",
        "offline_experiment.run",
        "synthetic.model.call",
    }
    assert "style.collect" not in handlers
    assert len({id(handler) for handler in handlers.values()}) == 2


class _FakeChildRepository:
    def block_unstarted(self, **values) -> None:
        del values

    def load_claimed(self, lease):
        del lease
        raise AssertionError("builder contract test must not execute child")

    def assert_parent_active(self, lease) -> None:
        del lease


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
