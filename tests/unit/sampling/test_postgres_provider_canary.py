from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from unittest.mock import Mock
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from geo_core.sampling import CaptureMethod, LocationControl, SamplingSourceStratum
from geo_core.sampling.postgres_provider_canary import (
    PostgresProviderCanaryError,
    PostgresProviderCanaryRepository,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _uuid(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, value)


NOW = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
PROJECT_ID = uuid5(NAMESPACE_URL, "canary-project")
RUN_ID = uuid5(NAMESPACE_URL, "canary-run")
SUITE_ID = uuid5(NAMESPACE_URL, "canary-suite")
ADAPTER_HASH = _hash("adapter")
MODEL_HASH = _hash("model")
POLICY_HASH = _hash("policy")


def test_postgres_canary_reader_reconstructs_only_frozen_lineage() -> None:
    connection = _connection()
    repository = PostgresProviderCanaryRepository(connect=lambda: connection)

    evidence = repository.read(project_id=PROJECT_ID, run_id=RUN_ID)

    assert evidence.project_id == PROJECT_ID
    assert evidence.run_id == RUN_ID
    assert evidence.platform == "google"
    assert evidence.surface == "google_gemini_api"
    assert evidence.adapter_release_id == "gemini-adapter-v1"
    assert evidence.valid_task_count == 10
    assert len(evidence.calls) == 10
    assert {item.provider for item in evidence.calls} == {"gemini"}
    assert connection.rollback.call_count == 1
    assert connection.close.call_count == 1
    persisted = repr(evidence).lower()
    for prohibited in ("question text", "answer text", "secret-value", "s3://"):
        assert prohibited not in persisted


def test_postgres_canary_reader_rejects_sampling_model_response_hash_drift() -> None:
    call_rows = _call_rows()
    call_rows[0]["provider_response_hash"] = _hash("different-response")
    connection = _connection(call_rows=call_rows)

    with pytest.raises(PostgresProviderCanaryError, match="response hashes differ"):
        PostgresProviderCanaryRepository(connect=lambda: connection).read(
            project_id=PROJECT_ID, run_id=RUN_ID
        )


def test_postgres_canary_reader_rejects_nonterminal_model_attempt() -> None:
    call_rows = _call_rows()
    call_rows[0]["terminal_status"] = None
    connection = _connection(call_rows=call_rows)

    with pytest.raises(PostgresProviderCanaryError, match="terminal Model Call"):
        PostgresProviderCanaryRepository(connect=lambda: connection).read(
            project_id=PROJECT_ID, run_id=RUN_ID
        )


def _connection(*, call_rows: list[dict[str, object]] | None = None) -> Mock:
    connection = Mock()
    connection.execute.side_effect = (
        _Result(),
        _Result(one=_meta_row()),
        _Result(many=_task_rows()),
        _Result(many=call_rows or _call_rows()),
    )
    return connection


class _Result:
    def __init__(
        self,
        *,
        one: dict[str, object] | None = None,
        many: list[dict[str, object]] | None = None,
    ) -> None:
        self._one = one
        self._many = many or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


def _source() -> SamplingSourceStratum:
    return SamplingSourceStratum(
        platform="google",
        surface="google_gemini_api",
        configured_model="gemini-configured-model",
        reported_model="gemini-reported-model",
        capture_method=CaptureMethod.PROVIDER_API,
        adapter_release="gemini-adapter-v1",
        locale="en-AU",
        region="not_controlled",
        language="en",
        search_mode="google_search",
        account_cohort="not_applicable",
        egress_policy_category="not_applicable",
        location_control=LocationControl.NOT_CONTROLLED,
        location_evidence_hash=_hash("uncontrolled-location"),
        requested_country="AU",
        requested_region=None,
        requested_locale="en-AU",
        requested_language="en",
        effective_country=None,
        effective_region=None,
        effective_locale=None,
        effective_language=None,
    )


def _meta_row() -> dict[str, object]:
    source = _source()
    return {
        "project_id": PROJECT_ID,
        "run_id": RUN_ID,
        "run_status": "completed",
        "purpose": "provider_live_canary",
        "started_at": NOW,
        "suite_id": SUITE_ID,
        "suite_hash": _hash("suite"),
        "suite_payload": {
            "source_stratum": source.canonical_value(),
            "adapter_release_hash": ADAPTER_HASH,
            "model_release_hash": MODEL_HASH,
        },
        "completed_at": NOW + timedelta(minutes=1),
    }


def _task_rows() -> list[dict[str, object]]:
    return [
        {
            "task_id": _uuid(f"task-{index}"),
            "task_key": _hash(f"task-{index}"),
            "question_id": "canary-question",
            "question_version": "v1",
            "repetition": index,
        }
        for index in range(1, 11)
    ]


def _call_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for task in _task_rows():
        repetition = task["repetition"]
        response_hash = _hash(f"response-{repetition}")
        provider_request_id = f"gemini-request-{repetition}"
        rows.append(
            {
                "sampling_attempt_id": _uuid(f"sampling-{repetition}"),
                "durable_job_id": _uuid(f"job-{repetition}"),
                "task_id": task["task_id"],
                "task_key": task["task_key"],
                "question_id": task["question_id"],
                "question_version": task["question_version"],
                "repetition": repetition,
                "model_call_attempt_id": _uuid(f"model-{repetition}"),
                "provider": "gemini",
                "adapter_release_id": "gemini-adapter-v1",
                "adapter_release_hash": ADAPTER_HASH,
                "model_release_id": "gemini-model-v1",
                "model_release_hash": MODEL_HASH,
                "configured_model": "gemini-configured-model",
                "capture_method": "provider_api",
                "requested_search_mode": "google_search",
                "terminal_status": "succeeded",
                "occurred_at": NOW + timedelta(seconds=int(repetition)),
                "provider_reported_model": "gemini-reported-model",
                "provider_request_id": provider_request_id,
                "response_hash": response_hash,
                "output_hash": _hash(f"output-{repetition}"),
                "search_mode": "google_search",
                "citation_count": 1,
                "citation_lineage_hash": _hash(f"citation-{repetition}"),
                "search_event_count": 1,
                "search_lineage_hash": _hash(f"search-{repetition}"),
                "usage_details_hash": _hash(f"usage-{repetition}"),
                "raw_artifact_policy_hash": POLICY_HASH,
                "raw_artifact_storage_decision": "allowed",
                "raw_artifact_display_decision": "allowed",
                "raw_artifact_retention_days": 30,
                "effective_location_evidence_hash": _hash("uncontrolled-location"),
                "error_code": None,
                "error_retryable": None,
                "observation_id": _uuid(f"observation-{repetition}"),
                "evidence_status": "complete",
                "observation_hash": _hash(f"observation-{repetition}"),
                "evidence_json": {
                    "provider_response_id": provider_request_id,
                    "raw_artifact": {"manifest_hash": _hash(f"raw-{repetition}")},
                    "derived_artifact": {
                        "manifest_hash": _hash(f"derived-{repetition}")
                    },
                },
                "provider_response_hash": response_hash,
            }
        )
    return rows
