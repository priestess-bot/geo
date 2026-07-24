from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from uuid import UUID

import pytest

from geo_core.model_gateway.artifact_recovery import ProviderArtifactRecoveryRequest
from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.model_gateway.postgres_artifact_recovery import (
    PostgresProviderArtifactRecovery,
)
from geo_core.model_gateway.provider_adapters.artifacts import (
    IndependentProviderArtifactEncryptor,
    MinioProviderArtifactSink,
    ProviderArtifactError,
)
from geo_core.model_gateway.releases import DataUseDecision, ProviderDataPolicy
from geo_core.model_gateway.contracts import ModelAudience
from geo_core.object_store import RetrievedObject, StoredObject, parse_s3_uri
from geo_core.secrets import (
    EnvelopeCipher,
    MasterKeyring,
    SecretReference,
    SecretValue,
)


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
PROJECT_ID = UUID("81000000-0000-0000-0000-000000000001")
JOB_ID = UUID("82000000-0000-0000-0000-000000000002")
PARENT_JOB_ID = UUID("82000000-0000-0000-0000-000000000099")
ATTEMPT_ID = UUID("83000000-0000-0000-0000-000000000003")
LEASE_TOKEN = UUID("84000000-0000-0000-0000-000000000004")
OUTPUT = {"answer": "Recovered", "recommended": True}
SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "recommended": {"type": "boolean"},
    },
    "required": ["answer", "recommended"],
    "additionalProperties": False,
}


def test_recovery_authenticates_artifact_and_records_idempotent_receipt() -> None:
    fixture = _Fixture()
    request = fixture.request()

    first = fixture.recovery.recover_derived(request)
    second = fixture.recovery.recover_derived(request)

    assert first.output == OUTPUT
    assert first.output_hash == canonical_json_hash(OUTPUT)
    assert first.recovery_receipt_id == second.recovery_receipt_id
    assert first.recovery_receipt_hash == second.recovery_receipt_hash
    assert fixture.database.insert_count == 1
    assert "output=[REDACTED]" in repr(first)
    assert "recommended" not in repr(first)


def test_recovery_rejects_schema_drift_before_writing_receipt() -> None:
    fixture = _Fixture()
    incompatible = {
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
        "additionalProperties": True,
    }
    request = ProviderArtifactRecoveryRequest(
        project_id=PROJECT_ID,
        source_model_job_id=JOB_ID,
        recovery_job_id=JOB_ID,
        lease_token=LEASE_TOKEN,
        fencing_generation=3,
        model_call_attempt_id=ATTEMPT_ID,
        expected_output_hash=canonical_json_hash(OUTPUT),
        output_schema=incompatible,
        application_output_schema=incompatible,
        purpose="geo_measurement",
    )
    fixture.database.artifact["output_schema_hash"] = request.output_schema_hash
    fixture.database.artifact["application_output_schema_hash"] = (
        request.application_output_schema_hash
    )

    with pytest.raises(ProviderArtifactError, match="validation failed"):
        fixture.recovery.recover_derived(request)

    assert fixture.database.insert_count == 0


def test_recovery_allows_child_artifact_only_under_its_active_parent_fence() -> None:
    fixture = _Fixture()
    fixture.database.artifact["source_parent_job_id"] = PARENT_JOB_ID
    request = ProviderArtifactRecoveryRequest(
        project_id=PROJECT_ID,
        source_model_job_id=JOB_ID,
        recovery_job_id=PARENT_JOB_ID,
        lease_token=LEASE_TOKEN,
        fencing_generation=3,
        model_call_attempt_id=ATTEMPT_ID,
        expected_output_hash=canonical_json_hash(OUTPUT),
        output_schema=SCHEMA,
        application_output_schema=SCHEMA,
        purpose="geo_measurement",
    )

    recovered = fixture.recovery.recover_derived(request)

    assert recovered.output == OUTPUT
    assert fixture.database.receipt is not None
    assert fixture.database.receipt["source_model_job_id"] == JOB_ID
    assert fixture.database.receipt["recovery_job_id"] == PARENT_JOB_ID


class _Fixture:
    def __init__(self) -> None:
        self.store = _ObjectStore()
        self.vault = _CapturingVault()
        self.lifecycle = _Lifecycle()
        sink = MinioProviderArtifactSink(
            object_store=self.store,
            encryptor=IndependentProviderArtifactEncryptor(self.vault),
            lifecycle_repository=self.lifecycle,
            clock=lambda: NOW,
        )
        policy = ProviderDataPolicy(
            storage=DataUseDecision.ALLOWED,
            cache=DataUseDecision.ALLOWED,
            display=DataUseDecision.ALLOWED,
            redistribution=DataUseDecision.PROHIBITED,
            retention_days=30,
            terms_reference="https://evidence.example/openai/terms/fixture",
            terms_sha256="a" * 64,
        )
        raw = {"id": "fixture", "output": OUTPUT}
        sink.capture(
            project_id=PROJECT_ID,
            job_id=JOB_ID,
            attempt_id=ATTEMPT_ID,
            provider="openai",
            adapter_release_id="openai-adapter-v1",
            adapter_release_hash="a" * 64,
            data_policy=policy,
            usage_purpose="geo_measurement",
            usage_audience=ModelAudience.INTERNAL_WORKER,
            raw_payload=raw,
            raw_content_hash=canonical_json_hash(raw),
            derived_payload=OUTPUT,
        )
        bundle = self.lifecycle.bundle
        assert bundle is not None
        raw_artifact = next(item for item in bundle.artifacts if item.kind.value == "raw")
        derived = next(item for item in bundle.artifacts if item.kind.value == "derived")
        key = self.vault.keys[str(derived.key_reference)]
        self.cipher = EnvelopeCipher(MasterKeyring(keys={1: b"K" * 32}, active_version=1))
        envelope = self.cipher.encrypt(
            reference=SecretReference(
                id=derived.artifact_id,
                project_id=PROJECT_ID,
                purpose="model_gateway.artifact_dek",
                created_at=NOW,
            ),
            version=1,
            value=SecretValue(key),
            created_at=NOW,
        )
        self.database = _Database(
            {
                "project_id": PROJECT_ID,
                "artifact_id": derived.artifact_id,
                "bundle_id": bundle.id,
                "kind": "derived",
                "job_id": JOB_ID,
                "attempt_id": ATTEMPT_ID,
                "provider": "openai",
                "adapter_release_id": "openai-adapter-v1",
                "adapter_release_hash": "a" * 64,
                "data_policy_hash": policy.data_policy_hash,
                "storage_decision": policy.storage.value,
                "cache_decision": policy.cache.value,
                "display_decision": policy.display.value,
                "redistribution_decision": policy.redistribution.value,
                "retention_days": policy.retention_days,
                "usage_purpose": "geo_measurement",
                "audience": "internal_worker",
                "bundle_status": "committed",
                "output_schema_hash": canonical_json_hash(SCHEMA),
                "application_output_schema_hash": canonical_json_hash(SCHEMA),
                "terminal_output_hash": canonical_json_hash(OUTPUT),
                "source_parent_job_id": None,
                "dek_status": "active",
                "manifest_uri": derived.manifest_uri,
                "manifest_hash": derived.manifest_hash,
                "content_hash": derived.content_hash,
                "content_byte_size": derived.content_byte_size,
                "raw_manifest_uri": raw_artifact.manifest_uri,
                "raw_manifest_hash": raw_artifact.manifest_hash,
                "raw_content_hash": raw_artifact.content_hash,
                "raw_content_byte_size": raw_artifact.content_byte_size,
                "payload_uri": derived.payload_uri,
                "payload_hash": derived.payload_hash,
                "encryption_algorithm": derived.encryption_algorithm,
                "key_ref": derived.key_reference,
                "expires_at": NOW + timedelta(days=30),
                "ciphertext": envelope.ciphertext,
                "data_nonce": envelope.data_nonce,
                "wrapped_data_key": envelope.wrapped_data_key,
                "wrap_nonce": envelope.wrap_nonce,
                "master_key_version": envelope.master_key_version,
                "algorithm": envelope.algorithm,
                "created_at": envelope.created_at,
            }
        )
        self.recovery = PostgresProviderArtifactRecovery(
            connect=lambda: _Connection(self.database),
            cipher=self.cipher,
            object_store=self.store,
            clock=lambda: NOW,
        )

    def request(self) -> ProviderArtifactRecoveryRequest:
        return ProviderArtifactRecoveryRequest(
            project_id=PROJECT_ID,
            source_model_job_id=JOB_ID,
            recovery_job_id=JOB_ID,
            lease_token=LEASE_TOKEN,
            fencing_generation=3,
            model_call_attempt_id=ATTEMPT_ID,
            expected_output_hash=canonical_json_hash(OUTPUT),
            output_schema=SCHEMA,
            application_output_schema=SCHEMA,
            purpose="geo_measurement",
        )


class _CapturingVault:
    def __init__(self) -> None:
        self.keys: dict[str, bytes] = {}

    def store_wrapped_key(
        self, *, project_id: UUID, artifact_id: UUID, key_material: bytearray
    ) -> str:
        del project_id
        self.keys[str(artifact_id)] = bytes(key_material)
        return str(artifact_id)

    def destroy_wrapped_key(self, *, project_id: UUID, key_reference: str) -> None:
        del project_id
        self.keys.pop(key_reference, None)


class _Lifecycle:
    def __init__(self) -> None:
        self.bundle = None

    def stage_bundle(self, bundle) -> None:
        self.bundle = bundle


class _ObjectStore:
    def __init__(self) -> None:
        self.bucket = "provider-artifacts"
        self.objects: dict[str, tuple[bytes, str]] = {}

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
        payload = content.encode() if isinstance(content, str) else content
        digest = hashlib.sha256(payload).hexdigest()
        assert expected_hash in {None, digest}
        self.objects[key] = (payload, content_type)
        return StoredObject(
            uri=self.uri_for_key(key),
            bucket=self.bucket,
            key=key,
            content_type=content_type,
            content_hash=digest,
            etag=None,
        )

    def get_s3_uri(self, *, uri: str, expected_hash: str | None = None) -> RetrievedObject:
        bucket, key = parse_s3_uri(uri)
        payload, content_type = self.objects[key]
        digest = hashlib.sha256(payload).hexdigest()
        if expected_hash != digest:
            raise ProviderArtifactError("fixture object hash mismatch")
        return RetrievedObject(
            content=payload,
            bucket=bucket,
            key=key,
            content_type=content_type,
            content_hash=digest,
            etag=None,
        )

    def delete_s3_uri(self, *, uri: str) -> bool:
        _, key = parse_s3_uri(uri)
        return self.objects.pop(key, None) is not None


class _Database:
    def __init__(self, artifact: dict[str, object]) -> None:
        self.artifact = artifact
        self.receipt: dict[str, object] | None = None
        self.insert_count = 0
        self.fence = {
            "status": "running",
            "lease_token": LEASE_TOKEN,
            "fencing_generation": 3,
            "lease_expires_at": NOW + timedelta(minutes=5),
            "cancel_requested_at": None,
        }


class _Connection:
    def __init__(self, database: _Database) -> None:
        self.database = database

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def close(self) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> "_Result":
        if "set_config('geo.project_id'" in query or "pg_advisory_xact_lock" in query:
            return _Result(None)
        if "SELECT artifact.*" in query:
            return _Result(self.database.artifact)
        if "SELECT * FROM model_gateway_artifact_recovery_receipts" in query:
            return _Result(self.database.receipt)
        if "SELECT status, lease_token" in query:
            return _Result(self.database.fence)
        if "INSERT INTO model_gateway_artifact_recovery_receipts" in query:
            self.database.insert_count += 1
            self.database.receipt = {
                "id": params[0],
                "project_id": params[1],
                "source_model_job_id": params[2],
                "recovery_job_id": params[3],
                "model_call_attempt_id": params[4],
                "artifact_id": params[5],
                "manifest_hash": params[6],
                "expected_output_hash": params[7],
                "recovered_output_hash": params[8],
                "purpose": params[9],
                "audience": "internal_worker",
                "lease_token": params[10],
                "fencing_generation": params[11],
                "receipt_hash": params[12],
                "recovered_at": params[13],
            }
            return _Result(self.database.receipt)
        raise AssertionError(f"unexpected query: {query}")


class _Result:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row

    def fetchone(self) -> dict[str, object] | None:
        return self.row
