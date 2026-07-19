"""Project-scoped PostgreSQL leases for the new durable worker composition."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import threading
from typing import Any, Literal
from uuid import UUID, uuid4

from geo_core.project_scope import set_project_scope


class LostJobLease(RuntimeError):
    """The current worker was fenced or its lease expired."""


class JobCancellationRequested(RuntimeError):
    """A running handler must stop before finalizing external work."""


@dataclass(frozen=True)
class WorkerLease:
    job_id: UUID
    project_id: UUID
    kind: str
    worker_id: str
    lease_token: UUID
    fencing_generation: int
    attempt_count: int
    max_attempts: int


@dataclass(frozen=True)
class ClaimResult:
    disposition: Literal["claimed", "busy", "terminal", "cancelled", "dead_lettered", "missing"]
    lease: WorkerLease | None = None
    kind: str | None = None


def _one(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    names = [column.name for column in cursor.description]
    return dict(zip(names, row, strict=True))


class PostgresDurableJobStore:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def open_project(self, project_id: UUID) -> Any:
        connection = self._connection_factory()
        set_project_scope(connection, project_id)
        return connection

    def claim(
        self,
        *,
        job_id: UUID,
        project_id: UUID,
        expected_kind: str,
        worker_id: str,
        lease_for: timedelta,
    ) -> ClaimResult:
        connection = self.open_project(project_id)
        try:
            row = _one(
                connection.execute(
                    """SELECT id, project_id, kind, status, attempt_count, max_attempts,
                              next_run_at, lease_expires_at, cancel_requested_at
                       FROM durable_jobs WHERE id = %s AND project_id = %s FOR UPDATE""",
                    (job_id, project_id),
                )
            )
            if row is None:
                connection.rollback()
                return ClaimResult("missing")
            if expected_kind and row["kind"] != expected_kind:
                raise ValueError("job kind does not match the selected handler")
            if row["status"] in {"succeeded", "failed", "dead_lettered", "cancelled"}:
                connection.rollback()
                return ClaimResult("terminal", kind=row["kind"])
            if row["cancel_requested_at"] is not None:
                self._set_terminal(connection, row, worker_id=worker_id, status="cancelled")
                connection.commit()
                return ClaimResult("cancelled", kind=row["kind"])
            now = datetime.now(UTC)
            due = row["status"] in {"queued", "retry_wait"} and row["next_run_at"] <= now
            expired = (
                row["status"] in {"running", "finalizing"}
                and row["lease_expires_at"] is not None
                and row["lease_expires_at"] <= now
            )
            if not (due or expired):
                connection.rollback()
                return ClaimResult("busy", kind=row["kind"])
            if row["attempt_count"] >= row["max_attempts"]:
                self._set_terminal(
                    connection,
                    row,
                    worker_id=worker_id,
                    status="dead_lettered",
                    error_code="attempt_budget_exhausted",
                )
                connection.commit()
                return ClaimResult("dead_lettered", kind=row["kind"])
            token = uuid4()
            claimed = _one(
                connection.execute(
                    """UPDATE durable_jobs SET status = 'running', lease_owner = %s,
                         lease_token = %s, lease_expires_at = %s, heartbeat_at = %s,
                         fencing_generation = fencing_generation + 1,
                         attempt_count = attempt_count + 1, error_code = NULL,
                         updated_at = clock_timestamp()
                       WHERE id = %s AND project_id = %s
                       RETURNING kind, attempt_count, max_attempts, fencing_generation""",
                    (worker_id, token, now + lease_for, now, job_id, project_id),
                )
            )
            if claimed is None:
                raise LostJobLease("job disappeared while claiming")
            lease = WorkerLease(
                job_id,
                project_id,
                claimed["kind"],
                worker_id,
                token,
                claimed["fencing_generation"],
                claimed["attempt_count"],
                claimed["max_attempts"],
            )
            self._event(
                connection,
                lease,
                "lease_reclaimed" if expired else "lease_claimed",
                {"attempt_count": lease.attempt_count},
            )
            connection.commit()
            return ClaimResult("claimed", lease, claimed["kind"])
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def heartbeat(self, lease: WorkerLease, *, lease_for: timedelta) -> None:
        connection = self.open_project(lease.project_id)
        try:
            row = _one(
                connection.execute(
                    """UPDATE durable_jobs SET heartbeat_at = clock_timestamp(),
                         lease_expires_at = clock_timestamp() + %s::interval,
                         updated_at = clock_timestamp()
                       WHERE id = %s AND project_id = %s AND lease_token = %s
                         AND fencing_generation = %s AND status IN ('running', 'finalizing')
                         AND lease_expires_at > clock_timestamp()
                       RETURNING cancel_requested_at""",
                    (
                        f"{lease_for.total_seconds()} seconds",
                        lease.job_id,
                        lease.project_id,
                        lease.lease_token,
                        lease.fencing_generation,
                    ),
                )
            )
            if row is None:
                raise LostJobLease("job lease was fenced before heartbeat")
            connection.commit()
            if row["cancel_requested_at"] is not None:
                raise JobCancellationRequested("job cancellation was requested")
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def fenced_transaction(self, lease: WorkerLease) -> Iterator[Any]:
        connection = self.open_project(lease.project_id)
        try:
            row = _one(
                connection.execute(
                    """SELECT cancel_requested_at FROM durable_jobs
                       WHERE id = %s AND project_id = %s AND lease_token = %s
                         AND fencing_generation = %s AND status IN ('running', 'finalizing')
                         AND lease_expires_at > clock_timestamp() FOR UPDATE""",
                    (
                        lease.job_id,
                        lease.project_id,
                        lease.lease_token,
                        lease.fencing_generation,
                    ),
                )
            )
            if row is None:
                raise LostJobLease("job lease was fenced before finalization")
            if row["cancel_requested_at"] is not None:
                raise JobCancellationRequested("job cancellation was requested")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete_in_transaction(
        self,
        connection: Any,
        lease: WorkerLease,
        *,
        result_ref: str,
        details: Mapping[str, object],
    ) -> None:
        changed = connection.execute(
            """UPDATE durable_jobs SET status = 'succeeded', result_ref = %s,
                 error_detail = %s::jsonb, lease_owner = NULL, lease_token = NULL,
                 lease_expires_at = NULL, heartbeat_at = NULL, completed_at = clock_timestamp(),
                 updated_at = clock_timestamp()
               WHERE id = %s AND project_id = %s AND lease_token = %s
                 AND fencing_generation = %s""",
            (
                result_ref,
                json.dumps(dict(details)),
                lease.job_id,
                lease.project_id,
                lease.lease_token,
                lease.fencing_generation,
            ),
        ).rowcount
        if changed != 1:
            raise LostJobLease("job lease was fenced during completion")
        self._event(connection, lease, "job_succeeded", details)

    def fail(
        self,
        lease: WorkerLease,
        *,
        error_code: str,
        details: Mapping[str, object],
        retry_delay: timedelta | None,
    ) -> str:
        connection = self.open_project(lease.project_id)
        try:
            retry = retry_delay is not None and lease.attempt_count < lease.max_attempts
            status = "retry_wait" if retry else "dead_lettered" if retry_delay else "failed"
            next_run_at = datetime.now(UTC) + retry_delay if retry_delay else datetime.now(UTC)
            changed = connection.execute(
                """UPDATE durable_jobs SET status = %s, error_code = %s,
                     error_detail = %s::jsonb, next_run_at = %s,
                     lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                     heartbeat_at = NULL, updated_at = clock_timestamp(),
                     completed_at = CASE WHEN %s IN ('failed', 'dead_lettered')
                                         THEN clock_timestamp() ELSE NULL END
                   WHERE id = %s AND project_id = %s AND lease_token = %s
                     AND fencing_generation = %s""",
                (
                    status,
                    error_code,
                    json.dumps(dict(details)),
                    next_run_at,
                    status,
                    lease.job_id,
                    lease.project_id,
                    lease.lease_token,
                    lease.fencing_generation,
                ),
            ).rowcount
            if changed != 1:
                raise LostJobLease("job lease was fenced during failure handling")
            self._event(connection, lease, f"job_{status}", details)
            connection.commit()
            return status
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def fail_in_transaction(
        self,
        connection: Any,
        lease: WorkerLease,
        *,
        error_code: str,
        details: Mapping[str, object],
    ) -> None:
        changed = connection.execute(
            """UPDATE durable_jobs SET status = 'failed', error_code = %s,
                 error_detail = %s::jsonb, lease_owner = NULL, lease_token = NULL,
                 lease_expires_at = NULL, heartbeat_at = NULL,
                 completed_at = clock_timestamp(), updated_at = clock_timestamp()
               WHERE id = %s AND project_id = %s AND lease_token = %s
                 AND fencing_generation = %s""",
            (
                error_code,
                json.dumps(dict(details)),
                lease.job_id,
                lease.project_id,
                lease.lease_token,
                lease.fencing_generation,
            ),
        ).rowcount
        if changed != 1:
            raise LostJobLease("job lease was fenced during failure handling")
        self._event(connection, lease, "job_failed", details)

    def fail_with_retry_in_transaction(
        self,
        connection: Any,
        lease: WorkerLease,
        *,
        error_code: str,
        details: Mapping[str, object],
        retry_delay: timedelta,
    ) -> str:
        retry = lease.attempt_count < lease.max_attempts
        status = "retry_wait" if retry else "dead_lettered"
        next_run_at = datetime.now(UTC) + retry_delay
        changed = connection.execute(
            """UPDATE durable_jobs SET status = %s, error_code = %s,
                 error_detail = %s::jsonb, next_run_at = %s,
                 lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                 heartbeat_at = NULL, updated_at = clock_timestamp(),
                 completed_at = CASE WHEN %s = 'dead_lettered'
                                     THEN clock_timestamp() ELSE NULL END
               WHERE id = %s AND project_id = %s AND lease_token = %s
                 AND fencing_generation = %s""",
            (
                status,
                error_code,
                json.dumps(dict(details)),
                next_run_at,
                status,
                lease.job_id,
                lease.project_id,
                lease.lease_token,
                lease.fencing_generation,
            ),
        ).rowcount
        if changed != 1:
            raise LostJobLease("job lease was fenced during retry handling")
        self._event(connection, lease, f"job_{status}", details)
        return status

    def cancel(self, lease: WorkerLease) -> None:
        connection = self.open_project(lease.project_id)
        try:
            changed = connection.execute(
                """UPDATE durable_jobs SET status = 'cancelled', lease_owner = NULL,
                     lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                     completed_at = clock_timestamp(), updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s AND lease_token = %s
                     AND fencing_generation = %s""",
                (lease.job_id, lease.project_id, lease.lease_token, lease.fencing_generation),
            ).rowcount
            if changed != 1:
                raise LostJobLease("job lease was fenced during cancellation")
            self._event(connection, lease, "job_cancelled", {})
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _set_terminal(
        self,
        connection: Any,
        row: Mapping[str, Any],
        *,
        worker_id: str,
        status: str,
        error_code: str | None = None,
    ) -> None:
        connection.execute(
            """UPDATE durable_jobs SET status = %s, error_code = %s,
                 lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                 heartbeat_at = NULL, completed_at = clock_timestamp(),
                 updated_at = clock_timestamp() WHERE id = %s AND project_id = %s""",
            (status, error_code, row["id"], row["project_id"]),
        )
        connection.execute(
            """INSERT INTO durable_job_events
                 (project_id, job_id, event_type, worker_id, details)
               VALUES (%s, %s, %s, %s, %s::jsonb)""",
            (row["project_id"], row["id"], f"job_{status}", worker_id, "{}"),
        )

    @staticmethod
    def _event(
        connection: Any,
        lease: WorkerLease,
        event_type: str,
        details: Mapping[str, object],
    ) -> None:
        connection.execute(
            """INSERT INTO durable_job_events
                 (project_id, job_id, event_type, worker_id, fencing_generation, details)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb)""",
            (
                lease.project_id,
                lease.job_id,
                event_type,
                lease.worker_id,
                lease.fencing_generation,
                json.dumps(dict(details)),
            ),
        )


class LeaseHeartbeat:
    """Keep a lease alive while a provider call runs without a database transaction."""

    def __init__(
        self,
        store: PostgresDurableJobStore,
        lease: WorkerLease,
        *,
        lease_for: timedelta,
        interval: timedelta,
    ) -> None:
        self._store = store
        self._lease = lease
        self._lease_for = lease_for
        self._interval = interval.total_seconds()
        self._stop = threading.Event()
        self._failure: BaseException | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "LeaseHeartbeat":
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self._stop.set()
        self._thread.join(timeout=max(1.0, self._interval + 1.0))

    def raise_if_stopped(self) -> None:
        if self._failure is not None:
            raise self._failure

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._store.heartbeat(self._lease, lease_for=self._lease_for)
            except BaseException as exc:
                self._failure = exc
                self._stop.set()
                return
