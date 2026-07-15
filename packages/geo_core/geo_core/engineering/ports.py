"""Persistence ports owned by the engineering governance application slice."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Self
from uuid import UUID

from geo_core.engineering.domain import WorkItemProjection


class DeliveryConflictError(RuntimeError):
    """A GitHub delivery id was reused with different immutable content."""


class UnknownRepositoryError(RuntimeError):
    """The GitHub repository has not been bound to a GEO project."""


@dataclass(frozen=True)
class DeliveryReceipt:
    delivery_id: str
    job_id: UUID
    duplicate: bool
    job_status: str = "queued"


@dataclass(frozen=True)
class EngineeringJobReceipt:
    job_id: UUID
    status: str


@dataclass(frozen=True)
class EngineeringEvent:
    sequence: int
    event_type: str
    data: Mapping[str, object]
    observed_at: datetime


class EngineeringRepository(Protocol):
    """One transaction's access to all engineering truth projections."""

    def record_github_delivery(
        self,
        *,
        delivery_id: str,
        event_name: str,
        external_repository_id: int,
        payload_hash: str,
        payload: Mapping[str, object],
        received_at: datetime,
    ) -> DeliveryReceipt: ...

    def register_repository(
        self,
        *,
        installation_id: int,
        external_repository_id: int,
        full_name: str,
        web_url: str,
        default_branch: str,
    ) -> UUID: ...

    def list_work_items(self, *, now: datetime) -> Sequence[WorkItemProjection]: ...

    def create_job(
        self,
        *,
        operation: str,
        repository_id: UUID | None,
        service_key: str | None,
        reason: str,
        idempotency_key: str,
        now: datetime,
    ) -> EngineeringJobReceipt: ...

    def list_events(self, *, after: int, limit: int) -> Sequence[EngineeringEvent]: ...

    def append_event(
        self, *, event_type: str, data: Mapping[str, object], observed_at: datetime
    ) -> int: ...

    def upsert_pull_request(self, projection: Mapping[str, object]) -> None: ...

    def upsert_ci_run(self, projection: Mapping[str, object]) -> None: ...

    def replace_ci_checks(
        self, *, run_id: UUID, checks: Sequence[Mapping[str, object]]
    ) -> None: ...

    def upsert_service_health(self, projection: Mapping[str, object]) -> None: ...

    def upsert_work_item(self, projection: Mapping[str, object]) -> None: ...


class EngineeringUnitOfWork(Protocol):
    @property
    def repository(self) -> EngineeringRepository: ...

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def commit(self) -> None: ...


class EngineeringUnitOfWorkFactory(Protocol):
    def __call__(self) -> EngineeringUnitOfWork: ...


EventIterator = Iterator[EngineeringEvent]
