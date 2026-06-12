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

from scripts.build_au_p0b_google_playwright_env_report import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    ENV_REPORT_VERSION,
    compute_google_playwright_env_report_hash,
)


REQUIRED_TOP_LEVEL_FIELDS = (
    "environment_report_version",
    "generated_at",
    "status",
    "ready_for_playwright_smoke",
    "ready_for_full_google_run",
    "next_action",
    "runbook_path",
    "runbook",
    "env_file",
    "required",
    "full_run_required",
    "recommended",
    "selector_groups",
    "file_checks",
    "dependency_checks",
    "collector_health",
    "missing_required",
    "missing_full_run_required",
    "missing_selector_groups",
    "warnings",
    "errors",
    "secrets_redacted",
    "environment_report_hash",
)
CHECK_FIELDS = ("name", "present", "source", "secret_redacted")
TRUTHY_REQUIRED_ENV = {"GOOGLE_PLAYWRIGHT_ENABLED"}


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _validate_env_checks(
    label: str,
    checks: list[object],
    errors: list[str],
    *,
    truthy_required_names: set[str] | None = None,
) -> list[str]:
    truthy_required_names = truthy_required_names or set()
    missing: list[str] = []
    for item in checks:
        check = _as_dict(item)
        name = check.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{label}_check_name_invalid")
            continue
        for field in CHECK_FIELDS:
            if field not in check:
                errors.append(f"{label}_check_field_missing:{name}:{field}")
        if "value" in check or "raw_value" in check:
            errors.append(f"{label}_check_raw_value_leaked:{name}")
        if check.get("secret_redacted") is not True:
            errors.append(f"{label}_check_secret_redaction_missing:{name}")
        present = check.get("present")
        if present is not True and present is not False:
            errors.append(f"{label}_check_present_invalid:{name}")
        if present is True:
            if not isinstance(check.get("value_length"), int) or check.get("value_length") <= 0:
                errors.append(f"{label}_check_value_length_invalid:{name}")
            prefix = check.get("sha256_prefix")
            if not isinstance(prefix, str) or len(prefix) != 12:
                errors.append(f"{label}_check_sha256_prefix_invalid:{name}")
            if name in truthy_required_names:
                if check.get("truthy") is not True and check.get("truthy") is not False:
                    errors.append(f"{label}_check_truthy_invalid:{name}")
                if check.get("truthy") is not True:
                    missing.append(name)
        else:
            missing.append(name)
    return missing


def _validate_selector_groups(groups: list[object], errors: list[str]) -> list[str]:
    missing: list[str] = []
    for item in groups:
        group = _as_dict(item)
        group_name = group.get("group")
        if not isinstance(group_name, str) or not group_name:
            errors.append("selector_group_name_invalid")
            continue
        if "value" in group or "raw_value" in group:
            errors.append(f"selector_group_raw_value_leaked:{group_name}")
        if group.get("secret_redacted") is not True:
            errors.append(f"selector_group_secret_redaction_missing:{group_name}")
        if group.get("present") is True:
            if not isinstance(group.get("selected_name"), str) or not group.get("selected_name"):
                errors.append(f"selector_group_selected_name_missing:{group_name}")
            if not isinstance(group.get("value_length"), int) or group.get("value_length") <= 0:
                errors.append(f"selector_group_value_length_invalid:{group_name}")
        else:
            missing.append(group_name)
    return missing


def _expected_next_action(report: dict[str, Any], *, ready_for_smoke: bool, collector_health: str) -> str:
    runbook = _as_dict(report.get("runbook"))
    env_file = _as_dict(report.get("env_file"))
    if runbook.get("status") != "pass":
        return "run_or_fix_au_p0b_google_runbook"
    if env_file.get("errors"):
        return "fix_google_playwright_env_file"
    if _as_list(report.get("missing_required")) or _as_list(report.get("missing_selector_groups")):
        return "populate_google_playwright_smoke_environment"
    if any(
        _as_dict(item).get("name") == "GOOGLE_PLAYWRIGHT_STORAGE_STATE"
        and _as_dict(item).get("present")
        and not _as_dict(item).get("is_file")
        for item in _as_list(report.get("file_checks"))
    ):
        return "fix_google_playwright_storage_state"
    if any(
        _as_dict(item).get("name") == "python_playwright_package"
        and _as_dict(item).get("present") is not True
        for item in _as_list(report.get("dependency_checks"))
    ):
        return "install_python_playwright"
    if not ready_for_smoke and collector_health != "ready":
        return "fix_google_playwright_collector_health"
    return "run_au_p0b_google_playwright_smoke"


def verify_google_playwright_env_report(
    report: Any,
    *,
    path: Path | None = None,
    require_ready_smoke: bool = False,
) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {
            "status": "fail",
            "errors": ["environment_report_not_json_object"],
            "hash_valid": False,
            "ready_for_playwright_smoke": False,
        }
    errors: list[str] = []
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in report:
            errors.append(f"field_missing:{field}")
    if report.get("environment_report_version") != ENV_REPORT_VERSION:
        errors.append("environment_report_version_invalid")
    if report.get("secrets_redacted") is not True:
        errors.append("secrets_redacted_missing")

    expected_hash = report.get("environment_report_hash")
    computed_hash = compute_google_playwright_env_report_hash(report)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("environment_report_hash_mismatch")

    missing_required = _validate_env_checks(
        "required",
        _as_list(report.get("required")),
        errors,
        truthy_required_names=TRUTHY_REQUIRED_ENV,
    )
    missing_full_required = _validate_env_checks(
        "full_run_required",
        _as_list(report.get("full_run_required")),
        errors,
    )
    _validate_env_checks("recommended", _as_list(report.get("recommended")), errors)
    missing_selector_groups = _validate_selector_groups(_as_list(report.get("selector_groups")), errors)
    if sorted(str(item) for item in _as_list(report.get("missing_required"))) != sorted(missing_required):
        errors.append("missing_required_mismatch")
    if sorted(str(item) for item in _as_list(report.get("missing_full_run_required"))) != sorted(missing_full_required):
        errors.append("missing_full_run_required_mismatch")
    if sorted(str(item) for item in _as_list(report.get("missing_selector_groups"))) != sorted(missing_selector_groups):
        errors.append("missing_selector_groups_mismatch")

    runbook = _as_dict(report.get("runbook"))
    env_file = _as_dict(report.get("env_file"))
    storage_state_ok = not any(
        _as_dict(item).get("name") == "GOOGLE_PLAYWRIGHT_STORAGE_STATE"
        and _as_dict(item).get("present")
        and not _as_dict(item).get("is_file")
        for item in _as_list(report.get("file_checks"))
    )
    playwright_ok = not any(
        _as_dict(item).get("name") == "python_playwright_package"
        and _as_dict(item).get("present") is not True
        for item in _as_list(report.get("dependency_checks"))
    )
    collector_health = str(report.get("collector_health") or "")
    expected_ready = (
        runbook.get("status") == "pass"
        and not _as_list(env_file.get("errors"))
        and not missing_required
        and not missing_selector_groups
        and storage_state_ok
        and playwright_ok
        and collector_health == "ready"
    )
    if report.get("ready_for_playwright_smoke") is not expected_ready:
        errors.append("ready_for_playwright_smoke_mismatch")
    manual_backfill_ok = any(
        _as_dict(item).get("name") == "MANUAL_BACKFILL_PATH"
        and _as_dict(item).get("present")
        and _as_dict(item).get("is_file")
        for item in _as_list(report.get("file_checks"))
    )
    expected_full_ready = expected_ready and not missing_full_required and manual_backfill_ok
    if report.get("ready_for_full_google_run") is not expected_full_ready:
        errors.append("ready_for_full_google_run_mismatch")
    expected_status = "pass" if expected_ready else "fail"
    if report.get("status") != expected_status:
        errors.append("status_mismatch")
    expected_next_action = _expected_next_action(
        report,
        ready_for_smoke=expected_ready,
        collector_health=collector_health,
    )
    if report.get("next_action") != expected_next_action:
        errors.append("next_action_mismatch")
    if require_ready_smoke and not expected_ready:
        errors.append("playwright_smoke_environment_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "environment_report_version": report.get("environment_report_version", ""),
        "environment_report_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_environment_report_hash": computed_hash,
        "hash_valid": hash_valid,
        "ready_for_playwright_smoke": expected_ready,
        "ready_for_full_google_run": expected_full_ready,
        "collector_health": collector_health,
        "missing_required": sorted(missing_required),
        "missing_full_run_required": sorted(missing_full_required),
        "missing_selector_groups": sorted(missing_selector_groups),
        "next_action": expected_next_action,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google Playwright environment report JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google Playwright environment report JSON.",
    )
    parser.add_argument(
        "--require-ready-smoke",
        action="store_true",
        help="Fail unless the environment is ready for one Google Playwright smoke capture.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["environment_report_file_missing"],
            "hash_valid": False,
            "ready_for_playwright_smoke": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"environment_report_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "ready_for_playwright_smoke": False,
        }
    else:
        result = verify_google_playwright_env_report(report, path=path, require_ready_smoke=args.require_ready_smoke)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
