from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import P0A_GEO_CITIES, P0A_SAMPLE_SIZE, build_p0a_collection_plan
from geno_core.prompt_pack import PROMPT_VERSION_AU_DTC_V1


PLAN_VERSION = "au_retest_scheduler_plan_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-retest-scheduler-plan-latest.json"
DEFAULT_PROJECT_ID = "au-dtc-design-partner"
DEFAULT_OFFSETS_DAYS = (0, 7, 14, 30)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_retest_scheduler_plan_hash(plan: dict[str, Any]) -> str:
    payload = dict(plan)
    payload.pop("retest_scheduler_plan_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


def _shell_command(command: list[str], env: dict[str, str] | None = None) -> str:
    env_prefix = [f"{key}={shlex.quote(value)}" for key, value in (env or {}).items()]
    return " ".join((*env_prefix, shlex.join(command)))


def _retest_output_path(offset_day: int) -> str:
    label = "baseline" if offset_day == 0 else f"t-plus-{offset_day}"
    return f"docs/runtime_preflight/au-retest-{label}.json"


def _manifest_output_path(offset_day: int) -> str:
    label = "baseline" if offset_day == 0 else f"t-plus-{offset_day}"
    return f"docs/runtime_preflight/au-retest-{label}-manifest.json"


def _window_command(*, prompt_limit: int, cities: tuple[str, ...], sample_size: int, output_path: str) -> list[str]:
    return [
        "python3",
        "workers/collector_worker/run_collection_slice.py",
        "--mode",
        "api",
        "--prompt-limit",
        str(prompt_limit),
        "--cities",
        ",".join(cities),
        "--sample-size",
        str(sample_size),
        "--require-ready-collectors",
        "--require-p0a-readiness",
        "--require-no-collection-failures",
        "--persist",
        "--persist-analysis",
        "--preflight-output-path",
        output_path,
    ]


def _manifest_command(*, payload_path: str, manifest_path: str) -> list[str]:
    return [
        "python3",
        "scripts/build_preflight_manifest.py",
        payload_path,
        "--manifest-path",
        manifest_path,
        "--require-design-partner-ready",
    ]


def build_au_retest_scheduler_plan(
    *,
    output_path: Path | None = None,
    project_id: str = DEFAULT_PROJECT_ID,
    generated_at: str | None = None,
    offsets_days: tuple[int, ...] = DEFAULT_OFFSETS_DAYS,
) -> dict[str, Any]:
    bootstrap = build_au_project_bootstrap()
    collection_plan = build_p0a_collection_plan(
        project_id=project_id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        geo_cities=P0A_GEO_CITIES,
        sample_size=P0A_SAMPLE_SIZE,
    )
    python_env = {"PYTHONPATH": "packages/geno_core:apps/api"}
    planned_runs_per_window = collection_plan.planned_runs
    timeline: list[dict[str, Any]] = []
    for offset_day in offsets_days:
        output = _retest_output_path(offset_day)
        manifest = _manifest_output_path(offset_day)
        label = "T0 baseline" if offset_day == 0 else f"T+{offset_day} retest"
        collect_command = _window_command(
            prompt_limit=collection_plan.prompt_count,
            cities=collection_plan.geo_cities,
            sample_size=collection_plan.sample_size,
            output_path=output,
        )
        manifest_command = _manifest_command(payload_path=output, manifest_path=manifest)
        timeline.append(
            {
                "id": "baseline" if offset_day == 0 else f"t_plus_{offset_day}",
                "label": label,
                "offset_day": offset_day,
                "planned_runs": planned_runs_per_window,
                "prompt_version": PROMPT_VERSION_AU_DTC_V1,
                "sample_size": collection_plan.sample_size,
                "platform_surfaces": list(collection_plan.platform_surfaces),
                "geo_cities": list(collection_plan.geo_cities),
                "commands": (
                    {
                        "id": "collect",
                        "env": python_env,
                        "command": collect_command,
                        "shell_command": _shell_command(collect_command, python_env),
                        "output_path": output,
                        "stop_on_failure": True,
                    },
                    {
                        "id": "manifest",
                        "env": python_env,
                        "command": manifest_command,
                        "shell_command": _shell_command(manifest_command, python_env),
                        "output_path": manifest,
                        "stop_on_failure": True,
                    },
                ),
                "evidence_outputs": [output, manifest],
            }
        )

    plan: dict[str, Any] = {
        "plan_version": PLAN_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass",
        "retest_scheduler_plan_ready": True,
        "project_id": project_id,
        "scope": {
            "market_code": bootstrap.market_profile.market_code,
            "locale": bootstrap.market_profile.locale,
            "industry_code": bootstrap.industry_profile.industry_code,
            "prompt_version": PROMPT_VERSION_AU_DTC_V1,
            "prompt_count": collection_plan.prompt_count,
            "platform_surfaces": list(collection_plan.platform_surfaces),
            "geo_cities": list(collection_plan.geo_cities),
            "sample_size": collection_plan.sample_size,
            "offsets_days": list(offsets_days),
            "window_count": len(offsets_days),
            "planned_runs_per_window": planned_runs_per_window,
            "total_planned_runs": planned_runs_per_window * len(offsets_days),
        },
        "scheduler_policy": {
            "scheduler_status": "planned_not_temporalized",
            "execution_mode": "manual_or_cron_replayable",
            "replay_key": {
                "project_id": project_id,
                "prompt_version": PROMPT_VERSION_AU_DTC_V1,
                "market_code": bootstrap.market_profile.market_code,
                "sample_size": collection_plan.sample_size,
                "platform_surfaces": list(collection_plan.platform_surfaces),
                "geo_cities": list(collection_plan.geo_cities),
            },
            "immutability_requirements": [
                "Use the same prompt_version, platform surfaces, geo cities, and sample_size for all retest windows.",
                "Write a JSON payload and manifest for each window before comparing scores.",
                "Do not compare T+ windows against a baseline that failed the P0a design-partner gate.",
            ],
        },
        "timeline": timeline,
        "verification_commands": [
            {"shell": "make au-retest-scheduler-plan"},
            {"shell": "make verify-au-retest-scheduler-plan"},
            {"shell": "make au-p0a-status"},
            {"shell": "make verify-au-p0a-status"},
        ],
        "runtime_endpoints": {
            "retest_scheduler_plan": "GET /v1/au-retest-scheduler-plan",
            "runtime_action_plans": "GET /v1/action-plans/runtime",
        },
        "paths": {
            "output": str(output_path or DEFAULT_OUTPUT_PATH),
        },
        "current_boundary": {
            "real_external_runs_completed": False,
            "temporal_scheduler_implemented": False,
            "requires_p0a_environment_ready": True,
            "requires_design_partner_ready_baseline": True,
            "notes": [
                "This plan is a deterministic execution contract, not evidence that any T-window collection has already run.",
                "The existing RetestSchedule/RetestComparison model stores runtime comparisons after persisted evidence exists.",
            ],
        },
    }
    plan["retest_scheduler_plan_hash"] = compute_retest_scheduler_plan_hash(plan)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the AU retest scheduler plan JSON.")
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_RETEST_SCHEDULER_PLAN_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU retest scheduler plan JSON.",
    )
    parser.add_argument("--project-id", default=os.environ.get("GENO_AU_RETEST_PROJECT_ID", DEFAULT_PROJECT_ID))
    parser.add_argument("--generated-at", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    plan = build_au_retest_scheduler_plan(
        output_path=output_path,
        project_id=args.project_id,
        generated_at=args.generated_at,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
