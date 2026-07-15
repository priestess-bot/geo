from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Literal
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5


ClaimMode = Literal["fresh", "recovery", "any"]


class LostLeaseError(RuntimeError):
    """The current process no longer owns an unexpired fencing token."""

    def __init__(self, message: str, *, cancel_requested: bool = False) -> None:
        super().__init__(message)
        self.cancel_requested = cancel_requested


class JobStateConflictError(RuntimeError):
    """A requested state transition lost to a terminal transition."""


@dataclass(frozen=True)
class DurableJobSpec:
    table: str
    schedule_column: str
    priority_column: str | None
    success_statuses: frozenset[str]
    result_column: str | None = None
    supports_finalizing: bool = False
    has_cancelled_at: bool = False


@dataclass(frozen=True)
class LeaseClaim:
    spec: DurableJobSpec
    job_id: UUID
    project_id: UUID
    worker_id: str
    lease_token: UUID = field(repr=False)
    lease_expires_at: datetime
    claimed_from: str
    attempt_count: int
    reclaimed: bool
    record: Mapping[str, Any] = field(repr=False)

    @property
    def token_fingerprint(self) -> str:
        return _token_fingerprint(self.lease_token)

    def worker_payload(self) -> dict[str, Any]:
        """Return handler input without the fencing token."""
        return {key: value for key, value in self.record.items() if key != "lease_token"}


@dataclass(frozen=True)
class ClaimOutcome:
    kind: Literal["claimed", "cancelled", "dead_lettered", "empty"]
    spec: DurableJobSpec
    claim: LeaseClaim | None = None
    job_id: UUID | None = None
    previous_status: str | None = None


_COMMON_SUCCESS = frozenset({"succeeded", "partial_succeeded"})
_SPECS = {
    "knowledge_import_jobs": DurableJobSpec(
        "knowledge_import_jobs", "next_run_at", "priority", _COMMON_SUCCESS, "result_summary", True
    ),
    "crawl_jobs": DurableJobSpec("crawl_jobs", "next_run_at", "priority", _COMMON_SUCCESS, "result_summary", True),
    "knowledge_parser_runs": DurableJobSpec(
        "knowledge_parser_runs",
        "next_run_at",
        "priority",
        frozenset({"succeeded", "fallback_succeeded", "partial_succeeded"}),
        None,
        True,
    ),
    "chunk_jobs": DurableJobSpec("chunk_jobs", "next_run_at", "priority", _COMMON_SUCCESS, "result_summary", True),
    "embedding_jobs": DurableJobSpec(
        "embedding_jobs", "next_run_at", "priority", _COMMON_SUCCESS, "result_summary", True
    ),
    "fact_extraction_jobs": DurableJobSpec(
        "fact_extraction_jobs", "next_run_at", "priority", _COMMON_SUCCESS
    ),
    "prompt_generation_jobs": DurableJobSpec(
        "prompt_generation_jobs", "next_run_at", "priority", _COMMON_SUCCESS
    ),
    "content_generation_jobs": DurableJobSpec(
        "content_generation_jobs", "next_run_at", "priority", frozenset({"succeeded"})
    ),
    "collection_jobs": DurableJobSpec(
        "collection_jobs",
        "next_attempt_at",
        None,
        _COMMON_SUCCESS,
        "result_summary",
        True,
        True,
    ),
}
DURABLE_JOB_SPECS: Mapping[str, DurableJobSpec] = MappingProxyType(_SPECS)
KNOWLEDGE_JOB_TABLES = tuple(table for table in _SPECS if table != "collection_jobs")


def durable_job_spec(table: str) -> DurableJobSpec:
    try:
        return DURABLE_JOB_SPECS[table]
    except KeyError as exc:
        raise ValueError("unsupported durable job table") from exc


def _trusted_spec(spec: DurableJobSpec) -> DurableJobSpec:
    trusted = durable_job_spec(spec.table)
    if trusted != spec:
        raise ValueError("durable job spec does not match the static allowlist")
    return trusted


def _token_fingerprint(token: object) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()[:16]


def _row_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    return dict(row)


def _queue_name(spec: DurableJobSpec) -> str:
    return "collection" if spec.table == "collection_jobs" else "knowledge"


def _increment_metric(cursor: Any, spec: DurableJobSpec, metric_name: str) -> None:
    cursor.execute(
        """
        INSERT INTO durable_job_metric_counters (
          queue_name, job_type, metric_name, metric_value
        ) VALUES (%s, %s, %s, 1)
        ON CONFLICT (queue_name, job_type, metric_name) DO UPDATE SET
          metric_value = durable_job_metric_counters.metric_value + 1,
          updated_at = now()
        """,
        (_queue_name(spec), spec.table, metric_name),
    )


def _begin(connection: Any) -> None:
    connection.rollback()


def _record_lease_audit(
    cursor: Any,
    *,
    record: Mapping[str, Any],
    spec: DurableJobSpec,
    event_type: str,
    worker_id: str,
    token: object,
    previous_worker: object,
    previous_status: str,
    reason: str,
    attempt_increment: int = 1,
) -> None:
    token_fingerprint = _token_fingerprint(token)
    before = {
        "status": previous_status,
        "worker": str(previous_worker or ""),
        "attempt": max(
            0,
            int(record.get("attempt_count") or 0)
            - (attempt_increment if event_type.endswith("claimed") else 0),
        ),
    }
    after = {
        "status": str(record.get("status") or ""),
        "worker": worker_id,
        "attempt": int(record.get("attempt_count") or 0),
        "token_fingerprint": token_fingerprint,
    }
    before_hash = hashlib.sha256(json.dumps(before, sort_keys=True).encode("utf-8")).hexdigest()
    after_hash = hashlib.sha256(json.dumps(after, sort_keys=True).encode("utf-8")).hexdigest()
    audit_id = uuid5(
        NAMESPACE_URL,
        f"durable-lease::{spec.table}::{record['id']}::{event_type}::{token_fingerprint}",
    )
    cursor.execute(
        """
        INSERT INTO audit_events (
          id, event_type, project_id, actor_type, actor_id, target_type, target_id,
          before_hash, after_hash, input_refs, output_refs, method_version, reason
        ) VALUES (%s, %s, %s, 'worker', %s, 'durable_job', %s,
                  %s, %s, %s::jsonb, %s::jsonb, 'durable_job_lease_v1', %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            audit_id,
            event_type,
            record["project_id"],
            worker_id,
            str(record["id"]),
            before_hash,
            after_hash,
            json.dumps({"table": spec.table, "previous_worker": str(previous_worker or "")}),
            json.dumps({"status": record.get("status"), "token_fingerprint": token_fingerprint}),
            reason,
        ),
    )


def _valid_finalize_descriptor(spec: DurableJobSpec, record: Mapping[str, Any]) -> bool:
    descriptor = record.get("finalize_descriptor")
    if not spec.supports_finalizing or not isinstance(descriptor, Mapping):
        return False
    result = descriptor.get("result")
    return (
        descriptor.get("descriptor_version") == "durable_artifact_finalize_v1"
        and descriptor.get("terminal_status") in spec.success_statuses
        and isinstance(result, Mapping)
        and bool(result)
    )


def durable_claim_candidate_sql(spec: DurableJobSpec, *, mode: Literal["fresh", "recovery"]) -> str:
    """Return the allowlisted candidate query used by production claim paths."""
    spec = _trusted_spec(spec)
    if mode == "recovery":
        predicate = (
            "status IN ('running', 'finalizing') AND lease_expires_at IS NOT NULL "
            "AND lease_expires_at <= now() AND cancel_requested_at IS NULL"
        )
        order_by = "lease_expires_at ASC"
    elif mode == "fresh":
        predicate = (
            f"status IN ('queued', 'retry_wait') AND {spec.schedule_column} <= now() "
            "AND cancel_requested_at IS NULL"
        )
        order_by = f"{spec.schedule_column} ASC"
    else:
        raise ValueError("candidate query mode must be fresh or recovery")
    if spec.priority_column:
        order_by += f", {spec.priority_column} DESC"
    order_by += ", created_at ASC"
    return f"""
        SELECT * FROM {spec.table}
        WHERE {predicate}
        ORDER BY {order_by}
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    """


def claim_durable_job(
    connection: Any,
    spec: DurableJobSpec,
    *,
    worker_id: str,
    lease_seconds: int,
    mode: ClaimMode = "any",
) -> ClaimOutcome:
    spec = _trusted_spec(spec)
    if mode not in {"fresh", "recovery", "any"}:
        raise ValueError("claim mode must be fresh, recovery or any")
    if not worker_id.strip():
        raise ValueError("worker_id is required")
    lease_seconds = max(3, int(lease_seconds))
    if mode == "any":
        recovery = claim_durable_job(
            connection, spec, worker_id=worker_id, lease_seconds=lease_seconds, mode="recovery"
        )
        if recovery.kind != "empty":
            return recovery
        return claim_durable_job(
            connection, spec, worker_id=worker_id, lease_seconds=lease_seconds, mode="fresh"
        )

    from psycopg.rows import dict_row

    candidate_sql = durable_claim_candidate_sql(spec, mode=mode)

    try:
        _begin(connection)
        with connection.cursor(row_factory=dict_row) as cursor:
            candidate: dict[str, Any] = {}
            if mode == "recovery":
                # Cancellation has its own reaping path so the indexed owner-
                # transfer predicate can remain cancel_requested_at IS NULL.
                cursor.execute(
                    f"""
                    SELECT * FROM {spec.table}
                    WHERE status IN ('running', 'finalizing')
                      AND lease_expires_at IS NOT NULL AND lease_expires_at <= now()
                      AND cancel_requested_at IS NOT NULL
                    ORDER BY lease_expires_at ASC, created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                )
                candidate = _row_dict(cursor.fetchone())
            if not candidate:
                cursor.execute(candidate_sql)
                candidate = _row_dict(cursor.fetchone())
            if not candidate:
                connection.rollback()
                return ClaimOutcome("empty", spec)

            previous_status = str(candidate["status"])
            previous_worker = candidate.get("locked_by")
            if candidate.get("cancel_requested_at") is not None:
                cancelled_at_sql = ", cancelled_at = now()" if spec.has_cancelled_at else ""
                cursor.execute(
                    f"""
                    UPDATE {spec.table}
                    SET status = 'cancelled', completed_at = now(){cancelled_at_sql},
                        locked_by = NULL, locked_at = NULL, heartbeat_at = NULL,
                        lease_expires_at = NULL, lease_token = NULL, updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (candidate["id"],),
                )
                updated = _row_dict(cursor.fetchone())
                _record_lease_audit(
                    cursor,
                    record=updated,
                    spec=spec,
                    event_type="durable_job.cancelled",
                    worker_id=worker_id,
                    token=candidate.get("lease_token") or "no-token",
                    previous_worker=previous_worker,
                    previous_status=previous_status,
                    reason="cancel request won before claim",
                )
                _increment_metric(cursor, spec, "cancelled")
                connection.commit()
                return ClaimOutcome("cancelled", spec, job_id=UUID(str(updated["id"])), previous_status=previous_status)

            descriptor_only_recovery = (
                mode == "recovery"
                and previous_status == "finalizing"
                and _valid_finalize_descriptor(spec, candidate)
            )
            if mode == "recovery" and previous_status == "finalizing" and not descriptor_only_recovery:
                cursor.execute(
                    f"""
                    UPDATE {spec.table}
                    SET status = 'dead_letter', dead_lettered_at = COALESCE(dead_lettered_at, now()),
                        completed_at = now(), locked_by = NULL, locked_at = NULL,
                        heartbeat_at = NULL, lease_expires_at = NULL, lease_token = NULL,
                        last_error_code = 'invalid_finalize_descriptor',
                        last_error_message = 'expired finalizing job has no valid persisted descriptor',
                        updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (candidate["id"],),
                )
                updated = _row_dict(cursor.fetchone())
                _record_lease_audit(
                    cursor,
                    record=updated,
                    spec=spec,
                    event_type="durable_job.dead_lettered",
                    worker_id=worker_id,
                    token=candidate.get("lease_token") or "no-token",
                    previous_worker=previous_worker,
                    previous_status=previous_status,
                    reason="invalid or missing persisted finalizing descriptor",
                )
                _increment_metric(cursor, spec, "dead_lettered")
                connection.commit()
                return ClaimOutcome(
                    "dead_lettered", spec, job_id=UUID(str(updated["id"])), previous_status=previous_status
                )

            if (
                int(candidate.get("attempt_count") or 0) >= int(candidate.get("max_attempts") or 0)
                and not descriptor_only_recovery
            ):
                cursor.execute(
                    f"""
                    UPDATE {spec.table}
                    SET status = 'dead_letter', dead_lettered_at = COALESCE(dead_lettered_at, now()),
                        completed_at = now(), locked_by = NULL, locked_at = NULL,
                        heartbeat_at = NULL, lease_expires_at = NULL, lease_token = NULL,
                        last_error_code = COALESCE(last_error_code, 'attempts_exhausted'),
                        last_error_message = COALESCE(last_error_message, 'maximum durable job attempts exhausted'),
                        updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (candidate["id"],),
                )
                updated = _row_dict(cursor.fetchone())
                _record_lease_audit(
                    cursor,
                    record=updated,
                    spec=spec,
                    event_type="durable_job.dead_lettered",
                    worker_id=worker_id,
                    token=candidate.get("lease_token") or "no-token",
                    previous_worker=previous_worker,
                    previous_status=previous_status,
                    reason="maximum attempts exhausted before claim",
                )
                _increment_metric(cursor, spec, "dead_lettered")
                connection.commit()
                return ClaimOutcome(
                    "dead_lettered", spec, job_id=UUID(str(updated["id"])), previous_status=previous_status
                )

            token = uuid4()
            reclaimed = mode == "recovery"
            next_status = "finalizing" if reclaimed and previous_status == "finalizing" else "running"
            cursor.execute(
                f"""
                UPDATE {spec.table}
                SET status = %s, locked_by = %s, locked_at = now(), heartbeat_at = now(),
                    lease_token = %s,
                    lease_expires_at = now() + (%s || ' seconds')::interval,
                    attempt_count = attempt_count + %s,
                    lease_reclaimed_count = lease_reclaimed_count + %s,
                    last_reclaimed_at = CASE WHEN %s THEN now() ELSE last_reclaimed_at END,
                    last_reclaimed_from = CASE WHEN %s THEN %s ELSE last_reclaimed_from END,
                    started_at = COALESCE(started_at, now()), completed_at = NULL,
                    updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (
                    next_status,
                    worker_id,
                    token,
                    lease_seconds,
                    0 if descriptor_only_recovery else 1,
                    1 if reclaimed else 0,
                    reclaimed,
                    reclaimed,
                    previous_worker,
                    candidate["id"],
                ),
            )
            updated = _row_dict(cursor.fetchone())
            _record_lease_audit(
                cursor,
                record=updated,
                spec=spec,
                event_type="durable_job.reclaimed" if reclaimed else "durable_job.claimed",
                worker_id=worker_id,
                token=token,
                previous_worker=previous_worker,
                previous_status=previous_status,
                reason="expired lease owner transfer" if reclaimed else "scheduled durable job claim",
                attempt_increment=0 if descriptor_only_recovery else 1,
            )
            connection.commit()
            claim = LeaseClaim(
                spec=spec,
                job_id=UUID(str(updated["id"])),
                project_id=UUID(str(updated["project_id"])),
                worker_id=worker_id,
                lease_token=token,
                lease_expires_at=updated["lease_expires_at"],
                claimed_from=previous_status,
                attempt_count=int(updated["attempt_count"]),
                reclaimed=reclaimed,
                record=MappingProxyType(updated),
            )
            return ClaimOutcome("claimed", spec, claim=claim, job_id=claim.job_id, previous_status=previous_status)
    except Exception:
        connection.rollback()
        raise


def _cas_record(
    connection: Any,
    *,
    spec: DurableJobSpec,
    sql: str,
    params: Sequence[Any],
    success_metrics: Sequence[str] = (),
    success_metrics_by_status: Mapping[str, Sequence[str]] | None = None,
    failure_metrics: Sequence[str] = ("lease_lost",),
) -> dict[str, Any]:
    from psycopg.rows import dict_row

    try:
        _begin(connection)
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql, tuple(params))
            record = _row_dict(cursor.fetchone())
            if not record:
                for metric_name in failure_metrics:
                    _increment_metric(cursor, spec, metric_name)
                connection.commit()
                raise LostLeaseError(f"lost durable lease for {spec.table}")
            for metric_name in success_metrics:
                _increment_metric(cursor, spec, metric_name)
            if success_metrics_by_status:
                for metric_name in success_metrics_by_status.get(str(record.get("status")), ()):
                    _increment_metric(cursor, spec, metric_name)
            connection.commit()
            return record
    except LostLeaseError:
        raise
    except Exception:
        connection.rollback()
        raise


def heartbeat_durable_job(connection: Any, claim: LeaseClaim, *, lease_seconds: int) -> dict[str, Any]:
    spec = _trusted_spec(claim.spec)
    return _cas_record(
        connection,
        spec=spec,
        sql=f"""
            UPDATE {spec.table}
            SET heartbeat_at = now(), lease_expires_at = now() + (%s || ' seconds')::interval,
                updated_at = now()
            WHERE id = %s AND status IN ('running', 'finalizing')
              AND locked_by = %s AND lease_token = %s AND lease_expires_at > now()
            RETURNING id, project_id, status, cancel_requested_at, lease_expires_at
        """,
        params=(max(3, int(lease_seconds)), claim.job_id, claim.worker_id, claim.lease_token),
        success_metrics=("heartbeat_success",),
        failure_metrics=("heartbeat_failure", "lease_lost"),
    )


def complete_durable_job(
    connection: Any,
    claim: LeaseClaim,
    *,
    status: str,
    result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    spec = _trusted_spec(claim.spec)
    if status not in spec.success_statuses:
        raise ValueError(f"unsupported success status for {spec.table}")
    result_sql = ""
    params: list[Any] = [status]
    if spec.result_column is not None:
        result_sql = f", {spec.result_column} = %s::jsonb"
        params.append(json.dumps(dict(result or {}), ensure_ascii=False, default=str))
    params.extend((claim.job_id, claim.worker_id, claim.lease_token))
    return _cas_record(
        connection,
        spec=spec,
        sql=f"""
            UPDATE {spec.table}
            SET status = %s{result_sql}, completed_at = now(),
                locked_by = NULL, locked_at = NULL, heartbeat_at = NULL,
                lease_expires_at = NULL, lease_token = NULL,
                last_error_code = NULL, last_error_message = NULL, updated_at = now()
            WHERE id = %s AND status IN ('running', 'finalizing')
              AND locked_by = %s AND lease_token = %s AND lease_expires_at > now()
              AND cancel_requested_at IS NULL
            RETURNING *
        """,
        params=params,
        failure_metrics=("stale_completion", "lease_lost"),
    )


def _complete_durable_job_in_current_transaction(
    connection: Any,
    claim: LeaseClaim,
    *,
    status: str,
    result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Promote a job without beginning or committing the caller's transaction."""
    spec = _trusted_spec(claim.spec)
    if status not in spec.success_statuses:
        raise ValueError(f"unsupported success status for {spec.table}")
    from psycopg.rows import dict_row

    result_sql = ""
    params: list[Any] = [status]
    if spec.result_column is not None:
        result_sql = f", {spec.result_column} = %s::jsonb"
        params.append(json.dumps(dict(result or {}), ensure_ascii=False, default=str))
    params.extend((claim.job_id, claim.worker_id, claim.lease_token))
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            UPDATE {spec.table}
            SET status = %s{result_sql}, completed_at = now(),
                locked_by = NULL, locked_at = NULL, heartbeat_at = NULL,
                lease_expires_at = NULL, lease_token = NULL,
                last_error_code = NULL, last_error_message = NULL, updated_at = now()
            WHERE id = %s AND status IN ('running', 'finalizing')
              AND locked_by = %s AND lease_token = %s AND lease_expires_at > now()
              AND cancel_requested_at IS NULL
            RETURNING *
            """,
            tuple(params),
        )
        return _row_dict(cursor.fetchone())


def fail_durable_job(
    connection: Any,
    claim: LeaseClaim,
    *,
    error_code: str,
    error_message: str,
    retryable: bool,
    retry_seconds: int = 120,
) -> dict[str, Any]:
    spec = _trusted_spec(claim.spec)
    return _cas_record(
        connection,
        spec=spec,
        sql=f"""
            UPDATE {spec.table}
            SET status = CASE
                  WHEN attempt_count >= max_attempts THEN 'dead_letter'
                  WHEN %s THEN 'retry_wait'
                  ELSE 'failed'
                END,
                {spec.schedule_column} = CASE
                  WHEN attempt_count < max_attempts AND %s
                    THEN now() + (%s || ' seconds')::interval
                  ELSE {spec.schedule_column}
                END,
                dead_lettered_at = CASE WHEN attempt_count >= max_attempts THEN now() ELSE dead_lettered_at END,
                completed_at = CASE WHEN attempt_count >= max_attempts OR NOT %s THEN now() ELSE NULL END,
                last_error_code = %s, last_error_message = %s,
                locked_by = NULL, locked_at = NULL, heartbeat_at = NULL,
                lease_expires_at = NULL, lease_token = NULL, updated_at = now()
            WHERE id = %s AND status IN ('running', 'finalizing')
              AND locked_by = %s AND lease_token = %s AND lease_expires_at > now()
              AND cancel_requested_at IS NULL
            RETURNING *
        """,
        params=(
            retryable,
            retryable,
            max(1, int(retry_seconds)),
            retryable,
            error_code[:200],
            error_message[:2000],
            claim.job_id,
            claim.worker_id,
            claim.lease_token,
        ),
        success_metrics_by_status={"dead_letter": ("dead_lettered",)},
        failure_metrics=("stale_completion", "lease_lost"),
    )


def begin_durable_finalizing(
    connection: Any, claim: LeaseClaim, *, descriptor: Mapping[str, Any]
) -> dict[str, Any]:
    spec = _trusted_spec(claim.spec)
    if not spec.supports_finalizing:
        raise ValueError(f"{spec.table} does not support artifact finalizing")
    return _cas_record(
        connection,
        spec=spec,
        sql=f"""
            UPDATE {spec.table}
            SET status = 'finalizing', finalize_descriptor = %s::jsonb, updated_at = now()
            WHERE id = %s AND status = 'running' AND locked_by = %s
              AND lease_token = %s AND lease_expires_at > now()
              AND cancel_requested_at IS NULL
            RETURNING *
        """,
        params=(
            json.dumps(dict(descriptor), ensure_ascii=False, default=str),
            claim.job_id,
            claim.worker_id,
            claim.lease_token,
        ),
        failure_metrics=("stale_completion", "lease_lost"),
    )


def expire_durable_finalizing_lease(
    connection: Any,
    claim: LeaseClaim,
    *,
    error_code: str,
    error_message: str,
) -> dict[str, Any]:
    """Stop this owner without downgrading a persisted artifact descriptor."""
    spec = _trusted_spec(claim.spec)
    if not spec.supports_finalizing:
        raise ValueError(f"{spec.table} does not support artifact finalizing")
    return _cas_record(
        connection,
        spec=spec,
        sql=f"""
            UPDATE {spec.table}
            SET lease_expires_at = now(), heartbeat_at = now(),
                last_error_code = %s, last_error_message = %s, updated_at = now()
            WHERE id = %s AND status = 'finalizing'
              AND locked_by = %s AND lease_token = %s
            RETURNING *
        """,
        params=(
            error_code[:200],
            error_message[:2000],
            claim.job_id,
            claim.worker_id,
            claim.lease_token,
        ),
        failure_metrics=(),
    )


def acknowledge_durable_cancel(connection: Any, claim: LeaseClaim) -> dict[str, Any]:
    spec = _trusted_spec(claim.spec)
    cancelled_at_sql = ", cancelled_at = now()" if spec.has_cancelled_at else ""
    cancelled = _cas_record(
        connection,
        spec=spec,
        sql=f"""
            UPDATE {spec.table}
            SET status = 'cancelled', completed_at = now(){cancelled_at_sql},
                locked_by = NULL, locked_at = NULL, heartbeat_at = NULL,
                lease_expires_at = NULL, lease_token = NULL, updated_at = now()
            WHERE id = %s AND status IN ('running', 'finalizing')
              AND locked_by = %s AND lease_token = %s AND lease_expires_at > now()
              AND cancel_requested_at IS NOT NULL
            RETURNING *
        """,
        params=(claim.job_id, claim.worker_id, claim.lease_token),
        success_metrics=("cancelled",),
    )
    return cancelled


def request_durable_cancel(
    connection: Any,
    spec: DurableJobSpec,
    *,
    project_id: UUID,
    job_id: UUID,
) -> dict[str, Any]:
    spec = _trusted_spec(spec)
    from psycopg.rows import dict_row

    try:
        _begin(connection)
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"SELECT * FROM {spec.table} WHERE id = %s AND project_id = %s FOR UPDATE",
                (job_id, project_id),
            )
            record = _row_dict(cursor.fetchone())
            if not record:
                connection.rollback()
                raise ValueError("durable job not found")
            status = str(record["status"])
            if status in {"queued", "retry_wait"}:
                cancelled_at_sql = ", cancelled_at = now()" if spec.has_cancelled_at else ""
                cursor.execute(
                    f"""
                    UPDATE {spec.table}
                    SET status = 'cancelled', cancel_requested_at = COALESCE(cancel_requested_at, now()),
                        completed_at = now(){cancelled_at_sql}, updated_at = now()
                    WHERE id = %s AND status IN ('queued', 'retry_wait')
                    RETURNING *
                    """,
                    (job_id,),
                )
            elif status in {"running", "finalizing"}:
                cursor.execute(
                    f"""
                    UPDATE {spec.table}
                    SET cancel_requested_at = COALESCE(cancel_requested_at, now()), updated_at = now()
                    WHERE id = %s AND status IN ('running', 'finalizing')
                    RETURNING *
                    """,
                    (job_id,),
                )
            else:
                connection.rollback()
                raise JobStateConflictError(f"cannot cancel terminal durable job in status {status}")
            updated = _row_dict(cursor.fetchone())
            if not updated:
                connection.rollback()
                raise JobStateConflictError("durable job state changed during cancellation")
            if str(updated.get("status")) == "cancelled":
                _increment_metric(cursor, spec, "cancelled")
            connection.commit()
            return updated
    except (ValueError, JobStateConflictError):
        raise
    except Exception:
        connection.rollback()
        raise


def next_fair_table_order(
    connection: Any,
    *,
    queue_name: Literal["knowledge_fresh", "knowledge_recovery", "collection_recovery"],
    tables: Sequence[str],
    worker_id: str,
) -> tuple[str, ...]:
    if not tables:
        return ()
    trusted_tables = tuple(durable_job_spec(table).table for table in tables)
    if len(set(trusted_tables)) != len(trusted_tables):
        raise ValueError("fair table order cannot contain duplicates")
    from psycopg.rows import dict_row

    try:
        _begin(connection)
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO durable_job_recovery_cursors (
                  queue_name, cursor_index, last_worker_id, worker_heartbeat_at
                ) VALUES (%s, 0, %s, now())
                ON CONFLICT (queue_name) DO UPDATE SET
                  cursor_index = (durable_job_recovery_cursors.cursor_index + 1) %% %s,
                  last_worker_id = EXCLUDED.last_worker_id,
                  worker_heartbeat_at = now(), updated_at = now()
                RETURNING cursor_index
                """,
                (queue_name, worker_id, len(trusted_tables)),
            )
            row = _row_dict(cursor.fetchone())
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    start = int(row["cursor_index"]) % len(trusted_tables)
    return trusted_tables[start:] + trusted_tables[:start]


def record_recovery_pass(
    connection: Any,
    *,
    queue_name: Literal["knowledge_recovery", "collection_recovery"],
    worker_id: str,
    slots_used: int,
) -> None:
    try:
        _begin(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO durable_job_recovery_cursors (
                  queue_name, cursor_index, recovery_slots_used, last_worker_id, worker_heartbeat_at
                ) VALUES (%s, 0, %s, %s, now())
                ON CONFLICT (queue_name) DO UPDATE SET
                  recovery_slots_used = EXCLUDED.recovery_slots_used,
                  last_worker_id = EXCLUDED.last_worker_id,
                  worker_heartbeat_at = now(), updated_at = now()
                """,
                (queue_name, max(0, int(slots_used)), worker_id),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def collect_durable_job_metrics(connection: Any) -> dict[str, Any]:
    """Return only aggregate, non-sensitive queue and lease metrics."""
    from psycopg.rows import dict_row

    queues: list[dict[str, Any]] = []
    try:
        _begin(connection)
        with connection.cursor(row_factory=dict_row) as cursor:
            for spec in DURABLE_JOB_SPECS.values():
                cursor.execute(
                    f"""
                    SELECT
                      count(*) FILTER (
                        WHERE status IN ('queued', 'retry_wait')
                          AND cancel_requested_at IS NULL
                      ) AS queue_depth,
                      COALESCE(EXTRACT(EPOCH FROM (now() - min(created_at) FILTER (
                        WHERE status IN ('queued', 'retry_wait')
                          AND cancel_requested_at IS NULL
                      ))), 0) AS oldest_queued_age_seconds,
                      count(*) FILTER (
                        WHERE status IN ('running', 'finalizing')
                          AND lease_expires_at IS NOT NULL AND lease_expires_at <= now()
                      ) AS expired_active_count,
                      COALESCE(EXTRACT(EPOCH FROM (now() - min(lease_expires_at) FILTER (
                        WHERE status IN ('running', 'finalizing')
                          AND lease_expires_at IS NOT NULL AND lease_expires_at <= now()
                      ))), 0) AS oldest_expired_age_seconds,
                      COALESCE(sum(lease_reclaimed_count), 0) AS reclaimed_total,
                      count(*) FILTER (WHERE status = 'dead_letter') AS dead_letter_total,
                      count(*) FILTER (WHERE status = 'cancelled') AS cancelled_total
                    FROM {spec.table}
                    """
                )
                row = _row_dict(cursor.fetchone())
                queues.append(
                    {
                        "queue": _queue_name(spec),
                        "job_type": spec.table,
                        "queue_depth": int(row.get("queue_depth") or 0),
                        "oldest_queued_age_seconds": float(row.get("oldest_queued_age_seconds") or 0),
                        "expired_active_count": int(row.get("expired_active_count") or 0),
                        "oldest_expired_age_seconds": float(row.get("oldest_expired_age_seconds") or 0),
                        "reclaimed_total": int(row.get("reclaimed_total") or 0),
                        "dead_letter_total": int(row.get("dead_letter_total") or 0),
                        "cancelled_total": int(row.get("cancelled_total") or 0),
                    }
                )
            cursor.execute(
                """
                SELECT queue_name, cursor_index, recovery_slots_used,
                       COALESCE(EXTRACT(EPOCH FROM (now() - worker_heartbeat_at)), 0)
                         AS worker_heartbeat_age_seconds
                FROM durable_job_recovery_cursors
                ORDER BY queue_name
                """
            )
            cursors = [
                {
                    "queue_name": str(row["queue_name"]),
                    "cursor_index": int(row["cursor_index"]),
                    "recovery_slots_used": int(row["recovery_slots_used"]),
                    "worker_heartbeat_age_seconds": float(row["worker_heartbeat_age_seconds"] or 0),
                }
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT queue_name, job_type, metric_name, metric_value
                FROM durable_job_metric_counters
                ORDER BY queue_name, job_type, metric_name
                """
            )
            counters = [
                {
                    "queue": str(row["queue_name"]),
                    "job_type": str(row["job_type"]),
                    "metric": str(row["metric_name"]),
                    "value": int(row["metric_value"]),
                }
                for row in cursor.fetchall()
            ]
        connection.commit()
        return {"queues": queues, "cursors": cursors, "counters": counters}
    except Exception:
        connection.rollback()
        raise


def fence_durable_transaction(
    connection: Any,
    claim: LeaseClaim,
    *,
    lease_seconds: int,
) -> dict[str, Any]:
    """Fence and renew a handler's current business transaction before commit."""
    spec = _trusted_spec(claim.spec)
    from psycopg.rows import dict_row

    try:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                UPDATE {spec.table}
                SET heartbeat_at = now(),
                    lease_expires_at = now() + (%s || ' seconds')::interval,
                    updated_at = now()
                WHERE id = %s AND status IN ('running', 'finalizing')
                  AND locked_by = %s AND lease_token = %s
                  AND lease_expires_at > now() AND cancel_requested_at IS NULL
                RETURNING id, project_id, status, lease_expires_at
                """,
                (max(3, int(lease_seconds)), claim.job_id, claim.worker_id, claim.lease_token),
            )
            record = _row_dict(cursor.fetchone())
            if not record:
                connection.rollback()
                with connection.cursor() as metric_cursor:
                    _increment_metric(metric_cursor, spec, "stale_completion")
                    _increment_metric(metric_cursor, spec, "lease_lost")
                connection.commit()
                raise LostLeaseError(f"lost durable lease before business commit for {spec.table}")
            _increment_metric(cursor, spec, "heartbeat_success")
            return record
    except LostLeaseError:
        raise
    except Exception:
        connection.rollback()
        raise


class LeaseFencedConnection:
    """Connection proxy that fences every handler-owned business commit."""

    def __init__(self, connection: Any, claim: LeaseClaim, *, lease_seconds: int) -> None:
        self._connection = connection
        self.claim = claim
        self.lease_seconds = max(3, int(lease_seconds))
        self._defer_commits = False
        self._terminal_completed = False
        self._finalizing_committed = False

    @property
    def raw_connection(self) -> Any:
        return self._connection

    def commit(self) -> None:
        if self._defer_commits:
            return
        fence_durable_transaction(
            self._connection,
            self.claim,
            lease_seconds=self.lease_seconds,
        )
        self._connection.commit()

    @property
    def commits_deferred(self) -> bool:
        return self._defer_commits

    @property
    def terminal_completed(self) -> bool:
        return self._terminal_completed

    @property
    def finalizing_committed(self) -> bool:
        return self._finalizing_committed

    def defer_commits_until_terminal(self) -> None:
        """Keep subsequent DB-only result writes in the terminal CAS transaction."""
        if self._terminal_completed:
            raise RuntimeError("cannot defer commits after terminal completion")
        self._defer_commits = True

    def complete(
        self,
        *,
        status: str,
        result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._defer_commits:
            raise RuntimeError("terminal completion requires deferred commits")
        if self._terminal_completed:
            raise RuntimeError("durable job transaction is already complete")
        spec = _trusted_spec(self.claim.spec)
        try:
            record = _complete_durable_job_in_current_transaction(
                self._connection,
                self.claim,
                status=status,
                result=result,
            )
            if not record:
                self._connection.rollback()
                with self._connection.cursor() as cursor:
                    _increment_metric(cursor, spec, "stale_completion")
                    _increment_metric(cursor, spec, "lease_lost")
                self._connection.commit()
                raise LostLeaseError(
                    f"lost durable lease before atomic business completion for {spec.table}"
                )
            self._connection.commit()
            self._terminal_completed = True
            return record
        except LostLeaseError:
            raise
        except Exception:
            self._connection.rollback()
            raise

    def begin_finalizing(self, *, descriptor: Mapping[str, Any]) -> dict[str, Any]:
        if not self._defer_commits:
            raise RuntimeError("artifact finalizing requires deferred result commits")
        if self._terminal_completed or self._finalizing_committed:
            raise RuntimeError("durable artifact transaction is already promoted")
        spec = _trusted_spec(self.claim.spec)
        if not spec.supports_finalizing:
            raise ValueError(f"{spec.table} does not support artifact finalizing")
        from psycopg.rows import dict_row

        try:
            with self._connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    f"""
                    UPDATE {spec.table}
                    SET status = 'finalizing', finalize_descriptor = %s::jsonb, updated_at = now()
                    WHERE id = %s AND status = 'running' AND locked_by = %s
                      AND lease_token = %s AND lease_expires_at > now()
                      AND cancel_requested_at IS NULL
                    RETURNING *
                    """,
                    (
                        json.dumps(dict(descriptor), ensure_ascii=False, default=str),
                        self.claim.job_id,
                        self.claim.worker_id,
                        self.claim.lease_token,
                    ),
                )
                record = _row_dict(cursor.fetchone())
            if not record:
                self._connection.rollback()
                with self._connection.cursor() as cursor:
                    _increment_metric(cursor, spec, "stale_completion")
                    _increment_metric(cursor, spec, "lease_lost")
                self._connection.commit()
                raise LostLeaseError(
                    f"lost durable lease before artifact finalizing for {spec.table}"
                )
            self._connection.commit()
            self._finalizing_committed = True
            return record
        except LostLeaseError:
            raise
        except Exception:
            self._connection.rollback()
            raise

    def rollback(self) -> None:
        self._connection.rollback()

    def cursor(self, *args: Any, **kwargs: Any) -> Any:
        return self._connection.cursor(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


_INTERNAL_LEASE_ENVIRONMENT_KEYS = (
    "GEO_INTERNAL_DURABLE_JOB_TABLE",
    "GEO_INTERNAL_DURABLE_JOB_ID",
    "GEO_INTERNAL_DURABLE_PROJECT_ID",
    "GEO_INTERNAL_DURABLE_WORKER_ID",
    "GEO_INTERNAL_DURABLE_LEASE_TOKEN",
    "GEO_INTERNAL_DURABLE_ATTEMPT_COUNT",
    "GEO_INTERNAL_DURABLE_LEASE_SECONDS",
)


def internal_lease_environment(claim: LeaseClaim, *, lease_seconds: int) -> dict[str, str]:
    """Build child-only environment values; callers must not log this mapping."""
    return {
        "GEO_INTERNAL_DURABLE_JOB_TABLE": claim.spec.table,
        "GEO_INTERNAL_DURABLE_JOB_ID": str(claim.job_id),
        "GEO_INTERNAL_DURABLE_PROJECT_ID": str(claim.project_id),
        "GEO_INTERNAL_DURABLE_WORKER_ID": claim.worker_id,
        "GEO_INTERNAL_DURABLE_LEASE_TOKEN": str(claim.lease_token),
        "GEO_INTERNAL_DURABLE_ATTEMPT_COUNT": str(claim.attempt_count),
        "GEO_INTERNAL_DURABLE_LEASE_SECONDS": str(max(3, int(lease_seconds))),
    }


def lease_claim_from_internal_environment(
    environment: Mapping[str, str] | None = None,
) -> tuple[LeaseClaim, int] | None:
    env = os.environ if environment is None else environment
    try:
        table = env.get("GEO_INTERNAL_DURABLE_JOB_TABLE", "").strip()
        if not table:
            return None
        required = {
            "job_id": env.get("GEO_INTERNAL_DURABLE_JOB_ID", "").strip(),
            "project_id": env.get("GEO_INTERNAL_DURABLE_PROJECT_ID", "").strip(),
            "worker_id": env.get("GEO_INTERNAL_DURABLE_WORKER_ID", "").strip(),
            "lease_token": env.get("GEO_INTERNAL_DURABLE_LEASE_TOKEN", "").strip(),
            "attempt_count": env.get("GEO_INTERNAL_DURABLE_ATTEMPT_COUNT", "").strip(),
            "lease_seconds": env.get("GEO_INTERNAL_DURABLE_LEASE_SECONDS", "").strip(),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"incomplete internal durable lease environment: {', '.join(missing)}")
        spec = durable_job_spec(table)
        claim = LeaseClaim(
            spec=spec,
            job_id=UUID(required["job_id"]),
            project_id=UUID(required["project_id"]),
            worker_id=required["worker_id"],
            lease_token=UUID(required["lease_token"]),
            lease_expires_at=datetime.now(UTC),
            claimed_from="internal_child",
            attempt_count=int(required["attempt_count"]),
            reclaimed=False,
            record=MappingProxyType({}),
        )
        return claim, max(3, int(required["lease_seconds"]))
    finally:
        if environment is None:
            for key in _INTERNAL_LEASE_ENVIRONMENT_KEYS:
                os.environ.pop(key, None)


class LeaseGuard:
    """Heartbeat a LeaseClaim over an independent, maintenance-scoped DB connection."""

    def __init__(
        self,
        claim: LeaseClaim,
        *,
        lease_seconds: int,
        connection_factory: Callable[[], Any],
        scope_initializer: Callable[[Any, str], None] | None = None,
        heartbeat_interval_seconds: float | None = None,
    ) -> None:
        self.claim = claim
        self.lease_seconds = max(3, int(lease_seconds))
        maximum_interval = self.lease_seconds / 3.0
        requested = heartbeat_interval_seconds if heartbeat_interval_seconds is not None else maximum_interval
        self.heartbeat_interval_seconds = max(0.1, min(float(requested), maximum_interval))
        self._connection_factory = connection_factory
        self._scope_initializer = scope_initializer
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._cancel_requested = threading.Event()
        self._failure: BaseException | None = None
        self._thread: threading.Thread | None = None

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested.is_set()

    def start(self) -> LeaseGuard:
        if self._thread is not None:
            return self
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"lease-guard-{self.claim.spec.table}",
            daemon=True,
        )
        self._thread.start()
        return self

    def _heartbeat_loop(self) -> None:
        connection = None
        try:
            connection = self._connection_factory()
            if self._scope_initializer is not None:
                self._scope_initializer(connection, self.claim.worker_id)
            while not self._stop.wait(self.heartbeat_interval_seconds):
                heartbeat = heartbeat_durable_job(
                    connection, self.claim, lease_seconds=self.lease_seconds
                )
                if heartbeat.get("cancel_requested_at") is not None:
                    self._cancel_requested.set()
                    self._failure = LostLeaseError(
                        f"cancellation requested for {self.claim.spec.table}", cancel_requested=True
                    )
                    return
        except BaseException as exc:  # fail closed on connection errors and stale CAS.
            self._failure = exc
            self._lost.set()
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def raise_if_stopped(self) -> None:
        if self._cancel_requested.is_set():
            raise LostLeaseError(
                f"cancellation requested for {self.claim.spec.table}", cancel_requested=True
            )
        if self._lost.is_set():
            if isinstance(self._failure, LostLeaseError):
                raise self._failure
            raise LostLeaseError(f"heartbeat failed for {self.claim.spec.table}") from self._failure

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.heartbeat_interval_seconds * 2))

    def __enter__(self) -> LeaseGuard:
        return self.start()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()
