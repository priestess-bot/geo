"""Persistent operator tasks opened by due placement measurement jobs."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from geo_core.placements.domain import (
    MeasurementCollectionTask,
    PlacementConflict,
    PlacementNotFound,
    PlacementRuleViolation,
)


_TASK_COLUMNS = """id, project_id, job_id, submission_id, protocol_id,
    measurement_window, expected_sample_count, actual_sample_count,
    scheduled_for, status, opened_at, completed_at, cancelled_at,
    acted_by, state_reason"""


def _row(cursor: Any) -> dict[str, Any]:
    value = cursor.fetchone()
    if value is None:
        raise PlacementNotFound("measurement collection task does not exist")
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((item.name for item in cursor.description), value, strict=True))


def _rows(cursor: Any) -> list[dict[str, Any]]:
    values = cursor.fetchall()
    if not values:
        return []
    if isinstance(values[0], Mapping):
        return [dict(value) for value in values]
    names = [item.name for item in cursor.description]
    return [dict(zip(names, value, strict=True)) for value in values]


class PostgresMeasurementTaskMixin:
    _db: Any

    def list_measurement_collection_tasks(
        self, *, project_id: UUID, submission_id: UUID | None, status: str | None
    ) -> tuple[MeasurementCollectionTask, ...]:
        records = _rows(
            self._db.execute(
                f"""SELECT {_TASK_COLUMNS} FROM measurement_collection_tasks
                    WHERE project_id = %s
                      AND (%s::uuid IS NULL OR submission_id = %s::uuid)
                      AND (%s::text IS NULL OR status = %s::text)
                    ORDER BY scheduled_for, opened_at""",
                (project_id, submission_id, submission_id, status, status),
            )
        )
        return tuple(MeasurementCollectionTask(**record) for record in records)

    def complete_measurement_collection_task(
        self, *, project_id: UUID, task_id: UUID, actor_id: UUID
    ) -> MeasurementCollectionTask:
        current = _row(
            self._db.execute(
                f"""SELECT {_TASK_COLUMNS} FROM measurement_collection_tasks
                    WHERE id = %s AND project_id = %s FOR UPDATE""",
                (task_id, project_id),
            )
        )
        protocol_status = _row(
            self._db.execute(
                """SELECT status FROM monitoring_protocols
                   WHERE id = %s AND project_id = %s""",
                (current["protocol_id"], project_id),
            )
        )["status"]
        if current["status"] == "completed":
            return MeasurementCollectionTask(**current)
        if current["status"] != "open":
            raise PlacementConflict("only an open measurement collection task can complete")
        if protocol_status != "frozen":
            raise PlacementConflict("measurement collection requires a frozen protocol")
        actual = _row(
            self._db.execute(
                """SELECT count(*) AS count FROM monitoring_observations
                   WHERE project_id = %s AND protocol_id = %s AND measurement_window = %s""",
                (project_id, current["protocol_id"], current["measurement_window"]),
            )
        )["count"]
        if actual < current["expected_sample_count"]:
            raise PlacementConflict(
                f"measurement samples are incomplete: {actual}/{current['expected_sample_count']}"
            )
        updated = _row(
            self._db.execute(
                f"""UPDATE measurement_collection_tasks
                    SET status = 'completed', actual_sample_count = %s,
                        completed_at = clock_timestamp(), acted_by = %s
                    WHERE id = %s AND project_id = %s
                    RETURNING {_TASK_COLUMNS}""",
                (actual, actor_id, task_id, project_id),
            )
        )
        return MeasurementCollectionTask(**updated)

    def cancel_measurement_collection_task(
        self, *, project_id: UUID, task_id: UUID, actor_id: UUID, reason: str
    ) -> MeasurementCollectionTask:
        if not reason.strip():
            raise PlacementRuleViolation("measurement task cancellation requires a reason")
        current = _row(
            self._db.execute(
                f"""SELECT {_TASK_COLUMNS} FROM measurement_collection_tasks
                    WHERE id = %s AND project_id = %s FOR UPDATE""",
                (task_id, project_id),
            )
        )
        if current["status"] == "cancelled":
            return MeasurementCollectionTask(**current)
        if current["status"] != "open":
            raise PlacementConflict("only an open measurement collection task can cancel")
        updated = _row(
            self._db.execute(
                f"""UPDATE measurement_collection_tasks
                    SET status = 'cancelled', cancelled_at = clock_timestamp(),
                        acted_by = %s, state_reason = %s
                    WHERE id = %s AND project_id = %s
                    RETURNING {_TASK_COLUMNS}""",
                (actor_id, reason.strip(), task_id, project_id),
            )
        )
        return MeasurementCollectionTask(**updated)
