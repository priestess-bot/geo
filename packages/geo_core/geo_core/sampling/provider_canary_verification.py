"""Independent semantic verification for redacted Provider canary manifests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import hashlib
import json
import re
from uuid import UUID

from geo_core.sampling.contracts import CaptureMethod
from geo_core.sampling.provider_canary import (
    ProviderCanaryAttemptEvidence,
    ProviderCanaryAttemptStatus,
    ProviderCanaryError,
    ProviderCanaryPlannedTask,
    ProviderCanaryRunEvidence,
    build_provider_canary_manifest,
)
from geo_core.sampling.provider_release import ProviderSamplingRelease


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROOT_FIELDS = {
    "schema_version",
    "release_id",
    "release_hash",
    "project_id",
    "suite_id",
    "suite_hash",
    "run_id",
    "source_stratum_hash",
    "platform",
    "surface",
    "capture_method",
    "planned_tasks",
    "planned_task_count",
    "valid_task_count",
    "invalid_task_count",
    "missing_task_count",
    "denominator_hash",
    "started_at",
    "completed_at",
    "calls",
    "generated_at",
    "manifest_hash",
}
_PLANNED_TASK_FIELDS = {
    "task_key",
    "task_id",
    "question_id",
    "question_version",
    "repetition",
}
_CALL_FIELDS = {
    "sampling_attempt_id",
    "durable_job_id",
    "model_call_attempt_id",
    "task_id",
    "task_key",
    "question_id",
    "question_version",
    "repetition",
    "status",
    "provider",
    "adapter_release_id",
    "adapter_release_hash",
    "model_release_id",
    "model_release_hash",
    "configured_model",
    "provider_reported_model",
    "provider_request_id",
    "capture_method",
    "search_mode",
    "citation_count",
    "citation_lineage_hash",
    "search_event_count",
    "search_lineage_hash",
    "usage_details_hash",
    "raw_artifact_policy_hash",
    "raw_storage_decision",
    "raw_display_decision",
    "raw_retention_days",
    "response_hash",
    "output_hash",
    "observation_id",
    "observation_hash",
    "raw_artifact_manifest_hash",
    "derived_artifact_manifest_hash",
    "evidence_status",
    "location_evidence_hash",
    "error_code",
    "error_retryable",
    "occurred_at",
}


def verify_provider_canary_manifest_value(
    value: Mapping[str, object], release: ProviderSamplingRelease
) -> str:
    """Reject both byte-level tampering and semantically forged acceptance data."""

    _exact_fields(value, _ROOT_FIELDS, "provider canary manifest")
    manifest_hash = _hash(value, "manifest_hash")
    payload = dict(value)
    payload.pop("manifest_hash")
    if _canonical_hash(payload) != manifest_hash:
        raise ProviderCanaryError("provider canary manifest hash does not match")
    if value.get("schema_version") != 1:
        raise ProviderCanaryError("provider canary manifest schema is unsupported")
    if (
        _text(value, "release_id") != release.release_id
        or _hash(value, "release_hash") != release.release_hash
    ):
        raise ProviderCanaryError("provider canary manifest release does not match")

    try:
        run = ProviderCanaryRunEvidence(
            project_id=_uuid(value, "project_id"),
            suite_id=_uuid(value, "suite_id"),
            suite_hash=_hash(value, "suite_hash"),
            run_id=_uuid(value, "run_id"),
            run_status="completed",
            purpose="provider_live_canary",
            platform=_text(value, "platform"),
            surface=_text(value, "surface"),
            capture_method=CaptureMethod(_text(value, "capture_method")),
            source_stratum_hash=_hash(value, "source_stratum_hash"),
            adapter_release_id=release.adapter_release_id,
            adapter_release_hash=release.adapter_release_hash,
            model_release_id=release.model_release_id,
            model_release_hash=release.model_release_hash,
            planned_tasks=tuple(
                _planned_task(item)
                for item in _object_array(value, "planned_tasks")
            ),
            calls=tuple(_call(item) for item in _object_array(value, "calls")),
            started_at=_timestamp(value, "started_at"),
            completed_at=_timestamp(value, "completed_at"),
        )
        rebuilt = build_provider_canary_manifest(
            release,
            run,
            generated_at=_timestamp(value, "generated_at"),
        )
    except ProviderCanaryError:
        raise
    except (TypeError, ValueError) as error:
        raise ProviderCanaryError("provider canary manifest has invalid typed values") from error
    if rebuilt.value() != dict(value):
        raise ProviderCanaryError("provider canary manifest is not canonical or coherent")
    if rebuilt.manifest_hash is None:
        raise ProviderCanaryError("provider canary manifest hash was not rebuilt")
    return rebuilt.manifest_hash


def _planned_task(value: Mapping[str, object]) -> ProviderCanaryPlannedTask:
    _exact_fields(value, _PLANNED_TASK_FIELDS, "provider canary planned Task")
    return ProviderCanaryPlannedTask(
        task_key=_hash(value, "task_key"),
        task_id=_uuid(value, "task_id"),
        question_id=_text(value, "question_id"),
        question_version=_text(value, "question_version"),
        repetition=_integer(value, "repetition"),
    )


def _call(value: Mapping[str, object]) -> ProviderCanaryAttemptEvidence:
    _exact_fields(value, _CALL_FIELDS, "provider canary call")
    return ProviderCanaryAttemptEvidence(
        sampling_attempt_id=_uuid(value, "sampling_attempt_id"),
        durable_job_id=_uuid(value, "durable_job_id"),
        model_call_attempt_id=_uuid(value, "model_call_attempt_id"),
        task_id=_uuid(value, "task_id"),
        task_key=_hash(value, "task_key"),
        question_id=_text(value, "question_id"),
        question_version=_text(value, "question_version"),
        repetition=_integer(value, "repetition"),
        status=ProviderCanaryAttemptStatus(_text(value, "status")),
        provider=_text(value, "provider"),
        adapter_release_id=_text(value, "adapter_release_id"),
        adapter_release_hash=_hash(value, "adapter_release_hash"),
        model_release_id=_text(value, "model_release_id"),
        model_release_hash=_hash(value, "model_release_hash"),
        configured_model=_text(value, "configured_model"),
        provider_reported_model=_optional_text(value, "provider_reported_model"),
        provider_request_id=_optional_text(value, "provider_request_id"),
        capture_method=CaptureMethod(_text(value, "capture_method")),
        search_mode=_text(value, "search_mode"),
        citation_count=_integer(value, "citation_count"),
        citation_lineage_hash=_hash(value, "citation_lineage_hash"),
        search_event_count=_integer(value, "search_event_count"),
        search_lineage_hash=_hash(value, "search_lineage_hash"),
        usage_details_hash=_hash(value, "usage_details_hash"),
        raw_artifact_policy_hash=_hash(value, "raw_artifact_policy_hash"),
        raw_storage_decision=_text(value, "raw_storage_decision"),
        raw_display_decision=_text(value, "raw_display_decision"),
        raw_retention_days=_optional_integer(value, "raw_retention_days"),
        response_hash=_optional_hash(value, "response_hash"),
        output_hash=_optional_hash(value, "output_hash"),
        observation_id=_optional_uuid(value, "observation_id"),
        observation_hash=_optional_hash(value, "observation_hash"),
        raw_artifact_manifest_hash=_optional_hash(
            value, "raw_artifact_manifest_hash"
        ),
        derived_artifact_manifest_hash=_optional_hash(
            value, "derived_artifact_manifest_hash"
        ),
        evidence_status=_optional_text(value, "evidence_status"),
        location_evidence_hash=_optional_hash(value, "location_evidence_hash"),
        error_code=_optional_text(value, "error_code"),
        error_retryable=_optional_boolean(value, "error_retryable"),
        occurred_at=_timestamp(value, "occurred_at"),
    )


def _exact_fields(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ProviderCanaryError(f"{label} fields are not allowlisted")


def _object_array(
    value: Mapping[str, object], key: str
) -> tuple[Mapping[str, object], ...]:
    item = value.get(key)
    if not isinstance(item, list):
        raise ProviderCanaryError(f"provider canary {key} must be an array")
    result: list[Mapping[str, object]] = []
    for child in item:
        if not isinstance(child, Mapping) or not all(
            isinstance(child_key, str) for child_key in child
        ):
            raise ProviderCanaryError(f"provider canary {key} items must be objects")
        result.append(child)
    return tuple(result)


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ProviderCanaryError(f"provider canary {key} must be text")
    return item


def _optional_text(value: Mapping[str, object], key: str) -> str | None:
    return None if value.get(key) is None else _text(value, key)


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise ProviderCanaryError(f"provider canary {key} must be non-negative integer")
    return item


def _optional_integer(value: Mapping[str, object], key: str) -> int | None:
    return None if value.get(key) is None else _integer(value, key)


def _optional_boolean(value: Mapping[str, object], key: str) -> bool | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, bool):
        raise ProviderCanaryError(f"provider canary {key} must be boolean")
    return item


def _uuid(value: Mapping[str, object], key: str) -> UUID:
    try:
        return UUID(_text(value, key))
    except ValueError as error:
        raise ProviderCanaryError(f"provider canary {key} must be UUID") from error


def _optional_uuid(value: Mapping[str, object], key: str) -> UUID | None:
    return None if value.get(key) is None else _uuid(value, key)


def _hash(value: Mapping[str, object], key: str) -> str:
    item = _text(value, key)
    if _SHA256.fullmatch(item) is None:
        raise ProviderCanaryError(f"provider canary {key} must be SHA-256")
    return item


def _optional_hash(value: Mapping[str, object], key: str) -> str | None:
    return None if value.get(key) is None else _hash(value, key)


def _timestamp(value: Mapping[str, object], key: str) -> datetime:
    try:
        item = datetime.fromisoformat(_text(value, key).replace("Z", "+00:00"))
    except ValueError as error:
        raise ProviderCanaryError(f"provider canary {key} must be ISO datetime") from error
    if item.tzinfo is None or item.utcoffset() is None:
        raise ProviderCanaryError(f"provider canary {key} must include timezone")
    return item


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["verify_provider_canary_manifest_value"]
