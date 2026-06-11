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

from scripts.build_au_p0a_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_PATH  # noqa: E402
from scripts.build_au_p0a_env_report import DEFAULT_OUTPUT_PATH as DEFAULT_ENV_REPORT_PATH  # noqa: E402
from scripts.build_preflight_manifest import MANIFEST_VERSION, compute_manifest_payload_hash  # noqa: E402
from scripts.verify_au_p0a_env_report import verify_au_p0a_env_report  # noqa: E402
from scripts.run_au_p0a_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_EXECUTION_PATH  # noqa: E402
from scripts.verify_au_p0a_runbook_execution import verify_au_p0a_runbook_execution  # noqa: E402
from scripts.verify_au_p0a_runbook import verify_au_p0a_runbook  # noqa: E402
from scripts.verify_preflight_payload import verify_preflight_payload  # noqa: E402


PACKAGE_VERSION = "au_p0a_evidence_package_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-evidence-package-latest.json"
PAYLOAD_ARTIFACTS = (
    ("preflight_json", "preflight_json"),
    ("small_batch_json", "small_batch_json"),
    ("full_batch_json", "full_batch_json"),
)
MANIFEST_ARTIFACTS = (
    ("preflight_manifest", "preflight_manifest", "preflight_json"),
    ("small_batch_manifest", "small_batch_manifest", "small_batch_json"),
    ("full_batch_manifest", "full_batch_manifest", "full_batch_json"),
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _stable_package_bytes(package: dict[str, Any]) -> bytes:
    return json.dumps(
        package,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def compute_package_payload_hash(package: dict[str, Any]) -> str:
    payload_for_hash = dict(package)
    payload_for_hash.pop("package_payload_hash", None)
    return hashlib.sha256(_stable_package_bytes(payload_for_hash)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, missing_error: str, invalid_prefix: str) -> tuple[Any | None, dict[str, Any]]:
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


def _runbook_artifact(runbook_path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    runbook, entry = _load_json(
        runbook_path,
        missing_error="runbook_file_missing",
        invalid_prefix="runbook_json_invalid",
    )
    if not isinstance(runbook, dict):
        entry.setdefault("status", "fail")
        entry.setdefault("errors", ["runbook_not_json_object"])
        return None, entry
    verification = verify_au_p0a_runbook(runbook, path=runbook_path)
    entry.update(
        {
            "status": verification["status"],
            "errors": verification["errors"],
            "hash_valid": verification["hash_valid"],
            "runbook_version": verification.get("runbook_version", ""),
            "runbook_payload_hash": verification.get("runbook_payload_hash", ""),
            "small_batch_planned_runs": verification.get("small_batch_planned_runs"),
            "full_batch_planned_runs": verification.get("full_batch_planned_runs"),
            "step_count": verification.get("step_count"),
        }
    )
    return runbook, entry


def _readiness_artifact(path: Path) -> dict[str, Any]:
    payload, entry = _load_json(
        path,
        missing_error="readiness_file_missing",
        invalid_prefix="readiness_json_invalid",
    )
    if not isinstance(payload, dict):
        entry.setdefault("status", "fail")
        entry.setdefault("errors", ["readiness_not_json_object"])
        return entry
    entry.update(
        {
            "status": payload.get("status", "fail"),
            "readiness_version": payload.get("readiness_version", ""),
            "phase": payload.get("phase", ""),
            "ready_to_run_phase": payload.get("ready_to_run_phase", False),
            "recommended_next_action": payload.get("recommended_next_action", ""),
            "errors": payload.get("errors", []),
            "warnings": payload.get("warnings", []),
        }
    )
    return entry


def _environment_artifact(path: Path) -> dict[str, Any]:
    payload, entry = _load_json(
        path,
        missing_error="environment_report_file_missing",
        invalid_prefix="environment_report_json_invalid",
    )
    if not isinstance(payload, dict):
        entry.setdefault("status", "fail")
        entry.setdefault("errors", ["environment_report_not_json_object"])
        return entry
    verifier = verify_au_p0a_env_report(payload, path=path)
    entry.update(
        {
            "status": verifier["status"],
            "errors": verifier["errors"],
            "hash_valid": verifier["hash_valid"],
            "environment_report_version": verifier.get("environment_report_version", ""),
            "environment_report_hash": verifier.get("environment_report_hash", ""),
            "ready_for_real_batch": verifier.get("ready_for_real_batch", False),
            "missing_required": verifier.get("missing_required", []),
            "missing_recommended": verifier.get("missing_recommended", []),
            "next_action": verifier.get("next_action", ""),
        }
    )
    return entry


def _runbook_execution_artifact(path: Path) -> dict[str, Any]:
    payload, entry = _load_json(
        path,
        missing_error="runbook_execution_file_missing",
        invalid_prefix="runbook_execution_json_invalid",
    )
    if not isinstance(payload, dict):
        entry.setdefault("status", "fail")
        entry.setdefault("errors", ["runbook_execution_not_json_object"])
        return entry
    verifier = verify_au_p0a_runbook_execution(payload, path=path)
    entry.update(
        {
            "status": verifier["status"],
            "errors": verifier["errors"],
            "hash_valid": verifier["hash_valid"],
            "execution_version": verifier.get("execution_version", ""),
            "execution_payload_hash": verifier.get("execution_payload_hash", ""),
            "mode": verifier.get("mode", ""),
            "ready_to_execute": verifier.get("ready_to_execute", False),
            "planned_step_count": verifier.get("planned_step_count"),
            "recorded_step_count": verifier.get("recorded_step_count"),
            "executed_command_count": verifier.get("executed_command_count"),
        }
    )
    return entry


def _payload_artifact(path: Path) -> dict[str, Any]:
    payload, entry = _load_json(
        path,
        missing_error="preflight_payload_file_missing",
        invalid_prefix="preflight_payload_json_invalid",
    )
    if not isinstance(payload, dict):
        entry.setdefault("status", "fail")
        entry.setdefault("errors", ["preflight_payload_not_json_object"])
        return entry
    verifier = verify_preflight_payload(payload, path=path)
    entry.update(
        {
            "status": verifier["status"],
            "errors": verifier["errors"],
            "hash_valid": verifier["hash_valid"],
            "ready_for_design_partner": verifier["ready_for_design_partner"],
            "phase": verifier.get("phase", ""),
            "recommended_next_action": verifier.get("recommended_next_action", ""),
            "blocking_reasons": verifier.get("blocking_reasons", []),
            "payload_hash": verifier.get("preflight_payload_hash", ""),
        }
    )
    return entry


def _manifest_artifact(path: Path, expected_payload_path: Path | None) -> dict[str, Any]:
    manifest, entry = _load_json(
        path,
        missing_error="preflight_manifest_file_missing",
        invalid_prefix="preflight_manifest_json_invalid",
    )
    if not isinstance(manifest, dict):
        entry.setdefault("status", "fail")
        entry.setdefault("errors", ["preflight_manifest_not_json_object"])
        return entry

    errors: list[str] = []
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        errors.append("preflight_manifest_version_invalid")
    expected_hash = manifest.get("manifest_payload_hash")
    computed_hash = compute_manifest_payload_hash(manifest)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("preflight_manifest_payload_hash_mismatch")
    preflight_payload = _as_dict(manifest.get("preflight_payload"))
    manifest_payload_path = preflight_payload.get("path")
    payload_path_matches_expected = None
    if expected_payload_path is not None and isinstance(manifest_payload_path, str):
        payload_path_matches_expected = Path(manifest_payload_path).resolve() == expected_payload_path.resolve()
        if not payload_path_matches_expected:
            errors.append("preflight_manifest_payload_path_mismatch")
    elif expected_payload_path is not None:
        errors.append("preflight_manifest_payload_path_missing")

    verifier = _as_dict(manifest.get("verifier"))
    run_summary = _as_dict(manifest.get("run_summary"))
    ready_for_design_partner = (
        verifier.get("status") == "pass"
        and verifier.get("hash_valid") is True
        and verifier.get("ready_for_design_partner") is True
        and run_summary.get("ready_for_design_partner") is True
    )
    entry.update(
        {
            "status": "pass" if not errors else "fail",
            "errors": errors,
            "hash_valid": hash_valid,
            "payload_path_matches_expected": payload_path_matches_expected,
            "ready_for_design_partner": ready_for_design_partner,
            "manifest_version": manifest.get("manifest_version", ""),
            "manifest_payload_hash": expected_hash if isinstance(expected_hash, str) else "",
            "computed_manifest_payload_hash": computed_hash,
            "run_summary": {
                "phase": run_summary.get("phase", ""),
                "ready_for_design_partner": run_summary.get("ready_for_design_partner", False),
                "planned_runs": run_summary.get("planned_runs"),
                "record_count": run_summary.get("record_count"),
                "success_count": run_summary.get("success_count"),
                "failure_count": run_summary.get("failure_count"),
            },
            "blocking_reasons": _as_dict(manifest.get("audit_checklist")).get("blocking_reasons", []),
        }
    )
    return entry


def _artifact_paths(runbook: dict[str, Any] | None) -> dict[str, str]:
    return {
        key: value
        for key, value in _as_dict(_as_dict(runbook).get("artifact_paths")).items()
        if isinstance(key, str) and isinstance(value, str)
    }


def build_au_p0a_evidence_package(
    *,
    runbook_path: Path = Path(DEFAULT_RUNBOOK_PATH),
    environment_path: Path | None = None,
    readiness_path: Path | None = None,
    runbook_execution_path: Path | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    runbook, runbook_entry = _runbook_artifact(runbook_path)
    artifact_paths = _artifact_paths(runbook)
    effective_readiness_path = readiness_path or Path(
        os.environ.get("GENO_AU_P0A_READINESS_OUTPUT_PATH", "docs/runtime_preflight/au-p0a-readiness-latest.json")
    )
    effective_environment_path = environment_path or Path(
        os.environ.get("GENO_AU_P0A_ENV_OUTPUT_PATH", DEFAULT_ENV_REPORT_PATH)
    )
    effective_runbook_execution_path = runbook_execution_path or Path(
        os.environ.get("GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH", DEFAULT_RUNBOOK_EXECUTION_PATH)
    )
    readiness_entry = _readiness_artifact(effective_readiness_path)

    artifacts: dict[str, Any] = {
        "runbook": runbook_entry,
        "environment": _environment_artifact(effective_environment_path),
        "runbook_execution": _runbook_execution_artifact(effective_runbook_execution_path),
        "readiness": readiness_entry,
    }
    for artifact_name, path_key in PAYLOAD_ARTIFACTS:
        path_value = artifact_paths.get(path_key)
        if not path_value:
            artifacts[artifact_name] = {"path": "", "exists": False, "status": "fail", "errors": ["artifact_path_missing"]}
            continue
        artifacts[artifact_name] = _payload_artifact(Path(path_value))

    for artifact_name, path_key, payload_path_key in MANIFEST_ARTIFACTS:
        path_value = artifact_paths.get(path_key)
        expected_payload = artifact_paths.get(payload_path_key)
        if not path_value:
            artifacts[artifact_name] = {"path": "", "exists": False, "status": "fail", "errors": ["artifact_path_missing"]}
            continue
        artifacts[artifact_name] = _manifest_artifact(Path(path_value), Path(expected_payload) if expected_payload else None)

    missing_artifacts = [name for name, entry in artifacts.items() if not entry.get("exists")]
    failed_artifacts = [name for name, entry in artifacts.items() if entry.get("status") == "fail"]
    ready_artifacts = [
        name
        for name, entry in artifacts.items()
        if entry.get("ready_for_design_partner") is True
        or entry.get("ready_for_real_batch") is True
        or entry.get("ready_to_run_phase") is True
        or entry.get("ready_to_execute") is True
    ]
    blocking_reasons = [
        f"{name}:{error}"
        for name, entry in artifacts.items()
        for error in entry.get("errors", [])
    ]
    package: dict[str, Any] = {
        "package_version": PACKAGE_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if not failed_artifacts else "fail",
        "ready_for_design_partner": (
            artifacts["preflight_json"].get("ready_for_design_partner") is True
            and artifacts["preflight_manifest"].get("ready_for_design_partner") is True
            and artifacts["small_batch_json"].get("ready_for_design_partner") is True
            and artifacts["small_batch_manifest"].get("ready_for_design_partner") is True
            and artifacts["full_batch_json"].get("ready_for_design_partner") is True
            and artifacts["full_batch_manifest"].get("ready_for_design_partner") is True
        ),
        "runbook_path": str(runbook_path),
        "output_path": str(output_path) if output_path else "",
        "artifact_paths": artifact_paths,
        "environment_path": str(effective_environment_path),
        "runbook_execution_path": str(effective_runbook_execution_path),
        "summary": {
            "artifact_count": len(artifacts),
            "missing_artifacts": missing_artifacts,
            "failed_artifacts": failed_artifacts,
            "ready_artifacts": ready_artifacts,
            "blocking_reasons": blocking_reasons,
        },
        "artifacts": artifacts,
    }
    package["package_payload_hash"] = compute_package_payload_hash(package)
    return package


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a package manifest for AU P0a real-batch evidence")
    parser.add_argument(
        "--runbook-path",
        default=os.environ.get("GENO_AU_P0A_RUNBOOK_OUTPUT_PATH", DEFAULT_RUNBOOK_PATH),
        help="Path to the generated AU P0a runbook JSON.",
    )
    parser.add_argument(
        "--readiness-path",
        default=os.environ.get("GENO_AU_P0A_READINESS_OUTPUT_PATH", "docs/runtime_preflight/au-p0a-readiness-latest.json"),
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
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_PACKAGE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0a evidence package JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    package = build_au_p0a_evidence_package(
        runbook_path=Path(args.runbook_path),
        environment_path=Path(args.environment_path),
        readiness_path=Path(args.readiness_path),
        runbook_execution_path=Path(args.runbook_execution_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(package, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(package, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if package["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
