"""Transactional in-memory Sampling adapters with commit-time CAS checks."""

from __future__ import annotations

from dataclasses import replace
from threading import RLock
from types import TracebackType
from typing import TypeVar
from uuid import UUID

from geo_core.sampling.contracts import (
    SamplingConflict,
    SamplingNotFound,
    SamplingRun,
    SamplingSuite,
    SamplingTask,
    SamplingTaskStatus,
)
from geo_core.sampling.execution import (
    AttemptTerminalStatus,
    SamplingAttempt,
    SamplingObservation,
    SamplingOutboxMessage,
)
from geo_core.sampling.ports import (
    SamplingOutboxRepository,
    SamplingRepository,
    SamplingUnitOfWork,
    SamplingUnitOfWorkFactory,
)


_Key = TypeVar("_Key")
_Value = TypeVar("_Value")
_SuiteKey = tuple[UUID, UUID]
_RunKey = tuple[UUID, UUID]
_TaskKey = tuple[UUID, UUID, UUID]
_AttemptKey = tuple[UUID, UUID]
_ObservationKey = tuple[UUID, UUID, UUID]
_OutboxKey = tuple[UUID, UUID]


class InMemorySamplingStore:
    """Shared committed state. Every UoW receives an isolated snapshot."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._suites: dict[_SuiteKey, SamplingSuite] = {}
        self._runs: dict[_RunKey, SamplingRun] = {}
        self._tasks: dict[_TaskKey, SamplingTask] = {}
        self._attempts: dict[_AttemptKey, SamplingAttempt] = {}
        self._observations: dict[_ObservationKey, SamplingObservation] = {}
        self._outbox: dict[_OutboxKey, SamplingOutboxMessage] = {}

    def unit_of_work_factory(self) -> SamplingUnitOfWorkFactory:
        return InMemorySamplingUnitOfWorkFactory(self)

    def suite(self, *, project_id: UUID, suite_id: UUID) -> SamplingSuite | None:
        with self._lock:
            return self._suites.get((project_id, suite_id))

    def suites(self, *, project_id: UUID) -> tuple[SamplingSuite, ...]:
        with self._lock:
            values = tuple(
                suite
                for (suite_project_id, _), suite in self._suites.items()
                if suite_project_id == project_id
            )
        return tuple(sorted(values, key=lambda item: (item.frozen_at, str(item.id)), reverse=True))

    def run(self, *, project_id: UUID, run_id: UUID) -> SamplingRun | None:
        with self._lock:
            return self._runs.get((project_id, run_id))

    def runs(self, *, project_id: UUID) -> tuple[SamplingRun, ...]:
        with self._lock:
            values = tuple(
                run
                for (run_project_id, _), run in self._runs.items()
                if run_project_id == project_id
            )
        return tuple(sorted(values, key=lambda item: (item.created_at, str(item.id)), reverse=True))

    def task(self, *, project_id: UUID, run_id: UUID, task_id: UUID) -> SamplingTask | None:
        with self._lock:
            return self._tasks.get((project_id, run_id, task_id))

    def attempt(self, *, project_id: UUID, attempt_id: UUID) -> SamplingAttempt | None:
        with self._lock:
            return self._attempts.get((project_id, attempt_id))

    def observation(
        self, *, project_id: UUID, run_id: UUID, task_id: UUID
    ) -> SamplingObservation | None:
        with self._lock:
            return self._observations.get((project_id, run_id, task_id))

    def outbox_messages(self, *, project_id: UUID) -> tuple[SamplingOutboxMessage, ...]:
        with self._lock:
            return tuple(
                message
                for (message_project_id, _), message in self._outbox.items()
                if message_project_id == project_id
            )


class InMemorySamplingUnitOfWorkFactory:
    def __init__(self, store: InMemorySamplingStore) -> None:
        self.store = store

    def __call__(self, *, project_id: UUID) -> SamplingUnitOfWork:
        return InMemorySamplingUnitOfWork(self.store, project_id=project_id)


class InMemorySamplingUnitOfWork:
    def __init__(self, store: InMemorySamplingStore, *, project_id: UUID) -> None:
        self._store = store
        self.project_id = project_id
        self._active = False
        self._touched_suites: set[_SuiteKey] = set()
        self._touched_runs: set[_RunKey] = set()
        self._touched_tasks: set[_TaskKey] = set()
        self._touched_attempts: set[_AttemptKey] = set()
        self._touched_observations: set[_ObservationKey] = set()
        self._touched_outbox: set[_OutboxKey] = set()
        self.sampling: SamplingRepository = _MemorySamplingRepository(self)
        self.outbox: SamplingOutboxRepository = _MemorySamplingOutbox(self)

    def __enter__(self) -> "InMemorySamplingUnitOfWork":
        if self._active:
            raise SamplingConflict("Sampling UoW is already active")
        with self._store._lock:
            self._base_suites = dict(self._store._suites)
            self._base_runs = dict(self._store._runs)
            self._base_tasks = dict(self._store._tasks)
            self._base_attempts = dict(self._store._attempts)
            self._base_observations = dict(self._store._observations)
            self._base_outbox = dict(self._store._outbox)
        self._suites = dict(self._base_suites)
        self._runs = dict(self._base_runs)
        self._tasks = dict(self._base_tasks)
        self._attempts = dict(self._base_attempts)
        self._observations = dict(self._base_observations)
        self._outbox_records = dict(self._base_outbox)
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
            _assert_unchanged(
                self._touched_suites,
                self._base_suites,
                self._store._suites,
                self._suites,
            )
            _assert_unchanged(self._touched_runs, self._base_runs, self._store._runs, self._runs)
            _assert_unchanged(
                self._touched_tasks, self._base_tasks, self._store._tasks, self._tasks
            )
            _assert_unchanged(
                self._touched_attempts,
                self._base_attempts,
                self._store._attempts,
                self._attempts,
            )
            _assert_unchanged(
                self._touched_observations,
                self._base_observations,
                self._store._observations,
                self._observations,
            )
            _assert_unchanged(
                self._touched_outbox,
                self._base_outbox,
                self._store._outbox,
                self._outbox_records,
            )
            _apply(self._store._suites, self._suites, self._touched_suites)
            _apply(self._store._runs, self._runs, self._touched_runs)
            _apply(self._store._tasks, self._tasks, self._touched_tasks)
            _apply(self._store._attempts, self._attempts, self._touched_attempts)
            _apply(
                self._store._observations,
                self._observations,
                self._touched_observations,
            )
            _apply(self._store._outbox, self._outbox_records, self._touched_outbox)

    def _require_scope(self, project_id: UUID) -> None:
        self._ensure_active()
        if project_id != self.project_id:
            raise SamplingConflict("Sampling UoW project scope mismatch")

    def _ensure_active(self) -> None:
        if not self._active:
            raise SamplingConflict("Sampling UoW is not active")


class _MemorySamplingRepository:
    def __init__(self, uow: InMemorySamplingUnitOfWork) -> None:
        self._uow = uow

    def get_suite(self, *, project_id: UUID, suite_id: UUID) -> SamplingSuite | None:
        self._uow._require_scope(project_id)
        return self._uow._suites.get((project_id, suite_id))

    def add_suite(self, suite: SamplingSuite) -> None:
        self._uow._require_scope(suite.project_id)
        key = (suite.project_id, suite.id)
        _add_idempotent(self._uow._suites, key, suite, "Sampling Suite")
        self._uow._touched_suites.add(key)

    def get_run(self, *, project_id: UUID, run_id: UUID) -> SamplingRun | None:
        self._uow._require_scope(project_id)
        return self._uow._runs.get((project_id, run_id))

    def add_run(self, run: SamplingRun) -> None:
        self._uow._require_scope(run.project_id)
        suite = self._uow._suites.get((run.project_id, run.suite_id))
        if suite is None:
            raise SamplingNotFound("Sampling Suite does not exist")
        if run.suite_hash != suite.suite_hash:
            raise SamplingConflict("Sampling Run uses a different Suite revision")
        key = (run.project_id, run.id)
        _add_idempotent(self._uow._runs, key, run, "Sampling Run")
        self._uow._touched_runs.add(key)

    def save_run(self, run: SamplingRun, *, expected_version: int) -> None:
        self._uow._require_scope(run.project_id)
        key = (run.project_id, run.id)
        current = self._uow._runs.get(key)
        _require_cas(current, expected_version, run.version, "Sampling Run")
        if current is not None and replace(current, status=run.status, version=run.version) != run:
            raise SamplingConflict("Sampling Run immutable denominator cannot be changed")
        self._uow._runs[key] = run
        self._uow._touched_runs.add(key)

    def get_task(self, *, project_id: UUID, run_id: UUID, task_id: UUID) -> SamplingTask | None:
        self._uow._require_scope(project_id)
        return self._uow._tasks.get((project_id, run_id, task_id))

    def list_tasks(self, *, project_id: UUID, run_id: UUID) -> tuple[SamplingTask, ...]:
        self._uow._require_scope(project_id)
        return tuple(
            task
            for (task_project, task_run, _), task in self._uow._tasks.items()
            if task_project == project_id and task_run == run_id
        )

    def add_tasks(self, tasks: tuple[SamplingTask, ...]) -> None:
        if not tasks:
            raise SamplingConflict("Sampling Task batch cannot be empty")
        seen: set[_TaskKey] = set()
        for task in tasks:
            self._uow._require_scope(task.project_id)
            run = self._uow._runs.get((task.project_id, task.run_id))
            if run is None:
                raise SamplingNotFound("Sampling Run does not exist")
            if (
                task.identity.task_key not in run.planned_task_keys
                or task.identity.suite_id != run.suite_id
                or task.identity.suite_hash != run.suite_hash
            ):
                raise SamplingConflict("Sampling Task is outside the Run denominator")
            key = (task.project_id, task.run_id, task.id)
            if key in seen:
                raise SamplingConflict("Sampling Task batch contains a duplicate")
            seen.add(key)
            _add_idempotent(self._uow._tasks, key, task, "Sampling Task")
            self._uow._touched_tasks.add(key)

    def save_task(self, task: SamplingTask, *, expected_version: int) -> None:
        self._uow._require_scope(task.project_id)
        key = (task.project_id, task.run_id, task.id)
        current = self._uow._tasks.get(key)
        _require_cas(current, expected_version, task.version, "Sampling Task")
        if current is not None:
            if (
                task.id != current.id
                or task.project_id != current.project_id
                or task.run_id != current.run_id
                or task.identity != current.identity
                or task.max_attempts != current.max_attempts
                or not _valid_attempt_inventory_change(current.attempt_ids, task.attempt_ids)
            ):
                raise SamplingConflict("Sampling Task immutable identity was changed")
        self._uow._tasks[key] = task
        self._uow._touched_tasks.add(key)

    def get_attempt(self, *, project_id: UUID, attempt_id: UUID) -> SamplingAttempt | None:
        self._uow._require_scope(project_id)
        return self._uow._attempts.get((project_id, attempt_id))

    def add_attempt(self, attempt: SamplingAttempt) -> None:
        self._uow._require_scope(attempt.project_id)
        task_key = (attempt.project_id, attempt.run_id, attempt.task_id)
        task = self._uow._tasks.get(task_key)
        if task is None or attempt.id not in task.attempt_ids:
            raise SamplingConflict("Attempt is not attached to its Sampling Task")
        key = (attempt.project_id, attempt.id)
        _add_idempotent(self._uow._attempts, key, attempt, "Sampling Attempt")
        self._uow._touched_attempts.add(key)

    def save_attempt(self, attempt: SamplingAttempt, *, expected_version: int) -> None:
        self._uow._require_scope(attempt.project_id)
        key = (attempt.project_id, attempt.id)
        current = self._uow._attempts.get(key)
        _require_cas(current, expected_version, attempt.record_version, "Sampling Attempt")
        if current is not None and (
            attempt.id != current.id
            or attempt.project_id != current.project_id
            or attempt.run_id != current.run_id
            or attempt.task_id != current.task_id
            or attempt.task_key != current.task_key
            or attempt.ordinal != current.ordinal
            or attempt.job.spec != current.job.spec
            or attempt.job.input_hash != current.job.input_hash
            or attempt.job.idempotency_key != current.job.idempotency_key
        ):
            raise SamplingConflict("Sampling Attempt immutable command was changed")
        self._uow._attempts[key] = attempt
        self._uow._touched_attempts.add(key)

    def get_observation(
        self, *, project_id: UUID, run_id: UUID, task_id: UUID
    ) -> SamplingObservation | None:
        self._uow._require_scope(project_id)
        return self._uow._observations.get((project_id, run_id, task_id))

    def list_observations(
        self, *, project_id: UUID, run_id: UUID
    ) -> tuple[SamplingObservation, ...]:
        self._uow._require_scope(project_id)
        return tuple(
            observation
            for (observation_project, observation_run, _), observation in (
                self._uow._observations.items()
            )
            if observation_project == project_id and observation_run == run_id
        )

    def add_observation(self, observation: SamplingObservation) -> None:
        self._uow._require_scope(observation.project_id)
        task_key = (observation.project_id, observation.run_id, observation.task_id)
        task = self._uow._tasks.get(task_key)
        attempt = self._uow._attempts.get((observation.project_id, observation.winning_attempt_id))
        if task is None or attempt is None or attempt.task_id != task.id:
            raise SamplingConflict("Observation lineage does not resolve to Task/Attempt")
        if (
            task.status is not SamplingTaskStatus.SUCCEEDED
            or attempt.terminal_status is not AttemptTerminalStatus.SUCCEEDED
            or observation.task_key != task.identity.task_key
            or observation.winning_attempt_id != attempt.id
            or attempt.job.result_ref != f"sampling-observation:{observation.id}"
        ):
            raise SamplingConflict("Observation requires a successfully fenced Attempt")
        key = task_key
        _add_idempotent(self._uow._observations, key, observation, "Sampling Observation")
        self._uow._touched_observations.add(key)


class _MemorySamplingOutbox:
    def __init__(self, uow: InMemorySamplingUnitOfWork) -> None:
        self._uow = uow

    def enqueue(self, message: SamplingOutboxMessage) -> None:
        self._uow._require_scope(message.project_id)
        if (message.project_id, message.job_id) not in self._uow._attempts:
            raise SamplingConflict("Sampling Outbox message has no persisted Attempt")
        attempt = self._uow._attempts[(message.project_id, message.job_id)]
        if message.topic != attempt.job.spec.kind or dict(message.payload) != dict(
            attempt.job.spec.payload
        ):
            raise SamplingConflict("Sampling Outbox differs from its immutable Job command")
        key = (message.project_id, message.id)
        _add_idempotent(self._uow._outbox_records, key, message, "Sampling Outbox message")
        self._uow._touched_outbox.add(key)


def _add_idempotent(values: dict[_Key, _Value], key: _Key, value: _Value, label: str) -> None:
    existing = values.get(key)
    if existing is not None and existing != value:
        raise SamplingConflict(f"{label} identity was reused with different content")
    values[key] = value


def _require_cas(
    current: object | None,
    expected_version: int,
    replacement_version: int,
    label: str,
) -> None:
    if current is None:
        raise SamplingNotFound(f"{label} does not exist")
    current_version = getattr(current, "version", None)
    if current_version is None:
        current_version = getattr(current, "record_version", None)
    if current_version != expected_version or replacement_version != expected_version + 1:
        raise SamplingConflict(f"{label} optimistic version check failed")


def _valid_attempt_inventory_change(
    current: tuple[UUID, ...], replacement: tuple[UUID, ...]
) -> bool:
    return replacement == current or (
        len(replacement) == len(current) + 1 and replacement[:-1] == current
    )


def _assert_unchanged(
    keys: set[_Key],
    base: dict[_Key, _Value],
    current: dict[_Key, _Value],
    staged: dict[_Key, _Value],
) -> None:
    for key in keys:
        if current.get(key) == base.get(key):
            continue
        if base.get(key) is None and current.get(key) == staged.get(key):
            continue
        raise SamplingConflict("concurrent Sampling transaction changed committed state")


def _apply(target: dict[_Key, _Value], staged: dict[_Key, _Value], keys: set[_Key]) -> None:
    for key in keys:
        target[key] = staged[key]
