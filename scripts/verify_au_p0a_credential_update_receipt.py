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

from scripts.build_au_p0a_credential_update_receipt import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    RECEIPT_VERSION,
    compute_p0a_credential_update_receipt_hash,
)


REQUIRED_FIELDS = (
    "p0a_credential_update_receipt_version",
    "generated_at",
    "status",
    "credential_update_receipt_ready",
    "credential_update_receipt_complete",
    "credentials_fulfilled",
    "credential_clearance_ready",
    "output_path",
    "credential_update_contract",
    "source_artifacts",
    "verifiers",
    "env_file_hygiene",
    "required_credential_records",
    "credential_update_action_plan",
    "summary",
    "post_update_validation_sequence",
    "strict_gate_commands",
    "runtime_endpoints",
    "redaction_policy",
    "p0a_credential_update_receipt_hash",
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


def _find_forbidden_secret_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {"value", "raw_value", "database_url", "secret", "token"}:
                findings.append(child_path)
            findings.extend(_find_forbidden_secret_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_secret_fields(child, path=f"{path}[{index}]"))
    return findings


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


def _owner_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        owner = str(item.get("owner_hint") or "unknown")
        counts[owner] = counts.get(owner, 0) + 1
    return dict(sorted(counts.items()))


def verify_au_p0a_credential_update_receipt(
    payload: Any,
    *,
    path: Path | None = None,
    require_complete: bool = False,
    verify_current_files: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0a_credential_update_receipt_not_json_object"],
            "hash_valid": False,
            "credential_update_receipt_ready": False,
            "credential_update_receipt_complete": False,
            "current_file_check_enabled": path is not None if verify_current_files is None else verify_current_files,
        }

    current_file_check_enabled = path is not None if verify_current_files is None else verify_current_files
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0a_credential_update_receipt_version") != RECEIPT_VERSION:
        errors.append("p0a_credential_update_receipt_version_invalid")
    for finding in _find_forbidden_secret_fields(payload):
        errors.append(f"forbidden_secret_field:{finding}")

    expected_hash = payload.get("p0a_credential_update_receipt_hash")
    computed_hash = compute_p0a_credential_update_receipt_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0a_credential_update_receipt_hash_mismatch")

    summary = _as_dict(payload.get("summary"))
    contract = _as_dict(payload.get("credential_update_contract"))
    source_artifacts = _as_dict(payload.get("source_artifacts"))
    verifiers = _as_dict(payload.get("verifiers"))
    env_file_hygiene = _as_dict(payload.get("env_file_hygiene"))
    records = [_as_dict(record) for record in _as_list(payload.get("required_credential_records"))]
    action_plan = _as_dict(payload.get("credential_update_action_plan"))
    validation_sequence = _strings(payload.get("post_update_validation_sequence"))
    strict_gate_commands = _strings(payload.get("strict_gate_commands"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))

    required_records = [record for record in records if record.get("required") is True]
    present_required = [record for record in required_records if record.get("present") is True]
    missing_required = sorted(str(record.get("name") or "") for record in required_records if record.get("present") is not True)
    missing_records = [record for record in required_records if record.get("present") is not True]
    action_items = [_as_dict(item) for item in _as_list(action_plan.get("action_items"))]
    for record in records:
        name = str(record.get("name") or "")
        for field in (
            "required",
            "owner_hint",
            "target_env_file",
            "source",
            "present",
            "fulfilled",
            "value_length",
            "sha256_prefix",
            "secret_redacted",
            "raw_value_recorded",
            "blocking_reasons",
            "post_update_checks",
        ):
            if field not in record:
                errors.append(f"credential_record_field_missing:{name}:{field}")
        if record.get("raw_value_recorded") is not False:
            errors.append(f"credential_record_raw_value_policy_invalid:{name}")
        if record.get("secret_redacted") is not True:
            errors.append(f"credential_record_secret_redaction_missing:{name}")
        if record.get("present") is True:
            if not isinstance(record.get("value_length"), int) or record.get("value_length") <= 0:
                errors.append(f"credential_record_value_length_invalid:{name}")
            prefix = record.get("sha256_prefix")
            if not isinstance(prefix, str) or len(prefix) != 12:
                errors.append(f"credential_record_sha256_prefix_invalid:{name}")

    if action_plan.get("version") != "au_p0a_credential_update_action_plan_v1":
        errors.append("credential_update_action_plan_version_invalid")
    if action_plan.get("ready") is not True:
        errors.append("credential_update_action_plan_ready_invalid")

    request_verifier = _as_dict(verifiers.get("credential_request"))
    env_verifier = _as_dict(verifiers.get("env_report"))
    fulfillment_verifier = _as_dict(verifiers.get("credential_fulfillment"))
    clearance_verifier = _as_dict(verifiers.get("credential_clearance"))
    credentials_fulfilled = fulfillment_verifier.get("credentials_fulfilled") is True
    credential_clearance_ready = clearance_verifier.get("credential_clearance_ready") is True
    expected_complete = (
        request_verifier.get("status") == "pass"
        and env_verifier.get("status") == "pass"
        and fulfillment_verifier.get("status") == "pass"
        and clearance_verifier.get("status") == "pass"
        and not missing_required
        and credentials_fulfilled
        and credential_clearance_ready
        and env_file_hygiene.get("hygiene_ready") is True
    )
    if action_plan.get("complete") is not expected_complete:
        errors.append("credential_update_action_plan_complete_mismatch")
    if action_plan.get("action_required") is not (not expected_complete):
        errors.append("credential_update_action_plan_action_required_mismatch")
    if action_plan.get("action_item_count") != len(missing_records):
        errors.append("credential_update_action_plan_action_item_count_mismatch")
    if _as_dict(action_plan.get("owner_counts")) != _owner_counts(action_items):
        errors.append("credential_update_action_plan_owner_counts_mismatch")
    if action_plan.get("target_env_file") != contract.get("target_env_file"):
        errors.append("credential_update_action_plan_target_env_file_mismatch")
    if action_plan.get("next_command") != (
        "make au-external-dependency-clearance" if expected_complete else "make au-p0a-env"
    ):
        errors.append("credential_update_action_plan_next_command_mismatch")
    if _strings(action_plan.get("post_update_validation_sequence")) != validation_sequence:
        errors.append("credential_update_action_plan_validation_sequence_mismatch")
    if action_plan.get("post_update_validation_command_count") != len(validation_sequence):
        errors.append("credential_update_action_plan_validation_count_mismatch")
    if "--require-complete" not in str(action_plan.get("strict_gate_command") or ""):
        errors.append("credential_update_action_plan_strict_gate_invalid")
    action_plan_redaction = _as_dict(action_plan.get("redaction_policy"))
    if action_plan_redaction.get("raw_secret_values_allowed") is not False:
        errors.append("credential_update_action_plan_raw_secret_policy_invalid")
    if action_plan_redaction.get("secret_redacted") is not True:
        errors.append("credential_update_action_plan_secret_redaction_missing")
    missing_names = [str(record.get("name") or "") for record in missing_records]
    action_names = [str(item.get("credential_name") or "") for item in action_items]
    if sorted(action_names) != sorted(missing_names):
        errors.append("credential_update_action_plan_action_names_mismatch")
    for index, item in enumerate(action_items, start=1):
        name = str(item.get("credential_name") or "")
        if item.get("order") != index:
            errors.append(f"credential_update_action_item_order_mismatch:{name}")
        if not name:
            errors.append("credential_update_action_item_name_missing")
        if not item.get("owner_hint"):
            errors.append(f"credential_update_action_item_owner_missing:{name}")
        if item.get("target_env_file") != contract.get("target_env_file"):
            errors.append(f"credential_update_action_item_target_env_file_mismatch:{name}")
        if "gitignored_env_file" not in set(_strings(item.get("allowed_update_surface_ids"))):
            errors.append(f"credential_update_action_item_surface_missing:{name}:gitignored_env_file")
        if "process_environment" not in set(_strings(item.get("allowed_update_surface_ids"))):
            errors.append(f"credential_update_action_item_surface_missing:{name}:process_environment")
        if item.get("next_command_after_update") != "make au-p0a-env":
            errors.append(f"credential_update_action_item_next_command_invalid:{name}")
        if "--require-complete" not in str(item.get("strict_gate_command") or ""):
            errors.append(f"credential_update_action_item_strict_gate_invalid:{name}")
        if item.get("raw_secret_values_allowed") is not False:
            errors.append(f"credential_update_action_item_raw_secret_policy_invalid:{name}")
        if item.get("secret_redacted") is not True:
            errors.append(f"credential_update_action_item_secret_redaction_missing:{name}")
    if payload.get("status") != "pass":
        errors.append("status_invalid")
    if payload.get("credential_update_receipt_ready") is not True:
        errors.append("credential_update_receipt_ready_invalid")
    if payload.get("credential_update_receipt_complete") is not expected_complete:
        errors.append("credential_update_receipt_complete_mismatch")
    if payload.get("credentials_fulfilled") is not credentials_fulfilled:
        errors.append("credentials_fulfilled_mismatch")
    if payload.get("credential_clearance_ready") is not credential_clearance_ready:
        errors.append("credential_clearance_ready_mismatch")

    if contract.get("raw_values_allowed_in_artifacts") is not False:
        errors.append("credential_update_contract_raw_secret_policy_invalid")
    if not contract.get("version"):
        errors.append("credential_update_contract_version_missing")
    if "gitignored_env_file" not in set(_strings(contract.get("allowed_update_surface_ids"))):
        errors.append("credential_update_contract_surface_missing:gitignored_env_file")
    if "process_environment" not in set(_strings(contract.get("allowed_update_surface_ids"))):
        errors.append("credential_update_contract_surface_missing:process_environment")

    if summary.get("required_count") != len(required_records):
        errors.append("summary_required_count_mismatch")
    if summary.get("present_required_count") != len(present_required):
        errors.append("summary_present_required_count_mismatch")
    if summary.get("missing_required_count") != len(missing_required):
        errors.append("summary_missing_required_count_mismatch")
    if sorted(_strings(summary.get("missing_required"))) != missing_required:
        errors.append("summary_missing_required_mismatch")
    if summary.get("credential_update_action_plan_ready") is not True:
        errors.append("summary_credential_update_action_plan_ready_mismatch")
    if summary.get("credential_update_action_required") is not (not expected_complete):
        errors.append("summary_credential_update_action_required_mismatch")
    if summary.get("credential_update_action_item_count") != len(missing_records):
        errors.append("summary_credential_update_action_item_count_mismatch")
    if _as_dict(summary.get("credential_update_action_owner_counts")) != _owner_counts(action_items):
        errors.append("summary_credential_update_action_owner_counts_mismatch")
    if summary.get("credential_update_post_update_validation_command_count") != len(validation_sequence):
        errors.append("summary_credential_update_post_update_validation_command_count_mismatch")
    if summary.get("env_file_hygiene_ready") is not (env_file_hygiene.get("hygiene_ready") is True):
        errors.append("summary_env_file_hygiene_ready_mismatch")
    if summary.get("credentials_fulfilled") is not credentials_fulfilled:
        errors.append("summary_credentials_fulfilled_mismatch")
    if summary.get("credential_clearance_ready") is not credential_clearance_ready:
        errors.append("summary_credential_clearance_ready_mismatch")
    if summary.get("credential_update_receipt_ready") is not True:
        errors.append("summary_credential_update_receipt_ready_mismatch")
    if summary.get("credential_update_receipt_complete") is not expected_complete:
        errors.append("summary_credential_update_receipt_complete_mismatch")
    if summary.get("raw_secret_values_allowed") is not False:
        errors.append("summary_raw_secret_policy_invalid")

    for key, (hash_field, verifier_key) in {
        "credential_request": ("p0a_credential_request_packet_hash", "credential_request"),
        "env_report": ("environment_report_hash", "env_report"),
        "credential_fulfillment": ("p0a_credential_fulfillment_hash", "credential_fulfillment"),
        "credential_clearance": ("p0a_credential_clearance_hash", "credential_clearance"),
    }.items():
        source = _as_dict(source_artifacts.get(key))
        verifier = _as_dict(verifiers.get(verifier_key))
        expected_source_hash = str(source.get("hash") or "")
        if source.get("hash_field") != hash_field:
            errors.append(f"source_hash_field_invalid:{key}")
        if expected_source_hash != str(verifier.get(hash_field) or ""):
            errors.append(f"source_hash_mismatch:{key}")
        if current_file_check_enabled:
            _check_current_source_file(
                errors,
                source_key=f"source_{key}",
                source=source,
                hash_field=hash_field,
                expected_hash=expected_source_hash,
            )

    for field in ("path", "exists", "entry_count", "file_mode", "permission_safe", "hygiene_ready", "secret_redacted"):
        if field not in env_file_hygiene:
            errors.append(f"env_file_hygiene_field_missing:{field}")
    if env_file_hygiene.get("secret_redacted") is not True:
        errors.append("env_file_hygiene_secret_redaction_missing")
    if "raw_value" in env_file_hygiene or "value" in env_file_hygiene:
        errors.append("env_file_hygiene_raw_value_leaked")

    for command in (
        "make verify-au-p0a-env-bootstrap",
        "make au-p0a-env",
        "make verify-au-p0a-env",
        "make au-p0a-credential-fulfillment",
        "make verify-au-p0a-credential-fulfillment",
    ):
        if command not in validation_sequence:
            errors.append(f"post_update_validation_command_missing:{command}")
    if "make verify-au-p0a-credential-update-receipt" not in strict_gate_commands:
        errors.append("strict_gate_missing:make_verify_receipt")
    if not any("--require-complete" in command for command in strict_gate_commands):
        errors.append("strict_gate_missing:require_complete")
    if endpoints.get("p0a_credential_update_receipt") != "GET /v1/p0a-credential-update-receipt/au":
        errors.append("runtime_endpoint_invalid:p0a_credential_update_receipt")
    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("redaction_policy_raw_secret_invalid")
    if redaction_policy.get("secret_redacted") is not True:
        errors.append("redaction_policy_secret_redaction_missing")
    if require_complete and not expected_complete:
        errors.append("p0a_credential_update_receipt_not_complete")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0a_credential_update_receipt_version": payload.get("p0a_credential_update_receipt_version", ""),
        "p0a_credential_update_receipt_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0a_credential_update_receipt_hash": computed_hash,
        "hash_valid": hash_valid,
        "credential_update_receipt_ready": True,
        "credential_update_receipt_complete": expected_complete,
        "credentials_fulfilled": credentials_fulfilled,
        "credential_clearance_ready": credential_clearance_ready,
        "missing_required_count": len(missing_required),
        "missing_required": missing_required,
        "credential_update_action_plan_ready": action_plan.get("ready") is True,
        "credential_update_action_required": action_plan.get("action_required") is True,
        "credential_update_action_item_count": len(action_items),
        "credential_update_action_owner_counts": _owner_counts(action_items),
        "credential_update_post_update_validation_command_count": len(validation_sequence),
        "env_file_hygiene_ready": env_file_hygiene.get("hygiene_ready") is True,
        "current_file_check_enabled": current_file_check_enabled,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0a credential update receipt JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0A_CREDENTIAL_UPDATE_RECEIPT_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0a credential update receipt JSON.",
    )
    parser.add_argument("--require-complete", action="store_true", help="Fail unless the credential update is complete.")
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
            "errors": ["p0a_credential_update_receipt_file_missing"],
            "hash_valid": False,
            "credential_update_receipt_ready": False,
            "credential_update_receipt_complete": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0a_credential_update_receipt_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "credential_update_receipt_ready": False,
            "credential_update_receipt_complete": False,
        }
    else:
        result = verify_au_p0a_credential_update_receipt(payload, path=path, require_complete=args.require_complete)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
