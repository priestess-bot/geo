"""Integrity-checked PostgreSQL read models for durable Sampling Runs.

The Internal API must render the persisted denominator and evidence rather than
reconstructing them from an enqueue request.  This repository intentionally
uses only the public Sampling aggregates and durable-job state; immutable Job
specs remain worker-only and are not exposed through this read path.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

import psycopg

from geo_core.jobs import DomainJobSpec, DurableJob, JobStatus
from geo_core.project_scope import set_project_scope
from geo_core.sampling.contracts import (
    EvidenceStatus,
    LocationControl,
    SamplingConflict,
    SamplingNotFound,
    SamplingSourceStratum,
)
from geo_core.sampling.execution import (
    AttemptTerminalStatus,
    ObservationArtifactKind,
    ObservationArtifactManifest,
    ObservationEvidence,
    SamplingActualLocationLineage,
    SamplingAttempt,
    SamplingObservation,
)


class PostgresSamplingReadError(SamplingConflict):
    """Persisted Sampling state cannot be rendered as a coherent read model."""


class PostgresSamplingReadRepository:
    """Read durable Attempts and Observations under the active Project scope."""

    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def attempts_for_run(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        source: SamplingSourceStratum,
    ) -> tuple[SamplingAttempt, ...]:
        rows = self._rows(project_id=project_id, run_id=run_id)
        return tuple(_attempt(row, source=source) for row in rows)

    def observations_for_run(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        source: SamplingSourceStratum,
    ) -> tuple[SamplingObservation, ...]:
        rows = self._rows(project_id=project_id, run_id=run_id)
        observations = [
            _observation(row, source=source)
            for row in rows
            if row.get("observation_id") is not None
        ]
        return tuple(sorted(observations, key=lambda item: item.task_key))

    def attempt(
        self,
        *,
        project_id: UUID,
        attempt_id: UUID,
        source: SamplingSourceStratum,
    ) -> SamplingAttempt:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                _SELECT_ATTEMPT + """\n                  WHERE attempt.project_id = %s AND attempt.id = %s""",
                (project_id, attempt_id),
            ).fetchone()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingReadError("Sampling Attempt could not be read") from error
        finally:
            connection.close()
        if row is None:
            raise SamplingNotFound("Sampling Attempt does not exist")
        return _attempt(_mapping(row), source=source)

    def _rows(self, *, project_id: UUID, run_id: UUID) -> tuple[Mapping[str, object], ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                _SELECT_ATTEMPT
                + """\n                  WHERE attempt.project_id = %s AND attempt.run_id = %s
                     ORDER BY attempt.task_key, attempt.ordinal""",
                (project_id, run_id),
            ).fetchall()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingReadError("Sampling Run evidence could not be read") from error
        finally:
            connection.close()
        return tuple(_mapping(row) for row in rows)


_SELECT_ATTEMPT = """
SELECT attempt.id AS attempt_id,
       attempt.project_id AS attempt_project_id,
       attempt.run_id AS attempt_run_id,
       attempt.task_id AS attempt_task_id,
       attempt.task_key AS attempt_task_key,
       attempt.ordinal AS attempt_ordinal,
       attempt.status AS attempt_status,
       attempt.version AS attempt_version,
       attempt.actual_location_json AS attempt_actual_location_json,
       job.id AS job_id,
       job.project_id AS job_project_id,
       job.kind AS job_kind,
       job.status AS job_status,
       job.priority AS job_priority,
       job.input_hash AS job_input_hash,
       job.idempotency_key AS job_idempotency_key,
       job.attempt_count AS job_attempt_count,
       job.max_attempts AS job_max_attempts,
       job.next_run_at AS job_next_run_at,
       job.lease_owner AS job_lease_owner,
       job.lease_token AS job_lease_token,
       job.lease_expires_at AS job_lease_expires_at,
       job.heartbeat_at AS job_heartbeat_at,
       job.fencing_generation AS job_fencing_generation,
       job.cancel_requested_at AS job_cancel_requested_at,
       job.parent_job_id AS job_parent_job_id,
       job.replay_nonce AS job_replay_nonce,
       job.result_ref AS job_result_ref,
       job.error_code AS job_error_code,
       observation.id AS observation_id,
       observation.project_id AS observation_project_id,
       observation.run_id AS observation_run_id,
       observation.task_id AS observation_task_id,
       observation.attempt_id AS observation_attempt_id,
       observation.task_key AS observation_task_key,
       observation.source_stratum_hash AS observation_source_stratum_hash,
       observation.status AS observation_status,
       observation.observation_hash AS observation_hash,
       observation.actual_location_json AS observation_actual_location_json,
       observation.evidence_json AS observation_evidence_json,
       observation.payload AS observation_payload,
       observation.observed_at AS observation_observed_at
  FROM workflow_c_sampling_attempts AS attempt
  JOIN durable_jobs AS job
    ON job.project_id = attempt.project_id AND job.id = attempt.durable_job_id
  LEFT JOIN workflow_c_sampling_observations AS observation
    ON observation.project_id = attempt.project_id AND observation.attempt_id = attempt.id
"""


def _attempt(row: Mapping[str, object], *, source: SamplingSourceStratum) -> SamplingAttempt:
    project_id = _uuid(row, "attempt_project_id")
    attempt_id = _uuid(row, "attempt_id")
    task_key = _hash(row, "attempt_task_key")
    job = _job(row, project_id=project_id, task_key=task_key)
    terminal_status = _terminal_status(job.status)
    persisted_status = _text(row, "attempt_status")
    if terminal_status is not None and persisted_status != terminal_status.value:
        raise PostgresSamplingReadError("Sampling Attempt and Durable Job terminal state differ")
    actual_location = _location(row.get("attempt_actual_location_json"))
    observation = (
        _observation(row, source=source) if row.get("observation_id") is not None else None
    )
    if observation is not None:
        if observation.winning_attempt_id != attempt_id:
            raise PostgresSamplingReadError("Sampling Observation has different Attempt lineage")
        if actual_location is not None and actual_location != observation.actual_location:
            raise PostgresSamplingReadError("Sampling Attempt location differs from Observation")
        actual_location = observation.actual_location
        evidence = observation.evidence
        provider_response_id = evidence.provider_response_id
        egress_verification_id = evidence.egress_verification_id
        raw_artifact_hash = evidence.raw_artifact.content_hash
    else:
        provider_response_id = None
        egress_verification_id = None
        raw_artifact_hash = None
    return SamplingAttempt(
        id=attempt_id,
        project_id=project_id,
        run_id=_uuid(row, "attempt_run_id"),
        task_id=_uuid(row, "attempt_task_id"),
        task_key=task_key,
        ordinal=_positive(row, "attempt_ordinal"),
        job=job,
        durable_job_id=job.id,
        record_version=_positive(row, "attempt_version"),
        provider_response_id=provider_response_id,
        egress_verification_id=egress_verification_id,
        raw_artifact_hash=raw_artifact_hash,
        actual_location=actual_location,
        terminal_status=terminal_status,
    )


def _observation(
    row: Mapping[str, object], *, source: SamplingSourceStratum
) -> SamplingObservation:
    payload = _json(row, "observation_payload")
    reasons = payload.get("ineligible_reasons")
    if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
        raise PostgresSamplingReadError("Sampling Observation reasons are invalid")
    status = EvidenceStatus(_text(row, "observation_status"))
    if payload.get("evidence_status") != status.value:
        raise PostgresSamplingReadError("Sampling Observation evidence state is corrupt")
    try:
        observation = SamplingObservation(
            id=_uuid(row, "observation_id"),
            project_id=_uuid(row, "observation_project_id"),
            run_id=_uuid(row, "observation_run_id"),
            task_id=_uuid(row, "observation_task_id"),
            task_key=_hash(row, "observation_task_key"),
            winning_attempt_id=_uuid(row, "observation_attempt_id"),
            source_stratum=source,
            source_stratum_hash=_hash(row, "observation_source_stratum_hash"),
            evidence_status=status,
            ineligible_reasons=tuple(reasons),
            evidence=_evidence(_json(row, "observation_evidence_json")),
            observed_at=_datetime(row, "observation_observed_at"),
            actual_location=_location_required(row.get("observation_actual_location_json")),
        )
    except (TypeError, ValueError) as error:
        raise PostgresSamplingReadError("Sampling Observation row is invalid") from error
    if observation.observation_hash != _hash(row, "observation_hash"):
        raise PostgresSamplingReadError("Sampling Observation hash is corrupt")
    return observation


def _job(row: Mapping[str, object], *, project_id: UUID, task_key: str) -> DurableJob:
    job_id = _uuid(row, "job_id")
    if _uuid(row, "job_project_id") != project_id:
        raise PostgresSamplingReadError("Sampling Attempt Durable Job lineage is corrupt")
    kind = _text(row, "job_kind")
    if kind not in {"sampling.provider_execute", "sampling.manual_import"}:
        raise PostgresSamplingReadError("Sampling Attempt Durable Job kind is unsupported")
    try:
        return DurableJob(
            id=job_id,
            project_id=project_id,
            # The full immutable spec is worker-only.  Attempt presentation needs
            # just this immutable public lineage subset, verified from aggregate rows.
            spec=DomainJobSpec(
                kind=kind,
                payload=MappingProxyType(
                    {
                        "run_id": str(_uuid(row, "attempt_run_id")),
                        "task_id": str(_uuid(row, "attempt_task_id")),
                        "task_key": task_key,
                        "attempt_id": str(_uuid(row, "attempt_id")),
                    }
                ),
            ),
            input_hash=_hash(row, "job_input_hash"),
            idempotency_key=_text(row, "job_idempotency_key"),
            status=JobStatus(_text(row, "job_status")),
            priority=_integer(row, "job_priority"),
            attempt_count=_nonnegative(row, "job_attempt_count"),
            max_attempts=_positive(row, "job_max_attempts"),
            next_run_at=_datetime(row, "job_next_run_at"),
            lease_owner=_nullable_text(row, "job_lease_owner"),
            lease_token=_nullable_uuid(row, "job_lease_token"),
            lease_expires_at=_nullable_datetime(row, "job_lease_expires_at"),
            heartbeat_at=_nullable_datetime(row, "job_heartbeat_at"),
            fencing_generation=_nonnegative(row, "job_fencing_generation"),
            cancel_requested_at=_nullable_datetime(row, "job_cancel_requested_at"),
            parent_job_id=_nullable_uuid(row, "job_parent_job_id"),
            replay_nonce=_nonnegative(row, "job_replay_nonce"),
            result_ref=_nullable_text(row, "job_result_ref"),
            error_code=_nullable_text(row, "job_error_code"),
        )
    except (TypeError, ValueError) as error:
        raise PostgresSamplingReadError("Sampling Attempt Durable Job is invalid") from error


def _evidence(value: Mapping[str, object]) -> ObservationEvidence:
    required = {
        "schema_version",
        "kind",
        "raw_artifact",
        "derived_artifact",
        "derived_summary",
        "evidence_locator",
        "provider_response_id",
        "egress_verification_id",
        "result_parameters_hash",
        "storage_decision",
        "cache_decision",
        "display_decision",
        "redistribution_decision",
        "usage_purpose",
        "usage_audience",
    }
    if set(value) != required or value.get("schema_version") != 1:
        raise PostgresSamplingReadError("Sampling Observation evidence schema is invalid")
    if value.get("kind") not in {"provider_api", "manual_ui"}:
        raise PostgresSamplingReadError("Sampling Observation evidence kind is invalid")
    try:
        return ObservationEvidence(
            raw_artifact=_artifact(_json_value(value.get("raw_artifact"))),
            derived_artifact=_artifact(_json_value(value.get("derived_artifact"))),
            derived_summary=_value_text(value, "derived_summary"),
            evidence_locator=_value_text(value, "evidence_locator"),
            provider_response_id=_nullable_value_text(value, "provider_response_id"),
            egress_verification_id=_nullable_value_text(value, "egress_verification_id"),
            result_parameters_hash=_value_hash(value, "result_parameters_hash"),
            storage_decision=_value_text(value, "storage_decision"),
            cache_decision=_value_text(value, "cache_decision"),
            display_decision=_value_text(value, "display_decision"),
            redistribution_decision=_value_text(value, "redistribution_decision"),
            usage_purpose=_value_text(value, "usage_purpose"),
            usage_audience=_value_text(value, "usage_audience"),
        )
    except (TypeError, ValueError) as error:
        raise PostgresSamplingReadError("Sampling Observation evidence is invalid") from error


def _location(value: object) -> SamplingActualLocationLineage | None:
    return None if value is None else _location_required(value)


def _location_required(value: object) -> SamplingActualLocationLineage:
    payload = _json_value(value)
    expected = {
        "location_control",
        "location_evidence_hash",
        "requested_country",
        "requested_region",
        "requested_locale",
        "requested_language",
        "effective_country",
        "effective_region",
        "effective_locale",
        "effective_language",
    }
    if set(payload) != expected:
        raise PostgresSamplingReadError("Sampling actual location schema is invalid")
    try:
        return SamplingActualLocationLineage(
            location_control=LocationControl(_value_text(payload, "location_control")),
            location_evidence_hash=_value_hash(payload, "location_evidence_hash"),
            requested_country=_nullable_value_text(payload, "requested_country"),
            requested_region=_nullable_value_text(payload, "requested_region"),
            requested_locale=_value_text(payload, "requested_locale"),
            requested_language=_value_text(payload, "requested_language"),
            effective_country=_nullable_value_text(payload, "effective_country"),
            effective_region=_nullable_value_text(payload, "effective_region"),
            effective_locale=_nullable_value_text(payload, "effective_locale"),
            effective_language=_nullable_value_text(payload, "effective_language"),
        )
    except (TypeError, ValueError) as error:
        raise PostgresSamplingReadError("Sampling actual location is invalid") from error


def _artifact(payload: Mapping[str, object]) -> ObservationArtifactManifest:
    expected = {
        "kind",
        "manifest_reference",
        "manifest_hash",
        "content_hash",
        "governance_policy_hash",
    }
    if set(payload) != expected:
        raise PostgresSamplingReadError("Sampling Observation artifact schema is invalid")
    return ObservationArtifactManifest(
        kind=ObservationArtifactKind(_value_text(payload, "kind")),
        manifest_reference=_value_text(payload, "manifest_reference"),
        manifest_hash=_value_hash(payload, "manifest_hash"),
        content_hash=_value_hash(payload, "content_hash"),
        governance_policy_hash=_value_hash(payload, "governance_policy_hash"),
    )


def _terminal_status(status: JobStatus) -> AttemptTerminalStatus | None:
    if status is JobStatus.SUCCEEDED:
        return AttemptTerminalStatus.SUCCEEDED
    if status in {JobStatus.FAILED, JobStatus.DEAD_LETTERED}:
        return AttemptTerminalStatus.FAILED
    if status is JobStatus.CANCELLED:
        return AttemptTerminalStatus.CANCELLED
    return None


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PostgresSamplingReadError("Sampling read row is invalid")
    return value


def _json(row: Mapping[str, object], key: str) -> Mapping[str, object]:
    return _json_value(row.get(key))


def _json_value(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise PostgresSamplingReadError("Sampling JSON value is invalid")
    return dict(value)


def _uuid(row: Mapping[str, object], key: str) -> UUID:
    value = row.get(key)
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PostgresSamplingReadError(f"Sampling {key} is invalid") from error


def _nullable_uuid(row: Mapping[str, object], key: str) -> UUID | None:
    return None if row.get(key) is None else _uuid(row, key)


def _datetime(row: Mapping[str, object], key: str) -> datetime:
    value = row.get(key)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PostgresSamplingReadError(f"Sampling {key} is invalid")
    return value


def _nullable_datetime(row: Mapping[str, object], key: str) -> datetime | None:
    return None if row.get(key) is None else _datetime(row, key)


def _text(row: Mapping[str, object], key: str) -> str:
    return _value_text(row, key)


def _nullable_text(row: Mapping[str, object], key: str) -> str | None:
    return _nullable_value_text(row, key)


def _value_text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PostgresSamplingReadError(f"Sampling {key} is invalid")
    return value


def _nullable_value_text(row: Mapping[str, object], key: str) -> str | None:
    return None if row.get(key) is None else _value_text(row, key)


def _hash(row: Mapping[str, object], key: str) -> str:
    value = _value_text(row, key)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise PostgresSamplingReadError(f"Sampling {key} must be a SHA-256 hash")
    return value


def _value_hash(row: Mapping[str, object], key: str) -> str:
    return _hash(row, key)


def _integer(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise PostgresSamplingReadError(f"Sampling {key} is invalid")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise PostgresSamplingReadError(f"Sampling {key} is invalid") from error


def _positive(row: Mapping[str, object], key: str) -> int:
    value = _integer(row, key)
    if value < 1:
        raise PostgresSamplingReadError(f"Sampling {key} must be positive")
    return value


def _nonnegative(row: Mapping[str, object], key: str) -> int:
    value = _integer(row, key)
    if value < 0:
        raise PostgresSamplingReadError(f"Sampling {key} must not be negative")
    return value


__all__ = ["PostgresSamplingReadError", "PostgresSamplingReadRepository"]
