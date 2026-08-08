"""Atomic durable admission for a ready Browser Capture Task slice."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Any
from uuid import UUID, uuid5

from psycopg import Error as PsycopgError
from psycopg.types.json import Jsonb

from geo_core.browser_capture.admission import BROWSER_ATTEMPT_NAMESPACE
from geo_core.browser_capture.domain import BrowserCaptureError
from geo_core.connectors.contracts import canonical_hash
from geo_core.project_scope import set_project_scope


@dataclass(frozen=True)
class BrowserCaptureBulkAttempt:
    attempt_id: UUID
    durable_job_id: UUID
    scheduled_at: datetime


@dataclass(frozen=True)
class BrowserCaptureBulkResult:
    run_id: UUID
    planned_task_count: int
    enqueued_count: int
    skipped_count: int
    attempts: tuple[BrowserCaptureBulkAttempt, ...]
    replayed: bool

    @property
    def scheduled_at(self) -> tuple[datetime, ...]:
        return tuple(item.scheduled_at for item in self.attempts)


class BrowserCaptureBulkAdmissionService:
    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def enqueue_ready(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        surface_release_id: UUID,
        egress_endpoint_id: UUID,
        profile_version_id: UUID,
        task_versions: Sequence[tuple[UUID, int]],
        requested_not_before: datetime,
        authorization_checked_at: datetime,
        max_tasks: int,
        idempotency_key: str,
    ) -> BrowserCaptureBulkResult:
        key = idempotency_key.strip()
        if not key or len(key) > 240 or not 1 <= max_tasks <= 100_000:
            raise BrowserCaptureError("Browser Capture bulk command is invalid")
        if requested_not_before.tzinfo is None or authorization_checked_at.tzinfo is None:
            raise BrowserCaptureError("Browser Capture bulk times must be timezone-aware")
        items = [
            {
                "task_id": str(task_id),
                "attempt_id": str(
                    uuid5(
                        BROWSER_ATTEMPT_NAMESPACE,
                        f"{project_id}:{run_id}:{task_id}:{key}",
                    )
                ),
                "expected_task_version": task_version,
                "idempotency_key_hash": _key_hash(f"{key}:{task_id}"),
            }
            for task_id, task_version in task_versions
        ]
        command = {
            "run_id": str(run_id),
            "surface_release_id": str(surface_release_id),
            "egress_endpoint_id": str(egress_endpoint_id),
            "profile_version_id": str(profile_version_id),
            "requested_not_before": requested_not_before.isoformat(),
            "max_tasks": max_tasks,
            "items": items,
        }
        try:
            with self._connect() as connection:
                set_project_scope(connection, project_id)
                row = connection.execute(
                    """SELECT geo_enqueue_ready_browser_capture_attempts(
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                       ) AS result""",
                    (
                        project_id,
                        run_id,
                        surface_release_id,
                        egress_endpoint_id,
                        profile_version_id,
                        _key_hash(key),
                        canonical_hash(command),
                        requested_not_before,
                        authorization_checked_at,
                        max_tasks,
                        Jsonb(items),
                    ),
                ).fetchone()
        except PsycopgError as error:
            reason = str(error).splitlines()[0].strip()
            raise BrowserCaptureError(
                reason or "Browser Capture bulk database admission failed"
            ) from error
        if row is None or not isinstance(row["result"], Mapping):
            raise BrowserCaptureError("Browser Capture bulk admission returned no result")
        return _parse_result(row["result"], expected_run_id=run_id)


def _parse_result(
    value: Mapping[str, object], *, expected_run_id: UUID
) -> BrowserCaptureBulkResult:
    try:
        run_id = UUID(str(value["run_id"]))
        raw_attempts = value["attempts"]
        if run_id != expected_run_id or not isinstance(raw_attempts, list):
            raise ValueError
        attempts = tuple(
            BrowserCaptureBulkAttempt(
                attempt_id=UUID(str(item["attempt_id"])),
                durable_job_id=UUID(str(item["durable_job_id"])),
                scheduled_at=_datetime(item["scheduled_at"]),
            )
            for item in raw_attempts
            if isinstance(item, Mapping)
        )
        result = BrowserCaptureBulkResult(
            run_id=run_id,
            planned_task_count=int(str(value["planned_task_count"])),
            enqueued_count=int(str(value["enqueued_count"])),
            skipped_count=int(str(value["skipped_count"])),
            attempts=attempts,
            replayed=value["replayed"] is True,
        )
    except (KeyError, TypeError, ValueError):
        raise BrowserCaptureError("Browser Capture bulk result is invalid") from None
    if result.enqueued_count != len(result.attempts):
        raise BrowserCaptureError("Browser Capture bulk result count is inconsistent")
    return result


def _datetime(value: object) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError
    return value


def _key_hash(value: str) -> str:
    return hashlib.sha256(
        canonical_hash({"idempotency_key": value}).encode("ascii")
    ).hexdigest()


__all__ = [
    "BrowserCaptureBulkAdmissionService",
    "BrowserCaptureBulkAttempt",
    "BrowserCaptureBulkResult",
]
