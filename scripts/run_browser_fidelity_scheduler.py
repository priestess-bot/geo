from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers/collector_worker/run_collection_slice.py"


def _env_truthy(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _optional_arg(args: list[str], flag: str, value: str | int | None) -> None:
    if value is not None and str(value).strip():
        args.extend([flag, str(value)])


def _json_or_raw(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)


def build_plan_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(WORKER_PATH),
        "--plan-browser-fidelity-sampling",
        "--fidelity-cadence",
        args.cadence,
        "--fidelity-prompt-count",
        str(args.prompt_count),
        "--fidelity-city-count",
        str(args.city_count),
        "--sample-size",
        str(args.sample_size),
    ]
    _optional_arg(command, "--fidelity-run-date", args.run_date)
    _optional_arg(command, "--fidelity-selection-seed", args.selection_seed)
    if args.persist_plan:
        command.append("--persist")
    return command


def run_scheduler(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    plan_command = build_plan_command(args)
    plan_result = _run_command(plan_command)
    plan_payload = _json_or_raw(plan_result.stdout)
    payload: dict[str, Any] = {
        "mode": "browser_fidelity_scheduler",
        "status": "planned" if plan_result.returncode == 0 else "plan_failed",
        "execute_requested": args.execute,
        "persist_plan": args.persist_plan,
        "plan_command": plan_command,
        "plan_returncode": plan_result.returncode,
        "plan_stdout": plan_payload,
        "plan_stderr": plan_result.stderr,
        "worker_command": None,
        "worker_returncode": None,
        "worker_stdout": None,
        "worker_stderr": None,
    }
    if plan_result.returncode != 0:
        return payload, plan_result.returncode
    if not isinstance(plan_payload, dict):
        payload["status"] = "plan_unparseable"
        return payload, 2

    raw_recommended_args = plan_payload.get("recommended_worker_args")
    if not isinstance(raw_recommended_args, list) or not raw_recommended_args:
        payload["status"] = "plan_missing_worker_args"
        return payload, 2

    recommended_args = tuple(str(item) for item in raw_recommended_args)
    worker_command = [sys.executable, str(WORKER_PATH), *recommended_args]
    payload["worker_command"] = worker_command
    if not args.execute:
        return payload, 0

    worker_result = _run_command(worker_command)
    payload["status"] = "executed" if worker_result.returncode == 0 else "worker_failed"
    payload["worker_returncode"] = worker_result.returncode
    payload["worker_stdout"] = _json_or_raw(worker_result.stdout)
    payload["worker_stderr"] = worker_result.stderr
    return payload, worker_result.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan and optionally execute scheduled browser fidelity sampling")
    parser.add_argument("--run-date", default=os.environ.get("GENO_BROWSER_FIDELITY_RUN_DATE"))
    parser.add_argument("--cadence", default=os.environ.get("GENO_BROWSER_FIDELITY_CADENCE", "weekly"))
    parser.add_argument(
        "--prompt-count",
        type=int,
        default=int(os.environ.get("GENO_BROWSER_FIDELITY_PROMPT_COUNT", "10")),
    )
    parser.add_argument(
        "--city-count",
        type=int,
        default=int(os.environ.get("GENO_BROWSER_FIDELITY_CITY_COUNT", "2")),
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=int(os.environ.get("GENO_BROWSER_FIDELITY_SAMPLE_SIZE", "1")),
    )
    parser.add_argument("--selection-seed", default=os.environ.get("GENO_BROWSER_FIDELITY_SELECTION_SEED"))
    parser.add_argument(
        "--persist-plan",
        action="store_true",
        default=_env_truthy("GENO_BROWSER_FIDELITY_PERSIST_PLAN", default=False),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=_env_truthy("GENO_BROWSER_FIDELITY_EXECUTE", default=False),
    )
    return parser.parse_args()


def main() -> None:
    payload, exit_code = run_scheduler(parse_args())
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
