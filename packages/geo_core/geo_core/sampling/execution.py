"""Sampling Attempt, safe Job/Outbox command and Observation evidence contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping
from uuid import UUID, uuid5

from geo_core.jobs import DomainJobSpec, DurableJob, JobStatus
from geo_core.sampling.contracts import (
    CaptureMethod,
    EvidenceStatus,
    LocationControl,
    SHA256_PATTERN,
    SamplingRuleViolation,
    SamplingSourceStratum,
    SamplingTaskIdentity,
    canonical_hash,
    _require_aware,
    _text,
)


SAMPLING_OUTBOX_NAMESPACE = UUID("a377ee93-22c7-586a-ac6a-0dc82a09ebee")
SAMPLING_OBSERVATION_NAMESPACE = UUID("064d61e9-5816-56b8-81a9-45f47ace8cb0")


class AttemptTerminalStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ObservationArtifactKind(StrEnum):
    RAW = "raw"
    DERIVED = "derived"


@dataclass(frozen=True)
class SamplingActualLocationLineage:
    location_control: LocationControl
    location_evidence_hash: str
    requested_country: str | None
    requested_region: str | None
    requested_locale: str
    requested_language: str
    effective_country: str | None
    effective_region: str | None
    effective_locale: str | None
    effective_language: str | None

    def __post_init__(self) -> None:
        control = LocationControl(self.location_control)
        if not SHA256_PATTERN.fullmatch(self.location_evidence_hash):
            raise SamplingRuleViolation("actual location evidence must be SHA-256")
        requested_locale = _text(self.requested_locale, "actual requested locale")
        requested_language = _text(self.requested_language, "actual requested language")
        requested_country = _optional_location(self.requested_country)
        requested_region = _optional_location(self.requested_region)
        effective_country = _optional_location(self.effective_country)
        effective_region = _optional_location(self.effective_region)
        effective_locale = _optional_location(self.effective_locale)
        effective_language = _optional_location(self.effective_language)
        effective = (
            effective_country,
            effective_region,
            effective_locale,
            effective_language,
        )
        if control is LocationControl.COUNTRY:
            valid = effective_country is not None and all(
                value is None for value in effective[1:]
            )
        elif control is LocationControl.MARKET_LANGUAGE:
            valid = (
                effective_country is None
                and effective_region is None
                and effective_locale is not None
                and effective_language is not None
            )
        elif control is LocationControl.LANGUAGE_ONLY:
            valid = effective_language is not None and all(
                value is None for value in effective[:3]
            )
        else:
            valid = all(value is None for value in effective)
        if not valid:
            raise SamplingRuleViolation("actual location values differ from their control")
        object.__setattr__(self, "location_control", control)
        object.__setattr__(self, "requested_country", requested_country)
        object.__setattr__(self, "requested_region", requested_region)
        object.__setattr__(self, "requested_locale", requested_locale)
        object.__setattr__(self, "requested_language", requested_language)
        object.__setattr__(self, "effective_country", effective_country)
        object.__setattr__(self, "effective_region", effective_region)
        object.__setattr__(self, "effective_locale", effective_locale)
        object.__setattr__(self, "effective_language", effective_language)

    def canonical_value(self) -> dict[str, object]:
        return {
            "location_control": self.location_control.value,
            "location_evidence_hash": self.location_evidence_hash,
            "requested_country": self.requested_country,
            "requested_region": self.requested_region,
            "requested_locale": self.requested_locale,
            "requested_language": self.requested_language,
            "effective_country": self.effective_country,
            "effective_region": self.effective_region,
            "effective_locale": self.effective_locale,
            "effective_language": self.effective_language,
        }


@dataclass(frozen=True)
class SamplingJobCommand:
    project_id: UUID
    run_id: UUID
    task_id: UUID
    task_key: str
    attempt_id: UUID
    capture_method: CaptureMethod
    adapter_release: str
    question_id: str
    question_version: str
    location_control: LocationControl
    location_evidence_hash: str
    requested_country: str | None
    requested_region: str | None
    requested_locale: str
    requested_language: str
    effective_country: str | None
    effective_region: str | None
    effective_locale: str | None
    effective_language: str | None
    not_before: datetime
    command_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "capture_method", CaptureMethod(self.capture_method))
        object.__setattr__(self, "location_control", LocationControl(self.location_control))
        for digest in (self.task_key,):
            if not SHA256_PATTERN.fullmatch(digest):
                raise SamplingRuleViolation("sampling Job Task key must be SHA-256")
        if not SHA256_PATTERN.fullmatch(self.location_evidence_hash):
            raise SamplingRuleViolation("sampling Job location evidence must be SHA-256")
        for name in ("adapter_release", "question_id", "question_version"):
            object.__setattr__(self, name, _text(getattr(self, name), f"Job {name}"))
        _require_aware(self.not_before, "sampling Job not_before")
        object.__setattr__(self, "command_hash", canonical_hash(dict(self.payload())))

    def payload(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "project_id": str(self.project_id),
                "run_id": str(self.run_id),
                "task_id": str(self.task_id),
                "task_key": self.task_key,
                "attempt_id": str(self.attempt_id),
                "capture_method": self.capture_method.value,
                "adapter_release": self.adapter_release,
                "question_id": self.question_id,
                "question_version": self.question_version,
                "location_control": self.location_control.value,
                "location_evidence_hash": self.location_evidence_hash,
                "requested_country": self.requested_country,
                "requested_region": self.requested_region,
                "requested_locale": self.requested_locale,
                "requested_language": self.requested_language,
                "effective_country": self.effective_country,
                "effective_region": self.effective_region,
                "effective_locale": self.effective_locale,
                "effective_language": self.effective_language,
                "not_before": self.not_before.isoformat(),
            }
        )


@dataclass(frozen=True)
class SamplingOutboxMessage:
    id: UUID
    project_id: UUID
    job_id: UUID
    topic: str
    payload: Mapping[str, object]
    idempotency_key: str
    payload_hash: str

    def __post_init__(self) -> None:
        topic = _text(self.topic, "sampling Outbox topic")
        key = _text(self.idempotency_key, "sampling Outbox idempotency key")
        payload = MappingProxyType(dict(self.payload))
        if self.payload_hash != canonical_hash(dict(payload)):
            raise SamplingRuleViolation("sampling Outbox payload hash is inconsistent")
        if self.id != uuid5(SAMPLING_OUTBOX_NAMESPACE, key):
            raise SamplingRuleViolation("sampling Outbox id must be deterministic")
        allowed = {
            "project_id",
            "run_id",
            "task_id",
            "task_key",
            "attempt_id",
            "capture_method",
            "adapter_release",
            "question_id",
            "question_version",
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
            "not_before",
        }
        if set(payload) != allowed:
            raise SamplingRuleViolation("sampling Outbox payload violates the safe whitelist")
        object.__setattr__(self, "topic", topic)
        object.__setattr__(self, "idempotency_key", key)
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True)
class SamplingAttempt:
    id: UUID
    project_id: UUID
    run_id: UUID
    task_id: UUID
    task_key: str
    ordinal: int
    job: DurableJob
    # In-memory construction uses the Attempt ID as the Job ID.  PostgreSQL
    # uses the durable producer's Job ID and persists that one-to-one link.
    durable_job_id: UUID | None = None
    record_version: int = 1
    provider_response_id: str | None = None
    egress_verification_id: str | None = None
    raw_artifact_hash: str | None = None
    actual_location: SamplingActualLocationLineage | None = None
    terminal_status: AttemptTerminalStatus | None = None

    def __post_init__(self) -> None:
        if not SHA256_PATTERN.fullmatch(self.task_key):
            raise SamplingRuleViolation("Attempt Task key must be SHA-256")
        if self.ordinal < 1 or self.record_version < 1:
            raise SamplingRuleViolation("Attempt ordinal and version must be positive")
        durable_job_id = self.durable_job_id or self.job.id
        if self.job.id != durable_job_id or self.job.project_id != self.project_id:
            raise SamplingRuleViolation("Attempt must own its one-to-one Durable Job")
        object.__setattr__(self, "durable_job_id", durable_job_id)
        payload = self.job.spec.payload
        if (
            payload.get("run_id") != str(self.run_id)
            or payload.get("task_id") != str(self.task_id)
            or payload.get("task_key") != self.task_key
            or payload.get("attempt_id") != str(self.id)
        ):
            raise SamplingRuleViolation("Attempt Durable Job payload has different lineage")
        for name in ("provider_response_id", "egress_verification_id"):
            value = getattr(self, name)
            object.__setattr__(self, name, value.strip() if value and value.strip() else None)
        if self.raw_artifact_hash is not None and not SHA256_PATTERN.fullmatch(
            self.raw_artifact_hash
        ):
            raise SamplingRuleViolation("Attempt raw artifact hash must be SHA-256")
        if self.terminal_status is not None:
            terminal = AttemptTerminalStatus(self.terminal_status)
            expected = {
                AttemptTerminalStatus.SUCCEEDED: JobStatus.SUCCEEDED,
                AttemptTerminalStatus.FAILED: (JobStatus.FAILED, JobStatus.DEAD_LETTERED),
                AttemptTerminalStatus.CANCELLED: JobStatus.CANCELLED,
            }[terminal]
            expected_statuses = expected if isinstance(expected, tuple) else (expected,)
            if self.job.status not in expected_statuses:
                raise SamplingRuleViolation("Attempt terminal status differs from Durable Job")
            object.__setattr__(self, "terminal_status", terminal)


@dataclass(frozen=True)
class ObservationArtifactManifest:
    kind: ObservationArtifactKind
    manifest_reference: str
    manifest_hash: str
    content_hash: str
    governance_policy_hash: str

    def __post_init__(self) -> None:
        try:
            kind = ObservationArtifactKind(self.kind)
        except ValueError as error:
            raise SamplingRuleViolation("Observation artifact kind is unsupported") from error
        reference = self.manifest_reference.strip()
        if not reference or len(reference) > 2000:
            raise SamplingRuleViolation("Observation artifact manifest reference is invalid")
        for digest in (
            self.manifest_hash,
            self.content_hash,
            self.governance_policy_hash,
        ):
            if not SHA256_PATTERN.fullmatch(digest):
                raise SamplingRuleViolation("Observation artifact hash must be SHA-256")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "manifest_reference", reference)

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "manifest_reference": self.manifest_reference,
            "manifest_hash": self.manifest_hash,
            "content_hash": self.content_hash,
            "governance_policy_hash": self.governance_policy_hash,
        }


@dataclass(frozen=True)
class ObservationEvidence:
    raw_artifact: ObservationArtifactManifest
    derived_artifact: ObservationArtifactManifest
    derived_summary: str
    evidence_locator: str
    provider_response_id: str | None
    egress_verification_id: str | None
    result_parameters_hash: str
    storage_decision: str
    cache_decision: str
    display_decision: str
    redistribution_decision: str
    usage_purpose: str
    usage_audience: str

    def __post_init__(self) -> None:
        if self.raw_artifact.kind is not ObservationArtifactKind.RAW:
            raise SamplingRuleViolation("Observation raw artifact manifest kind is invalid")
        if self.derived_artifact.kind is not ObservationArtifactKind.DERIVED:
            raise SamplingRuleViolation("Observation derived artifact manifest kind is invalid")
        summary = self.derived_summary.strip()
        if not summary or len(summary) > 280:
            raise SamplingRuleViolation("Observation derived summary is required and bounded")
        locator = self.evidence_locator.strip()
        if not locator or len(locator) > 500:
            raise SamplingRuleViolation("Observation evidence locator is required and bounded")
        if not SHA256_PATTERN.fullmatch(self.result_parameters_hash):
            raise SamplingRuleViolation("Observation result parameters hash is required")
        for decision in (
            self.storage_decision,
            self.cache_decision,
            self.display_decision,
            self.redistribution_decision,
        ):
            if decision not in {"allowed", "prohibited"}:
                raise SamplingRuleViolation("Observation data-policy decision is invalid")
        if not self.usage_purpose.strip() or self.usage_audience not in {
            "internal_worker",
            "admin",
            "customer",
            "export",
        }:
            raise SamplingRuleViolation("Observation usage purpose/audience is invalid")
        provider_response_id = (
            self.provider_response_id.strip()
            if self.provider_response_id and self.provider_response_id.strip()
            else None
        )
        egress_verification_id = (
            self.egress_verification_id.strip()
            if self.egress_verification_id and self.egress_verification_id.strip()
            else None
        )
        object.__setattr__(self, "derived_summary", summary)
        object.__setattr__(self, "evidence_locator", locator)
        object.__setattr__(self, "provider_response_id", provider_response_id)
        object.__setattr__(self, "egress_verification_id", egress_verification_id)

    def canonical_value(self) -> dict[str, object]:
        return {
            "raw_artifact": self.raw_artifact.canonical_value(),
            "derived_artifact": self.derived_artifact.canonical_value(),
            "derived_summary": self.derived_summary,
            "evidence_locator": self.evidence_locator,
            "provider_response_id": self.provider_response_id,
            "egress_verification_id": self.egress_verification_id,
            "result_parameters_hash": self.result_parameters_hash,
            "storage_decision": self.storage_decision,
            "cache_decision": self.cache_decision,
            "display_decision": self.display_decision,
            "redistribution_decision": self.redistribution_decision,
            "usage_purpose": self.usage_purpose,
            "usage_audience": self.usage_audience,
        }


@dataclass(frozen=True)
class SamplingObservation:
    id: UUID
    project_id: UUID
    run_id: UUID
    task_id: UUID
    task_key: str
    winning_attempt_id: UUID
    source_stratum: SamplingSourceStratum
    source_stratum_hash: str
    evidence_status: EvidenceStatus
    ineligible_reasons: tuple[str, ...]
    evidence: ObservationEvidence
    observed_at: datetime
    actual_location: SamplingActualLocationLineage | None = None
    observation_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.source_stratum_hash != self.source_stratum.stratum_hash:
            raise SamplingRuleViolation("Observation SourceStratum hash is inconsistent")
        if not SHA256_PATTERN.fullmatch(self.task_key):
            raise SamplingRuleViolation("Observation Task key must be SHA-256")
        status = EvidenceStatus(self.evidence_status)
        reasons = tuple(
            sorted({_text(item, "ineligible reason") for item in self.ineligible_reasons})
        )
        if (status is EvidenceStatus.COMPLETE) == bool(reasons):
            raise SamplingRuleViolation("Observation eligibility and reasons are inconsistent")
        _require_aware(self.observed_at, "Observation time")
        object.__setattr__(self, "evidence_status", status)
        object.__setattr__(self, "ineligible_reasons", reasons)
        object.__setattr__(self, "observation_hash", canonical_hash(self.canonical_value()))

    @property
    def included_in_metrics(self) -> bool:
        return self.evidence_status is EvidenceStatus.COMPLETE

    def canonical_value(self) -> dict[str, object]:
        return {
            "project_id": str(self.project_id),
            "run_id": str(self.run_id),
            "task_id": str(self.task_id),
            "task_key": self.task_key,
            "winning_attempt_id": str(self.winning_attempt_id),
            "source_stratum": self.source_stratum.canonical_value(),
            "source_stratum_hash": self.source_stratum_hash,
            "actual_location": (
                self.actual_location.canonical_value() if self.actual_location else None
            ),
            "evidence_status": self.evidence_status.value,
            "ineligible_reasons": list(self.ineligible_reasons),
            "evidence": self.evidence.canonical_value(),
            "observed_at": self.observed_at.isoformat(),
        }


def build_sampling_job(
    *,
    command: SamplingJobCommand,
    max_attempts: int = 1,
) -> tuple[DurableJob, SamplingOutboxMessage]:
    topic = (
        "sampling.manual_import"
        if command.capture_method is CaptureMethod.MANUAL_UI
        else "sampling.provider_execute"
    )
    job_key = f"sampling-attempt:{command.attempt_id}"
    job = DurableJob(
        id=command.attempt_id,
        project_id=command.project_id,
        spec=DomainJobSpec(kind=topic, payload=command.payload()),
        input_hash=command.command_hash,
        idempotency_key=job_key,
        max_attempts=max_attempts,
        next_run_at=command.not_before,
    )
    outbox_key = f"wake:{job_key}"
    payload = command.payload()
    outbox = SamplingOutboxMessage(
        id=uuid5(SAMPLING_OUTBOX_NAMESPACE, outbox_key),
        project_id=command.project_id,
        job_id=job.id,
        topic=topic,
        payload=payload,
        idempotency_key=outbox_key,
        payload_hash=canonical_hash(dict(payload)),
    )
    return job, outbox


def observation_id(
    identity: SamplingTaskIdentity,
    *,
    attempt_id: UUID,
    evidence: ObservationEvidence,
    actual_location: SamplingActualLocationLineage | None = None,
) -> UUID:
    value = canonical_hash(
        {
            "task_key": identity.task_key,
            "attempt_id": str(attempt_id),
            "evidence": evidence.canonical_value(),
            "actual_location": (
                actual_location.canonical_value() if actual_location else None
            ),
        }
    )
    return uuid5(SAMPLING_OBSERVATION_NAMESPACE, value)


def _optional_location(value: str | None) -> str | None:
    return _text(value, "actual location") if value is not None else None
