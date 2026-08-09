from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

import pytest

from scripts.geo_migrate import _canonical_json, _encrypt
from scripts.geo_sync import (
    ARCHIVE_SCHEMA,
    DELTA_SCHEMA,
    SyncError,
    _build_delta,
    _chunk,
    _join_chunks,
    _materialize_release,
    _baseline_stack_environment,
    _baseline_stack_import_command,
    _parser,
    _require_delta_parent,
    _require_role,
    _repo_slug,
    _write_materialized_package,
)


def _package(root: Path, name: str, files: dict[str, str], passphrase: Path) -> Path:
    package = root / name
    payload = package / "payload"
    payload.mkdir(parents=True)
    for relative, value in files.items():
        target = payload / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")
    entries = []
    from scripts.geo_migrate import _files

    entries.extend(_files(payload))
    (payload / "payload-manifest.json").write_bytes(_canonical_json({"files": entries}))
    encrypted = package / "payload.tar.gz.gpg"
    tar_path = root / f"{name}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as archive:
        for item in sorted(payload.rglob("*")):
            if item.is_file():
                archive.add(item, arcname=item.relative_to(payload).as_posix(), recursive=False)
    _encrypt(tar_path, encrypted, passphrase)
    manifest = {
        "schema_version": "geo-runtime-migration-v2",
        "status": "verified-export",
        "kind": "baseline",
        "archive_id": name,
        "release_tag": f"geo-migration-{name}",
        "source_git": {"commit": "a" * 40, "dirty": False},
        "payload": {
            "path": encrypted.name,
            "size_bytes": encrypted.stat().st_size,
            "sha256": hashlib.sha256(encrypted.read_bytes()).hexdigest(),
        },
    }
    (package / "manifest.json").write_bytes(_canonical_json(manifest))
    return package


def test_repo_slug_requires_owner_and_name() -> None:
    assert _repo_slug("https://github.com/priestess-bot/geo.git") == "priestess-bot/geo"
    with pytest.raises(SyncError):
        _repo_slug("geo")


def test_chunk_join_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "payload.gpg"
    source.write_bytes(b"0123456789")
    chunks = _chunk(source, tmp_path / "chunks", size=3)
    archive = {"chunks": chunks, "payload_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    joined = tmp_path / "joined.gpg"
    _join_chunks(tmp_path / "chunks", archive, joined)
    assert joined.read_bytes() == source.read_bytes()


def test_delta_carries_changes_and_deletions(tmp_path: Path) -> None:
    passphrase = tmp_path / "passphrase"
    passphrase.write_text("test-only-passphrase", encoding="utf-8")
    passphrase.chmod(0o600)
    parent = _package(tmp_path, "parent", {"geo/a.txt": "old", "geo/remove.txt": "gone"}, passphrase)
    current = _package(tmp_path, "current", {"geo/a.txt": "new", "geo/add.txt": "added"}, passphrase)
    delta = _build_delta(current, parent, passphrase, tmp_path / "out")
    manifest = json.loads((delta / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == DELTA_SCHEMA
    assert manifest["parent_release"] == "geo-migration-parent"
    assert manifest["changes"]["changed_paths"] == ["geo/a.txt", "geo/add.txt"]
    assert manifest["changes"]["deleted_paths"] == ["geo/remove.txt"]
    with pytest.raises(SyncError, match="previous full geo-runtime package"):
        _build_delta(current, delta, passphrase, tmp_path / "out-rejected")


def test_materialize_release_reconstructs_a_delta_chain(tmp_path: Path) -> None:
    passphrase = tmp_path / "passphrase"
    passphrase.write_text("test-only-passphrase", encoding="utf-8")
    passphrase.chmod(0o600)
    parent = _package(tmp_path, "parent", {"geo/a.txt": "old", "geo/remove.txt": "gone"}, passphrase)
    current = _package(tmp_path, "current", {"geo/a.txt": "new", "geo/add.txt": "added"}, passphrase)
    delta = _build_delta(current, parent, passphrase, tmp_path / "out")
    newer = _package(tmp_path, "newer", {"geo/a.txt": "newest", "geo/add.txt": "added"}, passphrase)
    second_delta = _build_delta(newer, current, passphrase, tmp_path / "out", parent_release=delta.name)
    second_manifest = json.loads((second_delta / "manifest.json").read_text(encoding="utf-8"))
    second_manifest["parent_archive_id"] = delta.name
    (second_delta / "manifest.json").write_bytes(_canonical_json(second_manifest))

    cache = tmp_path / "cache"
    shutil.copytree(parent, cache / "geo-migration-parent")
    shutil.copytree(delta, cache / delta.name)
    shutil.copytree(second_delta, cache / second_delta.name)
    destination = tmp_path / "materialized"
    base_manifest = _materialize_release(
        "priestess-bot/geo",
        second_delta.name,
        passphrase,
        cache,
        destination,
        set(),
    )

    assert base_manifest["archive_id"] == "parent"
    assert (destination / "payload/geo/a.txt").read_text(encoding="utf-8") == "newest"
    assert (destination / "payload/geo/add.txt").read_text(encoding="utf-8") == "added"
    assert not (destination / "payload/geo/remove.txt").exists()

    materialized = _write_materialized_package(
        destination / "payload",
        base_manifest,
        passphrase,
        tmp_path / "materialized-package",
    )
    assert (materialized / "manifest.json").is_file()
    assert (materialized / "payload.tar.gz.gpg").is_file()


def test_incremental_apply_requires_a_primary_source() -> None:
    with pytest.raises(SyncError, match="source_role=primary"):
        _require_role({"source_role": "source"}, {"primary"}, operation="incremental apply")


def test_delta_parent_identity_is_checked() -> None:
    with pytest.raises(SyncError, match="parent mismatch"):
        _require_delta_parent(
            {"parent_archive_id": "expected"},
            {"archive_id": "other"},
        )


def test_archive_schema_is_distinct_from_package_schema() -> None:
    assert ARCHIVE_SCHEMA != DELTA_SCHEMA


def test_baseline_import_uses_canonical_stack_and_forwards_runtime_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack_env = tmp_path / "production.env"
    runtime_root = tmp_path / "dify-runtime"
    state_file = tmp_path / "state" / "geo-dify-state.json"
    passphrase = tmp_path / "passphrase"
    secret_root = tmp_path / "secrets"
    package = tmp_path / "baseline"
    args = argparse.Namespace(
        stack_env_file=str(stack_env),
        stack_mode="production",
        dify_runtime_root=str(runtime_root),
        dify_state_file=str(state_file),
        passphrase_file=str(passphrase),
        secret_root=str(secret_root),
        target_project="geo",
        dify_project="geo-dify",
    )
    monkeypatch.setenv("UNRELATED_RUNTIME_VALUE", "retained")

    command = _baseline_stack_import_command(args, package)
    environment = _baseline_stack_environment(args)

    assert command[0].endswith("/scripts/geo-stack.sh")
    assert command[1] == "import"
    assert "--target-empty" in command
    assert "--confirm" in command
    assert command[command.index("--target-env-file") + 1] == str(stack_env.resolve())
    assert environment["GEO_STACK_ENV_FILE"] == str(stack_env.resolve())
    assert environment["GEO_STACK_MODE"] == "production"
    assert environment["GEO_DIFY_RUNTIME_ROOT"] == str(runtime_root.resolve())
    assert environment["GEO_DIFY_STATE_HOST_FILE"] == str(state_file.resolve())
    assert environment["UNRELATED_RUNTIME_VALUE"] == "retained"


def test_baseline_import_defaults_follow_stack_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEO_STACK_MODE", "production")
    monkeypatch.setenv("GEO_STACK_ENV_FILE", "/srv/geo/infra/production.env")
    monkeypatch.setenv("GEO_DIFY_RUNTIME_ROOT", "/srv/geo/.runtime/dify")
    monkeypatch.setenv("GEO_DIFY_STATE_HOST_FILE", "/srv/geo/.runtime/state.json")

    args = _parser().parse_args(
        [
            "import-baseline",
            "--repo",
            "priestess-bot/geo",
            "--passphrase-file",
            "/srv/geo-secrets/migration-passphrase",
            "--secret-root",
            "/srv/geo/.secrets",
        ]
    )

    assert args.stack_mode == "production"
    assert args.stack_env_file is None
    assert args.dify_runtime_root == "/srv/geo/.runtime/dify"
    assert args.dify_state_file == "/srv/geo/.runtime/state.json"
