from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_au_p0a_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_PATH  # noqa: E402
from scripts.verify_au_p0a_runbook import verify_au_p0a_runbook  # noqa: E402


EXECUTION_VERSION = "au_p0a_runbook_execution_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-runbook-execution-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_execution_bytes(execution: dict[str, Any]) -> bytes:
    return json.dumps(
        execution,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def compute_execution_payload_hash(execution: dict[str, Any]) -> str:
    payload_for_hash = dict(execution)
    payload_for_hash.pop("execution_payload_hash", None)
    return hashlib.sha256(_stable_execution_bytes(payload_for_hash)).hexdigest()


def _with_payload_hash(execution: dict[str, Any]) -> dict[str, Any]:
    execution["execution_payload_hash"] = compute_execution_payload_hash(execution)
    return execution


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _step_env(step: dict[str, Any]) -> dict[str, str]:
    return {str(key): str(value) for key, value in _as_dict(step.get("env")).items()}


def _command(step: dict[str, Any]) -> list[str]:
    return [str(item) for item in _as_list(step.get("command"))]


def _env_status(runbook: dict[str, Any], env: dict[str, str] | None) -> dict[str, Any]:
    env_map = os.environ if env is None else env
    required = [str(item) for item in _as_list(runbook.get("required_env"))]
    recommended = [str(item) for item in _as_list(runbook.get("recommended_env"))]
    missing_required = [name for name in required if not env_map.get(name)]
    missing_recommended = [name for name in recommended if not env_map.get(name)]
    return {
        "status": "pass" if not missing_required else "fail",
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "secrets_redacted": True,
    }


def _external_call_risk(step: dict[str, Any]) -> str:
    step_id = str(step.get("id", ""))
    if step_id in {"preflight_collect", "small_batch_collect", "full_batch_collect"}:
        return "provider_api_call"
    return "local_verifier_or_manifest"


def _step_result(
    step: dict[str, Any],
    *,
    index: int,
    execute: bool,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    command = _command(step)
    entry: dict[str, Any] = {
        "index": index,
        "id": step.get("id", ""),
        "title": step.get("title", ""),
        "type": step.get("type", ""),
        "planned_runs": step.get("planned_runs"),
        "stop_on_failure": step.get("stop_on_failure", False),
        "output_paths": _as_list(step.get("output_paths")),
        "external_call_risk": _external_call_risk(step),
        "status": "planned",
        "exit_code": None,
        "command": command,
        "shell_command": step.get("shell_command", ""),
        "env": _step_env(step),
    }
    if step.get("type") != "command":
        entry["status"] = "manual"
        entry["notes"] = _as_list(step.get("notes"))
        return entry
    if not command:
        entry.update({"status": "fail", "exit_code": 2, "errors": ["command_missing"]})
        return entry
    if not execute:
        entry["status"] = "dry_run"
        return entry

    merged_env = dict(os.environ)
    if env is not None:
        merged_env.update(env)
    merged_env.update(_step_env(step))
    completed = subprocess.run(command, env=merged_env, capture_output=True, text=True, check=False)
    entry.update(
        {
            "status": "pass" if completed.returncode == 0 else "fail",
            "exit_code": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
        }
    )
    return entry


def run_au_p0a_runbook(
    *,
    runbook_path: Path = Path(DEFAULT_RUNBOOK_PATH),
    output_path: Path | None = None,
    execute: bool = False,
    stop_after_step: str | None = None,
    env: dict[str, str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    try:
        runbook = json.loads(runbook_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _with_payload_hash({
            "execution_version": EXECUTION_VERSION,
            "generated_at": generated_at or _utc_now_iso(),
            "mode": "execute" if execute else "dry_run",
            "status": "fail",
            "ready_to_execute": False,
            "errors": ["runbook_file_missing"],
            "runbook_path": str(runbook_path),
            "output_path": str(output_path) if output_path else "",
            "steps": [],
        })
    except json.JSONDecodeError as exc:
        return _with_payload_hash({
            "execution_version": EXECUTION_VERSION,
            "generated_at": generated_at or _utc_now_iso(),
            "mode": "execute" if execute else "dry_run",
            "status": "fail",
            "ready_to_execute": False,
            "errors": [f"runbook_json_invalid:{exc.msg}"],
            "runbook_path": str(runbook_path),
            "output_path": str(output_path) if output_path else "",
            "steps": [],
        })
    if not isinstance(runbook, dict):
        return _with_payload_hash({
            "execution_version": EXECUTION_VERSION,
            "generated_at": generated_at or _utc_now_iso(),
            "mode": "execute" if execute else "dry_run",
            "status": "fail",
            "ready_to_execute": False,
            "errors": ["runbook_not_json_object"],
            "runbook_path": str(runbook_path),
            "output_path": str(output_path) if output_path else "",
            "steps": [],
        })

    verification = verify_au_p0a_runbook(runbook, path=runbook_path)
    environment = _env_status(runbook, env)
    steps: list[dict[str, Any]] = []
    errors: list[str] = []
    if verification["status"] != "pass":
        errors.extend(f"runbook:{error}" for error in verification["errors"])
    if execute and environment["status"] != "pass":
        errors.extend(f"environment:required_env_missing:{name}" for name in environment["missing_required"])

    stopped_after_step = False
    executed_count = 0
    failed_step_id = ""
    if not errors:
        for index, step in enumerate(_as_list(runbook.get("steps")), start=1):
            if not isinstance(step, dict):
                errors.append("step_not_object")
                continue
            result = _step_result(step, index=index, execute=execute, env=env)
            steps.append(result)
            if result["status"] in {"pass", "fail"}:
                executed_count += 1
            if result["status"] == "fail":
                failed_step_id = str(result.get("id", ""))
                errors.append(f"step_failed:{failed_step_id}")
                if result.get("stop_on_failure") is True:
                    break
            if stop_after_step and result.get("id") == stop_after_step:
                stopped_after_step = True
                break

    status = "pass" if not errors else "fail"
    ready_to_execute = verification["status"] == "pass" and environment["status"] == "pass"
    return _with_payload_hash({
        "execution_version": EXECUTION_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "mode": "execute" if execute else "dry_run",
        "status": status,
        "ready_to_execute": ready_to_execute,
        "execute_requested": execute,
        "runbook_path": str(runbook_path),
        "output_path": str(output_path) if output_path else "",
        "stop_after_step": stop_after_step or "",
        "stopped_after_step": stopped_after_step,
        "failed_step_id": failed_step_id,
        "errors": errors,
        "runbook_verification": verification,
        "environment": environment,
        "planned_step_count": len(_as_list(runbook.get("steps"))),
        "recorded_step_count": len(steps),
        "executed_command_count": executed_count,
        "steps": steps,
    })


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dry-run or execute the generated AU P0a runbook")
    parser.add_argument(
        "--runbook-path",
        default=os.environ.get("GENO_AU_P0A_RUNBOOK_OUTPUT_PATH", DEFAULT_RUNBOOK_PATH),
        help="Path to the generated AU P0a runbook JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the runbook execution JSON.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute command steps. Default is dry-run only.",
    )
    parser.add_argument(
        "--stop-after-step",
        default=os.environ.get("GENO_AU_P0A_STOP_AFTER_STEP", ""),
        help="Stop after recording/executing the named step id.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    result = run_au_p0a_runbook(
        runbook_path=Path(args.runbook_path),
        output_path=output_path,
        execute=args.execute,
        stop_after_step=args.stop_after_step or None,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
