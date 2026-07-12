from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from geno_core.audit import build_audit_event
from geno_core.durable_jobs import (
    ClaimMode,
    ClaimOutcome,
    LeaseClaim,
    LeaseGuard,
    acknowledge_durable_cancel,
    begin_durable_finalizing,
    claim_durable_job,
    complete_durable_job,
    durable_job_spec,
    fail_durable_job,
    record_recovery_pass,
    request_durable_cancel,
)


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
    "heartbeat_at",
    "lease_reclaimed_count",
    "last_reclaimed_at",
    "last_reclaimed_from",
    "dead_lettered_at",
    "cancel_requested_at",
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

    def claim_next_outcome(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 3600,
        mode: ClaimMode = "any",
    ) -> ClaimOutcome:
        return claim_durable_job(
            self.connection,
            durable_job_spec("collection_jobs"),
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            mode=mode,
        )

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 3600,
        mode: ClaimMode = "any",
    ) -> LeaseClaim | None:
        return self.claim_next_outcome(
            worker_id=worker_id, lease_seconds=lease_seconds, mode=mode
        ).claim

    def complete(self, *, claim: LeaseClaim, result: dict[str, Any]) -> dict[str, Any]:
        failure_count = int(result.get("failure_count") or 0)
        success_count = int(result.get("success_count") or 0)
        status = "partial_succeeded" if failure_count and success_count else "succeeded"
        return complete_durable_job(
            self.connection, claim, status=status, result=result
        )

    def begin_finalizing(self, *, claim: LeaseClaim, result: dict[str, Any]) -> dict[str, Any]:
        failure_count = int(result.get("failure_count") or 0)
        success_count = int(result.get("success_count") or 0)
        terminal_status = "partial_succeeded" if failure_count and success_count else "succeeded"
        return begin_durable_finalizing(
            self.connection,
            claim,
            descriptor={
                "descriptor_version": "durable_artifact_finalize_v1",
                "terminal_status": terminal_status,
                "result": result,
            },
        )

    def fail(
        self,
        *,
        claim: LeaseClaim,
        error_code: str,
        error_message: str,
        retry_seconds: int = 120,
        retryable: bool = True,
    ) -> dict[str, Any]:
        self.connection.rollback()
        return fail_durable_job(
            self.connection,
            claim,
            error_code=error_code,
            error_message=error_message,
            retry_seconds=retry_seconds,
            retryable=retryable,
        )

    def cancel(self, *, project_id: str, job_id: str) -> dict[str, Any]:
        cancelled = request_durable_cancel(
            self.connection,
            durable_job_spec("collection_jobs"),
            project_id=_uuid(project_id),
            job_id=_uuid(job_id),
        )
        cancelled.pop("lease_token", None)
        cancelled.pop("finalize_descriptor", None)
        return cancelled

    def acknowledge_cancel(self, claim: LeaseClaim) -> dict[str, Any]:
        self.connection.rollback()
        return acknowledge_durable_cancel(self.connection, claim)

    def record_recovery_pass(self, *, worker_id: str, slots_used: int) -> None:
        record_recovery_pass(
            self.connection,
            queue_name="collection_recovery",
            worker_id=worker_id,
            slots_used=slots_used,
        )

    def lease_guard(self, claim: LeaseClaim, *, lease_seconds: int) -> LeaseGuard:
        import psycopg

        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError("DATABASE_URL is required for the independent LeaseGuard connection")

        def initialize_scope(connection: Any, worker_id: str) -> None:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.rls_enabled', 'false', false)")
                cursor.execute("SELECT set_config('geno.runtime_project_access_control', 'false', false)")
                cursor.execute("SELECT set_config('app.actor_id', %s, false)", (worker_id,))
                cursor.execute("SELECT set_config('geno.runtime_actor_id', %s, false)", (worker_id,))
                cursor.execute("SELECT set_config('app.project_id', '', false)")
                cursor.execute("SELECT set_config('geno.runtime_project_id', '', false)")
                cursor.execute("SELECT set_config('app.project_ids', '', false)")
                cursor.execute("SELECT set_config('app.roles', 'system,worker', false)")
            connection.commit()

        return LeaseGuard(
            claim,
            lease_seconds=lease_seconds,
            connection_factory=lambda: psycopg.connect(database_url),
            scope_initializer=initialize_scope,
        )
