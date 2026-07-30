"""Project-scoped admission of automated UI Sampling Attempts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import hashlib
from typing import Any
from uuid import UUID, uuid5

from psycopg import Error as PsycopgError

from geo_core.browser_capture.domain import BrowserCaptureError
from geo_core.connectors.contracts import canonical_hash
from geo_core.project_scope import set_project_scope


BROWSER_ATTEMPT_NAMESPACE = UUID("8a52ee91-9d76-51ba-b794-a3d475bf18ee")


class BrowserCaptureAttemptAdmissionService:
    def __init__(
        self, *, connect: Callable[[], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._clock = clock

    def enqueue(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        expected_task_version: int,
        surface_release_id: UUID,
        egress_endpoint_id: UUID,
        profile_version_id: UUID,
        requested_not_before: datetime,
        idempotency_key: str,
    ) -> Mapping[str, object]:
        key = idempotency_key.strip()
        if not key or len(key) > 240 or expected_task_version < 1:
            raise BrowserCaptureError("Idempotency key and positive Task version are required")
        now = self._clock()
        if requested_not_before.tzinfo is None or requested_not_before < now:
            raise BrowserCaptureError("Browser Capture requested_not_before must be current or future")
        attempt_id = uuid5(BROWSER_ATTEMPT_NAMESPACE, f"{project_id}:{key}")
        try:
            with self._connect() as connection:
                set_project_scope(connection, project_id)
                row = connection.execute(
                    """SELECT item.query_text_hash
                         FROM workflow_c_sampling_tasks task
                         JOIN workflow_c_sampling_runs run
                           ON run.project_id = task.project_id AND run.id = task.run_id
                         JOIN workflow_c_sampling_suites suite
                           ON suite.project_id = run.project_id AND suite.id = run.suite_id
                         JOIN knowledge_question_set_items item
                           ON item.project_id = suite.project_id
                          AND item.question_set_id::text =
                              suite.payload->'suite'->>'question_set_id'
                          AND item.id::text = task.question_id
                        WHERE task.project_id = %s AND task.id = %s AND task.run_id = %s""",
                    (project_id, task_id, run_id),
                ).fetchone()
                if row is None:
                    raise BrowserCaptureError(
                        "Browser Sampling Task or frozen question was not found"
                    )
                spec = {
                    "schema_version": 1,
                    "kind": "browser.capture",
                    "run_id": str(run_id),
                    "task_id": str(task_id),
                    "attempt_id": str(attempt_id),
                    "task_version": expected_task_version + 1,
                    "attempt_version": 1,
                    "surface_release_id": str(surface_release_id),
                    "egress_endpoint_id": str(egress_endpoint_id),
                    "profile_version_id": str(profile_version_id),
                    "question_hash": row["query_text_hash"],
                }
                result = connection.execute(
                    """SELECT * FROM geo_enqueue_browser_capture_attempt(
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                       )""",
                    (
                        project_id, attempt_id, run_id, task_id, expected_task_version,
                        surface_release_id, egress_endpoint_id, profile_version_id,
                        _key_hash(key), canonical_hash(spec), requested_not_before, now,
                    ),
                ).fetchone()
        except PsycopgError as error:
            reason = str(error).splitlines()[0].strip()
            raise BrowserCaptureError(
                reason or "Browser Capture database admission failed"
            ) from error
        if result is None:
            raise BrowserCaptureError("Browser Capture Attempt admission returned no result")
        return dict(result)


def _key_hash(value: str) -> str:
    return hashlib.sha256(
        canonical_hash({"idempotency_key": value}).encode("ascii")
    ).hexdigest()


__all__ = ["BROWSER_ATTEMPT_NAMESPACE", "BrowserCaptureAttemptAdmissionService"]
