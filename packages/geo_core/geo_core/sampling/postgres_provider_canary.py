"""Project-scoped, text-free Provider canary evidence reader."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg

from geo_core.project_scope import set_project_scope
from geo_core.sampling.contracts import CaptureMethod
from geo_core.sampling.postgres_suites import sampling_source_stratum_from_value
from geo_core.sampling.provider_canary import (
    ProviderCanaryAttemptEvidence,
    ProviderCanaryAttemptStatus,
    ProviderCanaryError,
    ProviderCanaryPlannedTask,
    ProviderCanaryRunEvidence,
)


class PostgresProviderCanaryError(ProviderCanaryError):
    """Persistent canary lineage cannot be exported safely."""


class PostgresProviderCanaryRepository:
    """Read only allowlisted hashes and identities under Project RLS."""

    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def read(self, *, project_id: UUID, run_id: UUID) -> ProviderCanaryRunEvidence:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            meta_row = connection.execute(_META_SQL, (project_id, run_id)).fetchone()
            task_rows = connection.execute(_TASK_SQL, (project_id, run_id)).fetchall()
            call_rows = connection.execute(_CALL_SQL, (project_id, run_id)).fetchall()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresProviderCanaryError(
                "Provider canary evidence could not be read"
            ) from error
        finally:
            connection.close()
        if meta_row is None or not task_rows:
            raise PostgresProviderCanaryError("Provider canary Run does not exist")
        meta = _mapping(meta_row)
        suite_payload = _json(meta, "suite_payload")
        source_payload = suite_payload.get("source_stratum")
        if not isinstance(source_payload, Mapping):
            raise PostgresProviderCanaryError("canary Suite source stratum is absent")
        try:
            source = sampling_source_stratum_from_value(source_payload)
        except (TypeError, ValueError) as error:
            raise PostgresProviderCanaryError(
                "canary Suite source stratum is invalid"
            ) from error
        planned = tuple(_planned_task(_mapping(row)) for row in task_rows)
        calls = tuple(_call(_mapping(row)) for row in call_rows)
        if not calls:
            raise PostgresProviderCanaryError("Provider canary has no Model Call evidence")
        adapter_hash = _hash(suite_payload, "adapter_release_hash")
        model_hash = _hash(suite_payload, "model_release_hash")
        first = calls[0]
        if (
            first.adapter_release_id != source.adapter_release
            or first.adapter_release_hash != adapter_hash
            or first.model_release_hash != model_hash
        ):
            raise PostgresProviderCanaryError(
                "canary Model Call route differs from frozen Suite selectors"
            )
        completed_at = _datetime(meta, "completed_at")
        return ProviderCanaryRunEvidence(
            project_id=_uuid(meta, "project_id"),
            suite_id=_uuid(meta, "suite_id"),
            suite_hash=_hash(meta, "suite_hash"),
            run_id=_uuid(meta, "run_id"),
            run_status=_text(meta, "run_status"),
            purpose=_text(meta, "purpose"),
            platform=source.platform,
            surface=source.surface,
            capture_method=source.capture_method,
            source_stratum_hash=source.stratum_hash,
            adapter_release_id=first.adapter_release_id,
            adapter_release_hash=first.adapter_release_hash,
            model_release_id=first.model_release_id,
            model_release_hash=first.model_release_hash,
            planned_tasks=planned,
            calls=calls,
            started_at=_datetime(meta, "started_at"),
            completed_at=completed_at,
        )


_META_SQL = """
SELECT run.project_id,
       run.id AS run_id,
       run.status AS run_status,
       run.purpose,
       run.created_at AS started_at,
       suite.id AS suite_id,
       suite.suite_hash,
       suite.payload AS suite_payload,
       max(task.updated_at) AS completed_at
  FROM workflow_c_sampling_runs AS run
  JOIN workflow_c_sampling_suites AS suite
    ON suite.project_id = run.project_id AND suite.id = run.suite_id
  JOIN workflow_c_sampling_tasks AS task
    ON task.project_id = run.project_id AND task.run_id = run.id
 WHERE run.project_id = %s AND run.id = %s
 GROUP BY run.project_id, run.id, run.status, run.purpose, run.created_at,
          suite.id, suite.suite_hash, suite.payload
"""


_TASK_SQL = """
SELECT task.id AS task_id,
       task.task_key,
       task.question_id,
       task.question_version,
       task.repetition
  FROM workflow_c_sampling_tasks AS task
 WHERE task.project_id = %s AND task.run_id = %s
 ORDER BY task.task_key
"""


_CALL_SQL = """
SELECT attempt.id AS sampling_attempt_id,
       attempt.durable_job_id,
       task.id AS task_id,
       task.task_key,
       task.question_id,
       task.question_version,
       task.repetition,
       model_attempt.id AS model_call_attempt_id,
       model_attempt.provider,
       model_attempt.adapter_release_id,
       model_attempt.adapter_release_hash,
       model_attempt.model_release_id,
       model_attempt.model_release_hash,
       model_attempt.configured_model,
       model_attempt.capture_method,
       model_attempt.search_mode AS requested_search_mode,
       terminal.status AS terminal_status,
       terminal.occurred_at,
       terminal.provider_reported_model,
       terminal.provider_request_id,
       terminal.response_hash,
       terminal.output_hash,
       terminal.search_mode,
       terminal.citation_count,
       terminal.citation_lineage_hash,
       terminal.search_event_count,
       terminal.search_lineage_hash,
       terminal.usage_details_hash,
       terminal.raw_artifact_policy_hash,
       terminal.raw_artifact_storage_decision,
       terminal.raw_artifact_display_decision,
       terminal.raw_artifact_retention_days,
       terminal.effective_location_evidence_hash,
       terminal.error_code,
       terminal.error_retryable,
       observation.id AS observation_id,
       observation.status AS evidence_status,
       observation.observation_hash,
       observation.evidence_json,
       attempt.provider_response_hash
  FROM workflow_c_sampling_attempts AS attempt
  JOIN workflow_c_sampling_tasks AS task
    ON task.project_id = attempt.project_id AND task.id = attempt.task_id
  LEFT JOIN model_gateway_call_attempts AS model_attempt
    ON model_attempt.project_id = attempt.project_id
   AND model_attempt.job_id = attempt.durable_job_id
  LEFT JOIN model_gateway_terminal_events AS terminal
    ON terminal.project_id = model_attempt.project_id
   AND terminal.attempt_id = model_attempt.id
  LEFT JOIN workflow_c_sampling_observations AS observation
    ON observation.project_id = attempt.project_id
   AND observation.attempt_id = attempt.id
 WHERE attempt.project_id = %s AND attempt.run_id = %s
 ORDER BY task.task_key, attempt.ordinal, model_attempt.attempt_number
"""


def _planned_task(row: Mapping[str, object]) -> ProviderCanaryPlannedTask:
    return ProviderCanaryPlannedTask(
        task_key=_hash(row, "task_key"),
        task_id=_uuid(row, "task_id"),
        question_id=_text(row, "question_id"),
        question_version=_text(row, "question_version"),
        repetition=_positive(row, "repetition"),
    )


def _call(row: Mapping[str, object]) -> ProviderCanaryAttemptEvidence:
    if row.get("model_call_attempt_id") is None or row.get("terminal_status") is None:
        raise PostgresProviderCanaryError(
            "canary Sampling Attempt lacks terminal Model Call evidence"
        )
    evidence = _optional_json(row, "evidence_json")
    terminal_status = ProviderCanaryAttemptStatus(_text(row, "terminal_status"))
    response_hash: str | None
    provider_request_id: str | None
    raw_manifest_hash: str | None
    derived_manifest_hash: str | None
    if terminal_status is ProviderCanaryAttemptStatus.SUCCEEDED:
        if evidence is None:
            raise PostgresProviderCanaryError(
                "successful canary Model Call has no Sampling Observation"
            )
        raw = _nested(evidence, "raw_artifact")
        derived = _nested(evidence, "derived_artifact")
        response_hash = _hash(row, "response_hash")
        if _hash(row, "provider_response_hash") != response_hash:
            raise PostgresProviderCanaryError(
                "canary Sampling and Model Call response hashes differ"
            )
        provider_request_id = _optional_text(row, "provider_request_id")
        if evidence.get("provider_response_id") != provider_request_id:
            raise PostgresProviderCanaryError(
                "canary Observation provider request lineage differs"
            )
        raw_manifest_hash = _hash(raw, "manifest_hash")
        derived_manifest_hash = _hash(derived, "manifest_hash")
    else:
        if evidence is not None:
            raise PostgresProviderCanaryError(
                "failed canary Model Call unexpectedly has Observation evidence"
            )
        response_hash = _optional_hash(row, "response_hash")
        provider_request_id = _optional_text(row, "provider_request_id")
        raw_manifest_hash = derived_manifest_hash = None
    requested_search_mode = _text(row, "requested_search_mode")
    if _text(row, "search_mode") != requested_search_mode:
        raise PostgresProviderCanaryError("canary requested and effective search modes differ")
    return ProviderCanaryAttemptEvidence(
        sampling_attempt_id=_uuid(row, "sampling_attempt_id"),
        durable_job_id=_uuid(row, "durable_job_id"),
        model_call_attempt_id=_uuid(row, "model_call_attempt_id"),
        task_id=_uuid(row, "task_id"),
        task_key=_hash(row, "task_key"),
        question_id=_text(row, "question_id"),
        question_version=_text(row, "question_version"),
        repetition=_positive(row, "repetition"),
        status=terminal_status,
        provider=_text(row, "provider"),
        adapter_release_id=_text(row, "adapter_release_id"),
        adapter_release_hash=_hash(row, "adapter_release_hash"),
        model_release_id=_text(row, "model_release_id"),
        model_release_hash=_hash(row, "model_release_hash"),
        configured_model=_text(row, "configured_model"),
        provider_reported_model=_optional_text(row, "provider_reported_model"),
        provider_request_id=provider_request_id,
        capture_method=CaptureMethod(_text(row, "capture_method")),
        search_mode=requested_search_mode,
        citation_count=_nonnegative(row, "citation_count"),
        citation_lineage_hash=_hash(row, "citation_lineage_hash"),
        search_event_count=_nonnegative(row, "search_event_count"),
        search_lineage_hash=_hash(row, "search_lineage_hash"),
        usage_details_hash=_hash(row, "usage_details_hash"),
        raw_artifact_policy_hash=_hash(row, "raw_artifact_policy_hash"),
        raw_storage_decision=_text(row, "raw_artifact_storage_decision"),
        raw_display_decision=_text(row, "raw_artifact_display_decision"),
        raw_retention_days=_optional_nonnegative(row, "raw_artifact_retention_days"),
        response_hash=response_hash,
        output_hash=_optional_hash(row, "output_hash"),
        observation_id=_optional_uuid(row, "observation_id"),
        observation_hash=_optional_hash(row, "observation_hash"),
        raw_artifact_manifest_hash=raw_manifest_hash,
        derived_artifact_manifest_hash=derived_manifest_hash,
        evidence_status=_optional_text(row, "evidence_status"),
        location_evidence_hash=_optional_hash(
            row, "effective_location_evidence_hash"
        ),
        error_code=_optional_text(row, "error_code"),
        error_retryable=_optional_bool(row, "error_retryable"),
        occurred_at=_datetime(row, "occurred_at"),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PostgresProviderCanaryError("canary query requires mapping rows")
    return value


def _json(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise PostgresProviderCanaryError(f"canary {key} must be an object")
    return item


def _optional_json(
    value: Mapping[str, object], key: str
) -> Mapping[str, object] | None:
    return None if value.get(key) is None else _json(value, key)


def _nested(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    return _json(value, key)


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise PostgresProviderCanaryError(f"canary {key} must be non-empty text")
    return item


def _optional_text(value: Mapping[str, object], key: str) -> str | None:
    return None if value.get(key) is None else _text(value, key)


def _hash(value: Mapping[str, object], key: str) -> str:
    from geo_core.sampling.contracts import SHA256_PATTERN

    item = _text(value, key)
    if SHA256_PATTERN.fullmatch(item) is None:
        raise PostgresProviderCanaryError(f"canary {key} must be SHA-256")
    return item


def _optional_hash(value: Mapping[str, object], key: str) -> str | None:
    return None if value.get(key) is None else _hash(value, key)


def _uuid(value: Mapping[str, object], key: str) -> UUID:
    item = value.get(key)
    try:
        parsed = item if isinstance(item, UUID) else UUID(str(item))
    except (TypeError, ValueError) as error:
        raise PostgresProviderCanaryError(f"canary {key} must be UUID") from error
    if parsed.int == 0:
        raise PostgresProviderCanaryError(f"canary {key} cannot be zero")
    return parsed


def _optional_uuid(value: Mapping[str, object], key: str) -> UUID | None:
    return None if value.get(key) is None else _uuid(value, key)


def _datetime(value: Mapping[str, object], key: str) -> datetime:
    item = value.get(key)
    if not isinstance(item, datetime) or item.tzinfo is None or item.utcoffset() is None:
        raise PostgresProviderCanaryError(f"canary {key} must be aware datetime")
    return item


def _nonnegative(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise PostgresProviderCanaryError(f"canary {key} must be nonnegative integer")
    return item


def _positive(value: Mapping[str, object], key: str) -> int:
    item = _nonnegative(value, key)
    if item < 1:
        raise PostgresProviderCanaryError(f"canary {key} must be positive")
    return item


def _optional_nonnegative(value: Mapping[str, object], key: str) -> int | None:
    return None if value.get(key) is None else _nonnegative(value, key)


def _optional_bool(value: Mapping[str, object], key: str) -> bool | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, bool):
        raise PostgresProviderCanaryError(f"canary {key} must be boolean")
    return item


__all__ = ["PostgresProviderCanaryError", "PostgresProviderCanaryRepository"]
