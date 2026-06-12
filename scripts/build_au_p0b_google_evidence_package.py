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

from scripts.build_au_p0b_google_spike_runbook import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_PATH,
)
from scripts.build_au_p0b_google_spike_status_report import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_STATUS_REPORT_PATH,
)
from scripts.run_au_p0b_google_spike_runbook import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_EXECUTION_PATH,
)
from scripts.verify_au_p0b_google_spike_status_report import (  # noqa: E402
    verify_au_p0b_google_spike_status_report,
)


PACKAGE_VERSION = "au_p0b_google_evidence_package_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-evidence-package-latest.json"
REQUIRED_ARTIFACTS = (
    "status_report",
    "runbook",
    "execution",
    "playwright_env",
    "playwright_smoke",
    "manual_backfill",
    "health",
    "health_manifest",
    "spike",
    "spike_manifest",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _stable_package_bytes(package: dict[str, Any]) -> bytes:
    return json.dumps(
        package,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def compute_google_evidence_package_hash(package: dict[str, Any]) -> str:
    payload = dict(package)
    payload.pop("package_payload_hash", None)
    return hashlib.sha256(_stable_package_bytes(payload)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, missing_error: str, invalid_prefix: str) -> tuple[Any | None, dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except FileNotFoundError:
        return None, {
            "path": str(path),
            "exists": False,
            "status": "fail",
            "errors": [missing_error],
        }
    except json.JSONDecodeError as exc:
        return None, {
            "path": str(path),
            "exists": True,
            "status": "fail",
            "errors": [f"{invalid_prefix}:{exc.msg}"],
        }
    return payload, {
        "path": str(path),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "file_sha256": _file_sha256(path),
    }


def _paths_match(left: object, right: Path) -> bool:
    if not isinstance(left, str) or not left:
        return False
    return Path(left).resolve() == right.resolve()


def _status_report_artifact(
    path: Path,
    *,
    expected_runbook_path: Path,
    expected_execution_path: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    payload, entry = _load_json(
        path,
        missing_error="status_report_file_missing",
        invalid_prefix="status_report_json_invalid",
    )
    if not isinstance(payload, dict):
        entry.setdefault("status", "fail")
        entry.setdefault("errors", ["status_report_not_json_object"])
        entry.setdefault("hash_valid", False)
        entry["remaining_blockers"] = []
        entry["google_main_scoring_allowed"] = False
        entry["limited_coverage"] = True
        entry["next_action"] = "run_au_p0b_google_status"
        return None, entry

    verification = verify_au_p0b_google_spike_status_report(payload, path=path)
    errors = list(verification["errors"])
    inputs = _as_dict(payload.get("inputs"))
    if not _paths_match(inputs.get("runbook_path"), expected_runbook_path):
        errors.append("status_report_runbook_path_mismatch")
    if not _paths_match(inputs.get("execution_path"), expected_execution_path):
        errors.append("status_report_execution_path_mismatch")
    entry.update(
        {
            "status": "pass" if verification["status"] == "pass" and not errors else "fail",
            "errors": errors,
            "hash_valid": verification["hash_valid"],
            "status_report_version": verification.get("status_report_version", ""),
            "status_report_hash": verification.get("status_report_hash", ""),
            "computed_status_report_hash": verification.get("computed_status_report_hash", ""),
            "google_main_scoring_allowed": verification.get("google_main_scoring_allowed", False),
            "limited_coverage": verification.get("limited_coverage", True),
            "next_action": verification.get("next_action", ""),
            "remaining_blocker_count": verification.get("remaining_blocker_count", 0),
            "remaining_blockers": [str(item) for item in _as_list(payload.get("remaining_blockers"))],
        }
    )
    return payload, entry


def _plain_artifact(path: Path, *, error: str) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "status": "fail", "errors": [error]}
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "file_sha256": _file_sha256(path),
        "status": "fail",
        "errors": ["status_report_artifact_unavailable"],
    }


def _status_artifact_with_file_metadata(name: str, value: object) -> dict[str, Any]:
    item = dict(_as_dict(value))
    path_value = item.get("path")
    if isinstance(path_value, str) and path_value:
        path = Path(path_value)
        item.setdefault("path", str(path))
        if path.exists():
            item["exists"] = True
            item["size_bytes"] = path.stat().st_size
            item["file_sha256"] = _file_sha256(path)
        else:
            item["exists"] = False
    else:
        item["path"] = ""
        item["exists"] = False
        item.setdefault("errors", ["artifact_path_missing"])
    item.setdefault("status", "fail")
    item.setdefault("errors", [])
    item["source"] = f"status_report.artifacts.{name}"
    return item


def _fallback_artifacts(runbook_path: Path, execution_path: Path) -> dict[str, Any]:
    return {
        "runbook": _plain_artifact(runbook_path, error="runbook_file_missing"),
        "execution": _plain_artifact(execution_path, error="runbook_execution_file_missing"),
        "playwright_env": _plain_artifact(
            Path("docs/runtime_preflight/au-p0b-google-playwright-env-latest.json"),
            error="status_report_missing",
        ),
        "playwright_smoke": _plain_artifact(
            Path("docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json"),
            error="status_report_missing",
        ),
        "manual_backfill": _plain_artifact(
            Path("docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json"),
            error="status_report_missing",
        ),
        "health": _plain_artifact(
            Path("docs/runtime_preflight/au-p0b-google-spike-health-latest.json"),
            error="status_report_missing",
        ),
        "health_manifest": _plain_artifact(
            Path("docs/runtime_preflight/au-p0b-google-spike-health-manifest-latest.json"),
            error="status_report_missing",
        ),
        "spike": _plain_artifact(
            Path("docs/runtime_preflight/au-p0b-google-spike-latest.json"),
            error="status_report_missing",
        ),
        "spike_manifest": _plain_artifact(
            Path("docs/runtime_preflight/au-p0b-google-spike-manifest-latest.json"),
            error="status_report_missing",
        ),
    }


def _ready_artifacts(artifacts: dict[str, dict[str, Any]]) -> list[str]:
    ready: list[str] = []
    for name, artifact in artifacts.items():
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
            ready.append(name)
    return sorted(ready)


def _summary(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing_artifacts = sorted(name for name, item in artifacts.items() if item.get("exists") is not True)
    failed_artifacts = sorted(name for name, item in artifacts.items() if item.get("status") == "fail")
    blocking_reasons = sorted(
        f"{name}:{error}"
        for name, item in artifacts.items()
        for error in _as_list(item.get("errors"))
    )
    return {
        "artifact_count": len(artifacts),
        "missing_artifacts": missing_artifacts,
        "failed_artifacts": failed_artifacts,
        "ready_artifacts": _ready_artifacts(artifacts),
        "blocking_reasons": blocking_reasons,
    }


def build_au_p0b_google_evidence_package(
    *,
    runbook_path: Path = Path(DEFAULT_RUNBOOK_PATH),
    execution_path: Path = Path(DEFAULT_EXECUTION_PATH),
    status_report_path: Path = Path(DEFAULT_STATUS_REPORT_PATH),
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    status_payload, status_entry = _status_report_artifact(
        status_report_path,
        expected_runbook_path=runbook_path,
        expected_execution_path=execution_path,
    )
    artifacts: dict[str, dict[str, Any]] = {"status_report": status_entry}
    if isinstance(status_payload, dict):
        status_artifacts = _as_dict(status_payload.get("artifacts"))
        for artifact_name in REQUIRED_ARTIFACTS:
            if artifact_name == "status_report":
                continue
            artifacts[artifact_name] = _status_artifact_with_file_metadata(
                artifact_name,
                status_artifacts.get(artifact_name),
            )
    else:
        artifacts.update(_fallback_artifacts(runbook_path, execution_path))

    summary = _summary(artifacts)
    google_allowed = status_entry.get("google_main_scoring_allowed") is True and not summary["failed_artifacts"]
    remaining_blockers = (
        [str(item) for item in _as_list(status_entry.get("remaining_blockers"))]
        if status_entry.get("exists") is True
        else ["status_report:status_report_file_missing"]
    )
    package: dict[str, Any] = {
        "package_version": PACKAGE_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if not summary["failed_artifacts"] else "fail",
        "google_main_scoring_allowed": google_allowed,
        "limited_coverage": not google_allowed,
        "next_action": str(status_entry.get("next_action") or "run_au_p0b_google_status"),
        "remaining_blockers": remaining_blockers,
        "runbook_path": str(runbook_path),
        "execution_path": str(execution_path),
        "status_report_path": str(status_report_path),
        "output_path": str(output_path) if output_path else "",
        "summary": summary,
        "artifacts": artifacts,
    }
    package["package_payload_hash"] = compute_google_evidence_package_hash(package)
    return package


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google spike evidence package JSON")
    parser.add_argument(
        "--runbook-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH", DEFAULT_RUNBOOK_PATH),
        help="Path to the generated AU P0b Google runbook JSON.",
    )
    parser.add_argument(
        "--execution-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH", DEFAULT_EXECUTION_PATH),
        help="Path to the generated AU P0b Google runbook execution JSON.",
    )
    parser.add_argument(
        "--status-report-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH", DEFAULT_STATUS_REPORT_PATH),
        help="Path to the AU P0b Google status report JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0b Google evidence package JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    package = build_au_p0b_google_evidence_package(
        runbook_path=Path(args.runbook_path),
        execution_path=Path(args.execution_path),
        status_report_path=Path(args.status_report_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(package, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(package, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if package["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
