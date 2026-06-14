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

from scripts.build_au_p0a_credential_clearance import (  # noqa: E402
    CLEARANCE_VERSION,
    DEFAULT_OUTPUT_PATH,
    STEP_ID,
    compute_p0a_credential_clearance_hash,
)


REQUIRED_FIELDS = (
    "p0a_credential_clearance_version",
    "generated_at",
    "status",
    "credential_clearance_packet_ready",
    "credentials_fulfilled",
    "credential_clearance_ready",
    "ready_for_next_clearance_step",
    "output_path",
    "clearance_step",
    "source_artifacts",
    "p0a_credential_request_verifier",
    "p0a_credential_fulfillment_verifier",
    "summary",
    "missing_credential_items",
    "operator_steps",
    "post_update_validation_sequence",
    "runtime_endpoints",
    "hard_gate_commands",
    "redaction_policy",
    "p0a_credential_clearance_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


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


def _missing_by_owner(items: list[dict[str, Any]], owner: str) -> list[str]:
    return sorted(str(item.get("name") or "") for item in items if str(item.get("owner_hint") or "") == owner)


def verify_au_p0a_credential_clearance(
    payload: Any,
    *,
    path: Path | None = None,
    require_cleared: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0a_credential_clearance_not_json_object"],
            "hash_valid": False,
            "credential_clearance_packet_ready": False,
            "credential_clearance_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0a_credential_clearance_version") != CLEARANCE_VERSION:
        errors.append("p0a_credential_clearance_version_invalid")
    for finding in _find_forbidden_secret_fields(payload):
        errors.append(f"forbidden_secret_field:{finding}")

    expected_hash = payload.get("p0a_credential_clearance_hash")
    computed_hash = compute_p0a_credential_clearance_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0a_credential_clearance_hash_mismatch")

    request_verifier = _as_dict(payload.get("p0a_credential_request_verifier"))
    fulfillment_verifier = _as_dict(payload.get("p0a_credential_fulfillment_verifier"))
    source_artifacts = _as_dict(payload.get("source_artifacts"))
    request_source = _as_dict(source_artifacts.get("credential_request"))
    fulfillment_source = _as_dict(source_artifacts.get("credential_fulfillment"))
    clearance_source = _as_dict(source_artifacts.get("external_dependency_clearance"))
    summary = _as_dict(payload.get("summary"))
    clearance_step = _as_dict(payload.get("clearance_step"))
    missing_items = [_as_dict(item) for item in _as_list(payload.get("missing_credential_items"))]
    operator_steps = [_as_dict(item) for item in _as_list(payload.get("operator_steps"))]
    validation_sequence = _strings(payload.get("post_update_validation_sequence"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    hard_gate_commands = _strings(payload.get("hard_gate_commands"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))

    request_ok = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    fulfillment_ok = fulfillment_verifier.get("status") == "pass" and fulfillment_verifier.get("hash_valid") is True
    clearance_ok = str(clearance_source.get("verifier_status") or "") in {"pass", ""}
    expected_packet_ready = request_ok and fulfillment_ok and clearance_ok
    if payload.get("credential_clearance_packet_ready") is not expected_packet_ready:
        errors.append("credential_clearance_packet_ready_mismatch")
    if payload.get("status") != ("pass" if expected_packet_ready else "fail"):
        errors.append("status_mismatch")

    credentials_fulfilled = fulfillment_verifier.get("credentials_fulfilled") is True
    if payload.get("credentials_fulfilled") is not credentials_fulfilled:
        errors.append("credentials_fulfilled_mismatch")
    current_step_matches = clearance_step.get("current_step_matches") is True
    expected_cleared = credentials_fulfilled and current_step_matches
    if payload.get("credential_clearance_ready") is not expected_cleared:
        errors.append("credential_clearance_ready_mismatch")
    if payload.get("ready_for_next_clearance_step") is not expected_cleared:
        errors.append("ready_for_next_clearance_step_mismatch")
    if clearance_step.get("id") != STEP_ID:
        errors.append("clearance_step_id_invalid")
    if summary.get("current_clearance_step_id") != clearance_step.get("current_step_id"):
        errors.append("summary_current_clearance_step_id_mismatch")
    if summary.get("clearance_step_matches") is not current_step_matches:
        errors.append("summary_clearance_step_matches_mismatch")

    if request_source.get("hash") != request_verifier.get("p0a_credential_request_packet_hash"):
        errors.append("source_request_hash_mismatch")
    if fulfillment_source.get("hash") != fulfillment_verifier.get("p0a_credential_fulfillment_hash"):
        errors.append("source_fulfillment_hash_mismatch")
    if request_source.get("hash_field") != "p0a_credential_request_packet_hash":
        errors.append("source_request_hash_field_invalid")
    if fulfillment_source.get("hash_field") != "p0a_credential_fulfillment_hash":
        errors.append("source_fulfillment_hash_field_invalid")
    if clearance_source.get("hash_field") != "clearance_execution_hash":
        errors.append("source_clearance_hash_field_invalid")

    missing_names = sorted(str(item.get("name") or "") for item in missing_items)
    if summary.get("missing_required_count") != len(missing_items):
        errors.append("summary_missing_required_count_mismatch")
    if sorted(_strings(summary.get("missing_required"))) != missing_names:
        errors.append("summary_missing_required_mismatch")
    if _strings(summary.get("provider_missing_required")) != _missing_by_owner(missing_items, "provider_admin"):
        errors.append("summary_provider_missing_required_mismatch")
    if _strings(summary.get("runtime_database_missing_required")) != _missing_by_owner(
        missing_items,
        "runtime_database_admin",
    ):
        errors.append("summary_runtime_database_missing_required_mismatch")
    if summary.get("operator_step_count") != len(operator_steps):
        errors.append("summary_operator_step_count_mismatch")
    if summary.get("post_update_validation_command_count") != len(validation_sequence):
        errors.append("summary_post_update_validation_command_count_mismatch")
    if summary.get("raw_secret_values_allowed") is not False:
        errors.append("summary_raw_secret_policy_invalid")
    if not isinstance(summary.get("strict_gate_command"), str) or "--require-fulfilled" not in str(
        summary.get("strict_gate_command") or ""
    ):
        errors.append("summary_strict_gate_command_invalid")

    required_step_ids = {
        "verify_p0a_env_template",
        "bootstrap_local_env_file",
        "populate_missing_credentials",
        "refresh_redacted_env_report",
        "verify_fulfillment",
        "run_strict_gate",
    }
    step_ids = {str(step.get("id") or "") for step in operator_steps}
    for step_id in required_step_ids:
        if step_id not in step_ids:
            errors.append(f"operator_step_missing:{step_id}")
    for step in operator_steps:
        if not isinstance(step.get("order"), int):
            errors.append(f"operator_step_order_invalid:{step.get('id')}")
        if not str(step.get("command") or ""):
            errors.append(f"operator_step_command_missing:{step.get('id')}")

    for item in missing_items:
        name = str(item.get("name") or "")
        for field in (
            "owner_hint",
            "env_file_key",
            "target_env_file",
            "request_present",
            "environment_present",
            "accepted_injection_methods",
            "post_update_checks",
            "blocking_reasons",
            "raw_value_required_in_packet",
        ):
            if field not in item:
                errors.append(f"missing_credential_item_field_missing:{name}:{field}")
        if item.get("raw_value_required_in_packet") is not False:
            errors.append(f"missing_credential_item_raw_value_policy_invalid:{name}")

    for command in (
        "make verify-au-p0a-env-bootstrap",
        "make au-p0a-env",
        "make verify-au-p0a-env",
        "make au-p0a-credential-fulfillment",
        "make verify-au-p0a-credential-fulfillment",
    ):
        if command not in validation_sequence:
            errors.append(f"post_update_validation_command_missing:{command}")
    if not any("--require-fulfilled" in command for command in validation_sequence):
        errors.append("post_update_validation_missing_require_fulfilled")

    expected_endpoints = {
        "p0a_credential_clearance": "GET /v1/p0a-credential-clearance/au",
        "p0a_credential_request": "GET /v1/p0a-credential-request/au",
        "p0a_credential_fulfillment": "GET /v1/p0a-credential-fulfillment/au",
        "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
        "delivery_progress": "GET /v1/delivery-progress/au",
    }
    for key, expected in expected_endpoints.items():
        if endpoints.get(key) != expected:
            errors.append(f"runtime_endpoint_invalid:{key}")
    for command in (
        "make au-p0a-credential-clearance",
        "make verify-au-p0a-credential-clearance",
        "make au-p0a-credential-request",
        "make verify-au-p0a-credential-request",
        "make au-p0a-credential-fulfillment",
        "make verify-au-p0a-credential-fulfillment",
    ):
        if command not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{command}")
    if not any("--require-cleared" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_cleared")
    if not any("--require-fulfilled" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_fulfilled")
    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("redaction_policy_raw_secret_invalid")
    if redaction_policy.get("secret_redacted") is not True:
        errors.append("redaction_policy_secret_redaction_missing")
    if require_cleared and not expected_cleared:
        errors.append("p0a_credentials_not_cleared")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0a_credential_clearance_version": payload.get("p0a_credential_clearance_version", ""),
        "p0a_credential_clearance_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0a_credential_clearance_hash": computed_hash,
        "hash_valid": hash_valid,
        "credential_clearance_packet_ready": expected_packet_ready,
        "credential_clearance_ready": expected_cleared,
        "credentials_fulfilled": credentials_fulfilled,
        "missing_required_count": len(missing_items),
        "missing_required": missing_names,
        "current_clearance_step_id": clearance_step.get("current_step_id", ""),
        "next_command": summary.get("next_command", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0a credential clearance JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0A_CREDENTIAL_CLEARANCE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0a credential clearance JSON.",
    )
    parser.add_argument("--require-cleared", action="store_true", help="Fail unless P0a credentials are cleared.")
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
            "errors": ["p0a_credential_clearance_file_missing"],
            "hash_valid": False,
            "credential_clearance_packet_ready": False,
            "credential_clearance_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0a_credential_clearance_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "credential_clearance_packet_ready": False,
            "credential_clearance_ready": False,
        }
    else:
        result = verify_au_p0a_credential_clearance(payload, path=path, require_cleared=args.require_cleared)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
