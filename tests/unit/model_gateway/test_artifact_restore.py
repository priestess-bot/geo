from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from uuid import UUID

import pytest

from geo_core.model_gateway.artifact_restore import verify_provider_artifact_restore
from geo_core.model_gateway.provider_adapters.artifacts import (
    IndependentProviderArtifactEncryptor,
    ProviderArtifactError,
    provider_artifact_associated_data,
)
from geo_core.object_store import RetrievedObject
from geo_core.secrets import (
    EnvelopeCipher,
    MasterKeyring,
    SecretDecryptionError,
    SecretReference,
    SecretValue,
)


NOW = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
PROJECT_ID = UUID("d1000000-0000-0000-0000-000000000001")
ARTIFACT_ID = UUID("d1000000-0000-0000-0000-000000000002")
MASTER_KEY = b"P" * 32


def test_provider_restore_authenticates_canary_dek_and_representative_object() -> None:
    fixture = _fixture()

    result = verify_provider_artifact_restore(
        connection=fixture.connection,
        cipher=fixture.cipher,
        object_store=fixture.store,
    )

    assert result.verified_master_key_versions == (1,)
    assert result.active_dek_count == 1
    assert result.recoverable_artifact_count == 1
    assert result.representative_artifact_verified is True
    assert result.representative_artifact_id == ARTIFACT_ID
    assert result.empty_artifact_domain is False
    assert len(result.verification_receipt_hash) == 64


def test_provider_restore_rejects_wrong_key_and_active_status_drift() -> None:
    fixture = _fixture()
    wrong = EnvelopeCipher(MasterKeyring(keys={1: b"W" * 32}, active_version=1))
    with pytest.raises(SecretDecryptionError, match="canary authentication"):
        verify_provider_artifact_restore(
            connection=fixture.connection,
            cipher=wrong,
            object_store=fixture.store,
        )

    fixture.canary_rows[0]["status"] = "decrypt_only"
    with pytest.raises(ProviderArtifactError, match="active key"):
        verify_provider_artifact_restore(
            connection=fixture.connection,
            cipher=fixture.cipher,
            object_store=fixture.store,
        )


def test_provider_restore_rejects_nonempty_domain_without_representative() -> None:
    fixture = _fixture()
    fixture.counts = {"active_dek_count": 1, "recoverable_artifact_count": 0}
    fixture.representative = None

    with pytest.raises(ProviderArtifactError, match="without committed artifacts"):
        verify_provider_artifact_restore(
            connection=fixture.connection,
            cipher=fixture.cipher,
            object_store=fixture.store,
        )


def test_provider_restore_records_empty_domain_without_false_representative() -> None:
    fixture = _fixture()
    fixture.counts = {"active_dek_count": 0, "recoverable_artifact_count": 0}
    fixture.representative = None

    result = verify_provider_artifact_restore(
        connection=fixture.connection,
        cipher=fixture.cipher,
        object_store=fixture.store,
    )

    assert result.empty_artifact_domain is True
    assert result.representative_artifact_verified is False
    assert result.representative_artifact_id is None


class _Fixture:
    def __init__(self) -> None:
        self.cipher = EnvelopeCipher(MasterKeyring(keys={1: MASTER_KEY}, active_version=1))
        canary = self.cipher.create_canary(1)
        self.canary_rows = [
            {
                "master_key_version": 1,
                "status": "encrypt_decrypt",
                "algorithm": canary.algorithm,
                "canary_nonce": canary.nonce,
                "canary_ciphertext": canary.ciphertext,
            }
        ]
        plaintext = bytearray(b'{"answer":"restored provider response"}')
        content_hash = hashlib.sha256(plaintext).hexdigest()
        associated_data = provider_artifact_associated_data(
            project_id=PROJECT_ID,
            provider="openai",
            kind="raw",
            content_hash=content_hash,
            adapter_release_hash="a" * 64,
        )
        vault = _CapturingVault()
        encrypted = IndependentProviderArtifactEncryptor(vault).encrypt(
            project_id=PROJECT_ID,
            artifact_id=ARTIFACT_ID,
            plaintext=plaintext,
            associated_data=associated_data,
        )
        dek_envelope = self.cipher.encrypt(
            reference=SecretReference(
                id=ARTIFACT_ID,
                project_id=PROJECT_ID,
                purpose="model_gateway.artifact_dek",
                created_at=NOW,
            ),
            version=1,
            value=SecretValue(vault.key),
            created_at=NOW,
        )
        payload_hash = hashlib.sha256(encrypted.payload).hexdigest()
        manifest = b'{"schema_version":1}'
        manifest_hash = hashlib.sha256(manifest).hexdigest()
        self.store = _ObjectStore(
            {
                "s3://geo-artifacts/provider/payload.bin": encrypted.payload,
                "s3://geo-artifacts/provider/manifest.json": manifest,
            }
        )
        self.counts = {"active_dek_count": 1, "recoverable_artifact_count": 1}
        self.representative: dict[str, object] | None = {
            "artifact_id": ARTIFACT_ID,
            "project_id": PROJECT_ID,
            "kind": "raw",
            "provider": "openai",
            "adapter_release_hash": "a" * 64,
            "manifest_uri": "s3://geo-artifacts/provider/manifest.json",
            "manifest_hash": manifest_hash,
            "payload_uri": "s3://geo-artifacts/provider/payload.bin",
            "payload_hash": payload_hash,
            "content_hash": content_hash,
            "ciphertext": dek_envelope.ciphertext,
            "data_nonce": dek_envelope.data_nonce,
            "wrapped_data_key": dek_envelope.wrapped_data_key,
            "wrap_nonce": dek_envelope.wrap_nonce,
            "master_key_version": dek_envelope.master_key_version,
            "algorithm": dek_envelope.algorithm,
            "created_at": dek_envelope.created_at,
        }
        self.connection = _Connection(self)


class _CapturingVault:
    def __init__(self) -> None:
        self.key = b""

    def store_wrapped_key(
        self, *, project_id: UUID, artifact_id: UUID, key_material: bytearray
    ) -> str:
        del project_id
        self.key = bytes(key_material)
        return str(artifact_id)

    def destroy_wrapped_key(self, *, project_id: UUID, key_reference: str) -> None:
        del project_id, key_reference


class _Connection:
    def __init__(self, fixture: _Fixture) -> None:
        self.fixture = fixture

    def execute(self, query: str) -> _Result:
        if "model_gateway_artifact_master_key_versions" in query:
            return _Result(rows=self.fixture.canary_rows)
        if "AS active_dek_count" in query:
            return _Result(row=self.fixture.counts)
        if "SELECT artifact.*" in query:
            return _Result(row=self.fixture.representative)
        raise AssertionError("unexpected restore query")


class _Result:
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.row = row
        self.rows = rows or []

    def fetchone(self) -> dict[str, object] | None:
        return self.row

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class _ObjectStore:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def get_s3_uri(
        self, *, uri: str, expected_hash: str | None = None
    ) -> RetrievedObject:
        payload = self.objects[uri]
        digest = hashlib.sha256(payload).hexdigest()
        if expected_hash != digest:
            raise ProviderArtifactError("fixture restored object hash differs")
        return RetrievedObject(
            content=payload,
            bucket="geo-artifacts",
            key=uri.removeprefix("s3://geo-artifacts/"),
            content_type="application/octet-stream",
            content_hash=digest,
            etag=None,
        )


def _fixture() -> _Fixture:
    return _Fixture()
