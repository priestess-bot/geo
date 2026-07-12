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
    makefile = _read("Makefile")
    migration = _read("infra/db/migrations/up/0024_market_neutral_defaults.sql")
    checks = [
        _require("postgres_volume", "postgres_data:" in compose, "Postgres named volume is configured"),
        _require("minio_volume", "minio_data:" in compose, "MinIO named volume is configured"),
        _require("report_object_store", "OBJECT_STORE_BUCKET: geno-reports" in compose, "Report/evidence bucket is wired"),
        _require("incremental_migration_in_compose", "0024_market_neutral_defaults.sql" in compose, "Latest additive migration runs in docker startup"),
        _require("migration_has_no_destructive_schema_change", "DROP TABLE" not in migration and "DROP COLUMN" not in migration, "Latest migration has no destructive schema changes"),
        _require("migration_archives_deduplicated_rows", "knowledge_trace_refs_dedup_archive" in migration and "INSERT INTO knowledge_trace_refs_dedup_archive" in migration, "Trace rows are archived before deduplication"),
        _require("postgres_runtime_restore", "backup-postgres-smoke:" in compose and "pg_dump" in compose and "pg_restore" in compose, "Postgres smoke performs a real dump and restore"),
        _require("postgres_runtime_comparison", "source_tables" in compose and "restored_projects" in compose, "Restored schema and project counts are compared"),
        _require(
            "object_runtime_restore",
            "backup-object-smoke:" in compose
            and "mc rm" in compose
            and 'test "$$source_sha" = "$$restored_sha"' in compose,
            "Object smoke deletes and restores a real object with matching SHA-256",
        ),
        _require("backup_make_target", "--profile backup-smoke" in makefile and "backup-postgres-smoke" in makefile and "backup-object-smoke" in makefile, "Makefile runs both runtime restore smokes"),
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
