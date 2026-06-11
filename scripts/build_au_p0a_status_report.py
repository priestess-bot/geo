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

from scripts.build_au_p0a_evidence_package import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_PACKAGE_PATH,
    build_au_p0a_evidence_package,
)
from scripts.build_au_p0a_env_report import DEFAULT_OUTPUT_PATH as DEFAULT_ENV_REPORT_PATH  # noqa: E402
from scripts.build_au_p0a_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_PATH  # noqa: E402
from scripts.run_au_p0a_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_EXECUTION_PATH  # noqa: E402
from scripts.verify_au_p0a_evidence_package import verify_au_p0a_evidence_package  # noqa: E402
from scripts.verify_au_p0a_readiness import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_READINESS_PATH,
    PHASES,
    verify_au_p0a_readiness,
)
from scripts.verify_au_p0a_runbook import verify_au_p0a_runbook  # noqa: E402


STATUS_REPORT_VERSION = "au_p0a_status_report_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-status-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_status_bytes(report: dict[str, Any]) -> bytes:
    return json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def compute_status_report_hash(report: dict[str, Any]) -> str:
    payload_for_hash = dict(report)
    payload_for_hash.pop("status_report_hash", None)
    return hashlib.sha256(_stable_status_bytes(payload_for_hash)).hexdigest()


def _load_json(path: Path) -> tuple[Any | None, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, {"path": str(path), "exists": False, "status": "fail", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        return None, {"path": str(path), "exists": True, "status": "fail", "errors": [f"json_invalid:{exc.msg}"]}
    return payload, {"path": str(path), "exists": True}


def _load_or_build_package(
    *,
    package_path: Path,
    runbook_path: Path,
    environment_path: Path,
    readiness_path: Path,
    runbook_execution_path: Path,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    package, file_entry = _load_json(package_path)
    if isinstance(package, dict):
        file_entry["source"] = "existing_file"
        return package, file_entry

    built = build_au_p0a_evidence_package(
        runbook_path=runbook_path,
        environment_path=environment_path,
        readiness_path=readiness_path,
        runbook_execution_path=runbook_execution_path,
        output_path=package_path,
        generated_at=generated_at,
    )
    return built, {
        "path": str(package_path),
        "exists": False,
        "status": "generated_in_memory",
        "source": "generated_in_memory",
        "errors": file_entry.get("errors", []),
    }


def _runbook_status(runbook_path: Path) -> dict[str, Any]:
    runbook, file_entry = _load_json(runbook_path)
    if not isinstance(runbook, dict):
        return {
            "path": str(runbook_path),
            "exists": file_entry["exists"],
            "status": "fail",
            "errors": file_entry["errors"],
            "hash_valid": False,
        }
    verification = verify_au_p0a_runbook(runbook, path=runbook_path)
    return {
        "path": str(runbook_path),
        "exists": True,
        "status": verification["status"],
        "errors": verification["errors"],
        "hash_valid": verification["hash_valid"],
        "small_batch_planned_runs": verification.get("small_batch_planned_runs"),
        "full_batch_planned_runs": verification.get("full_batch_planned_runs"),
        "step_count": verification.get("step_count"),
    }


def _readiness_statuses(
    *,
    runbook_path: Path,
    env: dict[str, str] | None,
    require_db_check: bool,
    generated_at: str | None,
) -> dict[str, Any]:
    statuses: dict[str, Any] = {}
    for phase in PHASES:
        readiness = verify_au_p0a_readiness(
            phase=phase,
            runbook_path=runbook_path,
            env=env,
            require_db_check=require_db_check,
            generated_at=generated_at,
        )
        statuses[phase] = {
            "status": readiness["status"],
            "ready_to_run_phase": readiness["ready_to_run_phase"],
            "errors": readiness["errors"],
            "warnings": readiness["warnings"],
            "recommended_next_action": readiness["recommended_next_action"],
            "environment": readiness["environment"],
            "database": readiness["database"],
            "gate_count": len(readiness["gates"]),
        }
    return statuses


def _package_status(package: dict[str, Any], package_path: Path, *, require_design_partner_ready: bool) -> dict[str, Any]:
    verification = verify_au_p0a_evidence_package(
        package,
        path=package_path,
        require_design_partner_ready=require_design_partner_ready,
    )
    summary = package.get("summary") if isinstance(package.get("summary"), dict) else {}
    artifacts = package.get("artifacts") if isinstance(package.get("artifacts"), dict) else {}
    design_ready_eligible_artifacts = [
        name
        for name, artifact in artifacts.items()
        if isinstance(artifact, dict)
        and (
            "ready_for_design_partner" in artifact
            or "ready_for_real_batch" in artifact
            or "ready_to_run_phase" in artifact
            or "ready_to_execute" in artifact
        )
    ]
    package_manifest_status = package.get("status") if isinstance(package.get("status"), str) else "fail"
    return {
        "path": str(package_path),
        "status": "pass" if verification["status"] == "pass" and package_manifest_status == "pass" else "fail",
        "package_manifest_status": package_manifest_status,
        "verifier_status": verification["status"],
        "verifier_errors": verification["errors"],
        "errors": verification["errors"],
        "hash_valid": verification["hash_valid"],
        "ready_for_design_partner": verification["ready_for_design_partner"],
        "artifact_count": verification["artifact_count"],
        "missing_artifacts": verification["missing_artifacts"],
        "failed_artifacts": verification["failed_artifacts"],
        "ready_artifacts": list(summary.get("ready_artifacts", [])),
        "design_ready_eligible_artifacts": design_ready_eligible_artifacts,
        "blocking_reasons": list(summary.get("blocking_reasons", [])),
    }


def _completion(package_status: dict[str, Any]) -> dict[str, Any]:
    artifact_count = int(package_status.get("artifact_count") or 0)
    missing = len(package_status.get("missing_artifacts") or [])
    failed = len(package_status.get("failed_artifacts") or [])
    ready_count = len(set(package_status.get("ready_artifacts") or []))
    eligible_count = len(set(package_status.get("design_ready_eligible_artifacts") or []))
    non_failed_count = max(0, artifact_count - len(set(package_status.get("failed_artifacts") or [])))
    completion_percent = round((non_failed_count / artifact_count) * 100, 2) if artifact_count else 0.0
    design_ready_percent = round((ready_count / eligible_count) * 100, 2) if eligible_count else 0.0
    return {
        "artifact_count": artifact_count,
        "ready_artifact_count": ready_count,
        "design_ready_eligible_artifact_count": eligible_count,
        "non_failed_artifact_count": non_failed_count,
        "missing_artifact_count": missing,
        "failed_artifact_count": failed,
        "completion_percent": completion_percent,
        "design_ready_artifact_percent": design_ready_percent,
    }


def _next_action(readiness_statuses: dict[str, Any], package_status: dict[str, Any]) -> str:
    for phase in PHASES:
        phase_status = readiness_statuses.get(phase, {})
        if phase_status.get("status") != "pass":
            action = phase_status.get("recommended_next_action")
            return str(action) if action else f"fix_{phase}_readiness"
    if package_status.get("ready_for_design_partner") is not True:
        if package_status.get("missing_artifacts"):
            return "run_missing_au_p0a_batches_and_manifests"
        return "fix_failed_au_p0a_artifacts"
    return "ready_for_design_partner_handoff"


def build_au_p0a_status_report(
    *,
    runbook_path: Path = Path(DEFAULT_RUNBOOK_PATH),
    environment_path: Path = Path(DEFAULT_ENV_REPORT_PATH),
    readiness_path: Path = Path(DEFAULT_READINESS_PATH),
    runbook_execution_path: Path = Path(DEFAULT_RUNBOOK_EXECUTION_PATH),
    package_path: Path = Path(DEFAULT_PACKAGE_PATH),
    output_path: Path | None = None,
    env: dict[str, str] | None = None,
    require_db_check: bool = False,
    require_design_partner_ready: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    package, package_source = _load_or_build_package(
        package_path=package_path,
        runbook_path=runbook_path,
        environment_path=environment_path,
        readiness_path=readiness_path,
        runbook_execution_path=runbook_execution_path,
        generated_at=generated_at,
    )
    runbook = _runbook_status(runbook_path)
    readiness = _readiness_statuses(
        runbook_path=runbook_path,
        env=env,
        require_db_check=require_db_check,
        generated_at=generated_at,
    )
    package_result = _package_status(
        package,
        package_path,
        require_design_partner_ready=require_design_partner_ready,
    )
    completion = _completion(package_result)
    remaining_blockers = sorted(
        set(
            str(reason)
            for reason in package_result["blocking_reasons"]
            + [
                f"{phase}:{error}"
                for phase, phase_status in readiness.items()
                for error in phase_status.get("errors", [])
            ]
        )
    )
    report: dict[str, Any] = {
        "status_report_version": STATUS_REPORT_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if package_result["ready_for_design_partner"] and not remaining_blockers else "fail",
        "ready_for_design_partner": package_result["ready_for_design_partner"],
        "next_action": _next_action(readiness, package_result),
        "completion": completion,
        "remaining_blockers": remaining_blockers,
        "inputs": {
            "runbook_path": str(runbook_path),
            "environment_path": str(environment_path),
            "readiness_path": str(readiness_path),
            "runbook_execution_path": str(runbook_execution_path),
            "package_path": str(package_path),
            "output_path": str(output_path) if output_path else "",
            "require_db_check": require_db_check,
            "require_design_partner_ready": require_design_partner_ready,
        },
        "runbook": runbook,
        "readiness": readiness,
        "package_source": package_source,
        "package": package_result,
    }
    report["status_report_hash"] = compute_status_report_hash(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0a status report across local gates")
    parser.add_argument(
        "--runbook-path",
        default=os.environ.get("GENO_AU_P0A_RUNBOOK_OUTPUT_PATH", DEFAULT_RUNBOOK_PATH),
        help="Path to the generated AU P0a runbook JSON.",
    )
    parser.add_argument(
        "--readiness-path",
        default=os.environ.get("GENO_AU_P0A_READINESS_OUTPUT_PATH", DEFAULT_READINESS_PATH),
        help="Path to the latest AU P0a readiness JSON.",
    )
    parser.add_argument(
        "--environment-path",
        default=os.environ.get("GENO_AU_P0A_ENV_OUTPUT_PATH", DEFAULT_ENV_REPORT_PATH),
        help="Path to the latest AU P0a environment report JSON.",
    )
    parser.add_argument(
        "--runbook-execution-path",
        default=os.environ.get("GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH", DEFAULT_RUNBOOK_EXECUTION_PATH),
        help="Path to the latest AU P0a runbook execution dry-run JSON.",
    )
    parser.add_argument(
        "--package-path",
        default=os.environ.get("GENO_AU_P0A_PACKAGE_OUTPUT_PATH", DEFAULT_PACKAGE_PATH),
        help="Path to the latest AU P0a evidence package JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_STATUS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the status report JSON.",
    )
    parser.add_argument(
        "--require-db-check",
        action="store_true",
        help="Require SELECT 1 DATABASE_URL readiness in all phase checks.",
    )
    parser.add_argument(
        "--require-design-partner-ready",
        action="store_true",
        help="Exit non-zero unless the full evidence package is ready for design partner handoff.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    report = build_au_p0a_status_report(
        runbook_path=Path(args.runbook_path),
        environment_path=Path(args.environment_path),
        readiness_path=Path(args.readiness_path),
        runbook_execution_path=Path(args.runbook_execution_path),
        package_path=Path(args.package_path),
        output_path=output_path,
        require_db_check=args.require_db_check,
        require_design_partner_ready=args.require_design_partner_ready,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if args.require_design_partner_ready and report["ready_for_design_partner"] is not True:
        raise SystemExit(2)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
