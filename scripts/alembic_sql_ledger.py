"""Build and verify a deterministic checksum ledger for applied Alembic SQL files."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backup_envelope import BackupSecurityError, canonical_json  # noqa: E402


LEDGER_SCHEMA = "geo-alembic-sql-checksum-ledger-v1"
_REVISION = re.compile(r"^(?P<sequence>[0-9]{4})_[A-Za-z0-9_.-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_SQL_BYTES = 16 * 1024 * 1024


def build_ledger(sql_directory: Path, *, head_revision: str) -> dict[str, object]:
    """Return checksums for every migration SQL pair through ``head_revision``."""

    head_match = _REVISION.fullmatch(head_revision)
    if head_match is None:
        raise BackupSecurityError("Alembic SQL ledger head revision is invalid")
    head_sequence = int(head_match.group("sequence"))
    try:
        directory_metadata = sql_directory.lstat()
    except OSError:
        raise BackupSecurityError("Alembic SQL directory is unavailable") from None
    if not stat.S_ISDIR(directory_metadata.st_mode):
        raise BackupSecurityError("Alembic SQL directory is invalid")

    upgrades: dict[int, Path] = {}
    downgrades: dict[int, Path] = {}
    try:
        candidates = tuple(sql_directory.iterdir())
    except OSError:
        raise BackupSecurityError("Alembic SQL directory cannot be enumerated") from None
    for candidate in candidates:
        name = candidate.name
        is_downgrade = name.endswith(".down.sql")
        if is_downgrade:
            revision = name.removesuffix(".down.sql")
        elif name.endswith(".sql"):
            revision = name.removesuffix(".sql")
        else:
            continue
        match = _REVISION.fullmatch(revision)
        if match is None:
            raise BackupSecurityError("Alembic SQL filename is invalid")
        sequence = int(match.group("sequence"))
        if sequence > head_sequence:
            continue
        destination = downgrades if is_downgrade else upgrades
        if sequence in destination:
            raise BackupSecurityError("Alembic SQL sequence is duplicated")
        destination[sequence] = candidate

    expected_sequences = set(range(1, head_sequence + 1))
    if set(upgrades) != expected_sequences or set(downgrades) != expected_sequences:
        raise BackupSecurityError("Alembic SQL ledger is incomplete")
    if upgrades[head_sequence].stem != head_revision:
        raise BackupSecurityError("Alembic SQL ledger head does not match the database")

    entries: list[dict[str, object]] = []
    for sequence in sorted(expected_sequences):
        upgrade = upgrades[sequence]
        downgrade = downgrades[sequence]
        revision = upgrade.name.removesuffix(".sql")
        if downgrade.name.removesuffix(".down.sql") != revision:
            raise BackupSecurityError("Alembic SQL upgrade and downgrade names do not match")
        entries.append(
            {
                "downgrade_path": f"infra/db/alembic/sql/{downgrade.name}",
                "downgrade_sha256": _regular_file_sha256(downgrade),
                "revision": revision,
                "sequence": sequence,
                "upgrade_path": f"infra/db/alembic/sql/{upgrade.name}",
                "upgrade_sha256": _regular_file_sha256(upgrade),
            }
        )

    payload = {"entries": entries, "head_revision": head_revision}
    return {
        **payload,
        "ledger_sha256": hashlib.sha256(canonical_json(payload)).hexdigest(),
        "schema_version": LEDGER_SCHEMA,
    }


def validate_ledger(value: object) -> dict[str, object]:
    """Validate an untrusted ledger and return its canonical representation."""

    if not isinstance(value, Mapping) or set(value) != {
        "entries",
        "head_revision",
        "ledger_sha256",
        "schema_version",
    }:
        raise BackupSecurityError("Alembic SQL checksum ledger is invalid")
    if value["schema_version"] != LEDGER_SCHEMA:
        raise BackupSecurityError("Alembic SQL checksum ledger is unsupported")
    head_revision = value["head_revision"]
    head_match = _REVISION.fullmatch(head_revision) if isinstance(head_revision, str) else None
    entries = value["entries"]
    if head_match is None or not isinstance(entries, list):
        raise BackupSecurityError("Alembic SQL checksum ledger is invalid")
    head_sequence = int(head_match.group("sequence"))
    if len(entries) != head_sequence or head_sequence < 1:
        raise BackupSecurityError("Alembic SQL checksum ledger is incomplete")

    normalized_entries: list[dict[str, object]] = []
    for expected_sequence, entry in enumerate(entries, start=1):
        normalized_entries.append(_validate_entry(entry, expected_sequence))
    if normalized_entries[-1]["revision"] != head_revision:
        raise BackupSecurityError("Alembic SQL checksum ledger head is invalid")
    payload = {"entries": normalized_entries, "head_revision": head_revision}
    expected_digest = hashlib.sha256(canonical_json(payload)).hexdigest()
    supplied_digest = value["ledger_sha256"]
    if (
        not isinstance(supplied_digest, str)
        or _SHA256.fullmatch(supplied_digest) is None
        or supplied_digest != expected_digest
    ):
        raise BackupSecurityError("Alembic SQL checksum ledger digest is invalid")
    return {
        **payload,
        "ledger_sha256": expected_digest,
        "schema_version": LEDGER_SCHEMA,
    }


def verify_repository_ledger(
    sql_directory: Path, *, expected_ledger: object
) -> dict[str, object]:
    expected = validate_ledger(expected_ledger)
    actual = build_ledger(
        sql_directory,
        head_revision=str(expected["head_revision"]),
    )
    if actual != expected:
        raise BackupSecurityError("repository Alembic SQL does not match the backup ledger")
    return actual


def _validate_entry(value: object, expected_sequence: int) -> dict[str, object]:
    fields = {
        "downgrade_path",
        "downgrade_sha256",
        "revision",
        "sequence",
        "upgrade_path",
        "upgrade_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise BackupSecurityError("Alembic SQL checksum ledger entry is invalid")
    revision = value["revision"]
    match = _REVISION.fullmatch(revision) if isinstance(revision, str) else None
    if match is None or int(match.group("sequence")) != expected_sequence:
        raise BackupSecurityError("Alembic SQL checksum ledger sequence is invalid")
    expected_upgrade = f"infra/db/alembic/sql/{revision}.sql"
    expected_downgrade = f"infra/db/alembic/sql/{revision}.down.sql"
    if (
        value["sequence"] != expected_sequence
        or value["upgrade_path"] != expected_upgrade
        or value["downgrade_path"] != expected_downgrade
    ):
        raise BackupSecurityError("Alembic SQL checksum ledger path is invalid")
    for field in ("upgrade_sha256", "downgrade_sha256"):
        digest = value[field]
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise BackupSecurityError("Alembic SQL checksum ledger checksum is invalid")
    return {field: value[field] for field in sorted(fields)}


def _regular_file_sha256(path: Path) -> str:
    try:
        metadata = path.lstat()
    except OSError:
        raise BackupSecurityError("Alembic SQL file is unavailable") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size < 1
        or metadata.st_size > _MAX_SQL_BYTES
    ):
        raise BackupSecurityError("Alembic SQL file is invalid")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            opened_metadata = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(opened_metadata.st_mode)
                or (opened_metadata.st_dev, opened_metadata.st_ino)
                != (metadata.st_dev, metadata.st_ino)
                or opened_metadata.st_size != metadata.st_size
            ):
                raise BackupSecurityError("Alembic SQL file changed while being read")
            digest = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        raise BackupSecurityError("Alembic SQL file cannot be read") from None
    return digest.hexdigest()


def _load_json(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        raise BackupSecurityError("Alembic SQL checksum ledger JSON is invalid") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or verify an Alembic SQL ledger.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--sql-dir", type=Path, required=True)
    create.add_argument("--head-revision", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--sql-dir", type=Path, required=True)
    verify.add_argument("--ledger-json", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            ledger = build_ledger(args.sql_dir, head_revision=args.head_revision)
        else:
            ledger = verify_repository_ledger(
                args.sql_dir,
                expected_ledger=_load_json(args.ledger_json),
            )
        print(canonical_json(ledger).decode("ascii"))
        return 0
    except (BackupSecurityError, OSError):
        print("Alembic SQL ledger verification failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
