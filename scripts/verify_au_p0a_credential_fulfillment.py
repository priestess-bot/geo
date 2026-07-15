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

from scripts.build_au_p0a_credential_fulfillment import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    FULFILLMENT_VERSION,
    compute_p0a_credential_fulfillment_hash,
)


REQUIRED_FIELDS = (
    "p0a_credential_fulfillment_version",
    "generated_at",
    "status",
    "credential_fulfillment_ready",
    "credentials_fulfilled",
    "ready_for_design_partner",
    "output_path",
    "source_p0a_credential_request",
    "source_p0a_env_report",
    "p0a_credential_request_verifier",
    "p0a_env_report_verifier",
    "summary",
    "credential_fulfillment_items",
    "verification_commands",
    "hard_gate_commands",
    "runtime_endpoints",
    "redaction_policy",
    "p0a_credential_fulfillment_hash",
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
            owners.setdefault(owner, []).append(str(item.get("name") or ""))
    return {owner: sorted(names) for owner, names in sorted(owners.items())}


def verify_au_p0a_credential_fulfillment(
    payload: Any,
    *,
    path: Path | None = None,
    require_fulfilled: bool = False,
    verify_current_files: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0a_credential_fulfillment_not_json_object"],
            "hash_valid": False,
            "credential_fulfillment_ready": False,
            "credentials_fulfilled": False,
            "current_file_check_enabled": path is not None if verify_current_files is None else verify_current_files,
        }

    current_file_check_enabled = path is not None if verify_current_files is None else verify_current_files
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0a_credential_fulfillment_version") != FULFILLMENT_VERSION:
        errors.append("p0a_credential_fulfillment_version_invalid")
    for finding in _find_forbidden_secret_fields(payload):
        errors.append(f"forbidden_secret_field:{finding}")

    expected_hash = payload.get("p0a_credential_fulfillment_hash")
    computed_hash = compute_p0a_credential_fulfillment_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0a_credential_fulfillment_hash_mismatch")

    request_verifier = _as_dict(payload.get("p0a_credential_request_verifier"))
    env_verifier = _as_dict(payload.get("p0a_env_report_verifier"))
    summary = _as_dict(payload.get("summary"))
    source_request = _as_dict(payload.get("source_p0a_credential_request"))
    source_env = _as_dict(payload.get("source_p0a_env_report"))
    items = [_as_dict(item) for item in _as_list(payload.get("credential_fulfillment_items"))]
    verification_commands = _strings(payload.get("verification_commands"))
    hard_gate_commands = _strings(payload.get("hard_gate_commands"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))

    request_ok = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    env_ok = env_verifier.get("status") == "pass" and env_verifier.get("hash_valid") is True
    expected_ready = request_ok and env_ok
    if payload.get("credential_fulfillment_ready") is not expected_ready:
        errors.append("credential_fulfillment_ready_mismatch")
    if payload.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")
    if source_request.get("p0a_credential_request_packet_hash") != request_verifier.get(
        "p0a_credential_request_packet_hash"
    ):
        errors.append("source_p0a_credential_request_hash_mismatch")
    if source_env.get("environment_report_hash") != env_verifier.get("environment_report_hash"):
        errors.append("source_p0a_env_report_hash_mismatch")
    if current_file_check_enabled:
        _check_current_source_file(
            errors,
            source_key="source_p0a_credential_request",
            source=source_request,
            hash_field="p0a_credential_request_packet_hash",
            expected_hash=str(source_request.get("p0a_credential_request_packet_hash") or ""),
        )
        _check_current_source_file(
            errors,
            source_key="source_p0a_env_report",
            source=source_env,
            hash_field="environment_report_hash",
            expected_hash=str(source_env.get("environment_report_hash") or ""),
        )

    required_names = {"PERPLEXITY_API_KEY", "OPENAI_API_KEY", "DATABASE_URL"}
    item_names = {str(item.get("name") or "") for item in items}
    for name in required_names:
        if name not in item_names:
            errors.append(f"credential_fulfillment_item_missing:{name}")

    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("name") or "") for item in required_items if item.get("fulfilled") is not True)
    mismatches = sorted(str(item.get("name") or "") for item in items if item.get("presence_mismatch") is True)
    credentials_fulfilled = bool(required_items) and len(fulfilled_required) == len(required_items) and not mismatches
    if payload.get("credentials_fulfilled") is not credentials_fulfilled:
        errors.append("credentials_fulfilled_mismatch")
    if payload.get("ready_for_design_partner") is True and not credentials_fulfilled:
        errors.append("ready_for_design_partner_without_fulfilled_credentials")
    if summary.get("credentials_fulfilled") is not credentials_fulfilled:
        errors.append("summary_credentials_fulfilled_mismatch")
    if summary.get("credential_handoff_ready") is not source_request.get("credential_handoff_ready"):
        errors.append("summary_credential_handoff_ready_mismatch")
    if summary.get("environment_ready") is not env_verifier.get("ready_for_real_batch"):
        errors.append("summary_environment_ready_mismatch")
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
    if summary.get("raw_secret_values_allowed") is not False:
        errors.append("summary_raw_secret_policy_invalid")
    if not isinstance(summary.get("strict_gate_command"), str) or "--require-fulfilled" not in summary.get(
        "strict_gate_command",
        "",
    ):
        errors.append("summary_strict_gate_command_missing")

    for item in items:
        name = str(item.get("name") or "")
        for field in (
            "required",
            "fulfilled",
            "requested_present",
            "environment_present",
            "presence_mismatch",
            "request_source",
            "environment_source",
            "owner_hint",
            "env_file_key",
            "value_length",
            "sha256_prefix",
            "secret_redacted",
            "accepted_injection_methods",
            "post_update_checks",
            "blocking_reasons",
        ):
            if field not in item:
                errors.append(f"credential_fulfillment_item_field_missing:{name}:{field}")
        if item.get("required") is True:
            expected_fulfilled = (
                item.get("requested_present") is True
                and item.get("environment_present") is True
                and item.get("presence_mismatch") is not True
            )
            if item.get("fulfilled") is not expected_fulfilled:
                errors.append(f"credential_fulfillment_item_fulfilled_mismatch:{name}")
        if item.get("presence_mismatch") is not (item.get("requested_present") is not item.get("environment_present")):
            errors.append(f"credential_fulfillment_item_presence_mismatch_invalid:{name}")
        if item.get("secret_redacted") is not True:
            errors.append(f"credential_fulfillment_item_secret_redaction_missing:{name}")
        if item.get("fulfilled") is True and _as_list(item.get("blocking_reasons")):
            errors.append(f"credential_fulfillment_item_blocking_reasons_on_fulfilled:{name}")

    for command in (
        "make au-p0a-credential-request",
        "make verify-au-p0a-credential-request",
        "make au-p0a-env",
        "make verify-au-p0a-env",
        "make verify-au-p0a-credential-fulfillment",
    ):
        if command not in verification_commands:
            errors.append(f"verification_command_missing:{command}")
    if "make verify-au-p0a-credential-fulfillment" not in hard_gate_commands:
        errors.append("hard_gate_missing:make verify-au-p0a-credential-fulfillment")
    if not any("--require-fulfilled" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_fulfilled")
    if endpoints.get("p0a_credential_fulfillment") != "GET /v1/p0a-credential-fulfillment/au":
        errors.append("runtime_endpoint_p0a_credential_fulfillment_invalid")
    if endpoints.get("p0a_credential_request") != "GET /v1/p0a-credential-request/au":
        errors.append("runtime_endpoint_p0a_credential_request_invalid")
    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("redaction_policy_raw_secret_invalid")
    if redaction_policy.get("secret_redacted") is not True:
        errors.append("redaction_policy_secret_redaction_missing")
    if require_fulfilled and not credentials_fulfilled:
        errors.append("p0a_credentials_not_fulfilled")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0a_credential_fulfillment_version": payload.get("p0a_credential_fulfillment_version", ""),
        "p0a_credential_fulfillment_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0a_credential_fulfillment_hash": computed_hash,
        "hash_valid": hash_valid,
        "credential_fulfillment_ready": expected_ready,
        "credentials_fulfilled": credentials_fulfilled,
        "current_file_check_enabled": current_file_check_enabled,
        "missing_required_count": len(missing_required),
        "missing_required": missing_required,
        "next_action": summary.get("next_action", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0a credential fulfillment JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0A_CREDENTIAL_FULFILLMENT_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0a credential fulfillment JSON.",
    )
    parser.add_argument("--require-fulfilled", action="store_true", help="Fail unless P0a credentials are fulfilled.")
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
            "errors": ["p0a_credential_fulfillment_file_missing"],
            "hash_valid": False,
            "credential_fulfillment_ready": False,
            "credentials_fulfilled": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0a_credential_fulfillment_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "credential_fulfillment_ready": False,
            "credentials_fulfilled": False,
        }
    else:
        result = verify_au_p0a_credential_fulfillment(payload, path=path, require_fulfilled=args.require_fulfilled)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
