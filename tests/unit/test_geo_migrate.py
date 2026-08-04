from __future__ import annotations

import json
from pathlib import Path
import tarfile

import pytest

from scripts.geo_migrate import MigrationError, _extract_safe, _files, _host_tar, _verify_payload, build_parser


def test_payload_entries_are_deterministic_and_verify(tmp_path: Path) -> None:
    root = tmp_path / "payload"
    root.mkdir()
    (root / "z.txt").write_text("z", encoding="utf-8")
    (root / "a.txt").write_text("a", encoding="utf-8")

    entries = _files(root)
    assert [entry["path"] for entry in entries] == ["a.txt", "z.txt"]
    _verify_payload(root, entries)

    (root / "a.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(MigrationError, match="payload hash mismatch"):
        _verify_payload(root, entries)


def test_extract_safe_rejects_parent_escape(tmp_path: Path) -> None:
    archive = tmp_path / "payload.tar"
    with tarfile.open(archive, "w") as handle:
        info = tarfile.TarInfo("../../outside.txt")
        content = b"no"
        info.size = len(content)
        handle.addfile(info, __import__("io").BytesIO(content))
    with pytest.raises(MigrationError, match="unsafe archive member"):
        _extract_safe(archive, tmp_path / "out")


def test_manifest_sidecar_has_no_secret_values(tmp_path: Path) -> None:
    manifest = {
        "schema_version": "geo-runtime-migration-v1",
        "status": "verified-export",
        "payload": {"path": "payload.tar.gpg", "sha256": "a" * 64, "size_bytes": 10},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert "password" not in loaded
    assert "api_key" not in loaded


def test_encryption_key_can_be_excluded_from_secret_payload(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "migration-passphrase").write_text("keep-out", encoding="utf-8")
    (secrets / "runtime-key").write_text("include", encoding="utf-8")
    (secrets / "migration-passphrase").chmod(0o600)
    (secrets / "runtime-key").chmod(0o600)
    copied = tmp_path / "copied"
    from scripts.geo_migrate import _copy_regular_tree

    _copy_regular_tree(secrets, copied, exclude_names={"migration-passphrase"})
    assert not (copied / "migration-passphrase").exists()
    assert (copied / "runtime-key").read_text(encoding="utf-8") == "include"


def test_verify_parser_accepts_stack_wrapper_repo_root() -> None:
    args = build_parser().parse_args(
        ["verify", "--repo-root", "/srv/geo", "--package", "/srv/package", "--encryption-key-file", "/srv/key"]
    )
    assert args.command == "verify"
    assert args.repo_root == "/srv/geo"


def test_host_archive_allows_internal_symlinks_but_rejects_escape(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "target.txt").write_text("inside", encoding="utf-8")
    (source / "alias.txt").symlink_to("target.txt")
    archive = tmp_path / "safe.tar.gz"
    _host_tar(source, archive)
    with tarfile.open(archive, "r:gz") as payload:
        names = {member.name for member in payload.getmembers()}
    assert "alias.txt" in names

    (source / "python").symlink_to("/usr/bin/python3.12")
    runtime_archive = tmp_path / "runtime.tar.gz"
    _host_tar(source, runtime_archive)
    restored = tmp_path / "restored"
    from scripts.geo_migrate import _extract_archive_to_directory

    _extract_archive_to_directory(runtime_archive, restored)
    assert (restored / "python").is_symlink()
    assert (restored / "python").readlink() == Path("/usr/bin/python3.12")

    (source / "escape.txt").symlink_to("/etc/passwd")
    with pytest.raises(MigrationError, match="unsafe symlink"):
        _host_tar(source, tmp_path / "unsafe.tar.gz")
