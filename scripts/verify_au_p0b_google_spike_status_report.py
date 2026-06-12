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

from scripts.build_au_p0b_google_spike_status_report import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    STATUS_REPORT_VERSION,
    compute_google_spike_status_hash,
)


REQUIRED_FIELDS = (
    "status_report_version",
    "generated_at",
    "status",
    "google_main_scoring_allowed",
    "limited_coverage",
    "next_action",
    "remaining_blockers",
    "inputs",
    "artifacts",
    "status_report_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def verify_au_p0b_google_spike_status_report(
    report: Any,
    *,
    path: Path | None = None,
    require_google_main_scoring_allowed: bool = False,
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
    computed_hash = compute_google_spike_status_hash(report)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("status_report_hash_mismatch")

    remaining_blockers = _as_list(report.get("remaining_blockers"))
    google_allowed = report.get("google_main_scoring_allowed") is True
    limited_coverage = report.get("limited_coverage") is True
    expected_status = "pass" if google_allowed and not remaining_blockers else "fail"
    if report.get("status") != expected_status:
        errors.append("status_mismatch")
    if google_allowed == limited_coverage:
        errors.append("google_allowed_limited_coverage_mismatch")
    if require_google_main_scoring_allowed and not google_allowed:
        errors.append("google_main_scoring_not_allowed")

    artifacts = _as_dict(report.get("artifacts"))
    for name in (
        "runbook",
        "execution",
        "playwright_env",
        "playwright_smoke",
        "manual_backfill",
        "health",
        "health_manifest",
        "spike",
        "spike_manifest",
    ):
        if name not in artifacts:
            errors.append(f"artifact_missing:{name}")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "status_report_version": report.get("status_report_version", ""),
        "status_report_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_status_report_hash": computed_hash,
        "hash_valid": hash_valid,
        "google_main_scoring_allowed": google_allowed,
        "limited_coverage": limited_coverage,
        "next_action": report.get("next_action", ""),
        "remaining_blocker_count": len(remaining_blockers),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google spike status report JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google spike status report JSON.",
    )
    parser.add_argument(
        "--require-google-main-scoring-allowed",
        action="store_true",
        help="Fail unless the status report proves Google can enter the main scoring denominator.",
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
        result = verify_au_p0b_google_spike_status_report(
            report,
            path=path,
            require_google_main_scoring_allowed=args.require_google_main_scoring_allowed,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
