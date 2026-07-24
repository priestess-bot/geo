"""Worker-only recovery contract for committed encrypted derived artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
import re
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.model_gateway.releases import DataUseDecision
from geo_core.model_gateway.schema_validation import validate_output_schema_pair


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ProviderArtifactRecoveryRequest:
    project_id: UUID
    source_model_job_id: UUID
    recovery_job_id: UUID
    lease_token: UUID
    fencing_generation: int
    model_call_attempt_id: UUID
    expected_output_hash: str
    output_schema: Mapping[str, object] = field(repr=False)
    application_output_schema: Mapping[str, object] = field(repr=False)
    purpose: str
    output_schema_hash: str = field(init=False)
    application_output_schema_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value in (
            self.project_id,
            self.source_model_job_id,
            self.recovery_job_id,
            self.lease_token,
            self.model_call_attempt_id,
        ):
            if value.int == 0:
                raise ValueError("Provider artifact recovery UUIDs cannot be zero")
        if self.fencing_generation < 1:
            raise ValueError("Provider artifact recovery fence must be positive")
        if _SHA256.fullmatch(self.expected_output_hash) is None:
            raise ValueError("Provider artifact expected output hash must be SHA-256")
        if not self.purpose.strip():
            raise ValueError("Provider artifact recovery purpose is required")
        schema = MappingProxyType(dict(self.output_schema))
        application_schema = MappingProxyType(dict(self.application_output_schema))
        validate_output_schema_pair(schema, application_schema)
        object.__setattr__(self, "output_schema", schema)
        object.__setattr__(self, "application_output_schema", application_schema)
        object.__setattr__(self, "output_schema_hash", canonical_json_hash(schema))
        object.__setattr__(
            self,
            "application_output_schema_hash",
            canonical_json_hash(application_schema),
        )

    @property
    def portable_output_schema_hash(self) -> str:
        return self.output_schema_hash


@dataclass(frozen=True, repr=False)
class RecoveredProviderArtifact:
    model_call_attempt_id: UUID
    artifact_id: UUID
    manifest_hash: str
    content_hash: str
    output_hash: str
    output: Mapping[str, object] = field(repr=False)
    recovery_receipt_id: UUID
    recovery_receipt_hash: str
    recovered_at: datetime
    bundle_lineage: RecoveredProviderArtifactBundle | None = None

    def __post_init__(self) -> None:
        for value in (
            self.model_call_attempt_id,
            self.artifact_id,
            self.recovery_receipt_id,
        ):
            if value.int == 0:
                raise ValueError("Recovered Provider artifact UUIDs cannot be zero")
        for digest in (
            self.manifest_hash,
            self.content_hash,
            self.output_hash,
            self.recovery_receipt_hash,
        ):
            if _SHA256.fullmatch(digest) is None:
                raise ValueError("Recovered Provider artifact hash must be SHA-256")
        if self.recovered_at.tzinfo is None or self.recovered_at.utcoffset() is None:
            raise ValueError("Provider artifact recovery time must be timezone-aware")
        object.__setattr__(self, "output", MappingProxyType(dict(self.output)))

    def __repr__(self) -> str:
        return (
            "RecoveredProviderArtifact("
            f"attempt_id={self.model_call_attempt_id!r}, "
            f"artifact_id={self.artifact_id!r}, output=[REDACTED])"
        )


@dataclass(frozen=True)
class RecoveredProviderArtifactBundle:
    """Non-secret metadata needed to resume a post-call durable consumer."""

    raw_manifest_reference: str
    raw_manifest_hash: str
    raw_content_hash: str
    raw_byte_size: int
    derived_manifest_reference: str
    derived_manifest_hash: str
    derived_content_hash: str
    derived_byte_size: int
    data_policy_hash: str
    storage_decision: str
    cache_decision: str
    display_decision: str
    redistribution_decision: str
    retention_days: int | None

    def __post_init__(self) -> None:
        for reference in (
            self.raw_manifest_reference,
            self.derived_manifest_reference,
        ):
            if not reference.startswith("s3://"):
                raise ValueError("Recovered Provider artifact manifest must use S3")
        for digest in (
            self.raw_manifest_hash,
            self.raw_content_hash,
            self.derived_manifest_hash,
            self.derived_content_hash,
            self.data_policy_hash,
        ):
            if _SHA256.fullmatch(digest) is None:
                raise ValueError("Recovered Provider bundle hash must be SHA-256")
        if self.raw_byte_size < 1 or self.derived_byte_size < 1:
            raise ValueError("Recovered Provider artifact sizes must be positive")
        if DataUseDecision(self.storage_decision) is not DataUseDecision.ALLOWED:
            raise ValueError("Only durably stored Provider artifacts can be recovered")
        for decision in (
            self.cache_decision,
            self.display_decision,
            self.redistribution_decision,
        ):
            DataUseDecision(decision)
        if self.retention_days is not None and self.retention_days < 0:
            raise ValueError("Recovered Provider artifact retention cannot be negative")


class ProviderArtifactRecoveryPort(Protocol):
    def recover_derived(
        self, request: ProviderArtifactRecoveryRequest
    ) -> RecoveredProviderArtifact: ...


__all__ = [
    "ProviderArtifactRecoveryPort",
    "ProviderArtifactRecoveryRequest",
    "RecoveredProviderArtifactBundle",
    "RecoveredProviderArtifact",
]
