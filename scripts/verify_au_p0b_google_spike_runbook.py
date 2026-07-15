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

from scripts.build_au_p0b_google_spike_runbook import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    DEFAULT_SURFACE_COUNT,
    RUNBOOK_VERSION,
    compute_google_spike_runbook_hash,
)


EXPECTED_STEP_IDS = (
    "prepare_environment",
    "google_playwright_env",
    "google_playwright_env_verify",
    "google_playwright_smoke",
    "google_playwright_smoke_verify",
    "google_manual_backfill_verify",
    "google_spike_health_check",
    "google_spike_health_manifest",
    "google_spike_collect",
    "google_spike_manifest",
    "google_spike_decision_handoff",
)
REQUIRED_ENV = ("GOOGLE_PLAYWRIGHT_ENABLED", "MANUAL_BACKFILL_PATH", "DATABASE_URL")
REQUIRED_ARTIFACT_PATHS = (
    "playwright_env_json",
    "playwright_smoke_json",
    "manual_backfill_verification_json",
    "health_json",
    "health_manifest",
    "spike_json",
    "spike_manifest",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _planned_runs(prompt_count: object, geo_cities: object, sample_size: object) -> int | None:
    if not isinstance(prompt_count, int) or not isinstance(geo_cities, list | tuple) or not isinstance(sample_size, int):
        return None
    return prompt_count * len(geo_cities) * sample_size * DEFAULT_SURFACE_COUNT


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


def _env_contains(step: dict[str, Any], expected: str) -> bool:
    env = step.get("env")
    return isinstance(env, dict) and expected in {str(item) for item in env}


def verify_au_p0b_google_spike_runbook(runbook: Any, *, path: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(runbook, dict):
        return {"status": "fail", "errors": ["runbook_not_json_object"], "hash_valid": False}

    if runbook.get("runbook_version") != RUNBOOK_VERSION:
        errors.append("runbook_version_invalid")
    expected_hash = runbook.get("runbook_payload_hash")
    computed_hash = compute_google_spike_runbook_hash(runbook)
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
    planned_expected = _planned_runs(scope.get("prompt_count"), scope.get("geo_cities"), scope.get("sample_size"))
    if planned_expected is None or scope.get("planned_runs") != planned_expected:
        errors.append("planned_runs_invalid")
    if scope.get("surfaces") not in (["google_aio", "google_ai_mode"], ("google_aio", "google_ai_mode")):
        errors.append("surfaces_invalid")
    if scope.get("collection_paths") not in (["browser", "manual"], ("browser", "manual")):
        errors.append("collection_paths_invalid")
    pass_gate = _as_dict(scope.get("pass_gate"))
    if pass_gate.get("required_collection_path_count") != 2:
        errors.append("required_collection_path_count_invalid")

    steps = _step_map(runbook, errors)
    if steps:
        if steps["prepare_environment"].get("type") != "manual":
            errors.append("prepare_environment_step_type_invalid")
        if steps["google_spike_decision_handoff"].get("type") != "manual":
            errors.append("decision_handoff_step_type_invalid")
        for step_id in EXPECTED_STEP_IDS[1:10]:
            if steps.get(step_id, {}).get("stop_on_failure") is not True:
                errors.append(f"step_must_stop_on_failure:{step_id}")
        if planned_expected is not None:
            for step_id in ("google_spike_health_check", "google_spike_collect"):
                if steps.get(step_id, {}).get("planned_runs") != planned_expected:
                    errors.append(f"planned_runs_missing_or_invalid:{step_id}")
        env_step = steps.get("google_playwright_env", {})
        env_verify_step = steps.get("google_playwright_env_verify", {})
        smoke_step = steps.get("google_playwright_smoke", {})
        smoke_verify_step = steps.get("google_playwright_smoke_verify", {})
        manual_backfill_verify_step = steps.get("google_manual_backfill_verify", {})
        health_step = steps.get("google_spike_health_check", {})
        health_manifest_step = steps.get("google_spike_health_manifest", {})
        collect_step = steps.get("google_spike_collect", {})
        spike_manifest_step = steps.get("google_spike_manifest", {})
        if not _command_contains(env_step, "scripts/build_au_p0b_google_playwright_env_report.py"):
            errors.append("playwright_env_command_missing")
        if not _command_contains(env_step, "--runbook-path"):
            errors.append("playwright_env_runbook_path_missing")
        if not _command_contains(env_step, "--output-path"):
            errors.append("playwright_env_output_path_missing")
        if not _command_contains(env_verify_step, "scripts/verify_au_p0b_google_playwright_env_report.py"):
            errors.append("playwright_env_verify_command_missing")
        if not _command_contains(env_verify_step, "--require-ready-smoke"):
            errors.append("playwright_env_verify_ready_gate_missing")
        if not _command_contains(smoke_step, "scripts/run_au_p0b_google_playwright_smoke.py"):
            errors.append("playwright_smoke_command_missing")
        if smoke_step.get("planned_runs") != 1:
            errors.append("playwright_smoke_planned_runs_invalid")
        if not _command_contains(smoke_verify_step, "scripts/verify_au_p0b_google_playwright_smoke.py"):
            errors.append("playwright_smoke_verify_command_missing")
        if not _command_contains(smoke_verify_step, "--require-success"):
            errors.append("playwright_smoke_verify_success_gate_missing")
        if not _command_contains(manual_backfill_verify_step, "scripts/verify_au_p0b_manual_backfill.py"):
            errors.append("manual_backfill_verify_command_missing")
        if not _command_contains(manual_backfill_verify_step, "--output-path"):
            errors.append("manual_backfill_verify_output_path_missing")
        expected_manual_runs = (
            scope.get("prompt_count") * len(scope.get("geo_cities")) * scope.get("sample_size")
            if isinstance(scope.get("prompt_count"), int)
            and isinstance(scope.get("geo_cities"), list | tuple)
            and isinstance(scope.get("sample_size"), int)
            else None
        )
        if expected_manual_runs is not None and manual_backfill_verify_step.get("planned_runs") != expected_manual_runs:
            errors.append("manual_backfill_planned_runs_invalid")
        if not _command_contains(health_step, "make") or not _command_contains(health_step, "au-p0b-google-spike-health"):
            errors.append("health_make_target_missing")
        if not _env_contains(health_step, "GEO_AU_P0B_GOOGLE_SPIKE_HEALTH_OUTPUT_PATH"):
            errors.append("health_output_env_missing")
        if (
            not _command_contains(health_manifest_step, "make")
            or not _command_contains(health_manifest_step, "au-p0b-google-spike-health-manifest")
        ):
            errors.append("health_manifest_make_target_missing")
        if not _env_contains(health_manifest_step, "GEO_AU_P0B_GOOGLE_SPIKE_HEALTH_MANIFEST_PATH"):
            errors.append("health_manifest_output_env_missing")
        if not _command_contains(collect_step, "make") or not _command_contains(collect_step, "au-p0b-google-spike"):
            errors.append("collect_make_target_missing")
        if not _env_contains(collect_step, "GEO_AU_P0B_GOOGLE_SPIKE_OUTPUT_PATH"):
            errors.append("collect_output_env_missing")
        if not _command_contains(spike_manifest_step, "make") or not _command_contains(
            spike_manifest_step,
            "au-p0b-google-spike-manifest",
        ):
            errors.append("spike_manifest_make_target_missing")
        if not _env_contains(spike_manifest_step, "GEO_AU_P0B_GOOGLE_SPIKE_MANIFEST_PATH"):
            errors.append("spike_manifest_output_env_missing")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "runbook_version": runbook.get("runbook_version"),
        "runbook_payload_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_runbook_payload_hash": computed_hash,
        "hash_valid": hash_valid,
        "planned_runs": scope.get("planned_runs"),
        "step_count": len(_as_sequence(runbook.get("steps"))),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a generated AU P0b Google spike runbook")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the generated AU P0b Google spike runbook JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        runbook = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {"status": "fail", "path": str(path), "errors": ["runbook_file_missing"], "hash_valid": False}
    except json.JSONDecodeError as exc:
        result = {"status": "fail", "path": str(path), "errors": [f"runbook_json_invalid:{exc.msg}"], "hash_valid": False}
    else:
        result = verify_au_p0b_google_spike_runbook(runbook, path=path)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
