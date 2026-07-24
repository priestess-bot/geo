"""Durable metadata contracts for staged Provider artifact bundles and deletion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from typing import Protocol
from uuid import UUID

from geo_core.model_gateway.contracts import ModelAudience


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProviderArtifactKind(StrEnum):
    RAW = "raw"
    DERIVED = "derived"


class ProviderArtifactBundleStatus(StrEnum):
    STAGED = "staged"
    COMMITTED = "committed"
    ORPHANED = "orphaned"
    DELETION_PENDING = "deletion_pending"
    DELETED = "deleted"


class ProviderArtifactDeletionReason(StrEnum):
    ORPHANED = "orphaned"
    RETENTION_EXPIRED = "retention_expired"
    MANUAL = "manual"


@dataclass(frozen=True)
class StagedProviderArtifact:
    artifact_id: UUID
    kind: ProviderArtifactKind
    manifest_uri: str
    manifest_hash: str
    content_hash: str
    payload_uri: str
    payload_hash: str
    content_byte_size: int
    stored_byte_size: int
    classification: str
    encryption_algorithm: str
    key_reference: UUID
    expires_at: datetime | None

    def __post_init__(self) -> None:
        if self.artifact_id.int == 0 or self.key_reference.int == 0:
            raise ValueError("Provider artifact/key identity cannot be zero")
        object.__setattr__(self, "kind", ProviderArtifactKind(self.kind))
        for uri in (self.manifest_uri, self.payload_uri):
            if not uri.startswith("s3://"):
                raise ValueError("Provider artifact URI must be S3-compatible")
        for digest in (self.manifest_hash, self.content_hash, self.payload_hash):
            if _SHA256.fullmatch(digest) is None:
                raise ValueError("Provider artifact digest must be SHA-256")
        if self.content_byte_size < 1 or self.stored_byte_size < 1:
            raise ValueError("Provider artifact sizes must be positive")
        if not self.classification.strip() or not self.encryption_algorithm.strip():
            raise ValueError("Provider artifact governance/encryption metadata is required")
        _aware_optional(self.expires_at, "Provider artifact expiry")


@dataclass(frozen=True)
class StagedProviderArtifactBundle:
    id: UUID
    project_id: UUID
    job_id: UUID
    attempt_id: UUID
    provider: str
    adapter_release_id: str
    adapter_release_hash: str
    data_policy_hash: str
    storage_decision: str
    cache_decision: str
    display_decision: str
    redistribution_decision: str
    usage_purpose: str
    usage_audience: ModelAudience
    retention_days: int | None
    staged_at: datetime
    expires_at: datetime | None
    artifacts: tuple[StagedProviderArtifact, ...]

    def __post_init__(self) -> None:
        if min(self.id.int, self.project_id.int, self.job_id.int, self.attempt_id.int) == 0:
            raise ValueError("Provider artifact bundle identities cannot be zero")
        for value in (self.provider, self.adapter_release_id, self.usage_purpose):
            if not value.strip():
                raise ValueError("Provider artifact bundle text identity cannot be empty")
        for digest in (self.adapter_release_hash, self.data_policy_hash):
            if _SHA256.fullmatch(digest) is None:
                raise ValueError("Provider artifact bundle hash must be SHA-256")
        decisions = (
            self.storage_decision,
            self.cache_decision,
            self.display_decision,
            self.redistribution_decision,
        )
        if any(value not in {"allowed", "prohibited"} for value in decisions):
            raise ValueError("Provider artifact bundle policy decision is invalid")
        if self.storage_decision != "allowed":
            raise ValueError("only storage-allowed Provider artifacts may be staged")
        object.__setattr__(self, "usage_audience", ModelAudience(self.usage_audience))
        if self.retention_days is not None and self.retention_days < 0:
            raise ValueError("Provider artifact retention cannot be negative")
        _aware(self.staged_at, "Provider artifact staging time")
        _aware_optional(self.expires_at, "Provider artifact bundle expiry")
        if {item.kind for item in self.artifacts} != {
            ProviderArtifactKind.RAW,
            ProviderArtifactKind.DERIVED,
        }:
            raise ValueError("Provider artifact bundle requires exactly raw and derived artifacts")


@dataclass(frozen=True)
class ProviderArtifactDeletionLease:
    outbox_id: UUID
    bundle_id: UUID
    project_id: UUID
    reason: ProviderArtifactDeletionReason
    lease_token: UUID
    fencing_generation: int
    lease_expires_at: datetime
    artifacts: tuple[StagedProviderArtifact, ...]

    def __post_init__(self) -> None:
        if min(
            self.outbox_id.int,
            self.bundle_id.int,
            self.project_id.int,
            self.lease_token.int,
        ) == 0:
            raise ValueError("Provider artifact deletion identities cannot be zero")
        object.__setattr__(self, "reason", ProviderArtifactDeletionReason(self.reason))
        if self.fencing_generation < 1:
            raise ValueError("Provider artifact deletion fence must be positive")
        _aware(self.lease_expires_at, "Provider artifact deletion lease expiry")
        if not self.artifacts:
            raise ValueError("Provider artifact deletion lease has no artifacts")


@dataclass(frozen=True)
class ProviderArtifactDeletionReceipt:
    lease: ProviderArtifactDeletionLease
    deletion_receipt_hash: str
    deleted_at: datetime

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.deletion_receipt_hash) is None:
            raise ValueError("Provider artifact deletion receipt must be SHA-256")
        _aware(self.deleted_at, "Provider artifact deletion time")


class ProviderArtifactLifecycleRepository(Protocol):
    def stage_bundle(self, bundle: StagedProviderArtifactBundle) -> None: ...

    def destroy_unstaged_keys(self, *, now: datetime, grace_seconds: int) -> int: ...

    def enqueue_expired(
        self, *, now: datetime, staged_grace_seconds: int
    ) -> int: ...

    def claim_deletions(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        limit: int,
    ) -> tuple[ProviderArtifactDeletionLease, ...]: ...

    def complete_deletion(self, receipt: ProviderArtifactDeletionReceipt) -> None: ...

    def fail_deletion(
        self,
        lease: ProviderArtifactDeletionLease,
        *,
        now: datetime,
        error_code: str,
    ) -> None: ...


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _aware_optional(value: datetime | None, label: str) -> None:
    if value is not None:
        _aware(value, label)


__all__ = [
    "ProviderArtifactBundleStatus",
    "ProviderArtifactDeletionLease",
    "ProviderArtifactDeletionReason",
    "ProviderArtifactDeletionReceipt",
    "ProviderArtifactKind",
    "ProviderArtifactLifecycleRepository",
    "StagedProviderArtifact",
    "StagedProviderArtifactBundle",
]
