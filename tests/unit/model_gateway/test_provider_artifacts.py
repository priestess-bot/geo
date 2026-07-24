from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import UUID

import pytest

from geo_core.model_gateway import DataUseDecision, ModelAudience, ProviderDataPolicy
from geo_core.model_gateway.artifact_lifecycle import StagedProviderArtifactBundle
from geo_core.model_gateway.provider_adapters.artifacts import (
    IndependentProviderArtifactEncryptor,
    MinioProviderArtifactSink,
    ProviderArtifactError,
    StrictProviderArtifactGovernance,
)
from geo_core.object_store import RetrievedObject, StoredObject, parse_s3_uri


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
PROJECT_ID = UUID("cc000000-0000-0000-0000-000000000001")
ADAPTER_HASH = "a" * 64


class _MemoryObjectStore:
    def __init__(
        self,
        *,
        fail_put_number: int | None = None,
        fail_delete: bool = False,
    ) -> None:
        self.bucket = "provider-artifacts"
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.puts = 0
        self.fail_put_number = fail_put_number
        self.fail_delete = fail_delete

    def uri_for_key(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObject:
        self.puts += 1
        if self.puts == self.fail_put_number:
            raise RuntimeError("fixture MinIO write failure")
        payload = content.encode() if isinstance(content, str) else content
        digest = hashlib.sha256(payload).hexdigest()
        assert expected_hash in (None, digest)
        self.objects[key] = (payload, content_type)
        return StoredObject(
            uri=f"s3://{self.bucket}/{key}",
            bucket=self.bucket,
            key=key,
            content_type=content_type,
            content_hash=digest,
            etag=None,
        )

    def get_s3_uri(
        self, *, uri: str, expected_hash: str | None = None
    ) -> RetrievedObject:
        bucket, key = parse_s3_uri(uri)
        assert bucket == self.bucket
        payload, content_type = self.objects[key]
        digest = hashlib.sha256(payload).hexdigest()
        assert expected_hash in (None, digest)
        return RetrievedObject(
            content=payload,
            bucket=bucket,
            key=key,
            content_type=content_type,
            content_hash=digest,
            etag=None,
        )

    def delete_s3_uri(self, *, uri: str) -> bool:
        if self.fail_delete:
            raise RuntimeError("fixture MinIO delete failure")
        bucket, key = parse_s3_uri(uri)
        assert bucket == self.bucket
        self.objects.pop(key, None)
        return True


class _MemoryKeyVault:
    def __init__(self) -> None:
        self.keys: dict[str, bytes] = {}
        self.destroyed: list[str] = []

    def store_wrapped_key(
        self, *, project_id: UUID, artifact_id: UUID, key_material: bytearray
    ) -> str:
        del project_id
        reference = str(artifact_id)
        self.keys[reference] = bytes(key_material)
        return reference

    def destroy_wrapped_key(
        self, *, project_id: UUID, key_reference: str
    ) -> None:
        del project_id
        self.keys.pop(key_reference, None)
        self.destroyed.append(key_reference)


class _MemoryLifecycle:
    def __init__(self, *, fail_stage: bool = False) -> None:
        self.bundles: list[StagedProviderArtifactBundle] = []
        self.fail_stage = fail_stage

    def stage_bundle(self, bundle: StagedProviderArtifactBundle) -> None:
        if self.fail_stage:
            raise RuntimeError("fixture bundle stage failure")
        self.bundles.append(bundle)


def _policy(storage: DataUseDecision) -> ProviderDataPolicy:
    return ProviderDataPolicy(
        storage=storage,
        cache=DataUseDecision.ALLOWED,
        display=DataUseDecision.ALLOWED,
        redistribution=DataUseDecision.PROHIBITED,
        retention_days=30,
        terms_reference="https://evidence.example/openai/terms/2026-07-23",
        terms_sha256="a" * 64,
    )


def _capture(
    sink: MinioProviderArtifactSink,
    *,
    storage: DataUseDecision = DataUseDecision.ALLOWED,
):
    raw = {
        "id": "provider-response",
        "answer": "A useful Australian answer.",
        "api_key": "must-never-reach-minio",
    }
    raw_hash = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return sink.capture(
        project_id=PROJECT_ID,
        job_id=UUID("cc000000-0000-0000-0000-000000000002"),
        attempt_id=UUID("cc000000-0000-0000-0000-000000000003"),
        provider="openai",
        adapter_release_id="openai-adapter-v1",
        adapter_release_hash=ADAPTER_HASH,
        data_policy=_policy(storage),
        usage_purpose="geo_measurement",
        usage_audience=ModelAudience.INTERNAL_WORKER,
        raw_payload=raw,
        raw_content_hash=raw_hash,
        derived_payload={"answer": "A useful Australian answer.", "recommended": True},
    )


def test_allowed_policy_writes_encrypted_content_addressed_bundle_with_ttl() -> None:
    store = _MemoryObjectStore()
    vault = _MemoryKeyVault()
    sink = MinioProviderArtifactSink(
        object_store=store,
        encryptor=IndependentProviderArtifactEncryptor(vault),
        lifecycle_repository=(lifecycle := _MemoryLifecycle()),
        clock=lambda: NOW,
    )

    bundle = _capture(sink)

    assert bundle.raw.manifest_reference is not None
    assert bundle.derived.manifest_reference is not None
    assert bundle.raw.retention_days == bundle.derived.retention_days == 30
    assert bundle.raw.expires_at == bundle.derived.expires_at == NOW + timedelta(days=30)
    assert bundle.raw.byte_size > 0 and bundle.derived.byte_size > 0
    assert len(store.objects) == 4
    assert len(vault.keys) == 2
    assert lifecycle.bundles[0].id == bundle.bundle_id
    assert {item.kind.value for item in lifecycle.bundles[0].artifacts} == {
        "raw",
        "derived",
    }
    assert all("model-provider-artifacts/" in key for key in store.objects)
    stored_text = repr(store.objects)
    assert "must-never-reach-minio" not in stored_text
    assert "A useful Australian answer" not in stored_text
    raw_manifest = store.get_s3_uri(
        uri=bundle.raw.manifest_reference,
        expected_hash=bundle.raw.manifest_hash,
    )
    manifest = json.loads(raw_manifest.content)
    assert manifest["classification"] == "restricted_provider_response"
    assert manifest["retention_days"] == 30
    assert manifest["encryption_algorithm"] == "AES-256-GCM/independent-DEK/v1"
    assert manifest["persisted_content_hash"] == bundle.raw.content_hash


def test_prohibited_policy_keeps_only_hash_lineage_and_never_calls_minio_or_vault() -> None:
    store = _MemoryObjectStore()
    vault = _MemoryKeyVault()
    sink = MinioProviderArtifactSink(
        object_store=store,
        encryptor=IndependentProviderArtifactEncryptor(vault),
        lifecycle_repository=(lifecycle := _MemoryLifecycle()),
        clock=lambda: NOW,
    )

    bundle = _capture(sink, storage=DataUseDecision.PROHIBITED)

    assert bundle.raw.manifest_reference is None
    assert bundle.derived.manifest_reference is None
    assert bundle.raw.byte_size == bundle.derived.byte_size == 0
    assert bundle.raw.manifest_hash != bundle.raw.content_hash
    assert store.puts == 0 and store.objects == {}
    assert vault.keys == {}
    assert lifecycle.bundles == []


def test_second_artifact_write_failure_rolls_back_both_artifacts_and_deks() -> None:
    store = _MemoryObjectStore(fail_put_number=4)
    vault = _MemoryKeyVault()
    sink = MinioProviderArtifactSink(
        object_store=store,
        encryptor=IndependentProviderArtifactEncryptor(vault),
        lifecycle_repository=(lifecycle := _MemoryLifecycle()),
        clock=lambda: NOW,
    )

    with pytest.raises(ProviderArtifactError, match="persistence failed"):
        _capture(sink)

    assert store.objects == {}
    assert vault.keys == {}
    assert len(vault.destroyed) == 2
    assert len(lifecycle.bundles) == 1


def test_durable_stage_failure_rolls_back_objects_and_deks() -> None:
    store = _MemoryObjectStore()
    vault = _MemoryKeyVault()
    sink = MinioProviderArtifactSink(
        object_store=store,
        encryptor=IndependentProviderArtifactEncryptor(vault),
        lifecycle_repository=_MemoryLifecycle(fail_stage=True),
        clock=lambda: NOW,
    )

    with pytest.raises(ProviderArtifactError, match="persistence failed"):
        _capture(sink)

    assert store.objects == {}
    assert store.puts == 0
    assert vault.keys == {}
    assert len(vault.destroyed) == 2


def test_delete_failure_after_stage_retains_durable_cleanup_identity() -> None:
    store = _MemoryObjectStore(fail_put_number=4, fail_delete=True)
    vault = _MemoryKeyVault()
    lifecycle = _MemoryLifecycle()
    sink = MinioProviderArtifactSink(
        object_store=store,
        encryptor=IndependentProviderArtifactEncryptor(vault),
        lifecycle_repository=lifecycle,
        clock=lambda: NOW,
    )

    with pytest.raises(ProviderArtifactError, match="durable staged bundle"):
        _capture(sink)

    assert len(lifecycle.bundles) == 1
    staged = lifecycle.bundles[0]
    assert {item.payload_uri for item in staged.artifacts}
    assert {item.manifest_uri for item in staged.artifacts}
    assert store.objects
    assert vault.keys == {}


def test_strict_governance_redacts_sensitive_fields_before_encryption() -> None:
    governed = StrictProviderArtifactGovernance().govern(
        {
            "answer": "safe answer",
            "authorization": "Bearer provider-secret",
            "nested": {"refresh_token": "secret-value"},
        }
    )

    payload = json.loads(bytes(governed.payload))
    assert payload == {
        "answer": "safe answer",
        "authorization": "[REDACTED]",
        "nested": {"refresh_token": "[REDACTED]"},
    }
    assert "provider-secret" not in repr((governed, payload))
