from dataclasses import replace
from datetime import UTC, datetime
import pickle
from uuid import uuid4

import pytest

from geo_core.secrets import (
    AuthenticatedKeyringSnapshot,
    EnvelopeCipher,
    KeyringSnapshotCodec,
    MasterKeyring,
    RecoveryEscrowKey,
    RepresentativeSecretCanary,
    SecretConfigurationError,
    SecretReference,
    SecretSerializationRejected,
    SecretSnapshotIntegrityError,
    SecretValue,
    create_representative_secret_canary,
    reject_secret_bearing_payload,
    verify_representative_secret_probes,
)


NOW = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)
MASTER_V1 = bytes(range(32))
MASTER_V2 = bytes(reversed(range(32)))
ESCROW = b"E" * 32
DATA_BACKUP_REFERENCE = "data-backup-set-2026-07-23-01"


def test_authenticated_snapshot_restores_history_and_all_canary_layers() -> None:
    old_cipher = EnvelopeCipher(MasterKeyring(keys={1: MASTER_V1}, active_version=1))
    old_reference = SecretReference(
        id=uuid4(),
        project_id=uuid4(),
        purpose="provider.deepseek",
        created_at=NOW,
    )
    old_envelope = old_cipher.encrypt(
        reference=old_reference,
        version=1,
        value=SecretValue("historical-provider-test-secret"),
        created_at=NOW,
    )
    keyring = _keyring()
    codec = KeyringSnapshotCodec()
    snapshot = _snapshot(codec=codec, keyring=keyring)

    result = codec.restore(snapshot=snapshot, escrow_key=_escrow_key())
    restored_cipher = EnvelopeCipher(result.keyring)

    assert result.keyring.active_version == 2
    assert result.verified_key_versions == (1, 2)
    assert result.verified_representative_kinds == ("connector", "egress", "provider")
    assert result.data_backup_reference == DATA_BACKUP_REFERENCE
    assert restored_cipher.decrypt(old_envelope).matches("historical-provider-test-secret")
    assert snapshot.manifest.canary_versions == (1, 2)
    assert snapshot.manifest.key_versions == (1, 2)
    assert snapshot.manifest.manifest_sha256 == result.manifest_sha256


def test_snapshot_manifest_and_repr_never_contain_keys_or_canary_plaintext() -> None:
    keyring = _keyring()
    codec = KeyringSnapshotCodec()
    snapshot = _snapshot(codec=codec, keyring=keyring)
    manifest = snapshot.manifest.serialized_bytes()
    visible = manifest + repr(snapshot).encode() + repr(_escrow_key()).encode()

    assert MASTER_V1 not in visible
    assert MASTER_V2 not in visible
    assert ESCROW not in visible
    assert b"geo-representative-secret-canary" not in visible
    assert MASTER_V1 not in snapshot.ciphertext
    assert MASTER_V2 not in snapshot.ciphertext
    assert ESCROW not in snapshot.ciphertext
    assert "ciphertext=" not in repr(snapshot)


def test_missing_wrong_and_mismatched_escrow_keys_fail_closed() -> None:
    codec = KeyringSnapshotCodec()
    snapshot = _snapshot(codec=codec)

    with pytest.raises(SecretConfigurationError, match="required"):
        codec.restore(snapshot=snapshot, escrow_key=None)
    with pytest.raises(SecretConfigurationError, match="required"):
        codec.seal(
            keyring=_keyring(),
            escrow_key=None,
            representative_canaries=_representatives(EnvelopeCipher(_keyring())),
            snapshot_id=uuid4(),
            created_at=NOW,
            data_backup_reference=DATA_BACKUP_REFERENCE,
        )
    with pytest.raises(SecretSnapshotIntegrityError, match="does not match"):
        codec.restore(
            snapshot=snapshot,
            escrow_key=RecoveryEscrowKey(id="other-escrow-key", material=b"W" * 32),
        )
    with pytest.raises(SecretSnapshotIntegrityError, match="authentication failed"):
        codec.restore(
            snapshot=snapshot,
            escrow_key=RecoveryEscrowKey(id="offline-escrow-key-v1", material=b"W" * 32),
        )


def test_manifest_aad_and_ciphertext_checksum_detect_tampering() -> None:
    codec = KeyringSnapshotCodec()
    snapshot = _snapshot(codec=codec)
    forged_manifest = replace(
        snapshot.manifest,
        data_backup_reference="data-backup-set-forged",
    )
    forged_snapshot = AuthenticatedKeyringSnapshot(
        manifest=forged_manifest,
        ciphertext=snapshot.ciphertext,
    )

    with pytest.raises(SecretSnapshotIntegrityError, match="authentication failed"):
        codec.restore(snapshot=forged_snapshot, escrow_key=_escrow_key())

    tampered = bytes([snapshot.ciphertext[0] ^ 1]) + snapshot.ciphertext[1:]
    with pytest.raises(SecretSnapshotIntegrityError, match="checksum"):
        AuthenticatedKeyringSnapshot(manifest=snapshot.manifest, ciphertext=tampered)


def test_escrow_key_must_be_distinct_from_every_application_master_key() -> None:
    keyring = _keyring()
    codec = KeyringSnapshotCodec()

    with pytest.raises(SecretConfigurationError, match="independent"):
        codec.seal(
            keyring=keyring,
            escrow_key=RecoveryEscrowKey(id="bad-escrow-key", material=MASTER_V2),
            representative_canaries=_representatives(EnvelopeCipher(keyring)),
            snapshot_id=uuid4(),
            created_at=NOW,
            data_backup_reference=DATA_BACKUP_REFERENCE,
        )


def test_required_representative_canary_coverage_is_enforced() -> None:
    keyring = _keyring()
    cipher = EnvelopeCipher(keyring)
    representatives = _representatives(cipher)

    with pytest.raises(SecretConfigurationError, match="coverage is incomplete"):
        KeyringSnapshotCodec().seal(
            keyring=keyring,
            escrow_key=_escrow_key(),
            representative_canaries=representatives[:-1],
            snapshot_id=uuid4(),
            created_at=NOW,
            data_backup_reference=DATA_BACKUP_REFERENCE,
        )


def test_corrupt_representative_envelope_is_rejected_before_backup() -> None:
    keyring = _keyring()
    cipher = EnvelopeCipher(keyring)
    representatives = list(_representatives(cipher))
    original = representatives[0]
    corrupt_envelope = replace(
        original.envelope,
        ciphertext=bytes([original.envelope.ciphertext[0] ^ 1])
        + original.envelope.ciphertext[1:],
    )
    representatives[0] = replace(original, envelope=corrupt_envelope)

    with pytest.raises(SecretSnapshotIntegrityError, match="canary verification failed"):
        KeyringSnapshotCodec().seal(
            keyring=keyring,
            escrow_key=_escrow_key(),
            representative_canaries=representatives,
            snapshot_id=uuid4(),
            created_at=NOW,
            data_backup_reference=DATA_BACKUP_REFERENCE,
        )


def test_recovery_objects_cannot_enter_pickle_jobs_or_artifacts() -> None:
    codec = KeyringSnapshotCodec()
    snapshot = _snapshot(codec=codec)
    restored = codec.restore(snapshot=snapshot, escrow_key=_escrow_key())
    representative = _representatives(EnvelopeCipher(_keyring()))[0]

    for sensitive in (_escrow_key(), snapshot, restored, representative):
        with pytest.raises(SecretSerializationRejected, match="cannot be serialized"):
            pickle.dumps(sensitive)
        with pytest.raises(SecretSerializationRejected, match="cannot enter"):
            reject_secret_bearing_payload(sensitive)


def test_post_data_restore_probe_interface_validates_external_representatives() -> None:
    keyring = _keyring()
    probes = _representatives(EnvelopeCipher(keyring))

    verified = verify_representative_secret_probes(keyring=keyring, probes=probes)

    assert verified == ("connector", "egress", "provider")
    with pytest.raises(SecretConfigurationError, match="coverage is incomplete"):
        verify_representative_secret_probes(keyring=keyring, probes=probes[:-1])


def _snapshot(
    *,
    codec: KeyringSnapshotCodec,
    keyring: MasterKeyring | None = None,
) -> AuthenticatedKeyringSnapshot:
    selected = _keyring() if keyring is None else keyring
    return codec.seal(
        keyring=selected,
        escrow_key=_escrow_key(),
        representative_canaries=_representatives(EnvelopeCipher(selected)),
        snapshot_id=uuid4(),
        created_at=NOW,
        data_backup_reference=DATA_BACKUP_REFERENCE,
    )


def _keyring() -> MasterKeyring:
    return MasterKeyring(keys={1: MASTER_V1, 2: MASTER_V2}, active_version=2)


def _escrow_key() -> RecoveryEscrowKey:
    return RecoveryEscrowKey(id="offline-escrow-key-v1", material=ESCROW)


def _representatives(cipher: EnvelopeCipher) -> tuple[RepresentativeSecretCanary, ...]:
    purpose_by_kind = {
        "connector": "recovery.connector",
        "provider": "recovery.provider",
        "egress": "recovery.egress",
    }
    project_id = uuid4()
    return tuple(
        create_representative_secret_canary(
            cipher=cipher,
            canary_id=uuid4(),
            kind=kind,
            project_id=project_id,
            purpose=purpose,
            created_at=NOW,
        )
        for kind, purpose in purpose_by_kind.items()
    )
