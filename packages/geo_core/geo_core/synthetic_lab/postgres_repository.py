"""Project-scoped psycopg repositories for Synthetic Lab state."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.ports import (
    AuthorizationEnvelope,
    JobTerminalResult,
    SyntheticCommandRecord,
    SyntheticJob,
    SyntheticLabIdempotencyConflict,
    SyntheticLabPersistenceError,
    SyntheticLabVersionConflict,
    SyntheticOutboxMessage,
    VersionedAggregate,
)
from geo_core.synthetic_lab.postgres_codec import encode_object
from geo_core.synthetic_lab.postgres_rows import (
    DOMAIN_TO_DURABLE_KIND,
    DURABLE_TO_DOMAIN_KIND,
    aggregate_from_row,
    authorization_from_row,
    command_from_row,
    job_from_row,
    job_payload_to_json,
)


_JOB_SELECT = """
SELECT metadata.*, durable.kind AS durable_kind, durable.status,
       durable.priority, durable.input_hash, durable.idempotency_key,
       durable.attempt_count, durable.max_attempts, durable.next_run_at,
       durable.lease_owner, durable.lease_token, durable.lease_expires_at,
       durable.heartbeat_at, durable.fencing_generation,
       durable.cancel_requested_at, durable.parent_job_id, durable.replay_nonce,
       durable.result_ref, durable.error_code
FROM synthetic_lab_job_metadata AS metadata
JOIN durable_jobs AS durable
  ON durable.id = metadata.job_id AND durable.project_id = metadata.project_id
"""


class PostgresSyntheticCommandRepository:
    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection, self._project_id = connection, project_id

    def get(
        self, *, project_id: UUID, idempotency_key_hash: str
    ) -> SyntheticCommandRecord | None:
        _require_scope(self._project_id, project_id)
        row = _one(
            self._connection.execute(
                """SELECT * FROM synthetic_lab_command_receipts
                   WHERE project_id = %s AND idempotency_key_hash = %s""",
                (project_id, idempotency_key_hash),
            )
        )
        return command_from_row(row) if row is not None else None

    def stage(self, record: SyntheticCommandRecord) -> None:
        identity = record.identity
        _require_scope(self._project_id, identity.project_id)
        existing = self.get(
            project_id=identity.project_id,
            idempotency_key_hash=identity.idempotency_key_hash,
        )
        if existing is not None:
            if existing != record:
                raise SyntheticLabIdempotencyConflict(
                    "Idempotency-Key was reused with different frozen content"
                )
            return
        result_type, payload, result_hash = encode_object(record.result)
        try:
            self._connection.execute(
                """INSERT INTO synthetic_lab_command_receipts(
                       project_id, idempotency_key_hash, operation, request_hash,
                       result_type, result_payload, result_payload_hash
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    identity.project_id,
                    identity.idempotency_key_hash,
                    identity.operation.value,
                    identity.request_hash,
                    result_type,
                    Jsonb(payload),
                    result_hash,
                ),
            )
        except psycopg.Error as error:
            raise _database_error(error, idempotency=True) from None


class PostgresSyntheticAggregateRepository:
    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection, self._project_id = connection, project_id

    def get(
        self, *, project_id: UUID, kind: str, resource_id: UUID
    ) -> VersionedAggregate | None:
        _require_scope(self._project_id, project_id)
        row = _one(
            self._connection.execute(
                """SELECT * FROM synthetic_lab_aggregate_versions
                   WHERE project_id = %s AND kind = %s AND resource_id = %s
                   ORDER BY version DESC LIMIT 1""",
                (project_id, kind, resource_id),
            )
        )
        return aggregate_from_row(row) if row is not None else None

    def stage(self, aggregate: VersionedAggregate, *, expected_version: int) -> None:
        _require_scope(self._project_id, aggregate.project_id)
        current = self.get(
            project_id=aggregate.project_id,
            kind=aggregate.kind,
            resource_id=aggregate.resource_id,
        )
        current_version = current.version if current is not None else 0
        if current_version != expected_version or aggregate.version != expected_version + 1:
            raise SyntheticLabVersionConflict("Synthetic Lab aggregate CAS failed")
        payload_type, payload, content_hash = encode_object(aggregate.payload)
        try:
            self._connection.execute(
                """INSERT INTO synthetic_lab_aggregate_versions(
                       project_id, kind, resource_id, version, submitted_by,
                       payload_type, payload, payload_hash
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    aggregate.project_id,
                    aggregate.kind,
                    aggregate.resource_id,
                    aggregate.version,
                    aggregate.submitted_by,
                    payload_type,
                    Jsonb(payload),
                    content_hash,
                ),
            )
        except psycopg.Error as error:
            raise _database_error(error) from None


class PostgresSyntheticAuthorizationRepository:
    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection, self._project_id = connection, project_id

    def current(
        self, *, project_id: UUID, channel: str, adapter_release: str
    ) -> AuthorizationEnvelope | None:
        _require_scope(self._project_id, project_id)
        row = _one(
            self._connection.execute(
                """SELECT * FROM synthetic_lab_authorization_versions
                   WHERE project_id = %s AND channel = %s AND adapter_release = %s
                   ORDER BY version_number DESC LIMIT 1""",
                (project_id, channel, adapter_release),
            )
        )
        return authorization_from_row(row) if row is not None else None

    def stage(self, envelope: AuthorizationEnvelope, *, expected_version: int) -> None:
        record = envelope.record
        _require_scope(self._project_id, record.project_id)
        current = self.current(
            project_id=record.project_id,
            channel=record.channel,
            adapter_release=record.adapter_release,
        )
        current_version = current.record.version_number if current is not None else 0
        if current_version != expected_version or record.version_number != expected_version + 1:
            raise SyntheticLabVersionConflict("collection authorization CAS failed")
        try:
            self._connection.execute(
                """INSERT INTO synthetic_lab_authorization_versions(
                       id, project_id, channel, adapter_release, version_number,
                       previous_version_id, state, evidence_reference_hash,
                       decided_by, decided_at, allowed_purposes,
                       max_requests_per_period, period_seconds, max_concurrency,
                       expires_at, decision_reason, record_hash, submitted_by
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s
                   )""",
                (
                    record.id,
                    record.project_id,
                    record.channel,
                    record.adapter_release,
                    record.version_number,
                    record.previous_version_id,
                    record.state.value,
                    record.evidence_reference_hash,
                    record.decided_by,
                    record.decided_at,
                    list(record.allowed_purposes),
                    record.max_requests_per_period,
                    record.period_seconds,
                    record.max_concurrency,
                    record.expires_at,
                    record.decision_reason,
                    record.record_hash,
                    envelope.submitted_by,
                ),
            )
        except psycopg.Error as error:
            raise _database_error(error) from None


class PostgresSyntheticJobRepository:
    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection, self._project_id = connection, project_id

    def get(self, *, project_id: UUID, job_id: UUID) -> SyntheticJob | None:
        _require_scope(self._project_id, project_id)
        row = _one(
            self._connection.execute(
                _JOB_SELECT + " WHERE metadata.project_id = %s AND metadata.job_id = %s",
                (project_id, job_id),
            )
        )
        return job_from_row(row) if row is not None else None

    def stage(self, job: SyntheticJob, *, expected_version: int) -> None:
        _require_scope(self._project_id, job.project_id)
        current = self.get(project_id=job.project_id, job_id=job.id)
        current_version = current.version if current is not None else 0
        if current_version != expected_version or job.version != expected_version + 1:
            raise SyntheticLabVersionConflict("Durable Synthetic Lab Job CAS failed")
        try:
            if expected_version == 0:
                self._insert_job(job)
            else:
                self._update_job(job, expected_version=expected_version)
        except psycopg.Error as error:
            raise _database_error(error) from None

    def stage_terminal(self, result: JobTerminalResult) -> None:
        _require_scope(self._project_id, result.project_id)
        job = self.get(project_id=result.project_id, job_id=result.job_id)
        if job is None or job.lease_id is None:
            raise SyntheticLabVersionConflict("Synthetic Lab terminal Job ownership is unavailable")
        result_type, payload, _ = encode_object(result)
        runtime = job.runtime_inputs
        try:
            self._connection.execute(
                """INSERT INTO synthetic_lab_terminal_results(
                       project_id, job_id, job_kind, result_type, result_payload,
                       result_hash, lease_token, fencing_generation,
                       fact_snapshot_id, fact_snapshot_hash, profile_version_id,
                       profile_hash, prompt_release_id, prompt_release_hash
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s
                   )""",
                (
                    result.project_id,
                    result.job_id,
                    result.job_kind,
                    result_type,
                    Jsonb(payload),
                    result.result_hash,
                    job.lease_id,
                    job.fencing_token,
                    runtime.fact_snapshot_id if runtime else None,
                    runtime.fact_snapshot_hash if runtime else None,
                    runtime.profile_version_id if runtime else None,
                    runtime.profile_hash if runtime else None,
                    runtime.prompt_release_id if runtime else None,
                    runtime.prompt_release_hash if runtime else None,
                ),
            )
        except psycopg.Error as error:
            raise _database_error(error) from None

    def _insert_job(self, job: SyntheticJob) -> None:
        domain_kind = DURABLE_TO_DOMAIN_KIND.get(job.kind, job.kind)
        durable_kind = DOMAIN_TO_DURABLE_KIND.get(domain_kind)
        if durable_kind is None:
            raise SyntheticLabPersistenceError("unsupported Synthetic Lab Job kind")
        durable = job.durable
        self._connection.execute(
            """INSERT INTO durable_jobs(
                   id, project_id, kind, status, priority, input_hash, idempotency_key,
                   attempt_count, max_attempts, next_run_at, lease_owner, lease_token,
                   lease_expires_at, heartbeat_at, fencing_generation,
                   cancel_requested_at, parent_job_id, replay_nonce, result_ref, error_code
               ) VALUES (
                   %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   coalesce(%s, clock_timestamp()), %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s
               )""",
            (
                durable.id,
                durable.project_id,
                durable_kind,
                durable.status.value,
                durable.priority,
                durable.input_hash,
                durable.idempotency_key,
                durable.attempt_count,
                durable.max_attempts,
                durable.next_run_at,
                durable.lease_owner,
                durable.lease_token,
                durable.lease_expires_at,
                durable.heartbeat_at,
                durable.fencing_generation,
                durable.cancel_requested_at,
                durable.parent_job_id,
                durable.replay_nonce,
                durable.result_ref,
                durable.error_code,
            ),
        )
        self._insert_metadata(job, domain_kind=domain_kind)

    def _insert_metadata(self, job: SyntheticJob, *, domain_kind: str) -> None:
        payload = job_payload_to_json(job.payload)
        runtime, authorization = job.runtime_inputs, job.authorization_binding
        self._connection.execute(
            """INSERT INTO synthetic_lab_job_metadata(
                   job_id, project_id, metadata_version, domain_job_kind,
                   payload, payload_hash,
                   fact_snapshot_id, fact_snapshot_hash, profile_version_id,
                   profile_hash, prompt_release_id, prompt_release_hash,
                   facts_current_approved, profile_frozen, prompt_frozen,
                   authorization_id, authorization_channel,
                   authorization_adapter_release, authorization_version,
                   authorization_hash, authorization_purpose, authorization_expires_at
               ) VALUES (
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
               )""",
            (
                job.id,
                job.project_id,
                job.version,
                domain_kind,
                Jsonb(payload),
                canonical_hash(job.payload),
                runtime.fact_snapshot_id if runtime else None,
                runtime.fact_snapshot_hash if runtime else None,
                runtime.profile_version_id if runtime else None,
                runtime.profile_hash if runtime else None,
                runtime.prompt_release_id if runtime else None,
                runtime.prompt_release_hash if runtime else None,
                runtime.facts_current_approved if runtime else None,
                runtime.profile_frozen if runtime else None,
                runtime.prompt_frozen if runtime else None,
                authorization.authorization_id if authorization else None,
                authorization.channel if authorization else None,
                authorization.adapter_release if authorization else None,
                authorization.version_number if authorization else None,
                authorization.authorization_hash if authorization else None,
                authorization.purpose if authorization else None,
                authorization.expires_at if authorization else None,
            ),
        )

    def _update_job(self, job: SyntheticJob, *, expected_version: int) -> None:
        durable = job.durable
        changed = self._connection.execute(
            """UPDATE durable_jobs SET
                   status = %s, priority = %s, attempt_count = %s, max_attempts = %s,
                   next_run_at = coalesce(%s, next_run_at), lease_owner = %s,
                   lease_token = %s, lease_expires_at = %s, heartbeat_at = %s,
                   fencing_generation = %s, cancel_requested_at = %s,
                   result_ref = %s, error_code = %s, updated_at = clock_timestamp(),
                   completed_at = CASE WHEN %s IN (
                       'succeeded','failed','dead_lettered','cancelled'
                   ) THEN coalesce(completed_at, clock_timestamp()) ELSE completed_at END
               WHERE id = %s AND project_id = %s
                 AND EXISTS (
                     SELECT 1 FROM synthetic_lab_job_metadata metadata
                     WHERE metadata.job_id = %s AND metadata.project_id = %s
                       AND metadata.metadata_version = %s
                 )""",
            (
                durable.status.value,
                durable.priority,
                durable.attempt_count,
                durable.max_attempts,
                durable.next_run_at,
                durable.lease_owner,
                durable.lease_token,
                durable.lease_expires_at,
                durable.heartbeat_at,
                durable.fencing_generation,
                durable.cancel_requested_at,
                durable.result_ref,
                durable.error_code,
                durable.status.value,
                durable.id,
                durable.project_id,
                durable.id,
                durable.project_id,
                expected_version,
            ),
        ).rowcount
        if changed != 1:
            raise SyntheticLabVersionConflict("Durable Synthetic Lab Job CAS failed")
        changed = self._connection.execute(
            """UPDATE synthetic_lab_job_metadata
               SET metadata_version = %s, updated_at = clock_timestamp()
               WHERE project_id = %s AND job_id = %s AND metadata_version = %s""",
            (job.version, job.project_id, job.id, expected_version),
        ).rowcount
        if changed != 1:
            raise SyntheticLabVersionConflict("Synthetic Lab Job metadata CAS failed")


class PostgresSyntheticOutboxRepository:
    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection, self._project_id = connection, project_id

    def stage(self, message: SyntheticOutboxMessage) -> None:
        _require_scope(self._project_id, message.project_id)
        payload = {
            "project_id": str(message.project_id),
            "job_id": str(message.job_id),
            "event_type": message.event_type,
            "payload_hash": message.payload_hash,
        }
        try:
            self._connection.execute(
                """INSERT INTO broker_outbox(
                       id, project_id, job_id, topic, payload, idempotency_key
                   ) VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    message.id,
                    message.project_id,
                    message.job_id,
                    message.event_type,
                    Jsonb(payload),
                    f"synthetic:{message.id}",
                ),
            )
            self._connection.execute(
                """INSERT INTO synthetic_lab_outbox_messages(
                       id, project_id, job_id, event_type, payload_hash
                   ) VALUES (%s, %s, %s, %s, %s)""",
                (
                    message.id,
                    message.project_id,
                    message.job_id,
                    message.event_type,
                    message.payload_hash,
                ),
            )
        except psycopg.Error as error:
            raise _database_error(error) from None


def _one(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    return dict(row) if row is not None else None


def _require_scope(expected: UUID, actual: UUID) -> None:
    if expected != actual:
        raise SyntheticLabPersistenceError("Synthetic Lab UoW Project scope mismatch")


def _database_error(
    error: psycopg.Error, *, idempotency: bool = False
) -> SyntheticLabPersistenceError:
    if idempotency and error.sqlstate == "23505":
        return SyntheticLabIdempotencyConflict("Synthetic Lab idempotency race lost")
    if error.sqlstate in {"23505", "40001"}:
        return SyntheticLabVersionConflict("Synthetic Lab persistence CAS failed")
    return SyntheticLabPersistenceError("PostgreSQL rejected Synthetic Lab persistence")


__all__ = [
    "PostgresSyntheticAggregateRepository",
    "PostgresSyntheticAuthorizationRepository",
    "PostgresSyntheticCommandRepository",
    "PostgresSyntheticJobRepository",
    "PostgresSyntheticOutboxRepository",
]
