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

from scripts.build_au_p0a_evidence_package import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    PACKAGE_VERSION,
    compute_package_payload_hash,
)


REQUIRED_ARTIFACTS = (
    "runbook",
    "environment",
    "runbook_execution",
    "readiness",
    "preflight_json",
    "preflight_manifest",
    "small_batch_json",
    "small_batch_manifest",
    "full_batch_json",
    "full_batch_manifest",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _expected_ready_for_design_partner(artifacts: dict[str, Any]) -> bool:
    return all(
        _as_dict(artifacts.get(name)).get("ready_for_design_partner") is True
        for name in (
            "preflight_json",
            "preflight_manifest",
            "small_batch_json",
            "small_batch_manifest",
            "full_batch_json",
            "full_batch_manifest",
        )
    )


def verify_au_p0a_evidence_package(
    package: Any,
    *,
    path: Path | None = None,
    require_design_partner_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(package, dict):
        return {
            "status": "fail",
            "errors": ["package_not_json_object"],
            "hash_valid": False,
            "ready_for_design_partner": False,
        }

    errors: list[str] = []
    if package.get("package_version") != PACKAGE_VERSION:
        errors.append("package_version_invalid")
    expected_hash = package.get("package_payload_hash")
    computed_hash = compute_package_payload_hash(package)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("package_payload_hash_mismatch")

    artifacts = _as_dict(package.get("artifacts"))
    for name in REQUIRED_ARTIFACTS:
        artifact = artifacts.get(name)
        if not isinstance(artifact, dict):
            errors.append(f"artifact_missing:{name}")
            continue
        if "exists" not in artifact:
            errors.append(f"artifact_exists_missing:{name}")
        if "status" not in artifact:
            errors.append(f"artifact_status_missing:{name}")

    summary = _as_dict(package.get("summary"))
    if not summary:
        errors.append("summary_missing_or_invalid")
    expected_missing = sorted(name for name, artifact in artifacts.items() if not _as_dict(artifact).get("exists"))
    expected_failed = sorted(name for name, artifact in artifacts.items() if _as_dict(artifact).get("status") == "fail")
    expected_ready = sorted(
        name
        for name, artifact in artifacts.items()
        if _as_dict(artifact).get("ready_for_design_partner") is True
        or _as_dict(artifact).get("ready_for_real_batch") is True
        or _as_dict(artifact).get("ready_to_run_phase") is True
        or _as_dict(artifact).get("ready_to_execute") is True
    )
    expected_blocking = sorted(
        f"{name}:{error}"
        for name, artifact in artifacts.items()
        for error in _as_list(_as_dict(artifact).get("errors"))
    )
    summary_missing = sorted(str(item) for item in _as_list(summary.get("missing_artifacts")))
    summary_failed = sorted(str(item) for item in _as_list(summary.get("failed_artifacts")))
    summary_ready = sorted(str(item) for item in _as_list(summary.get("ready_artifacts")))
    summary_blocking = sorted(str(item) for item in _as_list(summary.get("blocking_reasons")))
    if summary.get("artifact_count") != len(artifacts):
        errors.append("summary_artifact_count_mismatch")
    if summary_missing != expected_missing:
        errors.append("summary_missing_artifacts_mismatch")
    if summary_failed != expected_failed:
        errors.append("summary_failed_artifacts_mismatch")
    if summary_ready != expected_ready:
        errors.append("summary_ready_artifacts_mismatch")
    if summary_blocking != expected_blocking:
        errors.append("summary_blocking_reasons_mismatch")

    ready_for_design_partner = _expected_ready_for_design_partner(artifacts)
    if package.get("ready_for_design_partner") is not ready_for_design_partner:
        errors.append("ready_for_design_partner_mismatch")
    if package.get("status") != ("pass" if not expected_failed else "fail"):
        errors.append("package_status_mismatch")
    if require_design_partner_ready and not ready_for_design_partner:
        errors.append("design_partner_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "package_version": package.get("package_version", ""),
        "package_payload_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_package_payload_hash": computed_hash,
        "hash_valid": hash_valid,
        "ready_for_design_partner": ready_for_design_partner,
        "artifact_count": len(artifacts),
        "missing_artifacts": summary_missing,
        "failed_artifacts": summary_failed,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0a evidence package JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0A_PACKAGE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0a evidence package JSON.",
    )
    parser.add_argument(
        "--require-design-partner-ready",
        action="store_true",
        help="Fail unless all preflight/small/full JSON and manifest artifacts are design-partner ready.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        package = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["package_file_missing"],
            "hash_valid": False,
            "ready_for_design_partner": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"package_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "ready_for_design_partner": False,
        }
    else:
        result = verify_au_p0a_evidence_package(
            package,
            path=path,
            require_design_partner_ready=args.require_design_partner_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
