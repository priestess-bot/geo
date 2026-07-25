"""Redacted, replayable acceptance evidence for live Provider Sampling runs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re
from uuid import UUID

from geo_core.sampling.contracts import CaptureMethod, canonical_hash
from geo_core.sampling.provider_release import (
    ProviderSamplingRelease,
)
from geo_core.sampling.provider_sources import require_canonical_provider_source


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProviderCanaryError(ValueError):
    """A purported live canary lacks sufficient or coherent evidence."""


class ProviderCanaryAttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, order=True)
class ProviderCanaryPlannedTask:
    task_key: str
    task_id: UUID
    question_id: str
    question_version: str
    repetition: int

    def __post_init__(self) -> None:
        _require_hash(self.task_key, "planned task")
        if self.task_id.int == 0 or self.repetition < 1:
            raise ProviderCanaryError("planned canary Task identity is invalid")
        if not self.question_id.strip() or not self.question_version.strip():
            raise ProviderCanaryError("planned canary question identity is empty")

    def manifest_value(self) -> dict[str, object]:
        return {
            "task_key": self.task_key,
            "task_id": str(self.task_id),
            "question_id": self.question_id,
            "question_version": self.question_version,
            "repetition": self.repetition,
        }


@dataclass(frozen=True)
class ProviderCanaryAttemptEvidence:
    sampling_attempt_id: UUID
    durable_job_id: UUID
    model_call_attempt_id: UUID
    task_id: UUID
    task_key: str
    question_id: str
    question_version: str
    repetition: int
    status: ProviderCanaryAttemptStatus
    provider: str
    adapter_release_id: str
    adapter_release_hash: str
    model_release_id: str
    model_release_hash: str
    configured_model: str
    provider_reported_model: str | None
    provider_request_id: str | None
    capture_method: CaptureMethod
    search_mode: str
    citation_count: int
    citation_lineage_hash: str
    search_event_count: int
    search_lineage_hash: str
    usage_details_hash: str
    raw_artifact_policy_hash: str
    raw_storage_decision: str
    raw_display_decision: str
    raw_retention_days: int | None
    response_hash: str | None
    output_hash: str | None
    observation_id: UUID | None
    observation_hash: str | None
    raw_artifact_manifest_hash: str | None
    derived_artifact_manifest_hash: str | None
    evidence_status: str | None
    location_evidence_hash: str | None
    error_code: str | None
    error_retryable: bool | None
    occurred_at: datetime

    def __post_init__(self) -> None:
        status = ProviderCanaryAttemptStatus(self.status)
        method = CaptureMethod(self.capture_method)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "capture_method", method)
        for uuid_value, label in (
            (self.sampling_attempt_id, "Sampling Attempt"),
            (self.durable_job_id, "Durable Job"),
            (self.model_call_attempt_id, "Model Call Attempt"),
            (self.task_id, "Sampling Task"),
        ):
            if uuid_value.int == 0:
                raise ProviderCanaryError(f"{label} ID cannot be zero")
        for hash_value, label in (
            (self.task_key, "task"),
            (self.adapter_release_hash, "adapter release"),
            (self.model_release_hash, "model release"),
            (self.citation_lineage_hash, "citation lineage"),
            (self.search_lineage_hash, "search lineage"),
            (self.usage_details_hash, "usage details"),
            (self.raw_artifact_policy_hash, "raw artifact policy"),
        ):
            _require_hash(hash_value, label)
        for optional_hash, label in (
            (self.response_hash, "response"),
            (self.output_hash, "output"),
            (self.observation_hash, "observation"),
            (self.raw_artifact_manifest_hash, "raw artifact manifest"),
            (self.derived_artifact_manifest_hash, "derived artifact manifest"),
            (self.location_evidence_hash, "location evidence"),
        ):
            if optional_hash is not None:
                _require_hash(optional_hash, label)
        if self.repetition < 1 or min(self.citation_count, self.search_event_count) < 0:
            raise ProviderCanaryError("canary repetition and lineage counts are invalid")
        if not self.question_id.strip() or not self.question_version.strip():
            raise ProviderCanaryError("canary question identity cannot be empty")
        if self.raw_storage_decision not in {"allowed", "prohibited"}:
            raise ProviderCanaryError("canary raw storage decision is invalid")
        if self.raw_display_decision not in {"allowed", "prohibited"}:
            raise ProviderCanaryError("canary raw display decision is invalid")
        if self.raw_retention_days is not None and self.raw_retention_days < 0:
            raise ProviderCanaryError("canary raw retention cannot be negative")
        _require_aware(self.occurred_at, "canary attempt time")
        if status is ProviderCanaryAttemptStatus.SUCCEEDED:
            required = (
                self.provider_reported_model,
                self.provider_request_id,
                self.response_hash,
                self.output_hash,
                self.observation_hash,
                self.raw_artifact_manifest_hash,
                self.derived_artifact_manifest_hash,
                self.evidence_status,
                self.location_evidence_hash,
            )
            if self.observation_id is None or any(value is None for value in required):
                raise ProviderCanaryError(
                    "successful canary attempts require complete observation lineage"
                )
            if self.error_code is not None or self.error_retryable is not None:
                raise ProviderCanaryError("successful canary attempt cannot carry an error")
        else:
            if self.observation_id is not None or self.observation_hash is not None:
                raise ProviderCanaryError("failed canary attempt cannot create an observation")
            if self.error_code is None or self.error_retryable is None:
                raise ProviderCanaryError("failed canary attempt requires classified error")

    @property
    def valid_observation(self) -> bool:
        return (
            self.status is ProviderCanaryAttemptStatus.SUCCEEDED
            and self.evidence_status == "complete"
        )

    def manifest_value(self) -> dict[str, object]:
        """Return an explicit allowlist; no prompt, answer, secret, URL or header fits."""

        return {
            "sampling_attempt_id": str(self.sampling_attempt_id),
            "durable_job_id": str(self.durable_job_id),
            "model_call_attempt_id": str(self.model_call_attempt_id),
            "task_id": str(self.task_id),
            "task_key": self.task_key,
            "question_id": self.question_id,
            "question_version": self.question_version,
            "repetition": self.repetition,
            "status": self.status.value,
            "provider": self.provider,
            "adapter_release_id": self.adapter_release_id,
            "adapter_release_hash": self.adapter_release_hash,
            "model_release_id": self.model_release_id,
            "model_release_hash": self.model_release_hash,
            "configured_model": self.configured_model,
            "provider_reported_model": self.provider_reported_model,
            "provider_request_id": self.provider_request_id,
            "capture_method": self.capture_method.value,
            "search_mode": self.search_mode,
            "citation_count": self.citation_count,
            "citation_lineage_hash": self.citation_lineage_hash,
            "search_event_count": self.search_event_count,
            "search_lineage_hash": self.search_lineage_hash,
            "usage_details_hash": self.usage_details_hash,
            "raw_artifact_policy_hash": self.raw_artifact_policy_hash,
            "raw_storage_decision": self.raw_storage_decision,
            "raw_display_decision": self.raw_display_decision,
            "raw_retention_days": self.raw_retention_days,
            "response_hash": self.response_hash,
            "output_hash": self.output_hash,
            "observation_id": str(self.observation_id) if self.observation_id else None,
            "observation_hash": self.observation_hash,
            "raw_artifact_manifest_hash": self.raw_artifact_manifest_hash,
            "derived_artifact_manifest_hash": self.derived_artifact_manifest_hash,
            "evidence_status": self.evidence_status,
            "location_evidence_hash": self.location_evidence_hash,
            "error_code": self.error_code,
            "error_retryable": self.error_retryable,
            "occurred_at": self.occurred_at.isoformat(),
        }


@dataclass(frozen=True)
class ProviderCanaryRunEvidence:
    project_id: UUID
    suite_id: UUID
    suite_hash: str
    run_id: UUID
    run_status: str
    purpose: str
    platform: str
    surface: str
    capture_method: CaptureMethod
    source_stratum_hash: str
    adapter_release_id: str
    adapter_release_hash: str
    model_release_id: str
    model_release_hash: str
    planned_tasks: tuple[ProviderCanaryPlannedTask, ...]
    calls: tuple[ProviderCanaryAttemptEvidence, ...]
    started_at: datetime
    completed_at: datetime
    denominator_hash: str = field(init=False)
    valid_task_count: int = field(init=False)
    invalid_task_count: int = field(init=False)
    missing_task_count: int = field(init=False)

    def __post_init__(self) -> None:
        method = CaptureMethod(self.capture_method)
        object.__setattr__(self, "capture_method", method)
        for uuid_value, label in (
            (self.project_id, "Project"),
            (self.suite_id, "Sampling Suite"),
            (self.run_id, "Sampling Run"),
        ):
            if uuid_value.int == 0:
                raise ProviderCanaryError(f"{label} ID cannot be zero")
        for hash_value, label in (
            (self.suite_hash, "suite"),
            (self.source_stratum_hash, "source stratum"),
            (self.adapter_release_hash, "adapter release"),
            (self.model_release_hash, "model release"),
        ):
            _require_hash(hash_value, label)
        planned_tasks = tuple(sorted(self.planned_tasks))
        planned = tuple(item.task_key for item in planned_tasks)
        calls = tuple(sorted(self.calls, key=lambda item: (item.task_key, item.occurred_at)))
        if not planned or len(planned) != len(set(planned)):
            raise ProviderCanaryError("canary denominator must be non-empty and unique")
        if any(_SHA256.fullmatch(value) is None for value in planned):
            raise ProviderCanaryError("canary task key must be lowercase SHA-256")
        if len({item.task_id for item in planned_tasks}) != len(planned_tasks):
            raise ProviderCanaryError("canary denominator has duplicate Task IDs")
        planned_by_key = {item.task_key: item for item in planned_tasks}
        repetitions: dict[tuple[str, str], set[int]] = {}
        for item in planned_tasks:
            repetitions.setdefault((item.question_id, item.question_version), set()).add(
                item.repetition
            )
        if any(values != set(range(1, 11)) for values in repetitions.values()):
            raise ProviderCanaryError("Provider canary requires repetitions 1 through 10")
        object.__setattr__(self, "planned_tasks", planned_tasks)
        object.__setattr__(self, "calls", calls)
        _require_aware(self.started_at, "canary start time")
        _require_aware(self.completed_at, "canary completion time")
        if self.completed_at < self.started_at:
            raise ProviderCanaryError("canary completion precedes its start")
        winning = [item for item in calls if item.observation_id is not None]
        if len({item.task_key for item in winning}) != len(winning):
            raise ProviderCanaryError("canary has duplicate winning Observations")
        if any(item.task_key not in planned for item in calls):
            raise ProviderCanaryError("canary call escaped the frozen denominator")
        if any(
            (
                call.task_id != planned_by_key[call.task_key].task_id
                or call.question_id != planned_by_key[call.task_key].question_id
                or call.question_version
                != planned_by_key[call.task_key].question_version
                or call.repetition != planned_by_key[call.task_key].repetition
            )
            for call in calls
        ):
            raise ProviderCanaryError("canary call differs from its planned Task identity")
        valid = sum(item.valid_observation for item in winning)
        invalid = len(winning) - valid
        missing = len(planned) - len(winning)
        if missing < 0:
            raise ProviderCanaryError("canary has more observations than planned slots")
        object.__setattr__(self, "valid_task_count", valid)
        object.__setattr__(self, "invalid_task_count", invalid)
        object.__setattr__(self, "missing_task_count", missing)
        object.__setattr__(self, "denominator_hash", canonical_hash(list(planned)))

    @property
    def planned_task_keys(self) -> tuple[str, ...]:
        return tuple(item.task_key for item in self.planned_tasks)


@dataclass(frozen=True)
class ProviderCanaryManifest:
    schema_version: int
    release_id: str
    release_hash: str
    project_id: UUID
    suite_id: UUID
    suite_hash: str
    run_id: UUID
    source_stratum_hash: str
    platform: str
    surface: str
    capture_method: str
    planned_tasks: tuple[dict[str, object], ...]
    planned_task_count: int
    valid_task_count: int
    invalid_task_count: int
    missing_task_count: int
    denominator_hash: str
    started_at: datetime
    completed_at: datetime
    calls: tuple[dict[str, object], ...]
    generated_at: datetime
    manifest_hash: str | None = None

    def calculate_hash(self) -> str:
        return _canonical_hash(self.value(include_hash=False))

    def with_hash(self) -> "ProviderCanaryManifest":
        from dataclasses import replace

        return replace(self, manifest_hash=self.calculate_hash())

    def value(self, *, include_hash: bool = True) -> dict[str, object]:
        value = {
            "schema_version": self.schema_version,
            "release_id": self.release_id,
            "release_hash": self.release_hash,
            "project_id": str(self.project_id),
            "suite_id": str(self.suite_id),
            "suite_hash": self.suite_hash,
            "run_id": str(self.run_id),
            "source_stratum_hash": self.source_stratum_hash,
            "platform": self.platform,
            "surface": self.surface,
            "capture_method": self.capture_method,
            "planned_tasks": list(self.planned_tasks),
            "planned_task_count": self.planned_task_count,
            "valid_task_count": self.valid_task_count,
            "invalid_task_count": self.invalid_task_count,
            "missing_task_count": self.missing_task_count,
            "denominator_hash": self.denominator_hash,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "calls": list(self.calls),
            "generated_at": self.generated_at.isoformat(),
        }
        if include_hash:
            value["manifest_hash"] = self.manifest_hash
        return value


def build_provider_canary_manifest(
    release: ProviderSamplingRelease,
    run: ProviderCanaryRunEvidence,
    *,
    generated_at: datetime,
) -> ProviderCanaryManifest:
    """Fail closed unless a completed ten-repeat live run proves the release."""

    _require_aware(generated_at, "canary manifest generation time")
    if generated_at < run.completed_at:
        raise ProviderCanaryError("canary manifest predates Run completion")
    try:
        require_canonical_provider_source(
            gateway_provider=release.gateway_provider,
            platform=run.platform,
            surface=run.surface,
            capture_method=run.capture_method,
        )
    except Exception as exc:
        raise ProviderCanaryError("canary source differs from Provider release") from exc
    if run.run_status != "completed" or run.purpose != "provider_live_canary":
        raise ProviderCanaryError("live canary requires a completed dedicated Sampling Run")
    if run.valid_task_count * 5 < len(run.planned_task_keys) * 4:
        raise ProviderCanaryError("Provider canary has less than 80% valid completion")
    valid_by_question = Counter(
        item.question_id for item in run.calls if item.valid_observation
    )
    question_ids = {item.question_id for item in run.planned_tasks}
    if not question_ids or any(valid_by_question[item] < 8 for item in question_ids):
        raise ProviderCanaryError("each Provider canary question needs eight valid repeats")
    if (
        run.adapter_release_id != release.adapter_release_id
        or run.adapter_release_hash != release.adapter_release_hash
        or run.model_release_id != release.model_release_id
        or run.model_release_hash != release.model_release_hash
    ):
        raise ProviderCanaryError("canary route release differs from frozen release")
    for call in run.calls:
        _validate_call(release, run, call)
    return ProviderCanaryManifest(
        schema_version=1,
        release_id=release.release_id,
        release_hash=release.release_hash,
        project_id=run.project_id,
        suite_id=run.suite_id,
        suite_hash=run.suite_hash,
        run_id=run.run_id,
        source_stratum_hash=run.source_stratum_hash,
        platform=run.platform,
        surface=run.surface,
        capture_method=run.capture_method.value,
        planned_tasks=tuple(item.manifest_value() for item in run.planned_tasks),
        planned_task_count=len(run.planned_task_keys),
        valid_task_count=run.valid_task_count,
        invalid_task_count=run.invalid_task_count,
        missing_task_count=run.missing_task_count,
        denominator_hash=run.denominator_hash,
        started_at=run.started_at,
        completed_at=run.completed_at,
        calls=tuple(item.manifest_value() for item in run.calls),
        generated_at=generated_at,
    ).with_hash()


def _validate_call(
    release: ProviderSamplingRelease,
    run: ProviderCanaryRunEvidence,
    call: ProviderCanaryAttemptEvidence,
) -> None:
    if (
        call.provider != release.gateway_provider
        or call.adapter_release_id != release.adapter_release_id
        or call.adapter_release_hash != release.adapter_release_hash
        or call.model_release_id != release.model_release_id
        or call.model_release_hash != release.model_release_hash
        or call.configured_model != release.configured_model
        or call.capture_method is not run.capture_method
        or call.search_mode != release.search_mode
        or call.raw_artifact_policy_hash != release.data_policy_hash
        or call.raw_storage_decision != release.raw_storage_decision
        or call.raw_display_decision != release.raw_display_decision
        or call.raw_retention_days != release.raw_retention_days
    ):
        raise ProviderCanaryError("canary call differs from frozen Provider release")
    if call.status is ProviderCanaryAttemptStatus.FAILED:
        return
    if not release.accepts_reported_model(call.provider_reported_model):
        raise ProviderCanaryError("provider-reported model violates the frozen policy")
    if call.location_evidence_hash is None:
        raise ProviderCanaryError("successful canary call lacks location lineage")
    if release.search_mode != "disabled":
        if call.search_event_count < 1 or call.citation_count < 1:
            raise ProviderCanaryError("grounded canary lacks search/citation lineage")
    elif call.search_event_count or call.citation_count:
        raise ProviderCanaryError("search-disabled canary unexpectedly reports search lineage")
    if release.gateway_provider == "microsoft" and call.citation_count < 2:
        raise ProviderCanaryError("Microsoft canary lacks required display/query citations")


def verify_provider_canary_manifest(
    value: Mapping[str, object], release: ProviderSamplingRelease
) -> str:
    """Rebuild a serialized canary against its independently supplied release."""

    from geo_core.sampling.provider_canary_verification import (
        verify_provider_canary_manifest_value,
    )

    return verify_provider_canary_manifest_value(value, release)


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_hash(value: str, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ProviderCanaryError(f"{label} hash must be lowercase SHA-256")


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderCanaryError(f"{label} must include a timezone")


__all__ = [
    "ProviderCanaryAttemptEvidence",
    "ProviderCanaryAttemptStatus",
    "ProviderCanaryError",
    "ProviderCanaryManifest",
    "ProviderCanaryPlannedTask",
    "ProviderCanaryRunEvidence",
    "build_provider_canary_manifest",
    "verify_provider_canary_manifest",
]
