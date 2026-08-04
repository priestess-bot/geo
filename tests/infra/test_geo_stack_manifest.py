from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_canonical_runtime_manifest_excludes_non_geo_projects() -> None:
    manifest = json.loads((ROOT / "infra/geo-stack-manifest.json").read_text(encoding="utf-8"))
    assert manifest["canonical_project"] == "geo"
    assert manifest["dify_project"] == "geo-dify"
    assert "geo-development" in manifest["legacy_projects"]
    assert "assetgraph" in manifest["excluded_projects"]
    assert manifest["ports"]["admin_web"] == 13001
    assert "postgres" in manifest["required_services"]
    assert manifest["dify_databases"] == ["dify", "dify_plugin"]


def test_stack_entrypoints_are_executable() -> None:
    for relative in ("scripts/geo-stack.sh", "scripts/geo_migrate.py", "scripts/geo_sync.py", "deploy/install.sh"):
        mode = (ROOT / relative).stat().st_mode
        assert mode & 0o111, relative


def test_manifest_declares_encrypted_release_transport() -> None:
    manifest = json.loads((ROOT / "infra/geo-stack-manifest.json").read_text(encoding="utf-8"))
    assert manifest["migration_entrypoint"] == "scripts/geo_sync.py"
    assert "private GitHub Release" in manifest["migration_transport"]
