"""Transactional persistence boundaries owned by the alerts application slice."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from geo_core.alerts.domain import Alert
from geo_core.alerts.notifications import NotificationOutboxCommand


class AlertRepository(Protocol):
    def get(self, *, project_id: UUID, alert_id: UUID) -> Alert | None: ...

    def get_active_by_dedupe_key(
        self, *, project_id: UUID, dedupe_key: str
    ) -> Alert | None: ...

    def add(self, alert: Alert) -> None: ...

    def save(self, alert: Alert, *, expected_version: int) -> None: ...


class AlertOutboxRepository(Protocol):
    def enqueue(self, command: NotificationOutboxCommand) -> None: ...


class AlertUnitOfWork(Protocol):
    alerts: AlertRepository
    outbox: AlertOutboxRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...


class AlertUnitOfWorkFactory(Protocol):
    def __call__(self) -> AlertUnitOfWork: ...
