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

from scripts.build_au_p0b_google_phase_execution_clearance import (  # noqa: E402
    CLEARANCE_VERSION,
    DEFAULT_OUTPUT_PATH,
    PHASE_ORDER,
    PREREQUISITE_STEP_ID,
    STEP_ID,
    compute_p0b_google_phase_execution_clearance_hash,
)


REQUIRED_FIELDS = (
    "p0b_google_phase_execution_clearance_version",
    "generated_at",
    "status",
    "phase_execution_clearance_packet_ready",
    "phase_execution_fulfilled",
    "phase_execution_clearance_ready",
    "ready_for_next_clearance_step",
    "blocked_by_prerequisite_step",
    "output_path",
    "clearance_step",
    "prerequisite_step",
    "source_artifacts",
    "p0b_google_phase_execution_request_verifier",
    "p0b_google_execution_checklist_verifier",
    "p0b_google_phase_execution_fulfillment_verifier",
    "summary",
    "phase_execution_clearance_items",
    "operator_steps",
    "post_update_validation_sequence",
    "runtime_endpoints",
    "hard_gate_commands",
    "redaction_policy",
    "p0b_google_phase_execution_clearance_hash",
)
FORBIDDEN_PHASE_FIELDS = {
    "value",
    "raw_value",
    "answer_text",
    "answer",
    "raw_answer",
    "citation_urls",
    "citations",
    "raw_citation",
    "screenshot_url",
    "screenshot",
    "html_snapshot_url",
    "html_snapshot",
    "raw_asset_url",
    "database_url",
    "selector_value",
    "provider_response",
    "raw_provider_response",
    "token",
    "secret",
}


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
            if key in FORBIDDEN_PHASE_FIELDS:
                findings.append(child_path)
            findings.extend(_find_forbidden_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_fields(child, path=f"{path}[{index}]"))
    return findings


def _owner_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        owner = str(item.get("owner_hint") or "unknown")
        counts[owner] = counts.get(owner, 0) + 1
    return dict(sorted(counts.items()))


def _missing_by_owner(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for item in items:
        if item.get("required") is True and item.get("fulfilled") is not True:
            owner = str(item.get("owner_hint") or "unknown")
            owners.setdefault(owner, []).append(str(item.get("key") or ""))
    return {owner: sorted(keys) for owner, keys in sorted(owners.items())}


def _blocking_reasons(items: list[dict[str, Any]]) -> list[str]:
    return sorted(
        dict.fromkeys(
            f"{item.get('phase_id')}:{reason}"
            for item in items
            for reason in _strings(item.get("blocking_reasons"))
        )
    )


def verify_au_p0b_google_phase_execution_clearance(
    payload: Any,
    *,
    path: Path | None = None,
    require_cleared: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0b_google_phase_execution_clearance_not_json_object"],
            "hash_valid": False,
            "phase_execution_clearance_packet_ready": False,
            "phase_execution_clearance_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0b_google_phase_execution_clearance_version") != CLEARANCE_VERSION:
        errors.append("p0b_google_phase_execution_clearance_version_invalid")
    for forbidden_path in _find_forbidden_fields(payload):
        errors.append(f"forbidden_phase_payload_field:{forbidden_path}")

    expected_hash = payload.get("p0b_google_phase_execution_clearance_hash")
    computed_hash = compute_p0b_google_phase_execution_clearance_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0b_google_phase_execution_clearance_hash_mismatch")

    request_verifier = _as_dict(payload.get("p0b_google_phase_execution_request_verifier"))
    checklist_verifier = _as_dict(payload.get("p0b_google_execution_checklist_verifier"))
    fulfillment_verifier = _as_dict(payload.get("p0b_google_phase_execution_fulfillment_verifier"))
    source_artifacts = _as_dict(payload.get("source_artifacts"))
    request_source = _as_dict(source_artifacts.get("phase_execution_request"))
    checklist_source = _as_dict(source_artifacts.get("p0b_google_execution_checklist"))
    fulfillment_source = _as_dict(source_artifacts.get("phase_execution_fulfillment"))
    clearance_source = _as_dict(source_artifacts.get("external_dependency_clearance"))
    summary = _as_dict(payload.get("summary"))
    clearance_step = _as_dict(payload.get("clearance_step"))
    prerequisite_step = _as_dict(payload.get("prerequisite_step"))
    items = [_as_dict(item) for item in _as_list(payload.get("phase_execution_clearance_items"))]
    operator_steps = [_as_dict(item) for item in _as_list(payload.get("operator_steps"))]
    validation_sequence = _strings(payload.get("post_update_validation_sequence"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    hard_gate_commands = _strings(payload.get("hard_gate_commands"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))

    request_ok = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    checklist_ok = checklist_verifier.get("status") == "pass" and checklist_verifier.get("hash_valid") is True
    fulfillment_ok = fulfillment_verifier.get("status") == "pass" and fulfillment_verifier.get("hash_valid") is True
    clearance_ok = str(clearance_source.get("status") or "") in {"pass", ""}
    expected_packet_ready = request_ok and checklist_ok and fulfillment_ok and clearance_ok
    if payload.get("phase_execution_clearance_packet_ready") is not expected_packet_ready:
        errors.append("phase_execution_clearance_packet_ready_mismatch")
    if payload.get("status") != ("pass" if expected_packet_ready else "fail"):
        errors.append("status_mismatch")

    item_ids = [str(item.get("phase_id") or "") for item in items]
    if item_ids != PHASE_ORDER:
        errors.append("phase_execution_clearance_item_order_invalid")
    item_keys = {str(item.get("key") or "") for item in items}
    for phase_id in PHASE_ORDER:
        if f"phase:{phase_id}" not in item_keys:
            errors.append(f"phase_execution_clearance_item_missing:{phase_id}")

    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True)
    presence_mismatches = sorted(str(item.get("key") or "") for item in items if item.get("presence_mismatch") is True)
    phase_execution_fulfilled = (
        bool(required_items) and len(fulfilled_required) == len(required_items) and not presence_mismatches
    )
    blocked_by_prerequisite = prerequisite_step.get("ready") is not True
    expected_next_ready = phase_execution_fulfilled and not blocked_by_prerequisite
    expected_clearance_ready = (
        phase_execution_fulfilled and clearance_step.get("step_ready") is True and not blocked_by_prerequisite
    )
    if payload.get("phase_execution_fulfilled") is not phase_execution_fulfilled:
        errors.append("phase_execution_fulfilled_mismatch")
    if payload.get("blocked_by_prerequisite_step") is not blocked_by_prerequisite:
        errors.append("blocked_by_prerequisite_step_mismatch")
    if payload.get("ready_for_next_clearance_step") is not expected_next_ready:
        errors.append("ready_for_next_clearance_step_mismatch")
    if payload.get("phase_execution_clearance_ready") is not expected_clearance_ready:
        errors.append("phase_execution_clearance_ready_mismatch")
    if require_cleared and not expected_clearance_ready:
        errors.append("p0b_google_phase_execution_not_cleared")

    if clearance_step.get("id") != STEP_ID:
        errors.append("clearance_step_id_invalid")
    if prerequisite_step.get("id") != PREREQUISITE_STEP_ID:
        errors.append("prerequisite_step_id_invalid")
    if summary.get("target_clearance_step_id") != STEP_ID:
        errors.append("summary_target_clearance_step_id_invalid")
    if summary.get("prerequisite_step_id") != PREREQUISITE_STEP_ID:
        errors.append("summary_prerequisite_step_id_invalid")
    if summary.get("blocked_by_prerequisite_step") is not blocked_by_prerequisite:
        errors.append("summary_blocked_by_prerequisite_step_mismatch")

    if request_source.get("hash") != request_verifier.get("p0b_google_phase_execution_request_packet_hash"):
        errors.append("source_phase_execution_request_hash_mismatch")
    if checklist_source.get("hash") != checklist_verifier.get("google_execution_checklist_hash"):
        errors.append("source_p0b_google_execution_checklist_hash_mismatch")
    if fulfillment_source.get("hash") != fulfillment_verifier.get("p0b_google_phase_execution_fulfillment_hash"):
        errors.append("source_phase_execution_fulfillment_hash_mismatch")
    expected_hash_fields = {
        "phase_execution_request": "p0b_google_phase_execution_request_packet_hash",
        "p0b_google_execution_checklist": "google_execution_checklist_hash",
        "phase_execution_fulfillment": "p0b_google_phase_execution_fulfillment_hash",
        "external_dependency_clearance": "clearance_execution_hash",
    }
    for key, expected_field in expected_hash_fields.items():
        if _as_dict(source_artifacts.get(key)).get("hash_field") != expected_field:
            errors.append(f"source_hash_field_invalid:{key}")

    blocking_reasons = _blocking_reasons(items)
    if summary.get("required_count") != len(required_items):
        errors.append("summary_required_count_mismatch")
    if summary.get("fulfilled_required_count") != len(fulfilled_required):
        errors.append("summary_fulfilled_required_count_mismatch")
    if summary.get("missing_required_count") != len(missing_required):
        errors.append("summary_missing_required_count_mismatch")
    if sorted(_strings(summary.get("missing_required"))) != missing_required:
        errors.append("summary_missing_required_mismatch")
    if summary.get("presence_mismatch_count") != len(presence_mismatches):
        errors.append("summary_presence_mismatch_count_mismatch")
    if sorted(_strings(summary.get("presence_mismatches"))) != presence_mismatches:
        errors.append("summary_presence_mismatches_mismatch")
    if summary.get("owner_counts") != _owner_counts(items):
        errors.append("summary_owner_counts_mismatch")
    if summary.get("missing_required_by_owner") != _missing_by_owner(items):
        errors.append("summary_missing_required_by_owner_mismatch")
    if summary.get("blocking_reason_count") != len(blocking_reasons):
        errors.append("summary_blocking_reason_count_mismatch")
    if sorted(_strings(summary.get("blocking_reasons"))) != blocking_reasons:
        errors.append("summary_blocking_reasons_mismatch")
    if summary.get("phase_execution_fulfilled") is not phase_execution_fulfilled:
        errors.append("summary_phase_execution_fulfilled_mismatch")
    if summary.get("phase_execution_fulfillment_ready") is not (
        fulfillment_verifier.get("phase_execution_fulfillment_ready") is True
    ):
        errors.append("summary_phase_execution_fulfillment_ready_mismatch")
    if summary.get("phase_execution_request_ready") is not request_ok:
        errors.append("summary_phase_execution_request_ready_mismatch")
    if summary.get("execution_checklist_ready") is not checklist_ok:
        errors.append("summary_execution_checklist_ready_mismatch")
    if summary.get("source_checklist_hash_aligned") is not fulfillment_verifier.get("phase_execution_fulfillment_ready"):
        errors.append("summary_source_checklist_hash_aligned_mismatch")
    if summary.get("google_spike_phase_handoff_ready") is not phase_execution_fulfilled:
        errors.append("summary_google_spike_phase_handoff_ready_mismatch")
    if summary.get("phase_count") != len(items):
        errors.append("summary_phase_count_mismatch")
    if _strings(summary.get("phase_order")) != PHASE_ORDER:
        errors.append("summary_phase_order_invalid")
    if summary.get("ready_phase_count") != len(fulfilled_required):
        errors.append("summary_ready_phase_count_mismatch")
    if summary.get("blocked_phase_count") != len(required_items) - len(fulfilled_required):
        errors.append("summary_blocked_phase_count_mismatch")
    if summary.get("prerequisite_step_ready") is not (prerequisite_step.get("ready") is True):
        errors.append("summary_prerequisite_step_ready_mismatch")
    if summary.get("target_clearance_step_ready") is not (clearance_step.get("step_ready") is True):
        errors.append("summary_target_clearance_step_ready_mismatch")
    if summary.get("target_clearance_step_can_start") is not (clearance_step.get("step_can_start") is True):
        errors.append("summary_target_clearance_step_can_start_mismatch")
    if summary.get("phase_execution_clearance_ready") is not expected_clearance_ready:
        errors.append("summary_phase_execution_clearance_ready_mismatch")
    if summary.get("ready_for_next_clearance_step") is not expected_next_ready:
        errors.append("summary_ready_for_next_clearance_step_mismatch")
    if summary.get("operator_step_count") != len(operator_steps):
        errors.append("summary_operator_step_count_mismatch")
    if summary.get("post_update_validation_command_count") != len(validation_sequence):
        errors.append("summary_post_update_validation_command_count_mismatch")
    for field in (
        "raw_secret_values_allowed",
        "raw_answer_values_allowed",
        "raw_citation_values_allowed",
        "raw_asset_urls_allowed",
        "raw_provider_response_allowed",
    ):
        if summary.get(field) is not False:
            errors.append(f"summary_redaction_policy_invalid:{field}")

    required_step_ids = {
        "clear_p0b_google_manual_backfill",
        "refresh_phase_execution_request",
        "refresh_execution_checklist",
        "refresh_phase_execution_fulfillment",
        "apply_current_phase_fix",
        "verify_phase_execution_fulfillment",
        "run_strict_gate",
        "continue_clearance_sequence",
    }
    observed_step_ids = {str(step.get("id") or "") for step in operator_steps}
    for step_id in required_step_ids:
        if step_id not in observed_step_ids:
            errors.append(f"operator_step_missing:{step_id}")
    for step in operator_steps:
        if not isinstance(step.get("order"), int):
            errors.append(f"operator_step_order_invalid:{step.get('id')}")
        if not str(step.get("command") or ""):
            errors.append(f"operator_step_command_missing:{step.get('id')}")

    for item in items:
        key = str(item.get("key") or "")
        for field in (
            "phase_id",
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
            "evidence_outputs",
            "owner_hint",
            "source_request_field",
            "source_checklist_field",
            "blocking_reasons",
        ):
            if field not in item:
                errors.append(f"phase_execution_clearance_item_field_missing:{key}:{field}")
        expected_presence_mismatch = (item.get("request_ready") is not item.get("checklist_ready")) or (
            item.get("request_can_start") is not item.get("checklist_can_start")
        )
        if item.get("presence_mismatch") is not expected_presence_mismatch:
            errors.append(f"phase_execution_clearance_item_presence_mismatch_invalid:{key}")
        expected_fulfilled = (
            item.get("required") is True
            and item.get("request_ready") is True
            and item.get("checklist_ready") is True
            and not expected_presence_mismatch
        )
        if item.get("fulfilled") is not expected_fulfilled:
            errors.append(f"phase_execution_clearance_item_fulfilled_mismatch:{key}")
        if item.get("fulfilled") is True and _as_list(item.get("blocking_reasons")):
            errors.append(f"phase_execution_clearance_item_blocking_reasons_on_fulfilled:{key}")

    for command in (
        "make au-p0b-google-manual-backfill-clearance",
        "make verify-au-p0b-google-manual-backfill-clearance",
        "make au-p0b-google-phase-execution-request",
        "make verify-au-p0b-google-phase-execution-request",
        "make au-p0b-google-execution-checklist",
        "make verify-au-p0b-google-execution-checklist",
        "make au-p0b-google-phase-execution-fulfillment",
        "make verify-au-p0b-google-phase-execution-fulfillment",
    ):
        if command not in validation_sequence:
            errors.append(f"post_update_validation_command_missing:{command}")
        if command not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{command}")
    if not any("--require-google-phases-ready" in command for command in validation_sequence):
        errors.append("post_update_validation_missing_require_google_phases_ready")
    if not any("--require-google-main-scoring-ready" in command for command in validation_sequence):
        errors.append("post_update_validation_missing_require_google_main_scoring_ready")
    if not any("--require-fulfilled" in command for command in validation_sequence):
        errors.append("post_update_validation_missing_require_fulfilled")
    if not any("--require-cleared" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_cleared")

    expected_endpoints = {
        "p0b_google_phase_execution_clearance": "GET /v1/p0b-google-phase-execution-clearance/au",
        "p0b_google_phase_execution_fulfillment": "GET /v1/p0b-google-phase-execution-fulfillment/au",
        "p0b_google_phase_execution_request": "GET /v1/p0b-google-phase-execution-request/au",
        "p0b_google_execution_checklist": "GET /v1/p0b-google-execution-checklist/au",
        "p0b_google_manual_backfill_clearance": "GET /v1/p0b-google-manual-backfill-clearance/au",
        "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
        "customer_handoff_readiness": "GET /v1/customer-handoff-readiness/au",
        "delivery_progress": "GET /v1/delivery-progress/au",
    }
    for key, expected in expected_endpoints.items():
        if endpoints.get(key) != expected:
            errors.append(f"runtime_endpoint_invalid:{key}")
    for field in (
        "raw_secret_values_allowed",
        "raw_answer_values_allowed",
        "raw_citation_values_allowed",
        "raw_asset_urls_allowed",
        "raw_provider_response_allowed",
    ):
        if redaction_policy.get(field) is not False:
            errors.append(f"redaction_policy_invalid:{field}")
    if redaction_policy.get("phase_entries_reference_command_ids_and_artifact_paths_only") is not True:
        errors.append("redaction_policy_phase_reference_invalid")
    if redaction_policy.get("phase_records_reference_counts_hashes_commands_and_artifact_paths_only") is not True:
        errors.append("redaction_policy_phase_record_reference_invalid")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0b_google_phase_execution_clearance_version": payload.get(
            "p0b_google_phase_execution_clearance_version",
            "",
        ),
        "p0b_google_phase_execution_clearance_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0b_google_phase_execution_clearance_hash": computed_hash,
        "hash_valid": hash_valid,
        "phase_execution_clearance_packet_ready": expected_packet_ready,
        "phase_execution_clearance_ready": expected_clearance_ready,
        "phase_execution_fulfilled": phase_execution_fulfilled,
        "blocked_by_prerequisite_step": blocked_by_prerequisite,
        "missing_required_count": len(missing_required),
        "missing_required": missing_required,
        "next_phase": summary.get("next_phase", ""),
        "next_action": summary.get("next_action", ""),
        "next_command": summary.get("next_command", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google phase execution clearance JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google phase execution clearance JSON.",
    )
    parser.add_argument(
        "--require-cleared",
        action="store_true",
        help="Fail unless P0b Google phase execution is cleared.",
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
            "errors": ["p0b_google_phase_execution_clearance_file_missing"],
            "hash_valid": False,
            "phase_execution_clearance_packet_ready": False,
            "phase_execution_clearance_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0b_google_phase_execution_clearance_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "phase_execution_clearance_packet_ready": False,
            "phase_execution_clearance_ready": False,
        }
    else:
        result = verify_au_p0b_google_phase_execution_clearance(
            payload,
            path=path,
            require_cleared=args.require_cleared,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
