"""Frozen Sampling Suite, SourceStratum, Run and Task identity contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
import re
from uuid import UUID, uuid5


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SAMPLING_TASK_NAMESPACE = UUID("710839f6-c592-533f-9ae0-33ed5f3e6c74")


class SamplingRuleViolation(ValueError):
    """A sampling command violates a frozen domain rule."""


class SamplingConflict(RuntimeError):
    """A sampling idempotency or optimistic-version check failed."""


class SamplingNotFound(RuntimeError):
    """A project-scoped sampling resource does not exist."""


class CaptureMethod(StrEnum):
    PROVIDER_API = "provider_api"
    PROXY_GROUNDED_API = "proxy_grounded_api"
    MANUAL_UI = "manual_ui"
    AUTOMATED_UI = "automated_ui"


class LocationControl(StrEnum):
    COUNTRY = "country"
    MARKET_LANGUAGE = "market_language"
    LANGUAGE_ONLY = "language_only"
    NOT_CONTROLLED = "not_controlled"


SUPPORTED_CAPTURE_METHODS = frozenset(
    {
        CaptureMethod.PROVIDER_API,
        CaptureMethod.PROXY_GROUNDED_API,
        CaptureMethod.MANUAL_UI,
        CaptureMethod.AUTOMATED_UI,
    }
)


class SamplingRunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SamplingTaskStatus(StrEnum):
    PLANNED = "planned"
    QUEUED = "queued"
    RUNNING = "running"
    FINALIZING = "finalizing"
    RETRY_READY = "retry_ready"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


class EvidenceStatus(StrEnum):
    COMPLETE = "complete"
    INELIGIBLE = "ineligible"


class RunEvidenceStatus(StrEnum):
    COMPLETE = "complete"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, order=True)
class SamplingQuestion:
    question_id: str
    question_version: str
    text_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "question_id", _text(self.question_id, "question id"))
        object.__setattr__(
            self, "question_version", _text(self.question_version, "question version")
        )
        if not SHA256_PATTERN.fullmatch(self.text_hash):
            raise SamplingRuleViolation("question text hash must be SHA-256")


@dataclass(frozen=True)
class SamplingSourceStratum:
    platform: str
    surface: str
    configured_model: str
    reported_model: str
    capture_method: CaptureMethod
    adapter_release: str
    locale: str
    region: str
    language: str
    search_mode: str
    account_cohort: str
    egress_policy_category: str
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
    stratum_hash: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            capture_method = CaptureMethod(self.capture_method)
        except ValueError as error:
            raise SamplingRuleViolation("capture method is unsupported") from error
        if capture_method not in SUPPORTED_CAPTURE_METHODS:
            raise SamplingRuleViolation("capture method is unsupported")
        try:
            location_control = LocationControl(self.location_control)
        except ValueError as error:
            raise SamplingRuleViolation("location control is unsupported") from error
        for name in (
            "platform",
            "surface",
            "configured_model",
            "reported_model",
            "adapter_release",
            "locale",
            "region",
            "language",
            "search_mode",
            "account_cohort",
            "egress_policy_category",
            "requested_locale",
            "requested_language",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), f"stratum {name}"))
        if capture_method in {
            CaptureMethod.PROVIDER_API,
            CaptureMethod.PROXY_GROUNDED_API,
        }:
            if self.account_cohort != "not_applicable":
                raise SamplingRuleViolation("API strata require account_cohort=not_applicable")
            if self.egress_policy_category != "not_applicable":
                raise SamplingRuleViolation(
                    "API strata require egress_policy_category=not_applicable"
                )
        elif capture_method is CaptureMethod.AUTOMATED_UI:
            if self.configured_model != "not_applicable" or self.reported_model != "not_applicable":
                raise SamplingRuleViolation("automated UI strata cannot claim a model identity")
            if self.account_cohort not in {"clean_anonymous", "managed_test_account"}:
                raise SamplingRuleViolation("automated UI strata require a frozen account cohort")
            if self.egress_policy_category == "not_applicable":
                raise SamplingRuleViolation("automated UI strata require a frozen egress cohort")
        if not SHA256_PATTERN.fullmatch(self.location_evidence_hash):
            raise SamplingRuleViolation("location capability evidence hash must be SHA-256")
        requested_country = _optional_geo(self.requested_country)
        requested_region = _optional_geo(self.requested_region)
        effective_country = _optional_geo(self.effective_country)
        effective_region = _optional_geo(self.effective_region)
        effective_locale = _optional_geo(self.effective_locale)
        effective_language = _optional_geo(self.effective_language)
        if location_control is LocationControl.COUNTRY:
            if effective_country is None or effective_region is not None:
                raise SamplingRuleViolation("country control requires only effective country")
            if requested_country is not None and requested_country != effective_country:
                raise SamplingRuleViolation("effective country differs from requested country")
            if self.region != effective_country:
                raise SamplingRuleViolation("country-controlled stratum must use effective country")
        elif location_control is LocationControl.MARKET_LANGUAGE:
            if (
                effective_country is not None
                or effective_region is not None
                or effective_locale is None
                or effective_language is None
            ):
                raise SamplingRuleViolation("market-language control has invalid effective geo")
            if self.region != LocationControl.NOT_CONTROLLED.value:
                raise SamplingRuleViolation("market-language stratum cannot claim a region")
        elif location_control is LocationControl.LANGUAGE_ONLY:
            if any(
                value is not None
                for value in (effective_country, effective_region, effective_locale)
            ) or effective_language is None:
                raise SamplingRuleViolation("language-only control has invalid effective geo")
            if self.region != LocationControl.NOT_CONTROLLED.value:
                raise SamplingRuleViolation("language-only stratum cannot claim a region")
        elif any(
            value is not None
            for value in (
                effective_country,
                effective_region,
                effective_locale,
                effective_language,
            )
        ) or self.region != LocationControl.NOT_CONTROLLED.value:
            raise SamplingRuleViolation("uncontrolled location must use a separate stratum")
        object.__setattr__(self, "capture_method", capture_method)
        object.__setattr__(self, "location_control", location_control)
        object.__setattr__(self, "requested_country", requested_country)
        object.__setattr__(self, "requested_region", requested_region)
        object.__setattr__(self, "effective_country", effective_country)
        object.__setattr__(self, "effective_region", effective_region)
        object.__setattr__(self, "effective_locale", effective_locale)
        object.__setattr__(self, "effective_language", effective_language)
        object.__setattr__(self, "stratum_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "platform": self.platform,
            "surface": self.surface,
            "configured_model": self.configured_model,
            "reported_model": self.reported_model,
            "capture_method": self.capture_method.value,
            "adapter_release": self.adapter_release,
            "locale": self.locale,
            "region": self.region,
            "language": self.language,
            "search_mode": self.search_mode,
            "account_cohort": self.account_cohort,
            "egress_policy_category": self.egress_policy_category,
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
class SamplingSuite:
    id: UUID
    project_id: UUID
    question_set_id: UUID
    question_set_version: str
    question_set_hash: str
    adapter_release_id: UUID
    adapter_release_hash: str
    model_release_id: UUID
    model_release_hash: str
    route_policy_id: UUID
    route_policy_hash: str
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    admission_policy_id: UUID
    admission_policy_hash: str
    questions: tuple[SamplingQuestion, ...]
    source_stratum: SamplingSourceStratum
    repetitions: int
    statistics_method_version: str
    max_planned_tasks: int
    max_daily_tasks: int
    minimum_request_interval_seconds: int
    max_concurrency: int
    frozen_by: str
    frozen_at: datetime
    minimum_valid_repeats: int = field(init=False)
    planned_task_count: int = field(init=False)
    suite_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for digest in (
            self.question_set_hash,
            self.adapter_release_hash,
            self.model_release_hash,
            self.route_policy_hash,
            self.runtime_manifest_hash,
            self.runtime_option_hash,
            self.admission_policy_hash,
        ):
            if not SHA256_PATTERN.fullmatch(digest):
                raise SamplingRuleViolation("Suite selector hashes must be SHA-256")
        object.__setattr__(
            self,
            "question_set_version",
            _text(self.question_set_version, "QuestionSet version"),
        )
        questions = tuple(sorted(self.questions))
        if not questions or len({item.question_id for item in questions}) != len(questions):
            raise SamplingRuleViolation("Suite questions must be non-empty and unique")
        capture = self.source_stratum.capture_method
        if capture in {CaptureMethod.PROVIDER_API, CaptureMethod.PROXY_GROUNDED_API}:
            if self.repetitions != 10:
                raise SamplingRuleViolation("API sampling freezes exactly 10 default repeats")
        elif self.repetitions < 3:
            raise SamplingRuleViolation("UI sampling requires at least three repeats")
        planned_count = len(questions) * self.repetitions
        minimum_valid = max(3, (4 * self.repetitions + 4) // 5)
        if self.max_planned_tasks < planned_count or self.max_daily_tasks < 1:
            raise SamplingRuleViolation("Suite throughput budget cannot fit planned tasks")
        if self.minimum_request_interval_seconds < 0 or self.max_concurrency < 1:
            raise SamplingRuleViolation("Suite rate and concurrency budget is invalid")
        _require_aware(self.frozen_at, "Suite frozen time")
        object.__setattr__(
            self,
            "statistics_method_version",
            _text(self.statistics_method_version, "statistics method version"),
        )
        object.__setattr__(self, "frozen_by", _text(self.frozen_by, "Suite freezer"))
        object.__setattr__(self, "questions", questions)
        object.__setattr__(self, "minimum_valid_repeats", minimum_valid)
        object.__setattr__(self, "planned_task_count", planned_count)
        object.__setattr__(self, "suite_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "project_id": str(self.project_id),
            "question_set_id": str(self.question_set_id),
            "question_set_version": self.question_set_version,
            "question_set_hash": self.question_set_hash,
            "adapter_release_id": str(self.adapter_release_id),
            "adapter_release_hash": self.adapter_release_hash,
            "model_release_id": str(self.model_release_id),
            "model_release_hash": self.model_release_hash,
            "route_policy_id": str(self.route_policy_id),
            "route_policy_hash": self.route_policy_hash,
            "runtime_manifest_id": str(self.runtime_manifest_id),
            "runtime_manifest_hash": self.runtime_manifest_hash,
            "runtime_option_id": str(self.runtime_option_id),
            "runtime_option_hash": self.runtime_option_hash,
            "admission_policy_id": str(self.admission_policy_id),
            "admission_policy_hash": self.admission_policy_hash,
            "questions": [
                {
                    "question_id": item.question_id,
                    "question_version": item.question_version,
                    "text_hash": item.text_hash,
                }
                for item in self.questions
            ],
            "source_stratum": self.source_stratum.canonical_value(),
            "repetitions": self.repetitions,
            "statistics_method_version": self.statistics_method_version,
            "max_planned_tasks": self.max_planned_tasks,
            "max_daily_tasks": self.max_daily_tasks,
            "minimum_request_interval_seconds": self.minimum_request_interval_seconds,
            "max_concurrency": self.max_concurrency,
            "minimum_valid_repeats": self.minimum_valid_repeats,
        }


@dataclass(frozen=True, order=True)
class SamplingTaskIdentity:
    suite_id: UUID
    suite_hash: str
    platform: str
    question_id: str
    question_version: str
    repetition: int
    region: str
    language: str
    capture_method: CaptureMethod
    adapter_release: str
    account_cohort: str
    egress_policy_category: str
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
    source_stratum_hash: str
    task_key: str = field(init=False, compare=False)
    task_id: UUID = field(init=False, compare=False)

    def __post_init__(self) -> None:
        try:
            capture_method = CaptureMethod(self.capture_method)
        except ValueError as error:
            raise SamplingRuleViolation("Task capture method is unsupported") from error
        if capture_method not in SUPPORTED_CAPTURE_METHODS:
            raise SamplingRuleViolation("Task capture method is unsupported")
        for digest in (
            self.suite_hash,
            self.source_stratum_hash,
            self.location_evidence_hash,
        ):
            if not SHA256_PATTERN.fullmatch(digest):
                raise SamplingRuleViolation("Task lineage hash must be SHA-256")
        if self.repetition < 1:
            raise SamplingRuleViolation("Task repetition must be positive")
        for name in (
            "platform",
            "question_id",
            "question_version",
            "region",
            "language",
            "adapter_release",
            "account_cohort",
            "egress_policy_category",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), f"Task {name}"))
        object.__setattr__(self, "capture_method", capture_method)
        object.__setattr__(self, "location_control", LocationControl(self.location_control))
        task_key = canonical_hash(self.canonical_value())
        object.__setattr__(self, "task_key", task_key)
        object.__setattr__(self, "task_id", uuid5(SAMPLING_TASK_NAMESPACE, task_key))

    def canonical_value(self) -> dict[str, object]:
        return {
            "suite_id": str(self.suite_id),
            "suite_hash": self.suite_hash,
            "platform": self.platform,
            "question_id": self.question_id,
            "question_version": self.question_version,
            "repetition": self.repetition,
            "region": self.region,
            "language": self.language,
            "capture_method": self.capture_method.value,
            "adapter_release": self.adapter_release,
            "account_cohort": self.account_cohort,
            "egress_policy_category": self.egress_policy_category,
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
            "source_stratum_hash": self.source_stratum_hash,
        }


@dataclass(frozen=True)
class SamplingRun:
    id: UUID
    project_id: UUID
    suite_id: UUID
    suite_hash: str
    admission_policy_id: UUID
    admission_policy_hash: str
    admission_grant_hash: str
    purpose: str
    authorization_reference: str
    authorization_valid_until: datetime
    admission_policy_version: str
    reserved_task_count: int
    planned_task_keys: tuple[str, ...]
    status: SamplingRunStatus
    admitted_not_before: datetime
    created_at: datetime
    version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", SamplingRunStatus(self.status))
        for digest in (
            self.suite_hash,
            self.admission_policy_hash,
            self.admission_grant_hash,
        ):
            if not SHA256_PATTERN.fullmatch(digest):
                raise SamplingRuleViolation("Run lineage hash must be SHA-256")
        for name in ("purpose", "authorization_reference", "admission_policy_version"):
            object.__setattr__(self, name, _text(getattr(self, name), f"Run {name}"))
        if not self.planned_task_keys or len(set(self.planned_task_keys)) != len(
            self.planned_task_keys
        ):
            raise SamplingRuleViolation("Run planned Task inventory must be non-empty and unique")
        if any(not SHA256_PATTERN.fullmatch(item) for item in self.planned_task_keys):
            raise SamplingRuleViolation("Run Task keys must be SHA-256")
        if self.reserved_task_count != len(self.planned_task_keys):
            raise SamplingRuleViolation("Run admission reservation must cover its denominator")
        _require_aware(self.admitted_not_before, "Run not_before")
        _require_aware(self.authorization_valid_until, "Run authorization expiry")
        _require_aware(self.created_at, "Run creation time")
        if self.admitted_not_before >= self.authorization_valid_until:
            raise SamplingRuleViolation("Run admission begins after authorization expiry")
        if self.version < 1:
            raise SamplingRuleViolation("Run version must be positive")


@dataclass(frozen=True)
class SamplingTask:
    id: UUID
    project_id: UUID
    run_id: UUID
    identity: SamplingTaskIdentity
    status: SamplingTaskStatus = SamplingTaskStatus.PLANNED
    attempt_ids: tuple[UUID, ...] = ()
    max_attempts: int = 3
    version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", SamplingTaskStatus(self.status))
        # `task_key` identifies the stable denominator member. A materialized
        # Task is Run-scoped, otherwise a permitted rerun of a frozen Suite
        # collides with the first Run's Task primary keys. The old id remains
        # readable for Runs materialized before this identity correction.
        if self.id not in {
            sampling_task_id(self.run_id, self.identity.task_key),
            self.identity.task_id,
        }:
            raise SamplingRuleViolation("Task id must derive from its Run-scoped identity")
        if len(set(self.attempt_ids)) != len(self.attempt_ids):
            raise SamplingRuleViolation("Task Attempt ids must be unique")
        if self.max_attempts < 1 or len(self.attempt_ids) > self.max_attempts:
            raise SamplingRuleViolation("Task Attempt budget is inconsistent")
        if self.version < len(self.attempt_ids) + 1:
            raise SamplingRuleViolation(
                "Task version cannot predate its immutable Attempt inventory"
            )


def sampling_task_id(run_id: UUID, task_key: str) -> UUID:
    """Return the deterministic materialized Task id for one frozen Run."""
    return uuid5(SAMPLING_TASK_NAMESPACE, f"{run_id}:{task_key}")


@dataclass(frozen=True)
class SamplingRunAssessment:
    run_id: UUID
    planned_task_count: int
    valid_task_count: int
    invalid_task_count: int
    missing_task_count: int
    valid_completion_ratio: Decimal
    sufficient_question_count: int
    question_count: int
    status: RunEvidenceStatus
    denominator_hash: str


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise SamplingRuleViolation(f"{label} is required and bounded")
    return normalized


def _optional_geo(value: str | None) -> str | None:
    if value is None:
        return None
    return _text(value, "location value")


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SamplingRuleViolation(f"{label} must be timezone-aware")
