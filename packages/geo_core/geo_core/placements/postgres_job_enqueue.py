"""Campaign-scoped durable job enqueue shared by Placement repositories."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID

from geo_core.placements.domain import (
    JobReference,
    PlacementConflict,
    canonical_hash,
)


class PostgresJobEnqueueMixin:
    _db: Any

    def _enqueue_job(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        kind: str,
        input_value: Mapping[str, object],
        idempotency_key: str,
    ) -> JobReference:
        input_hash = canonical_hash(
            {"campaign_id": str(campaign_id), "input": dict(input_value)}
        )
        cursor = self._db.execute(
            """INSERT INTO durable_jobs
                 (project_id, campaign_id, kind, input_hash, idempotency_key)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (project_id, kind, idempotency_key, replay_nonce) DO NOTHING
               RETURNING id, project_id, campaign_id, kind, status, input_hash""",
            (project_id, campaign_id, kind, input_hash, idempotency_key),
        )
        record = _optional_row(cursor)
        if record is None:
            record = _required_row(
                self._db.execute(
                    """SELECT id, project_id, campaign_id, kind, status, input_hash
                       FROM durable_jobs WHERE project_id = %s AND kind = %s
                         AND idempotency_key = %s AND replay_nonce = 0""",
                    (project_id, kind, idempotency_key),
                )
            )
            if record["input_hash"] != input_hash:
                raise PlacementConflict(
                    "idempotency key was already used with different input"
                )
        job = JobReference(
            id=record["id"],
            project_id=record["project_id"],
            campaign_id=record["campaign_id"],
            kind=record["kind"],
            status=record["status"],
        )
        self._db.execute(
            """INSERT INTO broker_outbox
                 (project_id, job_id, topic, payload, idempotency_key)
               VALUES (%s, %s, %s, %s::jsonb, %s)
               ON CONFLICT (project_id, idempotency_key) DO NOTHING""",
            (
                project_id,
                job.id,
                kind,
                json.dumps({"job_id": str(job.id)}),
                f"wake:{kind}:{idempotency_key}",
            ),
        )
        return job


def _optional_row(cursor: Any) -> dict[str, Any] | None:
    record = cursor.fetchone()
    if record is None:
        return None
    if isinstance(record, Mapping):
        return dict(record)
    return dict(zip((item.name for item in cursor.description), record, strict=True))


def _required_row(cursor: Any) -> dict[str, Any]:
    record = _optional_row(cursor)
    if record is None:
        raise RuntimeError("expected PostgreSQL row was not returned")
    return record
