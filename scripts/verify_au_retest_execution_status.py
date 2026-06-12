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

from scripts.build_au_retest_execution_status import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    STATUS_VERSION,
    compute_retest_execution_status_hash,
)


REQUIRED_FIELDS = (
    "status_version",
    "generated_at",
    "status",
    "execution_status_report_ready",
    "retest_execution_ready",
    "comparison_allowed",
    "next_action",
    "plan_source",
    "plan_verifier",
    "plan_summary",
    "summary",
    "windows",
    "runtime_endpoints",
    "paths",
    "current_boundary",
    "retest_execution_status_hash",
)
EXPECTED_WINDOW_IDS = ("baseline", "t_plus_7", "t_plus_14", "t_plus_30")


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def verify_au_retest_execution_status(status: Any, *, path: Path | None = None) -> dict[str, Any]:
    if not isinstance(status, dict):
        return {
            "status": "fail",
            "errors": ["retest_execution_status_not_json_object"],
            "hash_valid": False,
            "execution_status_report_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in status:
            errors.append(f"field_missing:{field}")
    if status.get("status_version") != STATUS_VERSION:
        errors.append("status_version_invalid")

    expected_hash = status.get("retest_execution_status_hash")
    computed_hash = compute_retest_execution_status_hash(status)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("retest_execution_status_hash_mismatch")

    plan_verifier = _as_dict(status.get("plan_verifier"))
    if plan_verifier.get("status") != "pass":
        errors.append("plan_verifier_status_invalid")

    windows = [_as_dict(item) for item in _as_list(status.get("windows"))]
    window_ids = tuple(str(window.get("id", "")) for window in windows)
    if window_ids != EXPECTED_WINDOW_IDS:
        errors.append("window_ids_or_order_invalid")
    ready_windows = [window for window in windows if window.get("window_ready") is True]
    ready_retest_windows = [window for window in ready_windows if int(window.get("offset_day") or 0) > 0]
    baseline_ready = bool(windows and windows[0].get("window_ready") is True and int(windows[0].get("offset_day") or 0) == 0)
    comparison_allowed = baseline_ready and bool(ready_retest_windows)
    missing_artifact_count = sum(int(window.get("missing_artifact_count") or 0) for window in windows)
    next_window = next((window for window in windows if window.get("window_ready") is not True), None)
    expected_ready = bool(windows) and len(ready_windows) == len(windows)
    expected_status = "pass" if expected_ready else "fail"
    if status.get("retest_execution_ready") is not expected_ready:
        errors.append("retest_execution_ready_mismatch")
    if status.get("status") != expected_status:
        errors.append("status_value_mismatch")
    if status.get("comparison_allowed") is not comparison_allowed:
        errors.append("comparison_allowed_mismatch")
    expected_next_action = (
        f"run_retest_window:{next_window['id']}"
        if next_window
        else "compare_all_retest_windows"
        if comparison_allowed
        else "run_retest_baseline"
    )
    if status.get("next_action") != expected_next_action:
        errors.append("next_action_mismatch")

    summary = _as_dict(status.get("summary"))
    if summary.get("window_count") != len(windows):
        errors.append("summary_window_count_mismatch")
    if summary.get("ready_window_count") != len(ready_windows):
        errors.append("summary_ready_window_count_mismatch")
    if summary.get("ready_retest_window_count") != len(ready_retest_windows):
        errors.append("summary_ready_retest_window_count_mismatch")
    if summary.get("missing_window_count") != len(windows) - len(ready_windows):
        errors.append("summary_missing_window_count_mismatch")
    if summary.get("missing_artifact_count") != missing_artifact_count:
        errors.append("summary_missing_artifact_count_mismatch")
    if summary.get("baseline_ready") is not baseline_ready:
        errors.append("summary_baseline_ready_mismatch")
    if summary.get("comparison_allowed") is not comparison_allowed:
        errors.append("summary_comparison_allowed_mismatch")
    if summary.get("next_window_id") != (next_window.get("id") if next_window else None):
        errors.append("summary_next_window_id_mismatch")

    for window in windows:
        payload = _as_dict(window.get("payload"))
        manifest = _as_dict(window.get("manifest"))
        if not payload:
            errors.append(f"window_payload_missing:{window.get('id')}")
        if not manifest:
            errors.append(f"window_manifest_missing:{window.get('id')}")
        expected_window_ready = (
            payload.get("ready_for_design_partner") is True and manifest.get("ready_for_design_partner") is True
        )
        if window.get("window_ready") is not expected_window_ready:
            errors.append(f"window_ready_mismatch:{window.get('id')}")
        expected_missing = int(payload.get("exists") is not True) + int(manifest.get("exists") is not True)
        if window.get("missing_artifact_count") != expected_missing:
            errors.append(f"window_missing_artifact_count_mismatch:{window.get('id')}")

    endpoints = _as_dict(status.get("runtime_endpoints"))
    if endpoints.get("retest_execution_status") != "GET /v1/au-retest-execution-status":
        errors.append("runtime_endpoint_retest_execution_status_invalid")
    if endpoints.get("retest_scheduler_plan") != "GET /v1/au-retest-scheduler-plan":
        errors.append("runtime_endpoint_retest_scheduler_plan_invalid")

    boundary = _as_dict(status.get("current_boundary"))
    if boundary.get("temporal_scheduler_implemented") is not False:
        errors.append("boundary_temporal_scheduler_must_be_false")
    if boundary.get("real_external_runs_completed") is not expected_ready:
        errors.append("boundary_real_external_runs_completed_mismatch")

    report_ready = status.get("execution_status_report_ready") is True
    return {
        "status": "pass" if not errors and report_ready else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "status_version": status.get("status_version", ""),
        "retest_execution_status_hash": expected_hash,
        "computed_retest_execution_status_hash": computed_hash,
        "hash_valid": hash_valid,
        "execution_status_report_ready": report_ready,
        "retest_execution_ready": status.get("retest_execution_ready") is True,
        "comparison_allowed": status.get("comparison_allowed") is True,
        "window_count": len(windows),
        "ready_window_count": len(ready_windows),
        "missing_artifact_count": missing_artifact_count,
        "next_action": status.get("next_action", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the AU retest execution status JSON.")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_RETEST_EXECUTION_STATUS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "errors": ["file_missing"],
            "path": str(path),
            "hash_valid": False,
            "execution_status_report_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "errors": [f"json_invalid:{exc.msg}"],
            "path": str(path),
            "hash_valid": False,
            "execution_status_report_ready": False,
        }
    else:
        result = verify_au_retest_execution_status(payload, path=path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
