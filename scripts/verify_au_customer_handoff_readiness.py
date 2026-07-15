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

from scripts.build_au_customer_handoff_readiness import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    READINESS_VERSION,
    compute_customer_handoff_readiness_hash,
)
from scripts.build_au_handoff_dossier import CUSTOMER_HANDOFF_READINESS_AUDIT_VERSION  # noqa: E402
from scripts.au_trial_handoff import (  # noqa: E402
    TRIAL_FULL_BATCH_STATUS,
    TRIAL_GOOGLE_COVERAGE_MODE,
    TRIAL_HANDOFF_VERSION,
    TRIAL_GATE_ORDER,
    compact_trial_handoff_summary,
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _percent(ready_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return round((ready_count / total_count) * 100, 1)


def _ready_count(gates: list[dict[str, Any]]) -> int:
    return len([gate for gate in gates if gate.get("ready") is True])


def _blocked_gate_ids(gates: list[dict[str, Any]]) -> list[str]:
    return [str(gate.get("id") or "") for gate in gates if gate.get("ready") is not True]


REQUIRED_FIELDS = (
    "customer_handoff_readiness_version",
    "generated_at",
    "status",
    "readiness_audit_ready",
    "ready_for_customer_report_handoff",
    "ready_for_trial_customer_handoff",
    "output_path",
    "source_handoff_dossier",
    "handoff_dossier_verifier",
    "summary",
    "readiness_audit",
    "trial_handoff_audit",
    "runtime_endpoints",
    "hard_gate_commands",
    "evidence_sources",
    "customer_handoff_readiness_hash",
)


def verify_au_customer_handoff_readiness(
    payload: Any,
    *,
    path: Path | None = None,
    require_customer_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["customer_handoff_readiness_not_json_object"],
            "hash_valid": False,
            "readiness_audit_ready": False,
            "ready_for_customer_report_handoff": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("customer_handoff_readiness_version") != READINESS_VERSION:
        errors.append("customer_handoff_readiness_version_invalid")

    expected_hash = payload.get("customer_handoff_readiness_hash")
    computed_hash = compute_customer_handoff_readiness_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("customer_handoff_readiness_hash_mismatch")

    source = _as_dict(payload.get("source_handoff_dossier"))
    verifier = _as_dict(payload.get("handoff_dossier_verifier"))
    summary = _as_dict(payload.get("summary"))
    audit = _as_dict(payload.get("readiness_audit"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    customer_gates = [_as_dict(item) for item in _as_list(audit.get("customer_gates"))]
    structural_gates = [_as_dict(item) for item in _as_list(audit.get("structural_gates"))]
    customer_ready_count = _ready_count(customer_gates)
    structural_ready_count = _ready_count(structural_gates)
    blocked_gate_ids = _blocked_gate_ids(customer_gates)
    ready_for_customer = audit.get("customer_report_handoff_ready") is True
    expected_ready = (
        verifier.get("status") == "pass"
        and verifier.get("hash_valid") is True
        and audit.get("audit_version") == CUSTOMER_HANDOFF_READINESS_AUDIT_VERSION
    )

    if payload.get("readiness_audit_ready") is not expected_ready:
        errors.append("readiness_audit_ready_mismatch")
    if payload.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")
    if payload.get("ready_for_customer_report_handoff") is not ready_for_customer:
        errors.append("ready_for_customer_report_handoff_mismatch")
    if require_customer_ready and not ready_for_customer:
        errors.append("customer_handoff_not_ready")

    trial_audit = _as_dict(payload.get("trial_handoff_audit"))
    trial_summary = compact_trial_handoff_summary(trial_audit)
    if trial_audit.get("trial_handoff_version") != TRIAL_HANDOFF_VERSION:
        errors.append("trial_handoff_version_invalid")
    trial_gates = [_as_dict(gate) for gate in _as_list(trial_audit.get("trial_gates"))]
    if [str(gate.get("id") or "") for gate in trial_gates] != list(TRIAL_GATE_ORDER):
        errors.append("trial_gate_order_mismatch")
    ready_trial_gate_count = _ready_count(trial_gates)
    blocked_trial_gate_ids = _blocked_gate_ids(trial_gates)
    if trial_audit.get("trial_ready_gate_count") != ready_trial_gate_count:
        errors.append("trial_ready_gate_count_mismatch")
    if trial_audit.get("trial_total_gate_count") != len(trial_gates):
        errors.append("trial_total_gate_count_mismatch")
    if trial_audit.get("trial_blocked_gate_count") != len(blocked_trial_gate_ids):
        errors.append("trial_blocked_gate_count_mismatch")
    if trial_audit.get("trial_blocked_gate_ids") != blocked_trial_gate_ids:
        errors.append("trial_blocked_gate_ids_mismatch")
    if trial_audit.get("trial_customer_handoff_readiness_percent") != _percent(
        ready_trial_gate_count,
        len(trial_gates),
    ):
        errors.append("trial_customer_handoff_readiness_percent_mismatch")
    if payload.get("ready_for_trial_customer_handoff") is not trial_summary["ready_for_trial_customer_handoff"]:
        errors.append("ready_for_trial_customer_handoff_mismatch")
    for field, expected in trial_summary.items():
        if summary.get(field) != expected:
            errors.append(f"summary_{field}_mismatch")
    if summary.get("trial_google_coverage_mode") != TRIAL_GOOGLE_COVERAGE_MODE:
        errors.append("summary_trial_google_coverage_mode_invalid")
    if summary.get("trial_full_batch_required") is not False:
        errors.append("summary_trial_full_batch_required_invalid")
    if summary.get("trial_full_batch_status") != TRIAL_FULL_BATCH_STATUS:
        errors.append("summary_trial_full_batch_status_invalid")
    if source.get("handoff_dossier_hash") != verifier.get("handoff_dossier_hash") and verifier.get(
        "handoff_dossier_hash"
    ):
        errors.append("source_handoff_dossier_hash_mismatch")
    if audit.get("audit_version") != CUSTOMER_HANDOFF_READINESS_AUDIT_VERSION:
        errors.append("readiness_audit_version_invalid")

    if summary.get("customer_ready_gate_count") != customer_ready_count:
        errors.append("summary_customer_ready_gate_count_mismatch")
    if summary.get("customer_total_gate_count") != len(customer_gates):
        errors.append("summary_customer_total_gate_count_mismatch")
    if summary.get("blocked_customer_gate_count") != len(blocked_gate_ids):
        errors.append("summary_blocked_customer_gate_count_mismatch")
    if summary.get("blocked_customer_gate_ids") != blocked_gate_ids:
        errors.append("summary_blocked_customer_gate_ids_mismatch")
    if summary.get("customer_report_handoff_readiness_percent") != _percent(
        customer_ready_count,
        len(customer_gates),
    ):
        errors.append("summary_customer_readiness_percent_mismatch")
    if summary.get("structural_ready_gate_count") != structural_ready_count:
        errors.append("summary_structural_ready_gate_count_mismatch")
    if summary.get("structural_total_gate_count") != len(structural_gates):
        errors.append("summary_structural_total_gate_count_mismatch")
    if summary.get("structural_auditability_percent") != _percent(structural_ready_count, len(structural_gates)):
        errors.append("summary_structural_auditability_percent_mismatch")
    for key in (
        "next_work_item_id",
        "remaining_blocker_count",
        "external_dependency_blocker_count",
        "readiness_statement",
    ):
        if summary.get(key) != audit.get(key):
            errors.append(f"summary_{key}_mismatch")
    if endpoints.get("customer_handoff_readiness") != "GET /v1/customer-handoff-readiness/au":
        errors.append("runtime_endpoint_customer_handoff_readiness_invalid")
    if endpoints.get("handoff_dossier") != "GET /v1/handoff-dossier/au":
        errors.append("runtime_endpoint_handoff_dossier_invalid")
    hard_gate_commands = [str(command) for command in _as_list(payload.get("hard_gate_commands"))]
    if "make verify-au-customer-handoff-readiness" not in hard_gate_commands:
        errors.append("hard_gate_missing:make verify-au-customer-handoff-readiness")
    if not any(command.endswith("--require-customer-ready") for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_customer_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "customer_handoff_readiness_version": payload.get("customer_handoff_readiness_version", ""),
        "customer_handoff_readiness_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_customer_handoff_readiness_hash": computed_hash,
        "hash_valid": hash_valid,
        "readiness_audit_ready": expected_ready,
        "ready_for_customer_report_handoff": ready_for_customer,
        "ready_for_trial_customer_handoff": payload.get("ready_for_trial_customer_handoff") is True,
        "trial_handoff_version": str(summary.get("trial_handoff_version") or ""),
        "customer_report_handoff_readiness_percent": summary.get("customer_report_handoff_readiness_percent", 0.0),
        "structural_auditability_percent": summary.get("structural_auditability_percent", 0.0),
        "trial_customer_handoff_readiness_percent": summary.get("trial_customer_handoff_readiness_percent", 0.0),
        "trial_ready_gate_count": summary.get("trial_ready_gate_count"),
        "trial_total_gate_count": summary.get("trial_total_gate_count"),
        "trial_blocked_gate_count": summary.get("trial_blocked_gate_count"),
        "trial_blocked_gate_ids": _as_list(summary.get("trial_blocked_gate_ids")),
        "trial_google_coverage_mode": str(summary.get("trial_google_coverage_mode") or ""),
        "trial_full_batch_required": summary.get("trial_full_batch_required") is True,
        "trial_full_batch_status": str(summary.get("trial_full_batch_status") or ""),
        "blocked_customer_gate_count": len(blocked_gate_ids),
        "next_work_item_id": str(summary.get("next_work_item_id") or ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU customer handoff readiness JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_CUSTOMER_HANDOFF_READINESS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU customer handoff readiness JSON.",
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
            "errors": ["customer_handoff_readiness_file_missing"],
            "hash_valid": False,
            "readiness_audit_ready": False,
            "ready_for_customer_report_handoff": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"customer_handoff_readiness_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "readiness_audit_ready": False,
            "ready_for_customer_report_handoff": False,
        }
    else:
        result = verify_au_customer_handoff_readiness(
            payload,
            path=path,
            require_customer_ready=args.require_customer_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
