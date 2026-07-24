"""Project-scoped persistence ports for Sampling Core."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from geo_core.sampling.contracts import SamplingRun, SamplingSuite, SamplingTask
from geo_core.sampling.execution import (
    SamplingAttempt,
    SamplingObservation,
    SamplingOutboxMessage,
)


class SamplingRepository(Protocol):
    def get_suite(self, *, project_id: UUID, suite_id: UUID) -> SamplingSuite | None: ...

    def add_suite(self, suite: SamplingSuite) -> None: ...

    def get_run(self, *, project_id: UUID, run_id: UUID) -> SamplingRun | None: ...

    def add_run(self, run: SamplingRun) -> None: ...

    def save_run(self, run: SamplingRun, *, expected_version: int) -> None: ...

    def get_task(self, *, project_id: UUID, run_id: UUID, task_id: UUID) -> SamplingTask | None: ...

    def list_tasks(self, *, project_id: UUID, run_id: UUID) -> tuple[SamplingTask, ...]: ...

    def add_tasks(self, tasks: tuple[SamplingTask, ...]) -> None: ...

    def save_task(self, task: SamplingTask, *, expected_version: int) -> None: ...

    def get_attempt(self, *, project_id: UUID, attempt_id: UUID) -> SamplingAttempt | None: ...

    def add_attempt(self, attempt: SamplingAttempt) -> None: ...

    def save_attempt(self, attempt: SamplingAttempt, *, expected_version: int) -> None: ...

    def get_observation(
        self, *, project_id: UUID, run_id: UUID, task_id: UUID
    ) -> SamplingObservation | None: ...

    def list_observations(
        self, *, project_id: UUID, run_id: UUID
    ) -> tuple[SamplingObservation, ...]: ...

    def add_observation(self, observation: SamplingObservation) -> None: ...


class SamplingOutboxRepository(Protocol):
    def enqueue(self, message: SamplingOutboxMessage) -> None: ...


class SamplingUnitOfWork(Protocol):
    sampling: SamplingRepository
    outbox: SamplingOutboxRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...


class SamplingUnitOfWorkFactory(Protocol):
    def __call__(self, *, project_id: UUID) -> SamplingUnitOfWork: ...
