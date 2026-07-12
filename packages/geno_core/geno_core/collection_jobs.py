from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from geno_core.audit import build_audit_event


COLLECTION_JOB_COLUMNS = (
    "id",
    "project_id",
    "status",
    "mode",
    "prompt_limit",
    "sample_size",
    "cities",
    "requested_by",
    "attempt_count",
    "max_attempts",
    "next_attempt_at",
    "locked_by",
    "locked_at",
    "lease_expires_at",
    "result_summary",
    "last_error_code",
    "last_error_message",
    "started_at",
    "completed_at",
    "cancelled_at",
    "created_at",
    "updated_at",
)


def _row(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return dict(zip(COLLECTION_JOB_COLUMNS, row, strict=True))


def _uuid(value: str) -> UUID:
    return UUID(str(value))


class CollectionJobStore:
    def __init__(self, repository: Any) -> None:
        self.repository = repository
        self.connection = repository.connection

    def enqueue(
        self,
        *,
        project_id: str,
        requested_by: str,
        prompt_limit: int,
        sample_size: int,
        cities: tuple[str, ...],
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        normalized_cities = tuple(dict.fromkeys(city.strip() for city in cities if city.strip()))
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT status FROM projects WHERE id = %s LIMIT 1", (_uuid(project_id),))
            project = cursor.fetchone()
            if not project:
                raise ValueError("project not found")
            project_status = str(project[0] if not isinstance(project, dict) else project["status"])
            if project_status != "active":
                raise ValueError("project must be running before collection can be queued")
            if not normalized_cities:
                cursor.execute(
                    """
                    SELECT DISTINCT city
                    FROM prompt_questions
                    WHERE project_id = %s AND status = 'active' AND city <> ''
                    ORDER BY city
                    """,
                    (_uuid(project_id),),
                )
                normalized_cities = tuple(
                    str(row[0] if not isinstance(row, dict) else row["city"])
                    for row in cursor.fetchall()
                ) or ("Global",)
            cursor.execute(
                f"""
                INSERT INTO collection_jobs (
                  project_id, mode, prompt_limit, sample_size, cities, requested_by, max_attempts
                ) VALUES (%s, 'api', %s, %s, %s, %s, %s)
                RETURNING {", ".join(COLLECTION_JOB_COLUMNS)}
                """,
                (
                    _uuid(project_id),
                    max(1, min(int(prompt_limit), 200)),
                    max(1, min(int(sample_size), 20)),
                    list(normalized_cities),
                    requested_by,
                    max(1, min(int(max_attempts), 10)),
                ),
            )
            job = _row(cursor.fetchone())
            audit = build_audit_event(
                event_type="collection.job_queued",
                project_id=project_id,
                actor_type="user",
                actor_id=requested_by,
                target_type="collection_job",
                target_id=str(job["id"]),
                before=None,
                after={"status": "queued", "mode": "api"},
                input_refs={"project_ids": [project_id]},
                output_refs={"collection_job_ids": [str(job["id"])]},
                method_version="collection_job_v1",
                reason="project collection queued",
            )
            self.repository.save_audit_events((audit,), cursor=cursor)
        self.connection.commit()
        return job

    def list(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        filters = ["project_id = %s"]
        params: list[Any] = [_uuid(project_id)]
        if status:
            filters.append("status = %s")
            params.append(status.strip().lower())
        where = " AND ".join(filters)
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM collection_jobs WHERE {where}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(COLLECTION_JOB_COLUMNS)}
                FROM collection_jobs
                WHERE {where}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, max(1, min(limit, 100)), max(0, offset)),
            )
            records = [_row(item) for item in cursor.fetchall()]
        return {"total_count": total_count, "limit": limit, "offset": offset, "records": records}

    def claim_next(self, *, worker_id: str, lease_seconds: int = 3600) -> dict[str, Any] | None:
        with self.connection.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute(
                """
                SELECT id
                FROM collection_jobs
                WHERE status = 'queued' AND next_attempt_at <= now()
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            )
            candidate = cursor.fetchone()
            if not candidate:
                self.connection.rollback()
                return None
            job_id = candidate[0] if not isinstance(candidate, dict) else candidate["id"]
            cursor.execute(
                f"""
                UPDATE collection_jobs
                SET status = 'running', locked_by = %s, locked_at = now(),
                    lease_expires_at = now() + (%s || ' seconds')::interval,
                    attempt_count = attempt_count + 1,
                    started_at = COALESCE(started_at, now()), updated_at = now()
                WHERE id = %s
                RETURNING {", ".join(COLLECTION_JOB_COLUMNS)}
                """,
                (worker_id, max(1, lease_seconds), job_id),
            )
            job = _row(cursor.fetchone())
            self.connection.commit()
            return job

    def complete(self, *, job: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        failure_count = int(result.get("failure_count") or 0)
        success_count = int(result.get("success_count") or 0)
        status = "partial_succeeded" if failure_count and success_count else "succeeded"
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE collection_jobs
                SET status = %s, result_summary = %s::jsonb, completed_at = now(),
                    locked_by = null, locked_at = null, lease_expires_at = null,
                    last_error_code = null, last_error_message = null, updated_at = now()
                WHERE id = %s
                RETURNING {", ".join(COLLECTION_JOB_COLUMNS)}
                """,
                (status, json.dumps(result, ensure_ascii=False, default=str), job["id"]),
            )
            updated = _row(cursor.fetchone())
        self.connection.commit()
        return updated

    def fail(self, *, job: dict[str, Any], error_code: str, error_message: str, retry_seconds: int = 120) -> dict[str, Any]:
        attempt_count = int(job.get("attempt_count") or 0)
        max_attempts = int(job.get("max_attempts") or 3)
        status = "dead_letter" if attempt_count >= max_attempts else "queued"
        next_attempt = datetime.now(UTC) + timedelta(seconds=max(1, retry_seconds))
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE collection_jobs
                SET status = %s, next_attempt_at = %s,
                    last_error_code = %s, last_error_message = %s,
                    locked_by = null, locked_at = null, lease_expires_at = null,
                    completed_at = CASE WHEN %s = 'dead_letter' THEN now() ELSE null END,
                    updated_at = now()
                WHERE id = %s
                RETURNING {", ".join(COLLECTION_JOB_COLUMNS)}
                """,
                (status, next_attempt, error_code, error_message[:2000], status, job["id"]),
            )
            updated = _row(cursor.fetchone())
        self.connection.commit()
        return updated

    def cancel(self, *, project_id: str, job_id: str) -> dict[str, Any]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE collection_jobs
                SET status = 'cancelled', cancelled_at = now(), completed_at = now(), updated_at = now()
                WHERE id = %s AND project_id = %s AND status = 'queued'
                RETURNING {", ".join(COLLECTION_JOB_COLUMNS)}
                """,
                (_uuid(job_id), _uuid(project_id)),
            )
            updated = _row(cursor.fetchone())
        if not updated:
            self.connection.rollback()
            raise ValueError("queued collection job not found")
        self.connection.commit()
        return updated
