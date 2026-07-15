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

from scripts.build_au_p0a_status_report import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_STATUS_PATH,
    build_au_p0a_status_report,
)
from scripts.build_au_p0b_google_evidence_package import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_PACKAGE_PATH,
    build_au_p0b_google_evidence_package,
)
from scripts.build_au_p0b_google_spike_runbook import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_RUNBOOK_PATH,
)
from scripts.build_au_p0b_google_spike_status_report import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_STATUS_PATH,
)
from scripts.build_au_p0c_report_package import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0C_REPORT_PACKAGE_PATH,
    build_au_p0c_report_package,
)
from scripts.run_au_p0b_google_spike_runbook import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_EXECUTION_PATH,
)
from scripts.verify_au_p0a_status_report import verify_au_p0a_status_report  # noqa: E402
from scripts.verify_au_p0b_google_evidence_package import (  # noqa: E402
    verify_au_p0b_google_evidence_package,
)
from scripts.verify_au_p0b_google_spike_status_report import (  # noqa: E402
    verify_au_p0b_google_spike_status_report,
)
from scripts.verify_au_p0c_report_package import verify_au_p0c_report_package  # noqa: E402


LAUNCH_STATUS_VERSION = "au_launch_status_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-launch-status-latest.json"


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


def compute_launch_status_hash(report: dict[str, Any]) -> str:
    payload = dict(report)
    payload.pop("launch_status_hash", None)
    return hashlib.sha256(_stable_status_bytes(payload)).hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _load_json(path: Path) -> tuple[Any | None, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, {"path": str(path), "exists": False, "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        return None, {"path": str(path), "exists": True, "errors": [f"json_invalid:{exc.msg}"]}
    return payload, {"path": str(path), "exists": True}


def _load_or_build_p0a_status(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        source["source"] = "existing_file"
        return payload, source
    built = build_au_p0a_status_report(generated_at=generated_at)
    source["source"] = "generated_in_memory"
    return built, source


def _load_or_build_p0b_status(
    path: Path,
    *,
    runbook_path: Path,
    execution_path: Path,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        source["source"] = "existing_file"
        return payload, source

    from scripts.build_au_p0b_google_spike_status_report import build_au_p0b_google_spike_status_report

    built = build_au_p0b_google_spike_status_report(
        runbook_path=runbook_path,
        execution_path=execution_path,
        generated_at=generated_at,
    )
    source["source"] = "generated_in_memory"
    return built, source


def _load_or_build_p0b_package(
    path: Path,
    *,
    runbook_path: Path,
    execution_path: Path,
    status_report_path: Path,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        source["source"] = "existing_file"
        return payload, source
    built = build_au_p0b_google_evidence_package(
        runbook_path=runbook_path,
        execution_path=execution_path,
        status_report_path=status_report_path,
        generated_at=generated_at,
    )
    source["source"] = "generated_in_memory"
    return built, source


def _load_or_build_p0c_package(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        source["source"] = "existing_file"
        return payload, source
    built = build_au_p0c_report_package(output_path=path, generated_at=generated_at)
    source["source"] = "generated_in_memory"
    return built, source


def _p0a_summary(status: dict[str, Any], *, path: Path) -> dict[str, Any]:
    verification = verify_au_p0a_status_report(status, path=path)
    return {
        "status": "pass" if verification["status"] == "pass" and status.get("ready_for_design_partner") is True else "fail",
        "verifier_status": verification["status"],
        "errors": verification["errors"],
        "hash_valid": verification["hash_valid"],
        "ready_for_design_partner": status.get("ready_for_design_partner") is True,
        "next_action": status.get("next_action", ""),
        "remaining_blockers": [str(item) for item in _as_list(status.get("remaining_blockers"))],
        "completion": _as_dict(status.get("completion")),
        "status_report_hash": status.get("status_report_hash", ""),
    }


def _p0b_summary(
    status: dict[str, Any],
    package: dict[str, Any],
    *,
    status_path: Path,
    package_path: Path,
) -> dict[str, Any]:
    status_verification = verify_au_p0b_google_spike_status_report(status, path=status_path)
    package_verification = verify_au_p0b_google_evidence_package(package, path=package_path)
    google_allowed = (
        status_verification["status"] == "pass"
        and package_verification["status"] == "pass"
        and status.get("google_main_scoring_allowed") is True
        and package.get("google_main_scoring_allowed") is True
    )
    return {
        "status": "pass" if google_allowed else "fail",
        "status_verifier_status": status_verification["status"],
        "package_verifier_status": package_verification["status"],
        "errors": sorted(set(status_verification["errors"] + package_verification["errors"])),
        "status_hash_valid": status_verification["hash_valid"],
        "package_hash_valid": package_verification["hash_valid"],
        "google_main_scoring_allowed": google_allowed,
        "limited_coverage": not google_allowed,
        "next_action": status.get("next_action") or package.get("next_action") or "",
        "remaining_blockers": sorted(
            set(
                [str(item) for item in _as_list(status.get("remaining_blockers"))]
                + [str(item) for item in _as_list(package.get("remaining_blockers"))]
            )
        ),
        "status_report_hash": status.get("status_report_hash", ""),
        "package_payload_hash": package.get("package_payload_hash", ""),
        "package_summary": _as_dict(package.get("summary")),
    }


def _p0c_summary(package: dict[str, Any], *, path: Path) -> dict[str, Any]:
    verification = verify_au_p0c_report_package(package, path=path)
    report_export = _as_dict(package.get("report_export"))
    summary = _as_dict(package.get("summary"))
    ready = verification["status"] == "pass" and package.get("p0c_report_contract_ready") is True
    return {
        "status": "pass" if ready else "fail",
        "package_verifier_status": verification["status"],
        "errors": verification["errors"],
        "hash_valid": verification["hash_valid"],
        "p0c_report_contract_ready": ready,
        "next_action": package.get("next_action", ""),
        "remaining_blockers": [str(item) for item in _as_list(package.get("remaining_blockers"))],
        "report_contract_version": package.get("package_version", ""),
        "package_payload_hash": package.get("package_payload_hash", ""),
        "google_coverage": report_export.get("google_coverage", ""),
        "api_browser_fidelity_status": report_export.get("api_browser_fidelity_status", ""),
        "audit_event_count": report_export.get("audit_event_count", 0),
        "artifact_count": summary.get("artifact_count", 0),
        "failed_artifacts": [str(item) for item in _as_list(summary.get("failed_artifacts"))],
        "ready_artifacts": [str(item) for item in _as_list(summary.get("ready_artifacts"))],
    }


def _next_action(p0a: dict[str, Any], p0b: dict[str, Any], p0c: dict[str, Any]) -> str:
    if p0a.get("ready_for_design_partner") is not True:
        return str(p0a.get("next_action") or "complete_au_p0a_real_batches")
    if p0b.get("google_main_scoring_allowed") is not True:
        return str(p0b.get("next_action") or "complete_au_p0b_google_spike")
    if p0c.get("status") != "pass":
        return "fix_p0c_report_contract"
    return "ready_for_customer_report_handoff"


def build_au_launch_status(
    *,
    p0a_status_path: Path = Path(DEFAULT_P0A_STATUS_PATH),
    p0b_google_status_path: Path = Path(DEFAULT_P0B_GOOGLE_STATUS_PATH),
    p0b_google_package_path: Path = Path(DEFAULT_P0B_GOOGLE_PACKAGE_PATH),
    p0b_google_runbook_path: Path = Path(DEFAULT_P0B_GOOGLE_RUNBOOK_PATH),
    p0b_google_execution_path: Path = Path(DEFAULT_P0B_GOOGLE_EXECUTION_PATH),
    p0c_report_package_path: Path = Path(DEFAULT_P0C_REPORT_PACKAGE_PATH),
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    p0a_status, p0a_source = _load_or_build_p0a_status(p0a_status_path, generated_at=generated_at)
    p0b_status, p0b_status_source = _load_or_build_p0b_status(
        p0b_google_status_path,
        runbook_path=p0b_google_runbook_path,
        execution_path=p0b_google_execution_path,
        generated_at=generated_at,
    )
    p0b_package, p0b_package_source = _load_or_build_p0b_package(
        p0b_google_package_path,
        runbook_path=p0b_google_runbook_path,
        execution_path=p0b_google_execution_path,
        status_report_path=p0b_google_status_path,
        generated_at=generated_at,
    )
    p0c_package, p0c_source = _load_or_build_p0c_package(p0c_report_package_path, generated_at=generated_at)
    p0a = _p0a_summary(p0a_status, path=p0a_status_path)
    p0b = _p0b_summary(
        p0b_status,
        p0b_package,
        status_path=p0b_google_status_path,
        package_path=p0b_google_package_path,
    )
    p0c = _p0c_summary(p0c_package, path=p0c_report_package_path)
    ready_for_customer_report_handoff = (
        p0a.get("ready_for_design_partner") is True
        and p0b.get("google_main_scoring_allowed") is True
        and p0c.get("p0c_report_contract_ready") is True
    )
    remaining_blockers = sorted(
        set(
            [f"p0a:{item}" for item in _as_list(p0a.get("remaining_blockers"))]
            + [f"p0b_google:{item}" for item in _as_list(p0b.get("remaining_blockers"))]
            + [f"p0c:{item}" for item in _as_list(p0c.get("errors"))]
        )
    )
    report: dict[str, Any] = {
        "launch_status_version": LAUNCH_STATUS_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if ready_for_customer_report_handoff else "fail",
        "ready_for_customer_report_handoff": ready_for_customer_report_handoff,
        "next_action": _next_action(p0a, p0b, p0c),
        "remaining_blockers": remaining_blockers,
        "inputs": {
            "p0a_status_path": str(p0a_status_path),
            "p0b_google_status_path": str(p0b_google_status_path),
            "p0b_google_package_path": str(p0b_google_package_path),
            "p0b_google_runbook_path": str(p0b_google_runbook_path),
            "p0b_google_execution_path": str(p0b_google_execution_path),
            "p0c_report_package_path": str(p0c_report_package_path),
            "output_path": str(output_path) if output_path else "",
        },
        "sources": {
            "p0a_status": p0a_source,
            "p0b_google_status": p0b_status_source,
            "p0b_google_package": p0b_package_source,
            "p0c_report_package": p0c_source,
        },
        "p0a_design_partner": p0a,
        "p0b_google": p0b,
        "p0c_customer_report": p0c,
    }
    report["launch_status_hash"] = compute_launch_status_hash(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU launch status report across P0a/P0b/P0c gates")
    parser.add_argument(
        "--p0a-status-path",
        default=os.environ.get("GEO_AU_P0A_STATUS_OUTPUT_PATH", DEFAULT_P0A_STATUS_PATH),
    )
    parser.add_argument(
        "--p0b-google-status-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH", DEFAULT_P0B_GOOGLE_STATUS_PATH),
    )
    parser.add_argument(
        "--p0b-google-package-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH", DEFAULT_P0B_GOOGLE_PACKAGE_PATH),
    )
    parser.add_argument(
        "--p0b-google-runbook-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH", DEFAULT_P0B_GOOGLE_RUNBOOK_PATH),
    )
    parser.add_argument(
        "--p0b-google-execution-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH", DEFAULT_P0B_GOOGLE_EXECUTION_PATH),
    )
    parser.add_argument(
        "--p0c-report-package-path",
        default=os.environ.get("GEO_AU_P0C_REPORT_PACKAGE_OUTPUT_PATH", DEFAULT_P0C_REPORT_PACKAGE_PATH),
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GEO_AU_LAUNCH_STATUS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit non-zero unless P0a, P0b Google and P0c report gates are ready for customer report handoff.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    report = build_au_launch_status(
        p0a_status_path=Path(args.p0a_status_path),
        p0b_google_status_path=Path(args.p0b_google_status_path),
        p0b_google_package_path=Path(args.p0b_google_package_path),
        p0b_google_runbook_path=Path(args.p0b_google_runbook_path),
        p0b_google_execution_path=Path(args.p0b_google_execution_path),
        p0c_report_package_path=Path(args.p0c_report_package_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if args.require_ready and report["ready_for_customer_report_handoff"] is not True:
        raise SystemExit(2)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
