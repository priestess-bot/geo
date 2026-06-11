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

from scripts.build_au_p0a_env_report import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    ENV_REPORT_VERSION,
    compute_env_report_hash,
)


REQUIRED_TOP_LEVEL_FIELDS = (
    "environment_report_version",
    "generated_at",
    "status",
    "ready_for_real_batch",
    "next_action",
    "runbook_path",
    "runbook",
    "env_file",
    "required",
    "recommended",
    "missing_required",
    "missing_recommended",
    "warnings",
    "errors",
    "secrets_redacted",
    "environment_report_hash",
)
CHECK_FIELDS = ("name", "present", "source", "value_length", "sha256_prefix", "secret_redacted")


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _expected_next_action(report: dict[str, Any], missing_required: list[str]) -> str:
    runbook = _as_dict(report.get("runbook"))
    env_file = _as_dict(report.get("env_file"))
    if runbook.get("status") != "pass":
        return "run_or_fix_au_p0a_runbook"
    if env_file.get("errors"):
        return "fix_environment_file"
    if missing_required:
        return "populate_required_environment"
    return "run_au_p0a_runbook_dry_run"


def _validate_checks(label: str, checks: list[object], errors: list[str]) -> list[str]:
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
        present = check.get("present")
        source = check.get("source")
        if present is not True and present is not False:
            errors.append(f"{label}_check_present_invalid:{name}")
        if source not in {"process", "env_file", "missing"}:
            errors.append(f"{label}_check_source_invalid:{name}")
        if check.get("secret_redacted") is not True:
            errors.append(f"{label}_check_secret_redaction_missing:{name}")
        if present is True:
            if not isinstance(check.get("value_length"), int) or check.get("value_length") <= 0:
                errors.append(f"{label}_check_value_length_invalid:{name}")
            prefix = check.get("sha256_prefix")
            if not isinstance(prefix, str) or len(prefix) != 12:
                errors.append(f"{label}_check_sha256_prefix_invalid:{name}")
        else:
            missing.append(name)
            if check.get("value_length") not in {0, None}:
                errors.append(f"{label}_check_missing_value_length_invalid:{name}")
            if check.get("sha256_prefix") not in {"", None}:
                errors.append(f"{label}_check_missing_sha256_prefix_invalid:{name}")
    return missing


def verify_au_p0a_env_report(
    report: Any,
    *,
    path: Path | None = None,
    require_ready_environment: bool = False,
) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {
            "status": "fail",
            "errors": ["environment_report_not_json_object"],
            "hash_valid": False,
            "ready_for_real_batch": False,
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
    computed_hash = compute_env_report_hash(report)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("environment_report_hash_mismatch")

    runbook = _as_dict(report.get("runbook"))
    env_file = _as_dict(report.get("env_file"))
    required_missing = _validate_checks("required", _as_list(report.get("required")), errors)
    recommended_missing = _validate_checks("recommended", _as_list(report.get("recommended")), errors)
    if sorted(str(item) for item in _as_list(report.get("missing_required"))) != sorted(required_missing):
        errors.append("missing_required_mismatch")
    if sorted(str(item) for item in _as_list(report.get("missing_recommended"))) != sorted(recommended_missing):
        errors.append("missing_recommended_mismatch")

    expected_ready = runbook.get("status") == "pass" and not required_missing and not _as_list(env_file.get("errors"))
    if report.get("ready_for_real_batch") is not expected_ready:
        errors.append("ready_for_real_batch_mismatch")
    expected_status = "pass" if expected_ready else "fail"
    if report.get("status") != expected_status:
        errors.append("status_mismatch")
    expected_next_action = _expected_next_action(report, required_missing)
    if report.get("next_action") != expected_next_action:
        errors.append("next_action_mismatch")
    expected_warnings = sorted(f"recommended_env_missing:{name}" for name in recommended_missing)
    if sorted(str(item) for item in _as_list(report.get("warnings"))) != expected_warnings:
        errors.append("warnings_mismatch")
    if require_ready_environment and not expected_ready:
        errors.append("environment_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "environment_report_version": report.get("environment_report_version", ""),
        "environment_report_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_environment_report_hash": computed_hash,
        "hash_valid": hash_valid,
        "ready_for_real_batch": expected_ready,
        "missing_required": sorted(required_missing),
        "missing_recommended": sorted(recommended_missing),
        "next_action": expected_next_action,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a redacted AU P0a environment report JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0A_ENV_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0a environment report JSON.",
    )
    parser.add_argument(
        "--require-ready-environment",
        action="store_true",
        help="Fail unless required AU P0a environment is present and the runbook verifies.",
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
            "ready_for_real_batch": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"environment_report_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "ready_for_real_batch": False,
        }
    else:
        result = verify_au_p0a_env_report(
            report,
            path=path,
            require_ready_environment=args.require_ready_environment,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
