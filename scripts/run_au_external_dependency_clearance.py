from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_au_external_dependency_handoff import DEFAULT_OUTPUT_PATH as DEFAULT_HANDOFF_PATH  # noqa: E402
from scripts.verify_au_external_dependency_handoff import verify_au_external_dependency_handoff  # noqa: E402


EXECUTION_VERSION = "au_external_dependency_clearance_execution_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-external-dependency-clearance-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_clearance_execution_hash(execution: dict[str, Any]) -> str:
    payload = dict(execution)
    payload.pop("clearance_execution_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


def _with_hash(execution: dict[str, Any]) -> dict[str, Any]:
    execution["clearance_execution_hash"] = compute_clearance_execution_hash(execution)
    return execution


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _load_handoff(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, ["external_dependency_handoff_file_missing"]
    except json.JSONDecodeError as exc:
        return None, [f"external_dependency_handoff_json_invalid:{exc.msg}"]
    if not isinstance(payload, dict):
        return None, ["external_dependency_handoff_not_json_object"]
    return payload, []


def _step_result(step: dict[str, Any], *, stop_after_step: str | None) -> dict[str, Any]:
    step_id = str(step.get("id") or "")
    ready = step.get("ready") is True
    can_start = step.get("can_start") is True
    if ready:
        status = "already_ready"
    elif can_start:
        status = "dry_run_ready_to_start"
    else:
        status = "blocked"
    return {
        "index": int(step.get("order") or 0),
        "id": step_id,
        "title": str(step.get("title") or ""),
        "stage": str(step.get("stage") or ""),
        "type": str(step.get("type") or ""),
        "status": status,
        "ready": ready,
        "can_start": can_start,
        "external_input_required": step.get("external_input_required") is True,
        "prerequisite_step_ids": _strings(step.get("prerequisite_step_ids")),
        "current_phase": str(step.get("current_phase") or ""),
        "planned_runs": int(step.get("planned_runs") or 0),
        "commands": _strings(step.get("commands")),
        "verification_commands": _strings(step.get("verification_commands")),
        "evidence_outputs": _strings(step.get("evidence_outputs")),
        "blocked_by": _strings(step.get("blocked_by")),
        "would_execute": can_start and not ready,
        "stops_after_this_step": bool(stop_after_step and step_id == stop_after_step),
    }


def run_au_external_dependency_clearance(
    *,
    handoff_path: Path = Path(DEFAULT_HANDOFF_PATH),
    output_path: Path | None = None,
    stop_after_step: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    handoff, load_errors = _load_handoff(handoff_path)
    if handoff is None:
        return _with_hash(
            {
                "clearance_execution_version": EXECUTION_VERSION,
                "generated_at": generated_at or _utc_now_iso(),
                "mode": "dry_run",
                "status": "fail",
                "ready_to_execute": False,
                "external_dependency_handoff_ready": False,
                "handoff_path": str(handoff_path),
                "output_path": str(output_path) if output_path else "",
                "errors": load_errors,
                "handoff_verification": {
                    "status": "fail",
                    "hash_valid": False,
                    "external_dependency_handoff_ready": False,
                    "errors": load_errors,
                },
                "clearance_sequence_version": "",
                "planned_step_count": 0,
                "recorded_step_count": 0,
                "ready_step_count": 0,
                "blocked_step_count": 0,
                "would_execute_step_count": 0,
                "current_step_id": "none",
                "next_command": "",
                "stop_after_step": stop_after_step or "",
                "stopped_after_step": False,
                "hard_gate_commands": [],
                "steps": [],
            }
        )

    handoff_verification = verify_au_external_dependency_handoff(handoff, path=handoff_path)
    sequence = _as_dict(handoff.get("clearance_sequence"))
    steps: list[dict[str, Any]] = []
    stopped_after_step = False
    for step in _as_list(sequence.get("steps")):
        step_result = _step_result(_as_dict(step), stop_after_step=stop_after_step)
        steps.append(step_result)
        if step_result["stops_after_this_step"]:
            stopped_after_step = True
            break

    errors: list[str] = []
    if handoff_verification.get("status") != "pass":
        errors.extend(f"handoff:{error}" for error in _strings(handoff_verification.get("errors")))
    if not steps and not errors:
        errors.append("clearance_sequence_steps_missing")
    if stop_after_step and not stopped_after_step:
        errors.append(f"stop_after_step_not_found:{stop_after_step}")

    ready_step_count = sum(1 for step in steps if step.get("ready") is True)
    blocked_step_count = sum(1 for step in steps if step.get("ready") is not True)
    would_execute_steps = [step for step in steps if step.get("would_execute") is True]
    result = {
        "clearance_execution_version": EXECUTION_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "mode": "dry_run",
        "status": "pass" if not errors else "fail",
        "ready_to_execute": handoff_verification.get("status") == "pass",
        "external_dependency_handoff_ready": handoff.get("external_dependency_handoff_ready") is True,
        "handoff_path": str(handoff_path),
        "output_path": str(output_path) if output_path else "",
        "errors": errors,
        "handoff_verification": handoff_verification,
        "clearance_sequence_version": str(sequence.get("version") or ""),
        "planned_step_count": int(sequence.get("step_count") or len(_as_list(sequence.get("steps")))),
        "recorded_step_count": len(steps),
        "ready_step_count": ready_step_count,
        "blocked_step_count": blocked_step_count,
        "would_execute_step_count": len(would_execute_steps),
        "current_step_id": str(sequence.get("current_step_id") or "none"),
        "next_command": str(sequence.get("next_command") or ""),
        "stop_after_step": stop_after_step or "",
        "stopped_after_step": stopped_after_step,
        "hard_gate_commands": _strings(sequence.get("hard_gate_commands")),
        "steps": steps,
    }
    return _with_hash(result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dry-run the AU external dependency clearance sequence")
    parser.add_argument(
        "--handoff-path",
        default=os.environ.get("GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH", DEFAULT_HANDOFF_PATH),
        help="Path to the AU external dependency handoff JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU external dependency clearance dry-run JSON.",
    )
    parser.add_argument(
        "--stop-after-step",
        default=os.environ.get("GENO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_STOP_AFTER_STEP", ""),
        help="Stop recording after the named clearance step id.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    result = run_au_external_dependency_clearance(
        handoff_path=Path(args.handoff_path),
        output_path=output_path,
        stop_after_step=args.stop_after_step or None,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
