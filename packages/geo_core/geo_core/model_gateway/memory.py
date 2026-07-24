"""Transactional in-memory model-call store with commit-time CAS checks."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from threading import RLock
from types import TracebackType
from typing import TypeVar
from uuid import UUID

from geo_core.jobs.lifecycle import JobStatus
from geo_core.model_gateway.contracts import (
    ModelCallBudgetExceeded,
    ModelCallConcurrencyExceeded,
)
from geo_core.model_gateway.ports import (
    ModelCallAttempt,
    ModelCallAttemptDraft,
    ModelCallIdempotencyConflict,
    ModelCallJobAdmission,
    ModelCallOutcome,
    ModelCallPersistenceError,
    ModelCallReconciliationRecord,
    ModelCallRepository,
    ModelCallTerminalEvent,
    ModelCallUnitOfWork,
    ModelCallUnitOfWorkFactory,
    ModelCallVersionConflict,
    PromptReleaseAdmission,
    StoredModelCallAttempt,
)
from geo_core.model_gateway.prompt_admission import ModelCallAdmissionMode


_KeyT = TypeVar("_KeyT")
_ValueT = TypeVar("_ValueT")


class InMemoryModelCallStore:
    """Shared committed state; every UoW mutates an isolated snapshot."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._jobs: dict[tuple[UUID, UUID], ModelCallJobAdmission] = {}
        self._prompts: dict[
            tuple[UUID, ModelCallAdmissionMode, UUID, UUID], PromptReleaseAdmission
        ] = {}
        self._attempts: dict[tuple[UUID, UUID], ModelCallAttempt] = {}
        self._idempotency: dict[tuple[UUID, UUID, str], UUID] = {}
        self._events: dict[tuple[UUID, UUID], ModelCallTerminalEvent] = {}
        self._reconciliations: dict[tuple[UUID, str], ModelCallReconciliationRecord] = {}
        self._fail_next_commit = False

    def unit_of_work_factory(self) -> ModelCallUnitOfWorkFactory:
        return InMemoryModelCallUnitOfWorkFactory(self)

    def seed_job(self, job: ModelCallJobAdmission) -> None:
        key = (job.project_id, job.job_id)
        with self._lock:
            if key in self._jobs:
                raise ModelCallPersistenceError("model-call Job admission already exists")
            self._jobs[key] = job

    def seed_prompt_release(self, prompt: PromptReleaseAdmission) -> None:
        key = _prompt_key(prompt)
        with self._lock:
            if key in self._prompts:
                raise ModelCallPersistenceError("Prompt Release admission already exists")
            self._prompts[key] = prompt

    def job(self, *, project_id: UUID, job_id: UUID) -> ModelCallJobAdmission | None:
        with self._lock:
            return self._jobs.get((project_id, job_id))

    def attempt(self, *, project_id: UUID, attempt_id: UUID) -> ModelCallAttempt | None:
        with self._lock:
            return self._attempts.get((project_id, attempt_id))

    def attempts(self, *, project_id: UUID, job_id: UUID) -> tuple[ModelCallAttempt, ...]:
        with self._lock:
            values = (
                attempt
                for (attempt_project_id, _), attempt in self._attempts.items()
                if attempt_project_id == project_id and attempt.spec.job_id == job_id
            )
            return tuple(sorted(values, key=lambda item: item.attempt_number))

    def terminal_event(
        self, *, project_id: UUID, attempt_id: UUID
    ) -> ModelCallTerminalEvent | None:
        with self._lock:
            return self._events.get((project_id, attempt_id))

    def fail_next_commit(self) -> None:
        with self._lock:
            self._fail_next_commit = True


class InMemoryModelCallUnitOfWorkFactory:
    def __init__(self, store: InMemoryModelCallStore) -> None:
        self.store = store

    def __call__(self, *, project_id: UUID) -> ModelCallUnitOfWork:
        return InMemoryModelCallUnitOfWork(self.store, project_id=project_id)


class InMemoryModelCallUnitOfWork:
    def __init__(self, store: InMemoryModelCallStore, *, project_id: UUID) -> None:
        self._store = store
        self.project_id = project_id
        self._active = False
        self._touched_jobs: set[tuple[UUID, UUID]] = set()
        self._touched_attempts: set[tuple[UUID, UUID]] = set()
        self._touched_idempotency: set[tuple[UUID, UUID, str]] = set()
        self._touched_events: set[tuple[UUID, UUID]] = set()
        self._touched_reconciliations: set[tuple[UUID, str]] = set()
        self.calls: ModelCallRepository = _MemoryModelCallRepository(self)

    def __enter__(self) -> InMemoryModelCallUnitOfWork:
        if self._active:
            raise ModelCallPersistenceError("model-call UoW is already active")
        with self._store._lock:
            self._base_jobs = dict(self._store._jobs)
            self._base_prompts = dict(self._store._prompts)
            self._base_attempts = dict(self._store._attempts)
            self._base_idempotency = dict(self._store._idempotency)
            self._base_events = dict(self._store._events)
            self._base_reconciliations = dict(self._store._reconciliations)
        self._jobs = dict(self._base_jobs)
        self._prompts = dict(self._base_prompts)
        self._attempts = dict(self._base_attempts)
        self._idempotency = dict(self._base_idempotency)
        self._events = dict(self._base_events)
        self._reconciliations = dict(self._base_reconciliations)
        self._active = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self._active = False
        return None

    def commit(self) -> None:
        self._ensure_active()
        with self._store._lock:
            if self._store._fail_next_commit:
                self._store._fail_next_commit = False
                raise ModelCallPersistenceError("simulated model-call commit failure")
            self._verify_unchanged(
                self._touched_jobs,
                self._base_jobs,
                self._store._jobs,
                "model-call Job budget changed concurrently",
            )
            self._verify_unchanged(
                self._touched_attempts,
                self._base_attempts,
                self._store._attempts,
                "model-call attempt changed concurrently",
            )
            self._verify_unchanged(
                self._touched_idempotency,
                self._base_idempotency,
                self._store._idempotency,
                "model-call idempotency key changed concurrently",
            )
            self._verify_unchanged(
                self._touched_events,
                self._base_events,
                self._store._events,
                "model-call terminal log changed concurrently",
            )
            self._verify_unchanged(
                self._touched_reconciliations,
                self._base_reconciliations,
                self._store._reconciliations,
                "model-call reconciliation command changed concurrently",
            )
            _apply(self._store._jobs, self._jobs, self._touched_jobs)
            _apply(self._store._attempts, self._attempts, self._touched_attempts)
            _apply(self._store._idempotency, self._idempotency, self._touched_idempotency)
            _apply(self._store._events, self._events, self._touched_events)
            _apply(
                self._store._reconciliations,
                self._reconciliations,
                self._touched_reconciliations,
            )

    def _verify_unchanged(
        self,
        keys: set[_KeyT],
        base: dict[_KeyT, _ValueT],
        current: dict[_KeyT, _ValueT],
        message: str,
    ) -> None:
        if any(current.get(key) != base.get(key) for key in keys):
            raise ModelCallVersionConflict(message)

    def _require_scope(self, project_id: UUID) -> None:
        self._ensure_active()
        if project_id != self.project_id:
            raise ModelCallPersistenceError("model-call UoW project scope mismatch")

    def _ensure_active(self) -> None:
        if not self._active:
            raise ModelCallPersistenceError("model-call UoW is not active")


class _MemoryModelCallRepository:
    def __init__(self, uow: InMemoryModelCallUnitOfWork) -> None:
        self._uow = uow

    def get_job(self, *, project_id: UUID, job_id: UUID) -> ModelCallJobAdmission | None:
        self._uow._require_scope(project_id)
        return self._uow._jobs.get((project_id, job_id))

    def get_prompt_release(
        self, *, project_id: UUID, binding_id: UUID, release_id: UUID
    ) -> PromptReleaseAdmission | None:
        self._uow._require_scope(project_id)
        return self._uow._prompts.get(
            (project_id, ModelCallAdmissionMode.RUNTIME_FROZEN, binding_id, release_id)
        )

    def get_prompt_test_release(
        self,
        *,
        project_id: UUID,
        release_id: UUID,
        state_id: UUID,
        state_version: int,
        test_set_hash: str,
    ) -> PromptReleaseAdmission | None:
        self._uow._require_scope(project_id)
        prompt = self._uow._prompts.get(
            (project_id, ModelCallAdmissionMode.PROMPT_RELEASE_TEST, state_id, release_id)
        )
        if (
            prompt is None
            or prompt.state_version != state_version
            or prompt.test_set_hash != test_set_hash
        ):
            return None
        return prompt

    def get_attempt(self, *, project_id: UUID, attempt_id: UUID) -> ModelCallAttempt | None:
        self._uow._require_scope(project_id)
        return self._uow._attempts.get((project_id, attempt_id))

    def get_attempt_by_idempotency(
        self, *, project_id: UUID, job_id: UUID, idempotency_key_hash: str
    ) -> ModelCallOutcome | None:
        self._uow._require_scope(project_id)
        attempt_id = self._uow._idempotency.get((project_id, job_id, idempotency_key_hash))
        if attempt_id is None:
            return None
        attempt = self._uow._attempts[(project_id, attempt_id)]
        return ModelCallOutcome(attempt, self._uow._events.get((project_id, attempt_id)))

    def get_terminal_event(
        self, *, project_id: UUID, attempt_id: UUID
    ) -> ModelCallTerminalEvent | None:
        self._uow._require_scope(project_id)
        return self._uow._events.get((project_id, attempt_id))

    def get_reconciliation_command(
        self, *, project_id: UUID, idempotency_key_hash: str
    ) -> ModelCallReconciliationRecord | None:
        self._uow._require_scope(project_id)
        return self._uow._reconciliations.get((project_id, idempotency_key_hash))

    def reserve_attempt(
        self,
        *,
        draft: ModelCallAttemptDraft,
        expected_job_version: int,
        expected_budget_version: int,
        reserved_at: datetime,
    ) -> StoredModelCallAttempt:
        self._uow._require_scope(draft.project_id)
        identity_key = (draft.project_id, draft.job_id, draft.idempotency_key_hash)
        existing_id = self._uow._idempotency.get(identity_key)
        if existing_id is not None:
            existing = self._uow._attempts[(draft.project_id, existing_id)]
            if existing.spec.request_hash != draft.request_hash:
                raise ModelCallIdempotencyConflict(
                    "model-call attempt idempotency key was reused for another request"
                )
            return StoredModelCallAttempt(existing, replayed=True)

        job_key = (draft.project_id, draft.job_id)
        job = self._uow._jobs.get(job_key)
        if job is None:
            raise ModelCallPersistenceError("model-call Job admission does not exist")
        if job.job_version != expected_job_version or draft.job_version != job.job_version:
            raise ModelCallVersionConflict("model-call Job version CAS failed")
        if job.budget_version != expected_budget_version:
            raise ModelCallVersionConflict("model-call paid budget CAS failed")
        if job.status is not JobStatus.RUNNING:
            raise ModelCallVersionConflict("model-call Job is no longer running")
        if (
            draft.lease_token != job.lease_token
            or draft.fencing_generation != job.fencing_generation
        ):
            raise ModelCallVersionConflict("model-call Job lease or fencing token is stale")
        if (
            draft.policy_version_id != job.policy_version_id
            or draft.policy_version_hash != job.policy_version_hash
            or draft.runtime_manifest_id != job.runtime_manifest_id
            or draft.runtime_manifest_hash != job.runtime_manifest_hash
            or draft.runtime_option_id != job.runtime_option_id
            or draft.runtime_option_hash != job.runtime_option_hash
            or draft.raw_artifact_policy_hash != job.raw_artifact_policy_hash
            or draft.raw_artifact_storage_decision != job.raw_artifact_storage_decision
            or draft.raw_artifact_retention_days != job.raw_artifact_retention_days
        ):
            raise ModelCallVersionConflict("model-call policy lineage changed before reservation")
        if job.reserved_calls >= job.maximum_concurrent_calls:
            raise ModelCallConcurrencyExceeded("job-wide concurrent model-call budget exhausted")
        if job.paid_calls + job.reserved_calls >= job.maximum_paid_calls:
            raise ModelCallBudgetExceeded("job-wide paid model-call budget exhausted")
        attempt_key = (draft.project_id, draft.id)
        if attempt_key in self._uow._attempts:
            raise ModelCallVersionConflict("model-call attempt identity already exists")

        attempt = ModelCallAttempt(
            spec=draft,
            attempt_number=job.next_attempt_number,
            reserved_at=reserved_at,
        )
        self._uow._attempts[attempt_key] = attempt
        self._uow._idempotency[identity_key] = draft.id
        self._uow._jobs[job_key] = replace(
            job,
            reserved_calls=job.reserved_calls + 1,
            budget_version=job.budget_version + 1,
            next_attempt_number=job.next_attempt_number + 1,
        )
        self._uow._touched_attempts.add(attempt_key)
        self._uow._touched_idempotency.add(identity_key)
        self._uow._touched_jobs.add(job_key)
        return StoredModelCallAttempt(attempt, replayed=False)

    def append_terminal_event(
        self,
        *,
        event: ModelCallTerminalEvent,
        expected_budget_version: int,
    ) -> None:
        self._uow._require_scope(event.project_id)
        attempt_key = (event.project_id, event.attempt_id)
        attempt = self._uow._attempts.get(attempt_key)
        if attempt is None or attempt.spec.job_id != event.job_id:
            raise ModelCallPersistenceError("model-call terminal event has no reservation")
        if attempt.spec.input_hash != event.input_hash:
            raise ModelCallPersistenceError("model-call terminal input hash changed")
        if attempt.spec.configured_model != event.configured_model:
            raise ModelCallPersistenceError("model-call configured model changed")
        if (
            attempt.spec.search_mode != event.lineage.search_mode
            or attempt.spec.capture_method != event.lineage.capture_method
            or attempt.spec.raw_artifact_policy_hash != event.lineage.raw_artifact_policy_hash
            or attempt.spec.raw_artifact_storage_decision
            != event.lineage.raw_artifact_storage_decision
            or attempt.spec.raw_artifact_retention_days != event.lineage.raw_artifact_retention_days
        ):
            raise ModelCallPersistenceError("model-call capture or policy lineage changed")
        if (
            event.status.value == "succeeded"
            and (attempt.spec.requested_location is None)
            != (event.lineage.effective_location is None)
        ):
            raise ModelCallPersistenceError(
                "model-call effective location differs from its reserved request"
            )
        if event.status.value == "failed" and event.lineage.effective_location is not None:
            raise ModelCallPersistenceError(
                "failed model-call cannot claim an effective location"
            )
        if event.occurred_at < attempt.reserved_at:
            raise ModelCallPersistenceError("model-call terminal event predates reservation")
        if attempt_key in self._uow._events:
            raise ModelCallVersionConflict("model-call attempt already has a terminal event")
        job_key = (event.project_id, event.job_id)
        job = self._uow._jobs[job_key]
        if job.budget_version != expected_budget_version:
            raise ModelCallVersionConflict("model-call terminal budget CAS failed")
        if job.reserved_calls < 1:
            raise ModelCallVersionConflict("model-call reservation is no longer held")
        paid_calls = job.paid_calls + event.paid_call_count
        if paid_calls > job.maximum_paid_calls:
            raise ModelCallBudgetExceeded("job-wide paid model-call budget exhausted")
        self._uow._events[attempt_key] = event
        self._uow._jobs[job_key] = replace(
            job,
            paid_calls=paid_calls,
            reserved_calls=job.reserved_calls - 1,
            budget_version=job.budget_version + 1,
        )
        self._uow._touched_events.add(attempt_key)
        self._uow._touched_jobs.add(job_key)

    def add_reconciliation_command(self, command: ModelCallReconciliationRecord) -> None:
        self._uow._require_scope(command.project_id)
        key = (command.project_id, command.idempotency_key_hash)
        if key in self._uow._reconciliations:
            raise ModelCallIdempotencyConflict(
                "manual reconciliation idempotency key already exists"
            )
        if any(
            item.attempt_id == command.attempt_id
            for (project_id, _), item in self._uow._reconciliations.items()
            if project_id == command.project_id
        ):
            raise ModelCallVersionConflict(
                "model-call attempt already has a reconciliation command"
            )
        self._uow._reconciliations[key] = command
        self._uow._touched_reconciliations.add(key)


def _prompt_key(
    prompt: PromptReleaseAdmission,
) -> tuple[UUID, ModelCallAdmissionMode, UUID, UUID]:
    identity = prompt.binding_id or prompt.state_id
    return (prompt.project_id, prompt.admission_mode, identity, prompt.release_id)


def _apply(target: dict[_KeyT, _ValueT], source: dict[_KeyT, _ValueT], keys: set[_KeyT]) -> None:
    for key in keys:
        target[key] = source[key]
