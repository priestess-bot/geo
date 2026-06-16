from __future__ import annotations

import argparse
import hashlib
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
    EXECUTION_CONTEXT_VERSION,
    PACKET_VERSION,
    REQUEST_PACKET_CONTEXTS,
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
    "source_external_dependency_handoff",
    "handoff_dossier_verifier",
    "summary",
    "next_work_item",
    "execution_context",
    "commands",
    "verification_commands",
    "evidence_outputs",
    "runtime_endpoints",
    "hard_gate_commands",
    "evidence_sources",
    "next_work_item_packet_hash",
)

P0A_COMPLETION_CONTRACT_VERSION = "au_p0a_credential_request_completion_contract_v1"
P0A_CREDENTIAL_UPDATE_RECEIPT_ENDPOINT = "GET /v1/p0a-credential-update-receipt/au"
P0A_CREDENTIAL_UPDATE_RECEIPT_STRICT_GATE = (
    "PYTHONPATH=packages/geno_core:apps/api python3 "
    "scripts/verify_au_p0a_credential_update_receipt.py "
    "${GENO_AU_P0A_CREDENTIAL_UPDATE_RECEIPT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json} "
    "--require-complete"
)
P0A_POST_UPDATE_VALIDATION_COMMAND_COUNT = 13


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _unique_strings(values: list[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        if value and value not in items:
            items.append(value)
    return items


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _p0a_completion_context_from_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    summary = _as_dict(payload.get("summary"))
    completion_contract = _as_dict(payload.get("credential_update_completion_contract"))
    redaction_policy = _as_dict(completion_contract.get("redaction_policy"))
    runtime_endpoints = _as_dict(completion_contract.get("runtime_endpoints"))
    strict_gates = _string_list(completion_contract.get("strict_gate_commands"))
    receipt_strict_gate = str(summary.get("credential_update_receipt_strict_gate") or "")
    if not receipt_strict_gate and strict_gates:
        receipt_strict_gate = strict_gates[-1]
    return {
        "credential_update_completion_contract_ready": summary.get("credential_update_completion_contract_ready")
        is True,
        "credential_update_completion_contract_version": str(completion_contract.get("version") or ""),
        "credential_update_receipt_required": summary.get("credential_update_receipt_required") is True,
        "credential_update_receipt_ready_required": completion_contract.get("credential_update_receipt_ready_required")
        is True,
        "credential_update_receipt_complete_required": completion_contract.get(
            "credential_update_receipt_complete_required"
        )
        is True,
        "credential_update_receipt_endpoint": str(
            summary.get("credential_update_receipt_endpoint")
            or runtime_endpoints.get("p0a_credential_update_receipt")
            or ""
        ),
        "credential_update_receipt_strict_gate": receipt_strict_gate,
        "post_update_validation_command_count": int(
            summary.get("post_update_validation_command_count")
            or completion_contract.get("post_update_validation_command_count")
            or 0
        ),
        "completion_contract_required_missing_key_count": int(
            completion_contract.get("required_missing_key_count") or 0
        ),
        "completion_contract_required_missing_keys": _string_list(completion_contract.get("required_missing_keys")),
        "completion_contract_raw_secret_values_allowed": redaction_policy.get("raw_secret_values_allowed") is True,
        "completion_contract_raw_database_url_allowed": redaction_policy.get("raw_database_url_allowed") is True,
        "completion_contract_raw_provider_response_allowed": redaction_policy.get(
            "raw_provider_response_allowed"
        )
        is True,
    }


def verify_au_next_work_item_packet(
    payload: Any,
    *,
    path: Path | None = None,
    require_customer_ready: bool = False,
    verify_current_files: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["next_work_item_packet_not_json_object"],
            "hash_valid": False,
            "next_work_item_packet_ready": False,
            "ready_for_customer_report_handoff": False,
        }

    current_file_check_enabled = path is not None if verify_current_files is None else verify_current_files
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
    external_source = _as_dict(payload.get("source_external_dependency_handoff"))
    verifier = _as_dict(payload.get("handoff_dossier_verifier"))
    summary = _as_dict(payload.get("summary"))
    next_work_item = _as_dict(payload.get("next_work_item"))
    execution_context = _as_dict(payload.get("execution_context"))
    linked_request_packet = _as_dict(execution_context.get("linked_request_packet"))
    linked_dependency_group = _as_dict(execution_context.get("linked_dependency_group"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    commands = _string_list(payload.get("commands"))
    verification_commands = _string_list(payload.get("verification_commands"))
    evidence_outputs = _string_list(payload.get("evidence_outputs"))
    work_item_commands = _string_list(execution_context.get("work_item_commands"))
    work_item_verification_commands = _string_list(execution_context.get("work_item_verification_commands"))
    work_item_evidence_outputs = _string_list(execution_context.get("work_item_evidence_outputs"))
    group_commands = _string_list(execution_context.get("group_commands"))
    group_verification_commands = _string_list(execution_context.get("group_verification_commands"))
    group_evidence_outputs = _string_list(execution_context.get("group_evidence_outputs"))
    combined_commands = _string_list(execution_context.get("combined_commands"))
    combined_verification_commands = _string_list(execution_context.get("combined_verification_commands"))
    combined_evidence_outputs = _string_list(execution_context.get("combined_evidence_outputs"))
    expected_combined_commands = _unique_strings(group_commands + work_item_commands)
    expected_combined_verification_commands = _unique_strings(
        work_item_verification_commands + group_verification_commands
    )
    expected_combined_evidence_outputs = _unique_strings(work_item_evidence_outputs + group_evidence_outputs)
    recommended_sequence = _string_list(execution_context.get("recommended_sequence"))
    hard_gate_commands = _string_list(payload.get("hard_gate_commands"))
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
    if not external_source.get("path"):
        errors.append("source_external_dependency_handoff_path_missing")
    if not external_source.get("external_dependency_handoff_hash"):
        errors.append("source_external_dependency_handoff_hash_missing")
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
    if summary.get("work_item_command_count") != len(work_item_commands):
        errors.append("summary_work_item_command_count_mismatch")
    if summary.get("work_item_verification_command_count") != len(work_item_verification_commands):
        errors.append("summary_work_item_verification_command_count_mismatch")
    if summary.get("work_item_evidence_output_count") != len(work_item_evidence_outputs):
        errors.append("summary_work_item_evidence_output_count_mismatch")
    if summary.get("group_command_count") != len(group_commands):
        errors.append("summary_group_command_count_mismatch")
    if summary.get("group_verification_command_count") != len(group_verification_commands):
        errors.append("summary_group_verification_command_count_mismatch")
    if summary.get("group_evidence_output_count") != len(group_evidence_outputs):
        errors.append("summary_group_evidence_output_count_mismatch")
    if summary.get("blocked_customer_gate_count") != len(blocked_customer_gate_ids):
        errors.append("summary_blocked_customer_gate_count_mismatch")
    if summary.get("runnable_now") is not bool(commands):
        errors.append("summary_runnable_now_mismatch")
    if execution_context.get("execution_context_version") != EXECUTION_CONTEXT_VERSION:
        errors.append("execution_context_version_invalid")
    if execution_context.get("next_work_item_id") != next_work_item_id:
        errors.append("execution_context_next_work_item_id_mismatch")
    expected_context = REQUEST_PACKET_CONTEXTS.get(next_work_item_id)
    if expected_context:
        if execution_context.get("linked_dependency_group_id") != expected_context["linked_dependency_group_id"]:
            errors.append("execution_context_dependency_group_id_mismatch")
        if linked_dependency_group.get("id") != expected_context["linked_dependency_group_id"]:
            errors.append("execution_context_dependency_group_mismatch")
        if linked_dependency_group.get("source") != "external_dependency_handoff":
            errors.append("execution_context_dependency_group_source_mismatch")
        if linked_dependency_group.get("source_path") != external_source.get("path"):
            errors.append("execution_context_dependency_group_source_path_mismatch")
        if linked_dependency_group.get("source_external_dependency_handoff_hash") != external_source.get(
            "external_dependency_handoff_hash"
        ):
            errors.append("execution_context_dependency_group_source_hash_mismatch")
        if not linked_dependency_group.get("status"):
            errors.append("execution_context_dependency_group_status_missing")
        if int(linked_dependency_group.get("command_count") or 0) <= 0:
            errors.append("execution_context_dependency_group_commands_empty")
        if int(linked_dependency_group.get("command_count") or 0) != len(
            _string_list(linked_dependency_group.get("commands"))
        ):
            errors.append("execution_context_dependency_group_command_count_mismatch")
        if int(linked_dependency_group.get("verification_command_count") or 0) != len(
            _string_list(linked_dependency_group.get("verification_commands"))
        ):
            errors.append("execution_context_dependency_group_verification_command_count_mismatch")
        if int(linked_dependency_group.get("evidence_output_count") or 0) != len(
            _string_list(linked_dependency_group.get("evidence_outputs"))
        ):
            errors.append("execution_context_dependency_group_evidence_output_count_mismatch")
        if int(linked_dependency_group.get("blocking_reason_count") or 0) != len(
            _string_list(linked_dependency_group.get("blocking_reasons"))
        ):
            errors.append("execution_context_dependency_group_blocking_reason_count_mismatch")
        if linked_request_packet.get("request_packet_available") is not True:
            errors.append("linked_request_packet_not_available")
        for field in (
            "request_packet_id",
            "request_packet_title",
            "artifact_type",
            "hash_field",
            "build_command",
            "verify_command",
            "strict_gate_command",
            "runtime_endpoint",
        ):
            if linked_request_packet.get(field) != expected_context[field]:
                errors.append(f"linked_request_packet_{field}_mismatch")
        if summary.get("linked_dependency_group_id") != expected_context["linked_dependency_group_id"]:
            errors.append("summary_linked_dependency_group_id_mismatch")
        if summary.get("linked_dependency_group_status") != linked_dependency_group.get("status"):
            errors.append("summary_linked_dependency_group_status_mismatch")
        if summary.get("linked_dependency_group_next_command") != linked_dependency_group.get("next_command"):
            errors.append("summary_linked_dependency_group_next_command_mismatch")
        if summary.get("linked_dependency_group_blocking_reason_count") != int(
            linked_dependency_group.get("blocking_reason_count") or 0
        ):
            errors.append("summary_linked_dependency_group_blocking_reason_count_mismatch")
        if summary.get("linked_request_packet_id") != expected_context["request_packet_id"]:
            errors.append("summary_linked_request_packet_id_mismatch")
        if summary.get("linked_request_artifact_type") != expected_context["artifact_type"]:
            errors.append("summary_linked_request_artifact_type_mismatch")
        if summary.get("linked_request_packet_hash") != linked_request_packet.get("packet_hash"):
            errors.append("summary_linked_request_packet_hash_mismatch")
        if summary.get("linked_request_packet_exists") is not (linked_request_packet.get("exists") is True):
            errors.append("summary_linked_request_packet_exists_mismatch")
        if summary.get("request_packet_hash_available") is not bool(linked_request_packet.get("packet_hash")):
            errors.append("summary_request_packet_hash_available_mismatch")
        if expected_context["request_packet_id"] == "p0a_credential_request":
            required_completion_fields = (
                "credential_update_completion_contract_ready",
                "credential_update_completion_contract_version",
                "credential_update_receipt_required",
                "credential_update_receipt_ready_required",
                "credential_update_receipt_complete_required",
                "credential_update_receipt_endpoint",
                "credential_update_receipt_strict_gate",
                "post_update_validation_command_count",
                "completion_contract_required_missing_key_count",
                "completion_contract_required_missing_keys",
                "completion_contract_raw_secret_values_allowed",
                "completion_contract_raw_database_url_allowed",
                "completion_contract_raw_provider_response_allowed",
            )
            for field in required_completion_fields:
                if field not in linked_request_packet:
                    errors.append(f"linked_request_packet_completion_contract_field_missing:{field}")
            expected_completion_values = {
                "credential_update_completion_contract_ready": True,
                "credential_update_completion_contract_version": P0A_COMPLETION_CONTRACT_VERSION,
                "credential_update_receipt_required": True,
                "credential_update_receipt_ready_required": True,
                "credential_update_receipt_complete_required": True,
                "credential_update_receipt_endpoint": P0A_CREDENTIAL_UPDATE_RECEIPT_ENDPOINT,
                "credential_update_receipt_strict_gate": P0A_CREDENTIAL_UPDATE_RECEIPT_STRICT_GATE,
                "post_update_validation_command_count": P0A_POST_UPDATE_VALIDATION_COMMAND_COUNT,
                "completion_contract_raw_secret_values_allowed": False,
                "completion_contract_raw_database_url_allowed": False,
                "completion_contract_raw_provider_response_allowed": False,
            }
            for field, expected_value in expected_completion_values.items():
                if linked_request_packet.get(field) != expected_value:
                    errors.append(f"linked_request_packet_{field}_mismatch")
            if linked_request_packet.get("completion_contract_required_missing_key_count") != len(
                _string_list(linked_request_packet.get("completion_contract_required_missing_keys"))
            ):
                errors.append("linked_request_packet_completion_contract_missing_key_count_mismatch")
            summary_completion_field_map = {
                "linked_request_completion_contract_ready": "credential_update_completion_contract_ready",
                "linked_request_completion_contract_version": "credential_update_completion_contract_version",
                "linked_request_credential_update_receipt_required": "credential_update_receipt_required",
                "linked_request_credential_update_receipt_endpoint": "credential_update_receipt_endpoint",
                "linked_request_credential_update_receipt_strict_gate": "credential_update_receipt_strict_gate",
                "linked_request_post_update_validation_command_count": "post_update_validation_command_count",
                "linked_request_completion_contract_missing_required_count": "completion_contract_required_missing_key_count",
                "linked_request_completion_contract_raw_secret_values_allowed": "completion_contract_raw_secret_values_allowed",
            }
            for summary_field, linked_field in summary_completion_field_map.items():
                if summary_field not in summary:
                    errors.append(f"summary_completion_contract_field_missing:{summary_field}")
                if summary.get(summary_field) != linked_request_packet.get(linked_field):
                    errors.append(f"summary_{summary_field}_mismatch")
            receipt_strict_gate = str(linked_request_packet.get("credential_update_receipt_strict_gate") or "")
            if receipt_strict_gate and receipt_strict_gate not in recommended_sequence:
                errors.append("recommended_sequence_missing:p0a_credential_update_receipt_strict_gate")
            if receipt_strict_gate and receipt_strict_gate not in hard_gate_commands:
                errors.append("hard_gate_missing:p0a_credential_update_receipt_strict_gate")
        for command in (
            expected_context["build_command"],
            expected_context["verify_command"],
            expected_context["strict_gate_command"],
        ):
            if command not in recommended_sequence:
                errors.append(f"recommended_sequence_missing:{command}")
        if current_file_check_enabled:
            linked_output_path = Path(str(linked_request_packet.get("output_path") or expected_context["output_path"]))
            linked_file_exists = linked_output_path.is_file()
            if linked_request_packet.get("exists") is not linked_file_exists:
                errors.append("linked_request_packet_file_exists_mismatch")
            if linked_file_exists:
                current_payload = _load_json_file(linked_output_path)
                if not current_payload:
                    errors.append("linked_request_packet_current_json_invalid")
                else:
                    current_hash = str(current_payload.get(expected_context["hash_field"]) or "")
                    if not current_hash:
                        errors.append("linked_request_packet_current_hash_missing")
                    if linked_request_packet.get("packet_hash") != current_hash:
                        errors.append("linked_request_packet_current_hash_mismatch")
                    if summary.get("linked_request_packet_hash") != current_hash:
                        errors.append("summary_linked_request_packet_current_hash_mismatch")
                    if expected_context["request_packet_id"] == "p0a_credential_request":
                        current_completion_context = _p0a_completion_context_from_request_payload(current_payload)
                        current_summary_completion_field_map = {
                            "linked_request_completion_contract_ready": (
                                "credential_update_completion_contract_ready"
                            ),
                            "linked_request_completion_contract_version": (
                                "credential_update_completion_contract_version"
                            ),
                            "linked_request_credential_update_receipt_required": (
                                "credential_update_receipt_required"
                            ),
                            "linked_request_credential_update_receipt_endpoint": (
                                "credential_update_receipt_endpoint"
                            ),
                            "linked_request_credential_update_receipt_strict_gate": (
                                "credential_update_receipt_strict_gate"
                            ),
                            "linked_request_post_update_validation_command_count": (
                                "post_update_validation_command_count"
                            ),
                            "linked_request_completion_contract_missing_required_count": (
                                "completion_contract_required_missing_key_count"
                            ),
                            "linked_request_completion_contract_raw_secret_values_allowed": (
                                "completion_contract_raw_secret_values_allowed"
                            ),
                        }
                        for field, current_value in current_completion_context.items():
                            if linked_request_packet.get(field) != current_value:
                                errors.append(f"linked_request_packet_current_{field}_mismatch")
                        for summary_field, linked_field in current_summary_completion_field_map.items():
                            if summary.get(summary_field) != current_completion_context.get(linked_field):
                                errors.append(f"summary_current_{summary_field}_mismatch")
                current_file_sha256 = _file_sha256(linked_output_path)
                if linked_request_packet.get("file_sha256") != current_file_sha256:
                    errors.append("linked_request_packet_file_sha256_mismatch")
            elif linked_request_packet.get("packet_hash"):
                errors.append("linked_request_packet_hash_present_but_file_missing")
    elif next_work_item_id != "none":
        if linked_request_packet.get("request_packet_available") is True:
            errors.append("unexpected_linked_request_packet_available")
    if commands != expected_combined_commands:
        errors.append("top_level_commands_do_not_match_combined_execution_context")
    if verification_commands != expected_combined_verification_commands:
        errors.append("top_level_verification_commands_do_not_match_combined_execution_context")
    if evidence_outputs != expected_combined_evidence_outputs:
        errors.append("top_level_evidence_outputs_do_not_match_combined_execution_context")
    if combined_commands != expected_combined_commands:
        errors.append("execution_context_combined_commands_mismatch")
    if combined_verification_commands != expected_combined_verification_commands:
        errors.append("execution_context_combined_verification_commands_mismatch")
    if combined_evidence_outputs != expected_combined_evidence_outputs:
        errors.append("execution_context_combined_evidence_outputs_mismatch")
    if execution_context.get("group_command_count") != len(group_commands):
        errors.append("execution_context_group_command_count_mismatch")
    if execution_context.get("group_verification_command_count") != len(group_verification_commands):
        errors.append("execution_context_group_verification_command_count_mismatch")
    if execution_context.get("group_evidence_output_count") != len(group_evidence_outputs):
        errors.append("execution_context_group_evidence_output_count_mismatch")
    for command in expected_combined_commands + expected_combined_verification_commands:
        if command not in recommended_sequence:
            errors.append(f"recommended_sequence_missing_combined_command:{command}")
    if execution_context.get("recommended_sequence_count") != len(recommended_sequence):
        errors.append("execution_context_recommended_sequence_count_mismatch")
    if summary.get("recommended_sequence_count") != len(recommended_sequence):
        errors.append("summary_recommended_sequence_count_mismatch")
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
    for command in (
        str(linked_request_packet.get("build_command") or ""),
        str(linked_request_packet.get("verify_command") or ""),
        str(linked_request_packet.get("strict_gate_command") or ""),
    ):
        if command and command not in hard_gate_commands:
            errors.append(f"hard_gate_missing_linked_request_command:{command}")
    if require_customer_ready and payload.get("ready_for_customer_report_handoff") is not True:
        errors.append("customer_handoff_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "current_file_check_enabled": current_file_check_enabled,
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
        "linked_request_packet_id": str(linked_request_packet.get("request_packet_id") or ""),
        "linked_dependency_group_id": str(execution_context.get("linked_dependency_group_id") or ""),
        "linked_dependency_group_status": str(linked_dependency_group.get("status") or ""),
        "recommended_sequence_count": len(recommended_sequence),
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
