"""Pre-persistence classification, retention and access rules for style artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from geo_core.synthetic_lab.domain import (
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


class ArtifactAccessClass(StrEnum):
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    RESTRICTED = "restricted"


class ArtifactForm(StrEnum):
    RAW = "raw"
    DERIVED = "derived"


class SensitiveFinding(StrEnum):
    COOKIE = "cookie"
    AUTHORIZATION = "authorization"
    SESSION_TOKEN = "session_token"
    PASSWORD = "password"
    STORAGE_STATE = "storage_state"
    USERNAME = "username"
    ACCOUNT_URL = "account_url"
    AVATAR = "avatar"
    EMAIL = "email"
    DIRECT_IDENTIFIER = "direct_identifier"
    RESTRICTED_CONTENT = "restricted_content"


class RawArtifactClassification(StrEnum):
    PUBLIC_RAW = "public_raw"
    RESTRICTED_AUTHENTICATED_RAW = "restricted_authenticated_raw"
    DERIVED_ANONYMIZED = "derived_anonymized"
    SECRET_BEARING_REJECTED = "secret_bearing_rejected"


class ArtifactStorageTier(StrEnum):
    NONE = "none"
    ENCRYPTED_RAW = "encrypted_raw"
    RESTRICTED_INDEPENDENT_DEK = "restricted_independent_dek"
    DERIVED_PROJECT = "derived_project"


class ArtifactAudience(StrEnum):
    INTERNAL_EVIDENCE = "internal_evidence"
    STYLE_RAW_REVIEWER = "style_raw_reviewer"
    SECURITY_AUDITOR = "security_auditor"
    PROJECT_OPERATOR = "project_operator"
    MODEL_GENERATION = "model_generation"
    RECOMMENDATION = "recommendation"
    CUSTOMER = "customer"
    GENERAL_EXPORT = "general_export"


_REDACTABLE_FINDINGS = frozenset(SensitiveFinding) - {SensitiveFinding.RESTRICTED_CONTENT}
_NEVER_EXTERNAL_AUDIENCES = frozenset(
    {
        ArtifactAudience.RECOMMENDATION,
        ArtifactAudience.CUSTOMER,
        ArtifactAudience.GENERAL_EXPORT,
    }
)


@dataclass(frozen=True, kw_only=True)
class RawArtifactInspection(SyntheticOnly):
    artifact_id: UUID
    project_id: UUID
    captured_at: datetime
    access_class: ArtifactAccessClass
    form: ArtifactForm
    payload_hash: str
    detected_findings: tuple[SensitiveFinding, ...]
    unresolved_findings: tuple[SensitiveFinding, ...]
    redaction_applied: bool
    redaction_verified: bool
    redacted_payload_hash: str | None
    anonymization_verified: bool
    policy_max_ttl_days: int | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.artifact_id, "raw artifact ID")
        _require_uuid(self.project_id, "raw artifact Project ID")
        _require_aware_datetime(self.captured_at, "raw artifact capture time")
        access_class = _as_enum(
            self.access_class,
            ArtifactAccessClass,
            "artifact access class",
        )
        form = _as_enum(self.form, ArtifactForm, "artifact form")
        object.__setattr__(self, "access_class", access_class)
        object.__setattr__(self, "form", form)
        _require_hash(self.payload_hash, "raw artifact payload hash")
        detected = tuple(
            _as_enum(value, SensitiveFinding, "sensitive finding")
            for value in self.detected_findings
        )
        unresolved = tuple(
            _as_enum(value, SensitiveFinding, "unresolved sensitive finding")
            for value in self.unresolved_findings
        )
        object.__setattr__(self, "detected_findings", detected)
        object.__setattr__(self, "unresolved_findings", unresolved)
        if len(detected) != len(set(detected)) or len(unresolved) != len(set(unresolved)):
            raise SyntheticLabContractError("artifact findings must be unique")
        if not set(unresolved).issubset(detected):
            raise SyntheticLabContractError("unresolved findings must have been detected")
        redactable_detected = set(detected).intersection(_REDACTABLE_FINDINGS)
        if redactable_detected and not unresolved:
            if not (
                self.redaction_applied
                and self.redaction_verified
                and self.redacted_payload_hash is not None
            ):
                raise SyntheticLabContractError(
                    "removed secret/PII findings require verified redaction evidence"
                )
            _require_hash(self.redacted_payload_hash, "redacted artifact payload hash")
            if self.redacted_payload_hash == self.payload_hash:
                raise SyntheticLabContractError("redaction must change the payload hash")
        elif self.redacted_payload_hash is not None:
            _require_hash(self.redacted_payload_hash, "redacted artifact payload hash")
        if self.policy_max_ttl_days is not None and self.policy_max_ttl_days < 0:
            raise SyntheticLabContractError("artifact policy TTL cannot be negative")


@dataclass(frozen=True, kw_only=True)
class ArtifactGovernanceDecision(SyntheticOnly):
    artifact_id: UUID
    project_id: UUID
    captured_at: datetime
    classification: RawArtifactClassification
    persisted_content_hash: str
    persistence_allowed: bool
    storage_tier: ArtifactStorageTier
    independent_dek_required: bool
    allowed_audiences: tuple[ArtifactAudience, ...]
    ttl_days: int | None
    expires_at: datetime | None
    destroy_temporary_payload: bool
    customer_visible: bool = field(default=False, init=False)
    general_export_allowed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_uuid(self.artifact_id, "artifact decision ID")
        _require_uuid(self.project_id, "artifact decision Project ID")
        _require_aware_datetime(self.captured_at, "artifact decision capture time")
        classification = _as_enum(
            self.classification,
            RawArtifactClassification,
            "raw artifact classification",
        )
        storage = _as_enum(self.storage_tier, ArtifactStorageTier, "artifact storage tier")
        audiences = tuple(
            _as_enum(value, ArtifactAudience, "artifact audience")
            for value in self.allowed_audiences
        )
        object.__setattr__(self, "classification", classification)
        object.__setattr__(self, "storage_tier", storage)
        object.__setattr__(self, "allowed_audiences", audiences)
        _require_hash(self.persisted_content_hash, "governed artifact content hash")
        if len(audiences) != len(set(audiences)) or set(audiences).intersection(
            _NEVER_EXTERNAL_AUDIENCES
        ):
            raise SyntheticLabContractError(
                "artifact audience cannot include Customer/export/recommendation"
            )
        if (
            classification != RawArtifactClassification.DERIVED_ANONYMIZED
            and ArtifactAudience.MODEL_GENERATION in audiences
        ):
            raise SyntheticLabContractError("raw artifact cannot be read by model generation")
        if self.persistence_allowed == (
            classification == RawArtifactClassification.SECRET_BEARING_REJECTED
        ):
            raise SyntheticLabContractError(
                "artifact rejection classification must match persistence decision"
            )
        if not self.persistence_allowed:
            if (
                storage != ArtifactStorageTier.NONE
                or audiences
                or self.ttl_days != 0
                or self.expires_at is not None
                or not self.destroy_temporary_payload
            ):
                raise SyntheticLabContractError(
                    "rejected artifact must have zero persistence and immediate destruction"
                )
        else:
            if storage == ArtifactStorageTier.NONE or not audiences:
                raise SyntheticLabContractError(
                    "persisted artifact requires governed storage and audience"
                )
            if classification == RawArtifactClassification.RESTRICTED_AUTHENTICATED_RAW and (
                storage != ArtifactStorageTier.RESTRICTED_INDEPENDENT_DEK
                or not self.independent_dek_required
            ):
                raise SyntheticLabContractError(
                    "restricted raw requires its restricted bucket and independent DEK"
                )
            if classification == RawArtifactClassification.PUBLIC_RAW and (
                storage != ArtifactStorageTier.ENCRYPTED_RAW or self.independent_dek_required
            ):
                raise SyntheticLabContractError("public raw requires encrypted raw storage")
            if classification == RawArtifactClassification.DERIVED_ANONYMIZED and (
                storage != ArtifactStorageTier.DERIVED_PROJECT or self.independent_dek_required
            ):
                raise SyntheticLabContractError(
                    "derived anonymized artifact requires project-derived storage"
                )
            if self.ttl_days is not None:
                if self.ttl_days < 1 or self.expires_at != self.captured_at + timedelta(
                    days=self.ttl_days
                ):
                    raise SyntheticLabContractError("artifact expiry must match its positive TTL")


@dataclass(frozen=True, kw_only=True)
class ArtifactLegalHold(SyntheticOnly):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    approved_by: tuple[UUID, UUID]
    reason: str
    approved_at: datetime
    expires_at: datetime
    hold_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.id, "legal hold ID"),
            (self.project_id, "legal hold Project ID"),
            (self.artifact_id, "legal hold artifact ID"),
        ):
            _require_uuid(uuid_value, label)
        approvers = tuple(self.approved_by)
        object.__setattr__(self, "approved_by", approvers)
        if len(approvers) != 2 or approvers[0] == approvers[1]:
            raise SyntheticLabContractError("legal hold requires two distinct approvers")
        for approver in approvers:
            _require_uuid(approver, "legal hold approver")
        _require_text(self.reason, "legal hold reason")
        _require_aware_datetime(self.approved_at, "legal hold approval time")
        _require_aware_datetime(self.expires_at, "legal hold expiry")
        if not self.approved_at < self.expires_at <= self.approved_at + timedelta(days=90):
            raise SyntheticLabContractError("legal hold must expire within 90 days")
        object.__setattr__(
            self,
            "hold_hash",
            _canonical_hash(
                {
                    "project_id": str(self.project_id),
                    "artifact_id": str(self.artifact_id),
                    "approved_by": sorted(str(item) for item in approvers),
                    "reason": self.reason,
                    "approved_at": self.approved_at.isoformat(),
                    "expires_at": self.expires_at.isoformat(),
                }
            ),
        )


@dataclass(frozen=True, kw_only=True)
class ArtifactTombstone(SyntheticOnly):
    project_id: UUID
    artifact_id: UUID
    original_content_hash: str
    classification: RawArtifactClassification
    deleted_at: datetime
    object_deleted: bool
    artifact_dek_destroyed: bool
    recoverable_body_retained: bool = field(default=False, init=False)
    tombstone_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "artifact tombstone Project ID")
        _require_uuid(self.artifact_id, "artifact tombstone artifact ID")
        _require_hash(self.original_content_hash, "artifact tombstone original hash")
        classification = _as_enum(
            self.classification,
            RawArtifactClassification,
            "tombstone classification",
        )
        object.__setattr__(self, "classification", classification)
        _require_aware_datetime(self.deleted_at, "artifact deletion time")
        if not self.object_deleted or not self.artifact_dek_destroyed:
            raise SyntheticLabContractError(
                "artifact tombstone requires object deletion and DEK destruction"
            )
        object.__setattr__(
            self,
            "tombstone_hash",
            _canonical_hash(
                {
                    "project_id": str(self.project_id),
                    "artifact_id": str(self.artifact_id),
                    "original_content_hash": self.original_content_hash,
                    "classification": classification.value,
                    "deleted_at": self.deleted_at.isoformat(),
                    "object_deleted": self.object_deleted,
                    "artifact_dek_destroyed": self.artifact_dek_destroyed,
                    "recoverable_body_retained": False,
                }
            ),
        )


def govern_raw_artifact(inspection: RawArtifactInspection) -> ArtifactGovernanceDecision:
    persisted_hash = inspection.redacted_payload_hash or inspection.payload_hash
    if inspection.unresolved_findings or inspection.policy_max_ttl_days == 0:
        return ArtifactGovernanceDecision(
            artifact_id=inspection.artifact_id,
            project_id=inspection.project_id,
            captured_at=inspection.captured_at,
            classification=RawArtifactClassification.SECRET_BEARING_REJECTED,
            persisted_content_hash=persisted_hash,
            persistence_allowed=False,
            storage_tier=ArtifactStorageTier.NONE,
            independent_dek_required=False,
            allowed_audiences=(),
            ttl_days=0,
            expires_at=None,
            destroy_temporary_payload=True,
        )
    if inspection.form == ArtifactForm.DERIVED:
        if not inspection.anonymization_verified:
            raise SyntheticLabContractError(
                "derived artifact requires verified anonymization before persistence"
            )
        return _persisted_decision(
            inspection,
            RawArtifactClassification.DERIVED_ANONYMIZED,
            ArtifactStorageTier.DERIVED_PROJECT,
            (ArtifactAudience.PROJECT_OPERATOR, ArtifactAudience.MODEL_GENERATION),
            default_ttl=None,
            independent_dek=False,
        )
    restricted = (
        inspection.access_class != ArtifactAccessClass.PUBLIC
        or SensitiveFinding.RESTRICTED_CONTENT in inspection.detected_findings
    )
    if restricted:
        return _persisted_decision(
            inspection,
            RawArtifactClassification.RESTRICTED_AUTHENTICATED_RAW,
            ArtifactStorageTier.RESTRICTED_INDEPENDENT_DEK,
            (ArtifactAudience.STYLE_RAW_REVIEWER, ArtifactAudience.SECURITY_AUDITOR),
            default_ttl=30,
            independent_dek=True,
        )
    return _persisted_decision(
        inspection,
        RawArtifactClassification.PUBLIC_RAW,
        ArtifactStorageTier.ENCRYPTED_RAW,
        (ArtifactAudience.INTERNAL_EVIDENCE,),
        default_ttl=90,
        independent_dek=False,
    )


def can_read_artifact(
    decision: ArtifactGovernanceDecision,
    audience: ArtifactAudience,
) -> bool:
    audience = _as_enum(audience, ArtifactAudience, "artifact audience")
    return decision.persistence_allowed and audience in decision.allowed_audiences


def assert_storage_target(
    decision: ArtifactGovernanceDecision,
    storage_tier: ArtifactStorageTier,
) -> None:
    storage_tier = _as_enum(storage_tier, ArtifactStorageTier, "artifact storage tier")
    if not decision.persistence_allowed or storage_tier != decision.storage_tier:
        raise SyntheticLabContractError("artifact cannot be written to the requested storage tier")


def create_artifact_tombstone(
    decision: ArtifactGovernanceDecision,
    *,
    deleted_at: datetime,
    legal_hold: ArtifactLegalHold | None = None,
) -> ArtifactTombstone:
    _require_aware_datetime(deleted_at, "artifact deletion time")
    if not decision.persistence_allowed or decision.expires_at is None:
        raise SyntheticLabContractError("artifact does not have a TTL deletion event")
    due_at = decision.expires_at
    if legal_hold is not None:
        if (
            legal_hold.project_id != decision.project_id
            or legal_hold.artifact_id != decision.artifact_id
        ):
            raise SyntheticLabScopeError("legal hold does not cover the artifact")
        if deleted_at < legal_hold.approved_at:
            raise SyntheticLabContractError(
                "legal hold was not active at the proposed deletion time"
            )
        if deleted_at < legal_hold.expires_at:
            raise SyntheticLabContractError("active legal hold prevents artifact deletion")
        due_at = max(due_at, legal_hold.expires_at)
    if deleted_at < due_at:
        raise SyntheticLabContractError("artifact TTL has not expired")
    return ArtifactTombstone(
        project_id=decision.project_id,
        artifact_id=decision.artifact_id,
        original_content_hash=decision.persisted_content_hash,
        classification=decision.classification,
        deleted_at=deleted_at,
        object_deleted=True,
        artifact_dek_destroyed=True,
    )


def _persisted_decision(
    inspection: RawArtifactInspection,
    classification: RawArtifactClassification,
    storage_tier: ArtifactStorageTier,
    audiences: tuple[ArtifactAudience, ...],
    *,
    default_ttl: int | None,
    independent_dek: bool,
) -> ArtifactGovernanceDecision:
    ttl = default_ttl
    if inspection.policy_max_ttl_days is not None:
        ttl = (
            inspection.policy_max_ttl_days
            if default_ttl is None
            else min(default_ttl, inspection.policy_max_ttl_days)
        )
    expires_at = inspection.captured_at + timedelta(days=ttl) if ttl is not None else None
    return ArtifactGovernanceDecision(
        artifact_id=inspection.artifact_id,
        project_id=inspection.project_id,
        captured_at=inspection.captured_at,
        classification=classification,
        persisted_content_hash=inspection.redacted_payload_hash or inspection.payload_hash,
        persistence_allowed=True,
        storage_tier=storage_tier,
        independent_dek_required=independent_dek,
        allowed_audiences=audiences,
        ttl_days=ttl,
        expires_at=expires_at,
        destroy_temporary_payload=True,
    )


__all__ = [
    "ArtifactAccessClass",
    "ArtifactAudience",
    "ArtifactForm",
    "ArtifactGovernanceDecision",
    "ArtifactLegalHold",
    "ArtifactStorageTier",
    "ArtifactTombstone",
    "RawArtifactClassification",
    "RawArtifactInspection",
    "SensitiveFinding",
    "assert_storage_target",
    "can_read_artifact",
    "create_artifact_tombstone",
    "govern_raw_artifact",
]
