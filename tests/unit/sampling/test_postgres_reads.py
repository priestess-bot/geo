from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from typing import Any
from uuid import uuid4

import pytest

from geo_core.sampling import (
    CaptureMethod,
    LocationControl,
    PostgresSamplingReadError,
    PostgresSamplingReadRepository,
    SamplingSourceStratum,
)
from geo_core.sampling.execution import (
    ObservationArtifactKind,
    ObservationArtifactManifest,
    ObservationEvidence,
    SamplingActualLocationLineage,
    SamplingObservation,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def test_postgres_sampling_reader_restores_persisted_attempt_and_observation() -> None:
    project_id = uuid4()
    source = _source()
    row = _row(project_id=project_id, source=source)
    repository = PostgresSamplingReadRepository(connect=lambda: _Connection(row))

    attempt = repository.attempt(
        project_id=project_id,
        attempt_id=row["attempt_id"],
        source=source,
    )
    observations = repository.observations_for_run(
        project_id=project_id,
        run_id=row["attempt_run_id"],
        source=source,
    )

    assert attempt.job.status.value == "succeeded"
    assert attempt.terminal_status is not None and attempt.terminal_status.value == "succeeded"
    assert attempt.actual_location is not None
    assert attempt.raw_artifact_hash == _hash("raw-content")
    assert len(observations) == 1
    assert observations[0].observation_hash == row["observation_hash"]
    assert observations[0].source_stratum_hash == source.stratum_hash


def test_postgres_sampling_reader_rejects_tampered_observation_hash() -> None:
    project_id = uuid4()
    source = _source()
    row = _row(project_id=project_id, source=source)
    row["observation_hash"] = _hash("tampered")
    repository = PostgresSamplingReadRepository(connect=lambda: _Connection(row))

    with pytest.raises(PostgresSamplingReadError, match="hash is corrupt"):
        repository.observations_for_run(
            project_id=project_id,
            run_id=row["attempt_run_id"],
            source=source,
        )


def _source() -> SamplingSourceStratum:
    return SamplingSourceStratum(
        platform="openai",
        surface="chat_completions",
        configured_model="gpt-5",
        reported_model="gpt-5",
        capture_method=CaptureMethod.PROVIDER_API,
        adapter_release="openai-v1",
        locale="en-AU",
        region="not_controlled",
        language="en",
        search_mode="web",
        account_cohort="not_applicable",
        egress_policy_category="not_applicable",
        location_control=LocationControl.MARKET_LANGUAGE,
        location_evidence_hash=_hash("location"),
        requested_country=None,
        requested_region=None,
        requested_locale="en-AU",
        requested_language="en",
        effective_country=None,
        effective_region=None,
        effective_locale="en-AU",
        effective_language="en",
    )


def _row(*, project_id, source: SamplingSourceStratum) -> dict[str, Any]:
    attempt_id, run_id, task_id, observation_id, job_id = (uuid4() for _ in range(5))
    task_key = _hash("task")
    actual = SamplingActualLocationLineage(
        location_control=source.location_control,
        location_evidence_hash=source.location_evidence_hash,
        requested_country=source.requested_country,
        requested_region=source.requested_region,
        requested_locale=source.requested_locale,
        requested_language=source.requested_language,
        effective_country=source.effective_country,
        effective_region=source.effective_region,
        effective_locale=source.effective_locale,
        effective_language=source.effective_language,
    )
    evidence = ObservationEvidence(
        raw_artifact=ObservationArtifactManifest(
            kind=ObservationArtifactKind.RAW,
            manifest_reference="restricted://raw",
            manifest_hash=_hash("raw-manifest"),
            content_hash=_hash("raw-content"),
            governance_policy_hash=_hash("governance"),
        ),
        derived_artifact=ObservationArtifactManifest(
            kind=ObservationArtifactKind.DERIVED,
            manifest_reference="restricted://derived",
            manifest_hash=_hash("derived-manifest"),
            content_hash=_hash("derived-content"),
            governance_policy_hash=_hash("governance"),
        ),
        derived_summary="Governed provider evidence was retained.",
        evidence_locator="observation://provider/1",
        provider_response_id="provider-response-1",
        egress_verification_id="egress-1",
        result_parameters_hash=_hash("parameters"),
        storage_decision="allowed",
        cache_decision="prohibited",
        display_decision="allowed",
        redistribution_decision="prohibited",
        usage_purpose="geo_measurement",
        usage_audience="admin",
    )
    observation = SamplingObservation(
        id=observation_id,
        project_id=project_id,
        run_id=run_id,
        task_id=task_id,
        task_key=task_key,
        winning_attempt_id=attempt_id,
        source_stratum=source,
        source_stratum_hash=source.stratum_hash,
        evidence_status="complete",
        ineligible_reasons=(),
        evidence=evidence,
        observed_at=NOW,
        actual_location=actual,
    )
    evidence_payload = {"schema_version": 1, "kind": "provider_api", **evidence.canonical_value()}
    return {
        "attempt_id": attempt_id,
        "attempt_project_id": project_id,
        "attempt_run_id": run_id,
        "attempt_task_id": task_id,
        "attempt_task_key": task_key,
        "attempt_ordinal": 1,
        "attempt_status": "succeeded",
        "attempt_version": 3,
        "attempt_actual_location_json": actual.canonical_value(),
        "job_id": job_id,
        "job_project_id": project_id,
        "job_kind": "sampling.provider_execute",
        "job_status": "succeeded",
        "job_priority": 0,
        "job_input_hash": _hash("job-input"),
        "job_idempotency_key": "sampling-attempt-1",
        "job_attempt_count": 1,
        "job_max_attempts": 3,
        "job_next_run_at": NOW,
        "job_lease_owner": None,
        "job_lease_token": None,
        "job_lease_expires_at": None,
        "job_heartbeat_at": None,
        "job_fencing_generation": 1,
        "job_cancel_requested_at": None,
        "job_parent_job_id": None,
        "job_replay_nonce": 0,
        "job_result_ref": f"sampling-observation:{observation_id}",
        "job_error_code": None,
        "observation_id": observation_id,
        "observation_project_id": project_id,
        "observation_run_id": run_id,
        "observation_task_id": task_id,
        "observation_attempt_id": attempt_id,
        "observation_task_key": task_key,
        "observation_source_stratum_hash": source.stratum_hash,
        "observation_status": "complete",
        "observation_hash": observation.observation_hash,
        "observation_actual_location_json": actual.canonical_value(),
        "observation_evidence_json": evidence_payload,
        "observation_payload": {"evidence_status": "complete", "ineligible_reasons": []},
        "observation_observed_at": NOW,
    }


class _Cursor:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [] if self._row is None else [self._row]


class _Connection:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def execute(self, statement: str, params=None) -> _Cursor:
        return _Cursor(self._row if "workflow_c_sampling_attempts" in statement else None)

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
