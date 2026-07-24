from datetime import UTC, datetime
from pathlib import Path
import pickle
from uuid import uuid4

import pytest

from geo_core.secrets import (
    AuthenticatedKeyringSnapshot,
    EnvelopeCipher,
    KeyringSnapshotCodec,
    KeyringSnapshotFileStore,
    MasterKeyring,
    RecoveryEscrowKey,
    RepresentativeSecretCanary,
    SecretConfigurationError,
    SecretRecoveryApplication,
    SecretSerializationRejected,
    create_representative_secret_canary,
    reject_secret_bearing_payload,
)

NOW = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)
MASTER_V1 = b"A" * 32
MASTER_V2 = b"B" * 32
ESCROW = b"E" * 32


def test_recovery_application_verifies_history_and_external_secret_probes() -> None:
    codec, snapshot, escrow_key, probes = _recovery_inputs()

    readiness = SecretRecoveryApplication(codec).recover(
        snapshot=snapshot,
        escrow_key=escrow_key,
        representative_probes=probes,
    )

    assert readiness.restore_result.verified_key_versions == (1, 2)
    assert readiness.verified_external_kinds == ("connector", "egress", "provider")
    assert "MASTER" not in repr(readiness)
    with pytest.raises(SecretSerializationRejected, match="cannot enter"):
        reject_secret_bearing_payload(readiness)
    with pytest.raises(SecretSerializationRejected, match="cannot be serialized"):
        pickle.dumps(readiness)


def test_recovery_application_can_restore_from_independent_file_bundle(
    tmp_path: Path,
) -> None:
    codec, snapshot, escrow_key, probes = _recovery_inputs()
    file_store = KeyringSnapshotFileStore(
        escrow_directory=tmp_path / "keyring-escrow",
        data_backup_directory=tmp_path / "data-backup",
        escrow_location_id="offline-keyring-a",
        data_backup_location_id="production-data-a",
    )
    file_store.save(snapshot)

    readiness = SecretRecoveryApplication(codec).recover_from_file(
        file_store=file_store,
        snapshot_id=snapshot.manifest.snapshot_id,
        escrow_key=escrow_key,
        representative_probes=probes,
    )

    assert readiness.restore_result.snapshot_id == snapshot.manifest.snapshot_id
    assert readiness.restore_result.data_backup_reference == "data-backup-set-app-test"


def test_recovery_application_requires_complete_external_probe_coverage() -> None:
    codec, snapshot, escrow_key, probes = _recovery_inputs()

    with pytest.raises(SecretConfigurationError, match="coverage is incomplete"):
        SecretRecoveryApplication(codec).recover(
            snapshot=snapshot,
            escrow_key=escrow_key,
            representative_probes=probes[:-1],
        )


def _recovery_inputs() -> tuple[
    KeyringSnapshotCodec,
    AuthenticatedKeyringSnapshot,
    RecoveryEscrowKey,
    tuple[RepresentativeSecretCanary, ...],
]:
    keyring = MasterKeyring(keys={1: MASTER_V1, 2: MASTER_V2}, active_version=2)
    cipher = EnvelopeCipher(keyring)
    project_id = uuid4()
    probes = tuple(
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
        representative_canaries=probes,
        snapshot_id=uuid4(),
        created_at=NOW,
        data_backup_reference="data-backup-set-app-test",
    )
    return codec, snapshot, escrow_key, probes
