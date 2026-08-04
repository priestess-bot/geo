#!/usr/bin/env python3
"""Move encrypted GEO runtime baselines and component deltas through GitHub Releases.

GitHub is used only as an authenticated transport for encrypted assets.  The
source database remains the authority; a test replica never merges local
writes back into a primary archive.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any

# Keep both `python -m scripts.geo_sync` and the operator-facing
# `python scripts/geo_sync.py` entrypoints usable from the repository root.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.geo_migrate import (
    LEGACY_SCHEMA,
    SCHEMA,
    MigrationError,
    _canonical_json,
    _decrypt,
    _encrypt,
    _extract_safe,
    _files,
    _payload_path,
)


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_SCHEMA = "geo-runtime-github-archive-v1"
DELTA_SCHEMA = "geo-runtime-migration-delta-v1"
DEFAULT_CHUNK_SIZE = 45 * 1024 * 1024


class SyncError(RuntimeError):
    """An archive cannot be uploaded, downloaded, or applied safely."""


def _run(command: list[str], *, cwd: Path | None = None) -> bytes:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise SyncError(f"required command is unavailable: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise SyncError(f"command failed ({command[0]}): {detail[-600:] or 'no detail'}") from error
    return result.stdout


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _secure_file(path: Path) -> None:
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError as error:
        raise SyncError(f"required secure file is missing: {path}") from error
    if path.is_symlink() or not path.is_file() or mode != 0o600:
        raise SyncError(f"passphrase input must be a regular 0600 file: {path}")


def _repo_slug(value: str) -> str:
    slug = value.strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
    if slug.count("/") != 1 or any(not part for part in slug.split("/")):
        raise SyncError("GitHub repository must be owner/name or https://github.com/owner/name")
    return slug


def _require_private_repo(repo: str) -> None:
    value = _run(["gh", "api", f"repos/{repo}", "--jq", ".private"]).decode().strip()
    if value != "true":
        raise SyncError("migration archive repository must be private")


def _package_manifest(package: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SyncError(f"package manifest is unreadable: {package}") from error
    if manifest.get("schema_version") not in {SCHEMA, LEGACY_SCHEMA, DELTA_SCHEMA}:
        raise SyncError("unsupported package schema")
    return manifest


def _require_role(manifest: dict[str, Any], allowed: set[str], *, operation: str) -> None:
    role = manifest.get("source_role")
    if role not in allowed:
        expected = ", ".join(sorted(allowed))
        raise SyncError(f"{operation} requires source_role={expected}; received {role!r}")


def _require_delta_parent(delta: dict[str, Any], parent: dict[str, Any]) -> None:
    expected = delta.get("parent_archive_id")
    actual = parent.get("archive_id")
    if expected and actual and expected != actual:
        raise SyncError(
            "incremental archive parent mismatch: "
            f"delta expects {expected!r}, resolved parent is {actual!r}"
        )


def _chunk(path: Path, directory: Path, *, size: int) -> list[dict[str, Any]]:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    result: list[dict[str, Any]] = []
    with path.open("rb") as source:
        index = 0
        while True:
            content = source.read(size)
            if not content:
                break
            chunk = directory / f"{path.name}.part-{index:06d}"
            chunk.write_bytes(content)
            chunk.chmod(0o600)
            result.append(
                {
                    "name": chunk.name,
                    "index": index,
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
            index += 1
    if not result:
        raise SyncError("encrypted payload is empty")
    return result


def _join_chunks(directory: Path, archive_manifest: dict[str, Any], destination: Path) -> None:
    chunks = archive_manifest.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise SyncError("GitHub archive has no payload chunks")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with destination.open("wb") as output:
        for expected_index, item in enumerate(chunks):
            if not isinstance(item, dict) or item.get("index") != expected_index:
                raise SyncError("GitHub archive chunk indexes are not contiguous")
            name = item.get("name")
            if not isinstance(name, str) or Path(name).name != name:
                raise SyncError("GitHub archive chunk name is unsafe")
            chunk = directory / name
            if not chunk.is_file() or _sha256(chunk) != item.get("sha256"):
                raise SyncError(f"GitHub archive chunk hash mismatch: {name}")
            with chunk.open("rb") as source:
                shutil.copyfileobj(source, output, 1024 * 1024)
    if _sha256(destination) != archive_manifest.get("payload_sha256"):
        raise SyncError("joined GitHub archive payload hash mismatch")


def _archive_assets(package: Path, work: Path, *, chunk_size: int) -> tuple[Path, list[Path]]:
    manifest = _package_manifest(package)
    payload = _payload_path(package, manifest)
    chunks = _chunk(payload, work / "chunks", size=chunk_size)
    archive_manifest = {
        "schema_version": ARCHIVE_SCHEMA,
        "archive_id": manifest.get("archive_id", package.name),
        "kind": manifest.get("kind", "baseline"),
        "package_schema": manifest.get("schema_version"),
        "package_manifest_sha256": _sha256(package / "manifest.json"),
        "payload_name": payload.name,
        "payload_sha256": _sha256(payload),
        "payload_size_bytes": payload.stat().st_size,
        "chunks": chunks,
        "created_at": datetime.now(UTC).isoformat(),
    }
    archive_manifest_path = work / "archive-manifest.json"
    archive_manifest_path.write_bytes(_canonical_json(archive_manifest))
    archive_manifest_path.chmod(0o600)
    assets = [package / "manifest.json", archive_manifest_path]
    assets.extend(work / "chunks" / item["name"] for item in chunks)
    return archive_manifest_path, assets


def upload_package(
    package: Path,
    *,
    repo: str,
    release: str | None,
    chunk_size: int,
    target_commit: str | None,
) -> str:
    _require_private_repo(repo)
    manifest = _package_manifest(package)
    tag = release or str(manifest.get("archive_id") or package.name)
    if not tag.startswith("geo-migration-"):
        tag = f"geo-migration-{tag}"
    manifest["release_tag"] = tag
    (package / "manifest.json").write_bytes(_canonical_json(manifest))
    (package / "manifest.json").chmod(0o600)
    with tempfile.TemporaryDirectory(prefix="geo-sync-upload-") as temporary:
        archive_manifest, assets = _archive_assets(package, Path(temporary), chunk_size=chunk_size)
        target = target_commit or str(manifest.get("source_git", {}).get("commit", ""))
        if not target:
            raise SyncError("release target commit is missing from package manifest")
        try:
            _run(["gh", "release", "view", tag, "--repo", repo])
        except SyncError:
            _run(
                [
                    "gh",
                    "release",
                    "create",
                    tag,
                    "--repo",
                    repo,
                    "--target",
                    target,
                    "--title",
                    f"GEO migration {tag}",
                    "--notes",
                    "Encrypted GEO runtime migration archive; payload is password protected.",
                ]
            )
        _run(["gh", "release", "upload", tag, *[str(item) for item in assets], "--repo", repo, "--clobber"])
        # Re-read the local manifest so a caller can persist only a harmless tag.
        if not archive_manifest.is_file():
            raise SyncError("archive manifest was not created")
    return tag


def download_package(repo: str, release: str, output: Path) -> Path:
    _require_private_repo(repo)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    _run(["gh", "release", "download", release, "--repo", repo, "--dir", str(output), "--clobber"])
    archive_manifest_path = output / "archive-manifest.json"
    manifest_path = output / "manifest.json"
    try:
        archive_manifest = json.loads(archive_manifest_path.read_text(encoding="utf-8"))
        package_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SyncError("downloaded GitHub archive manifest is invalid") from error
    if archive_manifest.get("schema_version") != ARCHIVE_SCHEMA:
        raise SyncError("unsupported GitHub archive schema")
    if archive_manifest.get("package_manifest_sha256") != _sha256(manifest_path):
        raise SyncError("package manifest hash does not match GitHub archive manifest")
    payload_name = archive_manifest.get("payload_name")
    if not isinstance(payload_name, str) or Path(payload_name).name != payload_name:
        raise SyncError("GitHub payload name is unsafe")
    joined = output / payload_name
    _join_chunks(output, archive_manifest, joined)
    if package_manifest.get("payload", {}).get("path") != payload_name:
        raise SyncError("package manifest payload path differs from downloaded archive")
    return output


def _extract_package(package: Path, passphrase: Path, destination: Path) -> dict[str, Any]:
    manifest = _package_manifest(package)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    decrypted = destination / "payload.tar.gz"
    _decrypt(_payload_path(package, manifest), decrypted, passphrase)
    payload = destination / "payload"
    payload.mkdir(mode=0o700)
    _extract_safe(decrypted, payload)
    payload_manifest_path = payload / "payload-manifest.json"
    entries = json.loads(payload_manifest_path.read_text(encoding="utf-8")).get("files")
    if not isinstance(entries, list):
        raise SyncError("payload manifest has no files")
    expected = {str(item["path"]): str(item["sha256"]) for item in entries}
    actual = {str(item["path"]): str(item["sha256"]) for item in _files(payload, exclude={"payload-manifest.json"})}
    if actual != expected:
        raise SyncError("decrypted payload content hash mismatch")
    return manifest


def _write_payload_manifest(payload: Path) -> None:
    entries = _files(payload, exclude={"payload-manifest.json"})
    path = payload / "payload-manifest.json"
    path.write_bytes(_canonical_json({"schema_version": "geo-runtime-payload-v2", "files": entries}))
    path.chmod(0o600)


def _build_delta(
    current: Path,
    parent: Path,
    passphrase: Path,
    output_root: Path,
    parent_release: str | None = None,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    current_manifest = _package_manifest(current)
    parent_manifest = _package_manifest(parent)
    if parent_manifest.get("schema_version") == DELTA_SCHEMA:
        raise SyncError(
            "incremental export requires the previous full geo-runtime package as --parent-package; "
            "pass the retained full export, not a delta package"
        )
    with tempfile.TemporaryDirectory(prefix="geo-sync-delta-") as temporary:
        temporary_root = Path(temporary)
        current_data = temporary_root / "current"
        parent_data = temporary_root / "parent"
        _extract_package(current, passphrase, current_data)
        _extract_package(parent, passphrase, parent_data)
        current_payload = current_data / "payload"
        parent_payload = parent_data / "payload"
        current_entries = {str(item["path"]): item for item in _files(current_payload, exclude={"payload-manifest.json"})}
        parent_entries = {str(item["path"]): item for item in _files(parent_payload, exclude={"payload-manifest.json"})}
        changed = sorted(
            path for path, item in current_entries.items() if parent_entries.get(path, {}).get("sha256") != item["sha256"]
        )
        deleted = sorted(set(parent_entries) - set(current_entries))
        delta_id = f"geo-migration-delta-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        package = output_root / delta_id
        package.mkdir(mode=0o700)
        payload = package / "payload"
        payload.mkdir(mode=0o700)
        for relative in changed:
            source = current_payload / relative
            target = payload / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        (payload / "deletions.json").write_bytes(_canonical_json({"paths": deleted}))
        _write_payload_manifest(payload)
        encrypted = package / "payload.tar.gz.gpg"
        with tempfile.TemporaryDirectory(prefix="geo-sync-delta-tar-") as tar_directory:
            tar_path = Path(tar_directory) / "payload.tar.gz"
            with tarfile.open(tar_path, "w:gz") as archive:
                for item in sorted(payload.rglob("*")):
                    if item.is_file():
                        archive.add(item, arcname=item.relative_to(payload).as_posix(), recursive=False)
            _encrypt(tar_path, encrypted, passphrase)
        manifest = {
            "schema_version": DELTA_SCHEMA,
            "status": "verified-export",
            "kind": "incremental",
            "archive_id": delta_id,
            "parent_archive_id": parent_manifest.get("archive_id", parent.name),
            "parent_release": parent_release or parent_manifest.get("release_tag") or parent_manifest.get("archive_id"),
            "source_git": current_manifest.get("source_git", {}),
            "source_environment": current_manifest.get("source_environment"),
            "source_role": "primary",
            "created_at": datetime.now(UTC).isoformat(),
            "changes": {"changed_paths": changed, "deleted_paths": deleted},
            "payload": {
                "path": encrypted.name,
                "size_bytes": encrypted.stat().st_size,
                "sha256": _sha256(encrypted),
            },
        }
        (package / "manifest.json").write_bytes(_canonical_json(manifest))
        (package / "manifest.json").chmod(0o600)
        return package


def _cached_release(repo: str, release: str, cache: Path) -> Path:
    package = cache / release
    if (package / "manifest.json").is_file():
        return package
    return download_package(repo, release, package)


def _materialize_release(
    repo: str,
    release: str,
    passphrase: Path,
    cache: Path,
    destination: Path,
    active: set[str],
) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    if release in active:
        raise SyncError("incremental archive parent cycle detected")
    active.add(release)
    package = _cached_release(repo, release, cache)
    manifest = _package_manifest(package)
    if manifest.get("schema_version") in {SCHEMA, LEGACY_SCHEMA}:
        extracted = destination / "base"
        extracted.mkdir(mode=0o700)
        base_manifest = _extract_package(package, passphrase, extracted)
        shutil.copytree(extracted / "payload", destination / "payload", dirs_exist_ok=True)
        active.remove(release)
        return base_manifest
    if manifest.get("schema_version") != DELTA_SCHEMA:
        raise SyncError("release is neither a baseline nor a supported delta")
    parent_release = manifest.get("parent_release")
    if not isinstance(parent_release, str) or not parent_release:
        raise SyncError("incremental archive has no parent release")
    parent_package = _cached_release(repo, parent_release, cache)
    parent_release_manifest = _package_manifest(parent_package)
    parent_manifest = _materialize_release(repo, parent_release, passphrase, cache, destination, active)
    _require_delta_parent(manifest, parent_release_manifest)
    delta_root = destination / f"delta-{len(active)}"
    delta_root.mkdir(mode=0o700)
    _extract_package(package, passphrase, delta_root)
    delta_payload = delta_root / "payload"
    target_payload = destination / "payload"
    changes = manifest.get("changes")
    if not isinstance(changes, dict):
        raise SyncError("incremental archive change manifest is invalid")
    changed_paths = changes.get("changed_paths")
    deleted_paths = changes.get("deleted_paths")
    if not isinstance(changed_paths, list) or not isinstance(deleted_paths, list):
        raise SyncError("incremental archive paths are invalid")
    for relative in changed_paths:
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise SyncError("incremental archive contains an unsafe changed path")
        source = delta_payload / relative
        if not source.is_file():
            raise SyncError(f"incremental changed path is missing: {relative}")
        target = target_payload / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for relative in deleted_paths:
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise SyncError("incremental archive contains an unsafe deleted path")
        target = (target_payload / relative).resolve()
        if target_payload.resolve() not in target.parents:
            raise SyncError("incremental deleted path escapes payload")
        if target.is_file() or target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
    active.remove(release)
    return parent_manifest


def _write_materialized_package(payload: Path, base_manifest: dict[str, Any], passphrase: Path, output: Path) -> Path:
    package = output / "materialized"
    package.mkdir(parents=True, exist_ok=True, mode=0o700)
    _write_payload_manifest(payload)
    with tempfile.TemporaryDirectory(prefix="geo-sync-materialized-tar-") as temporary:
        tar_path = Path(temporary) / "payload.tar.gz"
        with tarfile.open(tar_path, "w:gz") as archive:
            for item in sorted(payload.rglob("*")):
                if item.is_file():
                    archive.add(item, arcname=item.relative_to(payload).as_posix(), recursive=False)
        encrypted = package / "payload.tar.gz.gpg"
        _encrypt(tar_path, encrypted, passphrase)
    manifest = dict(base_manifest)
    manifest.update(
        {
            "schema_version": SCHEMA,
            "status": "verified-export",
            "kind": "materialized-incremental",
            "archive_id": f"materialized-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
            "release_tag": base_manifest.get("release_tag"),
            "payload": {
                "path": encrypted.name,
                "size_bytes": encrypted.stat().st_size,
                "sha256": _sha256(encrypted),
            },
        }
    )
    (package / "manifest.json").write_bytes(_canonical_json(manifest))
    (package / "manifest.json").chmod(0o600)
    return package


def _command_export(args: argparse.Namespace) -> Path:
    output_root = Path(args.output_root).resolve()
    command = [
        sys.executable,
        str(ROOT / "scripts" / "geo_migrate.py"),
        "export",
        "--repo-root",
        str(ROOT),
        "--source-project",
        args.source_project,
        "--source-environment",
        args.source_environment,
        "--source-role",
        args.source_role,
        "--dify-project",
        args.dify_project,
        "--output-root",
        str(output_root),
        "--encryption-key-file",
        args.passphrase_file,
        "--secret-root",
        args.secret_root,
        "--dify-runtime-root",
        args.dify_runtime_root,
        "--dify-state-file",
        args.dify_state_file,
    ]
    if args.allow_dirty:
        command.append("--allow-dirty")
    if not args.quiesce:
        command.append("--no-quiesce")
    _run(command)
    packages = sorted(output_root.glob("geo-runtime-*"), key=lambda item: item.stat().st_mtime)
    if not packages:
        raise SyncError("export command did not produce a package")
    return packages[-1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--repo", required=True, help="private GitHub owner/name")
        command.add_argument("--passphrase-file", required=True)

    export = sub.add_parser("export-baseline-upload")
    common(export)
    export.add_argument("--output-root", required=True)
    export.add_argument("--secret-root", required=True)
    export.add_argument("--dify-runtime-root", default=str(ROOT / ".runtime" / "dify-1.16.0"))
    export.add_argument("--dify-state-file", default=str(ROOT / ".runtime" / "geo-dify-state.json"))
    export.add_argument("--source-project", default="geo-advinsys-staging-v2")
    export.add_argument("--source-environment", default="staging")
    export.add_argument("--source-role", default="source")
    export.add_argument("--dify-project", default="geo-dify")
    export.add_argument("--release")
    export.add_argument("--allow-dirty", action="store_true")
    export.add_argument("--no-quiesce", dest="quiesce", action="store_false")
    export.set_defaults(quiesce=True)

    download = sub.add_parser("download")
    common(download)
    download.add_argument("--release", required=True)
    download.add_argument("--output", required=True)

    verify = sub.add_parser("verify-release")
    common(verify)
    verify.add_argument("--release", required=True)
    verify.add_argument("--output", required=True)

    restore = sub.add_parser("import-baseline")
    common(restore)
    restore.add_argument("--package")
    restore.add_argument("--release")
    restore.add_argument("--download-root", default=".runtime/geo-sync-cache")
    restore.add_argument("--secret-root", required=True)
    restore.add_argument("--dify-runtime-root", default=str(ROOT / ".runtime" / "dify-1.16.0"))
    restore.add_argument("--dify-state-file", default=str(ROOT / ".runtime" / "geo-dify-state.json"))
    restore.add_argument("--target-project", default="geo")
    restore.add_argument("--dify-project", default="geo-dify")
    restore.add_argument("--target-empty", action="store_true")
    restore.add_argument("--confirm", action="store_true")

    incremental = sub.add_parser("export-incremental-upload")
    common(incremental)
    incremental.add_argument("--parent-package", required=True)
    incremental.add_argument("--parent-release")
    incremental.add_argument("--output-root", required=True)
    incremental.add_argument("--secret-root", required=True)
    incremental.add_argument("--dify-runtime-root", default=str(ROOT / ".runtime" / "dify-1.16.0"))
    incremental.add_argument("--dify-state-file", default=str(ROOT / ".runtime" / "geo-dify-state.json"))
    incremental.add_argument("--source-project", default="geo")
    incremental.add_argument("--source-environment", default="production")
    incremental.add_argument("--source-role", default="primary")
    incremental.add_argument("--dify-project", default="geo-dify")
    incremental.add_argument("--release")
    incremental.add_argument("--allow-dirty", action="store_true")
    incremental.add_argument("--no-quiesce", dest="quiesce", action="store_false")
    incremental.set_defaults(quiesce=True)

    apply_delta = sub.add_parser("apply-incremental")
    common(apply_delta)
    apply_delta.add_argument("--release", required=True)
    apply_delta.add_argument("--package-cache", required=True)
    apply_delta.add_argument("--secret-root", required=True)
    apply_delta.add_argument("--dify-runtime-root", default=str(ROOT / ".runtime" / "dify-1.16.0"))
    apply_delta.add_argument("--dify-state-file", default=str(ROOT / ".runtime" / "geo-dify-state.json"))
    apply_delta.add_argument("--target-project", default="geo")
    apply_delta.add_argument("--dify-project", default="geo-dify")
    apply_delta.add_argument("--overwrite-test-replica", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _secure_file(Path(args.passphrase_file).resolve())
        repo = _repo_slug(args.repo)
        if args.command == "export-baseline-upload":
            package = _command_export(args)
            tag = upload_package(package, repo=repo, release=args.release, chunk_size=DEFAULT_CHUNK_SIZE, target_commit=None)
            print(json.dumps({"release": tag, "package": str(package)}, sort_keys=True))
        elif args.command == "download":
            path = download_package(repo, args.release, Path(args.output))
            print(path)
        elif args.command == "verify-release":
            path = download_package(repo, args.release, Path(args.output))
            _run([sys.executable, str(ROOT / "scripts" / "geo_migrate.py"), "verify", "--package", str(path), "--encryption-key-file", args.passphrase_file])
            print(path)
        elif args.command == "import-baseline":
            if not args.target_empty:
                raise SyncError("baseline import requires --target-empty; refuse to overwrite an unknown target")
            if not args.confirm:
                raise SyncError("baseline import requires --confirm")
            package = args.package
            if args.release:
                package = str(download_package(repo, args.release, Path(args.download_root) / args.release))
            if not package:
                raise SyncError("import-baseline requires --package or --release")
            baseline_manifest = _package_manifest(Path(package).resolve())
            _require_role(baseline_manifest, {"source", "primary"}, operation="baseline import")
            _run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "geo_migrate.py"),
                    "import",
                    "--package",
                    package,
                    "--encryption-key-file",
                    args.passphrase_file,
                    "--secret-root",
                    args.secret_root,
                    "--dify-runtime-root",
                    args.dify_runtime_root,
                    "--dify-state-file",
                    args.dify_state_file,
                    "--target-project",
                    args.target_project,
                    "--dify-project",
                    args.dify_project,
                    "--target-empty",
                    "--confirm",
                ]
            )
        elif args.command == "export-incremental-upload":
            if args.source_role != "primary" or args.source_environment != "production":
                raise SyncError("incremental export is only allowed from the production primary")
            current = _command_export(args)
            parent = Path(args.parent_package).resolve()
            delta = _build_delta(
                current,
                parent,
                Path(args.passphrase_file).resolve(),
                Path(args.output_root).resolve(),
                args.parent_release,
            )
            manifest = _package_manifest(delta)
            manifest["release_tag"] = args.release or manifest["archive_id"]
            (delta / "manifest.json").write_bytes(_canonical_json(manifest))
            tag = upload_package(delta, repo=repo, release=args.release, chunk_size=DEFAULT_CHUNK_SIZE, target_commit=None)
            print(json.dumps({"release": tag, "package": str(delta), "changed": manifest["changes"]}, sort_keys=True))
        elif args.command == "apply-incremental":
            if not args.overwrite_test_replica:
                raise SyncError("incremental import requires --overwrite-test-replica")
            path = download_package(repo, args.release, Path(args.package_cache) / args.release)
            manifest = _package_manifest(path)
            if manifest.get("schema_version") != DELTA_SCHEMA:
                raise SyncError("apply-incremental requires a delta release")
            _require_role(manifest, {"primary"}, operation="incremental apply")
            with tempfile.TemporaryDirectory(prefix="geo-sync-apply-") as temporary:
                materialized = Path(temporary) / "materialized"
                base_manifest = _materialize_release(
                    repo,
                    args.release,
                    Path(args.passphrase_file).resolve(),
                    Path(args.package_cache).resolve(),
                    materialized,
                    set(),
                )
                package = _write_materialized_package(
                    materialized / "payload",
                    base_manifest,
                    Path(args.passphrase_file).resolve(),
                    materialized,
                )
                _run(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "geo_migrate.py"),
                        "import",
                        "--package",
                        str(package),
                        "--encryption-key-file",
                        args.passphrase_file,
                        "--secret-root",
                        args.secret_root,
                        "--dify-runtime-root",
                        args.dify_runtime_root,
                        "--dify-state-file",
                        args.dify_state_file,
                        "--target-project",
                        args.target_project,
                        "--dify-project",
                        args.dify_project,
                        "--replace-test-replica",
                        "--confirm",
                    ]
                )
            print(json.dumps({"applied": args.release, "parent": manifest.get("parent_release")}, sort_keys=True))
        return 0
    except (MigrationError, SyncError) as error:
        print(f"geo-sync error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
