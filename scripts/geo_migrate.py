#!/usr/bin/env python3
"""Export and restore the canonical GEO + Dify runtime.

The migration package is deliberately operator-facing.  It contains logical
PostgreSQL dumps and quiesced stateful-volume snapshots, while credentials and
keyrings are included only inside an encrypted payload.  The sidecar manifest
never contains secret values.  The v2 format also captures Dify's local
application and plugin storage, which is otherwise easy to miss when moving a
self-hosted Dify instance.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Iterable
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infra.db.alembic.checksums import sql_hashes


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "geo-runtime-migration-v2"
LEGACY_SCHEMA = "geo-runtime-migration-v1"
VERIFY_RECEIPT_SCHEMA = "geo-runtime-migration-verification-receipt-v1"
DEFAULT_SOURCE_PROJECT = "geo-advinsys-staging-v2"
DEFAULT_TARGET_PROJECT = "geo"
DEFAULT_DIFY_PROJECT = "geo-dify"
_DIFY_STATE_NAME = "geo-dify-state.json"
_MIGRATION_SECRET_NAMES = frozenset(
    {
        "staging-project-backup-passphrase",
        "migration-passphrase",
        "geo-migration-passphrase",
    }
)

_DIFY_PERSISTENT_DIRECTORIES = (
    ("app-storage", "app/storage"),
    ("plugin-daemon", "plugin_daemon"),
)
_SAFE_RUNTIME_ABSOLUTE_SYMLINKS = frozenset({"/usr/bin/python3", "/usr/bin/python3.12"})

_IDENTITY_BINDING_FIELDS = {
    "admin_actor": "GEO_ADMIN_ACTOR_ID",
    "admin_tenant": "GEO_ADMIN_TENANT_ID",
    "model_gateway_worker": "GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID",
    "connector_worker": "GEO_CONNECTOR_SERVICE_IDENTITY_ID",
    "browser_capture_worker": "GEO_BROWSER_CAPTURE_SERVICE_IDENTITY_ID",
}
_SERVICE_IDENTITY_NAMES = {
    "model_gateway_worker": "model_gateway_worker",
    "connector_worker": "connector_worker",
    "browser_capture_worker": "browser_capture_worker",
}


class MigrationError(RuntimeError):
    """A safe, actionable migration failure."""


def _run(command: list[str], *, stdout=None, input_bytes: bytes | None = None) -> bytes:
    try:
        completed = subprocess.run(
            command,
            check=True,
            stdout=stdout if stdout is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            input=input_bytes,
        )
    except FileNotFoundError as error:
        raise MigrationError(f"required command is unavailable: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        safe_detail = detail[-600:] if detail else "no command detail"
        raise MigrationError(f"command failed ({command[0]}): {safe_detail}") from error
    return completed.stdout if completed.stdout is not None else b""


def _docker(*args: str, stdout=None) -> bytes:
    return _run(["docker", *args], stdout=stdout)


def _secure_file(path: Path, *, minimum_size: int = 1) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise MigrationError(f"required file is missing: {path}") from error
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise MigrationError(f"migration input must be a regular file: {path}")
    if stat.S_IMODE(metadata.st_mode) not in {0o600, 0o640, 0o644}:
        raise MigrationError(f"migration input has unsafe permissions: {path}")
    if metadata.st_size < minimum_size:
        raise MigrationError(f"migration input is empty: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _resolve_container(project: str, service: str) -> str:
    output = _docker(
        "ps",
        "-aq",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--filter",
        f"label=com.docker.compose.service={service}",
    ).decode("ascii", errors="ignore").splitlines()
    if not output:
        raise MigrationError(
            f"container is unavailable: project={project} service={service}; "
            "start the canonical stack or pass the correct project name"
        )
    if len(output) > 1:
        raise MigrationError(f"multiple containers found for {project}/{service}")
    return output[0].strip()


def _container_name(project: str, service: str) -> str:
    return _resolve_container(project, service)


def _service_containers(project: str) -> list[tuple[str, str]]:
    ids = _docker(
        "ps",
        "-aq",
        "--filter",
        f"label=com.docker.compose.project={project}",
    ).decode("ascii", errors="ignore").splitlines()
    services: list[tuple[str, str]] = []
    for container in ids:
        service = _docker(
            "inspect", "--format", "{{index .Config.Labels \"com.docker.compose.service\"}}", container
        ).decode("utf-8", errors="replace").strip()
        if service:
            services.append((service, container))
    return services


def _running(container: str) -> bool:
    return _docker("inspect", "--format", "{{.State.Running}}", container).decode().strip() == "true"


def _quiesce(projects: Iterable[str]) -> list[str]:
    stopped: list[str] = []
    stateful = {
        "postgres",
        "minio",
        "valkey",
        "db_postgres",
        "redis",
        "weaviate",
    }
    for project in projects:
        for service, container in _service_containers(project):
            if service in stateful or not _running(container):
                continue
            _docker("stop", container)
            stopped.append(container)
    return stopped


def _restart(containers: Iterable[str]) -> None:
    for container in reversed(list(containers)):
        _docker("start", container)


def _refresh_dify_gateway(project: str) -> None:
    gateway = _resolve_container(project, "nginx")
    if _running(gateway):
        _docker("restart", gateway)


def _docker_tar(container: str, source: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("wb") as output:
            _docker("exec", container, "tar", "-C", source, "-czf", "-", ".", stdout=output)
        return
    except MigrationError:
        # The MinIO image is intentionally minimal and has no tar binary.  A
        # host-side copy is slower but remains portable across image updates.
        with tempfile.TemporaryDirectory(prefix="geo-migration-copy-") as temporary:
            copied = Path(temporary) / "data"
            copied.mkdir()
            _docker("cp", f"{container}:{source}/.", str(copied))
            with tarfile.open(destination, "w:gz") as archive:
                for item in sorted(copied.rglob("*")):
                    if item.is_symlink() or not (item.is_file() or item.is_dir()):
                        raise MigrationError(f"state archive contains an unsupported path: {item}")
                    archive.add(item, arcname=item.relative_to(copied).as_posix(), recursive=False)


def _host_tar(source: Path, destination: Path) -> None:
    """Archive a bind-mounted runtime directory without following links."""

    if not source.is_dir() or source.is_symlink():
        raise MigrationError(f"persistent directory is unavailable: {source}")
    root = source.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        for item in sorted(source.rglob("*")):
            if item.is_symlink():
                link_name = os.readlink(item)
                link_target = (item.parent / link_name).resolve(strict=False)
                target_is_safe_system_link = link_target.as_posix() in _SAFE_RUNTIME_ABSOLUTE_SYMLINKS
                target_is_internal = link_target == root or root in link_target.parents
                if not target_is_safe_system_link and not target_is_internal:
                    raise MigrationError(f"persistent directory contains an unsafe symlink: {item}")
                archive.add(item, arcname=item.relative_to(source).as_posix(), recursive=False)
                continue
            if not (item.is_file() or item.is_dir()):
                raise MigrationError(f"persistent directory contains an unsupported path: {item}")
            archive.add(item, arcname=item.relative_to(source).as_posix(), recursive=False)


def _git_metadata(repo_root: Path, *, allow_dirty: bool) -> dict[str, object]:
    """Bind a package to the exact source code used to produce it."""

    try:
        commit = _run(["git", "-C", str(repo_root), "rev-parse", "HEAD"]).decode().strip()
        status = _run(["git", "-C", str(repo_root), "status", "--porcelain"]).decode()
    except MigrationError as error:
        raise MigrationError(f"source repository metadata is unavailable: {error}") from error
    if not commit or len(commit) != 40:
        raise MigrationError("source repository HEAD is not a full commit")
    if status and not allow_dirty:
        raise MigrationError(
            "source repository has uncommitted changes; commit the running code before export "
            "or explicitly pass --allow-dirty for a non-reproducible package"
        )
    return {"commit": commit, "dirty": bool(status)}


def _docker_copy(container: str, source: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _docker("cp", f"{container}:{source}", str(destination))


def _dump_postgres(container: str, database: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        _docker(
            "exec",
            container,
            "pg_dump",
            "-U",
            "postgres" if database in {"dify", "dify_plugin"} else "geo_installer",
            "-d",
            database,
            "-Fc",
            "--no-owner",
            "--no-privileges",
            stdout=output,
        )


def _dump_rdb(container: str, cli: str, destination: Path) -> None:
    remote = "/tmp/geo-migration-dump.rdb"
    _docker("exec", container, cli, "--rdb", remote)
    _docker_copy(container, remote, destination)
    _docker("exec", container, "rm", "-f", remote)


def _mount(container: str, destination: str) -> tuple[str, str, str]:
    output = _docker(
        "inspect",
        "--format",
        "{{range .Mounts}}{{if eq .Destination \"%s\"}}{{.Type}}|{{.Name}}|{{.Source}}{{end}}{{end}}" % destination,
        container,
    ).decode("utf-8", errors="replace").strip()
    if not output or output.count("|") != 2:
        raise MigrationError(f"stateful mount is unavailable: {container}:{destination}")
    return tuple(output.split("|", 2))  # type: ignore[return-value]


def _clear_directory(path: Path) -> None:
    if not path.is_dir() or path == Path("/") or len(path.parts) < 3:
        raise MigrationError(f"refusing to clear unsafe directory: {path}")
    for child in path.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)


def _restore_archive_to_mount(container: str, destination: str, archive: Path, *, clear: bool) -> None:
    mount_type, mount_name, mount_source = _mount(container, destination)
    if mount_type == "bind":
        target = Path(mount_source).resolve()
        if clear:
            _clear_directory(target)
        _extract_archive_to_directory(archive, target)
        return
    if mount_type != "volume" or not mount_name:
        raise MigrationError(f"unsupported mount type for {container}:{destination}: {mount_type}")
    _run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{mount_name}:/target",
            "-v",
            f"{archive.parent}:/source:ro",
            "busybox:1.36",
            "sh",
            "-ceu",
            "if [ \"$1\" = clear ]; then find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; fi; tar -xf /source/$(basename \"$2\") -C /target",
            "sh",
            "clear" if clear else "keep",
            archive.name,
        ]
    )


def _restore_host_archive(
    archive: Path,
    destination: Path,
    *,
    allowed_root: Path,
    clear: bool,
) -> None:
    """Restore a root-owned Dify bind mount through an audited Docker helper.

    The operator running the migration need not have permission to remove the
    existing bind-mounted files.  Docker performs the write as root inside a
    pinned, network-isolated helper container.  Only the two fixed Dify
    persistent roots pass ``allowed_root``; no user-controlled destination is
    interpolated into the helper shell.
    """

    archive = archive.resolve()
    if archive.is_symlink() or not archive.is_file():
        raise MigrationError(f"Dify restore archive is not a regular file: {archive}")
    if not archive.name or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in archive.name
    ):
        raise MigrationError(f"Dify restore archive name is unsafe: {archive.name!r}")
    root = allowed_root.resolve()
    target = destination.resolve(strict=False)
    if root == Path("/") or len(root.parts) < 3:
        raise MigrationError(f"refusing to use an unsafe Dify restore root: {root}")
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise MigrationError(
            f"Dify restore destination escapes its allowed root: {destination}"
        ) from error
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise MigrationError(f"Dify restore destination is unsafe: {destination}")
    if destination.exists() and destination.is_symlink():
        raise MigrationError(f"Dify restore destination must not be a symlink: {destination}")

    helper_script = (
        "set -eu; "
        "case \"$1\" in clear) find /target -mindepth 1 -maxdepth 1 "
        "-exec rm -rf -- {} + ;; keep) ;; *) exit 64 ;; esac; "
        "case \"$2\" in ''|*/*|*\\\\*) exit 64 ;; esac; "
        "test -f \"/source/$2\"; tar -xzf \"/source/$2\" -C /target"
    )
    _run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0:0",
            "-v",
            f"{target}:/target",
            "-v",
            f"{archive.parent}:/source:ro",
            "busybox:1.36",
            "sh",
            "-ceu",
            helper_script,
            "geo-migrate-restore",
            "clear" if clear else "keep",
            archive.name,
        ]
    )


def _restore_file_to_mount(container: str, destination: str, source: Path, *, clear: bool) -> None:
    mount_type, mount_name, mount_source = _mount(container, destination)
    if mount_type == "bind":
        target = Path(mount_source).resolve()
        if clear:
            _clear_directory(target)
        shutil.copy2(source, target / "dump.rdb")
        return
    if mount_type != "volume" or not mount_name:
        raise MigrationError(f"unsupported mount type for {container}:{destination}: {mount_type}")
    _run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{mount_name}:/target",
            "-v",
            f"{source.parent}:/source:ro",
            "busybox:1.36",
            "sh",
            "-ceu",
            "if [ \"$1\" = clear ]; then find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; fi; cp /source/$(basename \"$2\") /target/dump.rdb",
            "sh",
            "clear" if clear else "keep",
            source.name,
        ]
    )


def _copy_regular_tree(
    source: Path, destination: Path, *, exclude_names: set[str] | None = None
) -> None:
    if not source.is_dir() or source.is_symlink():
        raise MigrationError(f"secret/runtime root is not a directory: {source}")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for item in source.iterdir():
        if item.is_symlink() or not item.is_file():
            continue
        if exclude_names and item.name in exclude_names:
            continue
        _secure_file(item)
        shutil.copy2(item, destination / item.name)
        os.chmod(destination / item.name, 0o600)


def _files(root: Path, *, exclude: set[str] | None = None) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if exclude and path.relative_to(root).as_posix() in exclude:
            continue
        result.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return result


def _verify_payload(root: Path, entries: list[dict[str, object]]) -> None:
    expected = {str(item["path"]): str(item["sha256"]) for item in entries}
    actual = {
        str(item["path"]): str(item["sha256"])
        for item in _files(root, exclude={"payload-manifest.json"})
    }
    if actual != expected:
        missing = sorted(set(expected.keys()) - set(actual.keys()))
        extra = sorted(set(actual.keys()) - set(expected.keys()))
        raise MigrationError(f"payload hash mismatch; missing={missing[:3]} extra={extra[:3]}")


def _encrypt(payload: Path, destination: Path, key_file: Path) -> None:
    _secure_file(key_file)
    _run(
        [
            "gpg",
            "--batch",
            "--yes",
            "--pinentry-mode",
            "loopback",
            "--passphrase-file",
            str(key_file),
            "--symmetric",
            "--cipher-algo",
            "AES256",
            "--s2k-cipher-algo",
            "AES256",
            "--s2k-digest-algo",
            "SHA512",
            "--s2k-count",
            "65011712",
            "--compress-algo",
            "none",
            "--output",
            str(destination),
            str(payload),
        ]
    )
    os.chmod(destination, 0o600)


def _decrypt(source: Path, destination: Path, key_file: Path) -> None:
    _secure_file(key_file)
    _run(
        [
            "gpg",
            "--batch",
            "--yes",
            "--pinentry-mode",
            "loopback",
            "--passphrase-file",
            str(key_file),
            "--decrypt",
            "--output",
            str(destination),
            str(source),
        ]
    )


def _validate_archive_member(
    member: tarfile.TarInfo,
    *,
    allow_symlink: bool,
    description: str,
) -> None:
    """Validate tar metadata before any filesystem operation is attempted."""

    # Tar archives conventionally contain a directory entry named ``./`` for
    # their root.  It is harmless and must be accepted, while every other
    # member still has to be a relative path without parent traversal.
    name = member.name
    if name not in {"", ".", "./"}:
        normalized = Path(name)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise MigrationError(f"unsafe archive member ({description}): {name}")
    if member.islnk():
        raise MigrationError(f"unsafe {description} hardlink: {name}")
    if member.issym():
        if not allow_symlink:
            raise MigrationError(f"unsafe {description} symlink: {name}")
        return
    if not (member.isdir() or member.isreg()):
        raise MigrationError(f"unsupported {description} archive member: {name}")


def _extract_safe(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r") as payload:
        for member in payload.getmembers():
            _validate_archive_member(member, allow_symlink=False, description="payload")
            target = (destination / member.name).resolve()
            if target != destination.resolve() and destination.resolve() not in target.parents:
                raise MigrationError(f"unsafe archive member: {member.name}")

        def safe_filter(member: tarfile.TarInfo, path: str) -> tarfile.TarInfo:
            _validate_archive_member(member, allow_symlink=False, description="payload")
            return tarfile.data_filter(member, path)

        payload.extractall(destination, filter=safe_filter)


def _extract_archive_to_directory(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(archive, "r") as payload:
        for member in payload.getmembers():
            _validate_archive_member(member, allow_symlink=True, description="state")
            target = (destination / member.name).resolve()
            if member.issym():
                link_target = (destination / member.name).parent / member.linkname
                if link_target.resolve(strict=False).as_posix() in _SAFE_RUNTIME_ABSOLUTE_SYMLINKS:
                    continue
            if target != destination and destination not in target.parents:
                raise MigrationError(f"unsafe state archive member: {member.name}")

        def safe_filter(member: tarfile.TarInfo, path: str) -> tarfile.TarInfo:
            _validate_archive_member(member, allow_symlink=True, description="state")
            if member.issym():
                link_target = (Path(path) / member.name).parent / member.linkname
                if link_target.resolve(strict=False).as_posix() in _SAFE_RUNTIME_ABSOLUTE_SYMLINKS:
                    return member
            if member.issym() and os.path.isabs(member.linkname):
                if member.linkname not in _SAFE_RUNTIME_ABSOLUTE_SYMLINKS:
                    raise MigrationError(f"unsafe state archive symlink: {member.name}")
            return tarfile.data_filter(member, path)

        payload.extractall(destination, filter=safe_filter)


def _copy_runtime_inputs(args: argparse.Namespace, payload: Path) -> list[str]:
    secret_root = Path(args.secret_root).resolve()
    encryption_key = Path(args.encryption_key_file).resolve()
    excluded = set(_MIGRATION_SECRET_NAMES)
    if encryption_key.parent == secret_root:
        excluded.add(encryption_key.name)
    _copy_regular_tree(secret_root, payload / "secrets", exclude_names=excluded)
    runtime_root = Path(args.dify_runtime_root).resolve()
    dify_env = runtime_root / "docker" / ".env"
    _secure_file(dify_env)
    (payload / "dify").mkdir(parents=True, exist_ok=True)
    shutil.copy2(dify_env, payload / "dify" / "dify.env")
    os.chmod(payload / "dify" / "dify.env", 0o600)
    state = Path(args.dify_state_file).resolve()
    _secure_file(state)
    (payload / "dify").mkdir(parents=True, exist_ok=True)
    shutil.copy2(state, payload / "dify" / _DIFY_STATE_NAME)
    os.chmod(payload / "dify" / _DIFY_STATE_NAME, 0o600)
    volumes_root = runtime_root / "docker" / "volumes"
    for archive_name, relative_root in _DIFY_PERSISTENT_DIRECTORIES:
        _host_tar(
            volumes_root / relative_root,
            payload / "dify" / f"{archive_name}.tar.gz",
        )
    return sorted(excluded)


def export_package(args: argparse.Namespace) -> Path:
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    package = output_root / f"geo-runtime-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    if package.exists():
        raise MigrationError(f"migration package already exists: {package}")
    package.mkdir(mode=0o700)
    archive_id = package.name
    payload_root = package / "payload"
    payload_root.mkdir(mode=0o700)
    stopped: list[str] = []
    try:
        git_metadata = _git_metadata(Path(args.repo_root).resolve(), allow_dirty=args.allow_dirty)
        geo_pg = _resolve_container(args.source_project, "postgres")
        geo_minio = _resolve_container(args.source_project, "minio")
        geo_valkey = _resolve_container(args.source_project, "valkey")
        dify_pg = _resolve_container(args.dify_project, "db_postgres")
        dify_redis = _resolve_container(args.dify_project, "redis")
        dify_weaviate = _resolve_container(args.dify_project, "weaviate")
        source_identity_values = _identity_values(
            env_file=getattr(args, "source_env_file", None), role="source"
        )
        source_identity_database = _query_identity_bindings(geo_pg, source_identity_values)
        _assert_identity_bindings(source_identity_values, source_identity_database, role="source")
        identity_bindings = _identity_binding_manifest(
            source_identity_values, source_identity_database
        )
        if args.quiesce:
            stopped = _quiesce([args.source_project, args.dify_project])
        _dump_postgres(geo_pg, "geo", payload_root / "geo" / "postgres.dump")
        _dump_postgres(dify_pg, "dify", payload_root / "dify" / "postgres-dify.dump")
        _dump_postgres(dify_pg, "dify_plugin", payload_root / "dify" / "postgres-dify_plugin.dump")
        _dump_rdb(geo_valkey, "valkey-cli", payload_root / "geo" / "valkey.rdb")
        _dump_rdb(dify_redis, "redis-cli", payload_root / "dify" / "redis.rdb")
        _docker_tar(geo_minio, "/data", payload_root / "geo" / "minio-data.tar.gz")
        _docker_tar(dify_weaviate, "/var/lib/weaviate", payload_root / "dify" / "weaviate-data.tar.gz")
        excluded_secret_files = _copy_runtime_inputs(args, payload_root)
        entries = _files(payload_root, exclude={"payload-manifest.json"})
        payload_manifest = {
            "schema_version": SCHEMA,
            "source_project": args.source_project,
            "dify_project": args.dify_project,
            "kind": "baseline",
            "archive_id": archive_id,
            "source_environment": args.source_environment,
            "source_role": args.source_role,
            "source_git": git_metadata,
            "identity_bindings": identity_bindings,
            "created_at": datetime.now(UTC).isoformat(),
            "quiesced": bool(args.quiesce),
            "excluded_secret_files": excluded_secret_files,
            "files": entries,
        }
        payload_json = payload_root / "payload-manifest.json"
        payload_json.write_bytes(_canonical_json(payload_manifest))
        os.chmod(payload_json, 0o600)
        entries = _files(payload_root, exclude={"payload-manifest.json"})
        payload_manifest["files"] = entries
        payload_json.write_bytes(_canonical_json(payload_manifest))
        with tempfile.TemporaryDirectory(prefix="geo-migration-") as temp:
            tar_path = Path(temp) / "payload.tar.gz"
            with tarfile.open(tar_path, "w:gz") as archive:
                for item in sorted(payload_root.rglob("*")):
                    if item.is_file():
                        archive.add(item, arcname=item.relative_to(payload_root).as_posix(), recursive=False)
            encrypted = package / "payload.tar.gz.gpg"
            _encrypt(tar_path, encrypted, Path(args.encryption_key_file).resolve())
        shutil.rmtree(payload_root)
        manifest = {
            "schema_version": SCHEMA,
            "status": "verified-export",
            "created_at": payload_manifest["created_at"],
            "source_project": args.source_project,
            "dify_project": args.dify_project,
            "kind": "baseline",
            "archive_id": archive_id,
            "source_environment": args.source_environment,
            "source_role": args.source_role,
            "source_git": git_metadata,
            "identity_bindings": identity_bindings,
            "excluded_secret_files": excluded_secret_files,
            "source_containers": {
                "geo_postgres": geo_pg,
                "geo_minio": geo_minio,
                "geo_valkey": geo_valkey,
                "dify_postgres": dify_pg,
                "dify_redis": dify_redis,
                "dify_weaviate": dify_weaviate,
            },
            "quiesced": bool(args.quiesce),
            "payload": {
                "path": "payload.tar.gz.gpg",
                "size_bytes": (package / "payload.tar.gz.gpg").stat().st_size,
                "sha256": _sha256(package / "payload.tar.gz.gpg"),
                "encryption": "OpenPGP symmetric AES256",
            },
            "entries": entries,
        }
        (package / "manifest.json").write_bytes(_canonical_json(manifest))
        os.chmod(package / "manifest.json", 0o600)
        print(package / "manifest.json")
        return package / "manifest.json"
    except Exception:
        shutil.rmtree(package, ignore_errors=True)
        raise
    finally:
        if stopped:
            _restart(stopped)
            _refresh_dify_gateway(args.dify_project)


def _read_manifest(package: Path) -> dict[str, object]:
    manifest_path = package / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MigrationError(f"migration manifest is unreadable: {manifest_path}") from error
    if manifest.get("schema_version") not in {SCHEMA, LEGACY_SCHEMA} or manifest.get("status") != "verified-export":
        raise MigrationError("unsupported or unverified migration manifest")
    payload = manifest.get("payload")
    if not isinstance(payload, dict) or payload.get("path") not in {"payload.tar.gz.gpg", "payload.tar.gpg"}:
        raise MigrationError("migration payload metadata is invalid")
    encrypted = package / str(payload["path"])
    if _sha256(encrypted) != payload.get("sha256") or encrypted.stat().st_size != payload.get("size_bytes"):
        raise MigrationError("migration payload checksum does not match manifest")
    return manifest


def _payload_path(package: Path, manifest: dict[str, object]) -> Path:
    payload = manifest.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("path"), str):
        raise MigrationError("migration payload metadata is invalid")
    return package / str(payload["path"])


def _manifest_identity_bindings(manifest: dict[str, object]) -> dict[str, object]:
    value = manifest.get("identity_bindings")
    if not isinstance(value, dict) or value.get("schema_version") != "geo-runtime-identity-bindings-v1":
        raise MigrationError(
            "migration manifest has no identity bindings; re-export with the current geo_migrate.py"
        )
    bindings = value.get("bindings")
    database = value.get("database")
    if not isinstance(bindings, dict) or not isinstance(database, dict):
        raise MigrationError("migration identity bindings are malformed")
    for name, env_name in _IDENTITY_BINDING_FIELDS.items():
        row = bindings.get(name)
        if not isinstance(row, dict) or row.get("env_name") != env_name:
            raise MigrationError(f"migration identity binding {name} is malformed")
        try:
            parsed = UUID(str(row.get("identity_id", "")))
        except ValueError as error:
            raise MigrationError(f"migration identity binding {name} is not a UUID") from error
        if parsed.int == 0:
            raise MigrationError(f"migration identity binding {name} cannot be the nil UUID")
    return value


def _identity_values_from_manifest(bindings: dict[str, object]) -> dict[str, str]:
    rows = bindings.get("bindings")
    if not isinstance(rows, dict):
        raise MigrationError("migration identity bindings are malformed")
    values: dict[str, str] = {}
    for name, env_name in _IDENTITY_BINDING_FIELDS.items():
        row = rows.get(name)
        if not isinstance(row, dict):
            raise MigrationError(f"migration identity binding {name} is malformed")
        values[env_name] = str(row["identity_id"])
    return values


def _restore_pg(container: str, database: str, dump: Path) -> None:
    user = "postgres" if database in {"dify", "dify_plugin"} else "geo_installer"
    if database in {"dify", "dify_plugin"}:
        _docker("exec", container, "dropdb", "-U", "postgres", "--if-exists", database)
        _docker("exec", container, "createdb", "-U", "postgres", database)
    with dump.open("rb") as source:
        _run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "pg_restore",
                "-U",
                user,
                "-d",
                database,
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
            ],
            input_bytes=source.read(),
        )


def _validate_custom_dump(container: str, dump: Path) -> None:
    remote = "/tmp/geo-migration-check.dump"
    _docker("cp", str(dump), f"{container}:{remote}")
    try:
        _docker("exec", container, "pg_restore", "--list", remote)
    finally:
        _docker("exec", container, "rm", "-f", remote)


def _current_alembic_script() -> ScriptDirectory:
    configuration = Config(str(ROOT / "alembic.ini"))
    return ScriptDirectory.from_config(configuration)


def _current_alembic_head() -> str:
    heads = _current_alembic_script().get_heads()
    if len(heads) != 1:
        raise MigrationError(
            "current repository must expose exactly one Alembic head; "
            f"found {', '.join(sorted(heads)) or 'none'}"
        )
    return str(heads[0])


def _verify_checksum_ledger(container: str, database: str, *, head: str) -> dict[str, object]:
    user = "postgres" if database in {"dify", "dify_plugin"} else "geo_installer"
    raw = _docker(
        "exec",
        container,
        "psql",
        "-U",
        user,
        "-d",
        database,
        "-X",
        "-qAt",
        "-F",
        "\t",
        "-c",
        "SELECT revision, upgrade_sha256, downgrade_sha256 "
        "FROM public.alembic_sql_checksum_ledger ORDER BY revision;",
    ).decode("utf-8", errors="replace")
    rows: dict[str, tuple[str, str]] = {}
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or any(not part for part in parts):
            raise MigrationError("Alembic checksum ledger returned an invalid row")
        rows[parts[0]] = (parts[1], parts[2])
    script = _current_alembic_script()
    expected_revisions = [str(revision.revision) for revision in reversed(list(script.walk_revisions()))]
    sql_directory = ROOT / "infra" / "db" / "alembic" / "sql"
    expected = {revision: sql_hashes(sql_directory, revision) for revision in expected_revisions}
    if rows != expected:
        missing = sorted(set(expected) - set(rows))
        extra = sorted(set(rows) - set(expected))
        drift = sorted(revision for revision in set(rows) & set(expected) if rows[revision] != expected[revision])
        raise MigrationError(
            "restored Alembic checksum ledger does not match current code: "
            f"missing={missing[:3]} extra={extra[:3]} drift={drift[:3]}"
        )
    return {
        "head": head,
        "revision_count": len(rows),
        "sha256": hashlib.sha256(_canonical_json(rows)).hexdigest(),
    }


def _upgrade_restored_geo_database(project: str) -> None:
    """Run the image's migration command after restoring the GEO dump."""

    migrate = _resolve_container(project, "migrate")
    if _running(migrate):
        _docker("exec", migrate, "alembic", "-c", "/app/alembic.ini", "upgrade", "head")
    else:
        # The canonical Compose migrate service is a one-shot container.  A
        # start/attach reruns its image-pinned command against the restored DB.
        _docker("start", "-a", migrate)


def _verify_pg(
    container: str,
    database: str,
    *,
    require_current_head: bool = False,
) -> dict[str, object]:
    user = "postgres" if database in {"dify", "dify_plugin"} else "geo_installer"
    has_alembic = _docker(
        "exec", container, "psql", "-U", user, "-d", database, "-X", "-qAt", "-c",
        "SELECT to_regclass('public.alembic_version');",
    ).decode("utf-8", errors="replace").strip()
    if has_alembic:
        revision = _docker(
            "exec", container, "psql", "-U", user, "-d", database, "-X", "-qAt", "-c",
            "SELECT version_num FROM alembic_version LIMIT 1;",
        ).decode("utf-8", errors="replace").strip()
    else:
        revision = "no-alembic"
    count = _docker(
        "exec", container, "psql", "-U", user, "-d", database, "-X", "-qAt", "-c",
        "SELECT count(*) FROM pg_class WHERE relkind IN ('r','p');",
    ).decode("utf-8", errors="replace").strip()
    result: dict[str, object] = {
        "migration_revision": revision,
        "relation_count": int(count or "0"),
    }
    if require_current_head:
        expected_head = _current_alembic_head()
        if revision != expected_head:
            raise MigrationError(
                "restored GEO database is not at the current Alembic head: "
                f"database={revision or 'missing'} expected={expected_head}"
            )
        result["checksum_ledger"] = _verify_checksum_ledger(
            container, database, head=expected_head
        )
    return result


def _scalar(container: str, database: str, user: str, sql: str) -> str:
    return _docker(
        "exec",
        container,
        "psql",
        "-U",
        user,
        "-d",
        database,
        "-X",
        "-qAt",
        "-c",
        sql,
    ).decode("utf-8", errors="replace").strip()


def _read_env_assignments(path: Path) -> dict[str, str]:
    """Read only simple ``KEY=value`` entries from an operator env file.

    This helper is intentionally not a shell evaluator.  Migration identity
    bindings are UUIDs and do not need command substitution or interpolation;
    treating the file as data prevents an export/import check from executing
    arbitrary env-file content.
    """

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise MigrationError(f"identity binding env file is unreadable: {path}") from error
    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in _IDENTITY_BINDING_FIELDS.values():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def _identity_values(*, env_file: str | Path | None, role: str) -> dict[str, str]:
    """Resolve the five non-secret identity bindings used by a GEO stack."""

    values: dict[str, str] = {}
    if env_file:
        path = Path(env_file).expanduser().resolve()
        if not path.is_file():
            raise MigrationError(f"{role} identity binding env file is missing: {path}")
        values.update(_read_env_assignments(path))
    for field in _IDENTITY_BINDING_FIELDS.values():
        configured = os.getenv(field, "").strip()
        if configured:
            values[field] = configured
    missing = [field for field in _IDENTITY_BINDING_FIELDS.values() if not values.get(field)]
    if missing:
        raise MigrationError(
            f"{role} identity bindings are incomplete: missing {', '.join(missing)}; "
            "provide the stack env file or set these non-secret UUID variables"
        )
    for field, value in values.items():
        try:
            parsed = UUID(value)
        except ValueError as error:
            raise MigrationError(f"{role} identity binding {field} must be a UUID") from error
        if parsed.int == 0:
            raise MigrationError(f"{role} identity binding {field} cannot be the nil UUID")
        values[field] = str(parsed)
    return values


def _identity_binding_manifest(values: dict[str, str], database: dict[str, object]) -> dict[str, object]:
    """Build the public/non-secret identity section stored in both manifests."""

    bindings = {
        name: {"env_name": env_name, "identity_id": values[env_name]}
        for name, env_name in _IDENTITY_BINDING_FIELDS.items()
    }
    return {
        "schema_version": "geo-runtime-identity-bindings-v1",
        "bindings": bindings,
        "database": database,
    }


def _query_identity_bindings(container: str, values: dict[str, str]) -> dict[str, object]:
    """Read identity/service binding status without exposing login attributes."""

    actor = values["GEO_ADMIN_ACTOR_ID"]
    tenant = values["GEO_ADMIN_TENANT_ID"]
    model_gateway = values["GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID"]
    connector = values["GEO_CONNECTOR_SERVICE_IDENTITY_ID"]
    browser = values["GEO_BROWSER_CAPTURE_SERVICE_IDENTITY_ID"]
    # All interpolated values have passed UUID validation in _identity_values.
    query = f"""
SELECT json_build_object(
  'admin_actor', COALESCE((
    SELECT json_build_object(
      'identity_id', i.id::text,
      'status', i.status,
      'tenant_membership', EXISTS (
        SELECT 1 FROM project_memberships pm
        WHERE pm.identity_id = i.id AND pm.tenant_id = '{tenant}'::uuid
          AND pm.status = 'active'
      )
    ) FROM identities i WHERE i.id = '{actor}'::uuid
  ), '{{}}'::json),
  'admin_tenant', COALESCE((
    SELECT json_build_object('tenant_id', t.id::text, 'status', t.status)
    FROM tenants t WHERE t.id = '{tenant}'::uuid
  ), '{{}}'::json),
  'services', COALESCE((
    SELECT json_object_agg(s.service_name, json_build_object(
      'identity_id', s.identity_id::text,
      'service_status', s.status,
      'identity_status', i.status,
      'issuer', i.issuer,
      'subject', i.subject
    ) ORDER BY s.service_name)
    FROM service_identities s
    JOIN identities i ON i.id = s.identity_id
    WHERE s.identity_id IN (
      '{model_gateway}'::uuid, '{connector}'::uuid, '{browser}'::uuid
    )
  ), '{{}}'::json)
)::text;
"""
    raw = _scalar(container, "geo", "geo_installer", query)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise MigrationError("identity binding query returned invalid JSON") from error
    if not isinstance(result, dict):
        raise MigrationError("identity binding query returned an invalid object")
    return result


def _assert_identity_bindings(
    values: dict[str, str], database: dict[str, object], *, role: str
) -> None:
    """Fail closed if UUIDs, active status, or service names drift."""

    actor = database.get("admin_actor")
    if not isinstance(actor, dict) or actor.get("identity_id") != values["GEO_ADMIN_ACTOR_ID"]:
        raise MigrationError(f"{role} database admin identity does not match its env binding")
    if actor.get("status") != "active" or actor.get("tenant_membership") is not True:
        raise MigrationError(f"{role} database admin identity is not active in the configured tenant")
    configured_tenant = database.get("admin_tenant")
    if not isinstance(configured_tenant, dict) or configured_tenant.get("tenant_id") != values["GEO_ADMIN_TENANT_ID"]:
        raise MigrationError(f"{role} database tenant does not match its env binding")
    if configured_tenant.get("status") != "active":
        raise MigrationError(f"{role} configured tenant is not active")
    services = database.get("services")
    if not isinstance(services, dict):
        raise MigrationError(f"{role} database has no service identity bindings")
    for name, env_name in _IDENTITY_BINDING_FIELDS.items():
        if name in {"admin_actor", "admin_tenant"}:
            continue
        service = services.get(_SERVICE_IDENTITY_NAMES[name])
        if not isinstance(service, dict):
            raise MigrationError(f"{role} database is missing service identity {name}")
        if service.get("identity_id") != values[env_name]:
            raise MigrationError(f"{role} database service identity {name} does not match its env binding")
        if service.get("service_status") != "active" or service.get("identity_status") != "active":
            raise MigrationError(f"{role} service identity {name} is not active")
        expected_service = _SERVICE_IDENTITY_NAMES[name]
        if service.get("issuer") != "geo.service" or service.get("subject") != expected_service:
            raise MigrationError(f"{role} service identity {name} has an unexpected service subject")


def _target_identity_bindings(container: str, env_file: str | Path | None) -> dict[str, object]:
    values = _identity_values(env_file=env_file, role="target")
    database = _query_identity_bindings(container, values)
    _assert_identity_bindings(values, database, role="target")
    return _identity_binding_manifest(values, database)


def _assert_target_empty(target_pg: str, dify_pg: str, target_minio: str) -> None:
    try:
        projects = _scalar(target_pg, "geo", "geo_installer", "SELECT count(*) FROM public.projects;")
    except MigrationError as error:
        if "does not exist" in str(error):
            projects = "0"
        else:
            raise
    if projects != "0":
        raise MigrationError(
            f"target GEO database is not empty: projects={projects}; use a fresh target or remove its data explicitly"
        )
    try:
        dify_apps = _scalar(dify_pg, "dify", "postgres", "SELECT count(*) FROM public.apps;")
    except MigrationError as error:
        if "does not exist" in str(error):
            dify_apps = "0"
        else:
            raise
    if dify_apps != "0":
        raise MigrationError(
            f"target Dify database is not empty: app_rows={dify_apps}; use a fresh target before import"
        )
    mount_type, mount_name, mount_source = _mount(target_minio, "/data")
    if mount_type == "bind":
        root = Path(mount_source).resolve()
        unexpected = [
            item
            for item in root.rglob("*")
            if item.is_file() and ".minio.sys" not in item.parts
        ]
        if unexpected:
            raise MigrationError(
                f"target MinIO is not empty: {len(unexpected)} data files exist; use a fresh target"
            )
    elif mount_type == "volume":
        if not mount_name:
            raise MigrationError("target MinIO Docker volume has no name")
        first_data_file = _docker(
            "run",
            "--rm",
            "-v",
            f"{mount_name}:/data:ro",
            "busybox:1.36",
            "sh",
            "-ceu",
            "find /data -type f ! -path '/data/.minio.sys/*' -print -quit",
        ).decode("utf-8", errors="replace").strip()
        if first_data_file:
            raise MigrationError(
                "target MinIO is not empty: data files exist in its Docker volume "
                f"(first={first_data_file}); use a fresh target"
            )
    else:
        raise MigrationError(f"unsupported target MinIO mount type: {mount_type}")


def _verify_secret_store(container: str) -> dict[str, object]:
    """Run the application-owned keyring and ciphertext restore canary."""

    program = (
        "import json, os; "
        "from geo_core.secrets.postgres_restore import verify_secret_store_restore; "
        "result = verify_secret_store_restore("
        "database_url=os.environ['GEO_DATABASE_URL'], "
        "keyring_path=os.environ['GEO_SECRET_STORE_MASTER_KEYRING_FILE']); "
        "print(json.dumps({'verified_key_versions': list(result.verified_key_versions), "
        "'representative_secret_count': result.representative_secret_count}, sort_keys=True))"
    )
    output = _docker("exec", container, "python", "-c", program).decode("utf-8", errors="replace").strip()
    try:
        result = json.loads(output)
    except json.JSONDecodeError as error:
        raise MigrationError("Secret Store restore canary returned invalid output") from error
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("verified_key_versions"), list)
        or not isinstance(result.get("representative_secret_count"), int)
    ):
        raise MigrationError("Secret Store restore canary returned an invalid result")
    return result


def import_package(args: argparse.Namespace) -> Path:
    package = Path(args.package).resolve()
    manifest = _read_manifest(package)
    expected_identity_bindings = _manifest_identity_bindings(manifest)
    if not args.confirm:
        raise MigrationError("import requires --confirm; use --dry-run to validate without changing data")
    if args.target_empty is not True and args.replace_test_replica is not True:
        raise MigrationError(
            "import requires --target-empty, or explicit --replace-test-replica for a disposable test replica"
        )
    target_pg = _resolve_container(args.target_project, "postgres")
    target_minio = _resolve_container(args.target_project, "minio")
    target_valkey = _resolve_container(args.target_project, "valkey")
    target_internal = _resolve_container(args.target_project, "internal-api")
    dify_pg = _resolve_container(args.dify_project, "db_postgres")
    dify_redis = _resolve_container(args.dify_project, "redis")
    dify_weaviate = _resolve_container(args.dify_project, "weaviate")
    target_identity_values = _identity_values(
        env_file=getattr(args, "target_env_file", None), role="target"
    )
    expected_identity_values = _identity_values_from_manifest(expected_identity_bindings)
    if target_identity_values != expected_identity_values:
        mismatched = sorted(
            name
            for name in target_identity_values
            if target_identity_values[name] != expected_identity_values.get(name)
        )
        raise MigrationError(
            "target environment identity bindings do not match the migration manifest: "
            + ", ".join(mismatched)
        )
    if args.target_empty:
        _assert_target_empty(target_pg, dify_pg, target_minio)
    stopped: list[str] = []
    receipt_path = package / "restore-receipt.json"
    try:
        stopped = _quiesce([args.target_project, args.dify_project])
        with tempfile.TemporaryDirectory(prefix="geo-import-") as temp:
            temp_root = Path(temp)
            decrypted = temp_root / "payload.tar"
            _decrypt(_payload_path(package, manifest), decrypted, Path(args.encryption_key_file).resolve())
            extracted = temp_root / "payload"
            extracted.mkdir(mode=0o700)
            _extract_safe(decrypted, extracted)
            payload_manifest_path = extracted / "payload-manifest.json"
            payload_manifest = json.loads(payload_manifest_path.read_text(encoding="utf-8"))
            entries = payload_manifest.get("files")
            if not isinstance(entries, list):
                raise MigrationError("payload manifest has no file entries")
            payload_identity_bindings = _manifest_identity_bindings(payload_manifest)
            if payload_identity_bindings != expected_identity_bindings:
                raise MigrationError(
                    "outer and encrypted payload identity bindings do not match"
                )
            _verify_payload(extracted, entries)
            _validate_custom_dump(target_pg, extracted / "geo" / "postgres.dump")
            _validate_custom_dump(dify_pg, extracted / "dify" / "postgres-dify.dump")
            _validate_custom_dump(dify_pg, extracted / "dify" / "postgres-dify_plugin.dump")
            _restore_pg(target_pg, "geo", extracted / "geo" / "postgres.dump")
            # A logical dump can have been produced by an older checkout.  It
            # is never receipt-eligible until this checkout's migration image
            # upgrades it to the current head and its SQL ledger is verified.
            _upgrade_restored_geo_database(args.target_project)
            geo_postgres_check = _verify_pg(
                target_pg, "geo", require_current_head=True
            )
            _restore_pg(dify_pg, "dify", extracted / "dify" / "postgres-dify.dump")
            _restore_pg(dify_pg, "dify_plugin", extracted / "dify" / "postgres-dify_plugin.dump")
            _docker("stop", target_minio)
            _restore_archive_to_mount(target_minio, "/data", extracted / "geo" / "minio-data.tar.gz", clear=True)
            _docker("start", target_minio)
            _docker("stop", target_valkey)
            _restore_file_to_mount(target_valkey, "/data", extracted / "geo" / "valkey.rdb", clear=True)
            _docker("start", target_valkey)
            _docker("stop", dify_redis)
            _restore_file_to_mount(dify_redis, "/data", extracted / "dify" / "redis.rdb", clear=True)
            _docker("start", dify_redis)
            _docker("stop", dify_weaviate)
            _restore_archive_to_mount(dify_weaviate, "/var/lib/weaviate", extracted / "dify" / "weaviate-data.tar.gz", clear=True)
            _docker("start", dify_weaviate)
            runtime_root = Path(args.dify_runtime_root).resolve()
            dify_payload = extracted / "dify"
            volumes_root = runtime_root / "docker" / "volumes"
            for archive_name, relative_root in _DIFY_PERSISTENT_DIRECTORIES:
                _restore_host_archive(
                    dify_payload / f"{archive_name}.tar.gz",
                    volumes_root / relative_root,
                    allowed_root=volumes_root,
                    clear=True,
                )
            runtime_root.joinpath("docker").mkdir(parents=True, exist_ok=True)
            if (dify_payload / "dify.env").exists():
                shutil.copy2(dify_payload / "dify.env", runtime_root / "docker" / ".env")
                os.chmod(runtime_root / "docker" / ".env", 0o600)
            state_target = Path(args.dify_state_file).resolve()
            state_target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(dify_payload / _DIFY_STATE_NAME, state_target)
            os.chmod(state_target, 0o600)
            secret_root = Path(args.secret_root).resolve()
            _copy_regular_tree(extracted / "secrets", secret_root)
            checks = {
                "geo_postgres": geo_postgres_check,
                "dify_postgres": _verify_pg(dify_pg, "dify"),
                "dify_plugin_postgres": _verify_pg(dify_pg, "dify_plugin"),
                "payload_files": len(entries),
            }
            target_identity_bindings = _target_identity_bindings(
                target_pg, getattr(args, "target_env_file", None)
            )
            checks["identity_bindings"] = {
                "source": expected_identity_bindings,
                "target": target_identity_bindings,
                "match": target_identity_bindings["bindings"]
                == expected_identity_bindings["bindings"],
            }
        # The canary runs inside the application image so it uses the exact
        # target DATABASE_URL and mounted keyring that production workers use.
        if stopped:
            _restart(stopped)
            stopped = []
            _refresh_dify_gateway(args.dify_project)
        checks["secret_store"] = _verify_secret_store(target_internal)
        receipt = {
            "schema_version": "geo-runtime-restore-receipt-v1",
            "status": "verified-restore",
            "restored_at": datetime.now(UTC).isoformat(),
            "source_manifest_sha256": _sha256(package / "manifest.json"),
            "target_project": args.target_project,
            "dify_project": args.dify_project,
            "replacement_mode": "empty-target" if args.target_empty else "test-replica-overwrite",
            "checks": checks,
        }
        receipt_path.write_bytes(_canonical_json(receipt))
        os.chmod(receipt_path, 0o600)
        print(receipt_path)
        return receipt_path
    except Exception:
        if receipt_path.exists():
            receipt_path.unlink()
        raise
    finally:
        if stopped:
            _restart(stopped)
            _refresh_dify_gateway(args.dify_project)


def _write_verification_receipt(
    package: Path,
    manifest: dict[str, object],
    identity_bindings: dict[str, object],
    entries: list[dict[str, object]],
) -> Path:
    """Persist a hash-bound receipt for destructive legacy-volume cleanup."""

    manifest_path = package / "manifest.json"
    payload = manifest.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("sha256"), str):
        raise MigrationError("migration manifest payload checksum is missing")
    receipt = {
        "schema_version": VERIFY_RECEIPT_SCHEMA,
        "status": "verified-package",
        "verified_at": datetime.now(UTC).isoformat(),
        "manifest_sha256": _sha256(manifest_path),
        "payload_sha256": payload["sha256"],
        "migration_schema": manifest["schema_version"],
        "current_schema": SCHEMA,
        "identity_bindings_sha256": hashlib.sha256(
            _canonical_json(identity_bindings)
        ).hexdigest(),
        "payload_file_count": len(entries),
    }
    path = package / "verification-receipt.json"
    temporary = package / ".verification-receipt.json.tmp"
    temporary.write_bytes(_canonical_json(receipt))
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    return path


def verify_package(args: argparse.Namespace) -> None:
    package = Path(args.package).resolve()
    manifest = _read_manifest(package)
    identity_bindings = _manifest_identity_bindings(manifest)
    if getattr(args, "require_current_schema", False) and manifest.get("schema_version") != SCHEMA:
        raise MigrationError(
            f"migration package schema is not current: expected {SCHEMA}, "
            f"received {manifest.get('schema_version')!r}"
        )
    with tempfile.TemporaryDirectory(prefix="geo-verify-") as temporary:
        decrypted = Path(temporary) / "payload.tar"
        _decrypt(_payload_path(package, manifest), decrypted, Path(args.encryption_key_file).resolve())
        extracted = Path(temporary) / "payload"
        extracted.mkdir(mode=0o700)
        _extract_safe(decrypted, extracted)
        payload_manifest = json.loads(
            (extracted / "payload-manifest.json").read_text(encoding="utf-8")
        )
        if _manifest_identity_bindings(payload_manifest) != _manifest_identity_bindings(manifest):
            raise MigrationError("outer and encrypted payload identity bindings do not match")
        entries = payload_manifest.get("files")
        if not isinstance(entries, list):
            raise MigrationError("payload manifest has no file entries")
        _verify_payload(extracted, entries)
        if args.postgres_container:
            for relative in (
                "geo/postgres.dump",
                "dify/postgres-dify.dump",
                "dify/postgres-dify_plugin.dump",
            ):
                _validate_custom_dump(args.postgres_container, extracted / relative)
    if getattr(args, "write_receipt", False):
        receipt = _write_verification_receipt(package, manifest, identity_bindings, entries)
        print(f"verification receipt: {receipt}")
    payload = manifest.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("sha256"), str):
        raise MigrationError("migration manifest payload checksum is missing")
    print(
        f"verified migration package: source={manifest['source_project']} "
        f"files={len(entries)} payload_sha256={payload['sha256']}"
    )


def dry_run(args: argparse.Namespace) -> None:
    if args.command == "export":
        _secure_file(Path(args.encryption_key_file).resolve())
        _secure_file(Path(args.dify_state_file).resolve())
        _copy_regular_tree(Path(args.secret_root).resolve(), Path(tempfile.mkdtemp(prefix="geo-migrate-dry-run-")))
        print("dry-run export inputs: ok")
        return
    package = Path(args.package).resolve()
    manifest = _read_manifest(package)
    _manifest_identity_bindings(manifest)
    _secure_file(Path(args.encryption_key_file).resolve())
    with tempfile.TemporaryDirectory(prefix="geo-import-dry-run-") as temporary:
        decrypted = Path(temporary) / "payload.tar"
        _decrypt(_payload_path(package, manifest), decrypted, Path(args.encryption_key_file).resolve())
        extracted = Path(temporary) / "payload"
        extracted.mkdir(mode=0o700)
        _extract_safe(decrypted, extracted)
        payload_manifest = json.loads(
            (extracted / "payload-manifest.json").read_text(encoding="utf-8")
        )
        if _manifest_identity_bindings(payload_manifest) != _manifest_identity_bindings(manifest):
            raise MigrationError("outer and encrypted payload identity bindings do not match")
        entries = payload_manifest.get("files")
        if not isinstance(entries, list):
            raise MigrationError("payload manifest has no file entries")
        _verify_payload(extracted, entries)
    print(f"dry-run import payload: ok ({manifest['source_project']} -> {args.target_project})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export")
    export.add_argument("--repo-root", default=str(ROOT))
    export.add_argument("--source-project", default=os.getenv("GEO_SOURCE_PROJECT", DEFAULT_SOURCE_PROJECT))
    export.add_argument("--source-environment", default=os.getenv("GEO_SOURCE_ENVIRONMENT", "staging"))
    export.add_argument("--source-role", default=os.getenv("GEO_SOURCE_ROLE", "source"))
    export.add_argument(
        "--source-env-file",
        default=os.getenv("GEO_STACK_ENV_FILE", ""),
        help="stack env file containing the non-secret identity bindings",
    )
    export.add_argument("--dify-project", default=DEFAULT_DIFY_PROJECT)
    export.add_argument("--output-root", required=True)
    export.add_argument("--encryption-key-file", required=True)
    export.add_argument("--secret-root", required=True)
    export.add_argument("--dify-runtime-root", default=str(ROOT / ".runtime" / "dify-1.16.0"))
    export.add_argument("--dify-state-file", default=str(ROOT / ".runtime" / _DIFY_STATE_NAME))
    export.add_argument("--allow-dirty", action="store_true")
    export.add_argument("--no-quiesce", dest="quiesce", action="store_false")
    export.set_defaults(quiesce=True)
    imp = subparsers.add_parser("import")
    imp.add_argument("--repo-root", default=str(ROOT))
    imp.add_argument("--package", required=True)
    imp.add_argument("--target-project", default=os.getenv("GEO_TARGET_PROJECT", DEFAULT_TARGET_PROJECT))
    imp.add_argument(
        "--target-env-file",
        default=os.getenv("GEO_STACK_ENV_FILE", ""),
        help="target stack env file whose non-secret identity bindings must match the package",
    )
    imp.add_argument("--dify-project", default=DEFAULT_DIFY_PROJECT)
    imp.add_argument("--encryption-key-file", required=True)
    imp.add_argument("--secret-root", required=True)
    imp.add_argument("--dify-runtime-root", default=str(ROOT / ".runtime" / "dify-1.16.0"))
    imp.add_argument("--dify-state-file", default=str(ROOT / ".runtime" / _DIFY_STATE_NAME))
    imp.add_argument("--target-empty", action="store_true")
    imp.add_argument("--replace-test-replica", action="store_true")
    imp.add_argument("--confirm", action="store_true")
    imp.add_argument("--dry-run", action="store_true")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--repo-root", default=str(ROOT))
    verify.add_argument("--package", required=True)
    verify.add_argument("--encryption-key-file", required=True)
    verify.add_argument("--postgres-container", default="")
    verify.add_argument(
        "--require-current-schema",
        action="store_true",
        help="reject legacy migration schemas",
    )
    verify.add_argument(
        "--write-receipt",
        action="store_true",
        help="write a hash-bound verification-receipt.json after full verification",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify":
            verify_package(args)
        elif getattr(args, "dry_run", False):
            dry_run(args)
        elif args.command == "export":
            export_package(args)
        else:
            import_package(args)
    except MigrationError as error:
        print(f"geo-migrate error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
