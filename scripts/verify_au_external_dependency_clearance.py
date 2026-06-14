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

from scripts.build_au_external_dependency_handoff import CLEARANCE_SEQUENCE_VERSION, CLEARANCE_STEP_ORDER  # noqa: E402
from scripts.run_au_external_dependency_clearance import (  # noqa: E402
    CLEARANCE_REQUEST_CONTEXTS,
    DEFAULT_OUTPUT_PATH,
    EXECUTION_VERSION,
    REQUEST_CONTEXT_VERSION,
    compute_clearance_execution_hash,
)


REQUIRED_TOP_LEVEL_FIELDS = (
    "clearance_execution_version",
    "generated_at",
    "mode",
    "status",
    "ready_to_execute",
    "external_dependency_handoff_ready",
    "handoff_path",
    "output_path",
    "errors",
    "handoff_verification",
    "clearance_sequence_version",
    "planned_step_count",
    "recorded_step_count",
    "ready_step_count",
    "blocked_step_count",
    "would_execute_step_count",
    "current_step_id",
    "next_command",
    "stop_after_step",
    "stopped_after_step",
    "current_step_request_context",
    "current_recommended_sequence",
    "current_recommended_sequence_count",
    "current_strict_gate_command",
    "hard_gate_commands",
    "steps",
    "clearance_execution_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _find_forbidden_raw_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {
                "value",
                "raw_value",
                "database_url",
                "selector_value",
                "answer_text",
                "citation_urls",
                "screenshot_url",
                "html_snapshot_url",
            }:
                findings.append(child_path)
            findings.extend(_find_forbidden_raw_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_raw_fields(child, path=f"{path}[{index}]"))
    return findings


def verify_au_external_dependency_clearance(
    execution: Any,
    *,
    path: Path | None = None,
    require_handoff_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(execution, dict):
        return {
            "status": "fail",
            "errors": ["clearance_execution_not_json_object"],
            "hash_valid": False,
            "ready_to_execute": False,
        }

    errors: list[str] = []
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in execution:
            errors.append(f"field_missing:{field}")
    if execution.get("clearance_execution_version") != EXECUTION_VERSION:
        errors.append("clearance_execution_version_invalid")
    if execution.get("mode") != "dry_run":
        errors.append("mode_invalid")
    for forbidden_path in _find_forbidden_raw_fields(execution):
        errors.append(f"forbidden_raw_field:{forbidden_path}")

    expected_hash = execution.get("clearance_execution_hash")
    computed_hash = compute_clearance_execution_hash(execution)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("clearance_execution_hash_mismatch")

    handoff_verification = _as_dict(execution.get("handoff_verification"))
    if handoff_verification.get("status") != "pass":
        errors.append("handoff_verification_not_pass")
    if handoff_verification.get("hash_valid") is not True:
        errors.append("handoff_verification_hash_not_valid")
    if execution.get("ready_to_execute") is not (handoff_verification.get("status") == "pass"):
        errors.append("ready_to_execute_mismatch")
    expected_handoff_ready = handoff_verification.get("external_dependency_handoff_ready") is True
    if execution.get("external_dependency_handoff_ready") is not expected_handoff_ready:
        errors.append("external_dependency_handoff_ready_mismatch")
    if require_handoff_ready and not expected_handoff_ready:
        errors.append("external_dependency_handoff_not_ready")

    steps = [_as_dict(item) for item in _as_list(execution.get("steps"))]
    current_step_request_context = _as_dict(execution.get("current_step_request_context"))
    current_recommended_sequence = _strings(execution.get("current_recommended_sequence"))
    if execution.get("clearance_sequence_version") != CLEARANCE_SEQUENCE_VERSION:
        errors.append("clearance_sequence_version_invalid")
    if execution.get("planned_step_count") != len(CLEARANCE_STEP_ORDER):
        errors.append("planned_step_count_mismatch")
    if execution.get("recorded_step_count") != len(steps):
        errors.append("recorded_step_count_mismatch")
    if len(steps) > len(CLEARANCE_STEP_ORDER):
        errors.append("recorded_steps_exceed_clearance_sequence")
    observed_step_ids = tuple(str(step.get("id") or "") for step in steps)
    if observed_step_ids != CLEARANCE_STEP_ORDER[: len(steps)]:
        errors.append("recorded_step_order_mismatch")
    ready_count = sum(1 for step in steps if step.get("ready") is True)
    blocked_count = sum(1 for step in steps if step.get("ready") is not True)
    would_execute_count = sum(1 for step in steps if step.get("would_execute") is True)
    if execution.get("ready_step_count") != ready_count:
        errors.append("ready_step_count_mismatch")
    if execution.get("blocked_step_count") != blocked_count:
        errors.append("blocked_step_count_mismatch")
    if execution.get("would_execute_step_count") != would_execute_count:
        errors.append("would_execute_step_count_mismatch")
    if would_execute_count > 1:
        errors.append("would_execute_more_than_one_step")
    if execution.get("current_step_id") not in CLEARANCE_STEP_ORDER and execution.get("current_step_id") != "none":
        errors.append("current_step_id_invalid")
    if would_execute_count and execution.get("current_step_id") != next(
        str(step.get("id") or "") for step in steps if step.get("would_execute") is True
    ):
        errors.append("current_step_id_would_execute_mismatch")
    if execution.get("next_command") and not any(
        execution.get("next_command") in _strings(step.get("commands")) for step in steps
    ):
        errors.append("next_command_not_in_recorded_steps")
    if execution.get("stopped_after_step") is True and not execution.get("stop_after_step"):
        errors.append("stopped_after_step_without_target")
    if execution.get("stop_after_step") and execution.get("stopped_after_step") is not True:
        errors.append("stop_after_step_not_reached")
    current_step = next(
        (step for step in steps if step.get("id") == execution.get("current_step_id")),
        {},
    )
    current_step_context = _as_dict(current_step.get("linked_request_context")) if current_step else {}
    if current_step_context and current_step_request_context != current_step_context:
        errors.append("current_step_request_context_mismatch")
    if execution.get("current_recommended_sequence_count") != len(current_recommended_sequence):
        errors.append("current_recommended_sequence_count_mismatch")
    if current_step and current_recommended_sequence != _strings(current_step.get("recommended_sequence")):
        errors.append("current_recommended_sequence_mismatch")
    if current_step and execution.get("current_strict_gate_command") != current_step.get("strict_gate_command"):
        errors.append("current_strict_gate_command_mismatch")

    for step in steps:
        step_id = str(step.get("id") or "")
        for field in (
            "index",
            "title",
            "stage",
            "type",
            "status",
            "ready",
            "can_start",
            "external_input_required",
            "prerequisite_step_ids",
            "current_phase",
            "planned_runs",
            "commands",
            "verification_commands",
            "evidence_outputs",
            "blocked_by",
            "linked_request_context",
            "recommended_sequence",
            "recommended_sequence_count",
            "strict_gate_command",
            "would_execute",
            "stops_after_this_step",
        ):
            if field not in step:
                errors.append(f"clearance_step_field_missing:{step_id}:{field}")
        if step.get("status") not in {"already_ready", "dry_run_ready_to_start", "blocked"}:
            errors.append(f"clearance_step_status_invalid:{step_id}")
        if step.get("would_execute") is True and step.get("status") != "dry_run_ready_to_start":
            errors.append(f"clearance_step_would_execute_status_mismatch:{step_id}")
        if step.get("ready") is not True and not _as_list(step.get("blocked_by")):
            errors.append(f"clearance_step_blocked_by_missing:{step_id}")
        if not _as_list(step.get("verification_commands")):
            errors.append(f"clearance_step_verification_commands_missing:{step_id}")
        if not _as_list(step.get("evidence_outputs")):
            errors.append(f"clearance_step_evidence_outputs_missing:{step_id}")
        request_context = _as_dict(step.get("linked_request_context"))
        recommended_sequence = _strings(step.get("recommended_sequence"))
        expected_context = CLEARANCE_REQUEST_CONTEXTS.get(step_id)
        if request_context.get("request_context_version") != REQUEST_CONTEXT_VERSION:
            errors.append(f"clearance_step_request_context_version_invalid:{step_id}")
        if request_context.get("clearance_step_id") != step_id:
            errors.append(f"clearance_step_request_context_step_id_mismatch:{step_id}")
        if expected_context:
            if request_context.get("request_context_available") is not True:
                errors.append(f"clearance_step_request_context_unavailable:{step_id}")
            for field in (
                "artifact_type",
                "request_artifact_id",
                "request_artifact_title",
                "output_path",
                "hash_field",
                "build_command",
                "verify_command",
                "strict_gate_command",
                "runtime_endpoint",
            ):
                if request_context.get(field) != expected_context[field]:
                    errors.append(f"clearance_step_request_context_{field}_mismatch:{step_id}")
            for command in (
                expected_context["build_command"],
                expected_context["verify_command"],
                expected_context["strict_gate_command"],
            ):
                if command not in recommended_sequence:
                    errors.append(f"clearance_step_recommended_sequence_missing:{step_id}:{command}")
        else:
            if request_context.get("request_context_available") is True:
                errors.append(f"clearance_step_unexpected_request_context:{step_id}")
        if step.get("recommended_sequence_count") != len(recommended_sequence):
            errors.append(f"clearance_step_recommended_sequence_count_mismatch:{step_id}")
        if step.get("strict_gate_command") != request_context.get("strict_gate_command"):
            errors.append(f"clearance_step_strict_gate_command_mismatch:{step_id}")

    hard_gate_commands = set(_strings(execution.get("hard_gate_commands")))
    for command in (
        "make verify-au-launch-status",
        "make verify-au-handoff-dossier",
        "make verify-au-external-dependency-handoff",
    ):
        if command not in hard_gate_commands:
            errors.append(f"hard_gate_command_missing:{command}")
    if not any("--require-ready" in command for command in hard_gate_commands):
        errors.append("hard_gate_require_ready_command_missing")
    for step in steps:
        request_context = _as_dict(step.get("linked_request_context"))
        for command in (
            str(request_context.get("verify_command") or ""),
            str(request_context.get("strict_gate_command") or ""),
        ):
            if command and command not in hard_gate_commands:
                errors.append(f"hard_gate_request_context_command_missing:{step.get('id')}:{command}")

    expected_status = "pass" if not _as_list(execution.get("errors")) else "fail"
    if execution.get("status") != expected_status:
        errors.append("status_mismatch")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "clearance_execution_version": execution.get("clearance_execution_version", ""),
        "clearance_execution_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_clearance_execution_hash": computed_hash,
        "hash_valid": hash_valid,
        "ready_to_execute": handoff_verification.get("status") == "pass",
        "external_dependency_handoff_ready": expected_handoff_ready,
        "current_step_id": execution.get("current_step_id", ""),
        "next_command": execution.get("next_command", ""),
        "planned_step_count": execution.get("planned_step_count", 0),
        "recorded_step_count": len(steps),
        "would_execute_step_count": would_execute_count,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU external dependency clearance dry-run JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU external dependency clearance dry-run JSON.",
    )
    parser.add_argument(
        "--require-handoff-ready",
        action="store_true",
        help="Fail unless the underlying external dependency handoff is ready.",
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
            "errors": ["clearance_execution_file_missing"],
            "hash_valid": False,
            "ready_to_execute": False,
            "external_dependency_handoff_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"clearance_execution_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "ready_to_execute": False,
            "external_dependency_handoff_ready": False,
        }
    else:
        result = verify_au_external_dependency_clearance(
            execution,
            path=path,
            require_handoff_ready=args.require_handoff_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
