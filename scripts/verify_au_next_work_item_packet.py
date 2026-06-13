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

from scripts.build_au_next_work_item_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    PACKET_VERSION,
    compute_next_work_item_packet_hash,
)


REQUIRED_FIELDS = (
    "next_work_item_packet_version",
    "generated_at",
    "status",
    "next_work_item_packet_ready",
    "ready_for_customer_report_handoff",
    "output_path",
    "source_handoff_dossier",
    "handoff_dossier_verifier",
    "summary",
    "next_work_item",
    "commands",
    "verification_commands",
    "evidence_outputs",
    "runtime_endpoints",
    "hard_gate_commands",
    "evidence_sources",
    "next_work_item_packet_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def verify_au_next_work_item_packet(
    payload: Any,
    *,
    path: Path | None = None,
    require_customer_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["next_work_item_packet_not_json_object"],
            "hash_valid": False,
            "next_work_item_packet_ready": False,
            "ready_for_customer_report_handoff": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("next_work_item_packet_version") != PACKET_VERSION:
        errors.append("next_work_item_packet_version_invalid")

    expected_hash = payload.get("next_work_item_packet_hash")
    computed_hash = compute_next_work_item_packet_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("next_work_item_packet_hash_mismatch")

    source = _as_dict(payload.get("source_handoff_dossier"))
    verifier = _as_dict(payload.get("handoff_dossier_verifier"))
    summary = _as_dict(payload.get("summary"))
    next_work_item = _as_dict(payload.get("next_work_item"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    commands = _string_list(payload.get("commands"))
    verification_commands = _string_list(payload.get("verification_commands"))
    evidence_outputs = _string_list(payload.get("evidence_outputs"))
    blocked_customer_gate_ids = _string_list(summary.get("blocked_customer_gate_ids"))
    next_work_item_id = str(summary.get("next_work_item_id") or "")

    expected_ready = (
        verifier.get("status") == "pass"
        and verifier.get("hash_valid") is True
        and bool(next_work_item_id)
        and (next_work_item_id == "none" or next_work_item.get("id") == next_work_item_id)
    )
    if payload.get("next_work_item_packet_ready") is not expected_ready:
        errors.append("next_work_item_packet_ready_mismatch")
    if payload.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")
    if source.get("handoff_dossier_hash") != verifier.get("handoff_dossier_hash") and verifier.get(
        "handoff_dossier_hash"
    ):
        errors.append("source_handoff_dossier_hash_mismatch")
    if next_work_item_id != str(verifier.get("next_work_item_id") or ""):
        errors.append("summary_next_work_item_id_verifier_mismatch")
    if next_work_item_id != "none" and next_work_item.get("id") != next_work_item_id:
        errors.append("next_work_item_id_mismatch")
    if summary.get("stage") != str(next_work_item.get("stage") or ""):
        errors.append("summary_stage_mismatch")
    if summary.get("title") != str(next_work_item.get("title") or ""):
        errors.append("summary_title_mismatch")
    if summary.get("dependency_class") != str(next_work_item.get("dependency_class") or ""):
        errors.append("summary_dependency_class_mismatch")
    if summary.get("external_dependency") is not (next_work_item.get("external_dependency") is True):
        errors.append("summary_external_dependency_mismatch")
    if summary.get("blocker_count") != int(next_work_item.get("blocker_count") or 0):
        errors.append("summary_blocker_count_mismatch")
    if summary.get("remaining_blocker_count") != int(verifier.get("remaining_blocker_count") or 0):
        errors.append("summary_remaining_blocker_count_mismatch")
    if summary.get("command_count") != len(commands):
        errors.append("summary_command_count_mismatch")
    if summary.get("verification_command_count") != len(verification_commands):
        errors.append("summary_verification_command_count_mismatch")
    if summary.get("evidence_output_count") != len(evidence_outputs):
        errors.append("summary_evidence_output_count_mismatch")
    if summary.get("blocked_customer_gate_count") != len(blocked_customer_gate_ids):
        errors.append("summary_blocked_customer_gate_count_mismatch")
    if summary.get("runnable_now") is not bool(commands):
        errors.append("summary_runnable_now_mismatch")
    if next_work_item_id != "none":
        if not commands:
            errors.append("commands_empty_for_active_work_item")
        if not verification_commands:
            errors.append("verification_commands_empty_for_active_work_item")
        if not evidence_outputs:
            errors.append("evidence_outputs_empty_for_active_work_item")

    if endpoints.get("next_work_item") != "GET /v1/next-work-item/au":
        errors.append("runtime_endpoint_next_work_item_invalid")
    if endpoints.get("handoff_dossier") != "GET /v1/handoff-dossier/au":
        errors.append("runtime_endpoint_handoff_dossier_invalid")
    if endpoints.get("customer_handoff_readiness") != "GET /v1/customer-handoff-readiness/au":
        errors.append("runtime_endpoint_customer_handoff_readiness_invalid")

    hard_gate_commands = _string_list(payload.get("hard_gate_commands"))
    for required in (
        "make au-next-work-item",
        "make verify-au-next-work-item",
        "make verify-au-customer-handoff-readiness",
    ):
        if required not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{required}")
    if not any(command.endswith("--require-customer-ready") for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_customer_ready")
    for command in verification_commands:
        if command not in hard_gate_commands:
            errors.append(f"hard_gate_missing_verification_command:{command}")
    if require_customer_ready and payload.get("ready_for_customer_report_handoff") is not True:
        errors.append("customer_handoff_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "next_work_item_packet_version": payload.get("next_work_item_packet_version", ""),
        "next_work_item_packet_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_next_work_item_packet_hash": computed_hash,
        "hash_valid": hash_valid,
        "next_work_item_packet_ready": expected_ready,
        "ready_for_customer_report_handoff": payload.get("ready_for_customer_report_handoff") is True,
        "next_work_item_id": next_work_item_id,
        "remaining_blocker_count": summary.get("remaining_blocker_count", 0),
        "command_count": len(commands),
        "verification_command_count": len(verification_commands),
        "evidence_output_count": len(evidence_outputs),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU next work item packet JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_NEXT_WORK_ITEM_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU next work item packet JSON.",
    )
    parser.add_argument(
        "--require-customer-ready",
        action="store_true",
        help="Fail unless the upstream customer report handoff is ready.",
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
            "errors": ["next_work_item_packet_file_missing"],
            "hash_valid": False,
            "next_work_item_packet_ready": False,
            "ready_for_customer_report_handoff": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"next_work_item_packet_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "next_work_item_packet_ready": False,
            "ready_for_customer_report_handoff": False,
        }
    else:
        result = verify_au_next_work_item_packet(
            payload,
            path=path,
            require_customer_ready=args.require_customer_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
