from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile

import pytest

import scripts.geo_migrate as geo_migrate
from scripts.geo_migrate import (
    MigrationError,
    _assert_identity_bindings,
    _copy_regular_tree,
    _extract_archive_to_directory,
    _extract_safe,
    _files,
    _host_tar,
    _identity_binding_manifest,
    _identity_values,
    _manifest_identity_bindings,
    _restore_host_archive,
    _verify_payload,
    build_parser,
)


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


def test_extract_safe_accepts_standard_dot_root_member(tmp_path: Path) -> None:
    archive = tmp_path / "payload.tar"
    with tarfile.open(archive, "w") as handle:
        root = tarfile.TarInfo("./")
        root.type = tarfile.DIRTYPE
        handle.addfile(root)
        content = b"ok"
        item = tarfile.TarInfo("./payload.txt")
        item.size = len(content)
        handle.addfile(item, __import__("io").BytesIO(content))

    destination = tmp_path / "out"
    destination.mkdir()
    _extract_safe(archive, destination)

    assert (destination / "payload.txt").read_bytes() == b"ok"


@pytest.mark.parametrize("member_kind", ["symlink", "hardlink", "fifo"])
def test_extract_safe_rejects_links_and_special_members(
    tmp_path: Path, member_kind: str
) -> None:
    archive = tmp_path / f"{member_kind}.tar"
    with tarfile.open(archive, "w") as handle:
        member = tarfile.TarInfo("escape")
        if member_kind == "symlink":
            member.type = tarfile.SYMTYPE
            member.linkname = "../../outside"
        elif member_kind == "hardlink":
            member.type = tarfile.LNKTYPE
            member.linkname = "target"
        else:
            member.type = tarfile.FIFOTYPE
        handle.addfile(member)

    with pytest.raises(MigrationError, match="(symlink|hardlink|unsupported)"):
        _extract_safe(archive, tmp_path / "out")


def test_restore_host_archive_uses_root_docker_helper_and_limits_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "app-storage.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        content = b"dify"
        item = tarfile.TarInfo("data.txt")
        item.size = len(content)
        handle.addfile(item, __import__("io").BytesIO(content))
    allowed_root = tmp_path / "runtime" / "docker" / "volumes"
    destination = allowed_root / "app" / "storage"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> bytes:
        calls.append(command)
        return b""

    monkeypatch.setattr(geo_migrate, "_run", fake_run)
    _restore_host_archive(
        archive,
        destination,
        allowed_root=allowed_root,
        clear=True,
    )

    command = calls[0]
    assert command[:4] == ["docker", "run", "--rm", "--network"]
    assert ["--user", "0:0"] == command[command.index("--user") : command.index("--user") + 2]
    assert command[command.index("--network") + 1] == "none"
    assert f"{destination.resolve()}:/target" in command
    assert f"{archive.parent.resolve()}:/source:ro" in command
    assert command[-1] == archive.name
    helper_script = command[command.index("-ceu") + 1]
    assert helper_script.startswith("set -eu;")
    assert "set -ceu" not in helper_script
    assert '"/source/$2"' in helper_script
    assert archive.name not in helper_script

    with pytest.raises(MigrationError, match="escapes its allowed root"):
        _restore_host_archive(
            archive,
            tmp_path / "outside",
            allowed_root=allowed_root,
            clear=True,
        )


def test_restore_host_archive_rejects_helper_archive_name_injection(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive;touch-marker.tar.gz"
    archive.write_bytes(b"not a tar")
    allowed_root = tmp_path / "runtime" / "docker" / "volumes"

    with pytest.raises(MigrationError, match="archive name is unsafe"):
        _restore_host_archive(
            archive,
            allowed_root / "app" / "storage",
            allowed_root=allowed_root,
            clear=True,
        )


def test_restore_host_archive_surfaces_docker_helper_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "app-storage.tar.gz"
    archive.write_bytes(b"placeholder")
    allowed_root = tmp_path / "runtime" / "docker" / "volumes"

    def failed_run(command: list[str], **_: object) -> bytes:
        assert command[:2] == ["docker", "run"]
        raise MigrationError("command failed (docker): helper unavailable")

    monkeypatch.setattr(geo_migrate, "_run", failed_run)
    with pytest.raises(MigrationError, match="helper unavailable"):
        _restore_host_archive(
            archive,
            allowed_root / "app" / "storage",
            allowed_root=allowed_root,
            clear=True,
        )


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


def test_verification_receipt_binds_manifest_payload_and_identity(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "schema_version": "geo-runtime-migration-v2",
        "status": "verified-export",
        "payload": {"sha256": "a" * 64},
    }
    identity = {"schema_version": "geo-runtime-identity-bindings-v1", "bindings": {}}
    manifest_path.write_bytes(geo_migrate._canonical_json(manifest))

    receipt_path = geo_migrate._write_verification_receipt(
        tmp_path,
        manifest,
        identity,
        [{"path": "geo/postgres.dump", "sha256": "b" * 64}],
    )

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == geo_migrate.VERIFY_RECEIPT_SCHEMA
    assert receipt["status"] == "verified-package"
    assert receipt["manifest_sha256"] == geo_migrate._sha256(manifest_path)
    assert receipt["payload_sha256"] == "a" * 64
    assert receipt["identity_bindings_sha256"] == hashlib.sha256(
        geo_migrate._canonical_json(identity)
    ).hexdigest()


def test_encryption_key_can_be_excluded_from_secret_payload(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "migration-passphrase").write_text("keep-out", encoding="utf-8")
    (secrets / "runtime-key").write_text("include", encoding="utf-8")
    (secrets / "migration-passphrase").chmod(0o600)
    (secrets / "runtime-key").chmod(0o600)
    copied = tmp_path / "copied"
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
    (source / "python3").symlink_to("python")
    runtime_archive = tmp_path / "runtime.tar.gz"
    _host_tar(source, runtime_archive)
    restored = tmp_path / "restored"
    _extract_archive_to_directory(runtime_archive, restored)
    assert (restored / "python").is_symlink()
    assert (restored / "python").readlink() == Path("/usr/bin/python3.12")
    assert (restored / "python3").is_symlink()

    (source / "escape.txt").symlink_to("/etc/passwd")
    with pytest.raises(MigrationError, match="unsafe symlink"):
        _host_tar(source, tmp_path / "unsafe.tar.gz")


IDENTITIES = {
    "GEO_ADMIN_ACTOR_ID": "30000000-0000-4000-8000-000000000003",
    "GEO_ADMIN_TENANT_ID": "10000000-0000-4000-8000-000000000001",
    "GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID": "40000000-0000-4000-8000-000000000006",
    "GEO_CONNECTOR_SERVICE_IDENTITY_ID": "40000000-0000-4000-8000-000000000004",
    "GEO_BROWSER_CAPTURE_SERVICE_IDENTITY_ID": "40000000-0000-4000-8000-000000000005",
}


def _database_bindings() -> dict[str, object]:
    return {
        "admin_actor": {
            "identity_id": IDENTITIES["GEO_ADMIN_ACTOR_ID"],
            "status": "active",
            "tenant_membership": True,
        },
        "admin_tenant": {
            "tenant_id": IDENTITIES["GEO_ADMIN_TENANT_ID"],
            "status": "active",
        },
        "services": {
            "model_gateway_worker": {
                "identity_id": IDENTITIES["GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID"],
                "service_status": "active",
                "identity_status": "active",
                "issuer": "geo.service",
                "subject": "model_gateway_worker",
            },
            "connector_worker": {
                "identity_id": IDENTITIES["GEO_CONNECTOR_SERVICE_IDENTITY_ID"],
                "service_status": "active",
                "identity_status": "active",
                "issuer": "geo.service",
                "subject": "connector_worker",
            },
            "browser_capture_worker": {
                "identity_id": IDENTITIES["GEO_BROWSER_CAPTURE_SERVICE_IDENTITY_ID"],
                "service_status": "active",
                "identity_status": "active",
                "issuer": "geo.service",
                "subject": "browser_capture_worker",
            },
        },
    }


def test_identity_bindings_are_normalized_from_a_data_only_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / "geo-stack.env"
    env_file.write_text(
        "\n".join(
            [
                "# comments and unrelated secrets are ignored",
                "GEO_ADMIN_ACTOR_ID='30000000-0000-4000-8000-000000000003'",
                "GEO_ADMIN_TENANT_ID=10000000-0000-4000-8000-000000000001",
                "GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID=40000000-0000-4000-8000-000000000006",
                "GEO_CONNECTOR_SERVICE_IDENTITY_ID=40000000-0000-4000-8000-000000000004",
                "GEO_BROWSER_CAPTURE_SERVICE_IDENTITY_ID=40000000-0000-4000-8000-000000000005",
                "GEO_AUTH_TOKEN_SECRET=must-not-be-read",
            ]
        ),
        encoding="utf-8",
    )

    values = _identity_values(env_file=env_file, role="source")

    assert values == IDENTITIES


def test_identity_bindings_fail_when_one_binding_is_missing(tmp_path: Path) -> None:
    env_file = tmp_path / "geo-stack.env"
    env_file.write_text(
        "GEO_ADMIN_ACTOR_ID=30000000-0000-4000-8000-000000000003\n",
        encoding="utf-8",
    )

    with pytest.raises(MigrationError, match="GEO_ADMIN_TENANT_ID"):
        _identity_values(env_file=env_file, role="target")


def test_identity_bindings_require_active_database_rows() -> None:
    values = dict(IDENTITIES)
    database = _database_bindings()
    _assert_identity_bindings(values, database, role="target")

    services = database["services"]
    assert isinstance(services, dict)
    connector = services["connector_worker"]
    assert isinstance(connector, dict)
    connector["identity_id"] = IDENTITIES["GEO_BROWSER_CAPTURE_SERVICE_IDENTITY_ID"]
    with pytest.raises(MigrationError, match="connector_worker"):
        _assert_identity_bindings(values, database, role="target")


def test_identity_manifest_round_trip_contains_only_binding_metadata() -> None:
    manifest = _identity_binding_manifest(IDENTITIES, _database_bindings())
    assert manifest["schema_version"] == "geo-runtime-identity-bindings-v1"
    assert manifest["bindings"]["connector_worker"]["env_name"] == "GEO_CONNECTOR_SERVICE_IDENTITY_ID"
    encoded = json.dumps(manifest, sort_keys=True)
    assert "must-not-be-read" not in encoded
    assert "email" not in encoded


def test_old_manifest_without_identity_bindings_is_not_restore_eligible() -> None:
    with pytest.raises(MigrationError, match="no identity bindings"):
        _manifest_identity_bindings(
            {"schema_version": "geo-runtime-migration-v2", "status": "verified-export"}
        )
