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

from scripts.build_au_p0b_google_execution_checklist import (  # noqa: E402
    CHECKLIST_VERSION,
    DEFAULT_OUTPUT_PATH,
    compute_google_execution_checklist_hash,
)


REQUIRED_FIELDS = (
    "execution_checklist_version",
    "generated_at",
    "status",
    "google_execution_checklist_ready",
    "google_main_scoring_allowed",
    "limited_coverage",
    "next_action",
    "paths",
    "summary",
    "runbook_source",
    "runbook_verifier",
    "playwright_environment_source",
    "playwright_environment",
    "playwright_environment_verifier",
    "status_report_source",
    "status_report",
    "status_report_verifier",
    "package_source",
    "evidence_package",
    "evidence_package_verifier",
    "required_environment",
    "full_run_required_environment",
    "selector_groups",
    "file_checks",
    "dependency_checks",
    "setup_commands",
    "execution_commands",
    "verification_commands",
    "work_items",
    "evidence_outputs",
    "current_boundary",
    "google_execution_checklist_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


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


def _command_ids(commands: list[object]) -> set[str]:
    return {str(_as_dict(item).get("id", "")) for item in commands}


def _validate_env_tasks(label: str, tasks: list[object], errors: list[str]) -> tuple[int, list[str]]:
    missing: list[str] = []
    for item in tasks:
        task = _as_dict(item)
        name = task.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{label}_task_name_missing")
            continue
        for field in (
            "gate",
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
        if task.get("secret_redacted") is not True:
            errors.append(f"{label}_task_secret_redaction_missing:{name}")
        if task.get("source") not in {"process", "env_file", "missing"}:
            errors.append(f"{label}_task_source_invalid:{name}")
        if task.get("present") is True:
            if not isinstance(task.get("value_length"), int) or task.get("value_length") <= 0:
                errors.append(f"{label}_task_value_length_invalid:{name}")
            if not isinstance(task.get("sha256_prefix"), str) or len(task.get("sha256_prefix")) != 12:
                errors.append(f"{label}_task_sha256_prefix_invalid:{name}")
            if task.get("truthy") is False:
                missing.append(name)
        elif task.get("present") is False:
            missing.append(name)
            if task.get("value_length") not in {0, None}:
                errors.append(f"{label}_task_missing_value_length_invalid:{name}")
            if task.get("sha256_prefix") not in {"", None}:
                errors.append(f"{label}_task_missing_sha256_prefix_invalid:{name}")
        else:
            errors.append(f"{label}_task_present_invalid:{name}")
    return len(tasks), sorted(missing)


def _validate_selector_tasks(tasks: list[object], errors: list[str]) -> tuple[int, list[str]]:
    missing: list[str] = []
    for item in tasks:
        task = _as_dict(item)
        group = task.get("group")
        if not isinstance(group, str) or not group:
            errors.append("selector_group_name_missing")
            continue
        for field in (
            "candidate_names",
            "present",
            "selected_name",
            "source",
            "value_length",
            "sha256_prefix",
            "secret_redacted",
            "action",
        ):
            if field not in task:
                errors.append(f"selector_group_field_missing:{group}:{field}")
        if task.get("secret_redacted") is not True:
            errors.append(f"selector_group_secret_redaction_missing:{group}")
        if task.get("present") is True:
            if not task.get("selected_name"):
                errors.append(f"selector_group_selected_name_missing:{group}")
            if not isinstance(task.get("value_length"), int) or task.get("value_length") <= 0:
                errors.append(f"selector_group_value_length_invalid:{group}")
            if not isinstance(task.get("sha256_prefix"), str) or len(task.get("sha256_prefix")) != 12:
                errors.append(f"selector_group_sha256_prefix_invalid:{group}")
        elif task.get("present") is False:
            missing.append(group)
        else:
            errors.append(f"selector_group_present_invalid:{group}")
    return len(tasks), sorted(missing)


def _validate_dependency_tasks(tasks: list[object], errors: list[str]) -> list[str]:
    missing: list[str] = []
    for item in tasks:
        task = _as_dict(item)
        name = task.get("name")
        if not isinstance(name, str) or not name:
            errors.append("dependency_name_missing")
            continue
        if task.get("secret_redacted") is not True:
            errors.append(f"dependency_secret_redaction_missing:{name}")
        if task.get("present") is True:
            continue
        if task.get("present") is False:
            missing.append(name)
        else:
            errors.append(f"dependency_present_invalid:{name}")
    return sorted(missing)


def _file_gate_issues(tasks: list[object]) -> list[str]:
    issues: list[str] = []
    for item in tasks:
        task = _as_dict(item)
        name = str(task.get("name", ""))
        expected_type = str(task.get("expected_type", ""))
        present = task.get("present") is True
        if name == "MANUAL_BACKFILL_PATH" and (not present or task.get("is_file") is not True):
            issues.append(f"{name}:file_missing")
        elif present and expected_type == "file" and task.get("is_file") is not True:
            issues.append(f"{name}:file_missing")
        elif present and expected_type == "directory" and task.get("is_dir") is not True:
            issues.append(f"{name}:directory_missing")
    return sorted(issues)


def _expected_next_action(
    *,
    runbook_ok: bool,
    env_ok: bool,
    ready_for_smoke: bool,
    env_next_action: str,
    remaining_blockers: list[str],
    google_allowed: bool,
) -> str:
    if not runbook_ok:
        return "run_make_au_p0b_google_runbook"
    if not env_ok or not ready_for_smoke:
        return env_next_action or "populate_google_playwright_smoke_environment"
    if any(blocker.startswith("playwright_smoke:") for blocker in remaining_blockers):
        return "run_google_playwright_smoke"
    if any(blocker.startswith("manual_backfill:") for blocker in remaining_blockers):
        return "run_verify_google_manual_backfill"
    if any(blocker.startswith("health:") or blocker.startswith("health_manifest:") for blocker in remaining_blockers):
        return "run_au_p0b_google_spike_health"
    if any(blocker.startswith("spike:") or blocker.startswith("spike_manifest:") for blocker in remaining_blockers):
        return "run_au_p0b_google_spike"
    if not google_allowed:
        return "run_au_p0b_google_status"
    return "allow_google_into_main_scoring_denominator"


def verify_au_p0b_google_execution_checklist(
    checklist: Any,
    *,
    path: Path | None = None,
    require_google_main_scoring_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(checklist, dict):
        return {
            "status": "fail",
            "errors": ["execution_checklist_not_json_object"],
            "hash_valid": False,
            "google_execution_checklist_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in checklist:
            errors.append(f"field_missing:{field}")
    if checklist.get("execution_checklist_version") != CHECKLIST_VERSION:
        errors.append("execution_checklist_version_invalid")
    for forbidden_path in _find_forbidden_secret_fields(checklist):
        errors.append(f"forbidden_secret_field:{forbidden_path}")

    expected_hash = checklist.get("google_execution_checklist_hash")
    computed_hash = compute_google_execution_checklist_hash(checklist)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("google_execution_checklist_hash_mismatch")

    summary = _as_dict(checklist.get("summary"))
    runbook_verifier = _as_dict(checklist.get("runbook_verifier"))
    env_summary = _as_dict(checklist.get("playwright_environment"))
    env_verifier = _as_dict(checklist.get("playwright_environment_verifier"))
    status_verifier = _as_dict(checklist.get("status_report_verifier"))
    package = _as_dict(checklist.get("evidence_package"))
    package_verifier = _as_dict(checklist.get("evidence_package_verifier"))
    required_count, missing_required = _validate_env_tasks(
        "required_environment",
        _as_list(checklist.get("required_environment")),
        errors,
    )
    full_required_count, missing_full_required = _validate_env_tasks(
        "full_run_required_environment",
        _as_list(checklist.get("full_run_required_environment")),
        errors,
    )
    selector_count, missing_selectors = _validate_selector_tasks(_as_list(checklist.get("selector_groups")), errors)
    missing_dependencies = _validate_dependency_tasks(_as_list(checklist.get("dependency_checks")), errors)
    file_issues = _file_gate_issues(_as_list(checklist.get("file_checks")))
    remaining_blockers = [str(item) for item in _as_list(package.get("remaining_blockers"))]
    if not remaining_blockers:
        remaining_blockers = [str(item) for item in _as_list(summary.get("remaining_blockers"))]

    if summary.get("required_environment_count") != required_count:
        errors.append("summary_required_environment_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("missing_required_environment"))) != missing_required:
        errors.append("summary_missing_required_environment_mismatch")
    if summary.get("missing_required_environment_count") != len(missing_required):
        errors.append("summary_missing_required_environment_count_mismatch")
    if summary.get("full_run_required_environment_count") != full_required_count:
        errors.append("summary_full_run_required_environment_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("missing_full_run_required_environment"))) != missing_full_required:
        errors.append("summary_missing_full_run_required_environment_mismatch")
    if summary.get("missing_full_run_required_environment_count") != len(missing_full_required):
        errors.append("summary_missing_full_run_required_environment_count_mismatch")
    if summary.get("selector_group_count") != selector_count:
        errors.append("summary_selector_group_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("missing_selector_groups"))) != missing_selectors:
        errors.append("summary_missing_selector_groups_mismatch")
    if summary.get("missing_selector_group_count") != len(missing_selectors):
        errors.append("summary_missing_selector_group_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("missing_dependencies"))) != missing_dependencies:
        errors.append("summary_missing_dependencies_mismatch")
    if summary.get("missing_dependency_count") != len(missing_dependencies):
        errors.append("summary_missing_dependency_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("file_gate_issues"))) != file_issues:
        errors.append("summary_file_gate_issues_mismatch")
    if summary.get("file_gate_issue_count") != len(file_issues):
        errors.append("summary_file_gate_issue_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("remaining_blockers"))) != sorted(remaining_blockers):
        errors.append("summary_remaining_blockers_mismatch")
    if summary.get("remaining_blocker_count") != len(remaining_blockers):
        errors.append("summary_remaining_blocker_count_mismatch")

    runbook_ok = runbook_verifier.get("status") == "pass" and runbook_verifier.get("hash_valid") is True
    env_ok = env_verifier.get("status") == "pass" and env_verifier.get("hash_valid") is True
    status_ok = status_verifier.get("status") == "pass" and status_verifier.get("hash_valid") is True
    package_ok = package_verifier.get("status") == "pass" and package_verifier.get("hash_valid") is True
    google_allowed = package.get("google_main_scoring_allowed") is True
    expected_ready = runbook_ok and env_ok and status_ok and package_ok and google_allowed and not remaining_blockers
    if checklist.get("google_execution_checklist_ready") is not expected_ready:
        errors.append("google_execution_checklist_ready_mismatch")
    if checklist.get("google_main_scoring_allowed") is not google_allowed:
        errors.append("google_main_scoring_allowed_mismatch")
    if checklist.get("limited_coverage") is not (not google_allowed):
        errors.append("limited_coverage_mismatch")
    if checklist.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")
    expected_next = _expected_next_action(
        runbook_ok=runbook_ok,
        env_ok=env_ok,
        ready_for_smoke=env_summary.get("ready_for_playwright_smoke") is True,
        env_next_action=str(env_summary.get("next_action") or ""),
        remaining_blockers=remaining_blockers,
        google_allowed=google_allowed,
    )
    if checklist.get("next_action") != expected_next:
        errors.append("next_action_mismatch")
    if require_google_main_scoring_ready and not expected_ready:
        errors.append("google_execution_not_ready")

    setup_ids = _command_ids(_as_list(checklist.get("setup_commands")))
    execution_ids = _command_ids(_as_list(checklist.get("execution_commands")))
    verification_ids = _command_ids(_as_list(checklist.get("verification_commands")))
    for command_id in {"copy_env_template", "build_runbook", "dry_run_runbook", "build_playwright_env", "build_execution_checklist"}:
        if command_id not in setup_ids:
            errors.append(f"setup_command_missing:{command_id}")
    for command_id in {
        "verify_playwright_env",
        "run_smoke",
        "verify_smoke_strict",
        "build_manual_template",
        "verify_manual_backfill",
        "run_health",
        "manifest_health",
        "run_full_spike",
        "manifest_full_spike",
        "refresh_status",
        "refresh_package",
    }:
        if command_id not in execution_ids:
            errors.append(f"execution_command_missing:{command_id}")
    for command_id in {"hard_playwright_env_gate", "hard_status_gate", "hard_package_gate"}:
        if command_id not in verification_ids:
            errors.append(f"verification_command_missing:{command_id}")
    if len(_as_list(checklist.get("evidence_outputs"))) < 10:
        errors.append("evidence_outputs_incomplete")
    if len(_as_list(checklist.get("work_items"))) < 5:
        errors.append("work_items_incomplete")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "execution_checklist_version": checklist.get("execution_checklist_version", ""),
        "google_execution_checklist_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_google_execution_checklist_hash": computed_hash,
        "hash_valid": hash_valid,
        "google_execution_checklist_ready": expected_ready,
        "google_main_scoring_allowed": google_allowed,
        "limited_coverage": checklist.get("limited_coverage") is True,
        "next_action": expected_next,
        "missing_required_environment": missing_required,
        "missing_full_run_required_environment": missing_full_required,
        "missing_selector_groups": missing_selectors,
        "missing_dependencies": missing_dependencies,
        "file_gate_issues": file_issues,
        "remaining_blocker_count": len(remaining_blockers),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google execution checklist JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google execution checklist JSON.",
    )
    parser.add_argument(
        "--require-google-main-scoring-ready",
        action="store_true",
        help="Fail unless the checklist proves Google can enter the main scoring denominator.",
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
            "errors": ["execution_checklist_file_missing"],
            "hash_valid": False,
            "google_execution_checklist_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"execution_checklist_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "google_execution_checklist_ready": False,
        }
    else:
        result = verify_au_p0b_google_execution_checklist(
            checklist,
            path=path,
            require_google_main_scoring_ready=args.require_google_main_scoring_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
