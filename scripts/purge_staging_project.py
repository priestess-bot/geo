#!/usr/bin/env python3
"""Precisely remove one backed-up staging Project and its project-scoped objects."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

try:
    from scripts.staging_project_backup import (
        DEFAULT_WRITER_CONTAINERS,
        assert_project,
        paused_containers,
        project_relation_counts,
        sha256_file,
    )
except ModuleNotFoundError:  # Direct `python scripts/...` execution.
    from staging_project_backup import (  # type: ignore[no-redef]
        DEFAULT_WRITER_CONTAINERS,
        assert_project,
        paused_containers,
        project_relation_counts,
        sha256_file,
    )


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def validate_backup_manifest(
    path: Path, *, project_id: UUID, project_name: str
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("backup manifest is unavailable or invalid") from error
    project = payload.get("project", {})
    archive = payload.get("archive", {})
    if (
        payload.get("schema_version") != 1
        or payload.get("status") != "verified"
        or project.get("id") != str(project_id)
        or project.get("name") != project_name
    ):
        raise RuntimeError("backup manifest does not verify the exact removal target")
    archive_path = path.parent / str(archive.get("path", ""))
    if (
        not archive_path.is_file()
        or archive.get("sha256") != sha256_file(archive_path)
        or archive.get("size_bytes") != archive_path.stat().st_size
    ):
        raise RuntimeError("backup archive is missing or differs from its verified manifest")
    checks = payload.get("restore_checks", {})
    if (
        checks.get("postgres_project_verified") is not True
        or int(checks.get("secret_decrypt_canary_count", 0)) < 1
        or int(checks.get("minio_project_file_count", 0)) < 1
    ):
        raise RuntimeError("backup manifest has not passed database, object, and key restore checks")
    return payload


def assert_confirmation(
    *, project_id: UUID, project_name: str, confirm_project_id: str, confirm_name: str
) -> None:
    if confirm_project_id != str(project_id) or confirm_name != project_name:
        raise RuntimeError("project removal confirmation does not exactly match the target")


def assert_installer(connection: psycopg.Connection[dict[str, object]]) -> None:
    row = connection.execute(
        """SELECT current_user AS current_user, session_user AS session_user,
                  pg_get_userbyid(database.datdba) AS database_owner,
                  role.rolsuper, role.rolbypassrls
             FROM pg_database AS database
             JOIN pg_roles AS role ON role.rolname = current_user
            WHERE database.datname = current_database()"""
    ).fetchone()
    if row is None or not (
        row["current_user"] == row["session_user"] == row["database_owner"]
        and row["current_user"] not in {"geo_app", "geo_worker"}
        and (bool(row["rolsuper"]) or bool(row["rolbypassrls"]))
    ):
        raise RuntimeError("project removal requires the direct database-owner installer role")


def assert_project_delete_fks(connection: psycopg.Connection[dict[str, object]]) -> None:
    rows = connection.execute(
        """SELECT child.relname AS child_table, constraint_row.conname,
                  constraint_row.confdeltype
             FROM pg_constraint AS constraint_row
             JOIN pg_class AS child ON child.oid = constraint_row.conrelid
            WHERE constraint_row.contype = 'f'
              AND constraint_row.confrelid = 'projects'::regclass
            ORDER BY child.relname, constraint_row.conname"""
    ).fetchall()
    unsafe = [
        row
        for row in rows
        if row["confdeltype"] != "c" and row["child_table"] != "access_audit_events"
    ]
    if unsafe:
        raise RuntimeError(f"unexpected non-cascading Project foreign keys: {unsafe}")


def project_base_tables(
    connection: psycopg.Connection[dict[str, object]],
) -> list[str]:
    rows = connection.execute(
        """SELECT DISTINCT relation.relname AS table_name
             FROM pg_class AS relation
             JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
             JOIN pg_attribute AS attribute ON attribute.attrelid = relation.oid
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p')
              AND attribute.attname = 'project_id'
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            ORDER BY relation.relname"""
    ).fetchall()
    return [str(row["table_name"]) for row in rows]


def verify_foreign_key_integrity(connection: psycopg.Connection[dict[str, object]]) -> None:
    source = (REPOSITORY_ROOT / "scripts/check_postgres_fk_integrity.sql").read_text(
        encoding="utf-8"
    )
    connection.execute(source)


def audit_rows_hash(
    connection: psycopg.Connection[dict[str, object]], project_id: UUID
) -> tuple[int, str]:
    rows = connection.execute(
        """SELECT id::text, tenant_id::text, project_id::text, actor_identity_id::text,
                  event_type, subject_type, subject_id::text, metadata, created_at::text
             FROM access_audit_events WHERE project_id = %s ORDER BY created_at, id""",
        (project_id,),
    ).fetchall()
    encoded = json.dumps(rows, default=str, sort_keys=True, separators=(",", ":")).encode()
    return len(rows), hashlib.sha256(encoded).hexdigest()


def delete_project_transaction(
    connection: psycopg.Connection[dict[str, object]],
    *,
    project_id: UUID,
    project_name: str,
    rollback: bool,
) -> dict[str, object]:
    assert_installer(connection)
    assert_project_delete_fks(connection)
    project = assert_project(connection, project_id, project_name)
    connection.execute("SELECT id FROM projects WHERE id = %s FOR UPDATE", (project_id,))
    before_counts = project_relation_counts(connection, project_id)
    audit_count, audit_hash = audit_rows_hash(connection, project_id)
    tables = project_base_tables(connection)
    connection.execute("SET LOCAL session_replication_role = 'replica'")
    for table_name in tables:
        connection.execute(
            sql.SQL("DELETE FROM {} WHERE project_id = %s").format(
                sql.Identifier(table_name)
            ),
            (project_id,),
        )
    deleted = connection.execute(
        "DELETE FROM projects WHERE id = %s AND tenant_id = %s RETURNING id",
        (project_id, project["tenant_id"]),
    ).fetchone()
    connection.execute("SET LOCAL session_replication_role = 'origin'")
    if deleted is None:
        raise RuntimeError("the exact Project row was not deleted")
    remaining = connection.execute(
        "SELECT count(*) AS count FROM projects WHERE id = %s", (project_id,)
    ).fetchone()
    if remaining is None or int(remaining["count"]) != 0:
        raise RuntimeError("Project deletion did not become visible inside the transaction")
    residual_counts = project_relation_counts(connection, project_id)
    if residual_counts:
        raise RuntimeError(f"project-scoped rows remain after deletion: {residual_counts}")
    verify_foreign_key_integrity(connection)
    result = {
        "project_id": str(project_id),
        "project_name": project_name,
        "project_relation_counts": before_counts,
        "access_audit_event_count": audit_count,
        "access_audit_event_sha256": audit_hash,
        "project_base_table_count": len(tables),
        "session_replication_role_override": "transaction_local_replica_then_origin",
        "foreign_key_integrity_verified": True,
    }
    if rollback:
        connection.rollback()
        with connection.transaction():
            assert_project(connection, project_id, project_name)
        return {**result, "database_status": "simulated_and_rolled_back"}
    connection.commit()
    return {**result, "database_status": "deleted"}


def list_project_objects(minio_container: str, project_id: UUID) -> list[str]:
    completed = subprocess.run(
        [
            "docker",
            "exec",
            minio_container,
            "mc",
            "ls",
            "--recursive",
            "--json",
            "staging",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    keys: list[str] = []
    for line in completed.stdout.splitlines():
        payload = json.loads(line)
        key = payload.get("key")
        if payload.get("type") == "file" and isinstance(key, str):
            if str(project_id) in key.split("/"):
                keys.append(key)
    return sorted(set(keys))


def remove_project_objects(minio_container: str, project_id: UUID) -> dict[str, object]:
    keys = list_project_objects(minio_container, project_id)
    key_hash = hashlib.sha256("\n".join(keys).encode()).hexdigest()
    for start in range(0, len(keys), 50):
        targets = [f"staging/{key}" for key in keys[start : start + 50]]
        subprocess.run(
            [
                "docker",
                "exec",
                minio_container,
                "mc",
                "rm",
                "--force",
                "--versions",
                *targets,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    remaining = list_project_objects(minio_container, project_id)
    if remaining:
        raise RuntimeError(f"{len(remaining)} project-scoped MinIO objects remain")
    return {
        "artifact_status": "deleted",
        "artifact_object_count": len(keys),
        "artifact_object_key_sha256": key_hash,
    }


def write_receipt(path: Path | None, payload: dict[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True, type=lambda value: str(UUID(value)))
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--confirm-project-id", default="")
    parser.add_argument("--confirm-name", default="")
    parser.add_argument("--backup-manifest", type=Path)
    parser.add_argument(
        "--database-url",
        default=os.getenv("GEO_STAGING_DATABASE_URL", ""),
        help="installer database URL; GEO_STAGING_DATABASE_URL is preferred",
    )
    parser.add_argument("--minio-container", default="geo-advinsys-staging-v2-minio-1")
    parser.add_argument(
        "--writer-container", action="append", default=list(DEFAULT_WRITER_CONTAINERS)
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--simulate-delete", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or GEO_STAGING_DATABASE_URL is required")

    project_id = UUID(args.project_id)
    destructive = args.simulate_delete or args.apply
    backup: dict[str, Any] | None = None
    if destructive:
        assert_confirmation(
            project_id=project_id,
            project_name=args.project_name,
            confirm_project_id=args.confirm_project_id,
            confirm_name=args.confirm_name,
        )
        if args.backup_manifest is None:
            parser.error("--backup-manifest is required for deletion simulation or apply")
        backup = validate_backup_manifest(
            args.backup_manifest.resolve(),
            project_id=project_id,
            project_name=args.project_name,
        )

    started_at = datetime.now(UTC).isoformat()
    with paused_containers(tuple(args.writer_container)):
        with psycopg.connect(args.database_url, row_factory=dict_row) as connection:
            existing = connection.execute(
                "SELECT name FROM projects WHERE id = %s", (project_id,)
            ).fetchone()
            if not destructive:
                project = assert_project(connection, project_id, args.project_name)
                database_result = {
                    "database_status": "dry_run",
                    "tenant_id": str(project["tenant_id"]),
                    "project_relation_counts": project_relation_counts(connection, project_id),
                }
            elif existing is None and args.apply:
                database_result = {"database_status": "already_deleted"}
            else:
                database_result = delete_project_transaction(
                    connection,
                    project_id=project_id,
                    project_name=args.project_name,
                    rollback=args.simulate_delete,
                )

        object_keys = list_project_objects(args.minio_container, project_id)
        if args.apply:
            artifact_result = remove_project_objects(args.minio_container, project_id)
        else:
            artifact_result = {
                "artifact_status": "dry_run",
                "artifact_object_count": len(object_keys),
                "artifact_object_key_sha256": hashlib.sha256(
                    "\n".join(object_keys).encode()
                ).hexdigest(),
            }

    receipt = {
        "schema_version": 1,
        "status": "completed" if args.apply else "verified_no_change",
        "action": "apply" if args.apply else "simulate_delete" if args.simulate_delete else "dry_run",
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "project_id": str(project_id),
        "project_name": args.project_name,
        "backup_manifest": str(args.backup_manifest.resolve()) if args.backup_manifest else None,
        "backup_archive_sha256": backup["archive"]["sha256"] if backup else None,
        "database": database_result,
        "artifacts": artifact_result,
    }
    write_receipt(args.receipt, receipt)
    print(json.dumps(receipt, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
