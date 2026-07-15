"""Checksum verification for Alembic revisions backed by external SQL files."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory


LEDGER_TABLE = "alembic_sql_checksum_ledger"


class MigrationChecksumError(RuntimeError):
    """An applied revision's SQL no longer matches its recorded content."""


def sql_hashes(sql_directory: Path, revision: str) -> tuple[str, str]:
    upgrade = sql_directory / f"{revision}.sql"
    downgrade = sql_directory / f"{revision}.down.sql"
    try:
        return _sha256(upgrade), _sha256(downgrade)
    except OSError as error:
        raise MigrationChecksumError(
            f"missing external SQL for Alembic revision {revision}"
        ) from error


def applied_revisions(connection: Any, script: ScriptDirectory) -> frozenset[str]:
    if not _table_exists(connection, "alembic_version"):
        return frozenset()
    heads = tuple(
        str(row[0])
        for row in connection.exec_driver_sql("SELECT version_num FROM alembic_version")
    )
    applied: set[str] = set()
    pending = list(heads)
    while pending:
        revision_id = pending.pop()
        if revision_id in applied:
            continue
        revision = script.get_revision(revision_id)
        if revision is None:
            raise MigrationChecksumError(f"database references unknown revision {revision_id}")
        applied.add(revision_id)
        down_revisions = revision._normalized_down_revisions
        pending.extend(value for value in down_revisions if value)
    return frozenset(applied)


def ensure_ledger(connection: Any) -> None:
    connection.exec_driver_sql(
        f"""
        CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} (
            revision text PRIMARY KEY CHECK (btrim(revision) <> ''),
            upgrade_sha256 text NOT NULL CHECK (upgrade_sha256 ~ '^[0-9a-f]{{64}}$'),
            downgrade_sha256 text NOT NULL CHECK (downgrade_sha256 ~ '^[0-9a-f]{{64}}$'),
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
        """
    )
    _lock_down_ledger(connection)


def verify_applied(
    connection: Any,
    *,
    script: ScriptDirectory,
    sql_directory: Path,
) -> frozenset[str]:
    applied = applied_revisions(connection, script)
    rows = {
        str(row[0]): (str(row[1]), str(row[2]))
        for row in connection.exec_driver_sql(
            f"SELECT revision, upgrade_sha256, downgrade_sha256 FROM {LEDGER_TABLE}"
        )
    }
    missing = applied - rows.keys()
    if missing:
        raise MigrationChecksumError(
            "checksum ledger is missing applied revisions: " + ", ".join(sorted(missing))
        )
    unknown = rows.keys() - applied
    if unknown:
        raise MigrationChecksumError(
            "checksum ledger contains revisions not applied by Alembic: "
            + ", ".join(sorted(unknown))
        )
    for revision in sorted(applied):
        expected = sql_hashes(sql_directory, revision)
        if rows[revision] != expected:
            raise MigrationChecksumError(
                f"applied Alembic SQL checksum drift detected for {revision}"
            )
    return applied


def synchronize_ledger(
    connection: Any,
    *,
    script: ScriptDirectory,
    sql_directory: Path,
) -> None:
    applied = applied_revisions(connection, script)
    rows = {
        str(row[0])
        for row in connection.exec_driver_sql(f"SELECT revision FROM {LEDGER_TABLE}")
    }
    removed = rows - applied
    for revision in sorted(removed):
        connection.exec_driver_sql(
            f"DELETE FROM {LEDGER_TABLE} WHERE revision = %s", (revision,)
        )
    for revision in sorted(applied - rows):
        upgrade_hash, downgrade_hash = sql_hashes(sql_directory, revision)
        connection.exec_driver_sql(
            f"""INSERT INTO {LEDGER_TABLE}
                  (revision, upgrade_sha256, downgrade_sha256)
                VALUES (%s, %s, %s)""",
            (revision, upgrade_hash, downgrade_hash),
        )
    _lock_down_ledger(connection)


def _table_exists(connection: Any, table_name: str) -> bool:
    row = connection.exec_driver_sql(
        "SELECT to_regclass(%s) IS NOT NULL", (f"public.{table_name}",)
    ).first()
    return bool(row and row[0])


def _lock_down_ledger(connection: Any) -> None:
    runtime_roles = ("geo_app", "geo_worker", "geo_readonly")
    existing = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT rolname FROM pg_roles WHERE rolname IN ('geo_app','geo_worker','geo_readonly')"
        )
    }
    if existing == set(runtime_roles):
        connection.exec_driver_sql(
            f"REVOKE ALL ON public.{LEDGER_TABLE} "
            "FROM PUBLIC, geo_app, geo_worker, geo_readonly"
        )
    else:
        connection.exec_driver_sql(f"REVOKE ALL ON public.{LEDGER_TABLE} FROM PUBLIC")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
