from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_au_p0a_env_template import verify_au_p0a_env_template  # noqa: E402


BOOTSTRAP_VERSION = "au_p0a_env_file_bootstrap_v1"
DEFAULT_TEMPLATE_PATH = ".env.au-p0a.example"
DEFAULT_ENV_FILE = ".env.au-p0a"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-env-bootstrap-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_env_file_bootstrap_hash(report: dict[str, Any]) -> str:
    payload = dict(report)
    payload.pop("env_file_bootstrap_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_to_root(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except (OSError, ValueError):
        return ""


def _git_status_flag(args: list[str]) -> bool | None:
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    return result.returncode == 0


def _load_env_entries(path: Path) -> tuple[int, list[str]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0, []
    errors: list[str] = []
    entry_count = 0
    for line_number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            errors.append(f"env_file_line_invalid:{line_number}")
            continue
        key = stripped.split("=", 1)[0].strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            errors.append(f"env_file_key_invalid:{line_number}")
            continue
        entry_count += 1
    return entry_count, errors


def _env_file_hygiene(path: Path) -> dict[str, Any]:
    exists = path.exists()
    entry_count, parse_errors = _load_env_entries(path)
    relative_path = _relative_to_root(path)
    inside_workspace = bool(relative_path)
    git_ignored: bool | None = None
    git_tracked: bool | None = None
    if inside_workspace:
        git_ignored = _git_status_flag(["git", "check-ignore", "--quiet", "--", relative_path])
        git_tracked = _git_status_flag(["git", "ls-files", "--error-unmatch", "--", relative_path])

    file_mode = ""
    permission_safe = False
    if exists:
        mode = path.stat().st_mode & 0o777
        file_mode = f"{mode:04o}"
        permission_safe = bool(mode & stat.S_IRUSR) and bool(mode & stat.S_IWUSR) and not bool(mode & 0o077)

    git_safe = True
    if inside_workspace:
        git_safe = git_tracked is False and git_ignored is True
    errors = list(parse_errors)
    warnings: list[str] = []
    if exists and not permission_safe:
        errors.append("env_file_permissions_not_0600")
    if exists and not git_safe:
        if git_tracked is True:
            errors.append("env_file_tracked_by_git")
        if git_ignored is not True:
            errors.append("env_file_not_gitignored")
        if git_tracked is None or git_ignored is None:
            warnings.append("env_file_git_status_unavailable")

    return {
        "path": str(path),
        "exists": exists,
        "entry_count": entry_count,
        "inside_workspace": inside_workspace,
        "relative_path": relative_path,
        "git_ignored": git_ignored,
        "git_tracked": git_tracked,
        "git_safe": git_safe,
        "file_mode": file_mode,
        "permission_safe": permission_safe,
        "hygiene_required": exists,
        "hygiene_ready": exists and permission_safe and git_safe and not parse_errors,
        "errors": errors,
        "warnings": warnings,
        "secret_redacted": True,
    }


def bootstrap_au_p0a_env_file(
    *,
    template_path: Path = Path(DEFAULT_TEMPLATE_PATH),
    env_file_path: Path = Path(DEFAULT_ENV_FILE),
    output_path: Path | None = None,
    overwrite: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    template_verification = verify_au_p0a_env_template(template_path=template_path, generated_at=generated_at)
    errors: list[str] = []
    warnings: list[str] = []
    action = "noop_existing_env_file"
    created = False
    overwritten = False

    if template_verification.get("status") != "pass":
        errors.append("template_verifier_not_pass")
        action = "blocked_template_verification"
    elif env_file_path.exists() and not overwrite:
        action = "noop_existing_env_file"
    else:
        try:
            env_file_path.parent.mkdir(parents=True, exist_ok=True)
            if env_file_path.exists() and overwrite:
                overwritten = True
            shutil.copyfile(template_path, env_file_path)
            env_file_path.chmod(0o600)
            created = not overwritten
            action = "overwrote_env_file_from_template" if overwritten else "created_env_file_from_template"
        except OSError as exc:
            errors.append(f"env_file_bootstrap_failed:{exc.__class__.__name__}")
            action = "bootstrap_failed"

    hygiene = _env_file_hygiene(env_file_path)
    errors.extend(str(item) for item in hygiene.get("errors", []))
    warnings.extend(str(item) for item in hygiene.get("warnings", []))

    template_entry: dict[str, Any] = {
        "path": str(template_path),
        "exists": template_path.exists(),
        "template_verifier_status": template_verification.get("status", ""),
        "template_verification_hash": template_verification.get("template_verification_hash", ""),
    }
    if template_path.is_file():
        template_entry["file_sha256"] = _file_sha256(template_path)
    env_file_entry: dict[str, Any] = {
        "path": str(env_file_path),
        "exists": env_file_path.exists(),
        "created": created,
        "overwritten": overwritten,
        "hygiene": hygiene,
    }
    if env_file_path.is_file():
        env_file_entry["file_sha256"] = _file_sha256(env_file_path)

    report: dict[str, Any] = {
        "env_file_bootstrap_version": BOOTSTRAP_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if not errors else "fail",
        "env_file_bootstrap_ready": not errors and hygiene.get("hygiene_ready") is True,
        "output_path": str(output_path) if output_path else "",
        "action": action,
        "overwrite": overwrite,
        "template": template_entry,
        "env_file": env_file_entry,
        "summary": {
            "template_verifier_status": template_verification.get("status", ""),
            "template_hash_valid": bool(template_verification.get("template_verification_hash")),
            "env_file_exists": env_file_path.exists(),
            "env_file_created": created,
            "env_file_overwritten": overwritten,
            "env_file_git_ignored": hygiene.get("git_ignored"),
            "env_file_git_tracked": hygiene.get("git_tracked"),
            "env_file_permission_safe": hygiene.get("permission_safe") is True,
            "env_file_hygiene_ready": hygiene.get("hygiene_ready") is True,
            "env_file_mode": hygiene.get("file_mode", ""),
            "env_file_entry_count": hygiene.get("entry_count", 0),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "next_action": "fill_provider_keys_and_database_url" if not errors else "fix_env_file_bootstrap",
        },
        "next_commands": [
            "edit .env.au-p0a",
            "make au-p0a-env",
            "make verify-au-p0a-env",
            "make au-p0a-environment-checklist",
            "make verify-au-p0a-environment-checklist",
        ],
        "verification_commands": [
            "make verify-au-p0a-env-bootstrap",
            "make au-p0a-env",
            "make verify-au-p0a-env",
        ],
        "evidence_outputs": [
            str(output_path or DEFAULT_OUTPUT_PATH),
            "docs/runtime_preflight/au-p0a-env-latest.json",
            "docs/runtime_preflight/au-p0a-environment-checklist-latest.json",
        ],
        "errors": errors,
        "warnings": warnings,
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "recorded_fields": ["path", "exists", "mode", "file_sha256", "entry_count", "git_ignored", "git_tracked"],
            "secret_redacted": True,
        },
    }
    report["env_file_bootstrap_hash"] = compute_env_file_bootstrap_hash(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap the local AU P0a env file from the committed template")
    parser.add_argument(
        "--template-path",
        default=os.environ.get("GENO_AU_P0A_ENV_TEMPLATE_PATH", DEFAULT_TEMPLATE_PATH),
        help="Path to the committed AU P0a env template.",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("GENO_AU_P0A_ENV_FILE", DEFAULT_ENV_FILE),
        help="Path to the local AU P0a env file.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_ENV_BOOTSTRAP_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the bootstrap audit JSON.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing env file with the template.")
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    report = bootstrap_au_p0a_env_file(
        template_path=Path(args.template_path),
        env_file_path=Path(args.env_file),
        output_path=output_path,
        overwrite=args.overwrite,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if report["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
