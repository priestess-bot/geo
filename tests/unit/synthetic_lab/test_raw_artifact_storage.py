from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
from uuid import UUID, uuid4

import pytest

from geo_core.jobs.postgres import WorkerLease
from geo_core.jobs.postgres import LostJobLease
from geo_core.object_store import ObjectStoreError, RetrievedObject, StoredObject
from geo_core.secrets.models import SecretValue
from geo_core.synthetic_lab.domain import SyntheticLabContractError
from geo_core.synthetic_lab.raw_artifact_crypto import (
    IndependentDekArtifactEncryptor,
    ProjectTierArtifactEncryptor,
)
from geo_core.synthetic_lab.raw_artifact_governance import (
    ArtifactAccessClass,
    ArtifactForm,
    ArtifactLegalHold,
    RawArtifactInspection,
    SensitiveFinding,
)
from geo_core.synthetic_lab.raw_artifact_storage import (
    GovernedRawArtifactStorage,
    RawArtifactStores,
)
from geo_core.synthetic_lab.raw_artifact_storage_contracts import (
    ArtifactGovernanceDecision,
    ArtifactDeletionIntent,
    PersistedRawArtifact,
    RawArtifactWriteRequest,
)


PROJECT_ID = UUID("10000000-0000-0000-0000-000000000001")
CAPTURED_AT = datetime(2026, 7, 23, 8, tzinfo=UTC)


class MemoryObjectStore:
    def __init__(self, bucket: str) -> None:
        self.bucket = bucket
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.puts: list[str] = []
        self.gets: list[str] = []
        self.deletes: list[str] = []
        self.fail_next_delete = False

    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObject:
        value = content.encode() if isinstance(content, str) else content
        actual = hashlib.sha256(value).hexdigest()
        assert expected_hash in {None, actual}
        self.objects[key] = (value, content_type)
        self.puts.append(key)
        return StoredObject(
            uri=f"s3://{self.bucket}/{key}",
            bucket=self.bucket,
            key=key,
            content_type=content_type,
            content_hash=actual,
            etag=None,
        )

    def get_s3_uri(self, *, uri: str, expected_hash: str | None = None) -> RetrievedObject:
        prefix = f"s3://{self.bucket}/"
        assert uri.startswith(prefix)
        key = uri.removeprefix(prefix)
        value, content_type = self.objects[key]
        actual = hashlib.sha256(value).hexdigest()
        assert expected_hash in {None, actual}
        self.gets.append(key)
        return RetrievedObject(value, self.bucket, key, content_type, actual, None)

    def delete_s3_uri(self, *, uri: str) -> bool:
        if self.fail_next_delete:
            self.fail_next_delete = False
            raise ObjectStoreError("delete fixture failed")
        prefix = f"s3://{self.bucket}/"
        assert uri.startswith(prefix)
        key = uri.removeprefix(prefix)
        self.objects.pop(key, None)
        self.deletes.append(key)
        return True


class MemoryDekVault:
    def __init__(self) -> None:
        self.keys: dict[str, bytes] = {}
        self.destroyed: list[str] = []

    def store_wrapped_key(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        fencing_generation: int,
        key_material: bytearray,
    ) -> str:
        key_ref = f"dek://{project_id}/{artifact_id}/{fencing_generation}/{len(self.keys) + 1}"
        self.keys[key_ref] = bytes(key_material)
        return key_ref

    def destroy_wrapped_key(self, key_ref: str) -> None:
        self.keys.pop(key_ref, None)
        self.destroyed.append(key_ref)


class MemoryTierKeyResolver:
    def resolve(self, *, project_id, storage_tier):
        return f"project-tier-v1:{project_id}:{storage_tier.value}", SecretValue(b"t" * 32)


class MemoryManifestRepository:
    def __init__(self) -> None:
        self.rejections: list[tuple[WorkerLease, ArtifactGovernanceDecision]] = []
        self.artifacts: list[tuple[WorkerLease, PersistedRawArtifact]] = []
        self.tombstones: list[object] = []
        self.deletion_intents: list[ArtifactDeletionIntent] = []
        self.fail_persist = False
        self.persist_hook = None
        self.reject_deletion_lease = False

    def record_rejection(
        self,
        *,
        lease: WorkerLease,
        decision: ArtifactGovernanceDecision,
    ) -> None:
        self.rejections.append((lease, decision))

    def commit_persisted(
        self,
        *,
        lease: WorkerLease,
        artifact: PersistedRawArtifact,
    ) -> None:
        if self.persist_hook is not None:
            self.persist_hook(lease, artifact)
        if self.fail_persist:
            raise RuntimeError("database fixture failure")
        self.artifacts.append((lease, artifact))

    def begin_deletion(self, *, lease, artifact, tombstone):
        del artifact
        if self.reject_deletion_lease:
            raise LostJobLease("stale deletion fixture")
        intent = ArtifactDeletionIntent(
            project_id=lease.project_id,
            artifact_id=tombstone.artifact_id,
            tombstone_hash=tombstone.tombstone_hash,
            fencing_generation=lease.fencing_generation,
        )
        self.deletion_intents.append(intent)
        return intent

    def complete_tombstone(self, *, lease, intent, tombstone) -> None:
        self.tombstones.append((lease, intent, tombstone))


def test_rejected_secret_bearing_payload_never_reaches_any_object_store() -> None:
    runtime = _runtime()
    payload = bytearray(b"cookie=session-secret")
    inspection = _inspection(
        payload,
        access_class=ArtifactAccessClass.AUTHENTICATED,
        detected=(SensitiveFinding.COOKIE,),
        unresolved=(SensitiveFinding.COOKIE,),
    )

    result = runtime.service.persist(_request(payload, inspection))

    assert result.persisted is None
    assert len(runtime.repository.rejections) == 1
    assert not runtime.public.objects
    assert not runtime.restricted.objects
    assert not runtime.derived.objects
    assert payload == bytearray(len(payload))


def test_restricted_payload_uses_isolated_store_and_unique_dek_without_plaintext() -> None:
    runtime = _runtime()
    plaintext = b"authenticated account page content"
    records = []
    for _ in range(2):
        payload = bytearray(plaintext)
        inspection = _inspection(
            payload,
            access_class=ArtifactAccessClass.AUTHENTICATED,
            detected=(SensitiveFinding.RESTRICTED_CONTENT,),
        )
        records.append(runtime.service.persist(_request(payload, inspection)).persisted)
        assert payload == bytearray(len(payload))

    first, second = records
    assert first is not None and second is not None
    assert not runtime.public.objects and not runtime.derived.objects
    assert len(runtime.restricted.puts) == 4
    # The Style writer validates the object hash returned by PUT and has no
    # object-read capability for authenticated raw captures.
    assert not runtime.restricted.gets
    stored_bytes = b"".join(value for value, _media in runtime.restricted.objects.values())
    assert plaintext not in stored_bytes
    assert first.manifest.stored_object_hash != second.manifest.stored_object_hash
    assert first.manifest.artifact_key_ref != second.manifest.artifact_key_ref
    assert len(runtime.vault.keys) == 2
    assert first.manifest.customer_visible is False
    assert first.manifest.general_export_allowed is False
    assert first.manifest_uri.endswith(f"/{first.manifest.manifest_hash}.json")


@pytest.mark.parametrize(
    ("access_class", "form", "detected", "store_name"),
    [
        (ArtifactAccessClass.PUBLIC, ArtifactForm.RAW, (), "public"),
        (
            ArtifactAccessClass.AUTHENTICATED,
            ArtifactForm.RAW,
            (SensitiveFinding.RESTRICTED_CONTENT,),
            "restricted",
        ),
        (ArtifactAccessClass.PUBLIC, ArtifactForm.DERIVED, (), "derived"),
    ],
)
def test_every_encrypted_payload_uses_octet_stream_content_type(
    access_class, form, detected, store_name
) -> None:
    runtime = _runtime()
    payload = bytearray(b"governed artifact body")
    inspection = _inspection(
        payload,
        access_class=access_class,
        form=form,
        detected=detected,
    )

    persisted = runtime.service.persist(_request(payload, inspection)).persisted

    assert persisted is not None
    store = getattr(runtime, store_name)
    payload_types = [
        media_type for key, (_content, media_type) in store.objects.items() if key.endswith(".bin")
    ]
    assert payload_types == ["application/octet-stream"]
    assert persisted.manifest.media_type == "text/html"


def test_failed_manifest_commit_removes_objects_and_destroys_restricted_dek() -> None:
    runtime = _runtime()
    runtime.repository.fail_persist = True
    payload = bytearray(b"restricted body")
    inspection = _inspection(
        payload,
        access_class=ArtifactAccessClass.AUTHENTICATED,
        detected=(SensitiveFinding.RESTRICTED_CONTENT,),
    )

    with pytest.raises(RuntimeError, match="database fixture failure"):
        runtime.service.persist(_request(payload, inspection))

    assert not runtime.restricted.objects
    assert len(runtime.restricted.deletes) == 2
    assert not runtime.vault.keys
    assert len(runtime.vault.destroyed) == 1
    assert payload == bytearray(len(payload))


def test_expiry_honours_legal_hold_then_deletes_objects_key_and_commits_tombstone() -> None:
    runtime = _runtime()
    payload = bytearray(b"restricted retention body")
    inspection = _inspection(
        payload,
        access_class=ArtifactAccessClass.AUTHENTICATED,
        detected=(SensitiveFinding.RESTRICTED_CONTENT,),
        ttl_days=1,
    )
    persisted = runtime.service.persist(_request(payload, inspection)).persisted
    assert persisted is not None
    hold = ArtifactLegalHold(
        id=uuid4(),
        project_id=PROJECT_ID,
        artifact_id=inspection.artifact_id,
        approved_by=(uuid4(), uuid4()),
        reason="approved investigation",
        approved_at=CAPTURED_AT,
        expires_at=CAPTURED_AT + timedelta(days=2),
    )

    with pytest.raises(SyntheticLabContractError, match="active legal hold"):
        runtime.service.expire(
            lease=_lease(),
            artifact=persisted,
            deleted_at=CAPTURED_AT + timedelta(days=1, hours=1),
            legal_hold=hold,
        )
    assert not runtime.restricted.deletes

    tombstone = runtime.service.expire(
        lease=_lease(),
        artifact=persisted,
        deleted_at=CAPTURED_AT + timedelta(days=3),
        legal_hold=hold,
    )

    assert len(runtime.restricted.deletes) == 2
    assert not runtime.restricted.objects
    assert persisted.manifest.artifact_key_ref in runtime.vault.destroyed
    assert tombstone.recoverable_body_retained is False
    assert len(runtime.repository.tombstones) == 1


def test_stale_retention_lease_cannot_delete_current_objects() -> None:
    runtime = _runtime()
    payload = bytearray(b"retention lease body")
    inspection = _inspection(
        payload,
        access_class=ArtifactAccessClass.AUTHENTICATED,
        detected=(SensitiveFinding.RESTRICTED_CONTENT,),
        ttl_days=1,
    )
    persisted = runtime.service.persist(_request(payload, inspection)).persisted
    assert persisted is not None
    runtime.repository.reject_deletion_lease = True

    with pytest.raises(LostJobLease):
        runtime.service.expire(
            lease=_lease(),
            artifact=persisted,
            deleted_at=CAPTURED_AT + timedelta(days=2),
        )

    assert not runtime.restricted.deletes
    assert len(runtime.restricted.objects) == 2
    assert not runtime.vault.destroyed
    assert not runtime.repository.tombstones


def test_delete_failure_keeps_intent_retryable_and_never_claims_tombstone_complete() -> None:
    runtime = _runtime()
    payload = bytearray(b"retryable retention body")
    inspection = _inspection(
        payload,
        access_class=ArtifactAccessClass.AUTHENTICATED,
        detected=(SensitiveFinding.RESTRICTED_CONTENT,),
        ttl_days=1,
    )
    persisted = runtime.service.persist(_request(payload, inspection)).persisted
    assert persisted is not None
    runtime.restricted.fail_next_delete = True

    with pytest.raises(ObjectStoreError, match="delete fixture"):
        runtime.service.expire(
            lease=_lease(),
            artifact=persisted,
            deleted_at=CAPTURED_AT + timedelta(days=2),
        )
    assert runtime.repository.deletion_intents
    assert not runtime.repository.tombstones
    assert runtime.vault.keys

    runtime.service.expire(
        lease=_lease(),
        artifact=persisted,
        deleted_at=CAPTURED_AT + timedelta(days=2),
    )
    assert runtime.repository.tombstones
    assert not runtime.restricted.objects


def test_stale_generation_rollback_cannot_delete_winner_objects_with_same_content() -> None:
    runtime = _runtime()
    artifact_id = uuid4()
    plaintext = b"same captured body"
    stale_payload = bytearray(plaintext)
    winner_payload = bytearray(plaintext)
    stale_inspection = _inspection(
        stale_payload,
        access_class=ArtifactAccessClass.PUBLIC,
        artifact_id=artifact_id,
    )
    winner_inspection = _inspection(
        winner_payload,
        access_class=ArtifactAccessClass.PUBLIC,
        artifact_id=artifact_id,
    )
    winner_result = None

    def interleave(lease, artifact):
        nonlocal winner_result
        del artifact
        if lease.fencing_generation != 1:
            return
        runtime.repository.persist_hook = None
        winner_result = runtime.service.persist(
            _request(winner_payload, winner_inspection, generation=2)
        )
        raise LostJobLease("stale generation fixture")

    runtime.repository.persist_hook = interleave
    with pytest.raises(LostJobLease):
        runtime.service.persist(_request(stale_payload, stale_inspection, generation=1))

    assert winner_result is not None and winner_result.persisted is not None
    winner_uri = winner_result.persisted.manifest.payload_uri
    winner_key = winner_uri.removeprefix("s3://public-raw/")
    assert "/generation-2/" in winner_uri
    assert winner_key in runtime.public.objects
    assert all("/generation-1/" not in key for key in runtime.public.objects)
    assert plaintext not in b"".join(value for value, _media in runtime.public.objects.values())
    assert winner_result.persisted.manifest.tier_key_version is not None
    assert winner_result.persisted.manifest.encryption_algorithm.startswith("AES-256-GCM/")


@dataclass(frozen=True)
class _Runtime:
    service: GovernedRawArtifactStorage
    public: MemoryObjectStore
    restricted: MemoryObjectStore
    derived: MemoryObjectStore
    vault: MemoryDekVault
    repository: MemoryManifestRepository


def _runtime() -> _Runtime:
    public = MemoryObjectStore("public-raw")
    restricted = MemoryObjectStore("restricted-raw")
    derived = MemoryObjectStore("derived")
    vault = MemoryDekVault()
    repository = MemoryManifestRepository()
    service = GovernedRawArtifactStorage(
        stores=RawArtifactStores(
            encrypted_raw=public,
            restricted_independent_dek=restricted,
            derived_project=derived,
        ),
        encryptor=IndependentDekArtifactEncryptor(vault),
        tier_encryptor=ProjectTierArtifactEncryptor(MemoryTierKeyResolver()),
        repository=repository,
        clock=lambda: CAPTURED_AT + timedelta(minutes=1),
    )
    return _Runtime(service, public, restricted, derived, vault, repository)


def _inspection(
    payload: bytearray,
    *,
    access_class: ArtifactAccessClass,
    detected: tuple[SensitiveFinding, ...] = (),
    unresolved: tuple[SensitiveFinding, ...] = (),
    ttl_days: int | None = None,
    artifact_id: UUID | None = None,
    form: ArtifactForm = ArtifactForm.RAW,
) -> RawArtifactInspection:
    return RawArtifactInspection(
        artifact_id=artifact_id or uuid4(),
        project_id=PROJECT_ID,
        captured_at=CAPTURED_AT,
        access_class=access_class,
        form=form,
        payload_hash=hashlib.sha256(payload).hexdigest(),
        detected_findings=detected,
        unresolved_findings=unresolved,
        redaction_applied=False,
        redaction_verified=False,
        redacted_payload_hash=None,
        anonymization_verified=form is ArtifactForm.DERIVED,
        policy_max_ttl_days=ttl_days,
    )


def _request(
    payload: bytearray,
    inspection: RawArtifactInspection,
    *,
    generation: int = 1,
) -> RawArtifactWriteRequest:
    return RawArtifactWriteRequest(
        lease=_lease(generation=generation),
        inspection=inspection,
        payload=payload,
        media_type="text/html",
        source_identity_hash="1" * 64,
        record_count=1,
        producer_release="style-browser-v1",
    )


def _lease(*, generation: int = 1) -> WorkerLease:
    return WorkerLease(
        job_id=uuid4(),
        project_id=PROJECT_ID,
        kind="style.collect",
        worker_id="test-worker",
        lease_token=uuid4(),
        fencing_generation=generation,
        attempt_count=1,
        max_attempts=3,
    )
