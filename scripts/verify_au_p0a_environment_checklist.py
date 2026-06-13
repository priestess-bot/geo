from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_au_p0a_environment_checklist import (  # noqa: E402
    CHECKLIST_VERSION,
    DEFAULT_OUTPUT_PATH,
    compute_environment_checklist_hash,
)


REQUIRED_FIELDS = (
    "environment_checklist_version",
    "generated_at",
    "status",
    "environment_checklist_ready",
    "next_action",
    "paths",
    "summary",
    "runbook_source",
    "runbook_verifier",
    "environment_report_source",
    "environment_report",
    "environment_report_verifier",
    "env_file_hygiene",
    "status_report_summary",
    "required_environment",
    "recommended_environment",
    "setup_commands",
    "verification_commands",
    "evidence_outputs",
    "current_boundary",
    "environment_checklist_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _validate_tasks(label: str, tasks: list[object], errors: list[str]) -> tuple[int, int, list[str]]:
    present_count = 0
    missing: list[str] = []
    for item in tasks:
        task = _as_dict(item)
        name = task.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{label}_task_name_missing")
            continue
        for field in (
            "required",
            "present",
            "source",
            "value_length",
            "sha256_prefix",
            "secret_redacted",
            "action",
            "accepted_sources",
        ):
            if field not in task:
                errors.append(f"{label}_task_field_missing:{name}:{field}")
        if "value" in task or "raw_value" in task:
            errors.append(f"{label}_task_raw_value_leaked:{name}")
        if task.get("secret_redacted") is not True:
            errors.append(f"{label}_task_secret_redaction_missing:{name}")
        if task.get("source") not in {"process", "env_file", "missing"}:
            errors.append(f"{label}_task_source_invalid:{name}")
        if task.get("present") is True:
            present_count += 1
            if not isinstance(task.get("value_length"), int) or task.get("value_length") <= 0:
                errors.append(f"{label}_task_value_length_invalid:{name}")
            if not isinstance(task.get("sha256_prefix"), str) or len(task.get("sha256_prefix")) != 12:
                errors.append(f"{label}_task_sha256_prefix_invalid:{name}")
        elif task.get("present") is False:
            missing.append(name)
            if task.get("value_length") not in {0, None}:
                errors.append(f"{label}_task_missing_value_length_invalid:{name}")
            if task.get("sha256_prefix") not in {"", None}:
                errors.append(f"{label}_task_missing_sha256_prefix_invalid:{name}")
        else:
            errors.append(f"{label}_task_present_invalid:{name}")
    return len(tasks), present_count, sorted(missing)


def _command_ids(commands: list[object]) -> set[str]:
    return {str(_as_dict(item).get("id", "")) for item in commands}


def _validate_env_file_hygiene(hygiene: dict[str, Any], errors: list[str]) -> tuple[bool, list[str], list[str]]:
    for field in (
        "path",
        "exists",
        "entry_count",
        "inside_workspace",
        "relative_path",
        "git_ignored",
        "git_tracked",
        "git_safe",
        "file_mode",
        "permission_safe",
        "hygiene_required",
        "hygiene_ready",
        "errors",
        "warnings",
        "secret_redacted",
    ):
        if field not in hygiene:
            errors.append(f"env_file_hygiene_field_missing:{field}")
    if hygiene.get("secret_redacted") is not True:
        errors.append("env_file_hygiene_secret_redaction_missing")
    if "value" in hygiene or "raw_value" in hygiene:
        errors.append("env_file_hygiene_raw_value_leaked")
    hygiene_errors = [str(item) for item in _as_list(hygiene.get("errors"))]
    hygiene_warnings = [str(item) for item in _as_list(hygiene.get("warnings"))]
    if hygiene.get("hygiene_required") is True and hygiene.get("permission_safe") is not True:
        errors.append("env_file_hygiene_permission_unsafe")
    if hygiene.get("hygiene_required") is True and hygiene.get("git_safe") is not True:
        errors.append("env_file_hygiene_git_unsafe")
    expected_ready = not hygiene_errors and hygiene.get("hygiene_ready") is True
    return expected_ready, hygiene_errors, hygiene_warnings


def _find_forbidden_secret_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {"value", "raw_value"}:
                findings.append(child_path)
            findings.extend(_find_forbidden_secret_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_secret_fields(child, path=f"{path}[{index}]"))
    return findings


def verify_au_p0a_environment_checklist(
    checklist: Any,
    *,
    path: Path | None = None,
    require_ready_environment: bool = False,
) -> dict[str, Any]:
    if not isinstance(checklist, dict):
        return {
            "status": "fail",
            "errors": ["environment_checklist_not_json_object"],
            "hash_valid": False,
            "environment_checklist_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in checklist:
            errors.append(f"field_missing:{field}")
    if checklist.get("environment_checklist_version") != CHECKLIST_VERSION:
        errors.append("environment_checklist_version_invalid")
    for forbidden_path in _find_forbidden_secret_fields(checklist):
        errors.append(f"forbidden_secret_field:{forbidden_path}")

    expected_hash = checklist.get("environment_checklist_hash")
    computed_hash = compute_environment_checklist_hash(checklist)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("environment_checklist_hash_mismatch")

    summary = _as_dict(checklist.get("summary"))
    runbook_verifier = _as_dict(checklist.get("runbook_verifier"))
    env_report = _as_dict(checklist.get("environment_report"))
    env_verifier = _as_dict(checklist.get("environment_report_verifier"))
    env_file_hygiene = _as_dict(checklist.get("env_file_hygiene"))
    env_file_hygiene_ready, env_file_hygiene_errors, env_file_hygiene_warnings = _validate_env_file_hygiene(
        env_file_hygiene, errors
    )
    required_total, required_present, required_missing = _validate_tasks(
        "required", _as_list(checklist.get("required_environment")), errors
    )
    recommended_total, _, recommended_missing = _validate_tasks(
        "recommended", _as_list(checklist.get("recommended_environment")), errors
    )
    if summary.get("required_count") != required_total:
        errors.append("summary_required_count_mismatch")
    if summary.get("required_present_count") != required_present:
        errors.append("summary_required_present_count_mismatch")
    if summary.get("missing_required_count") != len(required_missing):
        errors.append("summary_missing_required_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("missing_required"))) != required_missing:
        errors.append("summary_missing_required_mismatch")
    if summary.get("recommended_count") != recommended_total:
        errors.append("summary_recommended_count_mismatch")
    if summary.get("missing_recommended_count") != len(recommended_missing):
        errors.append("summary_missing_recommended_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("missing_recommended"))) != recommended_missing:
        errors.append("summary_missing_recommended_mismatch")
    if summary.get("env_file_hygiene_ready") is not env_file_hygiene_ready:
        errors.append("summary_env_file_hygiene_ready_mismatch")
    if summary.get("env_file_hygiene_error_count") != len(env_file_hygiene_errors):
        errors.append("summary_env_file_hygiene_error_count_mismatch")

    runbook_ok = runbook_verifier.get("status") == "pass" and runbook_verifier.get("hash_valid") is True
    env_ok = env_verifier.get("status") == "pass" and env_verifier.get("hash_valid") is True
    env_ready = env_report.get("ready_for_real_batch") is True
    expected_ready = runbook_ok and env_ok and env_ready and env_file_hygiene_ready and not required_missing
    if checklist.get("environment_checklist_ready") is not expected_ready:
        errors.append("environment_checklist_ready_mismatch")
    if checklist.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")
    expected_next = (
        "run_make_au_p0a_runbook"
        if not runbook_ok
        else "populate_required_environment"
        if required_missing
        else "fix_au_p0a_environment_report"
        if not env_ok
        else "run_au_p0a_runbook_dry_run"
    )
    if checklist.get("next_action") != expected_next:
        errors.append("next_action_mismatch")
    if require_ready_environment and not expected_ready:
        errors.append("p0a_environment_not_ready")

    setup_ids = _command_ids(_as_list(checklist.get("setup_commands")))
    verification_ids = _command_ids(_as_list(checklist.get("verification_commands")))
    for command_id in {"verify_env_template", "copy_env_template", "build_runbook", "build_env_report", "verify_env_report"}:
        if command_id not in setup_ids:
            errors.append(f"setup_command_missing:{command_id}")
    for command_id in {"hard_env_gate", "dry_run_runbook", "readiness_with_db", "refresh_status"}:
        if command_id not in verification_ids:
            errors.append(f"verification_command_missing:{command_id}")
    if len(_as_list(checklist.get("evidence_outputs"))) < 4:
        errors.append("evidence_outputs_incomplete")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "environment_checklist_version": checklist.get("environment_checklist_version", ""),
        "environment_checklist_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_environment_checklist_hash": computed_hash,
        "hash_valid": hash_valid,
        "environment_checklist_ready": expected_ready,
        "next_action": expected_next,
        "missing_required": required_missing,
        "missing_recommended": recommended_missing,
        "env_file_hygiene_ready": env_file_hygiene_ready,
        "env_file_hygiene_errors": env_file_hygiene_errors,
        "env_file_hygiene_warnings": env_file_hygiene_warnings,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0a environment setup checklist JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0a environment checklist JSON.",
    )
    parser.add_argument(
        "--require-ready-environment",
        action="store_true",
        help="Fail unless the checklist proves the AU P0a environment is ready.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        checklist = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["environment_checklist_file_missing"],
            "hash_valid": False,
            "environment_checklist_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"environment_checklist_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "environment_checklist_ready": False,
        }
    else:
        result = verify_au_p0a_environment_checklist(
            checklist,
            path=path,
            require_ready_environment=args.require_ready_environment,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
