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

from scripts.build_au_p0a_runbook import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    PLATFORM_COUNT,
    RUNBOOK_VERSION,
    compute_runbook_payload_hash,
)


EXPECTED_STEP_IDS = (
    "prepare_environment",
    "preflight_collect",
    "preflight_verify_audit",
    "preflight_manifest_audit",
    "preflight_design_partner_gate",
    "small_batch_collect",
    "small_batch_manifest_gate",
    "full_batch_collect",
    "full_batch_manifest_gate",
)
REQUIRED_ENV = ("PERPLEXITY_API_KEY", "OPENAI_API_KEY", "DATABASE_URL")
REQUIRED_ARTIFACT_PATHS = (
    "preflight_json",
    "preflight_manifest",
    "small_batch_json",
    "small_batch_manifest",
    "full_batch_json",
    "full_batch_manifest",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _planned_runs(prompt_limit: object, cities: object, sample_size: object) -> int | None:
    if not isinstance(prompt_limit, int) or not isinstance(cities, list | tuple) or not isinstance(sample_size, int):
        return None
    return prompt_limit * len(cities) * sample_size * PLATFORM_COUNT


def _step_map(runbook: dict[str, Any], errors: list[str]) -> dict[str, dict[str, Any]]:
    raw_steps = runbook.get("steps")
    if not isinstance(raw_steps, list | tuple):
        errors.append("steps_missing_or_invalid")
        return {}
    steps: dict[str, dict[str, Any]] = {}
    ids: list[str] = []
    for step in raw_steps:
        if not isinstance(step, dict):
            errors.append("step_not_object")
            continue
        step_id = step.get("id")
        if not isinstance(step_id, str) or not step_id:
            errors.append("step_id_missing_or_invalid")
            continue
        ids.append(step_id)
        if step_id in steps:
            errors.append(f"duplicate_step_id:{step_id}")
        steps[step_id] = step
    if tuple(ids) != EXPECTED_STEP_IDS:
        errors.append("step_order_invalid")
    return steps


def _command_contains(step: dict[str, Any], expected: str) -> bool:
    command = step.get("command")
    return isinstance(command, list) and expected in {str(item) for item in command}


def verify_au_p0a_runbook(runbook: Any, *, path: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(runbook, dict):
        return {
            "status": "fail",
            "errors": ["runbook_not_json_object"],
            "hash_valid": False,
        }

    if runbook.get("runbook_version") != RUNBOOK_VERSION:
        errors.append("runbook_version_invalid")
    expected_hash = runbook.get("runbook_payload_hash")
    computed_hash = compute_runbook_payload_hash(runbook)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("runbook_payload_hash_mismatch")

    required_env = tuple(str(item) for item in _as_sequence(runbook.get("required_env")))
    if required_env != REQUIRED_ENV:
        errors.append("required_env_invalid")

    artifact_paths = _as_dict(runbook.get("artifact_paths"))
    for key in REQUIRED_ARTIFACT_PATHS:
        if not isinstance(artifact_paths.get(key), str) or not artifact_paths.get(key):
            errors.append(f"artifact_path_missing:{key}")

    scope = _as_dict(runbook.get("scope"))
    sample_size = scope.get("sample_size")
    small_batch = _as_dict(scope.get("small_batch"))
    full_batch = _as_dict(scope.get("full_batch"))
    small_expected = _planned_runs(small_batch.get("prompt_limit"), small_batch.get("cities"), sample_size)
    full_expected = _planned_runs(full_batch.get("prompt_limit"), full_batch.get("cities"), sample_size)
    if small_expected is None or small_batch.get("planned_runs") != small_expected:
        errors.append("small_batch_planned_runs_invalid")
    if full_expected is None or full_batch.get("planned_runs") != full_expected:
        errors.append("full_batch_planned_runs_invalid")

    steps = _step_map(runbook, errors)
    if steps:
        if steps["prepare_environment"].get("type") != "manual":
            errors.append("prepare_environment_step_type_invalid")
        for step_id in EXPECTED_STEP_IDS[1:]:
            if steps.get(step_id, {}).get("stop_on_failure") is not True:
                errors.append(f"step_must_stop_on_failure:{step_id}")
        if steps.get("preflight_collect", {}).get("planned_runs") != PLATFORM_COUNT * 3:
            errors.append("preflight_planned_runs_invalid")
        if small_expected is not None and steps.get("small_batch_collect", {}).get("planned_runs") != small_expected:
            errors.append("small_batch_step_planned_runs_invalid")
        if full_expected is not None and steps.get("full_batch_collect", {}).get("planned_runs") != full_expected:
            errors.append("full_batch_step_planned_runs_invalid")
        for step_id in ("preflight_design_partner_gate", "small_batch_manifest_gate", "full_batch_manifest_gate"):
            if not _command_contains(steps.get(step_id, {}), "--require-design-partner-ready"):
                errors.append(f"design_partner_gate_missing:{step_id}")
        for step_id in ("small_batch_collect", "full_batch_collect"):
            step = steps.get(step_id, {})
            for required_flag in ("--require-ready-collectors", "--require-p0a-readiness", "--require-no-collection-failures"):
                if not _command_contains(step, required_flag):
                    errors.append(f"collection_gate_missing:{step_id}:{required_flag}")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "runbook_version": runbook.get("runbook_version"),
        "runbook_payload_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_runbook_payload_hash": computed_hash,
        "hash_valid": hash_valid,
        "small_batch_planned_runs": small_batch.get("planned_runs"),
        "full_batch_planned_runs": full_batch.get("planned_runs"),
        "step_count": len(_as_sequence(runbook.get("steps"))),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a generated AU P0a real-batch runbook")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0A_RUNBOOK_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the generated AU P0a runbook JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        runbook = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["runbook_file_missing"],
            "hash_valid": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"runbook_json_invalid:{exc.msg}"],
            "hash_valid": False,
        }
    else:
        result = verify_au_p0a_runbook(runbook, path=path)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
