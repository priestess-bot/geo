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

from scripts.build_au_launch_status import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    LAUNCH_STATUS_VERSION,
    compute_launch_status_hash,
)


REQUIRED_FIELDS = (
    "launch_status_version",
    "generated_at",
    "status",
    "ready_for_customer_report_handoff",
    "next_action",
    "remaining_blockers",
    "inputs",
    "sources",
    "p0a_design_partner",
    "p0b_google",
    "p0c_customer_report",
    "launch_status_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _expected_next_action(report: dict[str, Any]) -> str:
    p0a = _as_dict(report.get("p0a_design_partner"))
    p0b = _as_dict(report.get("p0b_google"))
    p0c = _as_dict(report.get("p0c_customer_report"))
    if p0a.get("ready_for_design_partner") is not True:
        return str(p0a.get("next_action") or "complete_au_p0a_real_batches")
    if p0b.get("google_main_scoring_allowed") is not True:
        return str(p0b.get("next_action") or "complete_au_p0b_google_spike")
    if p0c.get("status") != "pass":
        return "fix_p0c_report_contract"
    return "ready_for_customer_report_handoff"


def _expected_blockers(report: dict[str, Any]) -> list[str]:
    p0a = _as_dict(report.get("p0a_design_partner"))
    p0b = _as_dict(report.get("p0b_google"))
    p0c = _as_dict(report.get("p0c_customer_report"))
    return sorted(
        set(
            [f"p0a:{item}" for item in _as_list(p0a.get("remaining_blockers"))]
            + [f"p0b_google:{item}" for item in _as_list(p0b.get("remaining_blockers"))]
            + [f"p0c:{item}" for item in _as_list(p0c.get("errors"))]
        )
    )


def verify_au_launch_status(
    report: Any,
    *,
    path: Path | None = None,
    require_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {
            "status": "fail",
            "errors": ["launch_status_not_json_object"],
            "hash_valid": False,
            "ready_for_customer_report_handoff": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in report:
            errors.append(f"field_missing:{field}")
    if report.get("launch_status_version") != LAUNCH_STATUS_VERSION:
        errors.append("launch_status_version_invalid")

    expected_hash = report.get("launch_status_hash")
    computed_hash = compute_launch_status_hash(report)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("launch_status_hash_mismatch")

    p0a = _as_dict(report.get("p0a_design_partner"))
    p0b = _as_dict(report.get("p0b_google"))
    p0c = _as_dict(report.get("p0c_customer_report"))
    if p0a.get("verifier_status") != "pass":
        errors.append("p0a_status_verifier_not_pass")
    if p0a.get("hash_valid") is not True:
        errors.append("p0a_status_hash_not_valid")
    if p0b.get("status_verifier_status") != "pass":
        errors.append("p0b_status_verifier_not_pass")
    if p0b.get("package_verifier_status") != "pass":
        errors.append("p0b_package_verifier_not_pass")
    if p0b.get("status_hash_valid") is not True:
        errors.append("p0b_status_hash_not_valid")
    if p0b.get("package_hash_valid") is not True:
        errors.append("p0b_package_hash_not_valid")
    if p0c.get("status") != "pass":
        errors.append("p0c_report_contract_not_pass")
    checks = _as_dict(p0c.get("checks"))
    for name in (
        "method_disclosure_fields_present",
        "score_rate_definitions_present",
        "audit_summary_count_present",
        "methodology_render_mentions_denominator",
        "audit_summary_render_mentions_events",
    ):
        if checks.get(name) is not True:
            errors.append(f"p0c_check_not_pass:{name}")

    expected_ready = (
        p0a.get("ready_for_design_partner") is True
        and p0b.get("google_main_scoring_allowed") is True
        and p0c.get("status") == "pass"
    )
    if report.get("ready_for_customer_report_handoff") is not expected_ready:
        errors.append("ready_for_customer_report_handoff_mismatch")
    expected_status = "pass" if expected_ready else "fail"
    if report.get("status") != expected_status:
        errors.append("status_mismatch")
    expected_next_action = _expected_next_action(report)
    if report.get("next_action") != expected_next_action:
        errors.append("next_action_mismatch")
    expected_blockers = _expected_blockers(report)
    actual_blockers = sorted(str(item) for item in _as_list(report.get("remaining_blockers")))
    if actual_blockers != expected_blockers:
        errors.append("remaining_blockers_mismatch")
    if require_ready and not expected_ready:
        errors.append("launch_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "launch_status_version": report.get("launch_status_version", ""),
        "launch_status_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_launch_status_hash": computed_hash,
        "hash_valid": hash_valid,
        "ready_for_customer_report_handoff": expected_ready,
        "next_action": expected_next_action,
        "remaining_blocker_count": len(actual_blockers),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU launch status JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_LAUNCH_STATUS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU launch status JSON.",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Fail unless the launch status is ready for customer report handoff.",
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
            "errors": ["launch_status_file_missing"],
            "hash_valid": False,
            "ready_for_customer_report_handoff": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"launch_status_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "ready_for_customer_report_handoff": False,
        }
    else:
        result = verify_au_launch_status(report, path=path, require_ready=args.require_ready)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
