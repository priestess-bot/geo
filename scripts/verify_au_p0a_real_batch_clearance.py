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

from scripts.build_au_p0a_real_batch_clearance import (  # noqa: E402
    CLEARANCE_VERSION,
    DEFAULT_OUTPUT_PATH,
    PHASE_ORDER,
    PREREQUISITE_STEP_ID,
    STEP_ID,
    compute_p0a_real_batch_clearance_hash,
)


REQUIRED_FIELDS = (
    "p0a_real_batch_clearance_version",
    "generated_at",
    "status",
    "real_batch_clearance_packet_ready",
    "real_batches_fulfilled",
    "real_batch_clearance_ready",
    "ready_for_next_clearance_step",
    "blocked_by_prerequisite_step",
    "output_path",
    "clearance_step",
    "prerequisite_step",
    "source_artifacts",
    "p0a_real_batch_request_verifier",
    "p0a_execution_checklist_verifier",
    "p0a_real_batch_fulfillment_verifier",
    "summary",
    "phase_clearance_items",
    "operator_steps",
    "post_update_validation_sequence",
    "runtime_endpoints",
    "hard_gate_commands",
    "redaction_policy",
    "p0a_real_batch_clearance_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


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


def _source_file_sha256(source: dict[str, Any]) -> str:
    source_meta = _as_dict(source.get("source"))
    return str(source_meta.get("file_sha256") or source.get("file_sha256") or "")


def _source_declares_existing(source: dict[str, Any]) -> bool:
    source_meta = _as_dict(source.get("source"))
    return source_meta.get("exists") is True or source_meta.get("source") == "existing_file"


def _check_current_source_file(
    errors: list[str],
    *,
    source_key: str,
    source: dict[str, Any],
    hash_field: str,
    expected_hash: str,
) -> None:
    source_path_value = str(source.get("path") or "")
    if not source_path_value:
        errors.append(f"{source_key}_source_path_missing")
        return

    source_path = Path(source_path_value)
    if source_path.is_file():
        current_payload = _load_json_file(source_path)
        if not current_payload:
            errors.append(f"{source_key}_current_json_invalid")
        else:
            current_hash = str(current_payload.get(hash_field) or "")
            if not current_hash:
                errors.append(f"{source_key}_current_hash_missing")
            elif expected_hash != current_hash:
                errors.append(f"{source_key}_current_hash_mismatch")

        expected_file_sha = _source_file_sha256(source)
        if expected_file_sha and expected_file_sha != _file_sha256(source_path):
            errors.append(f"{source_key}_file_sha256_mismatch")
    elif _source_declares_existing(source):
        errors.append(f"{source_key}_source_file_missing")


def _find_forbidden_raw_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {
                "value",
                "raw_value",
                "database_url",
                "secret",
                "token",
                "answer_text",
                "citation_urls",
                "screenshot_url",
                "html_snapshot_url",
            }:
                findings.append(child_path)
            findings.extend(_find_forbidden_raw_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_raw_fields(child, path=f"{path}[{index}]"))
    return findings


def _missing_by_owner(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for item in items:
        if item.get("fulfilled") is not True:
            owner = str(item.get("owner_hint") or "unknown")
            owners.setdefault(owner, []).append(str(item.get("key") or ""))
    return {owner: sorted(keys) for owner, keys in sorted(owners.items())}


def verify_au_p0a_real_batch_clearance(
    payload: Any,
    *,
    path: Path | None = None,
    require_cleared: bool = False,
    verify_current_files: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0a_real_batch_clearance_not_json_object"],
            "hash_valid": False,
            "real_batch_clearance_packet_ready": False,
            "real_batch_clearance_ready": False,
            "current_file_check_enabled": path is not None if verify_current_files is None else verify_current_files,
        }

    current_file_check_enabled = path is not None if verify_current_files is None else verify_current_files
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0a_real_batch_clearance_version") != CLEARANCE_VERSION:
        errors.append("p0a_real_batch_clearance_version_invalid")
    for forbidden_path in _find_forbidden_raw_fields(payload):
        errors.append(f"forbidden_raw_field:{forbidden_path}")

    expected_hash = payload.get("p0a_real_batch_clearance_hash")
    computed_hash = compute_p0a_real_batch_clearance_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0a_real_batch_clearance_hash_mismatch")

    request_verifier = _as_dict(payload.get("p0a_real_batch_request_verifier"))
    checklist_verifier = _as_dict(payload.get("p0a_execution_checklist_verifier"))
    fulfillment_verifier = _as_dict(payload.get("p0a_real_batch_fulfillment_verifier"))
    source_artifacts = _as_dict(payload.get("source_artifacts"))
    request_source = _as_dict(source_artifacts.get("real_batch_request"))
    checklist_source = _as_dict(source_artifacts.get("p0a_execution_checklist"))
    fulfillment_source = _as_dict(source_artifacts.get("real_batch_fulfillment"))
    clearance_source = _as_dict(source_artifacts.get("external_dependency_clearance"))
    summary = _as_dict(payload.get("summary"))
    clearance_step = _as_dict(payload.get("clearance_step"))
    prerequisite_step = _as_dict(payload.get("prerequisite_step"))
    phase_items = [_as_dict(item) for item in _as_list(payload.get("phase_clearance_items"))]
    operator_steps = [_as_dict(item) for item in _as_list(payload.get("operator_steps"))]
    validation_sequence = _strings(payload.get("post_update_validation_sequence"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    hard_gate_commands = _strings(payload.get("hard_gate_commands"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))

    request_ok = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    checklist_ok = checklist_verifier.get("status") == "pass" and checklist_verifier.get("hash_valid") is True
    fulfillment_ok = fulfillment_verifier.get("status") == "pass" and fulfillment_verifier.get("hash_valid") is True
    clearance_ok = str(clearance_source.get("verifier_status") or "") in {"pass", ""}
    expected_packet_ready = request_ok and checklist_ok and fulfillment_ok and clearance_ok
    if payload.get("real_batch_clearance_packet_ready") is not expected_packet_ready:
        errors.append("real_batch_clearance_packet_ready_mismatch")
    if payload.get("status") != ("pass" if expected_packet_ready else "fail"):
        errors.append("status_mismatch")

    real_batches_fulfilled = fulfillment_verifier.get("real_batches_fulfilled") is True
    if payload.get("real_batches_fulfilled") is not real_batches_fulfilled:
        errors.append("real_batches_fulfilled_mismatch")
    blocked_by_prerequisite = prerequisite_step.get("ready") is not True
    if payload.get("blocked_by_prerequisite_step") is not blocked_by_prerequisite:
        errors.append("blocked_by_prerequisite_step_mismatch")
    expected_next_ready = real_batches_fulfilled and not blocked_by_prerequisite
    expected_clearance_ready = real_batches_fulfilled and clearance_step.get("step_ready") is True and not blocked_by_prerequisite
    if payload.get("ready_for_next_clearance_step") is not expected_next_ready:
        errors.append("ready_for_next_clearance_step_mismatch")
    if payload.get("real_batch_clearance_ready") is not expected_clearance_ready:
        errors.append("real_batch_clearance_ready_mismatch")
    if require_cleared and not expected_clearance_ready:
        errors.append("p0a_real_batches_not_cleared")

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

    if request_source.get("hash") != request_verifier.get("p0a_real_batch_request_packet_hash"):
        errors.append("source_request_hash_mismatch")
    if checklist_source.get("hash") != checklist_verifier.get("p0a_execution_checklist_hash"):
        errors.append("source_checklist_hash_mismatch")
    if fulfillment_source.get("hash") != fulfillment_verifier.get("p0a_real_batch_fulfillment_hash"):
        errors.append("source_fulfillment_hash_mismatch")
    expected_hash_fields = {
        "real_batch_request": "p0a_real_batch_request_packet_hash",
        "p0a_execution_checklist": "p0a_execution_checklist_hash",
        "real_batch_fulfillment": "p0a_real_batch_fulfillment_hash",
        "external_dependency_clearance": "clearance_execution_hash",
    }
    for key, expected_field in expected_hash_fields.items():
        if _as_dict(source_artifacts.get(key)).get("hash_field") != expected_field:
            errors.append(f"source_hash_field_invalid:{key}")
    if current_file_check_enabled:
        _check_current_source_file(
            errors,
            source_key="source_request",
            source=request_source,
            hash_field="p0a_real_batch_request_packet_hash",
            expected_hash=str(request_source.get("hash") or ""),
        )
        _check_current_source_file(
            errors,
            source_key="source_checklist",
            source=checklist_source,
            hash_field="p0a_execution_checklist_hash",
            expected_hash=str(checklist_source.get("hash") or ""),
        )
        _check_current_source_file(
            errors,
            source_key="source_fulfillment",
            source=fulfillment_source,
            hash_field="p0a_real_batch_fulfillment_hash",
            expected_hash=str(fulfillment_source.get("hash") or ""),
        )
        _check_current_source_file(
            errors,
            source_key="source_clearance",
            source=clearance_source,
            hash_field="clearance_execution_hash",
            expected_hash=str(clearance_source.get("hash") or ""),
        )

    phase_order = [str(item.get("phase_id") or "") for item in phase_items]
    if phase_order != PHASE_ORDER:
        errors.append("phase_order_invalid")
    missing_required = sorted(str(item.get("key") or "") for item in phase_items if item.get("fulfilled") is not True)
    if summary.get("missing_required_count") != len(missing_required):
        errors.append("summary_missing_required_count_mismatch")
    if sorted(_strings(summary.get("missing_required"))) != missing_required:
        errors.append("summary_missing_required_mismatch")
    if summary.get("missing_required_by_owner") != _missing_by_owner(phase_items):
        errors.append("summary_missing_required_by_owner_mismatch")
    if summary.get("phase_count") != len(phase_items):
        errors.append("summary_phase_count_mismatch")
    if summary.get("ready_phase_count") != sum(1 for item in phase_items if item.get("fulfilled") is True):
        errors.append("summary_ready_phase_count_mismatch")
    if summary.get("blocked_phase_count") != sum(1 for item in phase_items if item.get("fulfilled") is not True):
        errors.append("summary_blocked_phase_count_mismatch")
    if summary.get("operator_step_count") != len(operator_steps):
        errors.append("summary_operator_step_count_mismatch")
    if summary.get("post_update_validation_command_count") != len(validation_sequence):
        errors.append("summary_post_update_validation_command_count_mismatch")
    if summary.get("raw_secret_values_allowed") is not False:
        errors.append("summary_raw_secret_policy_invalid")
    if summary.get("provider_response_values_allowed") is not False:
        errors.append("summary_provider_response_policy_invalid")

    required_step_ids = {
        "clear_p0a_provider_credentials",
        "refresh_real_batch_request",
        "refresh_real_batch_fulfillment",
        "run_current_real_batch_phase",
        "verify_real_batch_fulfillment",
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

    for item in phase_items:
        phase_id = str(item.get("phase_id") or "")
        for field in (
            "key",
            "phase_id",
            "title",
            "owner_hint",
            "fulfilled",
            "request_ready",
            "checklist_ready",
            "can_start",
            "planned_runs",
            "command_ids",
            "commands",
            "artifact_keys",
            "prerequisite_gate_ids",
            "evidence_outputs",
            "blocking_reasons",
        ):
            if field not in item:
                errors.append(f"phase_clearance_item_field_missing:{phase_id}:{field}")
        if item.get("fulfilled") is not True and not _as_list(item.get("blocking_reasons")):
            errors.append(f"phase_clearance_item_blocking_reasons_missing:{phase_id}")

    for command in (
        "make au-p0a-credential-clearance",
        "make verify-au-p0a-credential-clearance",
        "make au-p0a-real-batch-request",
        "make verify-au-p0a-real-batch-request",
        "make au-p0a-real-batch-fulfillment",
        "make verify-au-p0a-real-batch-fulfillment",
    ):
        if command not in validation_sequence:
            errors.append(f"post_update_validation_command_missing:{command}")
        if command not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{command}")
    if not any("--require-fulfilled" in command for command in validation_sequence):
        errors.append("post_update_validation_missing_require_fulfilled")
    if not any("--require-cleared" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_cleared")
    if not any("--require-design-partner-ready" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_design_partner_ready")

    expected_endpoints = {
        "p0a_real_batch_clearance": "GET /v1/p0a-real-batch-clearance/au",
        "p0a_real_batch_request": "GET /v1/p0a-real-batch-request/au",
        "p0a_real_batch_fulfillment": "GET /v1/p0a-real-batch-fulfillment/au",
        "p0a_execution_checklist": "GET /v1/p0a-execution-checklist/au",
        "p0a_credential_clearance": "GET /v1/p0a-credential-clearance/au",
        "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
        "delivery_progress": "GET /v1/delivery-progress/au",
    }
    for key, expected in expected_endpoints.items():
        if endpoints.get(key) != expected:
            errors.append(f"runtime_endpoint_invalid:{key}")
    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("redaction_policy_raw_secret_invalid")
    if redaction_policy.get("provider_response_values_allowed") is not False:
        errors.append("redaction_policy_provider_response_invalid")
    if redaction_policy.get("phase_entries_reference_command_ids_and_artifact_paths_only") is not True:
        errors.append("redaction_policy_phase_reference_invalid")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0a_real_batch_clearance_version": payload.get("p0a_real_batch_clearance_version", ""),
        "p0a_real_batch_clearance_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0a_real_batch_clearance_hash": computed_hash,
        "hash_valid": hash_valid,
        "current_file_check_enabled": current_file_check_enabled,
        "real_batch_clearance_packet_ready": expected_packet_ready,
        "real_batch_clearance_ready": expected_clearance_ready,
        "real_batches_fulfilled": real_batches_fulfilled,
        "blocked_by_prerequisite_step": blocked_by_prerequisite,
        "missing_required_count": len(missing_required),
        "missing_required": missing_required,
        "next_phase": summary.get("next_phase", ""),
        "next_command": summary.get("next_command", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0a real batch clearance JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0A_REAL_BATCH_CLEARANCE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0a real batch clearance JSON.",
    )
    parser.add_argument("--require-cleared", action="store_true", help="Fail unless P0a real batches are cleared.")
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
            "errors": ["p0a_real_batch_clearance_file_missing"],
            "hash_valid": False,
            "real_batch_clearance_packet_ready": False,
            "real_batch_clearance_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0a_real_batch_clearance_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "real_batch_clearance_packet_ready": False,
            "real_batch_clearance_ready": False,
        }
    else:
        result = verify_au_p0a_real_batch_clearance(payload, path=path, require_cleared=args.require_cleared)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
