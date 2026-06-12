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

from scripts.run_au_p0a_runbook import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    EXECUTION_VERSION,
    compute_execution_payload_hash,
)


REQUIRED_TOP_LEVEL_FIELDS = (
    "execution_version",
    "generated_at",
    "mode",
    "status",
    "ready_to_execute",
    "execute_requested",
    "runbook_path",
    "output_path",
    "errors",
    "runbook_verification",
    "environment",
    "planned_step_count",
    "recorded_step_count",
    "executed_command_count",
    "steps",
    "execution_payload_hash",
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


def _validate_env_checks(label: str, checks: list[object], errors: list[str]) -> list[str]:
    missing: list[str] = []
    for item in checks:
        check = _as_dict(item)
        name = check.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{label}_check_name_invalid")
            continue
        for field in ("name", "present", "source", "value_length", "sha256_prefix", "secret_redacted"):
            if field not in check:
                errors.append(f"{label}_check_field_missing:{name}:{field}")
        if check.get("source") not in {"process", "env_file", "missing"}:
            errors.append(f"{label}_check_source_invalid:{name}")
        if check.get("secret_redacted") is not True:
            errors.append(f"{label}_check_secret_redaction_missing:{name}")
        if check.get("present") is True:
            if not isinstance(check.get("value_length"), int) or check.get("value_length") <= 0:
                errors.append(f"{label}_check_value_length_invalid:{name}")
            if not isinstance(check.get("sha256_prefix"), str) or len(check.get("sha256_prefix")) != 12:
                errors.append(f"{label}_check_sha256_prefix_invalid:{name}")
        elif check.get("present") is False:
            missing.append(name)
            if check.get("value_length") not in {0, None}:
                errors.append(f"{label}_check_missing_value_length_invalid:{name}")
            if check.get("sha256_prefix") not in {"", None}:
                errors.append(f"{label}_check_missing_sha256_prefix_invalid:{name}")
        else:
            errors.append(f"{label}_check_present_invalid:{name}")
    return sorted(missing)


def _step_status_counts(steps: list[object]) -> dict[str, int]:
    counts = {"executed": 0, "failed": 0}
    for step in steps:
        status = _as_dict(step).get("status")
        if status in {"pass", "fail"}:
            counts["executed"] += 1
        if status == "fail":
            counts["failed"] += 1
    return counts


def verify_au_p0a_runbook_execution(
    execution: Any,
    *,
    path: Path | None = None,
    require_ready_to_execute: bool = False,
) -> dict[str, Any]:
    if not isinstance(execution, dict):
        return {
            "status": "fail",
            "errors": ["execution_not_json_object"],
            "hash_valid": False,
            "ready_to_execute": False,
        }

    errors: list[str] = []
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in execution:
            errors.append(f"field_missing:{field}")
    if execution.get("execution_version") != EXECUTION_VERSION:
        errors.append("execution_version_invalid")
    for forbidden_path in _find_forbidden_secret_fields(execution):
        errors.append(f"forbidden_secret_field:{forbidden_path}")

    expected_hash = execution.get("execution_payload_hash")
    computed_hash = compute_execution_payload_hash(execution)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("execution_payload_hash_mismatch")

    mode = execution.get("mode")
    execute_requested = execution.get("execute_requested")
    if mode not in {"dry_run", "execute"}:
        errors.append("mode_invalid")
    if execute_requested is not (mode == "execute"):
        errors.append("execute_requested_mismatch")

    runbook = _as_dict(execution.get("runbook_verification"))
    environment = _as_dict(execution.get("environment"))
    if environment.get("secrets_redacted") is not True:
        errors.append("environment_secrets_redacted_missing")
    env_file = _as_dict(environment.get("env_file"))
    if "path" not in env_file or "exists" not in env_file or "loaded" not in env_file:
        errors.append("environment_env_file_metadata_incomplete")
    required_missing = _validate_env_checks("required", _as_list(environment.get("required")), errors)
    recommended_missing = _validate_env_checks("recommended", _as_list(environment.get("recommended")), errors)
    if sorted(str(item) for item in _as_list(environment.get("missing_required"))) != required_missing:
        errors.append("environment_missing_required_mismatch")
    if sorted(str(item) for item in _as_list(environment.get("missing_recommended"))) != recommended_missing:
        errors.append("environment_missing_recommended_mismatch")
    if environment.get("status") not in {"pass", "fail"}:
        errors.append("environment_status_invalid")
    if environment.get("status") == "pass" and required_missing:
        errors.append("environment_status_pass_with_missing_required")
    expected_ready = runbook.get("status") == "pass" and environment.get("status") == "pass"
    if execution.get("ready_to_execute") is not expected_ready:
        errors.append("ready_to_execute_mismatch")
    if require_ready_to_execute and not expected_ready:
        errors.append("not_ready_to_execute")

    steps = _as_list(execution.get("steps"))
    planned_step_count = execution.get("planned_step_count")
    if not isinstance(planned_step_count, int):
        errors.append("planned_step_count_invalid")
        planned_step_count = 0
    if execution.get("recorded_step_count") != len(steps):
        errors.append("recorded_step_count_mismatch")
    counts = _step_status_counts(steps)
    if execution.get("executed_command_count") != counts["executed"]:
        errors.append("executed_command_count_mismatch")
    if mode == "dry_run" and execution.get("executed_command_count") != 0:
        errors.append("dry_run_executed_commands")
    if mode == "dry_run":
        invalid_statuses = [
            str(_as_dict(step).get("id", ""))
            for step in steps
            if _as_dict(step).get("type") == "command"
            and _as_dict(step).get("status") not in {"dry_run", "fail"}
        ]
        for step_id in invalid_statuses:
            errors.append(f"dry_run_command_status_invalid:{step_id}")
    if len(steps) > planned_step_count:
        errors.append("recorded_steps_exceed_planned")

    expected_status = "pass" if not _as_list(execution.get("errors")) else "fail"
    if execution.get("status") != expected_status:
        errors.append("status_mismatch")
    failed_step_id = execution.get("failed_step_id", "")
    if counts["failed"] and not failed_step_id:
        errors.append("failed_step_id_missing")
    if execution.get("stopped_after_step") is True and not execution.get("stop_after_step"):
        errors.append("stopped_after_step_without_target")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "execution_version": execution.get("execution_version", ""),
        "execution_payload_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_execution_payload_hash": computed_hash,
        "hash_valid": hash_valid,
        "mode": mode if isinstance(mode, str) else "",
        "ready_to_execute": expected_ready,
        "planned_step_count": planned_step_count,
        "recorded_step_count": len(steps),
        "executed_command_count": counts["executed"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0a runbook execution JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0a runbook execution JSON.",
    )
    parser.add_argument(
        "--require-ready-to-execute",
        action="store_true",
        help="Fail unless runbook verification and required environment checks are both passing.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        execution = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["execution_file_missing"],
            "hash_valid": False,
            "ready_to_execute": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"execution_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "ready_to_execute": False,
        }
    else:
        result = verify_au_p0a_runbook_execution(
            execution,
            path=path,
            require_ready_to_execute=args.require_ready_to_execute,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
