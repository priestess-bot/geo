from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from scripts.alembic_sql_ledger import build_ledger


ROOT = Path(__file__).resolve().parents[3]
ENVELOPE = ROOT / "scripts" / "backup_envelope.py"
MANIFEST = ROOT / "scripts" / "backup_manifest.py"


def _business_consistency(revision: str) -> str:
    relations = {
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
    empty_hash = hashlib.sha256(b"").hexdigest()
    return json.dumps(
        {
            "invariant_violations": {},
            "migration_revision": revision,
            "schema_version": "geo-non-b-business-consistency-v1",
            "tables": {
                relation: {
                    "aggregate_sha256": empty_hash,
                    "scopes": {},
                    "total_count": 0,
                }
                for relation in relations
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def test_file_entrypoints_run_outside_repository_and_preserve_binary_streams(
    tmp_path: Path,
) -> None:
    keyring = tmp_path / "keyring.json"
    keyring.write_text(
        json.dumps(
            {
                "active_version": 1,
                "format": "geo-backup-keyring-v1",
                "keys": [
                    {
                        "key": base64.b64encode(b"K" * 32).decode("ascii"),
                        "status": "encrypt_decrypt",
                        "version": 1,
                    }
                ],
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="ascii",
    )
    keyring.chmod(0o600)
    backup = tmp_path / "backup"
    backup.mkdir(mode=0o700)
    restore = tmp_path / "restore"
    restore.mkdir(mode=0o700)
    postgres = b"gzip-compatible-binary\x00postgres"
    minio = b"tar-compatible-binary\x00minio"
    migration_ledger = build_ledger(
        ROOT / "infra" / "db" / "alembic" / "sql",
        head_revision="0028_secret_store",
    )

    for artifact, content, filename in (
        ("postgres", postgres, "postgres.sql.gz.enc"),
        ("minio", minio, "minio.tar.enc"),
    ):
        completed = subprocess.run(
            [
                sys.executable,
                str(ENVELOPE),
                "encrypt",
                "--keyring",
                str(keyring),
                "--backup-id",
                "cli-backup",
                "--artifact",
                artifact,
                "--output",
                str(backup / filename),
            ],
            cwd=tmp_path,
            input=content,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

    created = subprocess.run(
        [
            sys.executable,
            str(MANIFEST),
            "create",
            "--keyring",
            str(keyring),
            "--backup-dir",
            str(backup),
            "--backup-id",
            "cli-backup",
            "--created-at",
            "2026-07-23T03:00:00Z",
            "--migration-revision",
            "0028_secret_store",
            "--alembic-sql-checksum-ledger-json",
            json.dumps(migration_ledger, separators=(",", ":"), sort_keys=True),
            "--postgres-project-count",
            "0",
            "--postgres-table-count",
            "40",
            "--critical-relation-counts-json",
            '{"evidence_items":0,"monitoring_reports":0,"project_memberships":0}',
            "--critical-relation-hashes-json",
            '{"evidence_items":"1111111111111111111111111111111111111111111111111111111111111111","monitoring_reports":"2222222222222222222222222222222222222222222222222222222222222222","project_memberships":"3333333333333333333333333333333333333333333333333333333333333333","projects":"4444444444444444444444444444444444444444444444444444444444444444"}',
            "--non-b-business-consistency-json",
            _business_consistency("0028_secret_store"),
            "--minio-object-count",
            "0",
            "--minio-bucket-object-counts-json",
            '{"geo-artifacts":0,"geo-restricted-recommendation-artifacts":0,"geo-restricted-workflow-c-artifacts":0,"geo-synthetic-style-derived":0,"geo-synthetic-style-raw":0}',
            "--secret-key-version-count",
            "1",
            "--secret-version-count",
            "0",
            "--representative-probe-target-count",
            "0",
            "--provider-artifact-key-version-count",
            "1",
            "--provider-active-dek-count",
            "0",
            "--provider-recoverable-artifact-count",
            "0",
            "--provider-representative-probe-target-count",
            "0",
            "--synthetic-artifact-key-version-count",
            "1",
            "--synthetic-active-dek-count",
            "0",
            "--synthetic-nondeleted-artifact-count",
            "0",
            "--synthetic-tier-key-artifact-count",
            "0",
            "--synthetic-restricted-probe-target-count",
            "0",
            "--synthetic-tier-probe-target-count",
            "0",
            "--recommendation-artifact-key-version-count",
            "1",
            "--recommendation-artifact-lineage-count",
            "0",
            "--recommendation-representative-probe-target-count",
            "0",
                "--recommendation-source-verification-receipt-hash",
                "5" * 64,
                "--workflow-c-artifact-key-version-count",
                "1",
                "--workflow-c-active-dek-count",
                "0",
                "--workflow-c-recoverable-artifact-count",
                "0",
                "--workflow-c-representative-probe-target-count",
                "0",
                "--workflow-c-source-verification-receipt-hash",
                "6" * 64,
            ],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert created.returncode == 0, created.stderr

    verified = subprocess.run(
        [
            sys.executable,
            str(MANIFEST),
            "verify",
            "--keyring",
            str(keyring),
            "--backup-dir",
            str(backup),
        ],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["backup_id"] == "cli-backup"

    decrypted = subprocess.run(
        [
            sys.executable,
            str(MANIFEST),
            "decrypt",
            "--keyring",
            str(keyring),
            "--backup-dir",
            str(backup),
            "--artifact",
            "postgres",
            "--staging-dir",
            str(restore),
        ],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert decrypted.returncode == 0, decrypted.stderr
    assert decrypted.stdout == postgres
    assert not list(restore.iterdir())


def test_cli_errors_do_not_echo_keyring_content_or_path(tmp_path: Path) -> None:
    canary = "BACKUP-KEYRING-CANARY-MUST-NOT-LEAK-9351"
    keyring = tmp_path / "sensitive-keyring-name.json"
    keyring.write_text(canary, encoding="ascii")
    keyring.chmod(0o600)
    output = tmp_path / "output"
    output.mkdir(mode=0o700)

    completed = subprocess.run(
        [
            sys.executable,
            str(ENVELOPE),
            "encrypt",
            "--keyring",
            str(keyring),
            "--backup-id",
            "failure",
            "--artifact",
            "postgres",
            "--output",
            str(output / "artifact.enc"),
        ],
        cwd=tmp_path,
        input=b"plaintext-canary",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert canary.encode() not in completed.stderr
    assert str(keyring).encode() not in completed.stderr
    assert completed.stdout == b""
    assert not list(output.iterdir())
