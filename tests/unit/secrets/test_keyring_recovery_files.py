from datetime import UTC, datetime
from pathlib import Path
import stat
from uuid import uuid4

import pytest

import geo_core.secrets.recovery_files as recovery_files
from geo_core.secrets import (
    AuthenticatedKeyringSnapshot,
    EnvelopeCipher,
    KeyringSnapshotCodec,
    KeyringSnapshotFileStore,
    MasterKeyring,
    RecoveryEscrowKey,
    SecretBackupLocationError,
    SecretConfigurationError,
    SecretReference,
    SecretSnapshotAlreadyExists,
    SecretSnapshotIntegrityError,
    SecretValue,
    create_representative_secret_canary,
)
NOW = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)
MASTER_V1 = bytes(range(32))
MASTER_V2 = bytes(reversed(range(32)))
ESCROW = b"E" * 32
DATA_BACKUP_REFERENCE = "data-backup-set-2026-07-23-01"


def test_file_snapshot_is_committed_with_strict_modes_and_restores(tmp_path: Path) -> None:
    store = _store(tmp_path)
    codec, snapshot, escrow_key = _snapshot()

    bundle = store.save(snapshot)
    result = store.restore(
        snapshot_id=snapshot.manifest.snapshot_id,
        codec=codec,
        escrow_key=escrow_key,
    )

    assert stat.S_IMODE((tmp_path / "keyring-escrow").stat().st_mode) == 0o700
    assert stat.S_IMODE(bundle.stat().st_mode) == 0o700
    assert {item.name for item in bundle.iterdir()} == {
        "manifest.json",
        "keyring.enc",
        "COMMITTED",
    }
    assert all(stat.S_IMODE(item.stat().st_mode) == 0o600 for item in bundle.iterdir())
    assert result.keyring.versions == (1, 2)
    assert result.data_backup_reference == DATA_BACKUP_REFERENCE

    persisted = b"".join(item.read_bytes() for item in bundle.iterdir())
    assert MASTER_V1 not in persisted
    assert MASTER_V2 not in persisted
    assert ESCROW not in persisted
    assert b"geo-representative-secret-canary" not in persisted


def test_snapshot_identity_is_immutable_and_second_save_does_not_overwrite(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _, snapshot, _ = _snapshot()
    bundle = store.save(snapshot)
    before = {item.name: item.read_bytes() for item in bundle.iterdir()}

    with pytest.raises(SecretSnapshotAlreadyExists, match="already exists"):
        store.save(snapshot)

    assert {item.name: item.read_bytes() for item in bundle.iterdir()} == before


def test_empty_environment_file_restore_decrypts_a_historical_envelope(tmp_path: Path) -> None:
    old_cipher = EnvelopeCipher(MasterKeyring(keys={1: MASTER_V1}, active_version=1))
    reference = SecretReference(
        id=uuid4(),
        project_id=uuid4(),
        purpose="provider.deepseek",
        created_at=NOW,
    )
    historical = old_cipher.encrypt(
        reference=reference,
        version=1,
        value=SecretValue("historical-recovery-test-value"),
        created_at=NOW,
    )
    store = _store(tmp_path)
    codec, snapshot, escrow_key = _snapshot()
    store.save(snapshot)

    result = store.restore(
        snapshot_id=snapshot.manifest.snapshot_id,
        codec=codec,
        escrow_key=escrow_key,
    )

    assert EnvelopeCipher(result.keyring).decrypt(historical).matches(
        "historical-recovery-test-value"
    )


@pytest.mark.parametrize("partial_name", ["manifest.json", "keyring.enc", "COMMITTED"])
def test_partial_snapshot_restore_fails_closed(tmp_path: Path, partial_name: str) -> None:
    store = _store(tmp_path)
    _, snapshot, _ = _snapshot()
    bundle = store.save(snapshot)
    (bundle / partial_name).unlink()

    with pytest.raises(SecretSnapshotIntegrityError, match="partial"):
        store.load(snapshot.manifest.snapshot_id)


def test_ciphertext_tamper_and_manifest_checksum_tamper_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _, snapshot, _ = _snapshot()
    bundle = store.save(snapshot)
    ciphertext_file = bundle / "keyring.enc"
    ciphertext = ciphertext_file.read_bytes()
    ciphertext_file.write_bytes(bytes([ciphertext[0] ^ 1]) + ciphertext[1:])

    with pytest.raises(SecretSnapshotIntegrityError, match="checksum"):
        store.load(snapshot.manifest.snapshot_id)

    other_store = _store(tmp_path / "other")
    _, other_snapshot, _ = _snapshot()
    other_bundle = other_store.save(other_snapshot)
    manifest_file = other_bundle / "manifest.json"
    manifest_file.write_bytes(manifest_file.read_bytes() + b"\n")
    with pytest.raises(SecretSnapshotIntegrityError, match="canonical"):
        other_store.load(other_snapshot.manifest.snapshot_id)


def test_commit_checksum_tamper_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _, snapshot, _ = _snapshot()
    bundle = store.save(snapshot)
    commit_file = bundle / "COMMITTED"
    raw = commit_file.read_bytes()
    commit_file.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])

    with pytest.raises(SecretSnapshotIntegrityError, match="commit is invalid"):
        store.load(snapshot.manifest.snapshot_id)


def test_snapshot_symlink_file_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _, snapshot, _ = _snapshot()
    bundle = store.save(snapshot)
    manifest = bundle / "manifest.json"
    target = tmp_path / "manifest-target"
    manifest.rename(target)
    manifest.symlink_to(target)

    with pytest.raises(SecretSnapshotIntegrityError, match="must be regular"):
        store.load(snapshot.manifest.snapshot_id)


@pytest.mark.parametrize("relative_file", ["manifest.json", "keyring.enc", "COMMITTED"])
def test_snapshot_file_permissions_must_remain_0600(
    tmp_path: Path,
    relative_file: str,
) -> None:
    store = _store(tmp_path)
    _, snapshot, _ = _snapshot()
    bundle = store.save(snapshot)
    (bundle / relative_file).chmod(0o644)

    with pytest.raises(SecretSnapshotIntegrityError, match="permissions"):
        store.load(snapshot.manifest.snapshot_id)


def test_escrow_root_and_bundle_permissions_must_remain_0700(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _, snapshot, _ = _snapshot()
    bundle = store.save(snapshot)
    bundle.chmod(0o750)

    with pytest.raises(SecretBackupLocationError, match="0700"):
        store.load(snapshot.manifest.snapshot_id)

    bundle.chmod(0o700)
    (tmp_path / "keyring-escrow").chmod(0o755)
    with pytest.raises(SecretBackupLocationError, match="0700"):
        store.load(snapshot.manifest.snapshot_id)


def test_overlapping_or_same_logical_backup_locations_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(SecretBackupLocationError, match="paths must not overlap"):
        KeyringSnapshotFileStore(
            escrow_directory=tmp_path / "backups" / "keyring",
            data_backup_directory=tmp_path / "backups",
            escrow_location_id="offline-keyring-a",
            data_backup_location_id="data-backup-a",
        )

    with pytest.raises(SecretBackupLocationError, match="must be independent"):
        KeyringSnapshotFileStore(
            escrow_directory=tmp_path / "keyring",
            data_backup_directory=tmp_path / "data",
            escrow_location_id="same-location",
            data_backup_location_id="same-location",
        )


def test_atomic_write_failure_removes_uncommitted_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    _, snapshot, _ = _snapshot()
    original = recovery_files._atomic_write_file
    calls = 0

    def fail_second_write(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SecretBackupLocationError("simulated safe write failure")
        original(path, payload)

    monkeypatch.setattr(recovery_files, "_atomic_write_file", fail_second_write)

    with pytest.raises(SecretBackupLocationError, match="simulated"):
        store.save(snapshot)

    assert not (tmp_path / "keyring-escrow" / str(snapshot.manifest.snapshot_id)).exists()


def test_file_restore_propagates_missing_and_wrong_escrow_key_failures(tmp_path: Path) -> None:
    store = _store(tmp_path)
    codec, snapshot, _ = _snapshot()
    store.save(snapshot)

    with pytest.raises(SecretConfigurationError, match="required"):
        store.restore(
            snapshot_id=snapshot.manifest.snapshot_id,
            codec=codec,
            escrow_key=None,
        )
    with pytest.raises(SecretSnapshotIntegrityError, match="authentication failed"):
        store.restore(
            snapshot_id=snapshot.manifest.snapshot_id,
            codec=codec,
            escrow_key=RecoveryEscrowKey(
                id="offline-escrow-key-v1",
                material=b"W" * 32,
            ),
        )


def _store(tmp_path: Path) -> KeyringSnapshotFileStore:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return KeyringSnapshotFileStore(
        escrow_directory=tmp_path / "keyring-escrow",
        data_backup_directory=tmp_path / "data-backup",
        escrow_location_id="offline-keyring-a",
        data_backup_location_id="production-data-a",
    )


def _snapshot() -> tuple[
    KeyringSnapshotCodec,
    AuthenticatedKeyringSnapshot,
    RecoveryEscrowKey,
]:
    keyring = MasterKeyring(keys={1: MASTER_V1, 2: MASTER_V2}, active_version=2)
    cipher = EnvelopeCipher(keyring)
    project_id = uuid4()
    representatives = tuple(
        create_representative_secret_canary(
            cipher=cipher,
            canary_id=uuid4(),
            kind=kind,
            project_id=project_id,
            purpose=f"recovery.{kind}",
            created_at=NOW,
        )
        for kind in ("connector", "provider", "egress")
    )
    codec = KeyringSnapshotCodec()
    escrow_key = RecoveryEscrowKey(id="offline-escrow-key-v1", material=ESCROW)
    snapshot = codec.seal(
        keyring=keyring,
        escrow_key=escrow_key,
        representative_canaries=representatives,
        snapshot_id=uuid4(),
        created_at=NOW,
        data_backup_reference=DATA_BACKUP_REFERENCE,
    )
    return codec, snapshot, escrow_key
