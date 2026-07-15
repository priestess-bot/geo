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

from scripts.run_au_p0b_google_spike_runbook import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    EXECUTION_VERSION,
    compute_google_spike_execution_hash,
)


REQUIRED_FIELDS = (
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


def _step_status_counts(steps: list[object]) -> dict[str, int]:
    counts = {"executed": 0, "failed": 0}
    for step in steps:
        status = _as_dict(step).get("status")
        if status in {"pass", "fail"}:
            counts["executed"] += 1
        if status == "fail":
            counts["failed"] += 1
    return counts


def verify_au_p0b_google_spike_runbook_execution(
    execution: Any,
    *,
    path: Path | None = None,
    require_ready_to_execute: bool = False,
) -> dict[str, Any]:
    if not isinstance(execution, dict):
        return {"status": "fail", "errors": ["execution_not_json_object"], "hash_valid": False, "ready_to_execute": False}

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in execution:
            errors.append(f"field_missing:{field}")
    if execution.get("execution_version") != EXECUTION_VERSION:
        errors.append("execution_version_invalid")

    expected_hash = execution.get("execution_payload_hash")
    computed_hash = compute_google_spike_execution_hash(execution)
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
        for step in steps:
            item = _as_dict(step)
            if item.get("type") == "command" and item.get("status") not in {"dry_run", "fail"}:
                errors.append(f"dry_run_command_status_invalid:{item.get('id', '')}")
    if len(steps) > planned_step_count:
        errors.append("recorded_steps_exceed_planned")

    expected_status = "pass" if not _as_list(execution.get("errors")) else "fail"
    if execution.get("status") != expected_status:
        errors.append("status_mismatch")
    if counts["failed"] and not execution.get("failed_step_id"):
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
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google spike runbook execution JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google spike runbook execution JSON.",
    )
    parser.add_argument("--require-ready-to-execute", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        execution = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {"status": "fail", "path": str(path), "errors": ["execution_file_missing"], "hash_valid": False}
    except json.JSONDecodeError as exc:
        result = {"status": "fail", "path": str(path), "errors": [f"execution_json_invalid:{exc.msg}"], "hash_valid": False}
    else:
        result = verify_au_p0b_google_spike_runbook_execution(
            execution,
            path=path,
            require_ready_to_execute=args.require_ready_to_execute,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
