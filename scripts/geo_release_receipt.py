"""Write a non-secret receipt for one canonical GEO runtime."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


SCHEMA_VERSION = "geo-release-receipt-v2"
RELEASE_ENV_NAME = "GEO_RELEASE_COMMIT"
_ENV_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_CONTENT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_DIFY_COMMIT = re.compile(r'^readonly DIFY_COMMIT="([0-9a-f]{40})"$', re.MULTILINE)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: Sequence[str], *, cwd: Path, check: bool = True) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(command)}: {detail}")
    return result.stdout.strip() if result.returncode == 0 else ""


def read_release_commit(env_file: Path) -> str | None:
    if not env_file.is_file():
        return None
    release: str | None = None
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_ASSIGNMENT.fullmatch(line.removeprefix("export ").lstrip())
        if match and match.group(1) == RELEASE_ENV_NAME:
            release = match.group(2).strip().strip("'\"")
    return release


def git_identity(repo_root: Path) -> dict[str, Any]:
    commit = run(["git", "rev-parse", "HEAD"], cwd=repo_root)
    dirty_lines = run(["git", "status", "--porcelain"], cwd=repo_root).splitlines()
    return {
        "commit": commit,
        "dirty": bool(dirty_lines),
        "dirty_entry_count": len(dirty_lines),
    }


def alembic_heads(repo_root: Path) -> list[str]:
    output = run(["uv", "run", "alembic", "heads"], cwd=repo_root, check=False)
    heads = []
    for line in output.splitlines():
        candidate = line.split()[0] if line.split() else ""
        if candidate:
            heads.append(candidate)
    return sorted(set(heads))


def _image_digests(image_id: str, *, repo_root: Path) -> list[str]:
    if not image_id:
        return []
    raw = run(["docker", "image", "inspect", image_id], cwd=repo_root, check=False)
    if not raw:
        return []
    payload = json.loads(raw)
    if not payload:
        return []
    return sorted(payload[0].get("RepoDigests") or [])


def runtime_containers(project: str, *, repo_root: Path) -> list[dict[str, Any]]:
    ids = run(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            "{{.ID}}",
        ],
        cwd=repo_root,
        check=False,
    ).splitlines()
    if not ids:
        return []
    raw = run(["docker", "inspect", *ids], cwd=repo_root)
    containers = []
    for value in json.loads(raw):
        config = value.get("Config") or {}
        labels = config.get("Labels") or {}
        release_values = [
            entry.split("=", 1)[1]
            for entry in config.get("Env") or []
            if entry.startswith(f"{RELEASE_ENV_NAME}=")
        ]
        image_id = value.get("Image", "")
        containers.append(
            {
                "service": labels.get("com.docker.compose.service", "unknown"),
                "container_name": value.get("Name", "").removeprefix("/"),
                "configured_image": config.get("Image", ""),
                "image_id": image_id,
                "content_digest": image_id if _CONTENT_DIGEST.fullmatch(image_id) else None,
                "repo_digests": _image_digests(image_id, repo_root=repo_root),
                "release_commit": release_values[-1] if release_values else None,
                "state": (value.get("State") or {}).get("Status", "unknown"),
            }
        )
    return sorted(containers, key=lambda item: (item["service"], item["container_name"]))


def release_tracked_services(repo_root: Path, mode: str) -> list[str]:
    manifest = json.loads((repo_root / "infra/geo-stack-manifest.json").read_text(encoding="utf-8"))
    configured = manifest.get("release_tracked_services", {}).get(mode)
    if not isinstance(configured, list) or not configured or not all(
        isinstance(item, str) and item for item in configured
    ):
        raise ValueError(f"release-tracked service contract is missing for mode {mode}")
    return sorted(set(configured))


def runtime_manifest(repo_root: Path) -> dict[str, Any]:
    value = json.loads(
        (repo_root / "infra/geo-stack-manifest.json").read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("GEO stack manifest must be an object")
    return value


def dify_source_commit(repo_root: Path) -> str:
    source = (repo_root / "scripts/bootstrap_dify_runtime.sh").read_text(encoding="utf-8")
    match = _DIFY_COMMIT.search(source)
    if match is None:
        raise ValueError("Dify bootstrap does not declare a pinned source commit")
    return match.group(1)


def release_match_summary(
    containers: Sequence[dict[str, Any]],
    *,
    tracked_services: Sequence[str],
    source_commit: str,
    declared_release: str | None,
) -> dict[str, Any]:
    tracked = set(tracked_services)
    present = {str(item["service"]) for item in containers}
    tracked_containers = [item for item in containers if item["service"] in tracked]
    missing_services = sorted(tracked - present)
    missing_commits = sorted(
        {str(item["service"]) for item in tracked_containers if item["release_commit"] is None}
    )
    observed = sorted(
        {str(item["release_commit"]) for item in tracked_containers if item["release_commit"] is not None}
    )
    declared_matches = declared_release == source_commit
    matches = (
        declared_matches
        and bool(tracked_containers)
        and not missing_services
        and not missing_commits
        and all(item["release_commit"] == source_commit for item in tracked_containers)
    )
    return {
        "release_tracked_services": sorted(tracked),
        "missing_release_tracked_services": missing_services,
        "missing_release_commit_services": missing_commits,
        "runtime_release_commits": observed,
        "declared_release_matches_source": declared_matches,
        "runtime_release_matches_source": matches,
    }


def build_receipt(
    *,
    repo_root: Path,
    mode: str,
    project: str,
    dify_project: str = "geo-dify",
    env_file: Path,
    compose_files: Sequence[Path],
) -> dict[str, Any]:
    git = git_identity(repo_root)
    expected_release = read_release_commit(env_file)
    containers = runtime_containers(project, repo_root=repo_root)
    dify_containers = runtime_containers(dify_project, repo_root=repo_root)
    manifest = runtime_manifest(repo_root)
    required_dify = manifest.get("dify_required_services")
    if not isinstance(required_dify, list) or not all(
        isinstance(item, str) and item for item in required_dify
    ):
        raise ValueError("Dify required service contract is missing")
    observed_dify = {str(item["service"]) for item in dify_containers}
    missing_dify = sorted(set(required_dify) - observed_dify)
    all_containers = [*containers, *dify_containers]
    images_addressed = bool(all_containers) and all(
        item["content_digest"] is not None for item in all_containers
    )
    release_summary = release_match_summary(
        containers,
        tracked_services=release_tracked_services(repo_root, mode),
        source_commit=git["commit"],
        declared_release=expected_release,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "project": project,
        "dify_project": dify_project,
        "source": git,
        "declared_release_commit": expected_release,
        **release_summary,
        "dify_source_commit": dify_source_commit(repo_root),
        "missing_dify_services": missing_dify,
        "all_runtime_images_content_addressed": images_addressed,
        "alembic_heads": alembic_heads(repo_root),
        "stack_manifest_sha256": sha256_file(repo_root / "infra/geo-stack-manifest.json"),
        "compose_files": [
            {
                "path": str(path.relative_to(repo_root)),
                "sha256": sha256_file(path),
            }
            for path in compose_files
        ],
        "containers": containers,
        "dify_containers": dify_containers,
    }


def write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--mode", choices=("internal", "production"), required=True)
    parser.add_argument("--project", default="geo")
    parser.add_argument("--dify-project", default="geo-dify")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--compose-file", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-running", action="store_true")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    compose_files = [path.resolve() for path in args.compose_file]
    try:
        payload = build_receipt(
            repo_root=repo_root,
            mode=args.mode,
            project=args.project,
            dify_project=args.dify_project,
            env_file=args.env_file.resolve(),
            compose_files=compose_files,
        )
        if args.require_running and not payload["containers"]:
            raise RuntimeError(f"no running containers found for Compose project {args.project}")
        if args.require_running and not payload["runtime_release_matches_source"]:
            raise RuntimeError("running GEO container release commits do not match the source Git SHA")
        if args.require_running and not payload["dify_containers"]:
            raise RuntimeError(f"no running containers found for Dify project {args.dify_project}")
        if args.require_running and payload["missing_dify_services"]:
            raise RuntimeError("running Dify project is missing required services")
        if args.require_running and not payload["all_runtime_images_content_addressed"]:
            raise RuntimeError("one or more runtime containers have no content-addressed image ID")
        write_receipt(args.output.resolve(), payload)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"geo release receipt error: {error}", file=sys.stderr)
        return 2
    print(f"release receipt: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
