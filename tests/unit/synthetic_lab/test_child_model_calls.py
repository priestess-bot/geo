from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
import hashlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from geo_core.jobs.postgres import JobCancellationRequested, WorkerLease
from geo_core.model_gateway.contracts import ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.child_model_calls import (
    SyntheticChildCallState,
    SyntheticChildCallStatus,
    SyntheticChildModelCallTask,
    SyntheticChildModelCallCoordinator,
    SyntheticChildModelCallPending,
    child_model_call_id,
    child_task_from_invocation,
)
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.child_task_artifacts import (
    EncryptedSyntheticChildTaskArtifactStore,
    SyntheticChildTaskArtifactRef,
)
from geo_core.synthetic_lab.child_model_worker import SyntheticChildModelCallHandler
from geo_core.synthetic_lab.artifact_keyring import SyntheticArtifactKeyring
from geo_core.synthetic_lab.execution_contracts import (
    FrozenPromptRef,
    ResolvedSyntheticPrompt,
    SyntheticExecutionBackend,
    SyntheticExecutionError,
    SyntheticManualReconciliationRequired,
    SyntheticExecutionStale,
    SyntheticModelInvocation,
    SyntheticModelResult,
    SyntheticWorkflowResult,
)
from geo_core.synthetic_lab.ports import RuntimeInputSnapshot
from geo_core.synthetic_lab.postgres_child_model_calls import (
    PostgresSyntheticChildCallRepository,
)
from geo_core.synthetic_lab.postgres_codec import decode_object, encode_object
from geo_core.workflow_runtime.errors import UnknownWorkflowOutcomeError


PROJECT_ID = UUID("32000000-0000-0000-0000-000000000001")
PARENT_JOB_ID = UUID("32000000-0000-0000-0000-000000000002")


class MemoryChildren:
    def __init__(self) -> None:
        self.states: dict[UUID, SyntheticChildCallState] = {}

    def resolve_or_stage(self, task, *, parent_lease):
        assert parent_lease.job_id == task.parent_job_id
        current = self.states.get(task.child_job_id)
        if current is None:
            current = SyntheticChildCallState(task=task, status=SyntheticChildCallStatus.QUEUED)
            self.states[task.child_job_id] = current
        return current

    def load_existing(self, invocation):
        child_id = child_model_call_id(
            parent_job_id=invocation.lease.job_id,
            step_key=invocation.step_key,
        )
        current = self.states.get(child_id)
        if current is None:
            return None
        expected = child_task_from_invocation(
            invocation,
            execution_backend=current.task.execution_backend,
            workflow_release_id=current.task.workflow_release_id,
            workflow_release_hash=current.task.workflow_release_hash,
        )
        if expected.input_hash != current.task.input_hash:
            return SyntheticChildCallState(
                task=current.task,
                status=SyntheticChildCallStatus.FAILED,
                failure_code="immutable_input_changed",
            )
        return current


class MemoryObjects:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, *, key, content, content_type, expected_hash):
        assert content_type.endswith("+encrypted")
        assert hashlib.sha256(content).hexdigest() == expected_hash
        self.objects[key] = content
        return SimpleNamespace(uri=f"s3://test-artifacts/{key}")

    def get_s3_uri(self, *, uri, expected_hash):
        prefix = "s3://test-artifacts/"
        assert uri.startswith(prefix)
        content = self.objects[uri.removeprefix(prefix)]
        assert hashlib.sha256(content).hexdigest() == expected_hash
        return SimpleNamespace(content=content)


class ChildStore:
    def __init__(self) -> None:
        self.connection = object()
        self.completions: list[tuple[str, dict[str, object]]] = []
        self.failures: list[tuple[str, timedelta | None]] = []

    def heartbeat(self, lease, *, lease_for) -> None:
        del lease, lease_for

    @contextmanager
    def fenced_transaction(self, lease):
        del lease
        yield self.connection

    def complete_in_transaction(self, connection, lease, *, result_ref, details) -> None:
        del connection, lease
        self.completions.append((result_ref, details))

    def fail(self, lease, *, error_code, details, retry_delay):
        del lease, details
        self.failures.append((error_code, retry_delay))
        return "retry_wait" if retry_delay else "failed"


class ClaimedChildRepository:
    def __init__(self, task) -> None:
        self.task = task
        self.parent_error: BaseException | None = None

    def load_claimed(self, lease):
        assert lease.job_id == self.task.child_job_id
        return self.task

    def assert_parent_active(self, lease) -> None:
        del lease
        if self.parent_error is not None:
            raise self.parent_error


class ChildRuntime:
    def __init__(self, value) -> None:
        self.value = value

    def current(self, frozen):
        del frozen
        return self.value


class ChildPrompts:
    def assert_current(self, frozen) -> None:
        del frozen


class ChildModel:
    def __init__(self, result) -> None:
        self.result = result

    def execute(self, invocation):
        assert invocation.lease.kind == "synthetic.model.call"
        return self.result


class FailingChildModel:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def execute(self, invocation):
        assert invocation.lease.kind == "synthetic.model.call"
        raise self.error


class _RecordedCursor:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row

    def fetchone(self) -> dict[str, object]:
        return self._row


class _RecordedChildConnection:
    def __init__(self, child_job_id: UUID) -> None:
        self.child_job_id = child_job_id
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.committed = False
        self.closed = False

    def execute(self, sql: str, parameters: tuple[object, ...]):
        self.calls.append((sql, parameters))
        return _RecordedCursor({"child_job_id": self.child_job_id})

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _StagedChildArtifacts:
    def __init__(self, task) -> None:
        self.task = task
        self.reference = SyntheticChildTaskArtifactRef(
            uri=f"s3://test-artifacts/children/{task.child_job_id}.bin",
            artifact_hash=_hash("child-artifact"),
        )

    def put(self, task):
        assert task == self.task
        return self.reference

    def load(self, reference, *, project_id, child_job_id, expected_input_hash):
        assert reference == self.reference
        assert project_id == self.task.project_id
        assert child_job_id == self.task.child_job_id
        assert expected_input_hash == self.task.input_hash
        return self.task


class _CapturingChildRepository(PostgresSyntheticChildCallRepository):
    def __init__(self, connection, *, artifacts) -> None:
        super().__init__(lambda: connection, artifacts=artifacts, results=object())
        self._connection = connection
        self._state_reads = 0

    def _open(self, project_id):
        assert project_id == PROJECT_ID
        return self._connection

    def _state_row(self, project_id, child_job_id):
        assert project_id == PROJECT_ID
        self._state_reads += 1
        if self._state_reads == 1:
            return None
        assert child_job_id == self._connection.child_job_id
        return {"status": "queued"}

    def _state(self, expected, row, *, parent_lease):
        assert parent_lease.job_id == expected.parent_job_id
        assert row["status"] == "queued"
        return SyntheticChildCallState(
            task=expected,
            status=SyntheticChildCallStatus.QUEUED,
        )


def test_child_identity_is_stable_per_parent_and_semantic_step() -> None:
    invocation = _invocation("evaluate:c1:claims:abc")
    first = child_task_from_invocation(invocation)
    retry = child_task_from_invocation(
        replace(
            invocation,
            lease=replace(
                invocation.lease,
                lease_token=uuid4(),
                fencing_generation=2,
                attempt_count=2,
            ),
        )
    )
    other = child_task_from_invocation(_invocation("evaluate:c1:style:abc"))

    assert first.child_job_id == retry.child_job_id
    assert first.input_hash == retry.input_hash
    assert first.child_job_id == child_model_call_id(
        parent_job_id=PARENT_JOB_ID,
        step_key="evaluate:c1:claims:abc",
    )
    assert other.child_job_id != first.child_job_id
    assert first.prompt.frozen.runtime_manifest_id == retry.prompt.frozen.runtime_manifest_id


def test_child_postgres_enqueue_freezes_both_schema_hashes_in_function_order() -> None:
    task = child_task_from_invocation(_invocation("generation:batch:1"))
    connection = _RecordedChildConnection(task.child_job_id)
    repository = _CapturingChildRepository(
        connection,
        artifacts=_StagedChildArtifacts(task),
    )

    state = repository.resolve_or_stage(task, parent_lease=_invocation("generation:batch:1").lease)

    assert state.status is SyntheticChildCallStatus.QUEUED
    assert connection.committed is True
    assert connection.closed is True
    sql, parameters = connection.calls[0]
    assert sql.count("%s") == 49
    assert len(parameters) == 49
    assert parameters[18] == task.prompt.frozen.frozen_state_version
    assert parameters[24] == task.admitted_by
    assert parameters[32:35] == ("model_gateway", None, None)
    assert parameters[42] == canonical_hash(task.prompt.output_schema)
    assert parameters[43] == canonical_hash(task.prompt.application_output_schema)
    assert parameters[44] == "s3://test-artifacts/children/%s.bin" % task.child_job_id
    assert parameters[45] == _hash("child-artifact")


def test_parent_replay_waits_then_returns_exact_completed_child_result() -> None:
    repository = MemoryChildren()
    coordinator = SyntheticChildModelCallCoordinator(repository)
    invocation = _invocation("generation:batch:1")

    with pytest.raises(SyntheticChildModelCallPending) as pending:
        coordinator.execute(invocation)

    task = repository.states[pending.value.child_job_id].task
    expected = _result()
    repository.states[task.child_job_id] = SyntheticChildCallState(
        task=task,
        status=SyntheticChildCallStatus.SUCCEEDED,
        result=expected,
    )

    assert coordinator.execute(invocation) == expected
    assert len(repository.states) == 1


def test_parent_replay_rejects_same_child_identity_with_changed_input() -> None:
    repository = MemoryChildren()
    coordinator = SyntheticChildModelCallCoordinator(repository)
    first = _invocation("generation:batch:1")
    with pytest.raises(SyntheticChildModelCallPending):
        coordinator.execute(first)

    changed_prompt = replace(
        first.prompt,
        structured_input_hash=_hash("different-input"),
    )
    changed = replace(first, prompt=changed_prompt)

    with pytest.raises(SyntheticExecutionStale, match="immutable input"):
        coordinator.execute(changed)


def test_parent_retry_uses_the_childs_frozen_dify_release_after_binding_changes() -> None:
    repository = MemoryChildren()
    invocation = _invocation("generation:batch:1")
    first_release = _workflow_release(invocation)

    class Releases:
        current = first_release
        calls = 0

        def resolve_active(self, *, project_id, purpose):
            assert project_id == invocation.lease.project_id
            assert purpose == invocation.prompt.frozen.purpose
            self.calls += 1
            return self.current

    releases = Releases()
    coordinator = SyntheticChildModelCallCoordinator(
        repository,
        workflow_releases=releases,
    )
    with pytest.raises(SyntheticChildModelCallPending) as pending:
        coordinator.execute(invocation)
    frozen_task = repository.states[pending.value.child_job_id].task
    assert frozen_task.execution_backend is SyntheticExecutionBackend.DIFY
    assert frozen_task.workflow_release_id == first_release.id
    assert frozen_task.workflow_release_hash == first_release.release_hash

    releases.current = SimpleNamespace(
        **{
            **vars(first_release),
            "id": uuid4(),
            "release_hash": _hash("new-release"),
        }
    )
    expected = _workflow_result(
        release_id=first_release.id,
        release_hash=first_release.release_hash,
    )
    repository.states[frozen_task.child_job_id] = SyntheticChildCallState(
        task=frozen_task,
        status=SyntheticChildCallStatus.SUCCEEDED,
        result=expected,
    )

    assert coordinator.execute(invocation) is expected
    assert releases.calls == 1


def test_new_migrated_child_fails_closed_without_an_active_dify_release() -> None:
    class Releases:
        def resolve_active(self, *, project_id, purpose):
            del project_id, purpose
            return None

    repository = MemoryChildren()
    coordinator = SyntheticChildModelCallCoordinator(
        repository,
        workflow_releases=Releases(),
    )

    with pytest.raises(SyntheticExecutionError, match="no active release"):
        coordinator.execute(_invocation("generation:batch:1"))
    assert repository.states == {}


def test_new_dify_child_rejects_a_release_for_another_frozen_prompt() -> None:
    invocation = _invocation("generation:batch:1")
    selected = _workflow_release(invocation)
    release = SimpleNamespace(
        **{**vars(selected), "prompt_release_id": uuid4()}
    )

    class Releases:
        def resolve_active(self, *, project_id, purpose):
            del project_id, purpose
            return release

    with pytest.raises(SyntheticExecutionStale, match="frozen Synthetic Prompt"):
        SyntheticChildModelCallCoordinator(
            MemoryChildren(),
            workflow_releases=Releases(),
        ).execute(invocation)


def test_parent_treats_unknown_child_outcome_as_manual_terminal_work() -> None:
    repository = MemoryChildren()
    coordinator = SyntheticChildModelCallCoordinator(repository)
    invocation = _invocation("generation:batch:1")
    with pytest.raises(SyntheticChildModelCallPending) as pending:
        coordinator.execute(invocation)
    task = repository.states[pending.value.child_job_id].task
    repository.states[task.child_job_id] = SyntheticChildCallState(
        task=task,
        status=SyntheticChildCallStatus.UNKNOWN_OUTCOME,
        failure_code="dify_unknown_outcome",
    )

    with pytest.raises(
        SyntheticManualReconciliationRequired,
        match="manual reconciliation",
    ) as caught:
        coordinator.execute(invocation)

    assert caught.value.child_job_id == task.child_job_id
    assert caught.value.failure_code == "dify_unknown_outcome"


def test_frozen_prompt_rejects_bare_or_legacy_purpose_alias() -> None:
    frozen = _invocation("generation:batch:1").prompt.frozen

    with pytest.raises(ValueError, match="exact governed Program kind"):
        replace(frozen, purpose="generation")


def test_child_task_artifact_is_deterministic_encrypted_and_round_trips() -> None:
    objects = MemoryObjects()
    artifacts = EncryptedSyntheticChildTaskArtifactStore(
        object_store=objects,
        keyring=SyntheticArtifactKeyring(active_version="1", keys={"1": b"k" * 32}),
    )
    task = child_task_from_invocation(_invocation("generation:batch:1"))

    first = artifacts.put(task)
    second = artifacts.put(task)
    loaded = artifacts.load(
        first,
        project_id=task.project_id,
        child_job_id=task.child_job_id,
        expected_input_hash=task.input_hash,
    )

    assert first == second
    assert loaded == task
    encrypted = next(iter(objects.objects.values()))
    assert b"Generate candidate batch" not in encrypted
    assert b"synthetic_lab.generation" not in encrypted


def test_legacy_native_child_payload_keeps_its_v1_identity_and_defaults() -> None:
    task = child_task_from_invocation(_invocation("generation:batch:legacy"))
    type_name, payload, _content_hash = encode_object(task)
    raw_fields = payload.get("fields")
    assert isinstance(raw_fields, dict)
    for name in ("execution_backend", "workflow_release_id", "workflow_release_hash"):
        raw_fields.pop(name)

    decoded = decode_object(type_name, payload)

    assert isinstance(decoded, SyntheticChildModelCallTask)
    assert decoded == task
    assert decoded.input_hash == task.input_hash


def test_dify_child_artifact_round_trip_preserves_the_frozen_release() -> None:
    release_id = uuid4()
    release_hash = _hash("artifact-workflow-release")
    task = child_task_from_invocation(
        _invocation("generation:batch:dify"),
        execution_backend=SyntheticExecutionBackend.DIFY,
        workflow_release_id=release_id,
        workflow_release_hash=release_hash,
    )
    objects = MemoryObjects()
    artifacts = EncryptedSyntheticChildTaskArtifactStore(
        object_store=objects,
        keyring=SyntheticArtifactKeyring(active_version="1", keys={"1": b"k" * 32}),
    )

    loaded = artifacts.load(
        artifacts.put(task),
        project_id=task.project_id,
        child_job_id=task.child_job_id,
        expected_input_hash=task.input_hash,
    )

    assert loaded == task
    assert loaded.execution_backend is SyntheticExecutionBackend.DIFY
    assert loaded.workflow_release_id == release_id
    assert loaded.workflow_release_hash == release_hash


def test_child_task_artifact_rejects_wrong_project_key_or_input_hash() -> None:
    objects = MemoryObjects()
    artifacts = EncryptedSyntheticChildTaskArtifactStore(
        object_store=objects,
        keyring=SyntheticArtifactKeyring(active_version="1", keys={"1": b"k" * 32}),
    )
    task = child_task_from_invocation(_invocation("generation:batch:1"))
    reference = artifacts.put(task)

    with pytest.raises(ValueError, match="authentication failed"):
        artifacts.load(
            reference,
            project_id=uuid4(),
            child_job_id=task.child_job_id,
            expected_input_hash=task.input_hash,
        )
    with pytest.raises(ValueError, match="authentication failed"):
        artifacts.load(
            reference,
            project_id=task.project_id,
            child_job_id=task.child_job_id,
            expected_input_hash=_hash("changed"),
        )


def test_child_worker_completes_with_governed_attempt_reference() -> None:
    task = child_task_from_invocation(_invocation("generation:batch:1"))
    lease = _child_lease(task.child_job_id)
    store = ChildStore()
    expected = _result()
    handler = SyntheticChildModelCallHandler(
        store=store,  # type: ignore[arg-type]
        repository=ClaimedChildRepository(task),
        runtime_inputs=ChildRuntime(task.runtime_inputs),
        prompts=ChildPrompts(),
        model_gateway=ChildModel(expected),
        lease_for=timedelta(minutes=2),
    )

    result = handler.handle(lease)

    assert result["status"] == "succeeded"
    assert store.completions == [
        (
            f"model-gateway://attempt/{expected.model_attempt_id}",
            {
                "model_attempt_id": str(expected.model_attempt_id),
                "response_hash": expected.response_hash,
                "task_input_hash": task.input_hash,
            },
        )
    ]


def test_child_worker_records_dify_attempt_reference() -> None:
    release_id = uuid4()
    release_hash = _hash("workflow-release")
    task = child_task_from_invocation(
        _invocation("generation:batch:1"),
        execution_backend=SyntheticExecutionBackend.DIFY,
        workflow_release_id=release_id,
        workflow_release_hash=release_hash,
    )
    lease = _child_lease(task.child_job_id)
    store = ChildStore()
    expected = _workflow_result(release_id=release_id, release_hash=release_hash)
    handler = SyntheticChildModelCallHandler(
        store=store,  # type: ignore[arg-type]
        repository=ClaimedChildRepository(task),
        runtime_inputs=ChildRuntime(task.runtime_inputs),
        prompts=ChildPrompts(),
        model_gateway=ChildModel(expected),
        lease_for=timedelta(minutes=2),
    )

    assert handler.handle(lease)["status"] == "succeeded"
    assert store.completions[0] == (
        f"dify-workflow://attempt/{expected.workflow_attempt_id}",
        {
            "workflow_attempt_id": str(expected.workflow_attempt_id),
            "workflow_release_id": str(expected.workflow_release_id),
            "response_hash": expected.response_hash,
            "task_input_hash": task.input_hash,
        },
    )


def test_child_worker_does_not_retry_unknown_dify_outcome() -> None:
    task = child_task_from_invocation(_invocation("generation:batch:1"))
    lease = _child_lease(task.child_job_id)
    store = ChildStore()
    handler = SyntheticChildModelCallHandler(
        store=store,  # type: ignore[arg-type]
        repository=ClaimedChildRepository(task),
        runtime_inputs=ChildRuntime(task.runtime_inputs),
        prompts=ChildPrompts(),
        model_gateway=FailingChildModel(
            UnknownWorkflowOutcomeError(
                "Dify may have accepted this request; reconcile before retrying",
                code="dify_unknown_outcome",
            )
        ),
        lease_for=timedelta(minutes=2),
    )

    assert handler.handle(lease)["status"] == "failed"
    assert store.failures == [("dify_unknown_outcome", None)]


def test_child_worker_stops_when_parent_is_cancelled_before_model_call() -> None:
    task = child_task_from_invocation(_invocation("generation:batch:1"))
    repository = ClaimedChildRepository(task)
    repository.parent_error = JobCancellationRequested("parent cancelled")
    store = ChildStore()
    handler = SyntheticChildModelCallHandler(
        store=store,  # type: ignore[arg-type]
        repository=repository,
        runtime_inputs=ChildRuntime(task.runtime_inputs),
        prompts=ChildPrompts(),
        model_gateway=ChildModel(_result()),
        lease_for=timedelta(minutes=2),
    )

    with pytest.raises(JobCancellationRequested):
        handler.handle(_child_lease(task.child_job_id))

    assert store.completions == []
    assert store.failures == []


def _invocation(step_key: str) -> SyntheticModelInvocation:
    runtime = RuntimeInputSnapshot(
        project_id=PROJECT_ID,
        fact_snapshot_id=uuid4(),
        fact_snapshot_hash=_hash("facts"),
        profile_version_id=uuid4(),
        profile_hash=_hash("profile"),
        prompt_release_id=uuid4(),
        prompt_release_hash=_hash("prompt"),
        facts_current_approved=True,
        profile_frozen=True,
        prompt_frozen=True,
    )
    frozen = FrozenPromptRef(
        project_id=PROJECT_ID,
        binding_id=uuid4(),
        binding_version=1,
        frozen_state_id=uuid4(),
        frozen_state_version=1,
        release_id=runtime.prompt_release_id,
        release_version=1,
        release_hash=runtime.prompt_release_hash,
        program_kind=ProgramKind.GENERATION,
        purpose="synthetic_lab.generation",
        route=ModelRoute(
            provider="openai",
            adapter_release_id="openai-v1",
            adapter_release_hash=_hash("adapter"),
            model_release_id="model-v1",
            model_release_hash=_hash("model"),
        ),
        configured_model="model-v1",
        runtime_manifest_id=UUID("32000000-0000-0000-0000-000000000010"),
        runtime_manifest_hash=_hash("manifest"),
        runtime_option_id=UUID("32000000-0000-0000-0000-000000000011"),
        runtime_option_hash=_hash("option"),
        model_policy=ModelPolicy(),
        model_policy_hash=_hash("policy"),
    )
    prompt = ResolvedSyntheticPrompt(
        frozen=frozen,
        messages=(
            {"role": "system", "content": "Return structured test data."},
            {"role": "user", "content": "Generate candidate batch."},
        ),
        output_schema={"type": "object"},
        application_output_schema={"type": "object"},
        prompt_bundle_hash=_hash("bundle"),
        structured_input_hash=_hash("input"),
    )
    return SyntheticModelInvocation(
        lease=WorkerLease(
            job_id=PARENT_JOB_ID,
            project_id=PROJECT_ID,
            kind="review.case.run",
            worker_id="parent-worker",
            lease_token=uuid4(),
            fencing_generation=1,
            attempt_count=1,
            max_attempts=3,
        ),
        expected_job_version=1,
        parent_task_input_hash=_hash("parent-task"),
        runtime_inputs=runtime,
        prompt=prompt,
        admitted_by=uuid4(),
        step_key=step_key,
        structured_input={"case": "fixed"},
    )


def _result() -> SyntheticModelResult:
    return SyntheticModelResult(
        model_attempt_id=uuid4(),
        model_call_id=uuid4(),
        output={"candidates": []},
        provider="openai",
        configured_model="model-v1",
        reported_model="model-v1",
        model_identity_hash=_hash("identity"),
        request_hash=_hash("request"),
        response_hash=_hash("response"),
    )


def _workflow_result(*, release_id: UUID, release_hash: str) -> SyntheticWorkflowResult:
    return SyntheticWorkflowResult(
        workflow_attempt_id=uuid4(),
        workflow_release_id=release_id,
        workflow_release_hash=release_hash,
        output={"candidates": []},
        configured_model="model-v1",
        reported_model="model-v1",
        model_identity_hash=_hash("dify-identity"),
        request_hash=_hash("dify-request"),
        response_hash=_hash("dify-response"),
    )


def _workflow_release(invocation: SyntheticModelInvocation):
    frozen = invocation.prompt.frozen
    return SimpleNamespace(
        id=uuid4(),
        project_id=frozen.project_id,
        purpose=frozen.purpose,
        prompt_release_id=frozen.release_id,
        prompt_release_hash=frozen.release_hash,
        configured_model=frozen.configured_model,
        release_hash=_hash("workflow-release"),
    )


def _child_lease(child_job_id: UUID) -> WorkerLease:
    return WorkerLease(
        job_id=child_job_id,
        project_id=PROJECT_ID,
        kind="synthetic.model.call",
        worker_id="child-worker",
        lease_token=uuid4(),
        fencing_generation=1,
        attempt_count=1,
        max_attempts=3,
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
