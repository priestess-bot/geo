from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def test_canonical_runtime_manifest_excludes_non_geo_projects() -> None:
    manifest = json.loads((ROOT / "infra/geo-stack-manifest.json").read_text(encoding="utf-8"))
    assert manifest["canonical_project"] == "geo"
    assert manifest["supported_modes"] == ["internal", "production"]
    assert manifest["dify_project"] == "geo-dify"
    assert {"api", "web", "worker", "db_postgres", "weaviate"} <= set(
        manifest["dify_required_services"]
    )
    assert "geo-development" in manifest["legacy_projects"]
    assert "geo-advinsys-staging-v2" in manifest["legacy_projects"]
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


def test_installer_preserves_existing_keyrings_and_rejects_partial_certificate_pair() -> None:
    installer = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    assert "if destination.exists() or destination.is_symlink():" in installer
    assert re.search(r"validate_existing\(\)\s+raise SystemExit\(0\)", installer)
    assert "keyring must contain its active key version" in installer
    assert "alert webhook certificate pair is incomplete" in installer


def test_installer_and_stack_mode_fail_closed() -> None:
    installer = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    assert 'GEO_STACK_MODE must be internal or production' in installer
    assert "production mode requires a pre-provisioned env file" in installer
    stack = (ROOT / "scripts/geo-stack.sh").read_text(encoding="utf-8")
    assert 'GEO_STACK_MODE must be internal or production' in stack
    assert 'production_preflight.py' in stack
    assert 'run_with_profiles up -d --build' in stack
    assert 'command -v python3' in stack
    assert 'run_dify up' in stack
    assert 'startswith("GEO_DIFY_")' in stack
    assert 'label=com.docker.compose.project=${project}' in stack
    assert '|| true' not in stack.split('cleanup_legacy()', 1)[1].split('delegate_migration()', 1)[0]
    assert 'identity_env_option=(--source-env-file "${STACK_ENV_FILE}")' in stack
    assert 'identity_env_option=(--target-env-file "${STACK_ENV_FILE}")' in stack


def test_legacy_volume_deletion_requires_full_current_package_verification() -> None:
    stack = (ROOT / "scripts/geo-stack.sh").read_text(encoding="utf-8")
    cleanup = stack.split("cleanup_legacy()", 1)[1].split("delegate_migration()", 1)[0]
    assert "geo_migrate.py\" verify" in cleanup
    assert "--require-current-schema" in cleanup
    assert "--write-receipt" in cleanup
    assert "verification-receipt.json" in cleanup
    assert "manifest_sha256" in cleanup
    assert "payload_sha256" in cleanup
    assert "identity_bindings_sha256" in cleanup
    assert "GEO_MIGRATION_KEY_FILE" in cleanup


def test_release_tracking_covers_canonical_first_party_services() -> None:
    manifest = json.loads((ROOT / "infra/geo-stack-manifest.json").read_text(encoding="utf-8"))
    internal = set(manifest["release_tracked_services"]["internal"])
    assert {
        "internal-api",
        "customer-api",
        "task-worker",
        "outbox-relay",
        "connector-worker",
        "browser-capture-worker",
        "admin-web",
        "customer-web",
    } <= internal


def test_production_bundle_connects_dify_without_weakening_service_identity() -> None:
    manifest = json.loads((ROOT / "infra/geo-stack-manifest.json").read_text(encoding="utf-8"))
    overlay_name = "infra/dify/compose.production-runtime.yml"
    assert overlay_name in manifest["production_compose_files"]
    overlay = (ROOT / overlay_name).read_text(encoding="utf-8")
    assert "GEO_WORKFLOW_RUNTIME_BACKEND: dify" in overlay
    assert "geo_dify_runtime" in overlay
    assert "user:" not in overlay
