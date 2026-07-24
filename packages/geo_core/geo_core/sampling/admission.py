"""Authorization, purpose, quota, rate and not-before admission rules."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from geo_core.sampling.contracts import (
    CaptureMethod,
    LocationControl,
    SHA256_PATTERN,
    SamplingRuleViolation,
    SamplingSuite,
    canonical_hash,
    _require_aware,
    _text,
)


class AuthorizationState(StrEnum):
    APPROVED = "approved"
    NOT_ASSESSED = "not_assessed"
    ASSESSED_NO_BASIS = "assessed_no_basis"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AdmissionPolicyStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    ASSESSED_NO_BASIS = "assessed_no_basis"
    REVOKED = "revoked"


@dataclass(frozen=True)
class SamplingAdmissionPolicy:
    id: UUID
    project_id: UUID
    platform: str
    capture_method: CaptureMethod
    adapter_release: str
    location_control: LocationControl
    location_evidence_hash: str
    authorization_state: AuthorizationState
    authorization_reference: str
    authorized_purposes: tuple[str, ...]
    valid_until: datetime
    quota_remaining: int
    daily_task_limit: int
    minimum_request_interval_seconds: int
    max_concurrency: int
    next_allowed_at: datetime
    policy_version: str
    policy_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "capture_method", CaptureMethod(self.capture_method))
        object.__setattr__(self, "location_control", LocationControl(self.location_control))
        object.__setattr__(
            self, "authorization_state", AuthorizationState(self.authorization_state)
        )
        for name in (
            "platform",
            "adapter_release",
            "authorization_reference",
            "policy_version",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), f"admission {name}"))
        purposes = tuple(
            sorted({_text(item, "authorized purpose") for item in self.authorized_purposes})
        )
        if not purposes:
            raise SamplingRuleViolation("admission policy requires an authorized purpose")
        if min(self.quota_remaining, self.daily_task_limit, self.max_concurrency) < 1:
            raise SamplingRuleViolation("admission quota and concurrency must be positive")
        if self.minimum_request_interval_seconds < 0:
            raise SamplingRuleViolation("admission request interval cannot be negative")
        if not SHA256_PATTERN.fullmatch(self.location_evidence_hash):
            raise SamplingRuleViolation("admission location evidence hash must be SHA-256")
        _require_aware(self.valid_until, "authorization expiry")
        _require_aware(self.next_allowed_at, "admission next_allowed_at")
        object.__setattr__(self, "authorized_purposes", purposes)
        object.__setattr__(
            self,
            "policy_hash",
            canonical_hash(
                {
                    "id": str(self.id),
                    "project_id": str(self.project_id),
                    "platform": self.platform,
                    "capture_method": self.capture_method.value,
                    "adapter_release": self.adapter_release,
                    "location_control": self.location_control.value,
                    "location_evidence_hash": self.location_evidence_hash,
                    "authorization_state": self.authorization_state.value,
                    "authorization_reference": self.authorization_reference,
                    "authorized_purposes": list(self.authorized_purposes),
                    "valid_until": self.valid_until.isoformat(),
                    "quota_remaining": self.quota_remaining,
                    "daily_task_limit": self.daily_task_limit,
                    "minimum_request_interval_seconds": self.minimum_request_interval_seconds,
                    "max_concurrency": self.max_concurrency,
                    "next_allowed_at": self.next_allowed_at.isoformat(),
                    "policy_version": self.policy_version,
                }
            ),
        )


@dataclass(frozen=True)
class SamplingAdmissionPolicyRecord:
    """Immutable policy definition with a maker-checker lifecycle."""

    id: UUID
    project_id: UUID
    revision: int
    supersedes_policy_id: UUID | None
    platform: str
    capture_method: CaptureMethod
    adapter_release: str
    location_control: LocationControl
    location_evidence_hash: str
    authorization_reference: str
    authorized_purposes: tuple[str, ...]
    valid_until: datetime
    quota_remaining: int
    daily_task_limit: int
    minimum_request_interval_seconds: int
    max_concurrency: int
    next_allowed_at: datetime
    created_by: str
    created_at: datetime
    status: AdmissionPolicyStatus = AdmissionPolicyStatus.DRAFT
    submitted_by: str | None = None
    submitted_at: datetime | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    revoked_by: str | None = None
    revoked_at: datetime | None = None
    revocation_reason: str | None = None
    aggregate_version: int = 1
    definition_hash: str = field(init=False)
    policy_version: str = field(init=False)

    def __post_init__(self) -> None:
        capture = CaptureMethod(self.capture_method)
        location_control = LocationControl(self.location_control)
        status = AdmissionPolicyStatus(self.status)
        if self.revision < 1 or self.aggregate_version < 1:
            raise SamplingRuleViolation("admission policy versions must be positive")
        for name in ("platform", "adapter_release", "authorization_reference", "created_by"):
            object.__setattr__(self, name, _text(getattr(self, name), f"admission policy {name}"))
        purposes = tuple(
            sorted({_text(item, "authorized purpose") for item in self.authorized_purposes})
        )
        if not purposes:
            raise SamplingRuleViolation("admission policy requires an authorized purpose")
        if min(self.quota_remaining, self.daily_task_limit, self.max_concurrency) < 1:
            raise SamplingRuleViolation("admission quota and concurrency must be positive")
        if self.minimum_request_interval_seconds < 0:
            raise SamplingRuleViolation("admission request interval cannot be negative")
        if not SHA256_PATTERN.fullmatch(self.location_evidence_hash):
            raise SamplingRuleViolation("admission location evidence hash must be SHA-256")
        _require_aware(self.created_at, "admission policy creation time")
        _require_aware(self.valid_until, "authorization expiry")
        _require_aware(self.next_allowed_at, "admission next_allowed_at")
        if self.valid_until <= self.created_at:
            raise SamplingRuleViolation("admission policy must be valid after creation")
        if self.next_allowed_at >= self.valid_until:
            raise SamplingRuleViolation("admission policy next_allowed_at must precede expiry")
        _validate_policy_audit(self, status)
        definition = {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "revision": self.revision,
            "supersedes_policy_id": (
                str(self.supersedes_policy_id) if self.supersedes_policy_id is not None else None
            ),
            "platform": self.platform,
            "capture_method": capture.value,
            "adapter_release": self.adapter_release,
            "location_control": location_control.value,
            "location_evidence_hash": self.location_evidence_hash,
            "authorization_reference": self.authorization_reference,
            "authorized_purposes": list(purposes),
            "valid_until": self.valid_until.isoformat(),
            "quota_remaining": self.quota_remaining,
            "daily_task_limit": self.daily_task_limit,
            "minimum_request_interval_seconds": self.minimum_request_interval_seconds,
            "max_concurrency": self.max_concurrency,
            "next_allowed_at": self.next_allowed_at.isoformat(),
        }
        definition_hash = canonical_hash(definition)
        object.__setattr__(self, "capture_method", capture)
        object.__setattr__(self, "location_control", location_control)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "authorized_purposes", purposes)
        object.__setattr__(self, "definition_hash", definition_hash)
        object.__setattr__(
            self,
            "policy_version",
            f"sampling-admission:{self.id}:r{self.revision}:{definition_hash[:12]}",
        )

    def effective_authorization_state(self, *, at: datetime) -> AuthorizationState:
        _require_aware(at, "authorization evaluation time")
        if self.status is AdmissionPolicyStatus.APPROVED:
            return (
                AuthorizationState.EXPIRED
                if at >= self.valid_until
                else AuthorizationState.APPROVED
            )
        if self.status is AdmissionPolicyStatus.ASSESSED_NO_BASIS:
            return AuthorizationState.ASSESSED_NO_BASIS
        if self.status is AdmissionPolicyStatus.REVOKED:
            return AuthorizationState.REVOKED
        return AuthorizationState.NOT_ASSESSED

    def approved_policy(self, *, at: datetime) -> SamplingAdmissionPolicy:
        state = self.effective_authorization_state(at=at)
        if state is not AuthorizationState.APPROVED:
            raise SamplingRuleViolation(f"sampling authorization is {state.value}")
        return SamplingAdmissionPolicy(
            id=self.id,
            project_id=self.project_id,
            platform=self.platform,
            capture_method=self.capture_method,
            adapter_release=self.adapter_release,
            location_control=self.location_control,
            location_evidence_hash=self.location_evidence_hash,
            authorization_state=state,
            authorization_reference=self.authorization_reference,
            authorized_purposes=self.authorized_purposes,
            valid_until=self.valid_until,
            quota_remaining=self.quota_remaining,
            daily_task_limit=self.daily_task_limit,
            minimum_request_interval_seconds=self.minimum_request_interval_seconds,
            max_concurrency=self.max_concurrency,
            next_allowed_at=self.next_allowed_at,
            policy_version=self.policy_version,
        )


def submit_admission_policy(
    record: SamplingAdmissionPolicyRecord, *, actor_id: str, occurred_at: datetime
) -> SamplingAdmissionPolicyRecord:
    if record.status is not AdmissionPolicyStatus.DRAFT:
        raise SamplingRuleViolation("only a draft admission policy can be submitted")
    actor = _text(actor_id, "admission policy submitter")
    _transition_time(record, occurred_at)
    return replace(
        record,
        status=AdmissionPolicyStatus.PENDING_REVIEW,
        submitted_by=actor,
        submitted_at=occurred_at,
        aggregate_version=record.aggregate_version + 1,
    )


def decide_admission_policy(
    record: SamplingAdmissionPolicyRecord,
    *,
    actor_id: str,
    occurred_at: datetime,
    reason: str,
    approved: bool,
) -> SamplingAdmissionPolicyRecord:
    if record.status is not AdmissionPolicyStatus.PENDING_REVIEW:
        raise SamplingRuleViolation("only a pending admission policy can be decided")
    actor = _text(actor_id, "admission policy checker")
    if actor == record.created_by:
        raise SamplingRuleViolation("admission policy maker cannot approve or reject it")
    decision_reason = _text(reason, "admission policy decision reason")
    _transition_time(record, occurred_at)
    return replace(
        record,
        status=(
            AdmissionPolicyStatus.APPROVED if approved else AdmissionPolicyStatus.ASSESSED_NO_BASIS
        ),
        decided_by=actor,
        decided_at=occurred_at,
        decision_reason=decision_reason,
        aggregate_version=record.aggregate_version + 1,
    )


def revoke_admission_policy(
    record: SamplingAdmissionPolicyRecord,
    *,
    actor_id: str,
    occurred_at: datetime,
    reason: str,
) -> SamplingAdmissionPolicyRecord:
    if record.status is not AdmissionPolicyStatus.APPROVED:
        raise SamplingRuleViolation("only an approved admission policy can be revoked")
    actor = _text(actor_id, "admission policy revoker")
    revocation_reason = _text(reason, "admission policy revocation reason")
    _transition_time(record, occurred_at)
    return replace(
        record,
        status=AdmissionPolicyStatus.REVOKED,
        revoked_by=actor,
        revoked_at=occurred_at,
        revocation_reason=revocation_reason,
        aggregate_version=record.aggregate_version + 1,
    )


@dataclass(frozen=True)
class SamplingAdmissionCommand:
    idempotency_key: str
    purpose: str
    requested_at: datetime
    requested_not_before: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "idempotency_key", _text(self.idempotency_key, "admission idempotency key")
        )
        object.__setattr__(self, "purpose", _text(self.purpose, "sampling purpose"))
        _require_aware(self.requested_at, "admission request time")
        _require_aware(self.requested_not_before, "requested not_before")
        if self.requested_not_before < self.requested_at:
            raise SamplingRuleViolation("requested not_before cannot predate admission request")


@dataclass(frozen=True)
class SamplingAdmissionGrant:
    policy_id: UUID
    policy_hash: str
    suite_id: UUID
    suite_hash: str
    purpose: str
    policy_version: str
    authorization_reference: str
    authorization_valid_until: datetime
    reserved_task_count: int
    not_before: datetime
    idempotency_key: str
    grant_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for digest in (self.policy_hash, self.suite_hash):
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise SamplingRuleViolation("admission Grant lineage must use SHA-256")
        for name in (
            "purpose",
            "policy_version",
            "authorization_reference",
            "idempotency_key",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), f"Grant {name}"))
        if self.reserved_task_count < 1:
            raise SamplingRuleViolation("admission Grant must reserve a positive denominator")
        _require_aware(self.not_before, "admission Grant not_before")
        _require_aware(self.authorization_valid_until, "admission Grant expiry")
        if self.not_before >= self.authorization_valid_until:
            raise SamplingRuleViolation("admission Grant cannot begin after authorization expiry")
        object.__setattr__(
            self,
            "grant_hash",
            canonical_hash(
                {
                    "policy_id": str(self.policy_id),
                    "policy_hash": self.policy_hash,
                    "suite_id": str(self.suite_id),
                    "suite_hash": self.suite_hash,
                    "purpose": self.purpose,
                    "policy_version": self.policy_version,
                    "authorization_reference": self.authorization_reference,
                    "authorization_valid_until": self.authorization_valid_until.isoformat(),
                    "reserved_task_count": self.reserved_task_count,
                    "not_before": self.not_before.isoformat(),
                    "idempotency_key": self.idempotency_key,
                }
            ),
        )


def admit_sampling_suite(
    suite: SamplingSuite,
    *,
    policy: SamplingAdmissionPolicy,
    command: SamplingAdmissionCommand,
) -> SamplingAdmissionGrant:
    if policy.project_id != suite.project_id:
        raise SamplingRuleViolation("admission policy belongs to another project")
    if (
        policy.platform != suite.source_stratum.platform
        or policy.capture_method is not suite.source_stratum.capture_method
        or policy.adapter_release != suite.source_stratum.adapter_release
        or policy.location_control is not suite.source_stratum.location_control
        or policy.location_evidence_hash != suite.source_stratum.location_evidence_hash
    ):
        raise SamplingRuleViolation("admission policy does not match Suite target release")
    if policy.authorization_state is not AuthorizationState.APPROVED:
        raise SamplingRuleViolation("sampling authorization is not approved")
    if command.requested_at >= policy.valid_until:
        raise SamplingRuleViolation("sampling authorization is expired")
    if command.purpose not in policy.authorized_purposes:
        raise SamplingRuleViolation("sampling purpose is not authorized")
    if suite.planned_task_count > policy.quota_remaining:
        raise SamplingRuleViolation("sampling quota cannot cover the planned denominator")
    if suite.max_daily_tasks > policy.daily_task_limit:
        raise SamplingRuleViolation("Suite daily budget exceeds authorization quota")
    if suite.minimum_request_interval_seconds < policy.minimum_request_interval_seconds:
        raise SamplingRuleViolation("Suite request rate exceeds authorization")
    if suite.max_concurrency > policy.max_concurrency:
        raise SamplingRuleViolation("Suite concurrency exceeds authorization")
    not_before = max(command.requested_not_before, policy.next_allowed_at)
    if not_before >= policy.valid_until:
        raise SamplingRuleViolation("sampling authorization expires before work is admissible")
    return SamplingAdmissionGrant(
        policy_id=policy.id,
        policy_hash=policy.policy_hash,
        suite_id=suite.id,
        suite_hash=suite.suite_hash,
        purpose=command.purpose,
        policy_version=policy.policy_version,
        authorization_reference=policy.authorization_reference,
        authorization_valid_until=policy.valid_until,
        reserved_task_count=suite.planned_task_count,
        not_before=not_before,
        idempotency_key=command.idempotency_key,
    )


def require_current_admission_policy(
    record: SamplingAdmissionPolicyRecord,
    *,
    policy_id: UUID,
    policy_hash: str,
    policy_version: str,
    at: datetime,
) -> SamplingAdmissionPolicy:
    policy = record.approved_policy(at=at)
    if (
        record.id != policy_id
        or policy.policy_hash != policy_hash
        or record.policy_version != policy_version
    ):
        raise SamplingRuleViolation("Sampling Run admission policy lineage is stale")
    return policy


def _validate_policy_audit(
    record: SamplingAdmissionPolicyRecord, status: AdmissionPolicyStatus
) -> None:
    timestamp_fields = (
        (record.submitted_by, record.submitted_at, "submission"),
        (record.decided_by, record.decided_at, "decision"),
        (record.revoked_by, record.revoked_at, "revocation"),
    )
    for actor, occurred_at, label in timestamp_fields:
        if (actor is None) != (occurred_at is None):
            raise SamplingRuleViolation(f"admission policy {label} audit is incomplete")
        if actor is not None:
            _text(actor, f"admission policy {label} actor")
            assert occurred_at is not None
            _require_aware(occurred_at, f"admission policy {label} time")
    if status is AdmissionPolicyStatus.DRAFT:
        if any(
            item is not None
            for item in (
                *timestamp_fields[0][:2],
                *timestamp_fields[1][:2],
                *timestamp_fields[2][:2],
            )
        ):
            raise SamplingRuleViolation("draft admission policy cannot have lifecycle audit")
    elif record.submitted_at is None:
        raise SamplingRuleViolation("non-draft admission policy requires submission audit")
    if status in {
        AdmissionPolicyStatus.APPROVED,
        AdmissionPolicyStatus.ASSESSED_NO_BASIS,
        AdmissionPolicyStatus.REVOKED,
    } and (record.decided_at is None or record.decision_reason is None):
        raise SamplingRuleViolation("decided admission policy requires decision audit")
    if status is AdmissionPolicyStatus.REVOKED and (
        record.revoked_at is None or record.revocation_reason is None
    ):
        raise SamplingRuleViolation("revoked admission policy requires revocation audit")


def _transition_time(record: SamplingAdmissionPolicyRecord, occurred_at: datetime) -> None:
    _require_aware(occurred_at, "admission policy transition time")
    latest = max(
        item
        for item in (record.created_at, record.submitted_at, record.decided_at, record.revoked_at)
        if item is not None
    )
    if occurred_at < latest:
        raise SamplingRuleViolation("admission policy transition time cannot move backwards")
