"""Acceptance helpers for scheduled placement measurement jobs."""

from __future__ import annotations

from uuid import UUID

from geo_core.jobs.postgres import PostgresDurableJobStore


def measurement_windows(
    store: PostgresDurableJobStore, project_id: UUID, submission_id: UUID
) -> tuple[int, ...]:
    connection = store.open_project(project_id)
    try:
        rows = connection.execute(
            """SELECT due_offset_days FROM measurement_job_specs
               WHERE project_id = %s AND submission_id = %s ORDER BY due_offset_days""",
            (project_id, submission_id),
        ).fetchall()
        connection.commit()
    finally:
        connection.close()
    return tuple(int(row[0]) for row in rows)


def make_measurement_job_due(
    store: PostgresDurableJobStore,
    project_id: UUID,
    submission_id: UUID,
    *,
    due_offset_days: int,
) -> UUID:
    connection = store.open_project(project_id)
    try:
        row = connection.execute(
            """SELECT job_id FROM measurement_job_specs
               WHERE project_id = %s AND submission_id = %s AND due_offset_days = %s""",
            (project_id, submission_id, due_offset_days),
        ).fetchone()
        if row is None:
            raise AssertionError("scheduled measurement job does not exist")
        connection.execute(
            """UPDATE durable_jobs SET next_run_at = clock_timestamp()
               WHERE id = %s AND project_id = %s""",
            (row[0], project_id),
        )
        connection.commit()
        return row[0]
    finally:
        connection.close()
