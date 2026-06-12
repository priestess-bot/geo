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

from scripts.build_au_p0b_google_evidence_package import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    PACKAGE_VERSION,
    REQUIRED_ARTIFACTS,
    compute_google_evidence_package_hash,
)


REQUIRED_FIELDS = (
    "package_version",
    "generated_at",
    "status",
    "google_main_scoring_allowed",
    "limited_coverage",
    "next_action",
    "remaining_blockers",
    "runbook_path",
    "execution_path",
    "status_report_path",
    "output_path",
    "summary",
    "artifacts",
    "package_payload_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _expected_ready_artifacts(artifacts: dict[str, Any]) -> list[str]:
    ready: list[str] = []
    for name, artifact_value in artifacts.items():
        artifact = _as_dict(artifact_value)
        if (
            artifact.get("google_main_scoring_allowed") is True
            or artifact.get("ready_to_execute") is True
            or artifact.get("ready_for_playwright_smoke") is True
            or artifact.get("ready_for_full_google_run") is True
            or artifact.get("smoke_success") is True
            or artifact.get("manual_backfill_ready") is True
            or artifact.get("collector_health_ready") is True
            or artifact.get("google_gates_ready") is True
        ):
            ready.append(str(name))
    return sorted(ready)


def verify_au_p0b_google_evidence_package(
    package: Any,
    *,
    path: Path | None = None,
    require_google_main_scoring_allowed: bool = False,
) -> dict[str, Any]:
    if not isinstance(package, dict):
        return {
            "status": "fail",
            "errors": ["package_not_json_object"],
            "hash_valid": False,
            "google_main_scoring_allowed": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in package:
            errors.append(f"field_missing:{field}")
    if package.get("package_version") != PACKAGE_VERSION:
        errors.append("package_version_invalid")

    expected_hash = package.get("package_payload_hash")
    computed_hash = compute_google_evidence_package_hash(package)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("package_payload_hash_mismatch")

    artifacts = _as_dict(package.get("artifacts"))
    for name in REQUIRED_ARTIFACTS:
        artifact = artifacts.get(name)
        if not isinstance(artifact, dict):
            errors.append(f"artifact_missing:{name}")
            continue
        if "path" not in artifact:
            errors.append(f"artifact_path_missing:{name}")
        if "exists" not in artifact:
            errors.append(f"artifact_exists_missing:{name}")
        if "status" not in artifact:
            errors.append(f"artifact_status_missing:{name}")
        if "errors" not in artifact:
            errors.append(f"artifact_errors_missing:{name}")

    summary = _as_dict(package.get("summary"))
    if not summary:
        errors.append("summary_missing_or_invalid")
    expected_missing = sorted(
        str(name) for name, artifact in artifacts.items() if _as_dict(artifact).get("exists") is not True
    )
    expected_failed = sorted(
        str(name) for name, artifact in artifacts.items() if _as_dict(artifact).get("status") == "fail"
    )
    expected_blocking = sorted(
        f"{name}:{error}"
        for name, artifact in artifacts.items()
        for error in _as_list(_as_dict(artifact).get("errors"))
    )
    expected_ready = _expected_ready_artifacts(artifacts)
    summary_missing = sorted(str(item) for item in _as_list(summary.get("missing_artifacts")))
    summary_failed = sorted(str(item) for item in _as_list(summary.get("failed_artifacts")))
    summary_blocking = sorted(str(item) for item in _as_list(summary.get("blocking_reasons")))
    summary_ready = sorted(str(item) for item in _as_list(summary.get("ready_artifacts")))
    if summary.get("artifact_count") != len(artifacts):
        errors.append("summary_artifact_count_mismatch")
    if summary_missing != expected_missing:
        errors.append("summary_missing_artifacts_mismatch")
    if summary_failed != expected_failed:
        errors.append("summary_failed_artifacts_mismatch")
    if summary_blocking != expected_blocking:
        errors.append("summary_blocking_reasons_mismatch")
    if summary_ready != expected_ready:
        errors.append("summary_ready_artifacts_mismatch")

    status_artifact = _as_dict(artifacts.get("status_report"))
    expected_google_allowed = (
        status_artifact.get("google_main_scoring_allowed") is True and not expected_failed
    )
    if package.get("google_main_scoring_allowed") is not expected_google_allowed:
        errors.append("google_main_scoring_allowed_mismatch")
    if package.get("limited_coverage") is not (not expected_google_allowed):
        errors.append("limited_coverage_mismatch")
    if package.get("status") != ("pass" if not expected_failed else "fail"):
        errors.append("package_status_mismatch")

    status_remaining = [str(item) for item in _as_list(status_artifact.get("remaining_blockers"))]
    if status_artifact.get("exists") is True:
        expected_remaining = sorted(status_remaining)
    else:
        expected_remaining = ["status_report:status_report_file_missing"]
    package_remaining = sorted(str(item) for item in _as_list(package.get("remaining_blockers")))
    if package_remaining != expected_remaining:
        errors.append("remaining_blockers_mismatch")
    expected_next_action = str(status_artifact.get("next_action") or "run_au_p0b_google_status")
    if package.get("next_action") != expected_next_action:
        errors.append("next_action_mismatch")
    if require_google_main_scoring_allowed and not expected_google_allowed:
        errors.append("google_main_scoring_not_allowed")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "package_version": package.get("package_version", ""),
        "package_payload_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_package_payload_hash": computed_hash,
        "hash_valid": hash_valid,
        "google_main_scoring_allowed": expected_google_allowed,
        "limited_coverage": package.get("limited_coverage") is True,
        "next_action": package.get("next_action", ""),
        "artifact_count": len(artifacts),
        "missing_artifacts": summary_missing,
        "failed_artifacts": summary_failed,
        "remaining_blocker_count": len(package_remaining),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google evidence package JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google evidence package JSON.",
    )
    parser.add_argument(
        "--require-google-main-scoring-allowed",
        action="store_true",
        help="Fail unless the package proves Google can enter the main scoring denominator.",
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
        result = verify_au_p0b_google_evidence_package(
            package,
            path=path,
            require_google_main_scoring_allowed=args.require_google_main_scoring_allowed,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
