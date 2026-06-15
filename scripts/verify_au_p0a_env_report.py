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
    POST_UPDATE_VALIDATION_COMMANDS,
    compute_env_report_hash,
)


REQUIRED_TOP_LEVEL_FIELDS = (
    "environment_report_version",
    "generated_at",
    "status",
    "ready_for_real_batch",
    "next_action",
    "next_command",
    "runbook_path",
    "runbook",
    "env_file",
    "required",
    "recommended",
    "missing_required",
    "missing_recommended",
    "credential_update_handoff",
    "post_update_validation_commands",
    "summary",
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
    hygiene = _as_dict(env_file.get("hygiene"))
    if runbook.get("status") != "pass":
        return "run_or_fix_au_p0a_runbook"
    if env_file.get("errors") or hygiene.get("errors"):
        return "fix_environment_file"
    if missing_required:
        return "populate_required_environment"
    return "run_au_p0a_runbook_dry_run"


def _expected_next_command(next_action: str) -> str:
    if next_action == "run_or_fix_au_p0a_runbook":
        return "make au-p0a-runbook"
    if next_action == "run_au_p0a_runbook_dry_run":
        return "make au-p0a-runbook-dry-run"
    return "make au-p0a-env"


def _find_forbidden_secret_fields(value: object, *, prefix: str = "") -> list[str]:
    forbidden: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in {"value", "raw_value", "secret", "token", "api_key", "database_url"}:
                forbidden.append(path)
            forbidden.extend(_find_forbidden_secret_fields(child, prefix=path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            forbidden.extend(_find_forbidden_secret_fields(child, prefix=f"{prefix}[{index}]"))
    return forbidden


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
    hygiene = _as_dict(env_file.get("hygiene"))
    if "hygiene" not in env_file:
        errors.append("env_file_hygiene_missing")
    elif hygiene.get("secret_redacted") is not True:
        errors.append("env_file_hygiene_secret_redaction_missing")
    hygiene_errors = [str(item) for item in _as_list(hygiene.get("errors"))]
    hygiene_warnings = [str(item) for item in _as_list(hygiene.get("warnings"))]
    if hygiene.get("hygiene_ready") is not True and hygiene.get("hygiene_ready") is not False:
        errors.append("env_file_hygiene_ready_invalid")
    if hygiene.get("hygiene_required") is not True and hygiene.get("hygiene_required") is not False:
        errors.append("env_file_hygiene_required_invalid")
    if hygiene.get("exists") is not env_file.get("exists"):
        errors.append("env_file_hygiene_exists_mismatch")
    if "value" in hygiene or "raw_value" in hygiene:
        errors.append("env_file_hygiene_raw_value_leaked")
    required_missing = _validate_checks("required", _as_list(report.get("required")), errors)
    recommended_missing = _validate_checks("recommended", _as_list(report.get("recommended")), errors)
    if sorted(str(item) for item in _as_list(report.get("missing_required"))) != sorted(required_missing):
        errors.append("missing_required_mismatch")
    if sorted(str(item) for item in _as_list(report.get("missing_recommended"))) != sorted(recommended_missing):
        errors.append("missing_recommended_mismatch")

    expected_ready = (
        runbook.get("status") == "pass"
        and not required_missing
        and not _as_list(env_file.get("errors"))
        and not hygiene_errors
        and hygiene.get("hygiene_ready") is True
    )
    if report.get("ready_for_real_batch") is not expected_ready:
        errors.append("ready_for_real_batch_mismatch")
    expected_status = "pass" if expected_ready else "fail"
    if report.get("status") != expected_status:
        errors.append("status_mismatch")
    expected_next_action = _expected_next_action(report, required_missing)
    if report.get("next_action") != expected_next_action:
        errors.append("next_action_mismatch")
    expected_next_command = _expected_next_command(expected_next_action)
    if report.get("next_command") != expected_next_command:
        errors.append("next_command_mismatch")
    post_update_commands = [str(item) for item in _as_list(report.get("post_update_validation_commands"))]
    if post_update_commands != list(POST_UPDATE_VALIDATION_COMMANDS):
        errors.append("post_update_validation_commands_mismatch")

    credential_handoff = _as_dict(report.get("credential_update_handoff"))
    for forbidden in _find_forbidden_secret_fields(credential_handoff, prefix="credential_update_handoff"):
        errors.append(f"forbidden_secret_field:{forbidden}")
    if credential_handoff.get("credential_update_handoff_version") != "au_p0a_env_credential_update_handoff_v1":
        errors.append("credential_update_handoff_version_invalid")
    expected_handoff_ready = (
        bool(required_missing)
        and runbook.get("status") == "pass"
        and not _as_list(env_file.get("errors"))
        and not hygiene_errors
        and hygiene.get("hygiene_ready") is True
    )
    if credential_handoff.get("ready_to_update_credentials") is not expected_handoff_ready:
        errors.append("credential_update_handoff_ready_mismatch")
    if sorted(str(item) for item in _as_list(credential_handoff.get("required_missing_keys"))) != sorted(
        required_missing
    ):
        errors.append("credential_update_handoff_missing_required_mismatch")
    if credential_handoff.get("next_action") != expected_next_action:
        errors.append("credential_update_handoff_next_action_mismatch")
    if credential_handoff.get("next_command") != expected_next_command:
        errors.append("credential_update_handoff_next_command_mismatch")
    if [str(item) for item in _as_list(credential_handoff.get("post_update_validation_commands"))] != list(
        POST_UPDATE_VALIDATION_COMMANDS
    ):
        errors.append("credential_update_handoff_validation_commands_mismatch")
    if credential_handoff.get("post_update_validation_command_count") != len(POST_UPDATE_VALIDATION_COMMANDS):
        errors.append("credential_update_handoff_validation_command_count_mismatch")
    redaction_policy = _as_dict(credential_handoff.get("redaction_policy"))
    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("credential_update_handoff_raw_secret_policy_invalid")
    if redaction_policy.get("secret_redacted") is not True:
        errors.append("credential_update_handoff_secret_redacted_missing")

    summary = _as_dict(report.get("summary"))
    if summary.get("required_count") != len(_as_list(report.get("required"))):
        errors.append("summary_required_count_mismatch")
    if summary.get("present_required_count") != len(_as_list(report.get("required"))) - len(required_missing):
        errors.append("summary_present_required_count_mismatch")
    if summary.get("missing_required_count") != len(required_missing):
        errors.append("summary_missing_required_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("missing_required"))) != sorted(required_missing):
        errors.append("summary_missing_required_mismatch")
    if summary.get("recommended_count") != len(_as_list(report.get("recommended"))):
        errors.append("summary_recommended_count_mismatch")
    if summary.get("present_recommended_count") != len(_as_list(report.get("recommended"))) - len(recommended_missing):
        errors.append("summary_present_recommended_count_mismatch")
    if summary.get("missing_recommended_count") != len(recommended_missing):
        errors.append("summary_missing_recommended_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("missing_recommended"))) != sorted(recommended_missing):
        errors.append("summary_missing_recommended_mismatch")
    if summary.get("runbook_status") != runbook.get("status", ""):
        errors.append("summary_runbook_status_mismatch")
    if summary.get("runbook_hash_valid") is not (runbook.get("hash_valid") is True):
        errors.append("summary_runbook_hash_valid_mismatch")
    if summary.get("env_file_exists") is not (env_file.get("exists") is True):
        errors.append("summary_env_file_exists_mismatch")
    if summary.get("env_file_loaded") is not (env_file.get("loaded") is True):
        errors.append("summary_env_file_loaded_mismatch")
    if summary.get("env_file_entry_count") != env_file.get("entry_count", 0):
        errors.append("summary_env_file_entry_count_mismatch")
    if summary.get("env_file_hygiene_ready") is not (hygiene.get("hygiene_ready") is True):
        errors.append("summary_env_file_hygiene_ready_mismatch")
    if summary.get("env_file_hygiene_error_count") != len(hygiene_errors):
        errors.append("summary_env_file_hygiene_error_count_mismatch")
    if summary.get("env_file_hygiene_warning_count") != len(hygiene_warnings):
        errors.append("summary_env_file_hygiene_warning_count_mismatch")
    if summary.get("ready_for_real_batch") is not expected_ready:
        errors.append("summary_ready_for_real_batch_mismatch")
    if summary.get("next_action") != expected_next_action:
        errors.append("summary_next_action_mismatch")
    if summary.get("next_command") != expected_next_command:
        errors.append("summary_next_command_mismatch")
    if summary.get("credential_update_handoff_ready") is not expected_handoff_ready:
        errors.append("summary_credential_update_handoff_ready_mismatch")
    if summary.get("post_update_validation_command_count") != len(POST_UPDATE_VALIDATION_COMMANDS):
        errors.append("summary_post_update_validation_command_count_mismatch")
    if summary.get("raw_secret_values_allowed") is not False:
        errors.append("summary_raw_secret_values_policy_invalid")
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
        "env_file_hygiene_ready": hygiene.get("hygiene_ready") is True,
        "env_file_hygiene_errors": hygiene_errors,
        "env_file_hygiene_warnings": hygiene_warnings,
        "next_action": expected_next_action,
        "next_command": expected_next_command,
        "credential_update_handoff_ready": expected_handoff_ready,
        "post_update_validation_command_count": len(POST_UPDATE_VALIDATION_COMMANDS),
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
