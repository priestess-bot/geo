from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.jobs.postgres import JobCancellationRequested, WorkerLease
from geo_core.model_gateway.contracts import ModelCaptureMethod, ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.object_store import RetrievedObject, StoredObject
from geo_core.prompts.application import PromptProgramApplication
from geo_core.prompts.application_models import PromptProgramRuntimeBlocked
from geo_core.prompts.bootstrap_catalog import (
    default_prompt_bootstrap_spec,
    prompt_bootstrap_catalog_hash,
)
from geo_core.prompts.bootstrap_contracts import EvalScenario, thaw_mapping
from geo_core.prompts.memory import InMemoryPromptProgramRepository
from geo_core.prompts.ports import PromptProgramIdempotencyConflict
from geo_core.prompts.program import ProgramKind, create_initial_release_state
from geo_core.prompts.test_artifacts import (
    S3PromptTestArtifactStore,
    S3PromptTestEvidenceVerifier,
    canonical_artifact_bytes,
)
from geo_core.prompts.test_execution_application import PromptTestApplication
from geo_core.prompts.test_execution_contracts import (
    PROMPT_TEST_JOB_KIND,
    PromptTestArtifactReceipt,
    PromptTestCaseModelResult,
    PromptTestExecutionError,
    PromptTestJob,
    PromptTestModelSelection,
    PromptTestRouteRequest,
    PromptTestRunClaim,
    PromptTestRunResult,
    PromptTestRunTask,
    PromptTestStale,
    StoredPromptTestJob,
)
from geo_core.prompts.test_worker import PromptTestExecutionHandler
from geo_core.secrets.models import SecretVersionHandle


NOW = datetime(2026, 7, 23, 11, 0, tzinfo=UTC)


def test_admission_freezes_server_selected_route_and_replays_exact_request() -> None:
    project_id, owner_id = uuid4(), uuid4()
    principal = _principal(project_id, owner_id)
    prompts = InMemoryPromptProgramRepository()
    spec = default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION)
    created = PromptProgramApplication(prompts, clock=lambda: NOW).create_program(
        principal,
        project_id=project_id,
        program_kind=spec.program_kind,
        purpose=spec.purpose,
        system_template=spec.system_template,
        user_template=spec.user_template,
        schemas=spec.schemas,
        model_policy=spec.model_policy,
        test_set_id=spec.test_set_id,
        test_set_version=1,
        test_set_hash=spec.test_set_hash,
        compiler_version="geo-prompt-bootstrap-compiler-v1",
        expected_version=0,
        idempotency_key="create-recommendation",
    ).value
    runs = _MemoryTestRuns()
    selector = _Selector(_selection(project_id))
    application = PromptTestApplication(
        uow_factory=_TestUowFactory(prompts, runs),
        runtime_selector=selector,
        clock=lambda: NOW,
    )
    request = PromptTestRouteRequest(
        runtime_selection_id=selector.selection.runtime_selection_id,
    )

    first = application.enqueue(
        principal,
        project_id=project_id,
        program_id=created.program.id,
        release_id=created.release.id,
        test_set_id=spec.test_set_id,
        test_set_version=1,
        test_set_hash=spec.test_set_hash,
        route=request,
        expected_version=1,
        idempotency_key="run-recommendation-v1",
    )
    replay = application.enqueue(
        principal,
        project_id=project_id,
        program_id=created.program.id,
        release_id=created.release.id,
        test_set_id=spec.test_set_id,
        test_set_version=1,
        test_set_hash=spec.test_set_hash,
        route=request,
        expected_version=1,
        idempotency_key="run-recommendation-v1",
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.value == first.value
    task = runs.tasks[first.value.id]
    assert task.release_hash == created.release.release_hash
    assert task.expected_state_id == created.state.id
    assert task.test_spec == spec
    assert task.model == selector.selection
    assert "plaintext" not in str(task.canonical_value()).casefold()


def test_admission_rejects_client_selected_test_set_or_reused_key() -> None:
    project_id, owner_id = uuid4(), uuid4()
    principal = _principal(project_id, owner_id)
    prompts, release, state = _stored_draft(project_id, owner_id)
    runs = _MemoryTestRuns()
    selection = _selection(project_id)
    application = PromptTestApplication(
        uow_factory=_TestUowFactory(prompts, runs),
        runtime_selector=_Selector(selection),
        clock=lambda: NOW,
    )
    route = PromptTestRouteRequest(
        selection.runtime_selection_id,
    )

    with pytest.raises(PromptTestExecutionError, match="immutable TestSet"):
        application.enqueue(
            principal,
            project_id=project_id,
            program_id=release.program_id,
            release_id=release.id,
            test_set_id=release.test_set_id,
            test_set_version=release.test_set_version,
            test_set_hash="ff" * 32,
            route=route,
            expected_version=state.version,
            idempotency_key="wrong-set",
        )
    accepted = application.enqueue(
        principal,
        project_id=project_id,
        program_id=release.program_id,
        release_id=release.id,
        test_set_id=release.test_set_id,
        test_set_version=release.test_set_version,
        test_set_hash=release.test_set_hash,
        route=route,
        expected_version=state.version,
        idempotency_key="same-key",
    )
    runs.forced_hash = "00" * 32
    with pytest.raises(PromptProgramIdempotencyConflict):
        application.enqueue(
            principal,
            project_id=project_id,
            program_id=release.program_id,
            release_id=release.id,
            test_set_id=release.test_set_id,
            test_set_version=release.test_set_version,
            test_set_hash=release.test_set_hash,
            route=route,
            expected_version=state.version,
            idempotency_key="same-key",
        )
    assert accepted.value.id in runs.tasks


def test_worker_evaluates_all_cases_and_only_passed_run_creates_evidence() -> None:
    claim, lease = _claim_and_lease()
    store = _JobStore()
    repository = _ExecutionRepository(claim)
    executor = _CaseExecutor(claim)
    artifacts = _ArtifactStore()
    handler = PromptTestExecutionHandler(
        store=store,  # type: ignore[arg-type]
        repository=repository,
        executor=executor,
        artifacts=artifacts,
        lease_for=timedelta(seconds=30),
        clock=lambda: NOW,
    )

    response = handler.handle(lease)

    assert response["status"] == "succeeded"
    assert response["passed"] is True
    assert executor.fixture_ids == [item.fixture_id for item in claim.task.test_spec.fixtures]
    assert repository.finalized is not None
    assert repository.finalized["evidence"].tested_by == claim.task.requested_by
    assert store.completed["passed"] is True
    assert store.failed is None


def test_worker_keeps_failed_evaluation_as_non_admitted_terminal_result() -> None:
    claim, lease = _claim_and_lease()
    store = _JobStore()
    repository = _ExecutionRepository(claim)
    executor = _CaseExecutor(claim, fail_first=True)
    handler = PromptTestExecutionHandler(
        store=store,  # type: ignore[arg-type]
        repository=repository,
        executor=executor,
        artifacts=_ArtifactStore(),
        lease_for=timedelta(seconds=30),
        clock=lambda: NOW,
    )

    response = handler.handle(lease)

    assert response["status"] == "succeeded"
    assert response["passed"] is False
    assert repository.finalized is None
    assert store.completed["passed"] is False


def test_worker_propagates_cancellation_and_fences_stale_release() -> None:
    claim, lease = _claim_and_lease()
    cancelled = _JobStore(cancel=True)
    handler = PromptTestExecutionHandler(
        store=cancelled,  # type: ignore[arg-type]
        repository=_ExecutionRepository(claim),
        executor=_CaseExecutor(claim),
        artifacts=_ArtifactStore(),
        lease_for=timedelta(seconds=30),
    )
    with pytest.raises(JobCancellationRequested):
        handler.handle(lease)

    stale_store = _JobStore()
    stale_repository = _ExecutionRepository(claim, stale=True)
    stale_handler = PromptTestExecutionHandler(
        store=stale_store,  # type: ignore[arg-type]
        repository=stale_repository,
        executor=_CaseExecutor(claim),
        artifacts=_ArtifactStore(),
        lease_for=timedelta(seconds=30),
    )
    response = stale_handler.handle(lease)
    assert response["status"] == "failed"
    assert stale_store.failed == "prompt_test_stale"
    assert stale_repository.finalized is None


def test_artifact_verifier_recomputes_pass_and_rejects_tampering() -> None:
    claim, _lease = _claim_and_lease()
    cases = tuple(_CaseExecutor(claim).case(fixture) for fixture in claim.task.test_spec.fixtures)
    outputs = {item.fixture_id: item.output for item in cases}
    from geo_core.prompts.bootstrap_evaluation import evaluate_prompt_test_set

    result = PromptTestRunResult(
        task=claim.task,
        cases=cases,
        evaluation=evaluate_prompt_test_set(claim.task.test_spec, outputs),
    )
    objects = _Objects()
    receipt = S3PromptTestArtifactStore(objects).persist(result)
    evidence, _state = _evidence_for(claim, receipt)
    verifier = S3PromptTestEvidenceVerifier(objects)

    verifier.verify(release=claim.release, evidence=evidence)
    document = dict(result.artifact_value())
    evaluation = dict(document["evaluation"])  # type: ignore[arg-type]
    evaluation["passed"] = False
    document["evaluation"] = evaluation
    objects.values[receipt.uri] = canonical_artifact_bytes(document)
    with pytest.raises(PromptTestExecutionError):
        verifier.verify(release=claim.release, evidence=evidence)


def test_approval_requires_latest_exact_evidence_and_server_verification() -> None:
    project_id, owner_id = uuid4(), uuid4()
    repository, release, draft_state = _stored_draft(project_id, owner_id)
    task = PromptTestRunTask(
        project_id=project_id,
        job_id=uuid4(),
        program_id=release.program_id,
        release_id=release.id,
        release_version=release.version,
        release_hash=release.release_hash,
        expected_state_id=draft_state.id,
        expected_state_version=draft_state.version,
        requested_by=owner_id,
        requested_at=NOW,
        test_spec=default_prompt_bootstrap_spec(release.program_kind),
        catalog_hash=prompt_bootstrap_catalog_hash(),
        model=_selection(project_id),
    )
    claim = PromptTestRunClaim(task, release, draft_state)
    cases = tuple(_CaseExecutor(claim).case(item) for item in task.test_spec.fixtures)
    from geo_core.prompts.bootstrap_evaluation import evaluate_prompt_test_set

    result = PromptTestRunResult(
        task=task,
        cases=cases,
        evaluation=evaluate_prompt_test_set(
            task.test_spec, {item.fixture_id: item.output for item in cases}
        ),
    )
    artifact = PromptTestArtifactReceipt("s3://prompt-tests/exact.json", result.result_hash)
    evidence, tested_state = _evidence_for(claim, artifact)
    repository.store_worker_test_transition(
        project_id=project_id,
        release=release,
        state=tested_state,
        expected_version=draft_state.version,
        test_evidence=evidence,
    )
    approver = _principal(project_id, uuid4())

    with pytest.raises(PromptProgramRuntimeBlocked, match="durable test evidence verifier"):
        PromptProgramApplication(repository, clock=lambda: NOW).approve_release(
            approver,
            project_id=project_id,
            release_id=release.id,
            expected_version=tested_state.version,
            idempotency_key="approve-without-verifier",
        )
    verifier = _RecordingVerifier()
    approved = PromptProgramApplication(
        repository,
        test_evidence_verifier=verifier,
        clock=lambda: NOW,
    ).approve_release(
        approver,
        project_id=project_id,
        release_id=release.id,
        expected_version=tested_state.version,
        idempotency_key="approve-exact-evidence",
    )
    assert verifier.values == (release, evidence)
    assert approved.value.admitted_test_evidence == evidence


class _MemoryTestRuns:
    def __init__(self) -> None:
        self.by_key: dict[str, StoredPromptTestJob] = {}
        self.tasks: dict[UUID, PromptTestRunTask] = {}
        self.forced_hash: str | None = None

    def enqueue(
        self, *, task: PromptTestRunTask, idempotency_key_hash: str, outbox_id: UUID
    ) -> StoredPromptTestJob:
        del outbox_id
        existing = self.by_key.get(idempotency_key_hash)
        if existing is not None:
            stored_hash = self.forced_hash or existing.job.input_hash
            if stored_hash != task.input_hash:
                raise PromptProgramIdempotencyConflict("different input")
            return StoredPromptTestJob(existing.job, replayed=True)
        job = PromptTestJob(
            id=task.job_id,
            project_id=task.project_id,
            release_id=task.release_id,
            release_hash=task.release_hash,
            test_set_id=task.test_set_id,
            test_set_version=task.test_set_version,
            test_set_hash=task.test_set_hash,
            input_hash=task.input_hash,
        )
        stored = StoredPromptTestJob(job, replayed=False)
        self.by_key[idempotency_key_hash] = stored
        self.tasks[job.id] = task
        return stored


class _TestUow:
    def __init__(self, prompts: InMemoryPromptProgramRepository, runs: _MemoryTestRuns) -> None:
        self.prompts = prompts
        self.test_runs = runs
        self.committed = False

    def __enter__(self) -> _TestUow:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def commit(self) -> None:
        self.committed = True


class _TestUowFactory:
    def __init__(self, prompts: InMemoryPromptProgramRepository, runs: _MemoryTestRuns) -> None:
        self.prompts, self.runs = prompts, runs

    def __call__(self, *, project_id: UUID) -> _TestUow:
        del project_id
        return _TestUow(self.prompts, self.runs)


class _Selector:
    def __init__(self, selection: PromptTestModelSelection) -> None:
        self.selection = selection

    def select(self, *, project_id: UUID, request: PromptTestRouteRequest):
        assert project_id == self.selection.provider_secret_handle.project_id
        assert request.runtime_selection_id == self.selection.runtime_selection_id
        return self.selection

    def list_approved(self, *, project_id: UUID):
        assert project_id == self.selection.provider_secret_handle.project_id
        return ()


class _ExecutionRepository:
    def __init__(self, claim: PromptTestRunClaim, *, stale: bool = False) -> None:
        self.claim, self.stale = claim, stale
        self.finalized: dict[str, Any] | None = None

    def load(self, lease: WorkerLease) -> PromptTestRunClaim:
        del lease
        return self.claim

    def assert_current(self, task: PromptTestRunTask) -> None:
        del task
        if self.stale:
            raise PromptTestStale("changed")

    def finalize_passed(self, **values: Any) -> None:
        self.finalized = values


class _CaseExecutor:
    def __init__(self, claim: PromptTestRunClaim, *, fail_first: bool = False) -> None:
        self.claim, self.fail_first = claim, fail_first
        self.fixture_ids: list[str] = []

    def execute(self, **values: Any) -> PromptTestCaseModelResult:
        fixture_id = values["fixture_id"]
        fixture = next(
            item for item in self.claim.task.test_spec.fixtures if item.fixture_id == fixture_id
        )
        self.fixture_ids.append(fixture_id)
        return self.case(fixture, fail=self.fail_first and len(self.fixture_ids) == 1)

    def case(self, fixture: Any, *, fail: bool = False) -> PromptTestCaseModelResult:
        output = _passing_output(self.claim, fixture)
        if fail:
            output = thaw_mapping(fixture.expected_output)
            output["subject_id"] = "different-subject"
        return PromptTestCaseModelResult(
            fixture_id=fixture.fixture_id,
            fixture_hash=fixture.fixture_hash,
            model_call_id=uuid5(self.claim.task.job_id, fixture.fixture_id),
            response_hash=fixture.fixture_hash,
            output=output,
        )


class _ArtifactStore:
    def persist(self, result: PromptTestRunResult) -> PromptTestArtifactReceipt:
        return PromptTestArtifactReceipt(
            uri=f"s3://prompt-tests/{result.task.job_id}.json",
            content_hash=result.result_hash,
        )


class _JobStore:
    def __init__(self, *, cancel: bool = False) -> None:
        self.cancel = cancel
        self.completed: dict[str, object] = {}
        self.failed: str | None = None

    def heartbeat(self, lease: WorkerLease, *, lease_for: timedelta) -> None:
        del lease, lease_for
        if self.cancel:
            raise JobCancellationRequested("cancelled")

    @contextmanager
    def fenced_transaction(self, lease: WorkerLease):
        del lease
        yield object()

    def complete_in_transaction(
        self,
        connection: object,
        lease: WorkerLease,
        *,
        result_ref: str,
        details: Mapping[str, object],
    ) -> None:
        del connection, lease, result_ref
        self.completed = dict(details)

    def fail(
        self,
        lease: WorkerLease,
        *,
        error_code: str,
        details: Mapping[str, object],
        retry_delay: timedelta | None,
    ) -> str:
        del lease, details, retry_delay
        self.failed = error_code
        return "failed"


class _Objects:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def put_object(self, *, key: str, content: bytes, content_type: str, expected_hash: str):
        uri = f"s3://prompt-tests/{key}"
        self.values[uri] = content
        return StoredObject(uri, "prompt-tests", key, content_type, expected_hash, None)

    def get_s3_uri(self, *, uri: str, expected_hash: str | None = None):
        content = self.values[uri]
        import hashlib

        digest = hashlib.sha256(content).hexdigest()
        if expected_hash is not None and digest != expected_hash:
            raise ValueError("hash mismatch")
        return RetrievedObject(content, "prompt-tests", uri, "application/json", digest, None)


class _RecordingVerifier:
    def __init__(self) -> None:
        self.values: tuple[object, object] | None = None

    def verify(self, *, release: object, evidence: object) -> None:
        self.values = (release, evidence)


def _stored_draft(project_id: UUID, owner_id: UUID):
    spec = default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION)
    draft = spec.compile_draft(project_id=project_id, owner_id=owner_id)
    state = create_initial_release_state(
        id=uuid4(), release=draft.release, actor_id=owner_id, acted_at=NOW
    )
    repository = InMemoryPromptProgramRepository()
    from geo_core.prompts.application_models import CreatedPromptProgram
    from geo_core.prompts.application_support import command_record, request_hash
    from geo_core.prompts.ports import PromptCommandOperation

    result = CreatedPromptProgram(draft.program, draft.release, state)
    repository.store_created_program(
        project_id=project_id,
        program=draft.program,
        release=draft.release,
        state=state,
        expected_version=0,
        command=command_record(
            project_id=project_id,
            key_hash="ab" * 32,
            operation=PromptCommandOperation.CREATE,
            request_hash=request_hash(
                operation=PromptCommandOperation.CREATE,
                actor_id=owner_id,
                project_id=project_id,
                expected_version=0,
                values={"fixture": True},
            ),
            result=result,
        ),
    )
    return repository, draft.release, state


def _claim_and_lease() -> tuple[PromptTestRunClaim, WorkerLease]:
    project_id, owner_id, job_id = uuid4(), uuid4(), uuid4()
    _repository, release, state = _stored_draft(project_id, owner_id)
    task = PromptTestRunTask(
        project_id=project_id,
        job_id=job_id,
        program_id=release.program_id,
        release_id=release.id,
        release_version=release.version,
        release_hash=release.release_hash,
        expected_state_id=state.id,
        expected_state_version=state.version,
        requested_by=owner_id,
        requested_at=NOW,
        test_spec=default_prompt_bootstrap_spec(release.program_kind),
        catalog_hash=prompt_bootstrap_catalog_hash(),
        model=_selection(project_id),
    )
    claim = PromptTestRunClaim(task, release, state)
    lease = WorkerLease(job_id, project_id, PROMPT_TEST_JOB_KIND, "worker", uuid4(), 1, 1, 3)
    return claim, lease


def _selection(project_id: UUID) -> PromptTestModelSelection:
    policy_version_id = uuid4()
    policy = ModelPolicy(
        allowed_providers=frozenset({"openai"}),
        allowed_adapter_release_ids=frozenset({"openai-adapter-v1"}),
        policy_version_id=policy_version_id,
        maximum_paid_calls=5,
        maximum_concurrent_calls=1,
    )
    assert policy.policy_version_hash is not None
    return PromptTestModelSelection(
        runtime_selection_id=uuid4(),
        runtime_selection_hash="55" * 32,
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash="11" * 32,
        route=ModelRoute(
            "openai",
            "openai-adapter-v1",
            "22" * 32,
            "openai-model-v1",
            "33" * 32,
        ),
        configured_model="openai-test-model",
        capture_method=ModelCaptureMethod.PROVIDER_API,
        policy_version_id=policy_version_id,
        policy_version_hash=policy.policy_version_hash,
        policy=policy,
        provider_secret_handle=SecretVersionHandle(
            reference_id=uuid4(),
            project_id=project_id,
            purpose="model_provider.openai",
            version=1,
        ),
    )


def _principal(project_id: UUID, identity_id: UUID) -> AccessPrincipal:
    tenant_id = uuid4()
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=tenant_id,
        memberships=(MembershipRecord(project_id, tenant_id, "admin"),),
        auth_method="test",
    )


def _passing_output(claim: PromptTestRunClaim, fixture: Any) -> dict[str, object]:
    spec = claim.task.test_spec
    positive = next(item for item in spec.fixtures if item.scenario is EvalScenario.POSITIVE)
    selected = fixture if fixture.scenario is EvalScenario.PROMPT_INJECTION else positive
    return thaw_mapping(selected.expected_output)


def _evidence_for(
    claim: PromptTestRunClaim, receipt: PromptTestArtifactReceipt
):
    from geo_core.prompts.test_worker import _passed_transition
    from geo_core.prompts.bootstrap_evaluation import evaluate_prompt_test_set

    cases = tuple(_CaseExecutor(claim).case(item) for item in claim.task.test_spec.fixtures)
    result = PromptTestRunResult(
        task=claim.task,
        cases=cases,
        evaluation=evaluate_prompt_test_set(
            claim.task.test_spec,
            {item.fixture_id: item.output for item in cases},
        ),
    )
    evidence, state = _passed_transition(claim, result, receipt, tested_at=NOW)
    assert evidence is not None and state is not None
    return evidence, state
