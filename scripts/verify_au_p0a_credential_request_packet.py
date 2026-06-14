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

from scripts.build_au_p0a_credential_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    PACKET_VERSION,
    compute_p0a_credential_request_packet_hash,
)


REQUIRED_FIELDS = (
    "p0a_credential_request_packet_version",
    "generated_at",
    "status",
    "credential_request_packet_ready",
    "credential_handoff_ready",
    "ready_for_design_partner",
    "output_path",
    "source_p0a_execution_checklist",
    "p0a_execution_checklist_verifier",
    "summary",
    "requested_credentials",
    "setup_commands",
    "verification_commands",
    "evidence_outputs",
    "redaction_policy",
    "runtime_endpoints",
    "hard_gate_commands",
    "evidence_sources",
    "p0a_credential_request_packet_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _find_forbidden_secret_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {"value", "raw_value"}:
                findings.append(child_path)
            findings.extend(_find_forbidden_secret_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_secret_fields(child, path=f"{path}[{index}]"))
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
        if item.get("required") is True and item.get("present") is not True:
            owner = str(item.get("owner_hint") or "unknown")
            owners.setdefault(owner, []).append(str(item.get("name") or ""))
    return {owner: sorted(names) for owner, names in sorted(owners.items())}


def verify_au_p0a_credential_request_packet(
    payload: Any,
    *,
    path: Path | None = None,
    require_credentials_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0a_credential_request_packet_not_json_object"],
            "hash_valid": False,
            "credential_request_packet_ready": False,
            "credential_handoff_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0a_credential_request_packet_version") != PACKET_VERSION:
        errors.append("p0a_credential_request_packet_version_invalid")

    expected_hash = payload.get("p0a_credential_request_packet_hash")
    computed_hash = compute_p0a_credential_request_packet_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0a_credential_request_packet_hash_mismatch")

    verifier = _as_dict(payload.get("p0a_execution_checklist_verifier"))
    source = _as_dict(payload.get("source_p0a_execution_checklist"))
    summary = _as_dict(payload.get("summary"))
    requested_credentials = [_as_dict(item) for item in _as_list(payload.get("requested_credentials"))]
    setup_commands = _string_list(payload.get("setup_commands"))
    verification_commands = _string_list(payload.get("verification_commands"))
    evidence_outputs = _string_list(payload.get("evidence_outputs"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    hard_gate_commands = _string_list(payload.get("hard_gate_commands"))

    expected_ready = verifier.get("status") == "pass" and verifier.get("hash_valid") is True
    if payload.get("credential_request_packet_ready") is not expected_ready:
        errors.append("credential_request_packet_ready_mismatch")
    if payload.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")
    if source.get("p0a_execution_checklist_hash") != verifier.get("p0a_execution_checklist_hash") and verifier.get(
        "p0a_execution_checklist_hash"
    ):
        errors.append("source_p0a_execution_checklist_hash_mismatch")

    required_names = {"PERPLEXITY_API_KEY", "OPENAI_API_KEY", "DATABASE_URL"}
    item_names = {str(item.get("name") or "") for item in requested_credentials}
    for name in required_names:
        if name not in item_names:
            errors.append(f"requested_credential_missing:{name}")
    missing_required = sorted(
        str(item.get("name") or "")
        for item in requested_credentials
        if item.get("required") is True and item.get("present") is not True
    )
    if sorted(_string_list(summary.get("missing_required"))) != missing_required:
        errors.append("summary_missing_required_mismatch")
    if summary.get("missing_required_count") != len(missing_required):
        errors.append("summary_missing_required_count_mismatch")
    if payload.get("credential_handoff_ready") is not (not missing_required):
        errors.append("credential_handoff_ready_mismatch")
    if summary.get("credential_handoff_ready") is not (not missing_required):
        errors.append("summary_credential_handoff_ready_mismatch")
    if summary.get("credential_item_count") != len(requested_credentials):
        errors.append("summary_credential_item_count_mismatch")
    if summary.get("required_item_count") != sum(1 for item in requested_credentials if item.get("required") is True):
        errors.append("summary_required_item_count_mismatch")
    if summary.get("present_required_count") != sum(
        1 for item in requested_credentials if item.get("required") is True and item.get("present") is True
    ):
        errors.append("summary_present_required_count_mismatch")
    if summary.get("owner_counts") != _owner_counts(requested_credentials):
        errors.append("summary_owner_counts_mismatch")
    if summary.get("missing_required_by_owner") != _missing_by_owner(requested_credentials):
        errors.append("summary_missing_required_by_owner_mismatch")
    if summary.get("setup_command_count") != len(setup_commands):
        errors.append("summary_setup_command_count_mismatch")
    if summary.get("verification_command_count") != len(verification_commands):
        errors.append("summary_verification_command_count_mismatch")
    if summary.get("evidence_output_count") != len(evidence_outputs):
        errors.append("summary_evidence_output_count_mismatch")
    if summary.get("raw_secret_values_allowed") is not False:
        errors.append("summary_raw_secret_policy_invalid")
    if summary.get("forbidden_exact_secret_fields_redacted") is not True:
        errors.append("summary_forbidden_field_redaction_missing")
    if setup_commands and summary.get("next_command") != setup_commands[0]:
        errors.append("summary_next_command_mismatch")
    if verification_commands and summary.get("post_update_verification_command") != verification_commands[0]:
        errors.append("summary_post_update_verification_command_mismatch")

    for command in (
        "make verify-au-p0a-env-template",
        "make au-p0a-env-bootstrap",
        "make verify-au-p0a-env-bootstrap",
    ):
        if command not in setup_commands:
            errors.append(f"setup_command_missing:{command}")
    for command in (
        "make au-p0a-env",
        "make verify-au-p0a-env",
        "make au-p0a-status",
        "make verify-au-p0a-status",
    ):
        if command not in verification_commands:
            errors.append(f"verification_command_missing:{command}")
    for output in (
        "docs/runtime_preflight/au-p0a-env-bootstrap-latest.json",
        "docs/runtime_preflight/au-p0a-env-latest.json",
        "docs/runtime_preflight/au-p0a-status-latest.json",
    ):
        if output not in evidence_outputs:
            errors.append(f"evidence_output_missing:{output}")

    for item in requested_credentials:
        name = str(item.get("name") or "")
        for field in (
            "required",
            "present",
            "source",
            "owner_hint",
            "accepted_injection_methods",
            "env_file_key",
            "value_length",
            "sha256_prefix",
            "secret_redacted",
            "post_update_checks",
        ):
            if field not in item:
                errors.append(f"requested_credential_field_missing:{name}:{field}")
        if item.get("env_file_key") != name:
            errors.append(f"requested_credential_env_key_mismatch:{name}")
        if item.get("secret_redacted") is not True:
            errors.append(f"requested_credential_secret_redaction_missing:{name}")
        accepted_methods = {str(value) for value in _as_list(item.get("accepted_injection_methods"))}
        if not {"process_environment", "GENO_AU_P0A_ENV_FILE", ".env.au-p0a"}.issubset(accepted_methods):
            errors.append(f"requested_credential_injection_methods_incomplete:{name}")

    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("redaction_policy_raw_secret_invalid")
    if redaction_policy.get("forbidden_exact_secret_fields_redacted") is not True:
        errors.append("redaction_policy_forbidden_field_redaction_missing")
    if redaction_policy.get("forbidden_exact_secret_field_count") != 2:
        errors.append("redaction_policy_forbidden_field_count_invalid")
    for finding in _find_forbidden_secret_fields(payload):
        errors.append(f"forbidden_secret_field:{finding}")

    if endpoints.get("p0a_credential_request") != "GET /v1/p0a-credential-request/au":
        errors.append("runtime_endpoint_p0a_credential_request_invalid")
    if endpoints.get("p0a_execution_checklist") != "GET /v1/p0a-execution-checklist/au":
        errors.append("runtime_endpoint_p0a_execution_checklist_invalid")
    if endpoints.get("external_dependency_handoff") != "GET /v1/external-dependency-handoff/au":
        errors.append("runtime_endpoint_external_dependency_handoff_invalid")
    for required in (
        "make au-p0a-credential-request",
        "make verify-au-p0a-credential-request",
        "make au-p0a-env",
        "make verify-au-p0a-env",
    ):
        if required not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{required}")
    if not any(command.endswith("--require-ready-environment") for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_ready_environment")
    if require_credentials_ready and payload.get("credential_handoff_ready") is not True:
        errors.append("p0a_credentials_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0a_credential_request_packet_version": payload.get("p0a_credential_request_packet_version", ""),
        "p0a_credential_request_packet_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0a_credential_request_packet_hash": computed_hash,
        "hash_valid": hash_valid,
        "credential_request_packet_ready": expected_ready,
        "credential_handoff_ready": payload.get("credential_handoff_ready") is True,
        "missing_required_count": len(missing_required),
        "target_env_file": summary.get("target_env_file", ""),
        "next_command": summary.get("next_command", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0a credential request packet JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0A_CREDENTIAL_REQUEST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0a credential request packet JSON.",
    )
    parser.add_argument(
        "--require-credentials-ready",
        action="store_true",
        help="Fail unless all required P0a credentials are recorded as present.",
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
            "errors": ["p0a_credential_request_packet_file_missing"],
            "hash_valid": False,
            "credential_request_packet_ready": False,
            "credential_handoff_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0a_credential_request_packet_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "credential_request_packet_ready": False,
            "credential_handoff_ready": False,
        }
    else:
        result = verify_au_p0a_credential_request_packet(
            payload,
            path=path,
            require_credentials_ready=args.require_credentials_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
