"""Safe metadata-only contracts for governed raw artifact persistence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.object_store import StoredObject
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.domain import (
    SyntheticLabContractError,
    _as_enum,
    _require_aware_datetime,
    _require_hash,
    _require_text,
    _require_uuid,
)
from geo_core.synthetic_lab.raw_artifact_governance import (
    ArtifactGovernanceDecision,
    ArtifactStorageTier,
    ArtifactTombstone,
    RawArtifactClassification,
    RawArtifactInspection,
)


class RawArtifactStorageError(RuntimeError):
    """A governed artifact could not be durably stored without exposing content."""


@dataclass(frozen=True, kw_only=True)
class RawArtifactWriteRequest:
    lease: WorkerLease
    inspection: RawArtifactInspection
    payload: bytearray = field(repr=False)
    media_type: str
    source_identity_hash: str
    record_count: int
    producer_release: str

    def __post_init__(self) -> None:
        if self.lease.project_id != self.inspection.project_id:
            raise SyntheticLabContractError("artifact write crosses Project scope")
        if not isinstance(self.payload, bytearray):
            raise SyntheticLabContractError("artifact temporary payload must be mutable")
        _require_text(self.media_type, "artifact media type")
        _require_hash(self.source_identity_hash, "artifact source identity")
        if self.record_count < 0:
            raise SyntheticLabContractError("artifact record count cannot be negative")
        _require_text(self.producer_release, "artifact producer release")


@dataclass(frozen=True, kw_only=True)
class ArtifactEncryptionEnvelope:
    payload: bytes = field(repr=False)
    key_ref: str
    algorithm: str

    def __post_init__(self) -> None:
        if not self.payload:
            raise SyntheticLabContractError("encrypted artifact payload is empty")
        _require_text(self.key_ref, "artifact DEK reference")
        _require_text(self.algorithm, "artifact encryption algorithm")


@dataclass(frozen=True, kw_only=True)
class TierEncryptionEnvelope:
    payload: bytes = field(repr=False)
    key_version: str
    algorithm: str

    def __post_init__(self) -> None:
        if not self.payload:
            raise SyntheticLabContractError("tier-encrypted artifact payload is empty")
        _require_text(self.key_version, "artifact tier key version")
        _require_text(self.algorithm, "artifact tier encryption algorithm")


@dataclass(frozen=True, kw_only=True)
class RawArtifactManifest:
    schema_version: int
    project_id: UUID
    artifact_id: UUID
    job_id: UUID
    fencing_generation: int
    classification: RawArtifactClassification
    storage_tier: ArtifactStorageTier
    persisted_content_hash: str
    stored_object_hash: str
    payload_uri: str
    media_type: str
    byte_size: int
    record_count: int
    source_identity_hash: str
    producer_release: str
    encryption_algorithm: str
    artifact_key_ref: str | None
    tier_key_version: str | None
    captured_at: datetime
    created_at: datetime
    ttl_days: int | None
    expires_at: datetime | None
    customer_visible: bool = field(default=False, init=False)
    general_export_allowed: bool = field(default=False, init=False)
    manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise SyntheticLabContractError("unsupported raw artifact manifest schema")
        for uuid_value, label in (
            (self.project_id, "artifact manifest Project"),
            (self.artifact_id, "artifact manifest artifact"),
            (self.job_id, "artifact manifest Job"),
        ):
            _require_uuid(uuid_value, label)
        if self.fencing_generation < 1:
            raise SyntheticLabContractError("artifact manifest fencing generation is invalid")
        classification = _as_enum(
            self.classification,
            RawArtifactClassification,
            "artifact manifest classification",
        )
        tier = _as_enum(self.storage_tier, ArtifactStorageTier, "artifact manifest tier")
        object.__setattr__(self, "classification", classification)
        object.__setattr__(self, "storage_tier", tier)
        for hash_value, label in (
            (self.persisted_content_hash, "persisted artifact content"),
            (self.stored_object_hash, "stored artifact object"),
            (self.source_identity_hash, "artifact source identity"),
        ):
            _require_hash(hash_value, label)
        for text_value, label in (
            (self.payload_uri, "artifact payload URI"),
            (self.media_type, "artifact media type"),
            (self.producer_release, "artifact producer release"),
            (self.encryption_algorithm, "artifact encryption algorithm"),
        ):
            _require_text(text_value, label)
        if not self.payload_uri.startswith("s3://"):
            raise SyntheticLabContractError("artifact payload URI must be S3-compatible")
        if self.byte_size < 1 or self.record_count < 0:
            raise SyntheticLabContractError("artifact manifest size/count is invalid")
        _require_aware_datetime(self.captured_at, "artifact manifest capture time")
        _require_aware_datetime(self.created_at, "artifact manifest creation time")
        if self.expires_at is not None:
            _require_aware_datetime(self.expires_at, "artifact manifest expiry")
        restricted = tier is ArtifactStorageTier.RESTRICTED_INDEPENDENT_DEK
        if restricted != (self.artifact_key_ref is not None) or restricted == (
            self.tier_key_version is not None
        ):
            raise SyntheticLabContractError(
                "restricted DEK and project tier key metadata must be mutually exclusive"
            )
        if self.artifact_key_ref is not None:
            _require_text(self.artifact_key_ref, "artifact DEK reference")
        if self.tier_key_version is not None:
            _require_text(self.tier_key_version, "artifact tier key version")
        object.__setattr__(self, "manifest_hash", canonical_hash(self.value()))

    def value(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "artifact_id": self.artifact_id,
            "job_id": self.job_id,
            "fencing_generation": self.fencing_generation,
            "classification": self.classification,
            "storage_tier": self.storage_tier,
            "persisted_content_hash": self.persisted_content_hash,
            "stored_object_hash": self.stored_object_hash,
            "payload_uri": self.payload_uri,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "record_count": self.record_count,
            "source_identity_hash": self.source_identity_hash,
            "producer_release": self.producer_release,
            "encryption_algorithm": self.encryption_algorithm,
            "artifact_key_ref": self.artifact_key_ref,
            "tier_key_version": self.tier_key_version,
            "captured_at": self.captured_at,
            "created_at": self.created_at,
            "ttl_days": self.ttl_days,
            "expires_at": self.expires_at,
            "customer_visible": False,
            "general_export_allowed": False,
        }


@dataclass(frozen=True, kw_only=True)
class PersistedRawArtifact:
    decision: ArtifactGovernanceDecision
    manifest: RawArtifactManifest
    manifest_uri: str

    def __post_init__(self) -> None:
        if (
            self.decision.project_id != self.manifest.project_id
            or self.decision.artifact_id != self.manifest.artifact_id
            or self.decision.persisted_content_hash != self.manifest.persisted_content_hash
        ):
            raise SyntheticLabContractError("persisted artifact metadata is inconsistent")
        if not self.manifest_uri.startswith("s3://"):
            raise SyntheticLabContractError("artifact manifest URI must be S3-compatible")


@dataclass(frozen=True, kw_only=True)
class RawArtifactWriteResult:
    decision: ArtifactGovernanceDecision
    persisted: PersistedRawArtifact | None

    def __post_init__(self) -> None:
        if self.decision.persistence_allowed != (self.persisted is not None):
            raise SyntheticLabContractError("artifact write result contradicts governance")


@dataclass(frozen=True, kw_only=True)
class ArtifactDeletionIntent:
    project_id: UUID
    artifact_id: UUID
    tombstone_hash: str
    fencing_generation: int
    intent_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "artifact deletion intent Project")
        _require_uuid(self.artifact_id, "artifact deletion intent artifact")
        _require_hash(self.tombstone_hash, "artifact deletion intent tombstone")
        if self.fencing_generation < 1:
            raise SyntheticLabContractError("artifact deletion fencing generation is invalid")
        object.__setattr__(
            self,
            "intent_hash",
            canonical_hash(
                {
                    "project_id": self.project_id,
                    "artifact_id": self.artifact_id,
                    "tombstone_hash": self.tombstone_hash,
                    "fencing_generation": self.fencing_generation,
                }
            ),
        )


class RawArtifactObjectStorePort(Protocol):
    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObject: ...

    def delete_s3_uri(self, *, uri: str) -> bool: ...


class ArtifactEncryptorPort(Protocol):
    def encrypt(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        fencing_generation: int,
        plaintext: bytearray,
        associated_data: bytes,
    ) -> ArtifactEncryptionEnvelope: ...

    def destroy_key(self, key_ref: str) -> None: ...


class ArtifactTierEncryptorPort(Protocol):
    def encrypt(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        storage_tier: ArtifactStorageTier,
        plaintext: bytearray,
        associated_data: bytes,
    ) -> TierEncryptionEnvelope: ...


class RawArtifactManifestRepositoryPort(Protocol):
    """Implementations must validate the lease in a fenced transaction."""

    def record_rejection(
        self,
        *,
        lease: WorkerLease,
        decision: ArtifactGovernanceDecision,
    ) -> None: ...

    def commit_persisted(
        self,
        *,
        lease: WorkerLease,
        artifact: PersistedRawArtifact,
    ) -> None: ...

    def begin_deletion(
        self,
        *,
        lease: WorkerLease,
        artifact: PersistedRawArtifact,
        tombstone: ArtifactTombstone,
    ) -> ArtifactDeletionIntent:
        """Fence the lease and make the artifact unreadable before object deletion."""

    def complete_tombstone(
        self,
        *,
        lease: WorkerLease,
        intent: ArtifactDeletionIntent,
        tombstone: ArtifactTombstone,
    ) -> None: ...


class ArtifactDekVaultPort(Protocol):
    """Wrap a DEK before returning; never retain the mutable input buffer."""

    def store_wrapped_key(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        fencing_generation: int,
        key_material: bytearray,
    ) -> str: ...

    def destroy_wrapped_key(self, key_ref: str) -> None: ...


def storage_manifest_hash(value: Mapping[str, object]) -> str:
    return canonical_hash(value)


__all__ = [
    "ArtifactDekVaultPort",
    "ArtifactDeletionIntent",
    "ArtifactEncryptionEnvelope",
    "ArtifactEncryptorPort",
    "ArtifactTierEncryptorPort",
    "PersistedRawArtifact",
    "RawArtifactManifest",
    "RawArtifactManifestRepositoryPort",
    "RawArtifactObjectStorePort",
    "RawArtifactStorageError",
    "RawArtifactWriteRequest",
    "RawArtifactWriteResult",
    "TierEncryptionEnvelope",
    "storage_manifest_hash",
]
