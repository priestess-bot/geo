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

from scripts.build_au_p0b_google_serp_status_report import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    STATUS_REPORT_VERSION,
    compute_google_serp_status_hash,
)


REQUIRED_FIELDS = (
    "status_report_version",
    "generated_at",
    "status",
    "comparison_evidence_ready",
    "supplier_health_ready",
    "google_main_scoring_allowed",
    "limited_coverage",
    "main_google_spike_required",
    "score_input_policy",
    "next_action",
    "remaining_blockers",
    "inputs",
    "artifacts",
    "status_report_hash",
)
REQUIRED_ARTIFACTS = (
    "fixture",
    "fixture_manifest",
    "health",
    "health_manifest",
    "comparison",
    "comparison_manifest",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def verify_au_p0b_google_serp_status_report(
    report: Any,
    *,
    path: Path | None = None,
    require_comparison_evidence_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {"status": "fail", "errors": ["status_report_not_json_object"], "hash_valid": False}

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in report:
            errors.append(f"field_missing:{field}")
    if report.get("status_report_version") != STATUS_REPORT_VERSION:
        errors.append("status_report_version_invalid")

    expected_hash = report.get("status_report_hash")
    computed_hash = compute_google_serp_status_hash(report)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("status_report_hash_mismatch")

    remaining_blockers = _as_list(report.get("remaining_blockers"))
    comparison_ready = report.get("comparison_evidence_ready") is True
    expected_status = "pass" if comparison_ready and not remaining_blockers else "fail"
    if report.get("status") != expected_status:
        errors.append("status_mismatch")
    if require_comparison_evidence_ready and not comparison_ready:
        errors.append("comparison_evidence_not_ready")
    if report.get("google_main_scoring_allowed") is not False:
        errors.append("google_main_scoring_must_remain_false")
    if report.get("limited_coverage") is not True:
        errors.append("limited_coverage_must_remain_true")
    if report.get("main_google_spike_required") is not True:
        errors.append("main_google_spike_required_missing")

    artifacts = _as_dict(report.get("artifacts"))
    for artifact in REQUIRED_ARTIFACTS:
        if artifact not in artifacts:
            errors.append(f"artifact_missing:{artifact}")
    if artifacts:
        supplier_health_ready = _as_dict(artifacts.get("health")).get("collector_health_ready") is True
        if report.get("supplier_health_ready") is not supplier_health_ready:
            errors.append("supplier_health_ready_mismatch")
        full_ready = (
            _as_dict(artifacts.get("fixture")).get("status") == "pass"
            and _as_dict(artifacts.get("fixture_manifest")).get("status") == "pass"
            and _as_dict(artifacts.get("health")).get("status") == "pass"
            and _as_dict(artifacts.get("health_manifest")).get("status") == "pass"
            and _as_dict(artifacts.get("comparison")).get("status") == "pass"
            and _as_dict(artifacts.get("comparison_manifest")).get("status") == "pass"
        )
        if comparison_ready is not full_ready:
            errors.append("comparison_evidence_ready_mismatch")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "status_report_version": report.get("status_report_version", ""),
        "status_report_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_status_report_hash": computed_hash,
        "hash_valid": hash_valid,
        "comparison_evidence_ready": comparison_ready,
        "supplier_health_ready": report.get("supplier_health_ready") is True,
        "google_main_scoring_allowed": report.get("google_main_scoring_allowed") is True,
        "limited_coverage": report.get("limited_coverage") is True,
        "next_action": report.get("next_action", ""),
        "remaining_blocker_count": len(remaining_blockers),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google SERP comparison status report JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_SERP_STATUS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google SERP comparison status report JSON.",
    )
    parser.add_argument(
        "--require-comparison-evidence-ready",
        action="store_true",
        help="Fail unless all SERP comparison artifacts prove ready for P0b review.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {"status": "fail", "path": str(path), "errors": ["status_report_file_missing"], "hash_valid": False}
    except json.JSONDecodeError as exc:
        result = {"status": "fail", "path": str(path), "errors": [f"status_report_json_invalid:{exc.msg}"], "hash_valid": False}
    else:
        result = verify_au_p0b_google_serp_status_report(
            report,
            path=path,
            require_comparison_evidence_ready=args.require_comparison_evidence_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
