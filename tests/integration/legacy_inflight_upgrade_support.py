from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID, uuid4

import psycopg


def insert_legacy_job(
    connection: psycopg.Connection[Any],
    *,
    job_id: UUID,
    project_id: UUID,
    kind: str,
    label: str,
    running: bool,
) -> None:
    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, kind, status, input_hash, idempotency_key,
              attempt_count, lease_owner, lease_token, lease_expires_at,
              heartbeat_at, fencing_generation, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                   CASE WHEN %s THEN clock_timestamp() - interval '10 minutes' END,
                   CASE WHEN %s THEN clock_timestamp() - interval '12 minutes' END,
                   %s, clock_timestamp() - interval '15 minutes')""",
        (
            job_id,
            project_id,
            kind,
            "running" if running else "queued",
            hashlib.sha256(label.encode()).hexdigest(),
            label,
            1 if running else 0,
            "retired-worker" if running else None,
            uuid4() if running else None,
            running,
            running,
            1 if running else 0,
        ),
    )


def job_events(connection: psycopg.Connection[Any], *, job_id: UUID) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            """SELECT event_type FROM durable_job_events
               WHERE job_id = %s ORDER BY created_at, id""",
            (job_id,),
        ).fetchall()
    ]
