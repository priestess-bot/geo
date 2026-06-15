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

from scripts.build_au_customer_handoff_package import (  # noqa: E402
    CUSTOMER_VISIBLE_ARTIFACTS,
    DEFAULT_OUTPUT_PATH,
    JSON_SOURCE_SPECS,
    MARKDOWN_SOURCE_SPECS,
    PACKAGE_VERSION,
    compute_customer_handoff_package_hash,
)


REQUIRED_FIELDS = (
    "customer_handoff_package_version",
    "generated_at",
    "status",
    "customer_handoff_package_manifest_ready",
    "customer_handoff_package_ready",
    "ready_for_report_export_handoff",
    "ready_for_customer_delivery",
    "next_action",
    "remaining_blockers",
    "output_path",
    "source_artifacts",
    "verifiers",
    "summary",
    "handoff_index",
    "runtime_endpoints",
    "operator_steps",
    "post_update_validation_sequence",
    "hard_gate_commands",
    "redaction_policy",
    "customer_handoff_package_hash",
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


def _expected_json_source_specs() -> dict[str, dict[str, Any]]:
    return {str(spec["name"]): spec for spec in JSON_SOURCE_SPECS}


def _expected_markdown_source_specs() -> dict[str, dict[str, Any]]:
    return {str(spec["name"]): spec for spec in MARKDOWN_SOURCE_SPECS}


def _source_ready(source: dict[str, Any]) -> bool:
    return (
        source.get("exists") is True
        and source.get("hash_valid") is True
        and source.get("verifier_status") == "pass"
    )


def _expected_summary(
    source_artifacts: dict[str, dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    required_sources = {
        name: artifact
        for name, artifact in source_artifacts.items()
        if artifact.get("required_for_customer_handoff") is True
    }
    ready_sources = sorted(name for name, artifact in required_sources.items() if _source_ready(artifact))
    blocked_sources = sorted(name for name, artifact in required_sources.items() if not _source_ready(artifact))
    blocking_reasons = sorted(
        dict.fromkeys(
            f"{name}:{error}"
            for name, artifact in source_artifacts.items()
            for error in _strings(artifact.get("errors"))
            if error
        )
    )
    manifest_ready = len(blocked_sources) == 0
    ready_for_report_export_handoff = summary.get("ready_for_report_export_handoff") is True
    p0c_ready = summary.get("p0c_report_contract_ready") is True
    package_ready = manifest_ready and ready_for_report_export_handoff and p0c_ready
    return {
        "source_artifact_count": len(source_artifacts),
        "required_source_artifact_count": len(required_sources),
        "ready_source_artifact_count": len(ready_sources),
        "blocked_source_artifact_count": len(blocked_sources),
        "ready_source_artifacts": ready_sources,
        "blocked_source_artifacts": blocked_sources,
        "blocking_reason_count": len(blocking_reasons),
        "blocking_reasons": blocking_reasons,
        "customer_visible_artifacts": sorted(
            name for name, artifact in source_artifacts.items() if artifact.get("customer_visible") is True
        ),
        "customer_handoff_package_manifest_ready": manifest_ready,
        "customer_handoff_package_ready": package_ready,
    }


def verify_au_customer_handoff_package(
    payload: Any,
    *,
    path: Path | None = None,
    require_ready: bool = False,
    verify_current_files: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["customer_handoff_package_not_json_object"],
            "hash_valid": False,
            "customer_handoff_package_manifest_ready": False,
            "customer_handoff_package_ready": False,
        }

    current_file_check_enabled = path is not None if verify_current_files is None else verify_current_files
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("customer_handoff_package_version") != PACKAGE_VERSION:
        errors.append("customer_handoff_package_version_invalid")
    for forbidden_path in _find_forbidden_fields(payload):
        errors.append(f"forbidden_customer_payload_field:{forbidden_path}")

    expected_hash = payload.get("customer_handoff_package_hash")
    computed_hash = compute_customer_handoff_package_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("customer_handoff_package_hash_mismatch")

    json_specs = _expected_json_source_specs()
    markdown_specs = _expected_markdown_source_specs()
    source_artifacts = {str(key): _as_dict(value) for key, value in _as_dict(payload.get("source_artifacts")).items()}
    verifiers = {str(key): _as_dict(value) for key, value in _as_dict(payload.get("verifiers")).items()}
    summary = _as_dict(payload.get("summary"))
    handoff_index = [_as_dict(item) for item in _as_list(payload.get("handoff_index"))]
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    operator_steps = [_as_dict(item) for item in _as_list(payload.get("operator_steps"))]
    validation_sequence = _strings(payload.get("post_update_validation_sequence"))
    hard_gate_commands = _strings(payload.get("hard_gate_commands"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))

    for name, spec in {**json_specs, **markdown_specs}.items():
        source = source_artifacts.get(name)
        if not isinstance(source, dict):
            errors.append(f"source_artifact_missing:{name}")
            continue
        for field in (
            "name",
            "stage",
            "artifact_type",
            "path",
            "exists",
            "required_for_customer_handoff",
            "customer_visible",
            "hash_field",
            "hash",
            "verifier_hash",
            "hash_valid",
            "verifier_status",
            "file_sha256",
            "size_bytes",
            "errors",
        ):
            if field not in source:
                errors.append(f"source_artifact_field_missing:{name}:{field}")
        if source.get("name") != name:
            errors.append(f"source_artifact_name_invalid:{name}")
        if source.get("stage") != spec.get("stage"):
            errors.append(f"source_artifact_stage_invalid:{name}")
        if source.get("required_for_customer_handoff") is not (spec.get("required_for_customer_handoff") is True):
            errors.append(f"source_artifact_required_flag_invalid:{name}")
        if source.get("customer_visible") is not (spec.get("customer_visible") is True):
            errors.append(f"source_artifact_customer_visible_invalid:{name}")
        if name in json_specs:
            expected_hash_field = str(spec["hash_field"])
            verifier = verifiers.get(name, {})
            if source.get("artifact_type") != "json":
                errors.append(f"source_artifact_type_invalid:{name}")
            if source.get("hash_field") != expected_hash_field:
                errors.append(f"source_artifact_hash_field_invalid:{name}")
            if verifier.get("hash_field") != expected_hash_field:
                errors.append(f"verifier_hash_field_invalid:{name}")
            if source.get("hash") != verifier.get("hash"):
                errors.append(f"source_verifier_hash_mismatch:{name}")
            if source.get("hash_valid") is not (verifier.get("hash_valid") is True):
                errors.append(f"source_verifier_hash_valid_mismatch:{name}")
            if source.get("verifier_status") != verifier.get("status"):
                errors.append(f"source_verifier_status_mismatch:{name}")
            if current_file_check_enabled:
                source_path = Path(str(source.get("path") or ""))
                if source_path.is_file():
                    current_payload = _load_json_file(source_path)
                    if not current_payload:
                        errors.append(f"source_current_json_invalid:{name}")
                    elif source.get("hash") != str(current_payload.get(expected_hash_field) or ""):
                        errors.append(f"source_current_payload_hash_mismatch:{name}")
                    current_file_sha256 = _file_sha256(source_path)
                    if source.get("file_sha256") != current_file_sha256:
                        errors.append(f"source_current_file_sha256_mismatch:{name}")
                    if source.get("size_bytes") != source_path.stat().st_size:
                        errors.append(f"source_current_size_mismatch:{name}")
                elif source.get("exists") is True:
                    errors.append(f"source_current_file_missing:{name}")
        else:
            if source.get("artifact_type") != "markdown":
                errors.append(f"source_artifact_type_invalid:{name}")
            if source.get("hash_field") != "file_sha256":
                errors.append(f"source_artifact_hash_field_invalid:{name}")
            if current_file_check_enabled:
                source_path = Path(str(source.get("path") or ""))
                if source_path.is_file():
                    current_file_sha256 = _file_sha256(source_path)
                    if source.get("file_sha256") != current_file_sha256:
                        errors.append(f"source_current_file_sha256_mismatch:{name}")
                    if source.get("hash") != current_file_sha256:
                        errors.append(f"source_current_hash_mismatch:{name}")
                    if source.get("size_bytes") != source_path.stat().st_size:
                        errors.append(f"source_current_size_mismatch:{name}")
                elif source.get("exists") is True:
                    errors.append(f"source_current_file_missing:{name}")

    expected_index = {
        str(item.get("name") or ""): {
            "stage": item.get("stage"),
            "artifact_type": item.get("artifact_type"),
            "path": item.get("path"),
            "hash_field": item.get("hash_field"),
            "hash": item.get("hash"),
            "file_sha256": item.get("file_sha256"),
            "customer_visible": item.get("customer_visible"),
            "required_for_customer_handoff": item.get("required_for_customer_handoff"),
            "status": item.get("status"),
        }
        for item in handoff_index
    }
    for name, source in source_artifacts.items():
        index_item = expected_index.get(name)
        if not index_item:
            errors.append(f"handoff_index_missing:{name}")
            continue
        if index_item["stage"] != source.get("stage"):
            errors.append(f"handoff_index_stage_mismatch:{name}")
        if index_item["artifact_type"] != source.get("artifact_type"):
            errors.append(f"handoff_index_type_mismatch:{name}")
        if index_item["path"] != source.get("path"):
            errors.append(f"handoff_index_path_mismatch:{name}")
        if index_item["hash_field"] != source.get("hash_field"):
            errors.append(f"handoff_index_hash_field_mismatch:{name}")
        if index_item["hash"] != source.get("hash"):
            errors.append(f"handoff_index_hash_mismatch:{name}")
        if index_item["file_sha256"] != source.get("file_sha256"):
            errors.append(f"handoff_index_file_sha256_mismatch:{name}")
        if index_item["customer_visible"] is not source.get("customer_visible"):
            errors.append(f"handoff_index_customer_visible_mismatch:{name}")
        if index_item["required_for_customer_handoff"] is not source.get("required_for_customer_handoff"):
            errors.append(f"handoff_index_required_mismatch:{name}")
        if index_item["status"] != source.get("verifier_status"):
            errors.append(f"handoff_index_status_mismatch:{name}")

    expected_summary = _expected_summary(source_artifacts, summary)
    for key, expected_value in expected_summary.items():
        if summary.get(key) != expected_value:
            errors.append(f"summary_{key}_mismatch")
    for name, source in source_artifacts.items():
        summary_hash_key = {
            "handoff_dossier": "handoff_dossier_hash",
            "customer_handoff_readiness": "customer_handoff_readiness_hash",
            "delivery_progress": "delivery_progress_hash",
            "customer_handoff_clearance": "customer_handoff_clearance_hash",
            "external_dependency_handoff": "external_dependency_handoff_hash",
            "external_dependency_clearance": "clearance_execution_hash",
            "p0a_credential_clearance": "p0a_credential_clearance_hash",
            "p0a_credential_update_receipt": "p0a_credential_update_receipt_hash",
            "p0a_real_batch_clearance": "p0a_real_batch_clearance_hash",
            "p0b_google_environment_clearance": "p0b_google_environment_clearance_hash",
            "p0b_google_manual_backfill_clearance": "p0b_google_manual_backfill_clearance_hash",
            "p0b_google_phase_execution_clearance": "p0b_google_phase_execution_clearance_hash",
            "p0a_evidence_package": "p0a_evidence_package_hash",
            "p0b_google_evidence_package": "p0b_google_evidence_package_hash",
            "p0c_report_package": "p0c_report_package_hash",
            "handoff_dossier_markdown": "handoff_dossier_markdown_sha256",
        }.get(name)
        if summary_hash_key and summary.get(summary_hash_key) != source.get("hash"):
            errors.append(f"summary_source_hash_mismatch:{name}")

    manifest_ready = expected_summary["customer_handoff_package_manifest_ready"]
    expected_package_ready = expected_summary["customer_handoff_package_ready"]
    if payload.get("customer_handoff_package_manifest_ready") is not manifest_ready:
        errors.append("customer_handoff_package_manifest_ready_mismatch")
    if payload.get("customer_handoff_package_ready") is not expected_package_ready:
        errors.append("customer_handoff_package_ready_mismatch")
    if payload.get("ready_for_customer_delivery") is not expected_package_ready:
        errors.append("ready_for_customer_delivery_mismatch")
    if payload.get("status") != ("pass" if manifest_ready else "fail"):
        errors.append("status_mismatch")
    expected_next_action = (
        "ready_for_customer_delivery_export" if expected_package_ready else "clear_customer_handoff_prerequisites_first"
    )
    if payload.get("next_action") != expected_next_action:
        errors.append("next_action_mismatch")
    expected_remaining = [] if manifest_ready else expected_summary["blocking_reasons"]
    if sorted(_strings(payload.get("remaining_blockers"))) != sorted(expected_remaining):
        errors.append("remaining_blockers_mismatch")
    if require_ready and not expected_package_ready:
        errors.append("customer_handoff_package_not_ready")

    expected_endpoints = {
        "customer_handoff_package": "GET /v1/customer-handoff-package/au",
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

    required_operator_step_ids = {
        "refresh_customer_handoff_sources",
        "refresh_p0_evidence_packages",
        "build_customer_handoff_package",
        "verify_customer_handoff_package",
        "run_customer_ready_strict_gate",
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

    required_commands = (
        "make au-customer-handoff-package",
        "make verify-au-customer-handoff-package",
        "make au-customer-handoff-clearance",
        "make verify-au-customer-handoff-clearance",
        "make au-delivery-progress",
        "make verify-au-delivery-progress",
        "make au-p0c-report-package",
        "make verify-au-p0c-report-package",
    )
    for command in required_commands:
        if command not in validation_sequence:
            errors.append(f"post_update_validation_command_missing:{command}")
        if command not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{command}")
    for marker in ("--require-cleared", "--require-ready"):
        if not any(marker in command for command in validation_sequence):
            errors.append(f"post_update_validation_missing:{marker}")
        if not any(marker in command for command in hard_gate_commands):
            errors.append(f"hard_gate_missing:{marker}")

    for field in (
        "raw_secret_values_allowed",
        "raw_answer_values_allowed",
        "raw_citation_values_allowed",
        "raw_asset_urls_allowed",
        "raw_provider_response_allowed",
    ):
        if summary.get(field) is not False:
            errors.append(f"summary_redaction_policy_invalid:{field}")
        if redaction_policy.get(field) is not False:
            errors.append(f"redaction_policy_invalid:{field}")
    if redaction_policy.get("source_payloads_embedded") is not False:
        errors.append("redaction_policy_source_payloads_embedded_invalid")
    if redaction_policy.get("hash_path_status_only") is not True:
        errors.append("redaction_policy_hash_path_status_only_invalid")
    if sorted(_strings(redaction_policy.get("customer_visible_artifacts"))) != sorted(CUSTOMER_VISIBLE_ARTIFACTS):
        errors.append("redaction_policy_customer_visible_artifacts_invalid")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "current_file_check_enabled": current_file_check_enabled,
        "customer_handoff_package_version": payload.get("customer_handoff_package_version", ""),
        "customer_handoff_package_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_customer_handoff_package_hash": computed_hash,
        "hash_valid": hash_valid,
        "customer_handoff_package_manifest_ready": manifest_ready,
        "customer_handoff_package_ready": expected_package_ready,
        "ready_for_report_export_handoff": summary.get("ready_for_report_export_handoff") is True,
        "ready_for_customer_delivery": expected_package_ready,
        "source_artifact_count": len(source_artifacts),
        "blocked_source_artifact_count": len(expected_summary["blocked_source_artifacts"]),
        "blocked_source_artifacts": expected_summary["blocked_source_artifacts"],
        "next_action": payload.get("next_action", ""),
        "next_command": summary.get("next_command", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU customer handoff package index JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_CUSTOMER_HANDOFF_PACKAGE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU customer handoff package JSON.",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Fail unless the customer handoff package is ready for customer delivery.",
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
            "errors": ["customer_handoff_package_file_missing"],
            "hash_valid": False,
            "customer_handoff_package_manifest_ready": False,
            "customer_handoff_package_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"customer_handoff_package_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "customer_handoff_package_manifest_ready": False,
            "customer_handoff_package_ready": False,
        }
    else:
        result = verify_au_customer_handoff_package(payload, path=path, require_ready=args.require_ready)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
