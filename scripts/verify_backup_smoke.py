from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _require(name: str, condition: bool, detail: str) -> dict[str, str]:
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    return {"name": name, "status": "pass", "detail": detail}


def build_backup_smoke_report() -> dict[str, object]:
    compose = _read("infra/docker-compose.yml")
    bootstrap = _read("infra/minio/bootstrap.sh")
    object_smoke = _read("infra/minio/backup-restore-smoke.sh")
    makefile = _read("Makefile")
    migration = _read("infra/db/migrations/up/0024_market_neutral_defaults.sql")
    checks = [
        _require(
            "postgres_volume", "postgres_data:" in compose, "Postgres named volume is configured"
        ),
        _require("minio_volume", "minio_data:" in compose, "MinIO named volume is configured"),
        _require(
            "report_object_store",
            "OBJECT_STORE_BUCKET: geo-reports" in compose,
            "Report/evidence bucket is wired",
        ),
        _require(
            "incremental_migration_in_compose",
            "0024_market_neutral_defaults.sql" in compose,
            "Latest additive migration runs in docker startup",
        ),
        _require(
            "migration_has_no_destructive_schema_change",
            "DROP TABLE" not in migration and "DROP COLUMN" not in migration,
            "Latest migration has no destructive schema changes",
        ),
        _require(
            "migration_archives_deduplicated_rows",
            "knowledge_trace_refs_dedup_archive" in migration
            and "INSERT INTO knowledge_trace_refs_dedup_archive" in migration,
            "Trace rows are archived before deduplication",
        ),
        _require(
            "postgres_runtime_restore",
            "backup-postgres-smoke:" in compose
            and "pg_dump" in compose
            and "pg_restore" in compose,
            "Postgres smoke performs a real dump and restore",
        ),
        _require(
            "postgres_runtime_comparison",
            "source_tables" in compose and "restored_projects" in compose,
            "Restored schema and project counts are compared",
        ),
        _require(
            "object_runtime_restore",
            "backup-object-smoke:" in compose
            and 'test "$source_hash" = "$backup_hash"' in object_smoke
            and 'test "$source_hash" = "$restored_hash"' in object_smoke,
            "Object smoke copies and restores a real object with matching SHA-256",
        ),
        _require(
            "bucket_creation_is_bootstrap_only",
            "mc mb --ignore-existing" in bootstrap
            and "mc mb --ignore-existing" not in object_smoke,
            "Only MinIO bootstrap creates required buckets",
        ),
        _require(
            "source_object_is_preserved",
            'mc rm "backup/$source_bucket/' not in object_smoke,
            "Backup smoke never deletes the source business object",
        ),
        _require(
            "backup_policy_negative_checks",
            "formal_backup_delete_denied" in object_smoke
            and "cross_run_delete_denied" in object_smoke
            and "source_write_denied" in object_smoke,
            "Backup smoke verifies source-write, formal-delete, and cross-run-delete denial",
        ),
        _require(
            "formal_backup_roundtrip",
            "formal_backup_put_list_get" in object_smoke,
            "Formal backup prefix performs put/list/get while retaining delete denial",
        ),
        _require(
            "ephemeral_principal_revocation",
            "ephemeral-cleanup.json" in bootstrap
            and "restore_principal_revoked" in bootstrap
            and "retention_principal_revoked" in bootstrap,
            "Restore and retention principals emit a verified revocation receipt",
        ),
        _require(
            "backup_make_target",
            "--profile backup-smoke" in makefile
            and "backup-postgres-smoke" in makefile
            and "backup-object-smoke" in makefile,
            "Makefile runs both runtime restore smokes",
        ),
    ]
    return {
        "status": "pass",
        "scope": "configuration_contract",
        "checks": checks,
        "summary": {"pass": len(checks), "fail": 0},
        "runtime_requirement": "make backup-smoke must also complete both Docker restore services",
    }


def main() -> int:
    print(json.dumps(build_backup_smoke_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
