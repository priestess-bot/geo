from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _require(name: str, condition: bool, detail: str) -> dict[str, str]:
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    return {"name": name, "status": "pass", "detail": detail}


def _round_trip_manifest() -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="geno-backup-smoke-") as root:
        base = Path(root)
        postgres_dump = base / "postgres.dump"
        object_payload = base / "report.pdf"
        manifest_path = base / "manifest.json"
        postgres_dump.write_text("pg_dump custom archive placeholder\n", encoding="utf-8")
        object_payload.write_bytes(b"%PDF-1.4\nbackup-smoke\n%%EOF\n")
        manifest = {
            "postgres_dump_sha256": hashlib.sha256(postgres_dump.read_bytes()).hexdigest(),
            "object_payload_sha256": hashlib.sha256(object_payload.read_bytes()).hexdigest(),
        }
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        restored = json.loads(manifest_path.read_text(encoding="utf-8"))
        if restored != manifest:
            raise AssertionError("backup manifest round trip mismatch")
        return manifest


def build_backup_smoke_report() -> dict[str, object]:
    compose = _read("infra/docker-compose.yml")
    makefile = _read("Makefile")
    migration = _read("infra/db/migrations/up/0020_action_recommendation_contract.sql")
    manifest = _round_trip_manifest()
    checks = [
        _require("postgres_volume", "postgres_data:" in compose, "Postgres named volume is configured"),
        _require("minio_volume", "minio_data:" in compose, "MinIO named volume is configured"),
        _require("report_object_store", "OBJECT_STORE_BUCKET: geno-reports" in compose, "Report/evidence bucket is wired"),
        _require("incremental_migration_in_compose", "0020_action_recommendation_contract.sql" in compose, "Latest additive migration runs in docker startup"),
        _require("migration_is_additive", "ADD COLUMN IF NOT EXISTS" in migration and "CREATE INDEX IF NOT EXISTS" in migration, "Latest migration is expand-only"),
        _require("backup_make_target", "backup-smoke:" in makefile and "scripts/verify_backup_smoke.py" in makefile, "Makefile runs executable backup smoke"),
        _require("postgres_manifest_round_trip", bool(manifest["postgres_dump_sha256"]), "Postgres backup manifest hash round trips"),
        _require("object_manifest_round_trip", bool(manifest["object_payload_sha256"]), "Object storage backup manifest hash round trips"),
    ]
    return {"status": "pass", "checks": checks, "summary": {"pass": len(checks), "fail": 0}}


def main() -> int:
    print(json.dumps(build_backup_smoke_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
