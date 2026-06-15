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

from scripts.build_au_p0a_real_batch_fulfillment import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    FULFILLMENT_VERSION,
    PHASE_ORDER,
    compute_p0a_real_batch_fulfillment_hash,
)
from scripts.verify_au_p0a_real_batch_request_packet import (  # noqa: E402
    EXPECTED_ARTIFACT_KEYS,
    EXPECTED_COMMAND_IDS,
    EXPECTED_GATE_IDS,
    EXPECTED_PLANNED_RUNS,
)


REQUIRED_FIELDS = (
    "p0a_real_batch_fulfillment_version",
    "generated_at",
    "status",
    "real_batch_fulfillment_ready",
    "real_batches_fulfilled",
    "real_batch_phase_handoff_ready",
    "ready_for_design_partner",
    "output_path",
    "source_p0a_real_batch_request",
    "source_p0a_execution_checklist",
    "p0a_real_batch_request_verifier",
    "p0a_execution_checklist_verifier",
    "summary",
    "real_batch_fulfillment_items",
    "phase_commands",
    "verification_commands",
    "evidence_outputs",
    "hard_gate_commands",
    "runtime_endpoints",
    "redaction_policy",
    "p0a_real_batch_fulfillment_hash",
)
FORBIDDEN_FIELDS = {"value", "raw_value", "database_url", "secret", "token"}


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _find_forbidden_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_FIELDS:
                findings.append(child_path)
            findings.extend(_find_forbidden_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_fields(child, path=f"{path}[{index}]"))
    return findings


def _missing_by_owner(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for item in items:
        if item.get("required") is True and item.get("fulfilled") is not True:
            owner = str(item.get("owner_hint") or "unknown")
            owners.setdefault(owner, []).append(str(item.get("key") or ""))
    return {owner: sorted(keys) for owner, keys in sorted(owners.items())}


def _owner_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        owner = str(item.get("owner_hint") or "unknown")
        counts[owner] = counts.get(owner, 0) + 1
    return dict(sorted(counts.items()))


def _next_phase(items: list[dict[str, Any]]) -> str:
    for item in items:
        if item.get("fulfilled") is not True:
            return str(item.get("phase_id") or "")
    return "complete"


def _phase_commands(items: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for item in items:
        commands.extend(_strings(item.get("commands")))
    return commands


def _evidence_outputs(items: list[dict[str, Any]]) -> list[str]:
    outputs: list[str] = []
    for item in items:
        outputs.extend(_strings(item.get("evidence_outputs")))
    return sorted(dict.fromkeys(outputs))


def verify_au_p0a_real_batch_fulfillment(
    payload: Any,
    *,
    path: Path | None = None,
    require_fulfilled: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0a_real_batch_fulfillment_not_json_object"],
            "hash_valid": False,
            "real_batch_fulfillment_ready": False,
            "real_batches_fulfilled": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0a_real_batch_fulfillment_version") != FULFILLMENT_VERSION:
        errors.append("p0a_real_batch_fulfillment_version_invalid")
    for forbidden_path in _find_forbidden_fields(payload):
        errors.append(f"forbidden_raw_field:{forbidden_path}")

    expected_hash = payload.get("p0a_real_batch_fulfillment_hash")
    computed_hash = compute_p0a_real_batch_fulfillment_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0a_real_batch_fulfillment_hash_mismatch")

    source_request = _as_dict(payload.get("source_p0a_real_batch_request"))
    source_checklist = _as_dict(payload.get("source_p0a_execution_checklist"))
    request_verifier = _as_dict(payload.get("p0a_real_batch_request_verifier"))
    checklist_verifier = _as_dict(payload.get("p0a_execution_checklist_verifier"))
    summary = _as_dict(payload.get("summary"))
    items = [_as_dict(item) for item in _as_list(payload.get("real_batch_fulfillment_items"))]
    phase_commands = _strings(payload.get("phase_commands"))
    verification_commands = _strings(payload.get("verification_commands"))
    evidence_outputs = _strings(payload.get("evidence_outputs"))
    hard_gate_commands = _strings(payload.get("hard_gate_commands"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))

    request_ok = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    checklist_ok = checklist_verifier.get("status") == "pass" and checklist_verifier.get("hash_valid") is True
    source_checklist_hash_aligned = source_request.get("source_p0a_execution_checklist_hash") == source_checklist.get(
        "p0a_execution_checklist_hash"
    )
    expected_ready = request_ok and checklist_ok and source_checklist_hash_aligned
    if payload.get("real_batch_fulfillment_ready") is not expected_ready:
        errors.append("real_batch_fulfillment_ready_mismatch")
    if payload.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")
    if source_request.get("p0a_real_batch_request_packet_hash") != request_verifier.get(
        "p0a_real_batch_request_packet_hash"
    ):
        errors.append("source_p0a_real_batch_request_hash_mismatch")
    if source_checklist.get("p0a_execution_checklist_hash") != checklist_verifier.get("p0a_execution_checklist_hash"):
        errors.append("source_p0a_execution_checklist_hash_mismatch")
    if not source_checklist_hash_aligned:
        errors.append("source_request_checklist_hash_not_aligned")

    item_ids = [str(item.get("phase_id") or "") for item in items]
    if item_ids != PHASE_ORDER:
        errors.append("real_batch_fulfillment_item_order_invalid")
    item_keys = {str(item.get("key") or "") for item in items}
    for phase_id in PHASE_ORDER:
        if f"phase:{phase_id}" not in item_keys:
            errors.append(f"real_batch_fulfillment_item_missing:{phase_id}")

    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True)
    mismatches = sorted(str(item.get("key") or "") for item in items if item.get("presence_mismatch") is True)
    real_batches_fulfilled = bool(required_items) and len(fulfilled_required) == len(required_items) and not mismatches
    blocking_reasons = sorted(
        dict.fromkeys(
            f"{item.get('phase_id')}:{reason}"
            for item in items
            for reason in _strings(item.get("blocking_reasons"))
        )
    )
    if payload.get("real_batches_fulfilled") is not real_batches_fulfilled:
        errors.append("real_batches_fulfilled_mismatch")
    if payload.get("real_batch_phase_handoff_ready") is not real_batches_fulfilled:
        errors.append("real_batch_phase_handoff_ready_mismatch")
    expected_design_partner = (
        real_batches_fulfilled
        and request_verifier.get("real_batch_phase_handoff_ready") is True
        and checklist_verifier.get("ready_for_design_partner") is True
    )
    if payload.get("ready_for_design_partner") is not expected_design_partner:
        errors.append("ready_for_design_partner_mismatch")
    if summary.get("real_batches_fulfilled") is not real_batches_fulfilled:
        errors.append("summary_real_batches_fulfilled_mismatch")
    if summary.get("real_batch_request_ready") is not request_ok:
        errors.append("summary_real_batch_request_ready_mismatch")
    if summary.get("execution_checklist_ready") is not checklist_ok:
        errors.append("summary_execution_checklist_ready_mismatch")
    if summary.get("source_checklist_hash_aligned") is not source_checklist_hash_aligned:
        errors.append("summary_source_checklist_hash_aligned_mismatch")
    expected_execution_plan_ready = (
        expected_ready
        and len(items) == len(PHASE_ORDER)
        and summary.get("total_planned_runs") == sum(EXPECTED_PLANNED_RUNS.values())
        and bool(phase_commands)
        and bool(evidence_outputs)
    )
    if summary.get("real_batch_execution_plan_ready") is not expected_execution_plan_ready:
        errors.append("summary_real_batch_execution_plan_ready_mismatch")
    if summary.get("real_batch_phase_handoff_ready") is not real_batches_fulfilled:
        errors.append("summary_real_batch_phase_handoff_ready_mismatch")
    if summary.get("ready_for_design_partner") is not expected_design_partner:
        errors.append("summary_ready_for_design_partner_mismatch")
    if summary.get("phase_count") != len(items):
        errors.append("summary_phase_count_mismatch")
    if _strings(summary.get("phase_order")) != PHASE_ORDER:
        errors.append("summary_phase_order_invalid")
    if summary.get("ready_phase_count") != len(fulfilled_required):
        errors.append("summary_ready_phase_count_mismatch")
    if summary.get("blocked_phase_count") != len(required_items) - len(fulfilled_required):
        errors.append("summary_blocked_phase_count_mismatch")
    if summary.get("next_phase") != _next_phase(items):
        errors.append("summary_next_phase_mismatch")
    if summary.get("total_planned_runs") != sum(EXPECTED_PLANNED_RUNS.values()):
        errors.append("summary_total_planned_runs_mismatch")
    if summary.get("required_count") != len(required_items):
        errors.append("summary_required_count_mismatch")
    if summary.get("fulfilled_required_count") != len(fulfilled_required):
        errors.append("summary_fulfilled_required_count_mismatch")
    if summary.get("missing_required_count") != len(missing_required):
        errors.append("summary_missing_required_count_mismatch")
    if sorted(_strings(summary.get("missing_required"))) != missing_required:
        errors.append("summary_missing_required_mismatch")
    if summary.get("presence_mismatch_count") != len(mismatches):
        errors.append("summary_presence_mismatch_count_mismatch")
    if sorted(_strings(summary.get("presence_mismatches"))) != mismatches:
        errors.append("summary_presence_mismatches_mismatch")
    if summary.get("owner_counts") != _owner_counts(items):
        errors.append("summary_owner_counts_mismatch")
    if summary.get("missing_required_by_owner") != _missing_by_owner(items):
        errors.append("summary_missing_required_by_owner_mismatch")
    if summary.get("blocking_reason_count") != len(blocking_reasons):
        errors.append("summary_blocking_reason_count_mismatch")
    if sorted(_strings(summary.get("blocking_reasons"))) != blocking_reasons:
        errors.append("summary_blocking_reasons_mismatch")
    if summary.get("command_count") != len(phase_commands):
        errors.append("summary_command_count_mismatch")
    if phase_commands != _phase_commands(items):
        errors.append("phase_commands_mismatch")
    if summary.get("evidence_output_count") != len(evidence_outputs):
        errors.append("summary_evidence_output_count_mismatch")
    if evidence_outputs != _evidence_outputs(items):
        errors.append("evidence_outputs_mismatch")
    if not isinstance(summary.get("strict_gate_command"), str) or "--require-fulfilled" not in summary.get(
        "strict_gate_command",
        "",
    ):
        errors.append("summary_strict_gate_command_missing")

    for item in items:
        phase_id = str(item.get("phase_id") or "")
        for field in (
            "key",
            "title",
            "required",
            "fulfilled",
            "request_ready",
            "checklist_ready",
            "request_can_start",
            "checklist_can_start",
            "presence_mismatch",
            "planned_runs",
            "command_ids",
            "commands",
            "artifact_keys",
            "prerequisite_gate_ids",
            "evidence_outputs",
            "owner_hint",
            "source_request_field",
            "source_checklist_field",
            "blocking_reasons",
        ):
            if field not in item:
                errors.append(f"real_batch_fulfillment_item_field_missing:{phase_id}:{field}")
        if set(_strings(item.get("command_ids"))) != EXPECTED_COMMAND_IDS.get(phase_id, set()):
            errors.append(f"real_batch_fulfillment_command_ids_mismatch:{phase_id}")
        if set(_strings(item.get("artifact_keys"))) != EXPECTED_ARTIFACT_KEYS.get(phase_id, set()):
            errors.append(f"real_batch_fulfillment_artifact_keys_mismatch:{phase_id}")
        if set(_strings(item.get("prerequisite_gate_ids"))) != EXPECTED_GATE_IDS.get(phase_id, set()):
            errors.append(f"real_batch_fulfillment_gate_ids_mismatch:{phase_id}")
        if item.get("planned_runs") != EXPECTED_PLANNED_RUNS.get(phase_id):
            errors.append(f"real_batch_fulfillment_planned_runs_mismatch:{phase_id}")
        expected_presence_mismatch = (item.get("request_ready") is not item.get("checklist_ready")) or (
            item.get("request_can_start") is not item.get("checklist_can_start")
        )
        if item.get("presence_mismatch") is not expected_presence_mismatch:
            errors.append(f"real_batch_fulfillment_presence_mismatch_invalid:{phase_id}")
        expected_fulfilled = (
            item.get("required") is True
            and item.get("request_ready") is True
            and item.get("checklist_ready") is True
            and not expected_presence_mismatch
        )
        if item.get("fulfilled") is not expected_fulfilled:
            errors.append(f"real_batch_fulfillment_item_fulfilled_mismatch:{phase_id}")
        if item.get("fulfilled") is True and _as_list(item.get("blocking_reasons")):
            errors.append(f"real_batch_fulfillment_blocking_reasons_on_fulfilled:{phase_id}")

    for command in (
        "make au-p0a-real-batch-request",
        "make verify-au-p0a-real-batch-request",
        "make au-p0a-execution-checklist",
        "make verify-au-p0a-execution-checklist",
        "make verify-au-p0a-real-batch-fulfillment",
    ):
        if command not in verification_commands:
            errors.append(f"verification_command_missing:{command}")
    if "make verify-au-p0a-real-batch-fulfillment" not in hard_gate_commands:
        errors.append("hard_gate_missing:make verify-au-p0a-real-batch-fulfillment")
    if not any("--require-fulfilled" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_fulfilled")
    if not any("--require-real-batches-ready" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_real_batches_ready")
    if not any("--require-design-partner-ready" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_design_partner_ready")
    if endpoints.get("p0a_real_batch_fulfillment") != "GET /v1/p0a-real-batch-fulfillment/au":
        errors.append("runtime_endpoint_p0a_real_batch_fulfillment_invalid")
    if endpoints.get("p0a_real_batch_request") != "GET /v1/p0a-real-batch-request/au":
        errors.append("runtime_endpoint_p0a_real_batch_request_invalid")
    if endpoints.get("p0a_execution_checklist") != "GET /v1/p0a-execution-checklist/au":
        errors.append("runtime_endpoint_p0a_execution_checklist_invalid")
    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("redaction_policy_raw_secret_invalid")
    if redaction_policy.get("phase_entries_reference_command_ids_and_artifact_paths_only") is not True:
        errors.append("redaction_policy_phase_reference_invalid")
    if require_fulfilled and not real_batches_fulfilled:
        errors.append("p0a_real_batches_not_fulfilled")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0a_real_batch_fulfillment_version": payload.get("p0a_real_batch_fulfillment_version", ""),
        "p0a_real_batch_fulfillment_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0a_real_batch_fulfillment_hash": computed_hash,
        "hash_valid": hash_valid,
        "real_batch_fulfillment_ready": expected_ready,
        "real_batches_fulfilled": real_batches_fulfilled,
        "ready_for_design_partner": expected_design_partner,
        "real_batch_execution_plan_ready": summary.get("real_batch_execution_plan_ready") is True,
        "next_phase": summary.get("next_phase", ""),
        "total_planned_runs": summary.get("total_planned_runs"),
        "ready_phase_count": summary.get("ready_phase_count"),
        "blocked_phase_count": summary.get("blocked_phase_count"),
        "command_count": summary.get("command_count"),
        "evidence_output_count": summary.get("evidence_output_count"),
        "missing_required_count": len(missing_required),
        "missing_required": missing_required,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0a real batch fulfillment JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0A_REAL_BATCH_FULFILLMENT_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0a real batch fulfillment JSON.",
    )
    parser.add_argument("--require-fulfilled", action="store_true", help="Fail unless P0a real batches are fulfilled.")
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
            "errors": ["p0a_real_batch_fulfillment_file_missing"],
            "hash_valid": False,
            "real_batch_fulfillment_ready": False,
            "real_batches_fulfilled": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0a_real_batch_fulfillment_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "real_batch_fulfillment_ready": False,
            "real_batches_fulfilled": False,
        }
    else:
        result = verify_au_p0a_real_batch_fulfillment(
            payload,
            path=path,
            require_fulfilled=args.require_fulfilled,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
