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


def _percent(ready_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return round((ready_count / total_count) * 100, 1)


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _progress_gate_lookup(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(gate.get("id") or ""): _as_dict(gate) for gate in _as_list(payload.get("progress_gates"))}


def verify_au_delivery_progress(
    payload: Any,
    *,
    path: Path | None = None,
    require_customer_ready: bool = False,
    verify_current_files: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["delivery_progress_not_json_object"],
            "hash_valid": False,
            "delivery_progress_ready": False,
            "ready_for_customer_report_handoff": False,
        }

    current_file_check_enabled = path is not None if verify_current_files is None else verify_current_files
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
        "p0a_credential_clearance",
        "p0a_credential_update_receipt",
        "p0a_real_batch_clearance",
        "p0b_google_environment_clearance",
        "p0b_google_manual_backfill_clearance",
        "p0b_google_phase_execution_clearance",
    )
    expected_status_pass = launch_verifier.get("hash_valid") is True and all(
        _as_dict(verifiers.get(key)).get("status") == "pass" for key in required_pass_verifiers
    )
    if payload.get("status") != ("pass" if expected_status_pass else "fail"):
        errors.append("status_mismatch")
    if payload.get("delivery_progress_ready") is not True:
        errors.append("delivery_progress_ready_mismatch")

    source_artifacts = _as_dict(payload.get("source_artifacts"))
    evidence_sources = _evidence_source_lookup(payload)
    for artifact_key, hash_field in (
        ("launch_status", "launch_status_hash"),
        ("handoff_dossier", "handoff_dossier_hash"),
        ("customer_handoff_readiness", "customer_handoff_readiness_hash"),
        ("next_work_item", "next_work_item_packet_hash"),
        ("external_dependency_handoff", "external_dependency_handoff_hash"),
        ("external_dependency_clearance", "clearance_execution_hash"),
        ("p0a_credential_clearance", "p0a_credential_clearance_hash"),
        ("p0a_credential_update_receipt", "p0a_credential_update_receipt_hash"),
        ("p0a_real_batch_clearance", "p0a_real_batch_clearance_hash"),
        ("p0b_google_environment_clearance", "p0b_google_environment_clearance_hash"),
        ("p0b_google_manual_backfill_clearance", "p0b_google_manual_backfill_clearance_hash"),
        ("p0b_google_phase_execution_clearance", "p0b_google_phase_execution_clearance_hash"),
    ):
        artifact = _as_dict(source_artifacts.get(artifact_key))
        if artifact.get("hash_field") != hash_field:
            errors.append(f"source_artifact_hash_field_mismatch:{artifact_key}")
        summary_key = hash_field if hash_field != "clearance_execution_hash" else "clearance_execution_hash"
        if summary.get(summary_key) != artifact.get("hash"):
            errors.append(f"source_artifact_hash_mismatch:{artifact_key}")
        if artifact.get("hash_valid") is not True:
            errors.append(f"source_artifact_hash_not_valid:{artifact_key}")
        if current_file_check_enabled:
            artifact_path = Path(str(artifact.get("path") or ""))
            artifact_source = _as_dict(artifact.get("source"))
            artifact_source_declares_existing = artifact_source.get("exists") is True or (
                artifact_source.get("source") == "existing_file"
            )
            if artifact_path.is_file():
                current_payload = _load_json_file(artifact_path)
                if not current_payload:
                    errors.append(f"source_artifact_current_json_invalid:{artifact_key}")
                else:
                    current_hash = str(current_payload.get(hash_field) or "")
                    if not current_hash:
                        errors.append(f"source_artifact_current_hash_missing:{artifact_key}")
                    if artifact.get("hash") != current_hash:
                        errors.append(f"source_artifact_current_hash_mismatch:{artifact_key}")
                    if summary.get(summary_key) != current_hash:
                        errors.append(f"summary_source_artifact_current_hash_mismatch:{artifact_key}")
                evidence_source = _as_dict(evidence_sources.get(artifact_key))
                current_file_sha256 = _file_sha256(artifact_path)
                if evidence_source.get("file_sha256") and evidence_source.get("file_sha256") != current_file_sha256:
                    errors.append(f"evidence_source_file_sha256_mismatch:{artifact_key}")
            elif artifact_source_declares_existing:
                errors.append(f"source_artifact_file_missing:{artifact_key}")

    p0a_credential_clearance_verifier = _as_dict(verifiers.get("p0a_credential_clearance"))
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

    p0a_credential_update_receipt_verifier = _as_dict(verifiers.get("p0a_credential_update_receipt"))
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

    p0a_real_batch_clearance_verifier = _as_dict(verifiers.get("p0a_real_batch_clearance"))
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
    if summary.get("p0a_real_batch_execution_plan_ready") is not (
        p0a_real_batch_clearance_verifier.get("real_batch_execution_plan_ready") is True
    ):
        errors.append("summary_p0a_real_batch_execution_plan_ready_mismatch")
    if summary.get("p0a_real_batch_missing_required_count") != p0a_real_batch_clearance_verifier.get(
        "missing_required_count"
    ):
        errors.append("summary_p0a_real_batch_missing_required_count_mismatch")
    real_batch_summary_field_map = {
        "p0a_real_batch_total_planned_runs": "total_planned_runs",
        "p0a_real_batch_ready_phase_count": "ready_phase_count",
        "p0a_real_batch_blocked_phase_count": "blocked_phase_count",
        "p0a_real_batch_phase_command_count": "phase_command_count",
        "p0a_real_batch_evidence_output_count": "evidence_output_count",
    }
    for summary_field, verifier_field in real_batch_summary_field_map.items():
        if summary.get(summary_field) != p0a_real_batch_clearance_verifier.get(verifier_field):
            errors.append(f"summary_{summary_field}_mismatch")

    p0b_google_environment_clearance_verifier = _as_dict(verifiers.get("p0b_google_environment_clearance"))
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

    p0b_google_manual_backfill_clearance_verifier = _as_dict(verifiers.get("p0b_google_manual_backfill_clearance"))
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
    if summary.get("p0b_google_manual_backfill_content_completion_handoff_ready") is not (
        p0b_google_manual_backfill_clearance_verifier.get("manual_content_completion_handoff_ready") is True
    ):
        errors.append("summary_p0b_google_manual_backfill_content_completion_handoff_ready_mismatch")
    manual_backfill_summary_field_map = {
        "p0b_google_manual_backfill_missing_prompt_city_sample_count": "missing_prompt_city_sample_count",
        "p0b_google_manual_backfill_duplicate_prompt_city_sample_count": "duplicate_prompt_city_sample_count",
        "p0b_google_manual_backfill_unexpected_prompt_city_record_count": "unexpected_prompt_city_record_count",
        "p0b_google_manual_backfill_missing_answer_line_count": "missing_answer_line_count",
        "p0b_google_manual_backfill_missing_citation_line_count": "missing_citation_line_count",
        "p0b_google_manual_backfill_missing_asset_line_count": "missing_asset_line_count",
        "p0b_google_manual_backfill_missing_total_content_cell_count": "missing_total_content_cell_count",
        "p0b_google_manual_backfill_post_content_completion_validation_command_count": (
            "post_content_completion_validation_command_count"
        ),
    }
    for summary_field, verifier_field in manual_backfill_summary_field_map.items():
        if summary.get(summary_field) != _int(p0b_google_manual_backfill_clearance_verifier.get(verifier_field)):
            errors.append(f"summary_{summary_field}_mismatch")

    p0b_google_phase_execution_clearance_verifier = _as_dict(verifiers.get("p0b_google_phase_execution_clearance"))
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
        "p0a_credential_clearance": "GET /v1/p0a-credential-clearance/au",
        "p0a_credential_update_receipt": "GET /v1/p0a-credential-update-receipt/au",
        "p0a_real_batch_clearance": "GET /v1/p0a-real-batch-clearance/au",
        "p0b_google_environment_clearance": "GET /v1/p0b-google-environment-clearance/au",
        "p0b_google_manual_backfill_clearance": "GET /v1/p0b-google-manual-backfill-clearance/au",
        "p0b_google_phase_execution_clearance": "GET /v1/p0b-google-phase-execution-clearance/au",
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
        "make verify-au-p0a-credential-clearance",
        "make au-p0a-credential-update-receipt",
        "make verify-au-p0a-credential-update-receipt",
        "make verify-au-p0a-real-batch-clearance",
        "make verify-au-p0b-google-environment-clearance",
        "make verify-au-p0b-google-manual-backfill-clearance",
        "make verify-au-p0b-google-phase-execution-clearance",
    ):
        if command not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{command}")
    if not any(command.endswith("--require-customer-ready") for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_customer_ready")
    if not any("--require-complete" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:p0a_credential_update_receipt_require_complete")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "current_file_check_enabled": current_file_check_enabled,
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
        "p0a_real_batch_execution_plan_ready": summary.get("p0a_real_batch_execution_plan_ready") is True,
        "p0a_real_batch_total_planned_runs": summary.get("p0a_real_batch_total_planned_runs"),
        "p0a_real_batch_ready_phase_count": summary.get("p0a_real_batch_ready_phase_count"),
        "p0a_real_batch_blocked_phase_count": summary.get("p0a_real_batch_blocked_phase_count"),
        "p0a_real_batch_phase_command_count": summary.get("p0a_real_batch_phase_command_count"),
        "p0a_real_batch_evidence_output_count": summary.get("p0a_real_batch_evidence_output_count"),
        "p0b_google_manual_backfill_ready": summary.get("p0b_google_manual_backfill_ready") is True,
        "p0b_google_manual_backfill_coverage_complete": summary.get(
            "p0b_google_manual_backfill_coverage_complete"
        )
        is True,
        "p0b_google_manual_backfill_content_complete": summary.get("p0b_google_manual_backfill_content_complete")
        is True,
        "p0b_google_manual_backfill_content_completion_handoff_ready": summary.get(
            "p0b_google_manual_backfill_content_completion_handoff_ready"
        )
        is True,
        "p0b_google_manual_backfill_missing_prompt_city_sample_count": summary.get(
            "p0b_google_manual_backfill_missing_prompt_city_sample_count",
        ),
        "p0b_google_manual_backfill_duplicate_prompt_city_sample_count": summary.get(
            "p0b_google_manual_backfill_duplicate_prompt_city_sample_count",
        ),
        "p0b_google_manual_backfill_unexpected_prompt_city_record_count": summary.get(
            "p0b_google_manual_backfill_unexpected_prompt_city_record_count",
        ),
        "p0b_google_manual_backfill_missing_answer_line_count": summary.get(
            "p0b_google_manual_backfill_missing_answer_line_count",
        ),
        "p0b_google_manual_backfill_missing_citation_line_count": summary.get(
            "p0b_google_manual_backfill_missing_citation_line_count",
        ),
        "p0b_google_manual_backfill_missing_asset_line_count": summary.get(
            "p0b_google_manual_backfill_missing_asset_line_count",
        ),
        "p0b_google_manual_backfill_missing_total_content_cell_count": summary.get(
            "p0b_google_manual_backfill_missing_total_content_cell_count",
        ),
        "p0b_google_manual_backfill_post_content_completion_validation_command_count": summary.get(
            "p0b_google_manual_backfill_post_content_completion_validation_command_count",
        ),
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
