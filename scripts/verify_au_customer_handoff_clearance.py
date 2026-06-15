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

from scripts.build_au_customer_handoff_clearance import (  # noqa: E402
    CLEARANCE_VERSION,
    DEFAULT_OUTPUT_PATH,
    EXPECTED_CUSTOMER_GATE_ORDER,
    PREREQUISITE_STEP_IDS,
    STEP_ID,
    compute_customer_handoff_clearance_hash,
)


REQUIRED_FIELDS = (
    "customer_handoff_clearance_version",
    "generated_at",
    "status",
    "customer_handoff_clearance_packet_ready",
    "customer_handoff_ready",
    "customer_handoff_clearance_ready",
    "ready_for_report_export_handoff",
    "blocked_by_prerequisite_step",
    "output_path",
    "clearance_step",
    "prerequisite_steps",
    "source_artifacts",
    "verifiers",
    "summary",
    "customer_handoff_clearance_items",
    "operator_steps",
    "post_update_validation_sequence",
    "runtime_endpoints",
    "hard_gate_commands",
    "evidence_sources",
    "redaction_policy",
    "customer_handoff_clearance_hash",
)

FORBIDDEN_CUSTOMER_FIELDS = {
    "value",
    "raw_value",
    "database_url",
    "selector_value",
    "answer_text",
    "answer",
    "raw_answer",
    "citation_urls",
    "citations",
    "screenshot_url",
    "html_snapshot_url",
    "raw_asset_url",
    "provider_response",
    "raw_provider_response",
    "token",
    "secret",
}


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


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


def _evidence_source_lookup(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("name") or ""): _as_dict(item) for item in _as_list(payload.get("evidence_sources"))}


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _find_forbidden_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_CUSTOMER_FIELDS:
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
            f"{item.get('gate_id')}:{reason}"
            for item in items
            for reason in _strings(item.get("blocking_reasons"))
        )
    )


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def verify_au_customer_handoff_clearance(
    payload: Any,
    *,
    path: Path | None = None,
    require_cleared: bool = False,
    verify_current_files: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["customer_handoff_clearance_not_json_object"],
            "hash_valid": False,
            "customer_handoff_clearance_packet_ready": False,
            "customer_handoff_clearance_ready": False,
        }

    current_file_check_enabled = path is not None if verify_current_files is None else verify_current_files
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("customer_handoff_clearance_version") != CLEARANCE_VERSION:
        errors.append("customer_handoff_clearance_version_invalid")
    for forbidden_path in _find_forbidden_fields(payload):
        errors.append(f"forbidden_customer_payload_field:{forbidden_path}")

    expected_hash = payload.get("customer_handoff_clearance_hash")
    computed_hash = compute_customer_handoff_clearance_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("customer_handoff_clearance_hash_mismatch")

    verifiers = _as_dict(payload.get("verifiers"))
    handoff_verifier = _as_dict(verifiers.get("handoff_dossier"))
    readiness_verifier = _as_dict(verifiers.get("customer_handoff_readiness"))
    progress_verifier = _as_dict(verifiers.get("delivery_progress"))
    external_handoff_verifier = _as_dict(verifiers.get("external_dependency_handoff"))
    external_clearance_verifier = _as_dict(verifiers.get("external_dependency_clearance"))
    p0a_credential_clearance_verifier = _as_dict(verifiers.get("p0a_credential_clearance"))
    p0a_credential_update_receipt_verifier = _as_dict(verifiers.get("p0a_credential_update_receipt"))
    p0a_real_batch_clearance_verifier = _as_dict(verifiers.get("p0a_real_batch_clearance"))
    p0b_google_environment_clearance_verifier = _as_dict(verifiers.get("p0b_google_environment_clearance"))
    p0b_google_manual_backfill_clearance_verifier = _as_dict(verifiers.get("p0b_google_manual_backfill_clearance"))
    p0b_google_phase_execution_clearance_verifier = _as_dict(verifiers.get("p0b_google_phase_execution_clearance"))
    source_artifacts = _as_dict(payload.get("source_artifacts"))
    evidence_sources = _evidence_source_lookup(payload)
    summary = _as_dict(payload.get("summary"))
    clearance_step = _as_dict(payload.get("clearance_step"))
    prerequisite_steps = [_as_dict(item) for item in _as_list(payload.get("prerequisite_steps"))]
    items = [_as_dict(item) for item in _as_list(payload.get("customer_handoff_clearance_items"))]
    operator_steps = [_as_dict(item) for item in _as_list(payload.get("operator_steps"))]
    validation_sequence = _strings(payload.get("post_update_validation_sequence"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    hard_gate_commands = _strings(payload.get("hard_gate_commands"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))

    source_to_verifier_hash = {
        "handoff_dossier": ("handoff_dossier_hash", handoff_verifier),
        "customer_handoff_readiness": ("customer_handoff_readiness_hash", readiness_verifier),
        "delivery_progress": ("delivery_progress_hash", progress_verifier),
        "external_dependency_handoff": ("external_dependency_handoff_hash", external_handoff_verifier),
        "external_dependency_clearance": ("clearance_execution_hash", external_clearance_verifier),
        "p0a_credential_clearance": ("p0a_credential_clearance_hash", p0a_credential_clearance_verifier),
        "p0a_credential_update_receipt": (
            "p0a_credential_update_receipt_hash",
            p0a_credential_update_receipt_verifier,
        ),
        "p0a_real_batch_clearance": ("p0a_real_batch_clearance_hash", p0a_real_batch_clearance_verifier),
        "p0b_google_environment_clearance": (
            "p0b_google_environment_clearance_hash",
            p0b_google_environment_clearance_verifier,
        ),
        "p0b_google_manual_backfill_clearance": (
            "p0b_google_manual_backfill_clearance_hash",
            p0b_google_manual_backfill_clearance_verifier,
        ),
        "p0b_google_phase_execution_clearance": (
            "p0b_google_phase_execution_clearance_hash",
            p0b_google_phase_execution_clearance_verifier,
        ),
    }
    for key, (hash_field, verifier) in source_to_verifier_hash.items():
        source = _as_dict(source_artifacts.get(key))
        if source.get("hash_field") != hash_field:
            errors.append(f"source_hash_field_invalid:{key}")
        if source.get("hash") != verifier.get(hash_field):
            errors.append(f"source_hash_mismatch:{key}")
        if source.get("hash_valid") is not True:
            errors.append(f"source_hash_not_valid:{key}")
        if source.get("verifier_status") != verifier.get("status"):
            errors.append(f"source_verifier_status_mismatch:{key}")
        if summary.get(hash_field) != source.get("hash"):
            errors.append(f"summary_source_hash_mismatch:{key}")
        if current_file_check_enabled:
            source_path = Path(str(source.get("path") or ""))
            source_metadata = _as_dict(source.get("source"))
            source_declares_existing = source_metadata.get("exists") is True or (
                source_metadata.get("source") == "existing_file"
            )
            if source_path.is_file():
                current_payload = _load_json_file(source_path)
                if not current_payload:
                    errors.append(f"source_artifact_current_json_invalid:{key}")
                else:
                    current_hash = str(current_payload.get(hash_field) or "")
                    if not current_hash:
                        errors.append(f"source_artifact_current_hash_missing:{key}")
                    if source.get("hash") != current_hash:
                        errors.append(f"source_artifact_current_hash_mismatch:{key}")
                    if summary.get(hash_field) != current_hash:
                        errors.append(f"summary_source_artifact_current_hash_mismatch:{key}")
                evidence_source = _as_dict(evidence_sources.get(key))
                current_file_sha256 = _file_sha256(source_path)
                if evidence_source.get("file_sha256") and evidence_source.get("file_sha256") != current_file_sha256:
                    errors.append(f"evidence_source_file_sha256_mismatch:{key}")
            elif source_declares_existing:
                errors.append(f"source_artifact_file_missing:{key}")

    expected_packet_ready = all(
        verifier.get("status") == "pass" and verifier.get("hash_valid") is True
        for verifier in (
            handoff_verifier,
            readiness_verifier,
            progress_verifier,
            external_handoff_verifier,
            external_clearance_verifier,
            p0a_credential_clearance_verifier,
            p0a_credential_update_receipt_verifier,
            p0a_real_batch_clearance_verifier,
            p0b_google_environment_clearance_verifier,
            p0b_google_manual_backfill_clearance_verifier,
            p0b_google_phase_execution_clearance_verifier,
        )
    )
    if payload.get("customer_handoff_clearance_packet_ready") is not expected_packet_ready:
        errors.append("customer_handoff_clearance_packet_ready_mismatch")
    if payload.get("status") != ("pass" if expected_packet_ready else "fail"):
        errors.append("status_mismatch")

    gate_ids = [str(item.get("gate_id") or "") for item in items]
    if tuple(gate_ids) != EXPECTED_CUSTOMER_GATE_ORDER:
        errors.append("customer_handoff_clearance_item_order_invalid")
    for item in items:
        key = str(item.get("key") or "")
        for field in (
            "gate_id",
            "title",
            "stage",
            "required",
            "fulfilled",
            "ready",
            "status",
            "evidence_ref",
            "next_action",
            "owner_hint",
            "blocking_reasons",
        ):
            if field not in item:
                errors.append(f"customer_handoff_clearance_item_field_missing:{key}:{field}")
        if item.get("key") != f"customer_gate:{item.get('gate_id')}":
            errors.append(f"customer_handoff_clearance_item_key_invalid:{key}")
        if item.get("fulfilled") is not (item.get("required") is True and item.get("ready") is True):
            errors.append(f"customer_handoff_clearance_item_fulfilled_mismatch:{key}")
        if item.get("ready") is True and _as_list(item.get("blocking_reasons")):
            errors.append(f"customer_handoff_clearance_item_blocking_reasons_on_ready:{key}")

    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True)
    blocking_reasons = _blocking_reasons(items)
    customer_handoff_ready = bool(required_items) and len(fulfilled_required) == len(required_items)
    if payload.get("customer_handoff_ready") is not customer_handoff_ready:
        errors.append("customer_handoff_ready_mismatch")
    if summary.get("customer_handoff_ready") is not customer_handoff_ready:
        errors.append("summary_customer_handoff_ready_mismatch")

    prerequisite_ids = [str(step.get("id") or "") for step in prerequisite_steps]
    if tuple(prerequisite_ids) != PREREQUISITE_STEP_IDS:
        errors.append("prerequisite_step_order_invalid")
    prerequisite_steps_ready = all(step.get("ready") is True for step in prerequisite_steps)
    blocked_by_prerequisite = not prerequisite_steps_ready
    expected_clearance_ready = (
        customer_handoff_ready
        and progress_verifier.get("ready_for_customer_report_handoff") is True
        and external_handoff_verifier.get("external_dependency_handoff_ready") is True
        and clearance_step.get("step_ready") is True
        and prerequisite_steps_ready
    )
    expected_report_ready = expected_packet_ready and expected_clearance_ready
    if payload.get("blocked_by_prerequisite_step") is not blocked_by_prerequisite:
        errors.append("blocked_by_prerequisite_step_mismatch")
    if payload.get("customer_handoff_clearance_ready") is not expected_clearance_ready:
        errors.append("customer_handoff_clearance_ready_mismatch")
    if payload.get("ready_for_report_export_handoff") is not expected_report_ready:
        errors.append("ready_for_report_export_handoff_mismatch")
    if require_cleared and not expected_clearance_ready:
        errors.append("customer_handoff_not_cleared")

    if clearance_step.get("id") != STEP_ID:
        errors.append("clearance_step_id_invalid")
    if summary.get("target_clearance_step_id") != STEP_ID:
        errors.append("summary_target_clearance_step_id_invalid")
    if _strings(summary.get("prerequisite_step_ids")) != list(PREREQUISITE_STEP_IDS):
        errors.append("summary_prerequisite_step_ids_invalid")
    if summary.get("blocked_by_prerequisite_step") is not blocked_by_prerequisite:
        errors.append("summary_blocked_by_prerequisite_step_mismatch")
    if summary.get("prerequisite_steps_ready") is not prerequisite_steps_ready:
        errors.append("summary_prerequisite_steps_ready_mismatch")
    if summary.get("target_clearance_step_ready") is not (clearance_step.get("step_ready") is True):
        errors.append("summary_target_clearance_step_ready_mismatch")
    if summary.get("target_clearance_step_can_start") is not (clearance_step.get("step_can_start") is True):
        errors.append("summary_target_clearance_step_can_start_mismatch")
    if summary.get("customer_handoff_clearance_ready") is not expected_clearance_ready:
        errors.append("summary_customer_handoff_clearance_ready_mismatch")
    if summary.get("ready_for_report_export_handoff") is not expected_report_ready:
        errors.append("summary_ready_for_report_export_handoff_mismatch")
    if summary.get("p0a_credential_clearance_ready") is not (
        p0a_credential_clearance_verifier.get("credential_clearance_ready") is True
    ):
        errors.append("summary_p0a_credential_clearance_ready_mismatch")
    if summary.get("p0a_credentials_fulfilled") is not (
        p0a_credential_clearance_verifier.get("credentials_fulfilled") is True
    ):
        errors.append("summary_p0a_credentials_fulfilled_mismatch")
    if summary.get("p0a_credential_missing_required_count") != p0a_credential_clearance_verifier.get(
        "missing_required_count"
    ):
        errors.append("summary_p0a_credential_missing_required_count_mismatch")
    if summary.get("p0a_credential_update_receipt_ready") is not (
        p0a_credential_update_receipt_verifier.get("credential_update_receipt_ready") is True
    ):
        errors.append("summary_p0a_credential_update_receipt_ready_mismatch")
    if summary.get("p0a_credential_update_receipt_complete") is not (
        p0a_credential_update_receipt_verifier.get("credential_update_receipt_complete") is True
    ):
        errors.append("summary_p0a_credential_update_receipt_complete_mismatch")
    if summary.get("p0a_credential_update_receipt_missing_required_count") != (
        p0a_credential_update_receipt_verifier.get("missing_required_count")
    ):
        errors.append("summary_p0a_credential_update_receipt_missing_required_count_mismatch")
    if summary.get("p0a_credential_update_env_file_hygiene_ready") is not (
        p0a_credential_update_receipt_verifier.get("env_file_hygiene_ready") is True
    ):
        errors.append("summary_p0a_credential_update_env_file_hygiene_ready_mismatch")
    if summary.get("p0a_real_batch_clearance_ready") is not (
        p0a_real_batch_clearance_verifier.get("real_batch_clearance_ready") is True
    ):
        errors.append("summary_p0a_real_batch_clearance_ready_mismatch")
    if summary.get("p0a_real_batches_fulfilled") is not (
        p0a_real_batch_clearance_verifier.get("real_batches_fulfilled") is True
    ):
        errors.append("summary_p0a_real_batches_fulfilled_mismatch")
    if summary.get("p0a_real_batch_blocked_by_prerequisite") is not (
        p0a_real_batch_clearance_verifier.get("blocked_by_prerequisite_step") is True
    ):
        errors.append("summary_p0a_real_batch_blocked_by_prerequisite_mismatch")
    if summary.get("p0a_real_batch_missing_required_count") != p0a_real_batch_clearance_verifier.get(
        "missing_required_count"
    ):
        errors.append("summary_p0a_real_batch_missing_required_count_mismatch")
    if summary.get("p0b_google_environment_clearance_ready") is not (
        p0b_google_environment_clearance_verifier.get("environment_clearance_ready") is True
    ):
        errors.append("summary_p0b_google_environment_clearance_ready_mismatch")
    if summary.get("p0b_google_environment_fulfilled") is not (
        p0b_google_environment_clearance_verifier.get("environment_fulfilled") is True
    ):
        errors.append("summary_p0b_google_environment_fulfilled_mismatch")
    if summary.get("p0b_google_environment_missing_required_count") != (
        p0b_google_environment_clearance_verifier.get("missing_required_count")
    ):
        errors.append("summary_p0b_google_environment_missing_required_count_mismatch")
    if summary.get("p0b_google_manual_backfill_clearance_ready") is not (
        p0b_google_manual_backfill_clearance_verifier.get("manual_backfill_clearance_ready") is True
    ):
        errors.append("summary_p0b_google_manual_backfill_clearance_ready_mismatch")
    if summary.get("p0b_google_manual_backfill_fulfilled") is not (
        p0b_google_manual_backfill_clearance_verifier.get("manual_backfill_fulfilled") is True
    ):
        errors.append("summary_p0b_google_manual_backfill_fulfilled_mismatch")
    if summary.get("p0b_google_manual_backfill_missing_required_count") != (
        p0b_google_manual_backfill_clearance_verifier.get("missing_required_count")
    ):
        errors.append("summary_p0b_google_manual_backfill_missing_required_count_mismatch")
    if summary.get("p0b_google_manual_backfill_ready") is not (
        p0b_google_manual_backfill_clearance_verifier.get("manual_backfill_ready") is True
    ):
        errors.append("summary_p0b_google_manual_backfill_ready_mismatch")
    if summary.get("p0b_google_manual_backfill_coverage_complete") is not (
        p0b_google_manual_backfill_clearance_verifier.get("manual_backfill_coverage_complete") is True
    ):
        errors.append("summary_p0b_google_manual_backfill_coverage_complete_mismatch")
    if summary.get("p0b_google_manual_backfill_content_complete") is not (
        p0b_google_manual_backfill_clearance_verifier.get("manual_backfill_content_complete") is True
    ):
        errors.append("summary_p0b_google_manual_backfill_content_complete_mismatch")
    manual_backfill_summary_field_map = {
        "p0b_google_manual_backfill_missing_prompt_city_sample_count": "missing_prompt_city_sample_count",
        "p0b_google_manual_backfill_duplicate_prompt_city_sample_count": "duplicate_prompt_city_sample_count",
        "p0b_google_manual_backfill_unexpected_prompt_city_record_count": "unexpected_prompt_city_record_count",
        "p0b_google_manual_backfill_missing_answer_line_count": "missing_answer_line_count",
        "p0b_google_manual_backfill_missing_citation_line_count": "missing_citation_line_count",
        "p0b_google_manual_backfill_missing_asset_line_count": "missing_asset_line_count",
    }
    for summary_field, verifier_field in manual_backfill_summary_field_map.items():
        if summary.get(summary_field) != _int(p0b_google_manual_backfill_clearance_verifier.get(verifier_field)):
            errors.append(f"summary_{summary_field}_mismatch")
        if summary.get(summary_field) != _int(_as_dict(progress_verifier).get(summary_field)):
            errors.append(f"summary_progress_{summary_field}_mismatch")
    if summary.get("p0b_google_phase_execution_clearance_ready") is not (
        p0b_google_phase_execution_clearance_verifier.get("phase_execution_clearance_ready") is True
    ):
        errors.append("summary_p0b_google_phase_execution_clearance_ready_mismatch")
    if summary.get("p0b_google_phase_execution_fulfilled") is not (
        p0b_google_phase_execution_clearance_verifier.get("phase_execution_fulfilled") is True
    ):
        errors.append("summary_p0b_google_phase_execution_fulfilled_mismatch")
    if summary.get("p0b_google_phase_execution_missing_required_count") != (
        p0b_google_phase_execution_clearance_verifier.get("missing_required_count")
    ):
        errors.append("summary_p0b_google_phase_execution_missing_required_count_mismatch")

    if summary.get("required_count") != len(required_items):
        errors.append("summary_required_count_mismatch")
    if summary.get("fulfilled_required_count") != len(fulfilled_required):
        errors.append("summary_fulfilled_required_count_mismatch")
    if summary.get("missing_required_count") != len(missing_required):
        errors.append("summary_missing_required_count_mismatch")
    if sorted(_strings(summary.get("missing_required"))) != missing_required:
        errors.append("summary_missing_required_mismatch")
    if summary.get("owner_counts") != _owner_counts(items):
        errors.append("summary_owner_counts_mismatch")
    if summary.get("missing_required_by_owner") != _missing_by_owner(items):
        errors.append("summary_missing_required_by_owner_mismatch")
    if summary.get("blocking_reason_count") != len(blocking_reasons):
        errors.append("summary_blocking_reason_count_mismatch")
    if sorted(_strings(summary.get("blocking_reasons"))) != blocking_reasons:
        errors.append("summary_blocking_reasons_mismatch")
    if summary.get("customer_gate_count") != len(items):
        errors.append("summary_customer_gate_count_mismatch")
    if summary.get("ready_customer_gate_count") != len(fulfilled_required):
        errors.append("summary_ready_customer_gate_count_mismatch")
    if summary.get("blocked_customer_gate_count") != len(required_items) - len(fulfilled_required):
        errors.append("summary_blocked_customer_gate_count_mismatch")
    expected_blocked_gate_ids = [str(item.get("gate_id") or "") for item in items if item.get("fulfilled") is not True]
    if summary.get("blocked_customer_gate_ids") != expected_blocked_gate_ids:
        errors.append("summary_blocked_customer_gate_ids_mismatch")
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

    required_operator_step_ids = {
        "clear_p0a_provider_credentials",
        "clear_p0a_real_batches",
        "clear_p0b_google_environment",
        "clear_p0b_google_manual_backfill",
        "clear_p0b_google_phase_execution",
        "refresh_external_dependency_handoff",
        "refresh_external_dependency_clearance",
        "refresh_handoff_dossier",
        "refresh_customer_handoff_readiness",
        "refresh_delivery_progress",
        "run_customer_ready_strict_gates",
    }
    observed_operator_step_ids = {str(step.get("id") or "") for step in operator_steps}
    for step_id in required_operator_step_ids:
        if step_id not in observed_operator_step_ids:
            errors.append(f"operator_step_missing:{step_id}")
    for step in operator_steps:
        if not isinstance(step.get("order"), int):
            errors.append(f"operator_step_order_invalid:{step.get('id')}")
        if not str(step.get("command") or ""):
            errors.append(f"operator_step_command_missing:{step.get('id')}")

    required_validation_commands = (
        "make au-p0a-credential-clearance",
        "make verify-au-p0a-credential-clearance",
        "make au-p0a-credential-update-receipt",
        "make verify-au-p0a-credential-update-receipt",
        "make au-p0a-real-batch-clearance",
        "make verify-au-p0a-real-batch-clearance",
        "make au-p0b-google-environment-clearance",
        "make verify-au-p0b-google-environment-clearance",
        "make au-p0b-google-manual-backfill-clearance",
        "make verify-au-p0b-google-manual-backfill-clearance",
        "make au-p0b-google-phase-execution-clearance",
        "make verify-au-p0b-google-phase-execution-clearance",
        "make au-customer-handoff-clearance",
        "make verify-au-customer-handoff-clearance",
        "make au-handoff-dossier",
        "make verify-au-handoff-dossier",
        "make au-customer-handoff-readiness",
        "make verify-au-customer-handoff-readiness",
        "make au-delivery-progress",
        "make verify-au-delivery-progress",
        "make au-external-dependency-handoff",
        "make verify-au-external-dependency-handoff",
        "make au-external-dependency-clearance",
        "make verify-au-external-dependency-clearance",
    )
    for command in required_validation_commands:
        if command not in validation_sequence:
            errors.append(f"post_update_validation_command_missing:{command}")
        if command not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{command}")
    for marker in ("--require-customer-ready", "--require-ready", "--require-handoff-ready", "--require-cleared"):
        if not any(marker in command for command in validation_sequence):
            errors.append(f"post_update_validation_missing:{marker}")
    if not any("--require-complete" in command for command in validation_sequence):
        errors.append("post_update_validation_missing:p0a_credential_update_receipt_require_complete")
    if not any("--require-cleared" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_cleared")
    if not any("--require-complete" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:p0a_credential_update_receipt_require_complete")

    expected_endpoints = {
        "customer_handoff_clearance": "GET /v1/customer-handoff-clearance/au",
        "handoff_dossier": "GET /v1/handoff-dossier/au",
        "customer_handoff_readiness": "GET /v1/customer-handoff-readiness/au",
        "delivery_progress": "GET /v1/delivery-progress/au",
        "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
        "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
        "p0a_credential_clearance": "GET /v1/p0a-credential-clearance/au",
        "p0a_credential_update_receipt": "GET /v1/p0a-credential-update-receipt/au",
        "p0a_real_batch_clearance": "GET /v1/p0a-real-batch-clearance/au",
        "p0b_google_environment_clearance": "GET /v1/p0b-google-environment-clearance/au",
        "p0b_google_manual_backfill_clearance": "GET /v1/p0b-google-manual-backfill-clearance/au",
        "p0b_google_phase_execution_clearance": "GET /v1/p0b-google-phase-execution-clearance/au",
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
    if redaction_policy.get("customer_gate_entries_reference_hashes_status_and_evidence_refs_only") is not True:
        errors.append("redaction_policy_customer_gate_reference_invalid")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "current_file_check_enabled": current_file_check_enabled,
        "customer_handoff_clearance_version": payload.get("customer_handoff_clearance_version", ""),
        "customer_handoff_clearance_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_customer_handoff_clearance_hash": computed_hash,
        "hash_valid": hash_valid,
        "customer_handoff_clearance_packet_ready": expected_packet_ready,
        "customer_handoff_clearance_ready": expected_clearance_ready,
        "customer_handoff_ready": customer_handoff_ready,
        "ready_for_report_export_handoff": expected_report_ready,
        "blocked_by_prerequisite_step": blocked_by_prerequisite,
        "missing_required_count": len(missing_required),
        "missing_required": missing_required,
        "next_action": summary.get("next_action", ""),
        "next_command": summary.get("next_command", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU customer handoff clearance JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_CUSTOMER_HANDOFF_CLEARANCE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU customer handoff clearance JSON.",
    )
    parser.add_argument(
        "--require-cleared",
        action="store_true",
        help="Fail unless customer handoff clearance is ready.",
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
            "errors": ["customer_handoff_clearance_file_missing"],
            "hash_valid": False,
            "customer_handoff_clearance_packet_ready": False,
            "customer_handoff_clearance_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"customer_handoff_clearance_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "customer_handoff_clearance_packet_ready": False,
            "customer_handoff_clearance_ready": False,
        }
    else:
        result = verify_au_customer_handoff_clearance(payload, path=path, require_cleared=args.require_cleared)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
