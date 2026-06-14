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

from scripts.build_au_delivery_progress import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    PROGRESS_GATES,
    PROGRESS_VERSION,
    compute_delivery_progress_hash,
)


REQUIRED_FIELDS = (
    "delivery_progress_version",
    "generated_at",
    "status",
    "delivery_progress_ready",
    "ready_for_customer_report_handoff",
    "output_path",
    "summary",
    "progress_gates",
    "source_artifacts",
    "verifiers",
    "runtime_endpoints",
    "hard_gate_commands",
    "evidence_sources",
    "delivery_progress_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _percent(ready_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return round((ready_count / total_count) * 100, 1)


def _progress_gate_lookup(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(gate.get("id") or ""): _as_dict(gate) for gate in _as_list(payload.get("progress_gates"))}


def verify_au_delivery_progress(
    payload: Any,
    *,
    path: Path | None = None,
    require_customer_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["delivery_progress_not_json_object"],
            "hash_valid": False,
            "delivery_progress_ready": False,
            "ready_for_customer_report_handoff": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("delivery_progress_version") != PROGRESS_VERSION:
        errors.append("delivery_progress_version_invalid")

    expected_hash = payload.get("delivery_progress_hash")
    computed_hash = compute_delivery_progress_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("delivery_progress_hash_mismatch")

    summary = _as_dict(payload.get("summary"))
    gates = [_as_dict(item) for item in _as_list(payload.get("progress_gates"))]
    gate_lookup = _progress_gate_lookup(payload)
    expected_gate_ids = [gate_id for gate_id, _, _ in PROGRESS_GATES]
    if [str(gate.get("id") or "") for gate in gates] != expected_gate_ids:
        errors.append("progress_gate_order_mismatch")
    ready_gate_count = len([gate for gate in gates if gate.get("ready") is True])
    blocked_gates = [gate for gate in gates if gate.get("ready") is not True]
    blocked_gate_ids = [str(gate.get("id") or "") for gate in blocked_gates]
    if summary.get("ready_progress_gate_count") != ready_gate_count:
        errors.append("summary_ready_progress_gate_count_mismatch")
    if summary.get("total_progress_gate_count") != len(gates):
        errors.append("summary_total_progress_gate_count_mismatch")
    if summary.get("blocked_progress_gate_count") != len(blocked_gates):
        errors.append("summary_blocked_progress_gate_count_mismatch")
    if summary.get("blocked_progress_gate_ids") != blocked_gate_ids:
        errors.append("summary_blocked_progress_gate_ids_mismatch")
    if summary.get("engineering_progress_percent") != _percent(ready_gate_count, len(gates)):
        errors.append("summary_engineering_progress_percent_mismatch")
    if require_customer_ready and payload.get("ready_for_customer_report_handoff") is not True:
        errors.append("customer_handoff_not_ready")

    verifiers = _as_dict(payload.get("verifiers"))
    launch_verifier = _as_dict(verifiers.get("launch_status"))
    required_pass_verifiers = (
        "handoff_dossier",
        "customer_handoff_readiness",
        "next_work_item",
        "external_dependency_handoff",
        "external_dependency_clearance",
    )
    expected_status_pass = launch_verifier.get("hash_valid") is True and all(
        _as_dict(verifiers.get(key)).get("status") == "pass" for key in required_pass_verifiers
    )
    if payload.get("status") != ("pass" if expected_status_pass else "fail"):
        errors.append("status_mismatch")
    if payload.get("delivery_progress_ready") is not True:
        errors.append("delivery_progress_ready_mismatch")

    source_artifacts = _as_dict(payload.get("source_artifacts"))
    for artifact_key, hash_field in (
        ("launch_status", "launch_status_hash"),
        ("handoff_dossier", "handoff_dossier_hash"),
        ("customer_handoff_readiness", "customer_handoff_readiness_hash"),
        ("next_work_item", "next_work_item_packet_hash"),
        ("external_dependency_handoff", "external_dependency_handoff_hash"),
        ("external_dependency_clearance", "clearance_execution_hash"),
    ):
        artifact = _as_dict(source_artifacts.get(artifact_key))
        if artifact.get("hash_field") != hash_field:
            errors.append(f"source_artifact_hash_field_mismatch:{artifact_key}")
        summary_key = hash_field if hash_field != "clearance_execution_hash" else "clearance_execution_hash"
        if summary.get(summary_key) != artifact.get("hash"):
            errors.append(f"source_artifact_hash_mismatch:{artifact_key}")
        if artifact.get("hash_valid") is not True:
            errors.append(f"source_artifact_hash_not_valid:{artifact_key}")

    if payload.get("ready_for_customer_report_handoff") is not (
        summary.get("customer_report_handoff_readiness_percent") == 100.0
        and gate_lookup.get("customer_report_handoff_ready", {}).get("ready") is True
    ):
        errors.append("ready_for_customer_report_handoff_mismatch")

    endpoints = _as_dict(payload.get("runtime_endpoints"))
    expected_endpoints = {
        "delivery_progress": "GET /v1/delivery-progress/au",
        "launch_status": "GET /v1/launch-status/au",
        "handoff_dossier": "GET /v1/handoff-dossier/au",
        "customer_handoff_readiness": "GET /v1/customer-handoff-readiness/au",
        "next_work_item": "GET /v1/next-work-item/au",
        "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
        "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
    }
    for key, endpoint in expected_endpoints.items():
        if endpoints.get(key) != endpoint:
            errors.append(f"runtime_endpoint_invalid:{key}")

    hard_gate_commands = [str(command) for command in _as_list(payload.get("hard_gate_commands"))]
    for command in (
        "make au-delivery-progress",
        "make verify-au-delivery-progress",
        "make verify-au-customer-handoff-readiness",
        "make verify-au-next-work-item",
    ):
        if command not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{command}")
    if not any(command.endswith("--require-customer-ready") for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_customer_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "delivery_progress_version": payload.get("delivery_progress_version", ""),
        "delivery_progress_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_delivery_progress_hash": computed_hash,
        "hash_valid": hash_valid,
        "delivery_progress_ready": payload.get("delivery_progress_ready") is True,
        "ready_for_customer_report_handoff": payload.get("ready_for_customer_report_handoff") is True,
        "engineering_progress_percent": summary.get("engineering_progress_percent", 0.0),
        "customer_report_handoff_readiness_percent": summary.get("customer_report_handoff_readiness_percent", 0.0),
        "structural_auditability_percent": summary.get("structural_auditability_percent", 0.0),
        "blocked_progress_gate_count": len(blocked_gates),
        "blocked_progress_gate_ids": blocked_gate_ids,
        "next_work_item_id": str(summary.get("next_work_item_id") or ""),
        "next_command": str(summary.get("next_command") or ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU delivery progress JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_DELIVERY_PROGRESS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU delivery progress JSON.",
    )
    parser.add_argument(
        "--require-customer-ready",
        action="store_true",
        help="Fail unless customer report handoff is ready.",
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
            "errors": ["delivery_progress_file_missing"],
            "hash_valid": False,
            "delivery_progress_ready": False,
            "ready_for_customer_report_handoff": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"delivery_progress_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "delivery_progress_ready": False,
            "ready_for_customer_report_handoff": False,
        }
    else:
        result = verify_au_delivery_progress(payload, path=path, require_customer_ready=args.require_customer_ready)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
