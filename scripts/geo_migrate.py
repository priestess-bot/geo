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


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "geo-runtime-migration-v2"
LEGACY_SCHEMA = "geo-runtime-migration-v1"
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
                link_target = (item.parent / os.readlink(item)).resolve(strict=False)
                if link_target != root and root not in link_target.parents:
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


def _restore_host_archive(archive: Path, destination: Path, *, clear: bool) -> None:
    """Restore a bind-mounted Dify directory after validating its archive."""

    if destination == Path("/") or len(destination.parts) < 3:
        raise MigrationError(f"refusing to restore into an unsafe directory: {destination}")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    if clear:
        _clear_directory(destination)
    _extract_archive_to_directory(archive, destination)


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
        item["path"]: item["sha256"]
        for item in _files(root, exclude={"payload-manifest.json"})
    }
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
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


def _extract_safe(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r") as payload:
        for member in payload.getmembers():
            target = (destination / member.name).resolve()
            if destination.resolve() not in target.parents:
                raise MigrationError(f"unsafe archive member: {member.name}")
        payload.extractall(destination, filter="data")


def _extract_archive_to_directory(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(archive, "r") as payload:
        for member in payload.getmembers():
            target = (destination / member.name).resolve()
            if destination not in target.parents:
                raise MigrationError(f"unsafe state archive member: {member.name}")
        payload.extractall(destination, filter="data")


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


def _verify_pg(container: str, database: str) -> dict[str, object]:
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
    return {"migration_revision": revision, "relation_count": int(count or "0")}


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
            _verify_payload(extracted, entries)
            _validate_custom_dump(target_pg, extracted / "geo" / "postgres.dump")
            _validate_custom_dump(dify_pg, extracted / "dify" / "postgres-dify.dump")
            _validate_custom_dump(dify_pg, extracted / "dify" / "postgres-dify_plugin.dump")
            _restore_pg(target_pg, "geo", extracted / "geo" / "postgres.dump")
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
                "geo_postgres": _verify_pg(target_pg, "geo"),
                "dify_postgres": _verify_pg(dify_pg, "dify"),
                "dify_plugin_postgres": _verify_pg(dify_pg, "dify_plugin"),
                "payload_files": len(entries),
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


def verify_package(args: argparse.Namespace) -> None:
    package = Path(args.package).resolve()
    manifest = _read_manifest(package)
    with tempfile.TemporaryDirectory(prefix="geo-verify-") as temporary:
        decrypted = Path(temporary) / "payload.tar"
        _decrypt(_payload_path(package, manifest), decrypted, Path(args.encryption_key_file).resolve())
        extracted = Path(temporary) / "payload"
        extracted.mkdir(mode=0o700)
        _extract_safe(decrypted, extracted)
        payload_manifest = json.loads(
            (extracted / "payload-manifest.json").read_text(encoding="utf-8")
        )
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
    print(
        f"verified migration package: source={manifest['source_project']} "
        f"files={len(entries)} payload_sha256={manifest['payload']['sha256']}"
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
