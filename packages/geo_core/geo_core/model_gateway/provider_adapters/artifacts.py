"""Governed, encrypted Provider response artifacts for production adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import re
from typing import Protocol
from uuid import UUID, NAMESPACE_URL, uuid5

from geo_core.model_gateway.contracts import ModelAudience
from geo_core.model_gateway.artifact_lifecycle import (
    ProviderArtifactKind,
    ProviderArtifactLifecycleRepository,
    StagedProviderArtifact,
    StagedProviderArtifactBundle,
)
from geo_core.model_gateway.releases import DataUseDecision, ProviderDataPolicy
from geo_core.object_store import RetrievedObject, StoredObject
from geo_core.model_gateway.provider_adapters.artifact_security import (
    IndependentProviderArtifactEncryptor as IndependentProviderArtifactEncryptor,
    ProviderArtifactEncryptionEnvelope as ProviderArtifactEncryptionEnvelope,
    ProviderArtifactEncryptor,
    ProviderArtifactError as ProviderArtifactError,
    ProviderArtifactGovernance as ProviderArtifactGovernance,
    ProviderArtifactKeyVault as ProviderArtifactKeyVault,
    StrictProviderArtifactGovernance as StrictProviderArtifactGovernance,
    canonical_provider_json_bytes,
    decrypt_provider_artifact_payload as decrypt_provider_artifact_payload,
    provider_artifact_associated_data as provider_artifact_associated_data,
    wipe_bytearray,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
@dataclass(frozen=True, kw_only=True)
class ProviderArtifactRecord:
    manifest_reference: str | None
    manifest_hash: str
    content_hash: str
    byte_size: int
    retention_days: int | None
    expires_at: datetime | None
    storage_decision: DataUseDecision

    def __post_init__(self) -> None:
        for digest in (self.manifest_hash, self.content_hash):
            if _SHA256.fullmatch(digest) is None:
                raise ProviderArtifactError("provider artifact digest must be SHA-256")
        decision = DataUseDecision(self.storage_decision)
        object.__setattr__(self, "storage_decision", decision)
        if decision not in {DataUseDecision.ALLOWED, DataUseDecision.PROHIBITED}:
            raise ProviderArtifactError("provider artifact storage decision is unresolved")
        if decision is DataUseDecision.ALLOWED:
            if self.manifest_reference is None or not self.manifest_reference.startswith("s3://"):
                raise ProviderArtifactError("stored provider artifact requires an S3 manifest")
            if self.byte_size < 1:
                raise ProviderArtifactError("stored provider artifact size must be positive")
        elif self.manifest_reference is not None or self.byte_size != 0:
            raise ProviderArtifactError("prohibited provider artifact cannot retain stored content")
        if self.retention_days is not None and self.retention_days < 0:
            raise ProviderArtifactError("provider artifact retention cannot be negative")
        if self.expires_at is not None and (
            self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None
        ):
            raise ProviderArtifactError("provider artifact expiry must be timezone-aware")


@dataclass(frozen=True, kw_only=True)
class ProviderArtifactBundle:
    raw: ProviderArtifactRecord
    derived: ProviderArtifactRecord
    bundle_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.raw.storage_decision is not self.derived.storage_decision:
            raise ProviderArtifactError("raw and derived artifact decisions must match")
        stored = self.raw.storage_decision is DataUseDecision.ALLOWED
        if stored != (self.bundle_id is not None):
            raise ProviderArtifactError("stored artifact bundle requires a durable bundle ID")


class ProviderArtifactSink(Protocol):
    def capture(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        attempt_id: UUID,
        provider: str,
        adapter_release_id: str,
        adapter_release_hash: str,
        data_policy: ProviderDataPolicy,
        usage_purpose: str,
        usage_audience: ModelAudience,
        raw_payload: Mapping[str, object],
        raw_content_hash: str,
        derived_payload: Mapping[str, object],
    ) -> ProviderArtifactBundle: ...


class ProviderArtifactObjectStore(Protocol):
    def uri_for_key(self, key: str) -> str: ...

    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObject: ...

    def get_s3_uri(self, *, uri: str, expected_hash: str | None = None) -> RetrievedObject: ...

    def delete_s3_uri(self, *, uri: str) -> bool: ...


@dataclass(frozen=True)
class _PersistedArtifact:
    artifact_id: UUID
    kind: ProviderArtifactKind
    record: ProviderArtifactRecord
    payload_uri: str
    payload_hash: str
    stored_byte_size: int
    manifest_uri: str
    key_reference: str
    classification: str
    encryption_algorithm: str
    payload_key: str
    payload_content: bytes = field(repr=False)
    manifest_key: str
    manifest_content: bytes = field(repr=False)


class MinioProviderArtifactSink:
    """Persist encrypted content-addressed raw and derived response artifacts."""

    def __init__(
        self,
        *,
        object_store: ProviderArtifactObjectStore,
        encryptor: ProviderArtifactEncryptor,
        lifecycle_repository: ProviderArtifactLifecycleRepository,
        governance: ProviderArtifactGovernance | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = object_store
        self._encryptor = encryptor
        self._lifecycle = lifecycle_repository
        self._governance = governance or StrictProviderArtifactGovernance()
        self._clock = clock or (lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return "MinioProviderArtifactSink([REDACTED])"

    def capture(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        attempt_id: UUID,
        provider: str,
        adapter_release_id: str,
        adapter_release_hash: str,
        data_policy: ProviderDataPolicy,
        usage_purpose: str,
        usage_audience: ModelAudience,
        raw_payload: Mapping[str, object],
        raw_content_hash: str,
        derived_payload: Mapping[str, object],
    ) -> ProviderArtifactBundle:
        if (
            min(project_id.int, job_id.int, attempt_id.int) == 0
            or not provider.strip()
            or not adapter_release_id.strip()
        ):
            raise ProviderArtifactError("provider artifact identity is incomplete")
        if _SHA256.fullmatch(adapter_release_hash) is None:
            raise ProviderArtifactError("provider artifact Adapter Release hash is invalid")
        if not usage_purpose.strip():
            raise ProviderArtifactError("provider artifact usage purpose is empty")
        usage_audience = ModelAudience(usage_audience)
        actual_raw_hash = hashlib.sha256(
            canonical_provider_json_bytes(raw_payload)
        ).hexdigest()
        if not hmac.compare_digest(actual_raw_hash, raw_content_hash):
            raise ProviderArtifactError("provider raw artifact hash does not match response")
        derived_hash = hashlib.sha256(
            canonical_provider_json_bytes(derived_payload)
        ).hexdigest()
        if data_policy.storage is DataUseDecision.PROHIBITED:
            return ProviderArtifactBundle(
                raw=_withheld_record(
                    raw_content_hash, data_policy, usage_purpose, usage_audience
                ),
                derived=_withheld_record(
                    derived_hash, data_policy, usage_purpose, usage_audience
                ),
                bundle_id=None,
            )
        if data_policy.storage is not DataUseDecision.ALLOWED:
            raise ProviderArtifactError("provider artifact storage policy is unverified")

        persisted: list[_PersistedArtifact] = []
        staged = False
        bundle_id = uuid5(NAMESPACE_URL, f"geo-provider-artifact-bundle:{attempt_id}")
        staged_at = self._clock()
        if staged_at.tzinfo is None or staged_at.utcoffset() is None:
            raise ProviderArtifactError("provider artifact clock must be timezone-aware")
        expires_at = (
            staged_at + timedelta(days=data_policy.retention_days)
            if data_policy.retention_days is not None
            else None
        )
        try:
            raw = self._prepare(
                kind="raw",
                project_id=project_id,
                attempt_id=attempt_id,
                provider=provider,
                adapter_release_id=adapter_release_id,
                adapter_release_hash=adapter_release_hash,
                source_hash=raw_content_hash,
                payload=raw_payload,
                data_policy=data_policy,
                usage_purpose=usage_purpose,
                usage_audience=usage_audience,
                created_at=staged_at,
                expires_at=expires_at,
            )
            persisted.append(raw)
            derived = self._prepare(
                kind="derived",
                project_id=project_id,
                attempt_id=attempt_id,
                provider=provider,
                adapter_release_id=adapter_release_id,
                adapter_release_hash=adapter_release_hash,
                source_hash=derived_hash,
                payload=derived_payload,
                data_policy=data_policy,
                usage_purpose=usage_purpose,
                usage_audience=usage_audience,
                created_at=staged_at,
                expires_at=expires_at,
            )
            persisted.append(derived)
            self._lifecycle.stage_bundle(
                StagedProviderArtifactBundle(
                    id=bundle_id,
                    project_id=project_id,
                    job_id=job_id,
                    attempt_id=attempt_id,
                    provider=provider,
                    adapter_release_id=adapter_release_id,
                    adapter_release_hash=adapter_release_hash,
                    data_policy_hash=data_policy.data_policy_hash,
                    storage_decision=data_policy.storage.value,
                    cache_decision=data_policy.cache.value,
                    display_decision=data_policy.display.value,
                    redistribution_decision=data_policy.redistribution.value,
                    usage_purpose=usage_purpose,
                    usage_audience=usage_audience,
                    retention_days=data_policy.retention_days,
                    staged_at=staged_at,
                    expires_at=expires_at,
                    artifacts=tuple(_staged_artifact(item) for item in persisted),
                )
            )
            staged = True
            for artifact in persisted:
                self._write(artifact)
            return ProviderArtifactBundle(
                raw=raw.record,
                derived=derived.record,
                bundle_id=bundle_id,
            )
        except BaseException as exc:
            rollback_error = self._rollback(project_id=project_id, artifacts=persisted)
            if rollback_error is not None:
                message = (
                    "provider artifact cleanup is deferred to the durable staged bundle"
                    if staged
                    else "provider artifact pre-stage key cleanup failed"
                )
                raise ProviderArtifactError(message) from rollback_error
            if isinstance(exc, ProviderArtifactError):
                raise
            raise ProviderArtifactError("provider artifact persistence failed") from exc

    def _prepare(
        self,
        *,
        kind: str,
        project_id: UUID,
        attempt_id: UUID,
        provider: str,
        adapter_release_id: str,
        adapter_release_hash: str,
        source_hash: str,
        payload: Mapping[str, object],
        data_policy: ProviderDataPolicy,
        usage_purpose: str,
        usage_audience: ModelAudience,
        created_at: datetime,
        expires_at: datetime | None,
    ) -> _PersistedArtifact:
        governed = self._governance.govern(payload)
        key_reference: str | None = None
        artifact_id = uuid5(NAMESPACE_URL, f"geo-provider-artifact:{attempt_id}:{kind}")
        try:
            content_hash = hashlib.sha256(governed.payload).hexdigest()
            envelope = self._encryptor.encrypt(
                project_id=project_id,
                artifact_id=artifact_id,
                plaintext=governed.payload,
                associated_data=provider_artifact_associated_data(
                    project_id=project_id,
                    provider=provider,
                    kind=kind,
                    content_hash=content_hash,
                    adapter_release_hash=adapter_release_hash,
                ),
            )
            key_reference = envelope.key_reference
            stored_hash = hashlib.sha256(envelope.payload).hexdigest()
            base_key = (
                f"model-provider-artifacts/{project_id}/{provider}/{kind}/{content_hash}"
            )
            payload_key = f"{base_key}/payloads/{stored_hash}.bin"
            payload_uri = self._store.uri_for_key(payload_key)
            manifest = {
                "schema_version": 1,
                "project_id": str(project_id),
                "artifact_id": str(artifact_id),
                "kind": kind,
                "provider": provider,
                "adapter_release_id": adapter_release_id,
                "adapter_release_hash": adapter_release_hash,
                "classification": governed.classification,
                "source_content_hash": source_hash,
                "persisted_content_hash": content_hash,
                "stored_object_hash": stored_hash,
                "payload_uri": payload_uri,
                "content_byte_size": len(governed.payload),
                "stored_byte_size": len(envelope.payload),
                "encryption_algorithm": envelope.algorithm,
                "key_reference": envelope.key_reference,
                "retention_days": data_policy.retention_days,
                "data_policy": data_policy.canonical_value(),
                "data_policy_hash": data_policy.data_policy_hash,
                "usage_purpose": usage_purpose,
                "usage_audience": usage_audience.value,
                "created_at": created_at.isoformat(),
                "expires_at": expires_at.isoformat() if expires_at is not None else None,
            }
            manifest_bytes = canonical_provider_json_bytes(manifest)
            manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
            manifest_key = f"{base_key}/manifests/{manifest_hash}.json"
            manifest_uri = self._store.uri_for_key(manifest_key)
            return _PersistedArtifact(
                artifact_id=artifact_id,
                kind=ProviderArtifactKind(kind),
                record=ProviderArtifactRecord(
                    manifest_reference=manifest_uri,
                    manifest_hash=manifest_hash,
                    content_hash=content_hash,
                    byte_size=len(governed.payload),
                    retention_days=data_policy.retention_days,
                    expires_at=expires_at,
                    storage_decision=DataUseDecision.ALLOWED,
                ),
                payload_uri=payload_uri,
                payload_hash=stored_hash,
                stored_byte_size=len(envelope.payload),
                manifest_uri=manifest_uri,
                key_reference=envelope.key_reference,
                classification=governed.classification,
                encryption_algorithm=envelope.algorithm,
                payload_key=payload_key,
                payload_content=envelope.payload,
                manifest_key=manifest_key,
                manifest_content=manifest_bytes,
            )
        except BaseException:
            if key_reference is not None:
                self._encryptor.destroy_key(
                    project_id=project_id, key_reference=key_reference
                )
            raise
        finally:
            wipe_bytearray(governed.payload)

    def _write(self, artifact: _PersistedArtifact) -> None:
        stored = self._store.put_object(
            key=artifact.payload_key,
            content=artifact.payload_content,
            content_type="application/octet-stream",
            expected_hash=artifact.payload_hash,
        )
        if stored.uri != artifact.payload_uri:
            raise ProviderArtifactError("provider artifact payload URI changed after staging")
        self._store.get_s3_uri(
            uri=artifact.payload_uri, expected_hash=artifact.payload_hash
        )
        manifest = self._store.put_object(
            key=artifact.manifest_key,
            content=artifact.manifest_content,
            content_type="application/json",
            expected_hash=artifact.record.manifest_hash,
        )
        if manifest.uri != artifact.manifest_uri:
            raise ProviderArtifactError("provider artifact manifest URI changed after staging")
        self._store.get_s3_uri(
            uri=artifact.manifest_uri,
            expected_hash=artifact.record.manifest_hash,
        )

    def _rollback(
        self, *, project_id: UUID, artifacts: list[_PersistedArtifact]
    ) -> BaseException | None:
        failure: BaseException | None = None
        for artifact in reversed(artifacts):
            try:
                self._cleanup(
                    payload_uri=artifact.payload_uri,
                    manifest_uri=artifact.manifest_uri,
                    project_id=project_id,
                    key_reference=artifact.key_reference,
                )
            except BaseException as exc:
                failure = failure or exc
        return failure

    def _cleanup(
        self,
        *,
        project_id: UUID,
        payload_uri: str | None,
        manifest_uri: str | None,
        key_reference: str | None,
    ) -> None:
        failure: BaseException | None = None
        for uri in (manifest_uri, payload_uri):
            if uri is None:
                continue
            try:
                self._store.delete_s3_uri(uri=uri)
            except BaseException as exc:
                failure = failure or exc
        if key_reference is not None:
            try:
                self._encryptor.destroy_key(
                    project_id=project_id, key_reference=key_reference
                )
            except BaseException as exc:
                failure = failure or exc
        if failure is not None:
            raise ProviderArtifactError("provider artifact cleanup failed") from failure


def _withheld_record(
    content_hash: str,
    data_policy: ProviderDataPolicy,
    usage_purpose: str,
    usage_audience: ModelAudience,
) -> ProviderArtifactRecord:
    metadata = {
        "schema_version": 1,
        "storage_decision": "prohibited",
        "content_hash": content_hash,
        "policy_hash": data_policy.data_policy_hash,
        "data_policy": data_policy.canonical_value(),
        "usage_purpose": usage_purpose,
        "usage_audience": usage_audience.value,
    }
    return ProviderArtifactRecord(
        manifest_reference=None,
        manifest_hash=hashlib.sha256(canonical_provider_json_bytes(metadata)).hexdigest(),
        content_hash=content_hash,
        byte_size=0,
        retention_days=data_policy.retention_days,
        expires_at=None,
        storage_decision=DataUseDecision.PROHIBITED,
    )


def _staged_artifact(value: _PersistedArtifact) -> StagedProviderArtifact:
    try:
        key_reference = UUID(value.key_reference)
    except ValueError:
        raise ProviderArtifactError("Provider artifact key reference must be a UUID") from None
    return StagedProviderArtifact(
        artifact_id=value.artifact_id,
        kind=value.kind,
        manifest_uri=value.manifest_uri,
        manifest_hash=value.record.manifest_hash,
        content_hash=value.record.content_hash,
        payload_uri=value.payload_uri,
        payload_hash=value.payload_hash,
        content_byte_size=value.record.byte_size,
        stored_byte_size=value.stored_byte_size,
        classification=value.classification,
        encryption_algorithm=value.encryption_algorithm,
        key_reference=key_reference,
        expires_at=value.record.expires_at,
    )


__all__ = [
    "IndependentProviderArtifactEncryptor",
    "MinioProviderArtifactSink",
    "ProviderArtifactBundle",
    "ProviderArtifactEncryptionEnvelope",
    "ProviderArtifactError",
    "ProviderArtifactGovernance",
    "ProviderArtifactKeyVault",
    "ProviderArtifactObjectStore",
    "ProviderArtifactRecord",
    "ProviderArtifactSink",
    "StrictProviderArtifactGovernance",
    "decrypt_provider_artifact_payload",
    "provider_artifact_associated_data",
]
