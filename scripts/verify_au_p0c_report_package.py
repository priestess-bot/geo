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

from scripts.build_au_p0c_report_package import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    PACKAGE_VERSION,
    REQUIRED_ARTIFACTS,
    compute_p0c_report_package_hash,
)


REQUIRED_FIELDS = (
    "package_version",
    "generated_at",
    "status",
    "p0c_report_contract_ready",
    "next_action",
    "remaining_blockers",
    "output_path",
    "fixture_scope",
    "report_export",
    "context",
    "summary",
    "artifacts",
    "package_payload_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def verify_au_p0c_report_package(
    package: Any,
    *,
    path: Path | None = None,
    require_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(package, dict):
        return {
            "status": "fail",
            "errors": ["package_not_json_object"],
            "hash_valid": False,
            "p0c_report_contract_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in package:
            errors.append(f"field_missing:{field}")
    if package.get("package_version") != PACKAGE_VERSION:
        errors.append("package_version_invalid")

    expected_hash = package.get("package_payload_hash")
    computed_hash = compute_p0c_report_package_hash(package)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("package_payload_hash_mismatch")

    artifacts = _as_dict(package.get("artifacts"))
    for name in REQUIRED_ARTIFACTS:
        artifact = artifacts.get(name)
        if not isinstance(artifact, dict):
            errors.append(f"artifact_missing:{name}")
            continue
        if "status" not in artifact:
            errors.append(f"artifact_status_missing:{name}")
        if "errors" not in artifact:
            errors.append(f"artifact_errors_missing:{name}")
        if str(name).endswith("_contract"):
            if "checks" not in artifact:
                errors.append(f"artifact_checks_missing:{name}")
        else:
            for field in ("filename", "media_type", "size_bytes", "content_sha256"):
                if field not in artifact:
                    errors.append(f"artifact_{field}_missing:{name}")
            if isinstance(artifact.get("content_sha256"), str) and len(str(artifact["content_sha256"])) != 64:
                errors.append(f"artifact_content_sha256_invalid:{name}")
            if int(artifact.get("size_bytes") or 0) <= 0:
                errors.append(f"artifact_size_not_positive:{name}")

    summary = _as_dict(package.get("summary"))
    expected_failed = sorted(name for name, artifact in artifacts.items() if _as_dict(artifact).get("status") == "fail")
    expected_ready = sorted(name for name, artifact in artifacts.items() if _as_dict(artifact).get("status") == "pass")
    expected_blocking = sorted(
        f"{name}:{error}" for name, artifact in artifacts.items() for error in _as_list(_as_dict(artifact).get("errors"))
    )
    summary_failed = sorted(str(item) for item in _as_list(summary.get("failed_artifacts")))
    summary_ready = sorted(str(item) for item in _as_list(summary.get("ready_artifacts")))
    summary_blocking = sorted(str(item) for item in _as_list(summary.get("blocking_reasons")))
    if summary.get("artifact_count") != len(artifacts):
        errors.append("summary_artifact_count_mismatch")
    if summary_failed != expected_failed:
        errors.append("summary_failed_artifacts_mismatch")
    if summary_ready != expected_ready:
        errors.append("summary_ready_artifacts_mismatch")
    if summary_blocking != expected_blocking:
        errors.append("summary_blocking_reasons_mismatch")

    report_export = _as_dict(package.get("report_export"))
    context = _as_dict(package.get("context"))
    if report_export.get("market_code") != "AU":
        errors.append("report_export_market_code_invalid")
    if report_export.get("report_type") != "customer_report_fixture":
        errors.append("report_export_type_invalid")
    if report_export.get("google_coverage") != "limited_coverage_appendix_only":
        errors.append("report_export_google_coverage_invalid")
    if report_export.get("api_browser_fidelity_status") != "sampled":
        errors.append("report_export_fidelity_status_invalid")
    if int(report_export.get("sample_size") or 0) != int(context.get("score_input_record_count") or -1):
        errors.append("report_export_sample_size_mismatch")
    if int(context.get("excluded_fidelity_sample_record_count") or 0) <= 0:
        errors.append("context_missing_excluded_fidelity_sample_records")
    if int(report_export.get("audit_event_count") or 0) <= 0:
        errors.append("report_export_audit_event_count_missing")

    ready = not expected_failed
    if package.get("p0c_report_contract_ready") is not ready:
        errors.append("p0c_report_contract_ready_mismatch")
    expected_status = "pass" if ready else "fail"
    if package.get("status") != expected_status:
        errors.append("package_status_mismatch")
    expected_next_action = "ready_for_p0c_customer_report_handoff" if ready else "fix_p0c_report_package"
    if package.get("next_action") != expected_next_action:
        errors.append("next_action_mismatch")
    remaining_blockers = sorted(str(item) for item in _as_list(package.get("remaining_blockers")))
    if remaining_blockers != expected_blocking:
        errors.append("remaining_blockers_mismatch")
    if require_ready and not ready:
        errors.append("p0c_report_package_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "package_version": package.get("package_version", ""),
        "package_payload_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_package_payload_hash": computed_hash,
        "hash_valid": hash_valid,
        "p0c_report_contract_ready": ready,
        "next_action": package.get("next_action", ""),
        "artifact_count": len(artifacts),
        "failed_artifacts": summary_failed,
        "remaining_blocker_count": len(remaining_blockers),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0c customer report delivery package JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0C_REPORT_PACKAGE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0c report package JSON.",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Fail unless the P0c report package is ready for customer report handoff.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        package = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {"status": "fail", "path": str(path), "errors": ["package_file_missing"], "hash_valid": False}
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"package_json_invalid:{exc.msg}"],
            "hash_valid": False,
        }
    else:
        result = verify_au_p0c_report_package(package, path=path, require_ready=args.require_ready)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
