from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_au_p0a_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_PATH  # noqa: E402
from scripts.build_preflight_manifest import (  # noqa: E402
    MANIFEST_VERSION,
    compute_manifest_payload_hash,
)
from scripts.verify_au_p0a_runbook import REQUIRED_ENV, verify_au_p0a_runbook  # noqa: E402
from scripts.verify_preflight_payload import verify_preflight_payload  # noqa: E402


READINESS_VERSION = "au_p0a_readiness_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-readiness-latest.json"
PHASES = ("preflight", "small_batch", "full_batch")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _load_json(path: Path, missing_error: str, invalid_prefix: str) -> tuple[Any | None, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
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
    return payload, {"path": str(path), "exists": True}


def _load_and_verify_runbook(runbook_path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    runbook, entry = _load_json(
        runbook_path,
        missing_error="runbook_file_missing",
        invalid_prefix="runbook_json_invalid",
    )
    if runbook is None:
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
    return runbook if isinstance(runbook, dict) else None, entry


def _environment_check(runbook: dict[str, Any] | None, env: Mapping[str, str]) -> dict[str, Any]:
    required = tuple(str(item) for item in _as_sequence(_as_dict(runbook).get("required_env"))) or REQUIRED_ENV
    recommended = tuple(str(item) for item in _as_sequence(_as_dict(runbook).get("recommended_env")))
    required_checks = [{"name": name, "present": bool(env.get(name))} for name in required]
    recommended_checks = [{"name": name, "present": bool(env.get(name))} for name in recommended]
    missing_required = [item["name"] for item in required_checks if not item["present"]]
    missing_recommended = [item["name"] for item in recommended_checks if not item["present"]]
    return {
        "status": "pass" if not missing_required else "fail",
        "required": required_checks,
        "recommended": recommended_checks,
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "secrets_redacted": True,
    }


def _artifact_path(artifact_paths: dict[str, Any], key: str) -> Path | None:
    path = artifact_paths.get(key)
    return Path(path) if isinstance(path, str) and path else None


def _payload_gate(path: Path | None, *, require_design_partner_ready: bool) -> dict[str, Any]:
    if path is None:
        return {"path": "", "exists": False, "status": "fail", "errors": ["artifact_path_missing"]}
    payload, entry = _load_json(
        path,
        missing_error="preflight_payload_file_missing",
        invalid_prefix="preflight_payload_json_invalid",
    )
    if payload is None:
        return entry
    verifier = verify_preflight_payload(
        payload,
        path=path,
        require_design_partner_ready=require_design_partner_ready,
    )
    entry.update(
        {
            "status": verifier["status"],
            "errors": verifier["errors"],
            "hash_valid": verifier["hash_valid"],
            "ready_for_design_partner": verifier["ready_for_design_partner"],
            "phase": verifier.get("phase"),
            "recommended_next_action": verifier.get("recommended_next_action"),
            "blocking_reasons": verifier.get("blocking_reasons", ()),
        }
    )
    return entry


def _manifest_gate(
    path: Path | None,
    *,
    expected_payload_path: Path | None,
    require_design_partner_ready: bool,
) -> dict[str, Any]:
    if path is None:
        return {"path": "", "exists": False, "status": "fail", "errors": ["artifact_path_missing"]}
    manifest, entry = _load_json(
        path,
        missing_error="preflight_manifest_file_missing",
        invalid_prefix="preflight_manifest_json_invalid",
    )
    if manifest is None:
        return entry
    if not isinstance(manifest, dict):
        entry.update({"status": "fail", "errors": ["preflight_manifest_not_json_object"]})
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
    payload_path_matches = None
    if expected_payload_path is not None and isinstance(manifest_payload_path, str):
        payload_path_matches = Path(manifest_payload_path).resolve() == expected_payload_path.resolve()
        if not payload_path_matches:
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
    if require_design_partner_ready and not ready_for_design_partner:
        errors.append("preflight_manifest_design_partner_not_ready")

    entry.update(
        {
            "status": "pass" if not errors else "fail",
            "errors": errors,
            "hash_valid": hash_valid,
            "payload_path_matches_expected": payload_path_matches,
            "ready_for_design_partner": ready_for_design_partner,
            "manifest_payload_hash": expected_hash if isinstance(expected_hash, str) else "",
            "computed_manifest_payload_hash": computed_hash,
        }
    )
    return entry


def _append_gate_errors(errors: list[str], gate_name: str, gate: dict[str, Any]) -> None:
    if gate.get("status") == "pass":
        return
    for error in _as_sequence(gate.get("errors")):
        errors.append(f"{gate_name}:{error}")


def _next_action(phase: str, errors: list[str]) -> str:
    if errors:
        if any(error.startswith("required_env_missing:") for error in errors):
            return "configure_required_environment"
        if any(error.startswith("runbook") or error.startswith("runbook:") for error in errors):
            return "run_make_au_p0a_runbook_and_verify"
        if any(error.startswith("preflight_") for error in errors):
            return "run_or_fix_preflight_and_manifest"
        if any(error.startswith("small_batch_") for error in errors):
            return "run_or_fix_small_batch_and_manifest"
        return "resolve_readiness_errors"
    if phase == "preflight":
        return "run_make_api_preflight"
    if phase == "small_batch":
        return "run_small_au_p0a_batch"
    return "run_full_au_p0a_batch"


def verify_au_p0a_readiness(
    *,
    phase: str = "preflight",
    runbook_path: Path = Path(DEFAULT_RUNBOOK_PATH),
    env: Mapping[str, str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    env_map = os.environ if env is None else env
    errors: list[str] = []
    warnings: list[str] = []
    gates: dict[str, Any] = {}

    if phase not in PHASES:
        errors.append(f"phase_invalid:{phase}")
        phase = "preflight"

    runbook, runbook_entry = _load_and_verify_runbook(runbook_path)
    if runbook_entry.get("status") != "pass":
        errors.extend(f"runbook:{error}" for error in _as_sequence(runbook_entry.get("errors")))

    environment = _environment_check(runbook, env_map)
    for name in environment["missing_required"]:
        errors.append(f"required_env_missing:{name}")
    for name in environment["missing_recommended"]:
        warnings.append(f"recommended_env_missing:{name}")

    artifact_paths = _as_dict(_as_dict(runbook).get("artifact_paths"))
    if runbook is not None and phase in ("small_batch", "full_batch"):
        preflight_path = _artifact_path(artifact_paths, "preflight_json")
        preflight_manifest_path = _artifact_path(artifact_paths, "preflight_manifest")
        gates["preflight_json"] = _payload_gate(preflight_path, require_design_partner_ready=True)
        gates["preflight_manifest"] = _manifest_gate(
            preflight_manifest_path,
            expected_payload_path=preflight_path,
            require_design_partner_ready=True,
        )
        _append_gate_errors(errors, "preflight_json", gates["preflight_json"])
        _append_gate_errors(errors, "preflight_manifest", gates["preflight_manifest"])

    if runbook is not None and phase == "full_batch":
        small_batch_path = _artifact_path(artifact_paths, "small_batch_json")
        small_manifest_path = _artifact_path(artifact_paths, "small_batch_manifest")
        gates["small_batch_json"] = _payload_gate(small_batch_path, require_design_partner_ready=True)
        gates["small_batch_manifest"] = _manifest_gate(
            small_manifest_path,
            expected_payload_path=small_batch_path,
            require_design_partner_ready=True,
        )
        _append_gate_errors(errors, "small_batch_json", gates["small_batch_json"])
        _append_gate_errors(errors, "small_batch_manifest", gates["small_batch_manifest"])

    return {
        "readiness_version": READINESS_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "phase": phase,
        "status": "pass" if not errors else "fail",
        "ready_to_run_phase": not errors,
        "errors": errors,
        "warnings": warnings,
        "recommended_next_action": _next_action(phase, errors),
        "runbook": runbook_entry,
        "environment": environment,
        "artifact_paths": artifact_paths,
        "gates": gates,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify AU P0a real-batch readiness before external collection")
    parser.add_argument(
        "--phase",
        choices=PHASES,
        default=os.environ.get("GENO_AU_P0A_READINESS_PHASE", "preflight"),
        help="Readiness phase to verify: preflight, small_batch, or full_batch.",
    )
    parser.add_argument(
        "--runbook-path",
        default=os.environ.get("GENO_AU_P0A_RUNBOOK_OUTPUT_PATH", DEFAULT_RUNBOOK_PATH),
        help="Path to the generated AU P0a runbook JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_READINESS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the readiness JSON result.",
    )
    parser.add_argument(
        "--generated-at",
        default=None,
        help="Override generated_at timestamp, primarily for deterministic replay tests.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    result = verify_au_p0a_readiness(
        phase=args.phase,
        runbook_path=Path(args.runbook_path),
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
