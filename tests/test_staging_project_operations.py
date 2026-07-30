from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from scripts.purge_staging_project import (
    assert_confirmation,
    list_project_objects,
    validate_backup_manifest,
)


PROJECT_ID = UUID("94ec48ea-b2f4-449f-9e93-21c391c66ad0")


def _manifest(tmp_path: Path) -> Path:
    archive = tmp_path / "backup.tar.gpg"
    archive.write_bytes(b"encrypted-backup")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "verified",
                "project": {"id": str(PROJECT_ID), "name": "ADVINSYS Australia"},
                "archive": {
                    "path": archive.name,
                    "size_bytes": archive.stat().st_size,
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                },
                "restore_checks": {
                    "postgres_project_verified": True,
                    "secret_decrypt_canary_count": 1,
                    "minio_project_file_count": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_backup_manifest_must_bind_all_three_restore_proofs(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    payload = validate_backup_manifest(
        manifest, project_id=PROJECT_ID, project_name="ADVINSYS Australia"
    )
    assert payload["status"] == "verified"

    payload["restore_checks"]["secret_decrypt_canary_count"] = 0
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="database, object, and key restore checks"):
        validate_backup_manifest(
            manifest, project_id=PROJECT_ID, project_name="ADVINSYS Australia"
        )


def test_removal_confirmation_requires_exact_id_and_name() -> None:
    assert_confirmation(
        project_id=PROJECT_ID,
        project_name="ADVINSYS Australia",
        confirm_project_id=str(PROJECT_ID),
        confirm_name="ADVINSYS Australia",
    )
    with pytest.raises(RuntimeError, match="does not exactly match"):
        assert_confirmation(
            project_id=PROJECT_ID,
            project_name="ADVINSYS Australia",
            confirm_project_id=str(PROJECT_ID),
            confirm_name="ADVINSYS",
        )


def test_project_object_selection_requires_an_exact_path_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = type(
        "Completed",
        (),
        {
            "stdout": "\n".join(
                json.dumps({"type": "file", "key": key})
                for key in (
                    f"bucket/model/{PROJECT_ID}/payload.bin",
                    f"bucket/model/prefix-{PROJECT_ID}/not-owned.bin",
                    "bucket/model/another-project/payload.bin",
                )
            )
        },
    )()
    monkeypatch.setattr("scripts.purge_staging_project.subprocess.run", lambda *args, **kwargs: completed)

    assert list_project_objects("minio", PROJECT_ID) == [
        f"bucket/model/{PROJECT_ID}/payload.bin"
    ]


def test_purge_uses_transaction_local_trigger_bypass_and_checks_every_foreign_key() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts/purge_staging_project.py").read_text(
        encoding="utf-8"
    )
    assert "SET LOCAL session_replication_role = 'replica'" in source
    assert "SET LOCAL session_replication_role = 'origin'" in source
    assert "check_postgres_fk_integrity.sql" in source


def test_project_backup_restricts_the_encrypted_archive() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "scripts/staging_project_backup.py"
    ).read_text(encoding="utf-8")

    assert "os.chmod(archive, 0o600)" in source
