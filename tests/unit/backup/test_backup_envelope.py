from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path

import pytest

from scripts.alembic_sql_ledger import build_ledger
from scripts.backup_envelope import (
    BackupSecurityError,
    decrypt_authenticated_to_stream,
    encrypt_stream,
    inspect_envelope,
    load_backup_keyring,
)
from scripts.backup_manifest import (
    create_backup_set_manifest,
    decrypt_backup_artifact,
    verify_backup_set,
)


CANARY = b"BACKUP-PLAINTEXT-CANARY-MUST-STAY-ENCRYPTED-1842\x00" * 50_000
MASTER_V1 = bytes(range(32))
MASTER_V2 = bytes(reversed(range(32)))
RELATION_HASHES = {
    "evidence_items": "1" * 64,
    "monitoring_reports": "2" * 64,
    "project_memberships": "3" * 64,
    "projects": "4" * 64,
}
BUSINESS_RELATIONS = {
    "model_gateway_call_attempts",
    "model_gateway_job_admissions",
    "model_gateway_runtime_manifests",
    "model_gateway_runtime_options",
    "model_gateway_terminal_events",
    "prompt_program_bindings",
    "prompt_program_releases",
    "prompt_programs",
    "synthetic_lab_aggregate_versions",
    "synthetic_lab_artifact_governance_decisions",
    "synthetic_lab_execution_results",
    "synthetic_lab_execution_tasks",
    "synthetic_lab_manual_import_manifests",
    "synthetic_lab_terminal_results",
}
EMPTY_HASH = hashlib.sha256(b"").hexdigest()
BUSINESS_CONSISTENCY = {
    "invariant_violations": {},
    "migration_revision": "0028_secret_store",
    "schema_version": "geo-non-b-business-consistency-v1",
    "tables": {
        relation: {
            "aggregate_sha256": EMPTY_HASH,
            "scopes": {},
            "total_count": 0,
        }
        for relation in BUSINESS_RELATIONS
    },
}
RECOMMENDATION_SOURCE = {
    "artifact_lineage_count": 0,
    "master_key_version_count": 1,
    "representative_probe_target_count": 0,
    "source_verification_receipt_hash": "5" * 64,
}
WORKFLOW_C_SOURCE = {
    "active_dek_count": 0,
    "master_key_version_count": 1,
    "recoverable_artifact_count": 0,
    "representative_probe_target_count": 0,
    "source_verification_receipt_hash": "6" * 64,
}
ROOT = Path(__file__).resolve().parents[3]
MIGRATION_LEDGER = build_ledger(
    ROOT / "infra" / "db" / "alembic" / "sql",
    head_revision="0028_secret_store",
)


def test_streaming_envelope_and_signed_manifest_round_trip(tmp_path: Path) -> None:
    keyring_path = _keyring(tmp_path, active=2)
    keyring = load_backup_keyring(keyring_path)
    backup = _backup_set(tmp_path, keyring=keyring)

    manifest = verify_backup_set(backup, keyring=keyring)
    restored_postgres = BytesIO()
    restored_minio = BytesIO()
    restore_staging = _secure_directory(tmp_path / "restore-staging")
    decrypt_backup_artifact(
        backup,
        "postgres",
        restored_postgres,
        keyring=keyring,
        staging_directory=restore_staging,
    )
    decrypt_backup_artifact(
        backup,
        "minio",
        restored_minio,
        keyring=keyring,
        staging_directory=restore_staging,
    )

    assert restored_postgres.getvalue() == CANARY
    assert restored_minio.getvalue() == b"minio-tar-stream\x00" + CANARY
    assert manifest["key_version"] == 2
    assert manifest["source"] == {
        "minio": {
            "bucket_object_counts": {
                "geo-artifacts": 2,
                "geo-restricted-recommendation-artifacts": 0,
                "geo-restricted-workflow-c-artifacts": 1,
                "geo-synthetic-style-derived": 0,
                "geo-synthetic-style-raw": 0,
            },
            "object_count": 3,
        },
        "provider_artifacts": {
            "active_dek_count": 0,
            "master_key_version_count": 1,
            "recoverable_artifact_count": 0,
            "representative_probe_target_count": 0,
        },
        "recommendation_artifacts": RECOMMENDATION_SOURCE,
        "postgres": {
            "alembic_sql_checksum_ledger": MIGRATION_LEDGER,
            "critical_relation_counts": {
                "evidence_items": 5,
                "monitoring_reports": 3,
                "project_memberships": 4,
            },
            "critical_relation_hashes": RELATION_HASHES,
            "migration_revision": "0028_secret_store",
            "non_b_business_consistency": BUSINESS_CONSISTENCY,
            "project_count": 2,
            "table_count": 42,
        },
        "secret_store": {
            "encrypted_secret_version_count": 4,
            "master_key_version_count": 2,
            "representative_probe_target_count": 2,
        },
        "synthetic_artifacts": {
            "active_dek_count": 0,
            "master_key_version_count": 1,
            "nondeleted_artifact_count": 0,
            "restricted_probe_target_count": 0,
            "tier_key_artifact_count": 0,
            "tier_probe_target_count": 0,
        },
        "workflow_c_artifacts": WORKFLOW_C_SOURCE,
    }
    persisted = b"".join(item.read_bytes() for item in backup.iterdir())
    assert CANARY[:48] not in persisted
    assert MASTER_V1 not in persisted
    assert MASTER_V2 not in persisted
    assert not list(restore_staging.iterdir())


def test_every_artifact_uses_a_fresh_data_key_and_nonce(tmp_path: Path) -> None:
    keyring = load_backup_keyring(_keyring(tmp_path, active=1))
    output = _secure_directory(tmp_path / "output")
    first = output / "first.enc"
    second = output / "second.enc"

    encrypt_stream(BytesIO(CANARY), first, keyring=keyring, backup_id="run-1", artifact="one")
    encrypt_stream(BytesIO(CANARY), second, keyring=keyring, backup_id="run-1", artifact="two")

    assert first.read_bytes() != second.read_bytes()
    assert inspect_envelope(first).encrypted_sha256 != inspect_envelope(second).encrypted_sha256


def test_envelope_commit_never_overwrites_an_existing_backup_file(tmp_path: Path) -> None:
    keyring = load_backup_keyring(_keyring(tmp_path, active=1))
    output = _secure_directory(tmp_path / "output")
    destination = output / "artifact.enc"
    encrypt_stream(
        BytesIO(CANARY),
        destination,
        keyring=keyring,
        backup_id="append-only",
        artifact="postgres",
    )
    original = destination.read_bytes()

    with pytest.raises(BackupSecurityError):
        encrypt_stream(
            BytesIO(b"replacement"),
            destination,
            keyring=keyring,
            backup_id="append-only",
            artifact="postgres",
        )

    assert destination.read_bytes() == original


@pytest.mark.parametrize("mutation", ("ciphertext", "tag", "truncate"))
def test_envelope_tamper_never_releases_unauthenticated_plaintext(
    tmp_path: Path,
    mutation: str,
) -> None:
    keyring = load_backup_keyring(_keyring(tmp_path, active=1))
    output = _secure_directory(tmp_path / "output")
    envelope = output / "artifact.enc"
    encrypt_stream(
        BytesIO(CANARY), envelope, keyring=keyring, backup_id="tamper-run", artifact="postgres"
    )
    raw = bytearray(envelope.read_bytes())
    if mutation == "ciphertext":
        raw[len(raw) // 2] ^= 1
    elif mutation == "tag":
        raw[-1] ^= 1
    else:
        del raw[-8:]
    envelope.write_bytes(raw)
    envelope.chmod(0o600)
    destination = BytesIO()

    with pytest.raises(BackupSecurityError):
        decrypt_authenticated_to_stream(
            envelope,
            destination,
            keyring=keyring,
            expected_backup_id="tamper-run",
            expected_artifact="postgres",
            staging_directory=_secure_directory(tmp_path / "restore"),
        )

    assert destination.getvalue() == b""


def test_wrong_missing_and_old_keyrings_fail_closed(tmp_path: Path) -> None:
    current = load_backup_keyring(_keyring(tmp_path, active=2, name="current.json"))
    output = _secure_directory(tmp_path / "output")
    envelope = output / "artifact.enc"
    encrypt_stream(
        BytesIO(CANARY), envelope, keyring=current, backup_id="key-run", artifact="postgres"
    )
    wrong = load_backup_keyring(
        _keyring(tmp_path, active=2, name="wrong.json", v1=b"W" * 32, v2=b"X" * 32)
    )
    old = load_backup_keyring(
        _keyring(tmp_path, active=1, name="old.json", include_v2=False)
    )
    staging = _secure_directory(tmp_path / "restore")

    for keyring in (wrong, old):
        destination = BytesIO()
        with pytest.raises(BackupSecurityError):
            decrypt_authenticated_to_stream(
                envelope,
                destination,
                keyring=keyring,
                expected_backup_id="key-run",
                expected_artifact="postgres",
                staging_directory=staging,
            )
        assert destination.getvalue() == b""


@pytest.mark.parametrize("target", ("manifest.json", "manifest.sig", "COMMITTED"))
def test_manifest_signature_and_commit_tamper_fail_before_decryption(
    tmp_path: Path,
    target: str,
) -> None:
    keyring = load_backup_keyring(_keyring(tmp_path, active=1))
    backup = _backup_set(tmp_path, keyring=keyring)
    path = backup / target
    raw = bytearray(path.read_bytes())
    raw[len(raw) // 2] ^= 1
    path.write_bytes(raw)
    path.chmod(0o600)

    with pytest.raises(BackupSecurityError):
        verify_backup_set(backup, keyring=keyring)


@pytest.mark.parametrize("target", ("postgres.sql.gz.enc", "minio.tar.enc"))
def test_encrypted_artifact_hash_and_truncation_fail_manifest_verification(
    tmp_path: Path,
    target: str,
) -> None:
    keyring = load_backup_keyring(_keyring(tmp_path, active=1))
    backup = _backup_set(tmp_path, keyring=keyring)
    path = backup / target
    path.write_bytes(path.read_bytes()[:-1])
    path.chmod(0o600)

    with pytest.raises(BackupSecurityError):
        verify_backup_set(backup, keyring=keyring)


def test_keyring_and_backup_permissions_and_symlinks_are_rejected(tmp_path: Path) -> None:
    keyring_path = _keyring(tmp_path, active=1)
    keyring_path.chmod(0o640)
    with pytest.raises(BackupSecurityError):
        load_backup_keyring(keyring_path)
    keyring_path.chmod(0o600)
    link = tmp_path / "keyring-link.json"
    link.symlink_to(keyring_path)
    with pytest.raises(BackupSecurityError):
        load_backup_keyring(link)

    keyring = load_backup_keyring(keyring_path)
    backup = _backup_set(tmp_path, keyring=keyring)
    backup.chmod(0o750)
    with pytest.raises(BackupSecurityError):
        verify_backup_set(backup, keyring=keyring)
    backup.chmod(0o700)
    artifact = backup / "postgres.sql.gz.enc"
    artifact.chmod(0o640)
    with pytest.raises(BackupSecurityError):
        verify_backup_set(backup, keyring=keyring)


def test_uncommitted_extra_and_inconsistent_probe_sets_are_rejected(tmp_path: Path) -> None:
    keyring = load_backup_keyring(_keyring(tmp_path, active=1))
    backup = _backup_set(tmp_path, keyring=keyring)
    (backup / "COMMITTED").unlink()
    with pytest.raises(BackupSecurityError):
        verify_backup_set(backup, keyring=keyring)

    backup = _backup_set(tmp_path, keyring=keyring, name="extra-backup")
    extra = backup / "plaintext.sql"
    extra.write_text("must-not-exist", encoding="utf-8")
    extra.chmod(0o600)
    with pytest.raises(BackupSecurityError):
        verify_backup_set(backup, keyring=keyring)

    raw = _secure_directory(tmp_path / "inconsistent")
    _write_artifacts(raw, keyring=keyring, backup_id="inconsistent")
    with pytest.raises(BackupSecurityError):
        create_backup_set_manifest(
            raw,
            keyring=keyring,
            backup_id="inconsistent",
            created_at="2026-07-23T03:00:00Z",
            migration_revision="0028_secret_store",
            alembic_sql_checksum_ledger=MIGRATION_LEDGER,
            postgres_project_count=0,
            postgres_table_count=1,
            critical_relation_counts={
                "evidence_items": 0,
                "monitoring_reports": 0,
                "project_memberships": 0,
            },
            critical_relation_hashes=RELATION_HASHES,
            non_b_business_consistency=BUSINESS_CONSISTENCY,
            minio_object_count=0,
            minio_bucket_object_counts={
                "geo-artifacts": 0,
                "geo-restricted-recommendation-artifacts": 0,
                "geo-restricted-workflow-c-artifacts": 0,
                "geo-synthetic-style-derived": 0,
                "geo-synthetic-style-raw": 0,
            },
            secret_key_version_count=1,
            secret_version_count=0,
            representative_probe_target_count=1,
            provider_artifact_key_version_count=1,
            provider_active_dek_count=0,
            provider_recoverable_artifact_count=0,
            provider_representative_probe_target_count=0,
            synthetic_artifact_key_version_count=1,
            synthetic_active_dek_count=0,
            synthetic_nondeleted_artifact_count=0,
            synthetic_tier_key_artifact_count=0,
            synthetic_restricted_probe_target_count=0,
            synthetic_tier_probe_target_count=0,
            recommendation_artifact_key_version_count=1,
            recommendation_artifact_lineage_count=0,
            recommendation_representative_probe_target_count=0,
            recommendation_source_verification_receipt_hash="5" * 64,
            workflow_c_artifact_key_version_count=1,
            workflow_c_active_dek_count=0,
            workflow_c_recoverable_artifact_count=0,
            workflow_c_representative_probe_target_count=0,
            workflow_c_source_verification_receipt_hash="6" * 64,
        )

    no_key_canary = _secure_directory(tmp_path / "no-key-canary")
    _write_artifacts(no_key_canary, keyring=keyring, backup_id="no-key-canary")
    with pytest.raises(BackupSecurityError):
        create_backup_set_manifest(
            no_key_canary,
            keyring=keyring,
            backup_id="no-key-canary",
            created_at="2026-07-23T03:00:00Z",
            migration_revision="0028_secret_store",
            alembic_sql_checksum_ledger=MIGRATION_LEDGER,
            postgres_project_count=0,
            postgres_table_count=1,
            critical_relation_counts={
                "evidence_items": 0,
                "monitoring_reports": 0,
                "project_memberships": 0,
            },
            critical_relation_hashes=RELATION_HASHES,
            non_b_business_consistency=BUSINESS_CONSISTENCY,
            minio_object_count=0,
            minio_bucket_object_counts={
                "geo-artifacts": 0,
                "geo-restricted-recommendation-artifacts": 0,
                "geo-restricted-workflow-c-artifacts": 0,
                "geo-synthetic-style-derived": 0,
                "geo-synthetic-style-raw": 0,
            },
            secret_key_version_count=0,
            secret_version_count=0,
            representative_probe_target_count=0,
            provider_artifact_key_version_count=1,
            provider_active_dek_count=0,
            provider_recoverable_artifact_count=0,
            provider_representative_probe_target_count=0,
            synthetic_artifact_key_version_count=1,
            synthetic_active_dek_count=0,
            synthetic_nondeleted_artifact_count=0,
            synthetic_tier_key_artifact_count=0,
            synthetic_restricted_probe_target_count=0,
            synthetic_tier_probe_target_count=0,
            recommendation_artifact_key_version_count=1,
            recommendation_artifact_lineage_count=0,
            recommendation_representative_probe_target_count=0,
            recommendation_source_verification_receipt_hash="5" * 64,
            workflow_c_artifact_key_version_count=1,
            workflow_c_active_dek_count=0,
            workflow_c_recoverable_artifact_count=0,
            workflow_c_representative_probe_target_count=0,
            workflow_c_source_verification_receipt_hash="6" * 64,
        )


def test_historical_key_remains_usable_for_committed_backup(tmp_path: Path) -> None:
    initial = load_backup_keyring(_keyring(tmp_path, active=1, name="initial.json"))
    backup = _backup_set(tmp_path, keyring=initial)
    rotated = load_backup_keyring(_keyring(tmp_path, active=2, name="rotated.json"))

    assert verify_backup_set(backup, keyring=rotated)["key_version"] == 1
    restored = BytesIO()
    decrypt_backup_artifact(
        backup,
        "postgres",
        restored,
        keyring=rotated,
        staging_directory=_secure_directory(tmp_path / "restore"),
    )
    assert restored.getvalue() == CANARY


def _backup_set(
    tmp_path: Path,
    *,
    keyring: object,
    name: str = "backup",
) -> Path:
    backup = _secure_directory(tmp_path / name)
    _write_artifacts(backup, keyring=keyring, backup_id=name)
    create_backup_set_manifest(
        backup,
        keyring=keyring,
        backup_id=name,
        created_at="2026-07-23T03:00:00Z",
        migration_revision="0028_secret_store",
        alembic_sql_checksum_ledger=MIGRATION_LEDGER,
        postgres_project_count=2,
        postgres_table_count=42,
        critical_relation_counts={
            "evidence_items": 5,
            "monitoring_reports": 3,
            "project_memberships": 4,
        },
        critical_relation_hashes=RELATION_HASHES,
        non_b_business_consistency=BUSINESS_CONSISTENCY,
        minio_object_count=3,
        minio_bucket_object_counts={
            "geo-artifacts": 2,
            "geo-restricted-recommendation-artifacts": 0,
            "geo-restricted-workflow-c-artifacts": 1,
            "geo-synthetic-style-derived": 0,
            "geo-synthetic-style-raw": 0,
        },
        secret_key_version_count=2,
        secret_version_count=4,
        representative_probe_target_count=2,
        provider_artifact_key_version_count=1,
        provider_active_dek_count=0,
        provider_recoverable_artifact_count=0,
        provider_representative_probe_target_count=0,
        synthetic_artifact_key_version_count=1,
        synthetic_active_dek_count=0,
        synthetic_nondeleted_artifact_count=0,
        synthetic_tier_key_artifact_count=0,
        synthetic_restricted_probe_target_count=0,
        synthetic_tier_probe_target_count=0,
        recommendation_artifact_key_version_count=1,
        recommendation_artifact_lineage_count=0,
        recommendation_representative_probe_target_count=0,
        recommendation_source_verification_receipt_hash="5" * 64,
        workflow_c_artifact_key_version_count=1,
        workflow_c_active_dek_count=0,
        workflow_c_recoverable_artifact_count=0,
        workflow_c_representative_probe_target_count=0,
        workflow_c_source_verification_receipt_hash="6" * 64,
    )
    return backup


def _write_artifacts(backup: Path, *, keyring: object, backup_id: str) -> None:
    encrypt_stream(
        BytesIO(CANARY),
        backup / "postgres.sql.gz.enc",
        keyring=keyring,
        backup_id=backup_id,
        artifact="postgres",
    )
    encrypt_stream(
        BytesIO(b"minio-tar-stream\x00" + CANARY),
        backup / "minio.tar.enc",
        keyring=keyring,
        backup_id=backup_id,
        artifact="minio",
    )


def _keyring(
    tmp_path: Path,
    *,
    active: int,
    name: str = "backup-keyring.json",
    v1: bytes = MASTER_V1,
    v2: bytes = MASTER_V2,
    include_v2: bool = True,
) -> Path:
    entries = [
        {
            "key": base64.b64encode(v1).decode("ascii"),
            "status": "encrypt_decrypt" if active == 1 else "decrypt_only",
            "version": 1,
        }
    ]
    if include_v2:
        entries.append(
            {
                "key": base64.b64encode(v2).decode("ascii"),
                "status": "encrypt_decrypt" if active == 2 else "decrypt_only",
                "version": 2,
            }
        )
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {"active_version": active, "format": "geo-backup-keyring-v1", "keys": entries},
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="ascii",
    )
    path.chmod(0o600)
    return path


def _secure_directory(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path
