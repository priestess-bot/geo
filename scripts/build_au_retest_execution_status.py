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

from scripts.build_au_retest_scheduler_plan import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_RETEST_PLAN_PATH,
    build_au_retest_scheduler_plan,
)
from scripts.build_preflight_manifest import MANIFEST_VERSION, compute_manifest_payload_hash  # noqa: E402
from scripts.verify_au_retest_scheduler_plan import verify_au_retest_scheduler_plan  # noqa: E402
from scripts.verify_preflight_payload import verify_preflight_payload  # noqa: E402


STATUS_VERSION = "au_retest_execution_status_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-retest-execution-status-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_retest_execution_status_hash(status: dict[str, Any]) -> str:
    payload = dict(status)
    payload.pop("retest_execution_status_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _unique_strings(values: list[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value)
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _resolve_artifact_path(path: str, *, artifact_base_dir: Path) -> Path:
    artifact_path = Path(path)
    if artifact_path.is_absolute():
        return artifact_path
    return artifact_base_dir / artifact_path


def _load_json_file(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, ["file_missing"]
    except json.JSONDecodeError as exc:
        return None, [f"json_invalid:{exc.msg}"]
    if not isinstance(payload, dict):
        return None, ["json_not_object"]
    return payload, []


def _load_or_build_plan(*, plan_path: Path, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, errors = _load_json_file(plan_path)
    if payload is None:
        plan = build_au_retest_scheduler_plan(output_path=None, generated_at=generated_at)
        return plan, {
            "path": str(plan_path),
            "exists": False,
            "source": "generated_in_memory",
            "errors": errors,
        }
    return payload, {
        "path": str(plan_path),
        "exists": True,
        "source": "existing_file",
        "size_bytes": plan_path.stat().st_size,
        "file_sha256": _file_sha256(plan_path),
        "errors": [],
    }


def _inspect_payload(
    *,
    planned_path: str,
    artifact_base_dir: Path,
    expected_planned_runs: int,
    expected_sample_size: int,
    expected_prompt_limit: int,
    expected_cities: list[str],
) -> dict[str, Any]:
    resolved_path = _resolve_artifact_path(planned_path, artifact_base_dir=artifact_base_dir)
    payload, load_errors = _load_json_file(resolved_path)
    if payload is None:
        return {
            "path": planned_path,
            "resolved_path": str(resolved_path),
            "exists": False,
            "status": "missing",
            "ready_for_design_partner": False,
            "hash_valid": False,
            "blocking_reasons": load_errors,
            "errors": load_errors,
        }

    verifier = verify_preflight_payload(payload, path=resolved_path, require_design_partner_ready=True)
    summary = _as_dict(payload.get("preflight_summary"))
    errors = list(verifier.get("errors") or [])
    if summary.get("planned_runs", payload.get("planned_runs")) != expected_planned_runs:
        errors.append("payload_planned_runs_mismatch")
    if summary.get("sample_size") != expected_sample_size:
        errors.append("payload_sample_size_mismatch")
    if summary.get("prompt_limit") != expected_prompt_limit:
        errors.append("payload_prompt_limit_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("cities"))) != sorted(expected_cities):
        errors.append("payload_cities_mismatch")

    ready = verifier.get("ready_for_design_partner") is True and not errors
    return {
        "path": planned_path,
        "resolved_path": str(resolved_path),
        "exists": True,
        "status": "pass" if ready else "fail",
        "size_bytes": resolved_path.stat().st_size,
        "file_sha256": _file_sha256(resolved_path),
        "preflight_payload_hash": payload.get("preflight_payload_hash", ""),
        "computed_payload_hash": verifier.get("computed_payload_hash", ""),
        "hash_valid": verifier.get("hash_valid") is True,
        "ready_for_design_partner": ready,
        "verifier_status": verifier.get("status", ""),
        "phase": verifier.get("phase", ""),
        "recommended_next_action": verifier.get("recommended_next_action", ""),
        "blocking_reasons": list(verifier.get("blocking_reasons") or ()) + errors,
        "errors": errors,
    }


def _inspect_manifest(
    *,
    planned_path: str,
    artifact_base_dir: Path,
    expected_payload_path: str,
    expected_planned_runs: int,
    expected_sample_size: int,
    expected_prompt_limit: int,
    expected_cities: list[str],
) -> dict[str, Any]:
    resolved_path = _resolve_artifact_path(planned_path, artifact_base_dir=artifact_base_dir)
    manifest, load_errors = _load_json_file(resolved_path)
    if manifest is None:
        return {
            "path": planned_path,
            "resolved_path": str(resolved_path),
            "exists": False,
            "status": "missing",
            "ready_for_design_partner": False,
            "hash_valid": False,
            "blocking_reasons": load_errors,
            "errors": load_errors,
        }

    errors: list[str] = []
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        errors.append("manifest_version_invalid")
    expected_hash = manifest.get("manifest_payload_hash")
    computed_hash = compute_manifest_payload_hash(manifest)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("manifest_payload_hash_mismatch")

    run_summary = _as_dict(manifest.get("run_summary"))
    verifier = _as_dict(manifest.get("verifier"))
    preflight_payload = _as_dict(manifest.get("preflight_payload"))
    if preflight_payload.get("path") != expected_payload_path:
        errors.append("manifest_payload_path_mismatch")
    if run_summary.get("planned_runs") != expected_planned_runs:
        errors.append("manifest_planned_runs_mismatch")
    if run_summary.get("sample_size") != expected_sample_size:
        errors.append("manifest_sample_size_mismatch")
    if run_summary.get("prompt_limit") != expected_prompt_limit:
        errors.append("manifest_prompt_limit_mismatch")
    if sorted(str(item) for item in _as_list(run_summary.get("cities"))) != sorted(expected_cities):
        errors.append("manifest_cities_mismatch")

    ready = (
        not errors
        and verifier.get("status") == "pass"
        and verifier.get("ready_for_design_partner") is True
        and run_summary.get("ready_for_design_partner") is True
    )
    blocking_reasons = list(verifier.get("errors") or []) + list(_as_list(_as_dict(manifest.get("audit_checklist")).get("blocking_reasons")))
    if not ready and not blocking_reasons and not errors:
        blocking_reasons.append("manifest_not_design_partner_ready")
    return {
        "path": planned_path,
        "resolved_path": str(resolved_path),
        "exists": True,
        "status": "pass" if ready else "fail",
        "size_bytes": resolved_path.stat().st_size,
        "file_sha256": _file_sha256(resolved_path),
        "manifest_version": manifest.get("manifest_version", ""),
        "manifest_payload_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_manifest_payload_hash": computed_hash,
        "hash_valid": hash_valid,
        "ready_for_design_partner": ready,
        "verifier_status": verifier.get("status", ""),
        "blocking_reasons": blocking_reasons + errors,
        "errors": errors,
    }


def _expected_paths(window: dict[str, Any]) -> tuple[str, str]:
    outputs = [str(item) for item in _as_list(window.get("evidence_outputs"))]
    if len(outputs) >= 2:
        return outputs[0], outputs[1]
    window_id = str(window.get("id") or "unknown")
    return f"docs/runtime_preflight/au-retest-{window_id}.json", f"docs/runtime_preflight/au-retest-{window_id}-manifest.json"


def _build_window_status(*, window: dict[str, Any], scope: dict[str, Any], artifact_base_dir: Path) -> dict[str, Any]:
    payload_path, manifest_path = _expected_paths(window)
    expected_cities = [str(item) for item in _as_list(window.get("geo_cities") or scope.get("geo_cities"))]
    prompt_limit = int(scope.get("prompt_count") or 0)
    sample_size = int(window.get("sample_size") or scope.get("sample_size") or 0)
    planned_runs = int(window.get("planned_runs") or 0)
    payload_status = _inspect_payload(
        planned_path=payload_path,
        artifact_base_dir=artifact_base_dir,
        expected_planned_runs=planned_runs,
        expected_sample_size=sample_size,
        expected_prompt_limit=prompt_limit,
        expected_cities=expected_cities,
    )
    manifest_status = _inspect_manifest(
        planned_path=manifest_path,
        artifact_base_dir=artifact_base_dir,
        expected_payload_path=payload_path,
        expected_planned_runs=planned_runs,
        expected_sample_size=sample_size,
        expected_prompt_limit=prompt_limit,
        expected_cities=expected_cities,
    )
    blocking_reasons = []
    for prefix, artifact in (("payload", payload_status), ("manifest", manifest_status)):
        if not artifact.get("exists"):
            blocking_reasons.append(f"{prefix}:file_missing")
        if artifact.get("status") != "pass":
            for reason in artifact.get("blocking_reasons", []) or []:
                blocking_reasons.append(f"{prefix}:{reason}")
    window_ready = payload_status.get("ready_for_design_partner") is True and manifest_status.get("ready_for_design_partner") is True
    return {
        "id": str(window.get("id", "")),
        "label": str(window.get("label", "")),
        "offset_day": window.get("offset_day"),
        "planned_runs": planned_runs,
        "prompt_version": window.get("prompt_version", scope.get("prompt_version", "")),
        "sample_size": sample_size,
        "window_ready": window_ready,
        "payload": payload_status,
        "manifest": manifest_status,
        "missing_artifact_count": int(not payload_status.get("exists")) + int(not manifest_status.get("exists")),
        "blocking_reasons": _unique_strings(blocking_reasons),
    }


def _next_window(windows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for window in windows:
        if window.get("window_ready") is not True:
            return window
    return None


def build_au_retest_execution_status(
    *,
    plan_path: Path = Path(DEFAULT_RETEST_PLAN_PATH),
    output_path: Path | None = None,
    artifact_base_dir: Path = Path("."),
    generated_at: str | None = None,
) -> dict[str, Any]:
    plan, plan_source = _load_or_build_plan(plan_path=plan_path, generated_at=generated_at)
    plan_verifier = verify_au_retest_scheduler_plan(plan, path=plan_path if plan_source.get("exists") else None)
    scope = _as_dict(plan.get("scope"))
    windows = [
        _build_window_status(window=_as_dict(window), scope=scope, artifact_base_dir=artifact_base_dir)
        for window in _as_list(plan.get("timeline"))
    ]
    ready_windows = [window for window in windows if window.get("window_ready") is True]
    ready_retest_windows = [window for window in ready_windows if int(window.get("offset_day") or 0) > 0]
    baseline_ready = bool(windows and windows[0].get("window_ready") is True and int(windows[0].get("offset_day") or 0) == 0)
    comparison_allowed = baseline_ready and bool(ready_retest_windows)
    retest_execution_ready = len(windows) > 0 and len(ready_windows) == len(windows)
    missing_artifact_count = sum(int(window.get("missing_artifact_count") or 0) for window in windows)
    next_window = _next_window(windows)
    if next_window:
        next_action = f"run_retest_window:{next_window['id']}"
    elif comparison_allowed:
        next_action = "compare_all_retest_windows"
    else:
        next_action = "run_retest_baseline"
    status: dict[str, Any] = {
        "status_version": STATUS_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if retest_execution_ready else "fail",
        "execution_status_report_ready": True,
        "retest_execution_ready": retest_execution_ready,
        "comparison_allowed": comparison_allowed,
        "next_action": next_action,
        "plan_source": plan_source,
        "plan_verifier": plan_verifier,
        "plan_summary": {
            "plan_version": plan.get("plan_version", ""),
            "project_id": plan.get("project_id", ""),
            "prompt_version": scope.get("prompt_version", ""),
            "offsets_days": scope.get("offsets_days", []),
            "planned_runs_per_window": scope.get("planned_runs_per_window"),
            "total_planned_runs": scope.get("total_planned_runs"),
            "retest_scheduler_plan_hash": plan.get("retest_scheduler_plan_hash", ""),
        },
        "summary": {
            "window_count": len(windows),
            "ready_window_count": len(ready_windows),
            "ready_retest_window_count": len(ready_retest_windows),
            "missing_window_count": len(windows) - len(ready_windows),
            "missing_artifact_count": missing_artifact_count,
            "baseline_ready": baseline_ready,
            "comparison_allowed": comparison_allowed,
            "next_window_id": next_window.get("id") if next_window else None,
        },
        "windows": windows,
        "runtime_endpoints": {
            "retest_scheduler_plan": "GET /v1/au-retest-scheduler-plan",
            "retest_execution_status": "GET /v1/au-retest-execution-status",
            "runtime_action_plans": "GET /v1/action-plans/runtime",
        },
        "paths": {
            "plan": str(plan_path),
            "artifact_base_dir": str(artifact_base_dir),
            "output": str(output_path or DEFAULT_OUTPUT_PATH),
        },
        "current_boundary": {
            "temporal_scheduler_implemented": False,
            "real_external_runs_completed": retest_execution_ready,
            "requires_p0a_environment_ready": True,
            "requires_design_partner_ready_baseline": True,
            "notes": [
                "This status checks whether planned retest payload and manifest artifacts exist and pass design-partner gates.",
                "Missing windows are expected before real provider credentials and scheduled collection are available.",
            ],
        },
    }
    status["retest_execution_status_hash"] = compute_retest_execution_status_hash(status)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the AU retest execution status JSON.")
    parser.add_argument(
        "--plan-path",
        default=os.environ.get("GEO_AU_RETEST_SCHEDULER_PLAN_OUTPUT_PATH", DEFAULT_RETEST_PLAN_PATH),
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GEO_AU_RETEST_EXECUTION_STATUS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
    )
    parser.add_argument(
        "--artifact-base-dir",
        default=os.environ.get("GEO_AU_RETEST_ARTIFACT_BASE_DIR", "."),
    )
    parser.add_argument("--generated-at", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    status = build_au_retest_execution_status(
        plan_path=Path(args.plan_path),
        output_path=Path(args.output_path),
        artifact_base_dir=Path(args.artifact_base_dir),
        generated_at=args.generated_at,
    )
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
