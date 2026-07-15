"""Cross-project dispatch port backed by narrowly scoped security-definer functions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class OutboxMessage:
    id: UUID
    project_id: UUID
    job_id: UUID
    topic: str
    payload: Mapping[str, object]


@dataclass(frozen=True)
class RecoverableJob:
    job_id: UUID
    project_id: UUID
    kind: str


class PostgresOutboxStore:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def claim(
        self, *, worker_id: str, batch_size: int, lease_seconds: int
    ) -> tuple[OutboxMessage, ...]:
        with self._connection_factory() as connection:
            rows = connection.execute(
                "SELECT * FROM geo_worker_claim_broker_outbox(%s, %s, %s)",
                (worker_id, batch_size, lease_seconds),
            ).fetchall()
            return tuple(
                OutboxMessage(
                    id=row[0], project_id=row[1], job_id=row[2], topic=row[3], payload=row[4]
                )
                for row in rows
            )

    def acknowledge(self, message: OutboxMessage, *, worker_id: str) -> bool:
        with self._connection_factory() as connection:
            return bool(
                connection.execute(
                    "SELECT geo_worker_ack_broker_outbox(%s, %s, %s)",
                    (message.id, message.project_id, worker_id),
                ).fetchone()[0]
            )

    def fail(self, message: OutboxMessage, *, worker_id: str, error: str) -> bool:
        with self._connection_factory() as connection:
            return bool(
                connection.execute(
                    "SELECT geo_worker_fail_broker_outbox(%s, %s, %s, %s)",
                    (message.id, message.project_id, worker_id, error),
                ).fetchone()[0]
            )

    def recoverable(self, *, batch_size: int) -> tuple[RecoverableJob, ...]:
        with self._connection_factory() as connection:
            rows = connection.execute(
                "SELECT * FROM geo_worker_recoverable_jobs(%s)", (batch_size,)
            ).fetchall()
            return tuple(RecoverableJob(row[0], row[1], row[2]) for row in rows)
