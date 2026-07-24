from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from uuid import UUID

from geo_core.object_store import RetrievedObject, parse_s3_uri
from geo_core.secrets import (
    SecretReference,
    SecretValue,
    EnvelopeCipher,
    MasterKeyring,
    SecretConfigurationError,
    SecretDecryptionError,
)
from geo_core.workflow_c_artifacts.postgres import (
    verify_workflow_c_artifact_keyring_canaries,
    verify_workflow_c_artifact_restore,
)
from geo_core.sampling.manual_artifact_storage import (
    IndependentWorkflowCArtifactEncryptor,
    workflow_c_artifact_associated_data,
)


class _Cursor:
    def __init__(self, rows) -> None:
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self, rows) -> None:
        self.rows = rows

    def execute(self, _statement: str):
        return _Cursor(self.rows)


def _rows(cipher: EnvelopeCipher):
    return tuple(
        {
            "master_key_version": version,
            "status": (
                "encrypt_decrypt"
                if version == cipher.active_master_key_version
                else "decrypt_only"
            ),
            "algorithm": canary.algorithm,
            "canary_nonce": canary.nonce,
            "canary_ciphertext": canary.ciphertext,
            "retired_at": None,
        }
        for version in cipher.master_key_versions
        for canary in (cipher.create_canary(version),)
    )


def test_keyring_canaries_require_every_historical_key_and_correct_material() -> None:
    correct = EnvelopeCipher(
        MasterKeyring(keys={1: b"A" * 32, 2: b"B" * 32}, active_version=2)
    )
    rows = _rows(correct)
    assert verify_workflow_c_artifact_keyring_canaries(
        _Connection(rows), correct
    ) == (1, 2)

    missing_history = EnvelopeCipher(
        MasterKeyring(keys={2: b"B" * 32}, active_version=2)
    )
    try:
        verify_workflow_c_artifact_keyring_canaries(
            _Connection(rows), missing_history
        )
    except SecretConfigurationError:
        pass
    else:
        raise AssertionError("missing historical Workflow C key must fail recovery")

    wrong_material = EnvelopeCipher(
        MasterKeyring(keys={1: b"X" * 32, 2: b"Y" * 32}, active_version=2)
    )
    try:
        verify_workflow_c_artifact_keyring_canaries(
            _Connection(rows), wrong_material
        )
    except SecretDecryptionError:
        pass
    else:
        raise AssertionError("wrong Workflow C key material must fail canary recovery")


def test_restore_verifies_one_representative_ciphertext_end_to_end() -> None:
    now = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    project_id = UUID("cc300000-0000-0000-0000-000000000001")
    artifact_id = UUID("cc300000-0000-0000-0000-000000000002")
    master = EnvelopeCipher(
        MasterKeyring(keys={1: b"M" * 32}, active_version=1),
        random_bytes=lambda size: b"N" * size,
    )
    plaintext = bytearray(b'{"redacted":"safe evidence"}')
    content_hash = hashlib.sha256(plaintext).hexdigest()
    policy_hash = "c" * 64

    class Vault:
        key = b""

        def store_wrapped_key(self, **values):
            self.key = bytes(values["key_material"])
            return artifact_id

        def destroy_wrapped_key(self, **_values):
            return None

    vault = Vault()
    encrypted = IndependentWorkflowCArtifactEncryptor(
        vault, random_bytes=lambda size: b"D" * size
    ).encrypt(
        project_id=project_id,
        artifact_id=artifact_id,
        plaintext=plaintext,
        associated_data=workflow_c_artifact_associated_data(
            project_id=project_id,
            artifact_id=artifact_id,
            persisted_content_hash=content_hash,
            governance_policy_hash=policy_hash,
        ),
    )
    object_hash = hashlib.sha256(encrypted.payload).hexdigest()
    payload_uri = (
        "s3://geo-restricted-workflow-c-artifacts/"
        "workflow-c/manual-evidence/representative.bin"
    )
    manifest_value = {
        "artifact_id": str(artifact_id),
        "project_id": str(project_id),
        "persisted_content_hash": content_hash,
        "stored_object_hash": object_hash,
        "raw_retained": False,
        "export_allowed": False,
        "audience": "admin_only",
        "classification": "restricted_manual_evidence",
    }
    manifest = json.dumps(
        manifest_value, sort_keys=True, separators=(",", ":")
    ).encode()
    manifest_hash = hashlib.sha256(manifest).hexdigest()
    manifest_uri = (
        "s3://geo-restricted-workflow-c-artifacts/"
        "workflow-c/manual-evidence/representative.json"
    )
    wrapped = master.encrypt(
        reference=SecretReference(
            id=artifact_id,
            project_id=project_id,
            purpose="workflow_c.manual_artifact_dek",
            created_at=now,
        ),
        version=1,
        value=SecretValue(vault.key),
        created_at=now,
    )
    canary = master.create_canary(1)
    representative = {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "manifest_uri": manifest_uri,
        "manifest_hash": manifest_hash,
        "object_uri": payload_uri,
        "object_hash": object_hash,
        "redacted_content_hash": content_hash,
        "governance_policy_hash": policy_hash,
        "ciphertext": wrapped.ciphertext,
        "data_nonce": wrapped.data_nonce,
        "wrapped_data_key": wrapped.wrapped_data_key,
        "wrap_nonce": wrapped.wrap_nonce,
        "master_key_version": wrapped.master_key_version,
        "dek_algorithm": wrapped.algorithm,
        "dek_created_at": now,
    }

    class RestoreConnection:
        def execute(self, statement: str):
            if "workflow_c_artifact_master_key_versions" in statement:
                return _Cursor(
                    [
                        {
                            "master_key_version": 1,
                            "status": "encrypt_decrypt",
                            "algorithm": canary.algorithm,
                            "canary_nonce": canary.nonce,
                            "canary_ciphertext": canary.ciphertext,
                            "retired_at": None,
                        }
                    ]
                )
            if "active_dek_count" in statement:
                return _Cursor(
                    [{"active_dek_count": 1, "recoverable_artifact_count": 1}]
                )
            return _Cursor([representative])

    class Objects:
        values = {payload_uri: encrypted.payload, manifest_uri: manifest}

        def get_s3_uri(self, *, uri: str, expected_hash: str):
            bucket, key = parse_s3_uri(uri)
            content = self.values[uri]
            assert hashlib.sha256(content).hexdigest() == expected_hash
            return RetrievedObject(
                content=content,
                bucket=bucket,
                key=key,
                content_type="application/octet-stream",
                content_hash=expected_hash,
                etag=None,
            )

    result = verify_workflow_c_artifact_restore(
        connection=RestoreConnection(),
        cipher=master,
        object_store=Objects(),
    )
    assert result.representative_artifact_verified is True
    assert result.representative_artifact_id == artifact_id
    assert result.recoverable_artifact_count == 1
    assert result.empty_artifact_domain is False
