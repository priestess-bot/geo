from datetime import UTC, datetime
import hashlib
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from geo_core.synthetic_lab.artifact_keyring import (
    ArtifactKeyringConfigurationError,
    SyntheticArtifactKeyring,
)
from geo_core.synthetic_lab.artifact_keyring_postgres import (
    PostgresArtifactDekVault,
    verify_synthetic_artifact_recovery,
)
from geo_core.synthetic_lab.raw_artifact_storage import artifact_encryption_aad


def test_dek_wrap_is_bound_to_fencing_generation() -> None:
    keyring = SyntheticArtifactKeyring(active_version="1", keys={"1": b"k" * 32})
    vault = PostgresArtifactDekVault(keyring)
    project_id, artifact_id = uuid4(), uuid4()
    key_ref = vault.store_wrapped_key(
        project_id=project_id,
        artifact_id=artifact_id,
        fencing_generation=3,
        key_material=bytearray(b"d" * 32),
    )
    pending = vault.pending_for(
        key_ref=key_ref,
        project_id=project_id,
        artifact_id=artifact_id,
        fencing_generation=3,
    )
    assert vault.unwrap(
        key_ref=key_ref,
        project_id=project_id,
        artifact_id=artifact_id,
        fencing_generation=3,
        wrapped_dek=pending.wrapped_dek,
        wrap_nonce=pending.wrap_nonce,
        master_key_version="1",
    ) == b"d" * 32
    with pytest.raises(Exception, match="authentication failed"):
        vault.unwrap(
            key_ref=key_ref,
            project_id=project_id,
            artifact_id=artifact_id,
            fencing_generation=4,
            wrapped_dek=pending.wrapped_dek,
            wrap_nonce=pending.wrap_nonce,
            master_key_version="1",
        )


def test_recovery_verifier_authenticates_canary_dek_and_real_artifact() -> None:
    root = b"r" * 32
    keyring = SyntheticArtifactKeyring(active_version="1", keys={"1": root})
    project_id, artifact_id, job_id = uuid4(), uuid4(), uuid4()
    vault = PostgresArtifactDekVault(keyring)
    key_ref = vault.store_wrapped_key(
        project_id=project_id,
        artifact_id=artifact_id,
        fencing_generation=2,
        key_material=bytearray(b"d" * 32),
    )
    pending = vault.pending_for(
        key_ref=key_ref,
        project_id=project_id,
        artifact_id=artifact_id,
        fencing_generation=2,
    )
    captured_at = datetime(2026, 7, 23, 11, 0, tzinfo=UTC)
    plaintext = b"anonymous encrypted artifact"
    content_hash = hashlib.sha256(plaintext).hexdigest()
    aad = artifact_encryption_aad(
        project_id=project_id,
        artifact_id=artifact_id,
        job_id=job_id,
        content_hash=content_hash,
        captured_at=captured_at,
    )
    nonce = b"n" * 12
    payload = b"GEO-RAW-AESGCM-V1\x00" + nonce + AESGCM(b"d" * 32).encrypt(
        nonce, plaintext, aad
    )
    stored_hash = hashlib.sha256(payload).hexdigest()
    artifact_row = {
        "project_id": project_id,
        "artifact_id": artifact_id,
        "job_id": job_id,
        "fencing_generation": 2,
        "persisted_content_hash": content_hash,
        "stored_object_hash": stored_hash,
        "payload_uri": "s3://private/redacted-test-key",
        "captured_at": captured_at,
        "key_ref": key_ref,
        "wrapped_dek": pending.wrapped_dek,
        "wrap_nonce": pending.wrap_nonce,
        "master_key_version": "1",
    }
    connection = _RecoveryConnection(
        canary=_canary(root),
        counts=(1, 1, 1, 0),
        restricted=artifact_row,
        tier=None,
    )
    result = verify_synthetic_artifact_recovery(
        lambda: connection,
        keyring,
        object_reader=lambda uri, expected: payload,
    )
    assert result.verified_master_key_versions == ("1",)
    assert result.restricted_representative_verified is True
    assert result.tier_representative_verified is False
    assert result.empty_artifact_domain is False

    wrong = SyntheticArtifactKeyring(active_version="1", keys={"1": b"x" * 32})
    with pytest.raises(ArtifactKeyringConfigurationError, match="authentication failed"):
        verify_synthetic_artifact_recovery(
            lambda: _RecoveryConnection(
                canary=_canary(root), counts=(1, 0, 0, 0), restricted=None, tier=None
            ),
            wrong,
            object_reader=None,
        )


def test_empty_artifact_domain_still_requires_key_canary() -> None:
    root = b"e" * 32
    keyring = SyntheticArtifactKeyring(active_version="1", keys={"1": root})
    result = verify_synthetic_artifact_recovery(
        lambda: _RecoveryConnection(
            canary=_canary(root), counts=(1, 0, 0, 0), restricted=None, tier=None
        ),
        keyring,
        object_reader=None,
    )
    assert result.empty_artifact_domain is True
    assert result.verified_master_key_canary_count == 1


def _canary(root: bytes) -> tuple[object, ...]:
    nonce = b"c" * 12
    ciphertext = AESGCM(root).encrypt(
        nonce,
        b"geo-synthetic-artifact-key-canary-v1\x001",
        b"geo-synthetic-artifact-key-canary-aad-v1\x001",
    )
    return ("1", "encrypt_decrypt", "AES-256-GCM", nonce, ciphertext)


class _Cursor:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _RecoveryConnection:
    def __init__(self, *, canary, counts, restricted, tier) -> None:
        self.canary, self.counts = canary, counts
        self.restricted, self.tier = restricted, tier

    def execute(self, sql: str, parameters: object = None):
        del parameters
        if "FROM synthetic_lab_artifact_master_key_versions" in sql and "ORDER BY" in sql:
            return _Cursor([self.canary])
        if "SELECT\n                   (SELECT count(*)" in sql:
            return _Cursor([self.counts])
        if "JOIN synthetic_lab_artifact_deks" in sql:
            return _Cursor([self.restricted] if self.restricted else [])
        if "storage_tier <> 'restricted_independent_dek'" in sql:
            return _Cursor([self.tier] if self.tier else [])
        raise AssertionError(sql)

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass
