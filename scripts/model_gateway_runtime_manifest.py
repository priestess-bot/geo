#!/usr/bin/env python3
"""Verify or idempotently register a governed Model Gateway runtime manifest."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path

from geo_core.model_gateway import KNOWN_MODEL_PROVIDERS
from geo_core.model_gateway.postgres_runtime_catalog import PostgresRuntimeCatalog
from geo_core.model_gateway.runtime_catalog import register_runtime_manifest
from geo_core.model_gateway.runtime_manifest import (
    ModelGatewayRuntimeManifest,
    parse_runtime_manifest,
)
from geo_core.model_gateway.runtime_manifest_schema import (
    runtime_manifest_json_schema,
    runtime_manifest_six_provider_template,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("export-schema", "export-template", "verify", "register")
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-six-providers", action="store_true")
    parser.add_argument("--database-url-env", default="GEO_DATABASE_URL")
    parser.add_argument("--database-url-file-env", default="GEO_DATABASE_URL_FILE")
    args = parser.parse_args()

    if args.command == "export-schema":
        if args.output is None:
            parser.error("--output is required for export-schema")
        _write_schema(args.output)
        print(json.dumps({"status": "exported", "output": str(args.output)}, sort_keys=True))
        return 0
    if args.command == "export-template":
        if args.output is None:
            parser.error("--output is required for export-template")
        _write_json(args.output, runtime_manifest_six_provider_template())
        print(json.dumps({"status": "exported", "output": str(args.output)}, sort_keys=True))
        return 0
    if args.manifest is None:
        parser.error("--manifest is required for verify/register")
    manifest = _load_manifest(args.manifest)
    providers = {item.adapter_release.provider for item in manifest.provider_runtimes}
    if args.require_six_providers and providers != set(KNOWN_MODEL_PROVIDERS):
        missing = sorted(set(KNOWN_MODEL_PROVIDERS) - providers)
        raise SystemExit(f"six-provider Gate is incomplete; missing={missing}")

    active_versions: list[int] = []
    if args.command == "register":
        database_url = _database_url(
            direct_env=args.database_url_env,
            file_env=args.database_url_file_env,
        )
        catalog = PostgresRuntimeCatalog(database_url)
        handles = register_runtime_manifest(catalog, manifest)
        active_versions = [handle.version for handle in handles]

    print(
        json.dumps(
            {
                "status": "registered" if args.command == "register" else "verified",
                "manifest_id": str(manifest.manifest_id),
                "project_id": str(manifest.project_id),
                "manifest_hash": manifest.manifest_hash,
                "providers": sorted(providers),
                "adapter_release_hashes": sorted(
                    item.adapter_release.release_hash for item in manifest.provider_runtimes
                ),
                "model_release_hashes": sorted(
                    item.release_hash for item in manifest.model_releases
                ),
                "policy_version_id": str(manifest.project_policy.policy_version_id),
                "policy_version_hash": manifest.project_policy.policy_version_hash,
                "active_secret_versions": active_versions,
            },
            sort_keys=True,
        )
    )
    return 0


def _load_manifest(path: Path) -> ModelGatewayRuntimeManifest:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit("runtime manifest cannot be read as JSON") from exc
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise SystemExit("runtime manifest root must be a JSON object")
    return parse_runtime_manifest(value)


def _database_url(*, direct_env: str, file_env: str) -> str:
    direct = os.getenv(direct_env, "").strip()
    if direct:
        return direct
    file_name = os.getenv(file_env, "").strip()
    if not file_name:
        raise SystemExit(f"{direct_env} or {file_env} is required for manifest registration")
    try:
        value = Path(file_name).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise SystemExit(f"{file_env} cannot be read") from exc
    if not value:
        raise SystemExit(f"{file_env} is empty")
    return value


def _write_schema(path: Path) -> None:
    _write_json(path, runtime_manifest_json_schema())


def _write_json(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
