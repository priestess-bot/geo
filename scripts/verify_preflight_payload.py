from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


DEFAULT_PREFLIGHT_PATH = "docs/runtime_preflight/api-preflight-latest.json"
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SUMMARY_VERSION = "provider_preflight_v1"
CHECKLIST_VERSION = "provider_preflight_audit_checklist_v1"
SUMMARY_REQUIRED_FIELDS = (
    "summary_version",
    "phase",
    "exit_code",
    "ready_for_design_partner",
    "recommended_next_action",
)
CHECKLIST_REQUIRED_FIELDS = (
    "checklist_version",
    "overall_status",
    "ready_for_design_partner",
    "worker_args",
    "evidence_refs",
    "checks",
    "run_totals",
)


def stable_preflight_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def compute_preflight_payload_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("preflight_payload_hash", None)
    return hashlib.sha256(stable_preflight_payload_bytes(payload_for_hash)).hexdigest()


def _missing_fields(payload: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(field for field in fields if field not in payload)


def _output_path_matches_file(payload: dict[str, Any], path: Path) -> bool | None:
    output_path = payload.get("preflight_output_path")
    if not isinstance(output_path, str) or not output_path:
        return None
    return Path(output_path).resolve() == path.resolve()


def verify_preflight_payload(
    payload: Any,
    *,
    path: Path | None = None,
    require_design_partner_ready: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["payload_not_json_object"],
            "hash_valid": False,
            "ready_for_design_partner": False,
        }

    expected_hash = payload.get("preflight_payload_hash")
    if not isinstance(expected_hash, str) or not HASH_PATTERN.fullmatch(expected_hash):
        errors.append("preflight_payload_hash_missing_or_invalid")
        expected_hash = ""
    computed_hash = compute_preflight_payload_hash(payload)
    hash_valid = bool(expected_hash) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("preflight_payload_hash_mismatch")

    summary = payload.get("preflight_summary")
    if not isinstance(summary, dict):
        errors.append("preflight_summary_missing_or_invalid")
        summary = {}
    else:
        for field in _missing_fields(summary, SUMMARY_REQUIRED_FIELDS):
            errors.append(f"preflight_summary_missing_field:{field}")
        if summary.get("summary_version") != SUMMARY_VERSION:
            errors.append("preflight_summary_version_invalid")

    checklist = payload.get("preflight_audit_checklist")
    if not isinstance(checklist, dict):
        errors.append("preflight_audit_checklist_missing_or_invalid")
        checklist = {}
    else:
        for field in _missing_fields(checklist, CHECKLIST_REQUIRED_FIELDS):
            errors.append(f"preflight_audit_checklist_missing_field:{field}")
        if checklist.get("checklist_version") != CHECKLIST_VERSION:
            errors.append("preflight_audit_checklist_version_invalid")
        if "worker_args" in checklist and not isinstance(checklist.get("worker_args"), list):
            errors.append("preflight_audit_checklist_worker_args_not_list")

    summary_ready = summary.get("ready_for_design_partner") is True
    checklist_ready = checklist.get("ready_for_design_partner") is True
    checklist_pass = checklist.get("overall_status") == "pass"
    ready_for_design_partner = summary_ready and checklist_ready and checklist_pass
    if summary and checklist and summary_ready != checklist_ready:
        errors.append("preflight_ready_status_mismatch")
    if require_design_partner_ready and not ready_for_design_partner:
        errors.append("design_partner_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "preflight_payload_hash": expected_hash,
        "computed_payload_hash": computed_hash,
        "hash_valid": hash_valid,
        "output_path_matches_file": _output_path_matches_file(payload, path) if path else None,
        "summary_version": summary.get("summary_version"),
        "checklist_version": checklist.get("checklist_version"),
        "phase": summary.get("phase"),
        "exit_code": summary.get("exit_code"),
        "ready_for_design_partner": ready_for_design_partner,
        "recommended_next_action": summary.get("recommended_next_action"),
        "blocking_reasons": checklist.get("blocking_reasons", ()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a GEO provider preflight JSON payload")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_API_PREFLIGHT_OUTPUT_PATH", DEFAULT_PREFLIGHT_PATH),
        help="Path to the preflight JSON payload.",
    )
    parser.add_argument(
        "--require-design-partner-ready",
        action="store_true",
        help="Fail unless summary/checklist both prove the payload is ready for design-partner expansion.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["preflight_payload_file_missing"],
            "hash_valid": False,
            "ready_for_design_partner": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"preflight_payload_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "ready_for_design_partner": False,
        }
    else:
        result = verify_preflight_payload(
            payload,
            path=path,
            require_design_partner_ready=args.require_design_partner_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
