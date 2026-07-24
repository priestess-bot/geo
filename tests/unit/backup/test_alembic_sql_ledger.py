from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.alembic_sql_ledger import (
    build_ledger,
    validate_ledger,
    verify_repository_ledger,
)
from scripts.backup_envelope import BackupSecurityError


def test_ledger_covers_every_upgrade_and_downgrade_through_database_head(
    tmp_path: Path,
) -> None:
    sql = _sql_directory(tmp_path, count=3)

    ledger = build_ledger(sql, head_revision="0002_change_2")

    assert ledger["head_revision"] == "0002_change_2"
    assert [entry["revision"] for entry in ledger["entries"]] == [
        "0001_change_1",
        "0002_change_2",
    ]
    assert ledger["entries"][0]["upgrade_sha256"] == hashlib.sha256(
        b"upgrade 1\n"
    ).hexdigest()
    assert validate_ledger(ledger) == ledger
    assert verify_repository_ledger(sql, expected_ledger=ledger) == ledger


def test_ledger_rejects_missing_pair_duplicate_sequence_and_head_mismatch(
    tmp_path: Path,
) -> None:
    sql = _sql_directory(tmp_path / "missing", count=2)
    (sql / "0002_change_2.down.sql").unlink()
    with pytest.raises(BackupSecurityError):
        build_ledger(sql, head_revision="0002_change_2")

    sql = _sql_directory(tmp_path / "duplicate", count=2)
    (sql / "0002_duplicate.sql").write_text("duplicate\n", encoding="ascii")
    with pytest.raises(BackupSecurityError):
        build_ledger(sql, head_revision="0002_change_2")

    sql = _sql_directory(tmp_path / "head", count=2)
    with pytest.raises(BackupSecurityError):
        build_ledger(sql, head_revision="0002_different_name")


def test_ledger_rejects_content_drift_tampered_digest_and_symlink(tmp_path: Path) -> None:
    sql = _sql_directory(tmp_path / "drift", count=2)
    ledger = build_ledger(sql, head_revision="0002_change_2")
    (sql / "0001_change_1.sql").write_text("changed\n", encoding="ascii")
    with pytest.raises(BackupSecurityError):
        verify_repository_ledger(sql, expected_ledger=ledger)

    tampered = {**ledger, "ledger_sha256": "0" * 64}
    with pytest.raises(BackupSecurityError):
        validate_ledger(tampered)

    sql = _sql_directory(tmp_path / "symlink", count=1)
    target = sql / "target.sql"
    target.write_text("upgrade\n", encoding="ascii")
    (sql / "0001_change_1.sql").unlink()
    (sql / "0001_change_1.sql").symlink_to(target)
    with pytest.raises(BackupSecurityError):
        build_ledger(sql, head_revision="0001_change_1")


def _sql_directory(root: Path, *, count: int) -> Path:
    sql = root / "sql"
    sql.mkdir(parents=True)
    for sequence in range(1, count + 1):
        revision = f"{sequence:04d}_change_{sequence}"
        (sql / f"{revision}.sql").write_text(
            f"upgrade {sequence}\n", encoding="ascii"
        )
        (sql / f"{revision}.down.sql").write_text(
            f"downgrade {sequence}\n", encoding="ascii"
        )
    return sql
