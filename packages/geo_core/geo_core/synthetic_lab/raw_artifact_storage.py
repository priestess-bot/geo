"""Governed raw artifact persistence before any object-store write."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
import hashlib
import hmac
import json
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.synthetic_lab.raw_artifact_governance import (
    ArtifactLegalHold,
    ArtifactStorageTier,
    ArtifactTombstone,
    RawArtifactClassification,
    assert_storage_target,
    create_artifact_tombstone,
    govern_raw_artifact,
)
from geo_core.synthetic_lab.raw_artifact_storage_contracts import (
    ArtifactEncryptorPort,
    ArtifactTierEncryptorPort,
    ArtifactDeletionIntent,
    PersistedRawArtifact,
    RawArtifactManifest,
    RawArtifactManifestRepositoryPort,
    RawArtifactObjectStorePort,
    RawArtifactStorageError,
    RawArtifactWriteRequest,
    RawArtifactWriteResult,
)


@dataclass(frozen=True, kw_only=True)
class RawArtifactStores:
    encrypted_raw: RawArtifactObjectStorePort
    restricted_independent_dek: RawArtifactObjectStorePort
    derived_project: RawArtifactObjectStorePort

    def for_tier(self, tier: ArtifactStorageTier) -> RawArtifactObjectStorePort:
        stores = {
            ArtifactStorageTier.ENCRYPTED_RAW: self.encrypted_raw,
            ArtifactStorageTier.RESTRICTED_INDEPENDENT_DEK: self.restricted_independent_dek,
            ArtifactStorageTier.DERIVED_PROJECT: self.derived_project,
        }
        try:
            return stores[tier]
        except KeyError as error:
            raise RawArtifactStorageError("governance selected no writable storage tier") from error


class GovernedRawArtifactStorage:
    def __init__(
        self,
        *,
        stores: RawArtifactStores,
        encryptor: ArtifactEncryptorPort,
        tier_encryptor: ArtifactTierEncryptorPort,
        repository: RawArtifactManifestRepositoryPort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._stores = stores
        self._encryptor = encryptor
        self._tier_encryptor = tier_encryptor
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def persist(self, request: RawArtifactWriteRequest) -> RawArtifactWriteResult:
        payload_uri: str | None = None
        manifest_uri: str | None = None
        key_ref: str | None = None
        store: RawArtifactObjectStorePort | None = None
        try:
            decision = govern_raw_artifact(request.inspection)
            content_hash = hashlib.sha256(request.payload).hexdigest()
            if not hmac.compare_digest(content_hash, decision.persisted_content_hash):
                raise RawArtifactStorageError("temporary payload does not match inspected content")
            if not decision.persistence_allowed:
                self._repository.record_rejection(lease=request.lease, decision=decision)
                return RawArtifactWriteResult(decision=decision, persisted=None)

            assert_storage_target(decision, decision.storage_tier)
            store = self._stores.for_tier(decision.storage_tier)
            stored_payload: bytes
            tier_key_version: str | None = None
            if decision.classification is RawArtifactClassification.RESTRICTED_AUTHENTICATED_RAW:
                artifact_envelope = self._encryptor.encrypt(
                    project_id=request.inspection.project_id,
                    artifact_id=request.inspection.artifact_id,
                    fencing_generation=request.lease.fencing_generation,
                    plaintext=request.payload,
                    associated_data=_encryption_aad(request, decision.persisted_content_hash),
                )
                stored_payload = artifact_envelope.payload
                key_ref = artifact_envelope.key_ref
                encryption_algorithm = artifact_envelope.algorithm
            else:
                tier_envelope = self._tier_encryptor.encrypt(
                    project_id=request.inspection.project_id,
                    artifact_id=request.inspection.artifact_id,
                    storage_tier=decision.storage_tier,
                    plaintext=request.payload,
                    associated_data=_encryption_aad(request, decision.persisted_content_hash),
                )
                stored_payload = tier_envelope.payload
                tier_key_version = tier_envelope.key_version
                encryption_algorithm = tier_envelope.algorithm

            stored_hash = hashlib.sha256(stored_payload).hexdigest()
            base_key = _artifact_base_key(
                request.inspection.project_id,
                request.inspection.artifact_id,
                request.lease.fencing_generation,
            )
            stored = store.put_object(
                key=f"{base_key}/payloads/{stored_hash}.bin",
                content=stored_payload,
                content_type="application/octet-stream",
                expected_hash=stored_hash,
            )
            payload_uri = stored.uri
            if not hmac.compare_digest(stored.content_hash, stored_hash):
                raise RawArtifactStorageError("object store changed the uploaded payload hash")

            manifest = RawArtifactManifest(
                schema_version=1,
                project_id=request.inspection.project_id,
                artifact_id=request.inspection.artifact_id,
                job_id=request.lease.job_id,
                fencing_generation=request.lease.fencing_generation,
                classification=decision.classification,
                storage_tier=decision.storage_tier,
                persisted_content_hash=decision.persisted_content_hash,
                stored_object_hash=stored_hash,
                payload_uri=stored.uri,
                media_type=request.media_type,
                byte_size=len(stored_payload),
                record_count=request.record_count,
                source_identity_hash=request.source_identity_hash,
                producer_release=request.producer_release,
                encryption_algorithm=encryption_algorithm,
                artifact_key_ref=key_ref,
                tier_key_version=tier_key_version,
                captured_at=request.inspection.captured_at,
                created_at=self._clock(),
                ttl_days=decision.ttl_days,
                expires_at=decision.expires_at,
            )
            manifest_bytes = _canonical_json_bytes(manifest.value())
            actual_manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
            if not hmac.compare_digest(actual_manifest_hash, manifest.manifest_hash):
                raise RawArtifactStorageError("artifact manifest canonical hash mismatch")
            stored_manifest = store.put_object(
                key=f"{base_key}/manifests/{manifest.manifest_hash}.json",
                content=manifest_bytes,
                content_type="application/json",
                expected_hash=manifest.manifest_hash,
            )
            manifest_uri = stored_manifest.uri
            if not hmac.compare_digest(
                stored_manifest.content_hash,
                manifest.manifest_hash,
            ):
                raise RawArtifactStorageError("object store changed the uploaded manifest hash")
            artifact = PersistedRawArtifact(
                decision=decision,
                manifest=manifest,
                manifest_uri=stored_manifest.uri,
            )
            self._repository.commit_persisted(lease=request.lease, artifact=artifact)
            return RawArtifactWriteResult(decision=decision, persisted=artifact)
        except BaseException as error:
            cleanup_error = self._rollback(
                store=store,
                payload_uri=payload_uri,
                manifest_uri=manifest_uri,
                key_ref=key_ref,
            )
            if cleanup_error is not None:
                raise RawArtifactStorageError(
                    "artifact rollback could not fully destroy stored material"
                ) from cleanup_error
            raise error
        finally:
            _wipe(request.payload)

    def expire(
        self,
        *,
        lease: WorkerLease,
        artifact: PersistedRawArtifact,
        deleted_at: datetime,
        legal_hold: ArtifactLegalHold | None = None,
    ) -> ArtifactTombstone:
        tombstone = create_artifact_tombstone(
            artifact.decision,
            deleted_at=deleted_at,
            legal_hold=legal_hold,
        )
        intent = self._repository.begin_deletion(
            lease=lease,
            artifact=artifact,
            tombstone=tombstone,
        )
        _assert_deletion_intent(intent, lease, artifact, tombstone)
        store = self._stores.for_tier(artifact.manifest.storage_tier)
        store.delete_s3_uri(uri=artifact.manifest.payload_uri)
        store.delete_s3_uri(uri=artifact.manifest_uri)
        if artifact.manifest.artifact_key_ref is not None:
            self._encryptor.destroy_key(artifact.manifest.artifact_key_ref)
        self._repository.complete_tombstone(
            lease=lease,
            intent=intent,
            tombstone=tombstone,
        )
        return tombstone

    def _rollback(
        self,
        *,
        store: RawArtifactObjectStorePort | None,
        payload_uri: str | None,
        manifest_uri: str | None,
        key_ref: str | None,
    ) -> BaseException | None:
        failure: BaseException | None = None
        if store is not None:
            for uri in (manifest_uri, payload_uri):
                if uri is None:
                    continue
                try:
                    store.delete_s3_uri(uri=uri)
                except BaseException as error:
                    failure = failure or error
        if key_ref is not None:
            try:
                self._encryptor.destroy_key(key_ref)
            except BaseException as error:
                failure = failure or error
        return failure


def _artifact_base_key(project_id: UUID, artifact_id: UUID, generation: int) -> str:
    return f"synthetic-raw/{project_id}/{artifact_id}/generation-{generation}"


def _assert_deletion_intent(
    intent: ArtifactDeletionIntent,
    lease: WorkerLease,
    artifact: PersistedRawArtifact,
    tombstone: ArtifactTombstone,
) -> None:
    if (
        intent.project_id != lease.project_id
        or intent.artifact_id != artifact.decision.artifact_id
        or intent.tombstone_hash != tombstone.tombstone_hash
        or intent.fencing_generation != lease.fencing_generation
    ):
        raise RawArtifactStorageError("artifact deletion intent changed fenced ownership")


def _encryption_aad(request: RawArtifactWriteRequest, content_hash: str) -> bytes:
    return artifact_encryption_aad(
        project_id=request.inspection.project_id,
        artifact_id=request.inspection.artifact_id,
        job_id=request.lease.job_id,
        content_hash=content_hash,
        captured_at=request.inspection.captured_at,
    )


def artifact_encryption_aad(
    *,
    project_id: UUID,
    artifact_id: UUID,
    job_id: UUID,
    content_hash: str,
    captured_at: datetime,
) -> bytes:
    return _canonical_json_bytes(
        {
            "project_id": project_id,
            "artifact_id": artifact_id,
            "job_id": job_id,
            "content_hash": content_hash,
            "captured_at": captured_at,
        }
    )


def _canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("artifact manifest contains a non-serializable metadata type")


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = ["GovernedRawArtifactStorage", "RawArtifactStores", "artifact_encryption_aad"]
