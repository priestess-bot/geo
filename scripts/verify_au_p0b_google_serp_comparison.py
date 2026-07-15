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

from scripts.verify_preflight_payload import verify_preflight_payload  # noqa: E402


DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-serp-fixture-latest.json"
COMPARISON_PLAN_VERSION = "google_serp_comparison_plan_v1"
COMPARISON_SUMMARY_VERSION = "google_serp_comparison_summary_v1"
EXPECTED_MODES = ("google-serp-fixture", "google-serp-spike")
EXPECTED_GEO_CITIES = ("Australia", "Sydney")
EXPECTED_SCORE_INPUT_POLICY = "comparison evidence only until merged with full GoogleSpikeGateResult and GoogleSpikeReadinessGate"


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _append_if(errors: list[str], condition: bool, error: str) -> None:
    if condition:
        errors.append(error)


def _plan_errors(plan: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    planned_runs = _as_int(plan.get("planned_runs"))
    top_planned_runs = _as_int(payload.get("planned_runs"))
    prompt_count = _as_int(plan.get("prompt_count"))
    sample_size = _as_int(plan.get("sample_size"))
    geo_cities = tuple(str(item) for item in _as_list(plan.get("geo_cities")))
    computed_runs = (prompt_count or 0) * len(geo_cities) * (sample_size or 0)

    _append_if(errors, plan.get("comparison_version") != COMPARISON_PLAN_VERSION, "comparison_plan_version_invalid")
    _append_if(errors, plan.get("surface") != "google_aio", "comparison_plan_surface_invalid")
    _append_if(errors, plan.get("access_method") != "third_party_api", "comparison_plan_access_method_invalid")
    _append_if(
        errors,
        plan.get("collector_backend_id") != "google.third_party_serp",
        "comparison_plan_collector_backend_invalid",
    )
    _append_if(errors, prompt_count != 30, "comparison_plan_prompt_count_invalid")
    _append_if(errors, geo_cities != EXPECTED_GEO_CITIES, "comparison_plan_geo_cities_invalid")
    _append_if(errors, sample_size != 2, "comparison_plan_sample_size_invalid")
    _append_if(errors, planned_runs != 120, "comparison_plan_planned_runs_invalid")
    _append_if(errors, computed_runs != planned_runs, "comparison_plan_computed_runs_mismatch")
    _append_if(errors, top_planned_runs != planned_runs, "top_level_planned_runs_mismatch")
    _append_if(errors, _as_int(plan.get("main_google_spike_planned_runs")) != 240, "main_google_spike_planned_runs_invalid")
    _append_if(errors, plan.get("score_input_policy") != EXPECTED_SCORE_INPUT_POLICY, "comparison_plan_score_policy_invalid")
    return errors


def _summary_errors(summary: dict[str, Any], payload: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    planned_runs = _as_int(summary.get("planned_runs"))
    plan_runs = _as_int(plan.get("planned_runs"))
    attempted_runs = _as_int(summary.get("attempted_runs"))
    completed_runs = _as_int(summary.get("completed_runs"))
    failure_count = _as_int(summary.get("failure_count"))
    record_count = _as_int(payload.get("record_count"))
    success_count = _as_int(payload.get("success_count"))
    payload_failure_count = _as_int(payload.get("failure_count"))
    screenshot_or_html_runs = _as_int(summary.get("screenshot_or_html_runs"))

    _append_if(errors, summary.get("comparison_version") != COMPARISON_SUMMARY_VERSION, "comparison_summary_version_invalid")
    _append_if(errors, planned_runs != plan_runs, "comparison_summary_planned_runs_mismatch")
    _append_if(errors, attempted_runs != record_count, "comparison_summary_attempted_runs_mismatch")
    _append_if(errors, completed_runs != success_count, "comparison_summary_completed_runs_mismatch")
    _append_if(errors, failure_count != payload_failure_count, "comparison_summary_failure_count_mismatch")
    _append_if(
        errors,
        screenshot_or_html_runs is not None and completed_runs is not None and screenshot_or_html_runs > completed_runs,
        "comparison_summary_asset_runs_exceed_completed_runs",
    )
    _append_if(
        errors,
        summary.get("score_input_policy") != EXPECTED_SCORE_INPUT_POLICY,
        "comparison_summary_score_policy_invalid",
    )
    if summary.get("ready_for_comparison") is True:
        _append_if(errors, attempted_runs != plan_runs, "comparison_ready_attempted_runs_mismatch")
        _append_if(errors, completed_runs != plan_runs, "comparison_ready_completed_runs_mismatch")
        _append_if(errors, failure_count != 0, "comparison_ready_has_failures")
        _append_if(errors, screenshot_or_html_runs != completed_runs, "comparison_ready_asset_runs_missing")
    return errors


def verify_au_p0b_google_serp_comparison(
    payload: Any,
    *,
    path: Path | None = None,
    require_comparison_ready: bool = False,
    require_collector_health_ready: bool = False,
) -> dict[str, Any]:
    generic = verify_preflight_payload(payload, path=path)
    errors = list(generic.get("errors", []))
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": errors or ["payload_not_json_object"],
            "path": str(path) if path else "",
            "hash_valid": False,
            "comparison_ready": False,
            "collector_health_ready": False,
        }

    mode = str(payload.get("mode") or "")
    plan = _as_dict(payload.get("google_serp_comparison_plan"))
    summary = _as_dict(payload.get("google_serp_comparison_summary"))
    collector_health_gate = _as_dict(payload.get("collector_health_gate"))
    persistence = _as_dict(payload.get("persistence"))
    collection_summary = _as_dict(persistence.get("collection_run_summary"))
    analysis = _as_dict(persistence.get("analysis"))

    _append_if(errors, mode not in EXPECTED_MODES, "mode_not_google_serp_comparison")
    _append_if(errors, "google_spike_gate" in payload, "full_google_spike_gate_present")
    _append_if(errors, "google_spike_readiness_gate" in payload, "full_google_spike_readiness_gate_present")
    _append_if(errors, not plan, "google_serp_comparison_plan_missing")
    if plan:
        errors.extend(_plan_errors(plan, payload))

    record_count = _as_int(payload.get("record_count")) or 0
    if record_count > 0 or generic.get("phase") != "collector_health":
        _append_if(errors, not summary, "google_serp_comparison_summary_missing")
    if summary and plan:
        errors.extend(_summary_errors(summary, payload, plan))

    collector_health_ready = collector_health_gate.get("gate_status") == "pass"
    if require_collector_health_ready and not collector_health_ready:
        errors.append("collector_health_not_ready")
    comparison_ready = summary.get("ready_for_comparison") is True
    if require_comparison_ready and not comparison_ready:
        errors.append("google_serp_comparison_not_ready")

    if collection_summary:
        _append_if(
            errors,
            collection_summary.get("run_type") != "google_serp_comparison",
            "collection_summary_run_type_invalid",
        )
    if analysis:
        _append_if(errors, analysis.get("enabled") is not False, "persist_analysis_not_allowed")

    return {
        "status": "pass" if generic.get("status") == "pass" and not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "mode": mode,
        "hash_valid": generic.get("hash_valid", False),
        "preflight_payload_hash": generic.get("preflight_payload_hash", ""),
        "computed_payload_hash": generic.get("computed_payload_hash", ""),
        "output_path_matches_file": generic.get("output_path_matches_file"),
        "phase": generic.get("phase"),
        "exit_code": generic.get("exit_code"),
        "planned_runs": payload.get("planned_runs"),
        "record_count": payload.get("record_count"),
        "success_count": payload.get("success_count"),
        "failure_count": payload.get("failure_count"),
        "collector_health_ready": collector_health_ready,
        "collector_health_failure_reasons": list(collector_health_gate.get("failure_reasons", [])),
        "comparison_plan_valid": bool(plan) and not _plan_errors(plan, payload),
        "comparison_summary_present": bool(summary),
        "comparison_ready": comparison_ready,
        "main_google_spike_planned_runs": plan.get("main_google_spike_planned_runs") if plan else None,
        "full_spike_gates_absent": "google_spike_gate" not in payload and "google_spike_readiness_gate" not in payload,
        "score_input_policy": plan.get("score_input_policy") if plan else "",
        "persistence_run_type": collection_summary.get("run_type") if collection_summary else "",
        "persist_analysis_enabled": analysis.get("enabled") if analysis else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google SERP comparison preflight payload")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_SERP_FIXTURE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the google-serp fixture/spike JSON payload.",
    )
    parser.add_argument(
        "--require-comparison-ready",
        action="store_true",
        help="Fail unless the payload contains a complete ready_for_comparison summary.",
    )
    parser.add_argument(
        "--require-collector-health-ready",
        action="store_true",
        help="Fail unless collector_health_gate.gate_status is pass.",
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
            "path": str(path),
            "errors": ["google_serp_payload_file_missing"],
            "hash_valid": False,
            "comparison_ready": False,
            "collector_health_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"google_serp_payload_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "comparison_ready": False,
            "collector_health_ready": False,
        }
    else:
        result = verify_au_p0b_google_serp_comparison(
            payload,
            path=path,
            require_comparison_ready=args.require_comparison_ready,
            require_collector_health_ready=args.require_collector_health_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
