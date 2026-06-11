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

from scripts.build_au_p0a_status_report import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    STATUS_REPORT_VERSION,
    compute_status_report_hash,
)
from scripts.verify_au_p0a_readiness import PHASES  # noqa: E402


REQUIRED_TOP_LEVEL_FIELDS = (
    "status_report_version",
    "generated_at",
    "status",
    "ready_for_design_partner",
    "next_action",
    "completion",
    "remaining_blockers",
    "inputs",
    "runbook",
    "readiness",
    "package_source",
    "package",
    "status_report_hash",
)
REQUIRED_COMPLETION_FIELDS = (
    "artifact_count",
    "ready_artifact_count",
    "design_ready_eligible_artifact_count",
    "non_failed_artifact_count",
    "missing_artifact_count",
    "failed_artifact_count",
    "completion_percent",
    "design_ready_artifact_percent",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _percent(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 2) if denominator else 0.0


def _expected_completion(package: dict[str, Any]) -> dict[str, Any]:
    artifact_count = int(package.get("artifact_count") or 0)
    ready_artifacts = set(str(item) for item in _as_list(package.get("ready_artifacts")))
    eligible = set(str(item) for item in _as_list(package.get("design_ready_eligible_artifacts")))
    failed_artifacts = set(str(item) for item in _as_list(package.get("failed_artifacts")))
    missing_artifacts = set(str(item) for item in _as_list(package.get("missing_artifacts")))
    non_failed_count = max(0, artifact_count - len(failed_artifacts))
    return {
        "artifact_count": artifact_count,
        "ready_artifact_count": len(ready_artifacts),
        "design_ready_eligible_artifact_count": len(eligible),
        "non_failed_artifact_count": non_failed_count,
        "missing_artifact_count": len(missing_artifacts),
        "failed_artifact_count": len(failed_artifacts),
        "completion_percent": _percent(non_failed_count, artifact_count),
        "design_ready_artifact_percent": _percent(len(ready_artifacts), len(eligible)),
    }


def _expected_remaining_blockers(report: dict[str, Any]) -> list[str]:
    package = _as_dict(report.get("package"))
    readiness = _as_dict(report.get("readiness"))
    blockers = [
        str(reason)
        for reason in _as_list(package.get("blocking_reasons"))
    ]
    blockers.extend(
        f"{phase}:{error}"
        for phase, phase_status in readiness.items()
        for error in _as_list(_as_dict(phase_status).get("errors"))
    )
    return sorted(set(blockers))


def _expected_next_action(report: dict[str, Any]) -> str:
    readiness = _as_dict(report.get("readiness"))
    package = _as_dict(report.get("package"))
    for phase in PHASES:
        phase_status = _as_dict(readiness.get(phase))
        if phase_status.get("status") != "pass":
            action = phase_status.get("recommended_next_action")
            return str(action) if action else f"fix_{phase}_readiness"
    if package.get("ready_for_design_partner") is not True:
        if _as_list(package.get("missing_artifacts")):
            return "run_missing_au_p0a_batches_and_manifests"
        return "fix_failed_au_p0a_artifacts"
    return "ready_for_design_partner_handoff"


def verify_au_p0a_status_report(
    report: Any,
    *,
    path: Path | None = None,
    require_design_partner_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {
            "status": "fail",
            "errors": ["status_report_not_json_object"],
            "hash_valid": False,
            "ready_for_design_partner": False,
        }

    errors: list[str] = []
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in report:
            errors.append(f"field_missing:{field}")
    if report.get("status_report_version") != STATUS_REPORT_VERSION:
        errors.append("status_report_version_invalid")

    expected_hash = report.get("status_report_hash")
    computed_hash = compute_status_report_hash(report)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("status_report_hash_mismatch")

    runbook = _as_dict(report.get("runbook"))
    if runbook.get("status") != "pass":
        errors.append("runbook_status_not_pass")
    if runbook.get("hash_valid") is not True:
        errors.append("runbook_hash_not_valid")

    readiness = _as_dict(report.get("readiness"))
    for phase in PHASES:
        phase_status = readiness.get(phase)
        if not isinstance(phase_status, dict):
            errors.append(f"readiness_phase_missing:{phase}")
            continue
        if "status" not in phase_status:
            errors.append(f"readiness_phase_status_missing:{phase}")
        if "ready_to_run_phase" not in phase_status:
            errors.append(f"readiness_phase_ready_missing:{phase}")
        if not isinstance(phase_status.get("errors", []), list):
            errors.append(f"readiness_phase_errors_invalid:{phase}")

    package = _as_dict(report.get("package"))
    if package.get("verifier_status") != "pass":
        errors.append("package_verifier_status_not_pass")
    if package.get("hash_valid") is not True:
        errors.append("package_hash_not_valid")
    if package.get("status") != (
        "pass"
        if package.get("verifier_status") == "pass" and package.get("package_manifest_status") == "pass"
        else "fail"
    ):
        errors.append("package_status_mismatch")

    completion = _as_dict(report.get("completion"))
    for field in REQUIRED_COMPLETION_FIELDS:
        if field not in completion:
            errors.append(f"completion_field_missing:{field}")
    expected_completion = _expected_completion(package)
    for field, expected_value in expected_completion.items():
        if completion.get(field) != expected_value:
            errors.append(f"completion_mismatch:{field}")

    expected_blockers = _expected_remaining_blockers(report)
    actual_blockers = sorted(str(item) for item in _as_list(report.get("remaining_blockers")))
    if actual_blockers != expected_blockers:
        errors.append("remaining_blockers_mismatch")

    expected_ready = package.get("ready_for_design_partner") is True
    if report.get("ready_for_design_partner") is not expected_ready:
        errors.append("ready_for_design_partner_mismatch")
    expected_status = "pass" if expected_ready and not expected_blockers else "fail"
    if report.get("status") != expected_status:
        errors.append("status_mismatch")
    expected_next_action = _expected_next_action(report)
    if report.get("next_action") != expected_next_action:
        errors.append("next_action_mismatch")
    if require_design_partner_ready and not expected_ready:
        errors.append("design_partner_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "status_report_version": report.get("status_report_version", ""),
        "status_report_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_status_report_hash": computed_hash,
        "hash_valid": hash_valid,
        "ready_for_design_partner": expected_ready,
        "next_action": expected_next_action,
        "remaining_blocker_count": len(actual_blockers),
        "completion": expected_completion,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0a status report JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0A_STATUS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0a status report JSON.",
    )
    parser.add_argument(
        "--require-design-partner-ready",
        action="store_true",
        help="Fail unless the status report is ready for design partner handoff.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["status_report_file_missing"],
            "hash_valid": False,
            "ready_for_design_partner": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"status_report_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "ready_for_design_partner": False,
        }
    else:
        result = verify_au_p0a_status_report(
            report,
            path=path,
            require_design_partner_ready=args.require_design_partner_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
