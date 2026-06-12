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

from scripts.build_au_retest_scheduler_plan import (  # noqa: E402
    DEFAULT_OFFSETS_DAYS,
    DEFAULT_OUTPUT_PATH,
    PLAN_VERSION,
    compute_retest_scheduler_plan_hash,
)


REQUIRED_FIELDS = (
    "plan_version",
    "generated_at",
    "status",
    "retest_scheduler_plan_ready",
    "project_id",
    "scope",
    "scheduler_policy",
    "timeline",
    "verification_commands",
    "runtime_endpoints",
    "paths",
    "current_boundary",
    "retest_scheduler_plan_hash",
)
EXPECTED_PLATFORM_SURFACES = ("chatgpt:chatgpt_search", "perplexity:sonar")
EXPECTED_GEO_CITIES = ("Australia", "Sydney", "Melbourne", "Brisbane")
REQUIRED_COMMAND_FLAGS = (
    "--mode",
    "api",
    "--prompt-limit",
    "100",
    "--cities",
    "Australia,Sydney,Melbourne,Brisbane",
    "--sample-size",
    "3",
    "--require-ready-collectors",
    "--require-p0a-readiness",
    "--require-no-collection-failures",
    "--persist",
    "--persist-analysis",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _command_items(command: object) -> set[str]:
    if not isinstance(command, list):
        return set()
    return {str(item) for item in command}


def verify_au_retest_scheduler_plan(plan: Any, *, path: Path | None = None) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {
            "status": "fail",
            "errors": ["retest_scheduler_plan_not_json_object"],
            "hash_valid": False,
            "retest_scheduler_plan_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in plan:
            errors.append(f"field_missing:{field}")
    if plan.get("plan_version") != PLAN_VERSION:
        errors.append("plan_version_invalid")
    expected_hash = plan.get("retest_scheduler_plan_hash")
    computed_hash = compute_retest_scheduler_plan_hash(plan)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("retest_scheduler_plan_hash_mismatch")

    scope = _as_dict(plan.get("scope"))
    if scope.get("market_code") != "AU":
        errors.append("scope_market_code_invalid")
    if scope.get("locale") != "en-AU":
        errors.append("scope_locale_invalid")
    if scope.get("prompt_version") != "au_dtc_ecommerce_v1":
        errors.append("scope_prompt_version_invalid")
    if scope.get("prompt_count") != 100:
        errors.append("scope_prompt_count_invalid")
    if tuple(_as_list(scope.get("platform_surfaces"))) != EXPECTED_PLATFORM_SURFACES:
        errors.append("scope_platform_surfaces_invalid")
    if tuple(_as_list(scope.get("geo_cities"))) != EXPECTED_GEO_CITIES:
        errors.append("scope_geo_cities_invalid")
    if scope.get("sample_size") != 3:
        errors.append("scope_sample_size_invalid")
    if tuple(_as_list(scope.get("offsets_days"))) != DEFAULT_OFFSETS_DAYS:
        errors.append("scope_offsets_days_invalid")
    if scope.get("window_count") != len(DEFAULT_OFFSETS_DAYS):
        errors.append("scope_window_count_invalid")
    if scope.get("planned_runs_per_window") != 2400:
        errors.append("scope_planned_runs_per_window_invalid")
    if scope.get("total_planned_runs") != 9600:
        errors.append("scope_total_planned_runs_invalid")

    scheduler_policy = _as_dict(plan.get("scheduler_policy"))
    if scheduler_policy.get("scheduler_status") != "planned_not_temporalized":
        errors.append("scheduler_status_invalid")
    replay_key = _as_dict(scheduler_policy.get("replay_key"))
    if replay_key.get("prompt_version") != scope.get("prompt_version"):
        errors.append("replay_key_prompt_version_mismatch")
    if replay_key.get("sample_size") != scope.get("sample_size"):
        errors.append("replay_key_sample_size_mismatch")

    timeline = [_as_dict(item) for item in _as_list(plan.get("timeline"))]
    if len(timeline) != len(DEFAULT_OFFSETS_DAYS):
        errors.append("timeline_window_count_invalid")
    for index, (window, offset_day) in enumerate(zip(timeline, DEFAULT_OFFSETS_DAYS, strict=False)):
        if window.get("offset_day") != offset_day:
            errors.append(f"timeline_offset_invalid:{index}")
        if window.get("planned_runs") != 2400:
            errors.append(f"timeline_planned_runs_invalid:{index}")
        if window.get("prompt_version") != "au_dtc_ecommerce_v1":
            errors.append(f"timeline_prompt_version_invalid:{index}")
        if window.get("sample_size") != 3:
            errors.append(f"timeline_sample_size_invalid:{index}")
        if tuple(_as_list(window.get("platform_surfaces"))) != EXPECTED_PLATFORM_SURFACES:
            errors.append(f"timeline_platform_surfaces_invalid:{index}")
        if tuple(_as_list(window.get("geo_cities"))) != EXPECTED_GEO_CITIES:
            errors.append(f"timeline_geo_cities_invalid:{index}")
        commands = [_as_dict(item) for item in _as_list(window.get("commands"))]
        command_ids = tuple(str(item.get("id", "")) for item in commands)
        if command_ids != ("collect", "manifest"):
            errors.append(f"timeline_command_ids_invalid:{index}")
        if commands:
            collect = commands[0]
            collect_items = _command_items(collect.get("command"))
            for flag in REQUIRED_COMMAND_FLAGS:
                if flag not in collect_items:
                    errors.append(f"collect_command_flag_missing:{index}:{flag}")
            if collect.get("stop_on_failure") is not True:
                errors.append(f"collect_stop_on_failure_invalid:{index}")
        if len(commands) > 1:
            manifest = commands[1]
            manifest_items = _command_items(manifest.get("command"))
            if "scripts/build_preflight_manifest.py" not in manifest_items:
                errors.append(f"manifest_command_invalid:{index}")
            if "--require-design-partner-ready" not in manifest_items:
                errors.append(f"manifest_gate_missing:{index}")
            if manifest.get("stop_on_failure") is not True:
                errors.append(f"manifest_stop_on_failure_invalid:{index}")
        outputs = [str(item) for item in _as_list(window.get("evidence_outputs"))]
        if len(outputs) != 2 or not all(output.startswith("docs/runtime_preflight/au-retest-") for output in outputs):
            errors.append(f"timeline_evidence_outputs_invalid:{index}")

    boundary = _as_dict(plan.get("current_boundary"))
    if boundary.get("real_external_runs_completed") is not False:
        errors.append("boundary_real_external_runs_must_be_false")
    if boundary.get("temporal_scheduler_implemented") is not False:
        errors.append("boundary_temporal_scheduler_must_be_false")
    if boundary.get("requires_p0a_environment_ready") is not True:
        errors.append("boundary_requires_p0a_environment_ready_invalid")
    if boundary.get("requires_design_partner_ready_baseline") is not True:
        errors.append("boundary_requires_design_partner_ready_baseline_invalid")

    endpoints = _as_dict(plan.get("runtime_endpoints"))
    if endpoints.get("retest_scheduler_plan") != "GET /v1/au-retest-scheduler-plan":
        errors.append("runtime_endpoint_retest_scheduler_plan_invalid")
    if endpoints.get("runtime_action_plans") != "GET /v1/action-plans/runtime":
        errors.append("runtime_endpoint_action_plans_invalid")

    ready = not errors and plan.get("retest_scheduler_plan_ready") is True
    return {
        "status": "pass" if ready else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "plan_version": plan.get("plan_version", ""),
        "retest_scheduler_plan_hash": expected_hash,
        "computed_retest_scheduler_plan_hash": computed_hash,
        "hash_valid": hash_valid,
        "retest_scheduler_plan_ready": plan.get("retest_scheduler_plan_ready") is True,
        "window_count": len(timeline),
        "planned_runs_per_window": scope.get("planned_runs_per_window"),
        "total_planned_runs": scope.get("total_planned_runs"),
        "scheduler_status": scheduler_policy.get("scheduler_status", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the AU retest scheduler plan JSON.")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_RETEST_SCHEDULER_PLAN_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
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
            "retest_scheduler_plan_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "errors": [f"json_invalid:{exc.msg}"],
            "path": str(path),
            "hash_valid": False,
            "retest_scheduler_plan_ready": False,
        }
    else:
        result = verify_au_retest_scheduler_plan(payload, path=path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
