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

from scripts.build_preflight_manifest import MANIFEST_VERSION, compute_manifest_payload_hash  # noqa: E402
from scripts.verify_au_p0b_google_serp_comparison import (  # noqa: E402
    EXPECTED_SCORE_INPUT_POLICY,
    verify_au_p0b_google_serp_comparison,
)


STATUS_REPORT_VERSION = "au_p0b_google_serp_status_report_v1"
DEFAULT_FIXTURE_PATH = "docs/runtime_preflight/au-p0b-google-serp-fixture-latest.json"
DEFAULT_FIXTURE_MANIFEST_PATH = "docs/runtime_preflight/au-p0b-google-serp-fixture-manifest-latest.json"
DEFAULT_HEALTH_PATH = "docs/runtime_preflight/au-p0b-google-serp-health-latest.json"
DEFAULT_HEALTH_MANIFEST_PATH = "docs/runtime_preflight/au-p0b-google-serp-health-manifest-latest.json"
DEFAULT_COMPARISON_PATH = "docs/runtime_preflight/au-p0b-google-serp-latest.json"
DEFAULT_COMPARISON_MANIFEST_PATH = "docs/runtime_preflight/au-p0b-google-serp-manifest-latest.json"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-serp-status-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_status_bytes(report: dict[str, Any]) -> bytes:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_google_serp_status_hash(report: dict[str, Any]) -> str:
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


def _comparison_payload_status(
    path: Path,
    *,
    require_comparison_ready: bool,
    require_collector_health_ready: bool,
) -> dict[str, Any]:
    payload, file_entry = _load_json(path)
    if not isinstance(payload, dict):
        return {
            "path": str(path),
            "exists": file_entry["exists"],
            "status": "fail",
            "errors": file_entry["errors"],
            "hash_valid": False,
            "collector_health_ready": False,
            "comparison_ready": False,
        }
    verification = verify_au_p0b_google_serp_comparison(
        payload,
        path=path,
        require_comparison_ready=require_comparison_ready,
        require_collector_health_ready=require_collector_health_ready,
    )
    return {
        "path": str(path),
        "exists": True,
        "status": verification["status"],
        "errors": verification["errors"],
        "hash_valid": verification["hash_valid"],
        "mode": verification["mode"],
        "phase": verification["phase"],
        "exit_code": verification["exit_code"],
        "planned_runs": verification["planned_runs"],
        "record_count": verification["record_count"],
        "success_count": verification["success_count"],
        "failure_count": verification["failure_count"],
        "collector_health_ready": verification["collector_health_ready"],
        "collector_health_failure_reasons": verification["collector_health_failure_reasons"],
        "comparison_plan_valid": verification["comparison_plan_valid"],
        "comparison_ready": verification["comparison_ready"],
        "full_spike_gates_absent": verification["full_spike_gates_absent"],
        "main_google_spike_planned_runs": verification["main_google_spike_planned_runs"],
        "persistence_run_type": verification["persistence_run_type"],
        "persist_analysis_enabled": verification["persist_analysis_enabled"],
    }


def _manifest_status(path: Path, *, expected_preflight_path: Path) -> dict[str, Any]:
    payload, file_entry = _load_json(path)
    if not isinstance(payload, dict):
        return {"path": str(path), "exists": file_entry["exists"], "status": "fail", "errors": file_entry["errors"], "hash_valid": False}

    errors: list[str] = []
    if payload.get("manifest_version") != MANIFEST_VERSION:
        errors.append("manifest_version_invalid")
    expected_hash = payload.get("manifest_payload_hash")
    computed_hash = compute_manifest_payload_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("manifest_payload_hash_mismatch")
    preflight_payload = payload.get("preflight_payload") if isinstance(payload.get("preflight_payload"), dict) else {}
    manifest_preflight_path = str(preflight_payload.get("path") or "")
    if not manifest_preflight_path:
        errors.append("manifest_preflight_path_missing")
    elif Path(manifest_preflight_path).resolve() != expected_preflight_path.resolve():
        errors.append("manifest_preflight_path_mismatch")
    verifier = payload.get("verifier") if isinstance(payload.get("verifier"), dict) else {}
    if verifier.get("status") != "pass":
        errors.append("manifest_verifier_not_pass")

    return {
        "path": str(path),
        "exists": True,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "hash_valid": hash_valid,
        "manifest_version": payload.get("manifest_version", ""),
        "verifier_status": verifier.get("status", ""),
        "preflight_payload_path": manifest_preflight_path,
    }


def _next_action(items: dict[str, dict[str, Any]]) -> str:
    if items["fixture"].get("status") != "pass":
        return "run_google_serp_fixture"
    if items["fixture_manifest"].get("status") != "pass":
        return "build_google_serp_fixture_manifest"
    if items["health"].get("status") != "pass":
        if items["health"].get("exists") and items["health"].get("collector_health_ready") is not True:
            return "configure_google_serp_supplier"
        return "run_google_serp_health_check"
    if items["health_manifest"].get("status") != "pass":
        return "build_google_serp_health_manifest"
    if items["comparison"].get("status") != "pass":
        if items["comparison"].get("exists"):
            return "fix_google_serp_comparison_failures"
        return "run_real_google_serp_comparison"
    if items["comparison_manifest"].get("status") != "pass":
        return "build_google_serp_comparison_manifest"
    return "handoff_google_serp_evidence_to_p0b_review"


def build_au_p0b_google_serp_status_report(
    *,
    fixture_path: Path = Path(DEFAULT_FIXTURE_PATH),
    fixture_manifest_path: Path = Path(DEFAULT_FIXTURE_MANIFEST_PATH),
    health_path: Path = Path(DEFAULT_HEALTH_PATH),
    health_manifest_path: Path = Path(DEFAULT_HEALTH_MANIFEST_PATH),
    comparison_path: Path = Path(DEFAULT_COMPARISON_PATH),
    comparison_manifest_path: Path = Path(DEFAULT_COMPARISON_MANIFEST_PATH),
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    items = {
        "fixture": _comparison_payload_status(
            fixture_path,
            require_comparison_ready=True,
            require_collector_health_ready=True,
        ),
        "fixture_manifest": _manifest_status(fixture_manifest_path, expected_preflight_path=fixture_path),
        "health": _comparison_payload_status(
            health_path,
            require_comparison_ready=False,
            require_collector_health_ready=True,
        ),
        "health_manifest": _manifest_status(health_manifest_path, expected_preflight_path=health_path),
        "comparison": _comparison_payload_status(
            comparison_path,
            require_comparison_ready=True,
            require_collector_health_ready=True,
        ),
        "comparison_manifest": _manifest_status(comparison_manifest_path, expected_preflight_path=comparison_path),
    }
    remaining_blockers = sorted(
        {
            f"{name}:{error}"
            for name, item in items.items()
            if item.get("status") != "pass"
            for error in (item.get("errors") or ["status_not_pass"])
        }
    )
    comparison_evidence_ready = (
        not remaining_blockers
        and items["fixture"].get("comparison_ready") is True
        and items["health"].get("collector_health_ready") is True
        and items["comparison"].get("comparison_ready") is True
    )
    report: dict[str, Any] = {
        "status_report_version": STATUS_REPORT_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if comparison_evidence_ready else "fail",
        "comparison_evidence_ready": comparison_evidence_ready,
        "supplier_health_ready": items["health"].get("collector_health_ready") is True,
        "google_main_scoring_allowed": False,
        "limited_coverage": True,
        "main_google_spike_required": True,
        "score_input_policy": EXPECTED_SCORE_INPUT_POLICY,
        "next_action": _next_action(items),
        "remaining_blockers": remaining_blockers,
        "inputs": {
            "fixture_path": str(fixture_path),
            "fixture_manifest_path": str(fixture_manifest_path),
            "health_path": str(health_path),
            "health_manifest_path": str(health_manifest_path),
            "comparison_path": str(comparison_path),
            "comparison_manifest_path": str(comparison_manifest_path),
            "output_path": str(output_path) if output_path else "",
        },
        "artifacts": items,
    }
    report["status_report_hash"] = compute_google_serp_status_hash(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google SERP comparison status report")
    parser.add_argument(
        "--fixture-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_SERP_FIXTURE_OUTPUT_PATH", DEFAULT_FIXTURE_PATH),
    )
    parser.add_argument(
        "--fixture-manifest-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_SERP_FIXTURE_MANIFEST_PATH", DEFAULT_FIXTURE_MANIFEST_PATH),
    )
    parser.add_argument(
        "--health-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_SERP_HEALTH_OUTPUT_PATH", DEFAULT_HEALTH_PATH),
    )
    parser.add_argument(
        "--health-manifest-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_SERP_HEALTH_MANIFEST_PATH", DEFAULT_HEALTH_MANIFEST_PATH),
    )
    parser.add_argument(
        "--comparison-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_SERP_OUTPUT_PATH", DEFAULT_COMPARISON_PATH),
    )
    parser.add_argument(
        "--comparison-manifest-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_SERP_MANIFEST_PATH", DEFAULT_COMPARISON_MANIFEST_PATH),
    )
    parser.add_argument("--output-path", default=os.environ.get("GEO_AU_P0B_GOOGLE_SERP_STATUS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH))
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    report = build_au_p0b_google_serp_status_report(
        fixture_path=Path(args.fixture_path),
        fixture_manifest_path=Path(args.fixture_manifest_path),
        health_path=Path(args.health_path),
        health_manifest_path=Path(args.health_manifest_path),
        comparison_path=Path(args.comparison_path),
        comparison_manifest_path=Path(args.comparison_manifest_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
