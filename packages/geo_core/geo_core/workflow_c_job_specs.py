"""Immutable, Project-scoped command specifications for Workflow C Workers.

Durable Job messages are wakeups only.  A Workflow C Worker must reconstruct
its input from the database after every retry, and must never accept provider
credentials or other secret material in that input. The SQL schema and atomic
producer entry point are added by the linear ``0032`` and ``0034`` migrations.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
from types import MappingProxyType
from typing import Any
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.project_scope import set_project_scope
from geo_core.secrets import SecretSerializationRejected, reject_secret_bearing_payload


_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "client_secret",
        "cookie",
        "cookies",
        "secret",
        "secret_value",
        "credential",
        "credential_value",
        "id_token",
        "password",
        "passwd",
        "proxy",
        "proxy_credentials",
        "token",
        "proxy_password",
        "proxy_url",
        "refresh_token",
        "session",
        "session_token",
        "storage_state",
    }
)

WORKFLOW_C_JOB_KINDS = frozenset(
    {
        "sampling.provider_execute",
        "sampling.manual_import",
        "workflow_c.analysis.semantic_metrics",
        "workflow_c.metric_judge",
        "workflow_c.metric_arbiter",
        "workflow_c.analysis.comparison",
        "workflow_c.analysis.drift",
        "workflow_c.alert.schedule",
        "workflow_c.alert.evaluate",
        "workflow_c.alert.notify",
    }
)


class WorkflowCJobSpecError(RuntimeError):
    """The immutable Worker command is absent, stale, or unsafe to execute."""


@dataclass(frozen=True)
class WorkflowCJobSpec:
    project_id: UUID
    job_id: UUID
    kind: str
    spec_hash: str
    payload: Mapping[str, object]
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise WorkflowCJobSpecError("Workflow C Job spec kind is required")
        _validate_payload(self.payload, expected_kind=self.kind)
        if _canonical_hash(self.payload) != self.spec_hash:
            raise WorkflowCJobSpecError("Workflow C Job spec hash does not match payload")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise WorkflowCJobSpecError("Workflow C Job spec timestamp must be timezone-aware")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class WorkflowCEnqueuedJob:
    """One idempotent Job/spec/outbox commit made by the Workflow C producer."""

    project_id: UUID
    job_id: UUID
    kind: str
    spec_hash: str
    replayed: bool


class PostgresWorkflowCJobSpecRepository:
    """Load exactly one frozen spec after the generic Worker has acquired a lease."""

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def load(self, lease: WorkerLease) -> WorkflowCJobSpec:
        connection = self._connect()
        try:
            set_project_scope(connection, lease.project_id)
            row = connection.execute(
                """SELECT spec.project_id, spec.job_id, spec.kind, spec.spec_hash,
                          spec.spec_payload, spec.created_at, durable.input_hash,
                          durable.kind AS durable_kind, durable.status,
                          durable.lease_token, durable.fencing_generation,
                          durable.lease_expires_at
                   FROM workflow_c_job_specs AS spec
                   JOIN durable_jobs AS durable
                     ON durable.project_id = spec.project_id
                    AND durable.id = spec.job_id
                  WHERE spec.project_id = %s AND spec.job_id = %s""",
                (lease.project_id, lease.job_id),
            ).fetchone()
            connection.rollback()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        if row is None:
            raise WorkflowCJobSpecError("Workflow C Job spec does not exist")
        values = dict(row) if isinstance(row, Mapping) else _positional_row(row)
        _validate_lease_binding(values, lease)
        payload = values["spec_payload"]
        if not isinstance(payload, Mapping):
            raise WorkflowCJobSpecError("Workflow C Job spec payload must be an object")
        project_id = values["project_id"]
        job_id = values["job_id"]
        kind = values["kind"]
        spec_hash = values["spec_hash"]
        created_at = values["created_at"]
        if (
            not isinstance(project_id, UUID)
            or not isinstance(job_id, UUID)
            or not isinstance(kind, str)
            or not isinstance(spec_hash, str)
            or not isinstance(created_at, datetime)
        ):
            raise WorkflowCJobSpecError("Workflow C Job spec row has invalid types")
        return WorkflowCJobSpec(
            project_id=project_id,
            job_id=job_id,
            kind=kind,
            spec_hash=spec_hash,
            payload=payload,
            created_at=created_at,
        )


class PostgresWorkflowCJobSpecWriter:
    """Atomically write a frozen Workflow C Job, its spec, and its wakeup.

    ``broker_outbox`` is intentionally part of this same transaction.  A
    broker outage can delay processing, but it cannot create a queued Job that
    has no recoverable immutable command, or a command that has no Job.
    """

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def enqueue(
        self,
        *,
        project_id: UUID,
        kind: str,
        payload: Mapping[str, object],
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> WorkflowCEnqueuedJob:
        normalized_kind = kind.strip()
        normalized_key = idempotency_key.strip()
        if not normalized_kind or not normalized_key or max_attempts < 1:
            raise WorkflowCJobSpecError("Workflow C Job enqueue input is invalid")
        _validate_payload(payload, expected_kind=normalized_kind)
        spec_hash = _canonical_hash(payload)
        _validate_analysis_payload(
            payload,
            expected_kind=normalized_kind,
            spec_hash=spec_hash,
        )
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT job_id, input_hash, replayed
                   FROM geo_enqueue_workflow_c_job_spec(
                       %s, %s, %s, %s::jsonb, %s, %s
                   )""",
                (
                    project_id,
                    normalized_kind,
                    spec_hash,
                    json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False),
                    normalized_key,
                    max_attempts,
                ),
            ).fetchone()
            if row is None:
                raise WorkflowCJobSpecError("Workflow C Durable Job was not persisted")
            values = dict(row) if isinstance(row, Mapping) else _enqueued_row(row)
            job_id = values.get("job_id")
            input_hash = values.get("input_hash")
            replayed = values.get("replayed")
            if (
                not isinstance(job_id, UUID)
                or not isinstance(input_hash, str)
                or not isinstance(replayed, bool)
            ):
                raise WorkflowCJobSpecError("Workflow C Durable Job row has invalid types")
            if not hmac.compare_digest(input_hash, spec_hash):
                raise WorkflowCJobSpecError(
                    "Workflow C idempotency key was reused with different input"
                )
            connection.commit()
            return WorkflowCEnqueuedJob(
                project_id=project_id,
                job_id=job_id,
                kind=normalized_kind,
                spec_hash=spec_hash,
                replayed=replayed,
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _enqueued_row(row: object) -> Mapping[str, object]:
    if not isinstance(row, tuple) or len(row) != 3:
        raise WorkflowCJobSpecError("Workflow C Durable Job row shape is invalid")
    return {"job_id": row[0], "input_hash": row[1], "replayed": row[2]}


def _validate_lease_binding(values: Mapping[str, object], lease: WorkerLease) -> None:
    if (
        values.get("project_id") != lease.project_id
        or values.get("job_id") != lease.job_id
        or values.get("kind") != lease.kind
        or values.get("durable_kind") != lease.kind
        or values.get("status") not in {"running", "finalizing"}
        or values.get("lease_token") != lease.lease_token
        or values.get("fencing_generation") != lease.fencing_generation
        or values.get("lease_expires_at") is None
    ):
        raise WorkflowCJobSpecError("Workflow C Job spec no longer belongs to this lease")
    spec_hash = values.get("spec_hash")
    durable_hash = values.get("input_hash")
    if not isinstance(spec_hash, str) or not isinstance(durable_hash, str):
        raise WorkflowCJobSpecError("Workflow C Job spec hash is unavailable")
    if lease.kind in {"workflow_c.metric_judge", "workflow_c.metric_arbiter"}:
        _validate_metric_child_task_binding(values, durable_hash)
        return
    if not hmac.compare_digest(spec_hash, durable_hash):
        raise WorkflowCJobSpecError("Workflow C Job spec differs from Durable Job input")


def _validate_metric_child_task_binding(values: Mapping[str, object], durable_hash: str) -> None:
    """Bind a metric child Job to its encrypted task, not its public reference.

    The immutable spec is deliberately a small, secret-free child reference;
    the actual executable input is the separately encrypted task envelope.
    Parent admission therefore uses the envelope's canonical hash as the
    Durable Job identity.  Normal Workflow C Jobs continue to require the
    public spec hash and Durable input hash to be identical.
    """

    payload = values.get("spec_payload")
    if not isinstance(payload, Mapping):
        raise WorkflowCJobSpecError("metric child Job spec payload is unavailable")
    child = payload.get("metric_model_child")
    if not isinstance(child, Mapping):
        raise WorkflowCJobSpecError("metric child Job spec is malformed")
    task_hash = child.get("task_hash")
    if not isinstance(task_hash, str) or not hmac.compare_digest(task_hash, durable_hash):
        raise WorkflowCJobSpecError("metric child Job task differs from Durable input")


def _validate_payload(payload: Mapping[str, object], *, expected_kind: str) -> None:
    if expected_kind not in WORKFLOW_C_JOB_KINDS:
        raise WorkflowCJobSpecError("Workflow C Job spec kind is unsupported")
    if payload.get("schema_version") != 1:
        raise WorkflowCJobSpecError("Workflow C Job spec schema_version must be 1")
    if payload.get("kind") != expected_kind:
        raise WorkflowCJobSpecError("Workflow C Job spec payload kind differs from Job kind")
    try:
        reject_secret_bearing_payload(payload)
    except SecretSerializationRejected as error:
        raise WorkflowCJobSpecError(
            "Workflow C Job spec cannot contain secret or credential material"
        ) from error
    _reject_sensitive_fields(payload)


def _validate_analysis_payload(
    payload: Mapping[str, object],
    *,
    expected_kind: str,
    spec_hash: str,
) -> None:
    """Reconstruct generic analytical inputs before they become durable work.

    PostgreSQL verifies the shape of these two public, secret-free commands.
    The full statistical relationships (frozen strata, pair uniqueness and
    method bounds) deliberately remain in the shared Python contracts so the
    producer and Worker reject precisely the same malformed inputs.
    """

    if expected_kind not in {
        "workflow_c.analysis.comparison",
        "workflow_c.analysis.drift",
    }:
        return
    from geo_core.workflow_c_statistical_specs import comparison_inputs, drift_inputs

    spec = WorkflowCJobSpec(
        project_id=UUID(int=0),
        job_id=UUID(int=0),
        kind=expected_kind,
        spec_hash=spec_hash,
        payload=payload,
        created_at=datetime.now(UTC),
    )
    if expected_kind == "workflow_c.analysis.comparison":
        comparison_inputs(spec)
    else:
        drift_inputs(spec)


def _reject_sensitive_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise WorkflowCJobSpecError("Workflow C Job spec keys must be strings")
            if _normalized_field_name(key) in _SENSITIVE_FIELD_NAMES:
                raise WorkflowCJobSpecError(
                    "Workflow C Job spec cannot contain secret or credential material"
                )
            _reject_sensitive_fields(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            _reject_sensitive_fields(child)


def _normalized_field_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _canonical_hash(value: Mapping[str, object]) -> str:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as error:
        raise WorkflowCJobSpecError("Workflow C Job spec payload is not canonical JSON") from error
    return hashlib.sha256(encoded).hexdigest()


def _positional_row(row: object) -> Mapping[str, object]:
    if not isinstance(row, tuple) or len(row) != 12:
        raise WorkflowCJobSpecError("Workflow C Job spec row shape is invalid")
    names = (
        "project_id",
        "job_id",
        "kind",
        "spec_hash",
        "spec_payload",
        "created_at",
        "input_hash",
        "durable_kind",
        "status",
        "lease_token",
        "fencing_generation",
        "lease_expires_at",
    )
    return dict(zip(names, row, strict=True))


__all__ = [
    "PostgresWorkflowCJobSpecWriter",
    "PostgresWorkflowCJobSpecRepository",
    "WORKFLOW_C_JOB_KINDS",
    "WorkflowCEnqueuedJob",
    "WorkflowCJobSpec",
    "WorkflowCJobSpecError",
]
