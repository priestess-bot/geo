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

from scripts.build_au_p0b_google_spike_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_PATH  # noqa: E402
from scripts.run_au_p0b_google_spike_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_EXECUTION_PATH  # noqa: E402
from scripts.verify_au_p0b_google_spike_runbook import verify_au_p0b_google_spike_runbook  # noqa: E402
from scripts.verify_au_p0b_google_spike_runbook_execution import (  # noqa: E402
    verify_au_p0b_google_spike_runbook_execution,
)
from scripts.verify_au_p0b_google_playwright_env_report import verify_google_playwright_env_report  # noqa: E402
from scripts.verify_au_p0b_google_playwright_smoke import verify_google_playwright_smoke  # noqa: E402
from scripts.verify_preflight_payload import verify_preflight_payload  # noqa: E402


STATUS_REPORT_VERSION = "au_p0b_google_spike_status_report_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-spike-status-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_status_bytes(report: dict[str, Any]) -> bytes:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_google_spike_status_hash(report: dict[str, Any]) -> str:
    payload = dict(report)
    payload.pop("status_report_hash", None)
    return hashlib.sha256(_stable_status_bytes(payload)).hexdigest()


def _load_json(path: Path) -> tuple[Any | None, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, {"path": str(path), "exists": False, "status": "fail", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        return None, {"path": str(path), "exists": True, "status": "fail", "errors": [f"json_invalid:{exc.msg}"]}
    return payload, {"path": str(path), "exists": True}


def _runbook_status(path: Path) -> dict[str, Any]:
    payload, file_entry = _load_json(path)
    if not isinstance(payload, dict):
        return {"path": str(path), "exists": file_entry["exists"], "status": "fail", "errors": file_entry["errors"], "hash_valid": False}
    verification = verify_au_p0b_google_spike_runbook(payload, path=path)
    return {
        "path": str(path),
        "exists": True,
        "status": verification["status"],
        "errors": verification["errors"],
        "hash_valid": verification["hash_valid"],
        "planned_runs": verification.get("planned_runs"),
        "step_count": verification.get("step_count"),
    }


def _execution_status(path: Path) -> dict[str, Any]:
    payload, file_entry = _load_json(path)
    if not isinstance(payload, dict):
        return {"path": str(path), "exists": file_entry["exists"], "status": "fail", "errors": file_entry["errors"], "hash_valid": False}
    verification = verify_au_p0b_google_spike_runbook_execution(payload, path=path)
    return {
        "path": str(path),
        "exists": True,
        "status": verification["status"],
        "errors": verification["errors"],
        "hash_valid": verification["hash_valid"],
        "ready_to_execute": verification["ready_to_execute"],
        "mode": verification["mode"],
        "planned_step_count": verification["planned_step_count"],
        "recorded_step_count": verification["recorded_step_count"],
    }


def _smoke_status(path: Path, *, require_success: bool = False) -> dict[str, Any]:
    payload, file_entry = _load_json(path)
    if not isinstance(payload, dict):
        return {
            "path": str(path),
            "exists": file_entry["exists"],
            "status": "fail",
            "errors": file_entry["errors"],
            "hash_valid": False,
            "smoke_success": False,
            "collector_health": "",
            "phase": "",
        }
    verification = verify_google_playwright_smoke(payload, path=path, require_success=require_success)
    return {
        "path": str(path),
        "exists": True,
        "status": verification["status"],
        "errors": verification["errors"],
        "hash_valid": verification["hash_valid"],
        "smoke_status": verification["smoke_status"],
        "smoke_success": verification["smoke_success"],
        "phase": verification["phase"],
        "collector_health": verification["collector_health"],
        "surface": verification["surface"],
        "collector_backend_id": verification["collector_backend_id"],
        "planned_runs": verification["planned_runs"],
        "record_count": verification["record_count"],
        "success_count": verification["success_count"],
        "failure_count": verification["failure_count"],
        "answer_present": verification["answer_present"],
        "surface_triggered": verification["surface_triggered"],
        "asset_count": verification["asset_count"],
    }


def _playwright_env_status(path: Path, *, require_ready_smoke: bool = False) -> dict[str, Any]:
    payload, file_entry = _load_json(path)
    if not isinstance(payload, dict):
        return {
            "path": str(path),
            "exists": file_entry["exists"],
            "status": "fail",
            "errors": file_entry["errors"],
            "hash_valid": False,
            "ready_for_playwright_smoke": False,
            "ready_for_full_google_run": False,
            "collector_health": "",
            "next_action": "",
        }
    verification = verify_google_playwright_env_report(payload, path=path, require_ready_smoke=require_ready_smoke)
    return {
        "path": str(path),
        "exists": True,
        "status": verification["status"],
        "errors": verification["errors"],
        "hash_valid": verification["hash_valid"],
        "ready_for_playwright_smoke": verification["ready_for_playwright_smoke"],
        "ready_for_full_google_run": verification["ready_for_full_google_run"],
        "collector_health": verification["collector_health"],
        "missing_required": verification["missing_required"],
        "missing_full_run_required": verification["missing_full_run_required"],
        "missing_selector_groups": verification["missing_selector_groups"],
        "next_action": verification["next_action"],
    }


def _preflight_status(
    path: Path,
    *,
    require_collector_health: bool = False,
    require_google_gates: bool = False,
) -> dict[str, Any]:
    payload, file_entry = _load_json(path)
    if not isinstance(payload, dict):
        return {
            "path": str(path),
            "exists": file_entry["exists"],
            "status": "fail",
            "errors": file_entry["errors"],
            "hash_valid": False,
            "google_gates_ready": False,
            "ready_for_design_partner": False,
        }
    verification = verify_preflight_payload(payload, path=path)
    google_gate = payload.get("google_spike_gate") if isinstance(payload.get("google_spike_gate"), dict) else {}
    readiness_gate = (
        payload.get("google_spike_readiness_gate")
        if isinstance(payload.get("google_spike_readiness_gate"), dict)
        else {}
    )
    collector_health_gate = (
        payload.get("collector_health_gate")
        if isinstance(payload.get("collector_health_gate"), dict)
        else {}
    )
    google_gates_ready = google_gate.get("gate_status") == "pass" and readiness_gate.get("gate_status") == "pass"
    errors = list(verification["errors"])
    collector_health_ready = collector_health_gate.get("gate_status") == "pass"
    if require_collector_health and not collector_health_ready:
        errors.append("collector_health_not_ready")
    if require_google_gates and not google_gates_ready:
        errors.append("google_spike_gates_not_ready")
    return {
        "path": str(path),
        "exists": True,
        "status": "pass" if verification["status"] == "pass" and not errors else "fail",
        "verifier_status": verification["status"],
        "errors": errors,
        "hash_valid": verification["hash_valid"],
        "ready_for_design_partner": verification["ready_for_design_partner"],
        "planned_runs": payload.get("planned_runs"),
        "record_count": payload.get("record_count"),
        "success_count": payload.get("success_count"),
        "failure_count": payload.get("failure_count"),
        "phase": verification.get("phase"),
        "recommended_next_action": verification.get("recommended_next_action"),
        "collector_health_ready": collector_health_ready,
        "collector_health_failure_reasons": list(collector_health_gate.get("failure_reasons", [])),
        "google_gates_ready": google_gates_ready,
        "google_spike_gate_status": google_gate.get("gate_status", "not_run"),
        "google_spike_readiness_status": readiness_gate.get("gate_status", "not_run"),
        "google_spike_failure_reasons": list(readiness_gate.get("failure_reasons", [])),
        "limited_coverage": google_gate.get("limited_coverage", True),
    }


def _manifest_status(path: Path) -> dict[str, Any]:
    payload, file_entry = _load_json(path)
    if not isinstance(payload, dict):
        return {"path": str(path), "exists": file_entry["exists"], "status": "fail", "errors": file_entry["errors"]}
    return {
        "path": str(path),
        "exists": True,
        "status": "pass" if payload.get("manifest_payload_hash") else "fail",
        "errors": [] if payload.get("manifest_payload_hash") else ["manifest_payload_hash_missing"],
        "manifest_version": payload.get("manifest_version", ""),
        "verifier_status": (payload.get("verifier") or {}).get("status") if isinstance(payload.get("verifier"), dict) else "",
    }


def _next_action(items: dict[str, dict[str, Any]]) -> str:
    if items["runbook"].get("status") != "pass":
        return "fix_google_spike_runbook"
    if items["execution"].get("status") != "pass":
        return "run_google_spike_runbook_dry_run"
    if items["playwright_env"].get("status") != "pass":
        if items["playwright_env"].get("exists") is False:
            return "run_google_playwright_env_report"
        next_action = str(items["playwright_env"].get("next_action") or "")
        return next_action or "fix_google_playwright_environment"
    if items["playwright_smoke"].get("status") != "pass":
        return "run_google_playwright_smoke"
    if items["health"].get("status") != "pass":
        return "run_google_spike_health_check"
    if items["health_manifest"].get("status") != "pass":
        return "build_google_spike_health_manifest"
    if items["spike"].get("status") != "pass":
        return "run_real_google_spike_matrix"
    if items["spike_manifest"].get("status") != "pass":
        return "build_google_spike_manifest"
    if items["spike"].get("google_gates_ready") is not True:
        return "keep_google_limited_coverage_and_fix_spike_paths"
    return "allow_google_into_main_scoring_denominator"


def build_au_p0b_google_spike_status_report(
    *,
    runbook_path: Path = Path(DEFAULT_RUNBOOK_PATH),
    execution_path: Path = Path(DEFAULT_EXECUTION_PATH),
    health_path: Path | None = None,
    health_manifest_path: Path | None = None,
    spike_path: Path | None = None,
    spike_manifest_path: Path | None = None,
    playwright_smoke_path: Path | None = None,
    playwright_env_path: Path | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    runbook_payload, _ = _load_json(runbook_path)
    artifact_paths = runbook_payload.get("artifact_paths") if isinstance(runbook_payload, dict) else {}
    artifact_paths = artifact_paths if isinstance(artifact_paths, dict) else {}
    health_path = health_path or Path(str(artifact_paths.get("health_json") or "docs/runtime_preflight/au-p0b-google-spike-health-latest.json"))
    health_manifest_path = health_manifest_path or Path(
        str(artifact_paths.get("health_manifest") or "docs/runtime_preflight/au-p0b-google-spike-health-manifest-latest.json")
    )
    spike_path = spike_path or Path(str(artifact_paths.get("spike_json") or "docs/runtime_preflight/au-p0b-google-spike-latest.json"))
    spike_manifest_path = spike_manifest_path or Path(
        str(artifact_paths.get("spike_manifest") or "docs/runtime_preflight/au-p0b-google-spike-manifest-latest.json")
    )
    playwright_smoke_path = playwright_smoke_path or Path(
        str(
            artifact_paths.get("playwright_smoke_json")
            or "docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json"
        )
    )
    playwright_env_path = playwright_env_path or Path(
        str(
            artifact_paths.get("playwright_env_json")
            or "docs/runtime_preflight/au-p0b-google-playwright-env-latest.json"
        )
    )

    items = {
        "runbook": _runbook_status(runbook_path),
        "execution": _execution_status(execution_path),
        "playwright_env": _playwright_env_status(playwright_env_path, require_ready_smoke=True),
        "playwright_smoke": _smoke_status(playwright_smoke_path, require_success=True),
        "health": _preflight_status(health_path, require_collector_health=True),
        "health_manifest": _manifest_status(health_manifest_path),
        "spike": _preflight_status(spike_path, require_google_gates=True),
        "spike_manifest": _manifest_status(spike_manifest_path),
    }
    remaining_blockers = sorted(
        {
            f"{name}:{error}"
            for name, item in items.items()
            if item.get("status") != "pass"
            for error in (item.get("errors") or ["status_not_pass"])
        }
    )
    report: dict[str, Any] = {
        "status_report_version": STATUS_REPORT_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if not remaining_blockers and items["spike"].get("google_gates_ready") is True else "fail",
        "google_main_scoring_allowed": items["spike"].get("google_gates_ready") is True,
        "limited_coverage": items["spike"].get("google_gates_ready") is not True,
        "next_action": _next_action(items),
        "remaining_blockers": remaining_blockers,
        "inputs": {
            "runbook_path": str(runbook_path),
            "execution_path": str(execution_path),
            "playwright_env_path": str(playwright_env_path),
            "playwright_smoke_path": str(playwright_smoke_path),
            "health_path": str(health_path),
            "health_manifest_path": str(health_manifest_path),
            "spike_path": str(spike_path),
            "spike_manifest_path": str(spike_manifest_path),
            "output_path": str(output_path) if output_path else "",
        },
        "artifacts": items,
    }
    report["status_report_hash"] = compute_google_spike_status_hash(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google spike status report across local gates")
    parser.add_argument(
        "--runbook-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH", DEFAULT_RUNBOOK_PATH),
    )
    parser.add_argument(
        "--execution-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH", DEFAULT_EXECUTION_PATH),
    )
    parser.add_argument("--output-path", default=os.environ.get("GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH))
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    report = build_au_p0b_google_spike_status_report(
        runbook_path=Path(args.runbook_path),
        execution_path=Path(args.execution_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
