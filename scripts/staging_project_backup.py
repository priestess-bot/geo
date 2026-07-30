#!/usr/bin/env python3
"""Create and restore-verify an encrypted staging backup before project removal."""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import tarfile
import tempfile
from typing import Iterator
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from geo_core.secrets.postgres_restore import verify_secret_store_restore


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WRITER_CONTAINERS = (
    "geo-advinsys-staging-v2-internal-api-1",
    "geo-advinsys-staging-v2-customer-api-1",
    "geo-advinsys-staging-v2-task-worker-1",
    "geo-advinsys-staging-v2-outbox-relay-1",
    "geo-advinsys-staging-v2-connector-worker-1",
    "geo-advinsys-staging-v2-browser-capture-worker-1",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate_file_hash(root: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    files = sorted(item for item in root.rglob("*") if item.is_file())
    for item in files:
        relative = item.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(item)))
    return len(files), digest.hexdigest()


def ensure_backup_key(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, base64.b64encode(secrets.token_bytes(32)) + b"\n")
        finally:
            os.close(descriptor)
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size < 32
    ):
        raise RuntimeError("backup key must be a non-empty regular file with mode 0600")


def run(command: list[str], *, stdin: Path | None = None, stdout: Path | None = None) -> str:
    input_handle = stdin.open("rb") if stdin else None
    output_handle = stdout.open("wb") if stdout else subprocess.PIPE
    try:
        completed = subprocess.run(
            command,
            check=True,
            stdin=input_handle,
            stdout=output_handle,
            stderr=subprocess.PIPE,
            text=False,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"command failed: {command[0]}: {detail}") from error
    finally:
        if input_handle:
            input_handle.close()
        if stdout and output_handle is not subprocess.PIPE:
            output_handle.close()
    return completed.stdout.decode("utf-8", errors="replace") if completed.stdout else ""


def project_relation_counts(
    connection: psycopg.Connection[dict[str, object]], project_id: UUID
) -> dict[str, int]:
    rows = connection.execute(
        """SELECT table_name
             FROM information_schema.columns
            WHERE table_schema = 'public' AND column_name = 'project_id'
            ORDER BY table_name"""
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        table_name = str(row["table_name"])
        count = connection.execute(
            sql.SQL("SELECT count(*) AS count FROM {} WHERE project_id = %s").format(
                sql.Identifier(table_name)
            ),
            (project_id,),
        ).fetchone()
        value = int(count["count"]) if count else 0
        if value:
            counts[table_name] = value
    return counts


def assert_project(
    connection: psycopg.Connection[dict[str, object]], project_id: UUID, project_name: str
) -> dict[str, object]:
    row = connection.execute(
        "SELECT id, tenant_id, name, status FROM projects WHERE id = %s", (project_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"project {project_id} does not exist")
    if row["name"] != project_name:
        raise RuntimeError(
            f"project {project_id} is named {row['name']!r}, expected {project_name!r}"
        )
    return row


@contextmanager
def paused_containers(container_names: tuple[str, ...]) -> Iterator[tuple[str, ...]]:
    paused: list[str] = []
    try:
        for name in container_names:
            inspected = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Running}}", name],
                capture_output=True,
                text=True,
                check=False,
            )
            if inspected.returncode != 0 or inspected.stdout.strip() != "true":
                continue
            run(["docker", "pause", name])
            paused.append(name)
        yield tuple(paused)
    finally:
        for name in reversed(paused):
            subprocess.run(
                ["docker", "unpause", name], capture_output=True, check=False
            )


def copy_keyrings(source: Path, target: Path) -> tuple[int, str]:
    if not source.is_dir():
        raise RuntimeError("staging keyring directory is unavailable")
    target.mkdir(mode=0o700)
    for item in sorted(source.iterdir()):
        if item.is_symlink() or not item.is_file():
            continue
        shutil.copy2(item, target / item.name)
    file_count, digest = aggregate_file_hash(target)
    if file_count == 0 or not (target / "secret-store-keyring.json").is_file():
        raise RuntimeError("staging keyring backup is incomplete")
    return file_count, digest


def create_payload(source: Path, target: Path) -> None:
    with tarfile.open(target, "w") as archive:
        for name in ("postgres.dump", "minio-data", "keyrings"):
            archive.add(source / name, arcname=name, recursive=True)


def extract_payload(payload: Path, target: Path) -> None:
    with tarfile.open(payload, "r") as archive:
        for member in archive.getmembers():
            destination = (target / member.name).resolve()
            if target.resolve() not in destination.parents and destination != target.resolve():
                raise RuntimeError("backup archive contains an unsafe member path")
        archive.extractall(target, filter="data")


def database_url_for(database_url: str, database_name: str) -> str:
    values = conninfo_to_dict(database_url)
    values["dbname"] = database_name
    return make_conninfo(**values)


def restore_database(
    *, database_url: str, postgres_container: str, dump: Path, database_name: str
) -> str:
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database_name))
        )
    run(
        [
            "docker",
            "exec",
            "-i",
            postgres_container,
            "pg_restore",
            "-U",
            "geo_installer",
            "-d",
            database_name,
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
        ],
        stdin=dump,
    )
    return database_url_for(database_url, database_name)


def drop_database(database_url: str, database_name: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (database_name,),
        )
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))


def verify_restored_payload(
    *,
    extracted: Path,
    database_url: str,
    postgres_container: str,
    project_id: UUID,
    project_name: str,
    expected_counts: dict[str, int],
) -> dict[str, object]:
    minio_root = extracted / "minio-data"
    minio_count, minio_hash = aggregate_file_hash(minio_root)
    project_object_count = sum(
        1
        for item in minio_root.rglob("*")
        if item.is_file() and str(project_id) in item.as_posix()
    )
    if minio_count == 0 or project_object_count == 0:
        raise RuntimeError("restored MinIO copy does not contain project artifacts")

    database_name = f"geo_restore_{uuid4().hex[:12]}"
    restored_url = ""
    try:
        restored_url = restore_database(
            database_url=database_url,
            postgres_container=postgres_container,
            dump=extracted / "postgres.dump",
            database_name=database_name,
        )
        with psycopg.connect(restored_url, row_factory=dict_row) as connection:
            restored_project = assert_project(connection, project_id, project_name)
            restored_counts = project_relation_counts(connection, project_id)
            migration = connection.execute(
                "SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1"
            ).fetchone()
        if restored_counts != expected_counts:
            raise RuntimeError("restored project relation counts differ from the source snapshot")
        secret_result = verify_secret_store_restore(
            database_url=restored_url,
            keyring_path=extracted / "keyrings" / "secret-store-keyring.json",
        )
        if secret_result.representative_secret_count < 1:
            raise RuntimeError("restored Secret Store has no representative ciphertext")
        return {
            "postgres_project_verified": True,
            "postgres_project_status": str(restored_project["status"]),
            "postgres_relation_count": len(restored_counts),
            "migration_revision": str(migration["version_num"]) if migration else None,
            "minio_file_count": minio_count,
            "minio_content_sha256": minio_hash,
            "minio_project_file_count": project_object_count,
            "secret_key_versions": list(secret_result.verified_key_versions),
            "secret_decrypt_canary_count": secret_result.representative_secret_count,
        }
    finally:
        if restored_url:
            drop_database(database_url, database_name)


def create_backup(args: argparse.Namespace) -> Path:
    project_id = UUID(args.project_id)
    started_at = datetime.now(UTC)
    run_id = f"advinsys-pre-delete-{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    pending = output_root / f".{run_id}.{os.getpid()}.pending"
    final = output_root / run_id
    if final.exists():
        raise RuntimeError(f"backup destination already exists: {final}")
    pending.mkdir(mode=0o700)
    ensure_backup_key(args.backup_key.resolve())

    try:
        with psycopg.connect(args.database_url, row_factory=dict_row) as connection:
            project = assert_project(connection, project_id, args.confirm_name)
            source_counts = project_relation_counts(connection, project_id)

        with tempfile.TemporaryDirectory(prefix="geo-staging-backup-") as temporary_name:
            temporary = Path(temporary_name)
            os.chmod(temporary, 0o700)
            source = temporary / "source"
            source.mkdir(mode=0o700)
            with paused_containers(tuple(args.writer_container)) as paused:
                run(
                    [
                        "docker",
                        "exec",
                        args.postgres_container,
                        "pg_dump",
                        "-U",
                        "geo_installer",
                        "-d",
                        "geo",
                        "-Fc",
                        "--no-owner",
                    ],
                    stdout=source / "postgres.dump",
                )
                run(
                    [
                        "docker",
                        "cp",
                        f"{args.minio_container}:/data/.",
                        str(source / "minio-data"),
                    ]
                )
                keyring_count, keyring_hash = copy_keyrings(
                    args.keyring_directory.resolve(), source / "keyrings"
                )

            payload = temporary / "payload.tar"
            create_payload(source, payload)
            archive = pending / "backup.tar.gpg"
            run(
                [
                    "gpg",
                    "--batch",
                    "--yes",
                    "--pinentry-mode",
                    "loopback",
                    "--passphrase-file",
                    str(args.backup_key.resolve()),
                    "--symmetric",
                    "--cipher-algo",
                    "AES256",
                    "--compress-algo",
                    "none",
                    "--output",
                    str(archive),
                    str(payload),
                ]
            )
            os.chmod(archive, 0o600)
            decrypted = temporary / "verified-payload.tar"
            run(
                [
                    "gpg",
                    "--batch",
                    "--yes",
                    "--pinentry-mode",
                    "loopback",
                    "--passphrase-file",
                    str(args.backup_key.resolve()),
                    "--decrypt",
                    "--output",
                    str(decrypted),
                    str(archive),
                ]
            )
            extracted = temporary / "restored"
            extracted.mkdir(mode=0o700)
            extract_payload(decrypted, extracted)
            checks = verify_restored_payload(
                extracted=extracted,
                database_url=args.database_url,
                postgres_container=args.postgres_container,
                project_id=project_id,
                project_name=args.confirm_name,
                expected_counts=source_counts,
            )

        manifest = {
            "schema_version": 1,
            "status": "verified",
            "created_at": started_at.isoformat(),
            "verified_at": datetime.now(UTC).isoformat(),
            "project": {
                "id": str(project_id),
                "tenant_id": str(project["tenant_id"]),
                "name": str(project["name"]),
            },
            "source": {
                "postgres_container": args.postgres_container,
                "minio_container": args.minio_container,
                "paused_writer_containers": list(paused),
                "project_relation_counts": source_counts,
                "keyring_file_count": keyring_count,
                "keyring_content_sha256": keyring_hash,
            },
            "archive": {
                "path": "backup.tar.gpg",
                "size_bytes": archive.stat().st_size,
                "sha256": sha256_file(archive),
                "encryption": "OpenPGP symmetric AES256",
                "key_reference": str(args.backup_key.resolve()),
            },
            "restore_checks": checks,
        }
        manifest_path = pending / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.chmod(manifest_path, 0o600)
        os.replace(pending, final)
        return final / "manifest.json"
    except Exception:
        shutil.rmtree(pending, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True, type=lambda value: str(UUID(value)))
    parser.add_argument("--confirm-name", required=True)
    parser.add_argument(
        "--database-url",
        default=os.getenv("GEO_STAGING_DATABASE_URL", ""),
        help="installer database URL; GEO_STAGING_DATABASE_URL is preferred",
    )
    parser.add_argument(
        "--postgres-container", default="geo-advinsys-staging-v2-postgres-1"
    )
    parser.add_argument("--minio-container", default="geo-advinsys-staging-v2-minio-1")
    parser.add_argument(
        "--writer-container", action="append", default=list(DEFAULT_WRITER_CONTAINERS)
    )
    parser.add_argument(
        "--keyring-directory", type=Path, default=REPOSITORY_ROOT / "artifacts/staging-secrets"
    )
    parser.add_argument(
        "--backup-key",
        type=Path,
        default=REPOSITORY_ROOT / "artifacts/staging-secrets/staging-project-backup-passphrase",
    )
    parser.add_argument(
        "--output-root", type=Path, default=REPOSITORY_ROOT / "artifacts/runs"
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or GEO_STAGING_DATABASE_URL is required")
    manifest_path = create_backup(args)
    print(json.dumps({"status": "verified", "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
