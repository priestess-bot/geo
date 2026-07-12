from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence


EXPECTED_SCHEMA_GENERATION = 2
EXPECTED_DATABASE_NAME = "geno_v2"
MANIFEST_VERSION = 1
ADVISORY_LOCK_NAME = "geno:schema-v2:install"
ADVISORY_LOCK_POLL_INTERVAL_SECONDS = 0.1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\.(?P<patch>0|[1-9][0-9]*)(?:[-+].*)?$")
REQUIRED_PG_ENVIRONMENT = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")


class SchemaV2Error(RuntimeError):
    """Raised when the Schema v2 compatibility contract is not satisfied."""


@dataclass(frozen=True)
class ManifestFile:
    path: str
    sha256: str


@dataclass(frozen=True)
class SchemaManifest:
    schema_generation: int
    database_name: str
    baseline_version: str
    baseline_hash: str
    minimum_app_version: str
    baseline_files: tuple[ManifestFile, ...]
    migration_files: tuple[ManifestFile, ...]

    @property
    def all_files(self) -> tuple[ManifestFile, ...]:
        return self.baseline_files + self.migration_files


def _require_nonempty_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaV2Error(f"manifest field {key!r} must be a non-empty string")
    return value


def _parse_files(raw: object, *, prefix: str, field: str) -> tuple[ManifestFile, ...]:
    if not isinstance(raw, list):
        raise SchemaV2Error(f"manifest field {field!r} must be a list")

    parsed: list[ManifestFile] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise SchemaV2Error(f"{field}[{index}] must contain only path and sha256")
        path = item.get("path")
        checksum = item.get("sha256")
        if not isinstance(path, str) or not isinstance(checksum, str):
            raise SchemaV2Error(f"{field}[{index}] path and sha256 must be strings")
        pure_path = PurePosixPath(path)
        if (
            pure_path.is_absolute()
            or ".." in pure_path.parts
            or len(pure_path.parts) != 2
            or pure_path.parts[0] != prefix
            or pure_path.suffix != ".sql"
        ):
            raise SchemaV2Error(f"unsafe or invalid Schema v2 path: {path!r}")
        if not SHA256_RE.fullmatch(checksum):
            raise SchemaV2Error(f"invalid SHA-256 for {path!r}")
        parsed.append(ManifestFile(path=path, sha256=checksum))

    paths = [item.path for item in parsed]
    if paths != sorted(paths):
        raise SchemaV2Error(f"manifest field {field!r} must be ordered by path")
    if len(paths) != len(set(paths)):
        raise SchemaV2Error(f"manifest field {field!r} contains duplicate paths")
    return tuple(parsed)


def compute_baseline_hash(files: Iterable[ManifestFile]) -> str:
    digest = hashlib.sha256()
    for item in files:
        digest.update(item.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(schema_root: Path) -> SchemaManifest:
    schema_root = schema_root.resolve()
    manifest_path = schema_root / "manifest.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaV2Error(f"cannot read Schema v2 manifest: {exc}") from exc
    if not isinstance(raw, dict):
        raise SchemaV2Error("Schema v2 manifest must be a JSON object")
    if raw.get("manifest_version") != MANIFEST_VERSION:
        raise SchemaV2Error(f"unsupported manifest_version: {raw.get('manifest_version')!r}")
    if raw.get("schema_generation") != EXPECTED_SCHEMA_GENERATION:
        raise SchemaV2Error(f"schema_generation must be {EXPECTED_SCHEMA_GENERATION}")

    baseline_files = _parse_files(
        raw.get("baseline_files"), prefix="baseline", field="baseline_files"
    )
    if not baseline_files:
        raise SchemaV2Error("baseline_files must contain the metadata bootstrap SQL")
    migration_files = _parse_files(
        raw.get("migration_files"), prefix="migrations", field="migration_files"
    )
    if set(item.path for item in baseline_files) & set(item.path for item in migration_files):
        raise SchemaV2Error("baseline and migration paths must be disjoint")

    manifest = SchemaManifest(
        schema_generation=EXPECTED_SCHEMA_GENERATION,
        database_name=_require_nonempty_string(raw, "database_name"),
        baseline_version=_require_nonempty_string(raw, "baseline_version"),
        baseline_hash=_require_nonempty_string(raw, "baseline_hash"),
        minimum_app_version=_require_nonempty_string(raw, "minimum_app_version"),
        baseline_files=baseline_files,
        migration_files=migration_files,
    )
    if manifest.database_name != EXPECTED_DATABASE_NAME:
        raise SchemaV2Error(
            f"database_name must remain fixed at {EXPECTED_DATABASE_NAME!r}"
        )
    if not SHA256_RE.fullmatch(manifest.baseline_hash):
        raise SchemaV2Error("baseline_hash must be a lowercase SHA-256 digest")
    calculated_baseline_hash = compute_baseline_hash(manifest.baseline_files)
    if calculated_baseline_hash != manifest.baseline_hash:
        raise SchemaV2Error(
            "baseline_hash mismatch: "
            f"expected {manifest.baseline_hash}, calculated {calculated_baseline_hash}"
        )

    for item in manifest.all_files:
        path = (schema_root / item.path).resolve()
        try:
            path.relative_to(schema_root)
        except ValueError as exc:
            raise SchemaV2Error(f"manifest path escapes schema root: {item.path!r}") from exc
        if not path.is_file():
            raise SchemaV2Error(f"manifest file does not exist: {item.path}")
        actual_checksum = _file_sha256(path)
        if actual_checksum != item.sha256:
            raise SchemaV2Error(
                f"checksum drift for {item.path}: expected {item.sha256}, got {actual_checksum}"
            )
    return manifest


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value)
    if match is None:
        raise SchemaV2Error(f"application version is not SemVer-compatible: {value!r}")
    return tuple(int(match.group(name)) for name in ("major", "minor", "patch"))


def ensure_app_compatible(*, app_version: str, minimum_app_version: str) -> None:
    if _version_tuple(app_version) < _version_tuple(minimum_app_version):
        raise SchemaV2Error(
            f"application {app_version} is older than required {minimum_app_version}"
        )


def _nonnegative_finite_seconds(raw_value: str) -> float:
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a finite non-negative number") from exc
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("must be a finite non-negative number")
    return value


def _validate_pg_environment(environment: dict[str, str]) -> None:
    missing = [name for name in REQUIRED_PG_ENVIRONMENT if not environment.get(name, "").strip()]
    if missing:
        raise SchemaV2Error(
            "missing required PostgreSQL connection settings: " + ", ".join(missing)
        )
    if environment["PGDATABASE"] != EXPECTED_DATABASE_NAME:
        raise SchemaV2Error("PGDATABASE must remain fixed at 'geno_v2'")
    try:
        port = int(environment["PGPORT"])
    except ValueError as exc:
        raise SchemaV2Error("PGPORT must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise SchemaV2Error("PGPORT must be an integer between 1 and 65535")


def _metadata_tables_exist(cursor: Any) -> tuple[bool, bool]:
    cursor.execute(
        "SELECT to_regclass('public.app_schema_metadata') IS NOT NULL, "
        "to_regclass('public.schema_migration_ledger') IS NOT NULL"
    )
    row = cursor.fetchone()
    return bool(row[0]), bool(row[1])


def _verify_database_identity(cursor: Any, *, expected_database_name: str) -> None:
    cursor.execute("SELECT current_database()")
    actual_database_name = str(cursor.fetchone()[0])
    if actual_database_name != expected_database_name:
        raise SchemaV2Error(
            "refusing Schema v2 operation on database "
            f"{actual_database_name!r}; expected {expected_database_name!r}"
        )


def _unexpected_public_objects(cursor: Any) -> list[str]:
    cursor.execute(
        """
        WITH unexpected_relations AS (
            SELECT
                CASE relation.relkind
                    WHEN 'r' THEN 'table'
                    WHEN 'p' THEN 'partitioned_table'
                    WHEN 'v' THEN 'view'
                    WHEN 'm' THEN 'materialized_view'
                    WHEN 'S' THEN 'sequence'
                    WHEN 'f' THEN 'foreign_table'
                    WHEN 'c' THEN 'composite_type'
                    WHEN 'i' THEN 'index'
                    WHEN 'I' THEN 'partitioned_index'
                    ELSE 'relation'
                END AS object_kind,
                format('%I.%I', namespace.nspname, relation.relname) AS object_identity
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f', 'c', 'i', 'I')
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_depend AS dependency
                  WHERE dependency.classid = 'pg_catalog.pg_class'::regclass
                    AND dependency.objid = relation.oid
                    AND dependency.refclassid = 'pg_catalog.pg_extension'::regclass
                    AND dependency.deptype = 'e'
              )
        ),
        unexpected_routines AS (
            SELECT
                CASE routine.prokind
                    WHEN 'p' THEN 'procedure'
                    WHEN 'a' THEN 'aggregate'
                    WHEN 'w' THEN 'window_function'
                    ELSE 'function'
                END AS object_kind,
                routine.oid::regprocedure::text AS object_identity
            FROM pg_catalog.pg_proc AS routine
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = routine.pronamespace
            WHERE namespace.nspname = 'public'
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_depend AS dependency
                  WHERE dependency.classid = 'pg_catalog.pg_proc'::regclass
                    AND dependency.objid = routine.oid
                    AND dependency.refclassid = 'pg_catalog.pg_extension'::regclass
                    AND dependency.deptype = 'e'
              )
        ),
        unexpected_types AS (
            SELECT
                CASE type_entry.typtype
                    WHEN 'e' THEN 'enum_type'
                    WHEN 'd' THEN 'domain_type'
                    WHEN 'r' THEN 'range_type'
                    WHEN 'm' THEN 'multirange_type'
                    ELSE 'base_type'
                END AS object_kind,
                format('%I.%I', namespace.nspname, type_entry.typname) AS object_identity
            FROM pg_catalog.pg_type AS type_entry
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = type_entry.typnamespace
            WHERE namespace.nspname = 'public'
              AND type_entry.typrelid = 0
              AND (
                  type_entry.typtype IN ('e', 'd', 'r', 'm')
                  OR (
                      type_entry.typtype = 'b'
                      AND type_entry.typelem = 0
                  )
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_depend AS dependency
                  WHERE dependency.classid = 'pg_catalog.pg_type'::regclass
                    AND dependency.objid = type_entry.oid
                    AND dependency.refclassid = 'pg_catalog.pg_extension'::regclass
                    AND dependency.deptype = 'e'
              )
        ),
        unexpected_collations AS (
            SELECT
                'collation'::text AS object_kind,
                format('%I.%I', namespace.nspname, coll.collname) AS object_identity
            FROM pg_catalog.pg_collation AS coll
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = coll.collnamespace
            WHERE namespace.nspname = 'public'
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_depend AS dependency
                  WHERE dependency.classid = 'pg_catalog.pg_collation'::regclass
                    AND dependency.objid = coll.oid
                    AND dependency.refclassid = 'pg_catalog.pg_extension'::regclass
                    AND dependency.deptype = 'e'
              )
        ),
        unexpected_operators AS (
            SELECT
                'operator'::text AS object_kind,
                format('%I.%I', namespace.nspname, op.oprname) AS object_identity
            FROM pg_catalog.pg_operator AS op
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = op.oprnamespace
            WHERE namespace.nspname = 'public'
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_depend AS dependency
                  WHERE dependency.classid = 'pg_catalog.pg_operator'::regclass
                    AND dependency.objid = op.oid
                    AND dependency.refclassid = 'pg_catalog.pg_extension'::regclass
                    AND dependency.deptype = 'e'
              )
        ),
        unexpected_text_search_configurations AS (
            SELECT
                'text_search_configuration'::text AS object_kind,
                format('%I.%I', namespace.nspname, ts_configuration.cfgname) AS object_identity
            FROM pg_catalog.pg_ts_config AS ts_configuration
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = ts_configuration.cfgnamespace
            WHERE namespace.nspname = 'public'
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_depend AS dependency
                  WHERE dependency.classid = 'pg_catalog.pg_ts_config'::regclass
                    AND dependency.objid = ts_configuration.oid
                    AND dependency.refclassid = 'pg_catalog.pg_extension'::regclass
                    AND dependency.deptype = 'e'
              )
        ),
        unexpected_text_search_dictionaries AS (
            SELECT
                'text_search_dictionary'::text AS object_kind,
                format('%I.%I', namespace.nspname, ts_dictionary.dictname) AS object_identity
            FROM pg_catalog.pg_ts_dict AS ts_dictionary
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = ts_dictionary.dictnamespace
            WHERE namespace.nspname = 'public'
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_depend AS dependency
                  WHERE dependency.classid = 'pg_catalog.pg_ts_dict'::regclass
                    AND dependency.objid = ts_dictionary.oid
                    AND dependency.refclassid = 'pg_catalog.pg_extension'::regclass
                    AND dependency.deptype = 'e'
              )
        ),
        unexpected_text_search_parsers AS (
            SELECT
                'text_search_parser'::text AS object_kind,
                format('%I.%I', namespace.nspname, ts_parser_entry.prsname) AS object_identity
            FROM pg_catalog.pg_ts_parser AS ts_parser_entry
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = ts_parser_entry.prsnamespace
            WHERE namespace.nspname = 'public'
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_depend AS dependency
                  WHERE dependency.classid = 'pg_catalog.pg_ts_parser'::regclass
                    AND dependency.objid = ts_parser_entry.oid
                    AND dependency.refclassid = 'pg_catalog.pg_extension'::regclass
                    AND dependency.deptype = 'e'
              )
        ),
        unexpected_text_search_templates AS (
            SELECT
                'text_search_template'::text AS object_kind,
                format('%I.%I', namespace.nspname, ts_template_entry.tmplname) AS object_identity
            FROM pg_catalog.pg_ts_template AS ts_template_entry
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = ts_template_entry.tmplnamespace
            WHERE namespace.nspname = 'public'
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_depend AS dependency
                  WHERE dependency.classid = 'pg_catalog.pg_ts_template'::regclass
                    AND dependency.objid = ts_template_entry.oid
                    AND dependency.refclassid = 'pg_catalog.pg_extension'::regclass
                    AND dependency.deptype = 'e'
              )
        ),
        unexpected_extensions AS (
            SELECT
                'extension'::text AS object_kind,
                ext.extname::text AS object_identity
            FROM pg_catalog.pg_extension AS ext
            WHERE ext.extname NOT IN ('plpgsql', 'pgcrypto', 'vector')
        )
        SELECT object_kind, object_identity FROM unexpected_relations
        UNION ALL
        SELECT object_kind, object_identity FROM unexpected_routines
        UNION ALL
        SELECT object_kind, object_identity FROM unexpected_types
        UNION ALL
        SELECT object_kind, object_identity FROM unexpected_collations
        UNION ALL
        SELECT object_kind, object_identity FROM unexpected_operators
        UNION ALL
        SELECT object_kind, object_identity FROM unexpected_text_search_configurations
        UNION ALL
        SELECT object_kind, object_identity FROM unexpected_text_search_dictionaries
        UNION ALL
        SELECT object_kind, object_identity FROM unexpected_text_search_parsers
        UNION ALL
        SELECT object_kind, object_identity FROM unexpected_text_search_templates
        UNION ALL
        SELECT object_kind, object_identity FROM unexpected_extensions
        ORDER BY object_kind, object_identity
        """
    )
    return [f"{row[0]}:{row[1]}" for row in cursor.fetchall()]


def _assert_clean_public_schema(cursor: Any) -> None:
    unexpected_objects = _unexpected_public_objects(cursor)
    if unexpected_objects:
        raise SchemaV2Error(
            "refusing to initialize Schema v2 with unexpected public objects: "
            f"{unexpected_objects}"
        )


def _acquire_advisory_lock(
    cursor: Any,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float = ADVISORY_LOCK_POLL_INTERVAL_SECONDS,
    monotonic: Any = time.monotonic,
    sleep: Any = time.sleep,
) -> None:
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise SchemaV2Error("advisory lock timeout must be finite and non-negative")
    if not math.isfinite(poll_interval_seconds) or poll_interval_seconds <= 0:
        raise SchemaV2Error("advisory lock poll interval must be finite and positive")

    deadline = monotonic() + timeout_seconds
    while True:
        cursor.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
            (ADVISORY_LOCK_NAME,),
        )
        row = cursor.fetchone()
        if row is not None and bool(row[0]):
            return

        remaining_seconds = deadline - monotonic()
        if remaining_seconds <= 0:
            raise SchemaV2Error(
                "timed out acquiring Schema v2 advisory lock "
                f"after {timeout_seconds:.3f} seconds"
            )
        sleep(min(poll_interval_seconds, remaining_seconds))


def _read_sql(schema_root: Path, item: ManifestFile) -> str:
    return (schema_root / item.path).read_text(encoding="utf-8")


def _record_file(cursor: Any, item: ManifestFile, *, app_commit: str) -> None:
    cursor.execute(
        "INSERT INTO schema_migration_ledger (migration_id, checksum, app_commit) "
        "VALUES (%s, %s, %s)",
        (item.path, item.sha256, app_commit),
    )


def _verify_metadata(cursor: Any, manifest: SchemaManifest) -> None:
    cursor.execute(
        "SELECT schema_generation, baseline_version, baseline_hash, minimum_app_version "
        "FROM app_schema_metadata"
    )
    rows = cursor.fetchall()
    expected = (
        manifest.schema_generation,
        manifest.baseline_version,
        manifest.baseline_hash,
        manifest.minimum_app_version,
    )
    if rows != [expected]:
        raise SchemaV2Error(
            "database metadata does not match the checked-in Schema v2 manifest"
        )


def _ledger_entries(cursor: Any) -> dict[str, str]:
    cursor.execute("SELECT migration_id, checksum FROM schema_migration_ledger")
    return {str(migration_id): str(checksum) for migration_id, checksum in cursor.fetchall()}


def _verify_ledger(
    cursor: Any,
    manifest: SchemaManifest,
    *, require_all_migrations: bool,
) -> dict[str, str]:
    ledger = _ledger_entries(cursor)
    expected_baseline = {item.path: item.sha256 for item in manifest.baseline_files}
    recorded_baseline = {
        migration_id: checksum
        for migration_id, checksum in ledger.items()
        if migration_id.startswith("baseline/")
    }
    if recorded_baseline != expected_baseline:
        raise SchemaV2Error("database baseline ledger does not match the manifest")

    expected_all = {item.path: item.sha256 for item in manifest.all_files}
    for migration_id, checksum in ledger.items():
        expected_checksum = expected_all.get(migration_id)
        if expected_checksum is None:
            raise SchemaV2Error(f"database contains unrecognized migration: {migration_id}")
        if checksum != expected_checksum:
            raise SchemaV2Error(f"database checksum drift for migration: {migration_id}")
    if require_all_migrations and ledger != expected_all:
        missing = sorted(set(expected_all) - set(ledger))
        raise SchemaV2Error(f"database is missing Schema v2 migrations: {missing}")
    return ledger


def _install_with_cursor(
    cursor: Any,
    *,
    schema_root: Path,
    manifest: SchemaManifest,
    app_commit: str,
) -> None:
    metadata_exists, ledger_exists = _metadata_tables_exist(cursor)
    if metadata_exists != ledger_exists:
        raise SchemaV2Error("Schema v2 metadata tables are only partially installed")

    if not metadata_exists:
        _assert_clean_public_schema(cursor)
        for item in manifest.baseline_files:
            cursor.execute(_read_sql(schema_root, item))
            _record_file(cursor, item, app_commit=app_commit)
        cursor.execute(
            "INSERT INTO app_schema_metadata "
            "(schema_generation, baseline_version, baseline_hash, minimum_app_version) "
            "VALUES (%s, %s, %s, %s)",
            (
                manifest.schema_generation,
                manifest.baseline_version,
                manifest.baseline_hash,
                manifest.minimum_app_version,
            ),
        )
    else:
        _verify_metadata(cursor, manifest)

    ledger = _verify_ledger(cursor, manifest, require_all_migrations=False)
    for item in manifest.migration_files:
        if item.path in ledger:
            continue
        cursor.execute(_read_sql(schema_root, item))
        _record_file(cursor, item, app_commit=app_commit)
        ledger[item.path] = item.sha256
    _verify_ledger(cursor, manifest, require_all_migrations=True)


def _verify_with_cursor(cursor: Any, manifest: SchemaManifest) -> None:
    metadata_exists, ledger_exists = _metadata_tables_exist(cursor)
    if not metadata_exists or not ledger_exists:
        raise SchemaV2Error("Schema v2 metadata tables are not installed")
    _verify_metadata(cursor, manifest)
    _verify_ledger(cursor, manifest, require_all_migrations=True)


def _connect_with_retry(*, timeout_seconds: float, driver: Any) -> Any:
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise SchemaV2Error("database connect timeout must be finite and non-negative")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            # libpq reads PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD directly.
            # No raw credential is assembled into a URI or command-line value.
            return driver.connect()
        except driver.OperationalError:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise
            time.sleep(min(0.5, remaining_seconds))


def run_database_command(
    command: str,
    *,
    schema_root: Path,
    app_version: str,
    app_commit: str,
    connect_timeout_seconds: float,
    lock_timeout_seconds: float,
) -> None:
    _validate_pg_environment(dict(os.environ))
    manifest = load_manifest(schema_root)
    ensure_app_compatible(
        app_version=app_version,
        minimum_app_version=manifest.minimum_app_version,
    )
    if not app_commit.strip():
        raise SchemaV2Error("app_commit must be non-empty")

    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised by the runner image.
        raise SchemaV2Error("psycopg is required to install Schema v2") from exc

    try:
        connection = _connect_with_retry(
            timeout_seconds=connect_timeout_seconds,
            driver=psycopg,
        )
    except SchemaV2Error:
        raise
    except Exception:
        raise SchemaV2Error("database connection failed") from None

    try:
        try:
            # Keep the session lock outside the migration transaction. This
            # makes every SQL file and its ledger write commit atomically while
            # the lock remains owned by the same connection.
            connection.autocommit = True
            with connection.cursor() as cursor:
                _verify_database_identity(
                    cursor,
                    expected_database_name=manifest.database_name,
                )
                _acquire_advisory_lock(
                    cursor,
                    timeout_seconds=lock_timeout_seconds,
                )
            try:
                with connection.transaction():
                    with connection.cursor() as cursor:
                        if command == "install":
                            _install_with_cursor(
                                cursor,
                                schema_root=schema_root.resolve(),
                                manifest=manifest,
                                app_commit=app_commit,
                            )
                        elif command == "verify":
                            cursor.execute("SET TRANSACTION READ ONLY")
                            _verify_with_cursor(cursor, manifest)
                        else:  # pragma: no cover - argparse constrains this branch.
                            raise SchemaV2Error(f"unsupported command: {command}")
            finally:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                        (ADVISORY_LOCK_NAME,),
                    )
        except SchemaV2Error:
            raise
        except Exception:
            raise SchemaV2Error("database operation failed") from None
    finally:
        try:
            connection.close()
        except Exception:
            raise SchemaV2Error("database connection cleanup failed") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install or verify the isolated Geno Schema v2")
    parser.add_argument("command", choices=("install", "verify"))
    parser.add_argument(
        "--schema-root",
        type=Path,
        default=Path("infra/db/schema-v2"),
    )
    parser.add_argument("--app-version", default=os.getenv("GENO_APP_VERSION", "0.1.0"))
    parser.add_argument("--app-commit", default=os.getenv("GENO_APP_COMMIT", "development"))
    parser.add_argument(
        "--connect-timeout-seconds",
        type=_nonnegative_finite_seconds,
        default=os.getenv("SCHEMA_V2_CONNECT_TIMEOUT_SECONDS", "30"),
    )
    parser.add_argument(
        "--lock-timeout-seconds",
        type=_nonnegative_finite_seconds,
        default=os.getenv("SCHEMA_V2_LOCK_TIMEOUT_SECONDS", "30"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_database_command(
            args.command,
            schema_root=args.schema_root,
            app_version=args.app_version,
            app_commit=args.app_commit,
            connect_timeout_seconds=args.connect_timeout_seconds,
            lock_timeout_seconds=args.lock_timeout_seconds,
        )
    except (SchemaV2Error, OSError) as exc:
        print(f"schema-v2 error: {exc}", file=sys.stderr)
        return 2
    print(f"Schema v2 {args.command} complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
