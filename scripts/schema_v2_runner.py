from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence


EXPECTED_SCHEMA_GENERATION = 2
MANIFEST_VERSION = 1
ADVISORY_LOCK_NAME = "geno:schema-v2:install"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\.(?P<patch>0|[1-9][0-9]*)(?:[-+].*)?$")


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


def _assert_clean_public_schema(cursor: Any) -> None:
    cursor.execute(
        "SELECT tablename FROM pg_catalog.pg_tables "
        "WHERE schemaname = 'public' ORDER BY tablename"
    )
    existing_tables = [str(row[0]) for row in cursor.fetchall()]
    if existing_tables:
        raise SchemaV2Error(
            "refusing to initialize Schema v2 in a non-empty public schema: "
            f"{existing_tables}"
        )


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


def _connect_with_retry(database_url: str, *, timeout_seconds: float, driver: Any) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            return driver.connect(database_url)
        except driver.OperationalError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)


def run_database_command(
    command: str,
    *,
    database_url: str,
    schema_root: Path,
    app_version: str,
    app_commit: str,
    connect_timeout_seconds: float,
) -> None:
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
            database_url,
            timeout_seconds=connect_timeout_seconds,
            driver=psycopg,
        )
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
                cursor.execute(
                    "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
                    (ADVISORY_LOCK_NAME,),
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
        finally:
            connection.close()
    except psycopg.Error as exc:
        raise SchemaV2Error(f"database operation failed: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install or verify the isolated Geno Schema v2")
    parser.add_argument("command", choices=("install", "verify"))
    parser.add_argument(
        "--database-url",
        default=os.getenv("SCHEMA_V2_DATABASE_URL", ""),
        help="Schema v2 PostgreSQL URL (or set SCHEMA_V2_DATABASE_URL)",
    )
    parser.add_argument(
        "--schema-root",
        type=Path,
        default=Path("infra/db/schema-v2"),
    )
    parser.add_argument("--app-version", default=os.getenv("GENO_APP_VERSION", "0.1.0"))
    parser.add_argument("--app-commit", default=os.getenv("GENO_APP_COMMIT", "development"))
    parser.add_argument("--connect-timeout-seconds", type=float, default=30.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.database_url:
        print("schema-v2 error: --database-url or SCHEMA_V2_DATABASE_URL is required", file=sys.stderr)
        return 2
    try:
        run_database_command(
            args.command,
            database_url=args.database_url,
            schema_root=args.schema_root,
            app_version=args.app_version,
            app_commit=args.app_commit,
            connect_timeout_seconds=args.connect_timeout_seconds,
        )
    except (SchemaV2Error, OSError) as exc:
        print(f"schema-v2 error: {exc}", file=sys.stderr)
        return 2
    print(f"Schema v2 {args.command} complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
