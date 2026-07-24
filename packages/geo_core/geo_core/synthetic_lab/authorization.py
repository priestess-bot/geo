"""Authorization versions and fail-closed style collection admission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from geo_core.synthetic_lab.domain import (
    STANDARD_STYLE_CHANNELS,
    SyntheticLabContractError,
    SyntheticLabScopeError,
    SyntheticOnly,
    _as_enum,
    _canonical_hash,
    _require_aware_datetime,
    _require_hash,
    _require_text,
    _require_uuid,
)


COLLECTION_AUTHORIZATION_PURPOSES = frozenset({"style_collection"})


class AuthorizationState(StrEnum):
    NOT_ASSESSED = "not_assessed"
    ASSESSED_NO_BASIS = "assessed_no_basis"
    APPROVED = "approved"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AuthorizationTrack(StrEnum):
    A_AUTOMATIC = "a_automatic"
    B_FIXTURE_OR_MANUAL = "b_fixture_or_manual"


class CollectionPath(StrEnum):
    AUTOMATIC = "automatic_collection"
    FIXTURE = "fixture"
    MANUAL_IMPORT = "manual_import"


class AdmissionDisposition(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, kw_only=True)
class AuthorizationRecord(SyntheticOnly):
    id: UUID
    project_id: UUID
    channel: str
    adapter_release: str
    version_number: int
    previous_version_id: UUID | None
    state: AuthorizationState
    evidence_reference_hash: str | None
    decided_by: UUID | None
    decided_at: datetime | None
    allowed_purposes: tuple[str, ...]
    max_requests_per_period: int | None
    period_seconds: int | None
    max_concurrency: int | None
    expires_at: datetime | None
    decision_reason: str | None
    record_hash: str

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.id, "authorization ID"),
            (self.project_id, "authorization Project ID"),
        ):
            _require_uuid(uuid_value, label)
        if self.previous_version_id is not None:
            _require_uuid(self.previous_version_id, "previous authorization version ID")
        if self.version_number < 1:
            raise SyntheticLabContractError("authorization version must be positive")
        if (self.version_number == 1) != (self.previous_version_id is None):
            raise SyntheticLabContractError("authorization version lineage must be contiguous")
        if self.channel not in STANDARD_STYLE_CHANNELS:
            raise SyntheticLabContractError(f"unsupported authorization channel: {self.channel!r}")
        _require_text(self.adapter_release, "authorization adapter release")
        state = _as_enum(self.state, AuthorizationState, "authorization state")
        object.__setattr__(self, "state", state)
        purposes = tuple(self.allowed_purposes)
        object.__setattr__(self, "allowed_purposes", purposes)
        if len(purposes) != len(set(purposes)) or any(not item.strip() for item in purposes):
            raise SyntheticLabContractError(
                "authorization purposes must be unique non-empty values"
            )
        if self.evidence_reference_hash is not None:
            _require_hash(self.evidence_reference_hash, "authorization evidence reference hash")
        if self.expires_at is not None:
            _require_aware_datetime(self.expires_at, "authorization expiry")
        rate_values = (
            self.max_requests_per_period,
            self.period_seconds,
            self.max_concurrency,
        )
        if any(value is not None for value in rate_values):
            if any(value is None or value < 1 for value in rate_values):
                raise SyntheticLabContractError(
                    "authorization frequency requires positive requests, period and concurrency"
                )
        if state == AuthorizationState.NOT_ASSESSED:
            if (
                any(
                    value is not None
                    for value in (
                        self.evidence_reference_hash,
                        self.decided_by,
                        self.decided_at,
                        self.expires_at,
                        self.decision_reason,
                    )
                )
                or purposes
                or any(value is not None for value in rate_values)
            ):
                raise SyntheticLabContractError(
                    "not_assessed authorization cannot carry a decision or allowance"
                )
        else:
            if self.decided_by is None or self.decided_at is None:
                raise SyntheticLabContractError(
                    "assessed authorization requires decision actor and time"
                )
            _require_uuid(self.decided_by, "authorization decision actor")
            _require_aware_datetime(self.decided_at, "authorization decision time")
            _require_text(self.decision_reason or "", "authorization decision reason")
        if state in {
            AuthorizationState.APPROVED,
            AuthorizationState.EXPIRED,
            AuthorizationState.REVOKED,
        }:
            if self.evidence_reference_hash is None or not purposes:
                raise SyntheticLabContractError(
                    "approved/expired/revoked authorization requires prior evidence and purposes"
                )
            if any(value is None for value in rate_values) or self.expires_at is None:
                raise SyntheticLabContractError(
                    "approved/expired/revoked authorization requires frequency and expiry lineage"
                )
        if state == AuthorizationState.APPROVED:
            if (
                self.decided_at is not None
                and self.expires_at is not None
                and self.expires_at <= self.decided_at
            ):
                raise SyntheticLabContractError(
                    "approved authorization expiry must follow its decision"
                )
        elif state == AuthorizationState.EXPIRED:
            if (
                self.decided_at is not None
                and self.expires_at is not None
                and self.expires_at > self.decided_at
            ):
                raise SyntheticLabContractError(
                    "expired authorization cannot precede its recorded expiry"
                )
        elif state == AuthorizationState.ASSESSED_NO_BASIS:
            if purposes or any(value is not None for value in rate_values) or self.expires_at:
                raise SyntheticLabContractError(
                    "assessed_no_basis authorization cannot grant collection allowances"
                )
        _require_hash(self.record_hash, "authorization record hash")
        if self.record_hash != authorization_record_hash(self):
            raise SyntheticLabContractError(
                "authorization record does not match its immutable hash"
            )
        if any(purpose not in COLLECTION_AUTHORIZATION_PURPOSES for purpose in purposes):
            raise SyntheticLabContractError(
                "authorization purpose is outside the governed collection catalog"
            )

    def effective_state(self, at: datetime) -> AuthorizationState:
        _require_aware_datetime(at, "authorization evaluation time")
        if (
            self.state == AuthorizationState.APPROVED
            and self.expires_at is not None
            and at >= self.expires_at
        ):
            return AuthorizationState.EXPIRED
        return self.state


@dataclass(frozen=True, kw_only=True)
class AuthorizationBinding(SyntheticOnly):
    authorization_id: UUID
    project_id: UUID
    channel: str
    adapter_release: str
    version_number: int
    authorization_hash: str
    purpose: str
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.authorization_id, "authorization binding ID")
        _require_uuid(self.project_id, "authorization binding Project ID")
        if self.channel not in STANDARD_STYLE_CHANNELS:
            raise SyntheticLabContractError("authorization binding channel is unsupported")
        _require_text(self.adapter_release, "authorization binding adapter release")
        _require_text(self.purpose, "authorization binding purpose")
        if self.version_number < 1:
            raise SyntheticLabContractError("authorization binding version must be positive")
        _require_hash(self.authorization_hash, "authorization binding hash")
        _require_aware_datetime(self.expires_at, "authorization binding expiry")


@dataclass(frozen=True, kw_only=True)
class CollectionAdmissionRequest(SyntheticOnly):
    project_id: UUID
    channel: str
    adapter_release: str
    path: CollectionPath
    purpose: str
    requested_at: datetime
    planned_requests: int = 1
    planned_period_seconds: int = 1
    planned_concurrency: int = 1

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "collection admission Project ID")
        if self.channel not in STANDARD_STYLE_CHANNELS:
            raise SyntheticLabContractError("collection admission channel is unsupported")
        _require_text(self.adapter_release, "collection admission adapter release")
        _require_text(self.purpose, "collection admission purpose")
        _require_aware_datetime(self.requested_at, "collection admission time")
        object.__setattr__(self, "path", _as_enum(self.path, CollectionPath, "collection path"))
        if (
            min(
                self.planned_requests,
                self.planned_period_seconds,
                self.planned_concurrency,
            )
            < 1
        ):
            raise SyntheticLabContractError("planned collection frequency must be positive")


@dataclass(frozen=True, kw_only=True)
class CollectionAdmissionCommand(SyntheticOnly):
    disposition: AdmissionDisposition
    track: AuthorizationTrack
    reason_code: str
    binding: AuthorizationBinding | None
    create_job: bool
    emit_outbox: bool
    may_issue_network_request: bool

    def __post_init__(self) -> None:
        disposition = _as_enum(self.disposition, AdmissionDisposition, "admission disposition")
        track = _as_enum(self.track, AuthorizationTrack, "authorization track")
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "track", track)
        _require_text(self.reason_code, "admission reason code")
        if disposition == AdmissionDisposition.REJECTED:
            if (
                self.binding
                or self.create_job
                or self.emit_outbox
                or self.may_issue_network_request
            ):
                raise SyntheticLabContractError(
                    "rejected admission must produce zero Job, outbox and network intents"
                )
        if self.create_job != self.emit_outbox:
            raise SyntheticLabContractError("live Job and outbox intents must be atomic")
        if self.create_job and (
            self.binding is None
            or track != AuthorizationTrack.A_AUTOMATIC
            or not self.may_issue_network_request
        ):
            raise SyntheticLabContractError(
                "automatic Job requires an A-track authorization binding"
            )
        if track == AuthorizationTrack.B_FIXTURE_OR_MANUAL and (
            self.create_job or self.emit_outbox or self.may_issue_network_request
        ):
            raise SyntheticLabContractError("B-track command cannot create live work")


@dataclass(frozen=True, kw_only=True)
class NavigationCommand(SyntheticOnly):
    proceed: bool
    issue_network_request: bool
    reason_code: str

    def __post_init__(self) -> None:
        _require_text(self.reason_code, "navigation decision reason")
        if self.proceed != self.issue_network_request:
            raise SyntheticLabContractError(
                "stopped navigation cannot issue a target-page network request"
            )


def authorization_record_hash(record: AuthorizationRecord) -> str:
    return _canonical_hash(
        {
            "project_id": str(record.project_id),
            "channel": record.channel,
            "adapter_release": record.adapter_release,
            "version_number": record.version_number,
            "previous_version_id": (
                str(record.previous_version_id) if record.previous_version_id else None
            ),
            "state": record.state.value,
            "evidence_reference_hash": record.evidence_reference_hash,
            "decided_by": str(record.decided_by) if record.decided_by else None,
            "decided_at": record.decided_at.isoformat() if record.decided_at else None,
            "allowed_purposes": list(record.allowed_purposes),
            "max_requests_per_period": record.max_requests_per_period,
            "period_seconds": record.period_seconds,
            "max_concurrency": record.max_concurrency,
            "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            "decision_reason": record.decision_reason,
        }
    )


def create_authorization_record(**values: object) -> AuthorizationRecord:
    required = {
        "id",
        "project_id",
        "channel",
        "adapter_release",
        "version_number",
        "previous_version_id",
        "state",
        "evidence_reference_hash",
        "decided_by",
        "decided_at",
        "allowed_purposes",
        "max_requests_per_period",
        "period_seconds",
        "max_concurrency",
        "expires_at",
        "decision_reason",
    }
    if set(values) != required:
        raise SyntheticLabContractError(
            "authorization factory requires the complete immutable record contract"
        )
    provisional = object.__new__(AuthorizationRecord)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    state = _as_enum(values.get("state"), AuthorizationState, "authorization state")
    purposes = values.get("allowed_purposes", ())
    if not isinstance(purposes, (tuple, list)):
        raise SyntheticLabContractError("authorization purposes must be a sequence")
    object.__setattr__(provisional, "state", state)
    object.__setattr__(provisional, "allowed_purposes", tuple(purposes))
    record_hash = authorization_record_hash(provisional)
    return AuthorizationRecord(**values, record_hash=record_hash)  # type: ignore[arg-type]


def assert_next_authorization_version(
    previous: AuthorizationRecord,
    current: AuthorizationRecord,
) -> None:
    if previous.project_id != current.project_id:
        raise SyntheticLabScopeError("authorization versions belong to different Projects")
    if (
        current.id == previous.id
        or current.previous_version_id != previous.id
        or current.version_number != previous.version_number + 1
        or current.channel != previous.channel
        or current.adapter_release != previous.adapter_release
    ):
        raise SyntheticLabContractError(
            "authorization versions must preserve target and contiguous identity"
        )


def open_authorization_reassessment(
    previous: AuthorizationRecord,
    *,
    reassessment_id: UUID,
    opened_at: datetime,
) -> AuthorizationRecord:
    """Open a blank next version; prior approval is never restored implicitly."""

    _require_uuid(reassessment_id, "authorization reassessment ID")
    _require_aware_datetime(opened_at, "authorization reassessment time")
    eligible = previous.state in {
        AuthorizationState.ASSESSED_NO_BASIS,
        AuthorizationState.EXPIRED,
        AuthorizationState.REVOKED,
    } or (
        previous.state is AuthorizationState.APPROVED
        and previous.effective_state(opened_at) is AuthorizationState.EXPIRED
    )
    if not eligible:
        raise SyntheticLabContractError(
            "authorization reassessment requires no-basis, expired or revoked lineage"
        )
    current = create_authorization_record(
        id=reassessment_id,
        project_id=previous.project_id,
        channel=previous.channel,
        adapter_release=previous.adapter_release,
        version_number=previous.version_number + 1,
        previous_version_id=previous.id,
        state=AuthorizationState.NOT_ASSESSED,
        evidence_reference_hash=None,
        decided_by=None,
        decided_at=None,
        allowed_purposes=(),
        max_requests_per_period=None,
        period_seconds=None,
        max_concurrency=None,
        expires_at=None,
        decision_reason=None,
    )
    assert_next_authorization_version(previous, current)
    return current


def admit_collection(
    request: CollectionAdmissionRequest,
    authorization: AuthorizationRecord | None,
) -> CollectionAdmissionCommand:
    if authorization is not None and (
        authorization.project_id != request.project_id
        or authorization.channel != request.channel
        or authorization.adapter_release != request.adapter_release
    ):
        return _rejected("authorization_scope_mismatch")
    if request.path in {CollectionPath.FIXTURE, CollectionPath.MANUAL_IMPORT}:
        return CollectionAdmissionCommand(
            disposition=AdmissionDisposition.ACCEPTED,
            track=AuthorizationTrack.B_FIXTURE_OR_MANUAL,
            reason_code="b_track_fixture_or_manual",
            binding=None,
            create_job=False,
            emit_outbox=False,
            may_issue_network_request=False,
        )
    if authorization is None:
        return _rejected("authorization_missing")
    if authorization.effective_state(request.requested_at) != AuthorizationState.APPROVED:
        return _rejected(
            f"authorization_{authorization.effective_state(request.requested_at).value}"
        )
    if request.purpose not in authorization.allowed_purposes:
        return _rejected("authorization_purpose_denied")
    if (
        authorization.max_requests_per_period is None
        or authorization.period_seconds is None
        or authorization.max_concurrency is None
        or request.planned_requests * authorization.period_seconds
        > authorization.max_requests_per_period * request.planned_period_seconds
        or request.planned_concurrency > authorization.max_concurrency
    ):
        return _rejected("authorization_frequency_exceeded")
    binding = AuthorizationBinding(
        authorization_id=authorization.id,
        project_id=authorization.project_id,
        channel=authorization.channel,
        adapter_release=authorization.adapter_release,
        version_number=authorization.version_number,
        authorization_hash=authorization.record_hash,
        purpose=request.purpose,
        expires_at=authorization.expires_at,  # type: ignore[arg-type]
    )
    return CollectionAdmissionCommand(
        disposition=AdmissionDisposition.ACCEPTED,
        track=AuthorizationTrack.A_AUTOMATIC,
        reason_code="authorization_approved",
        binding=binding,
        create_job=True,
        emit_outbox=True,
        may_issue_network_request=True,
    )


def recheck_before_navigation(
    binding: AuthorizationBinding,
    current: AuthorizationRecord | None,
    *,
    at: datetime,
) -> NavigationCommand:
    if current is None or (
        current.id != binding.authorization_id
        or current.project_id != binding.project_id
        or current.channel != binding.channel
        or current.adapter_release != binding.adapter_release
        or current.version_number != binding.version_number
        or current.record_hash != binding.authorization_hash
        or binding.purpose not in current.allowed_purposes
        or current.effective_state(at) != AuthorizationState.APPROVED
    ):
        return NavigationCommand(
            proceed=False,
            issue_network_request=False,
            reason_code="authorization_stale_or_inactive",
        )
    return NavigationCommand(
        proceed=True,
        issue_network_request=True,
        reason_code="authorization_recheck_passed",
    )


def _rejected(reason_code: str) -> CollectionAdmissionCommand:
    return CollectionAdmissionCommand(
        disposition=AdmissionDisposition.REJECTED,
        track=AuthorizationTrack.B_FIXTURE_OR_MANUAL,
        reason_code=reason_code,
        binding=None,
        create_job=False,
        emit_outbox=False,
        may_issue_network_request=False,
    )


__all__ = [
    "AdmissionDisposition",
    "AuthorizationBinding",
    "AuthorizationRecord",
    "AuthorizationState",
    "AuthorizationTrack",
    "CollectionAdmissionCommand",
    "CollectionAdmissionRequest",
    "CollectionPath",
    "COLLECTION_AUTHORIZATION_PURPOSES",
    "NavigationCommand",
    "admit_collection",
    "assert_next_authorization_version",
    "authorization_record_hash",
    "create_authorization_record",
    "open_authorization_reassessment",
    "recheck_before_navigation",
]
