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

from scripts.build_au_p0b_google_environment_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    PACKET_VERSION,
    compute_p0b_google_environment_request_packet_hash,
)


REQUIRED_FIELDS = (
    "p0b_google_environment_request_packet_version",
    "generated_at",
    "status",
    "google_environment_request_packet_ready",
    "environment_handoff_ready",
    "google_main_scoring_allowed",
    "output_path",
    "source_p0b_google_execution_checklist",
    "p0b_google_execution_checklist_verifier",
    "summary",
    "environment_items",
    "selector_items",
    "file_items",
    "dependency_items",
    "setup_commands",
    "verification_commands",
    "evidence_outputs",
    "redaction_policy",
    "runtime_endpoints",
    "hard_gate_commands",
    "evidence_sources",
    "p0b_google_environment_request_packet_hash",
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


def _environment_missing(item: dict[str, Any]) -> str:
    name = str(item.get("name") or "")
    gate = str(item.get("gate") or "")
    if gate == "playwright_smoke":
        return f"smoke_env:{name}"
    if gate == "full_google_run":
        return f"full_run_env:{name}"
    return f"environment:{name}"


def _file_issue(item: dict[str, Any], environment_missing: set[str]) -> str:
    name = str(item.get("name") or "")
    expected_type = str(item.get("expected_type") or "")
    present = item.get("present") is True
    if name == "MANUAL_BACKFILL_PATH" and (not present or item.get("is_file") is not True):
        if "full_run_env:MANUAL_BACKFILL_PATH" in environment_missing:
            return ""
        return f"file_gate:{name}:file_missing"
    if present and expected_type == "file" and item.get("is_file") is not True:
        return f"file_gate:{name}:file_missing"
    if present and expected_type == "directory" and item.get("is_dir") is not True:
        return f"file_gate:{name}:directory_missing"
    return ""


def _missing_by_owner(
    environment_items: list[dict[str, Any]],
    selector_items: list[dict[str, Any]],
    file_items: list[dict[str, Any]],
    dependency_items: list[dict[str, Any]],
) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    environment_missing: set[str] = set()
    for item in environment_items:
        if item.get("required") is True and (item.get("present") is not True or item.get("truthy") is False):
            missing = _environment_missing(item)
            environment_missing.add(missing)
            owners.setdefault(str(item.get("owner_hint") or "unknown"), []).append(missing)
    for item in selector_items:
        if item.get("present") is not True:
            owners.setdefault(str(item.get("owner_hint") or "unknown"), []).append(
                f"selector_group:{item.get('group') or ''}"
            )
    for item in dependency_items:
        if item.get("present") is not True:
            owners.setdefault(str(item.get("owner_hint") or "unknown"), []).append(
                f"dependency:{item.get('name') or ''}"
            )
    for item in file_items:
        issue = _file_issue(item, environment_missing)
        if issue:
            owners.setdefault(str(item.get("owner_hint") or "unknown"), []).append(issue)
    return {owner: sorted(names) for owner, names in sorted(owners.items())}


def _validate_environment_item(item: dict[str, Any], errors: list[str]) -> str:
    name = str(item.get("name") or "")
    if not name:
        errors.append("environment_item_name_missing")
        return ""
    for field in (
        "gate",
        "required",
        "present",
        "truthy",
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
            errors.append(f"environment_item_field_missing:{name}:{field}")
    if item.get("env_file_key") != name:
        errors.append(f"environment_item_env_key_mismatch:{name}")
    if item.get("secret_redacted") is not True:
        errors.append(f"environment_item_secret_redaction_missing:{name}")
    accepted_methods = {str(value) for value in _as_list(item.get("accepted_injection_methods"))}
    if not {"process_environment", "GENO_AU_P0B_GOOGLE_ENV_FILE", ".env.au-p0b-google"}.issubset(accepted_methods):
        errors.append(f"environment_item_injection_methods_incomplete:{name}")
    if item.get("present") is True:
        if not isinstance(item.get("value_length"), int) or item.get("value_length") <= 0:
            errors.append(f"environment_item_value_length_invalid:{name}")
        if not isinstance(item.get("sha256_prefix"), str) or len(item.get("sha256_prefix")) != 12:
            errors.append(f"environment_item_sha256_prefix_invalid:{name}")
        if item.get("truthy") is False:
            return _environment_missing(item)
        return ""
    if item.get("present") is False:
        if item.get("value_length") not in {0, None}:
            errors.append(f"environment_item_missing_value_length_invalid:{name}")
        if item.get("sha256_prefix") not in {"", None}:
            errors.append(f"environment_item_missing_sha256_prefix_invalid:{name}")
        return _environment_missing(item)
    errors.append(f"environment_item_present_invalid:{name}")
    return ""


def _validate_selector_item(item: dict[str, Any], errors: list[str]) -> str:
    group = str(item.get("group") or "")
    if not group:
        errors.append("selector_item_group_missing")
        return ""
    for field in (
        "candidate_names",
        "present",
        "selected_name",
        "source",
        "owner_hint",
        "accepted_injection_methods",
        "value_length",
        "sha256_prefix",
        "secret_redacted",
        "post_update_checks",
    ):
        if field not in item:
            errors.append(f"selector_item_field_missing:{group}:{field}")
    if item.get("secret_redacted") is not True:
        errors.append(f"selector_item_secret_redaction_missing:{group}")
    accepted_methods = {str(value) for value in _as_list(item.get("accepted_injection_methods"))}
    if not {"process_environment", "GENO_AU_P0B_GOOGLE_ENV_FILE", ".env.au-p0b-google"}.issubset(accepted_methods):
        errors.append(f"selector_item_injection_methods_incomplete:{group}")
    if item.get("present") is True:
        if not item.get("selected_name"):
            errors.append(f"selector_item_selected_name_missing:{group}")
        if not isinstance(item.get("value_length"), int) or item.get("value_length") <= 0:
            errors.append(f"selector_item_value_length_invalid:{group}")
        if not isinstance(item.get("sha256_prefix"), str) or len(item.get("sha256_prefix")) != 12:
            errors.append(f"selector_item_sha256_prefix_invalid:{group}")
        return ""
    if item.get("present") is False:
        return f"selector_group:{group}"
    errors.append(f"selector_item_present_invalid:{group}")
    return ""


def _validate_file_item(item: dict[str, Any], environment_missing: set[str], errors: list[str]) -> str:
    name = str(item.get("name") or "")
    if not name:
        errors.append("file_item_name_missing")
        return ""
    for field in (
        "expected_type",
        "present",
        "exists",
        "is_file",
        "is_dir",
        "source",
        "owner_hint",
        "accepted_injection_methods",
        "value_length",
        "sha256_prefix",
        "secret_redacted",
        "post_update_checks",
    ):
        if field not in item:
            errors.append(f"file_item_field_missing:{name}:{field}")
    if item.get("secret_redacted") is not True:
        errors.append(f"file_item_secret_redaction_missing:{name}")
    accepted_methods = {str(value) for value in _as_list(item.get("accepted_injection_methods"))}
    if not {"process_environment", "GENO_AU_P0B_GOOGLE_ENV_FILE", ".env.au-p0b-google"}.issubset(accepted_methods):
        errors.append(f"file_item_injection_methods_incomplete:{name}")
    return _file_issue(item, environment_missing)


def _validate_dependency_item(item: dict[str, Any], errors: list[str]) -> str:
    name = str(item.get("name") or "")
    if not name:
        errors.append("dependency_item_name_missing")
        return ""
    for field in ("present", "source", "owner_hint", "secret_redacted", "post_update_checks"):
        if field not in item:
            errors.append(f"dependency_item_field_missing:{name}:{field}")
    if item.get("secret_redacted") is not True:
        errors.append(f"dependency_item_secret_redaction_missing:{name}")
    if item.get("present") is False:
        return f"dependency:{name}"
    if item.get("present") is not True:
        errors.append(f"dependency_item_present_invalid:{name}")
    return ""


def verify_au_p0b_google_environment_request_packet(
    payload: Any,
    *,
    path: Path | None = None,
    require_environment_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0b_google_environment_request_packet_not_json_object"],
            "hash_valid": False,
            "google_environment_request_packet_ready": False,
            "environment_handoff_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0b_google_environment_request_packet_version") != PACKET_VERSION:
        errors.append("p0b_google_environment_request_packet_version_invalid")

    expected_hash = payload.get("p0b_google_environment_request_packet_hash")
    computed_hash = compute_p0b_google_environment_request_packet_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0b_google_environment_request_packet_hash_mismatch")

    verifier = _as_dict(payload.get("p0b_google_execution_checklist_verifier"))
    source = _as_dict(payload.get("source_p0b_google_execution_checklist"))
    summary = _as_dict(payload.get("summary"))
    environment_items = [_as_dict(item) for item in _as_list(payload.get("environment_items"))]
    selector_items = [_as_dict(item) for item in _as_list(payload.get("selector_items"))]
    file_items = [_as_dict(item) for item in _as_list(payload.get("file_items"))]
    dependency_items = [_as_dict(item) for item in _as_list(payload.get("dependency_items"))]
    setup_commands = _string_list(payload.get("setup_commands"))
    verification_commands = _string_list(payload.get("verification_commands"))
    evidence_outputs = _string_list(payload.get("evidence_outputs"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    hard_gate_commands = _string_list(payload.get("hard_gate_commands"))

    expected_ready = verifier.get("status") == "pass" and verifier.get("hash_valid") is True
    if payload.get("google_environment_request_packet_ready") is not expected_ready:
        errors.append("google_environment_request_packet_ready_mismatch")
    if payload.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")
    if source.get("google_execution_checklist_hash") != verifier.get("google_execution_checklist_hash") and verifier.get(
        "google_execution_checklist_hash"
    ):
        errors.append("source_p0b_google_execution_checklist_hash_mismatch")

    observed_environment_missing: list[str] = []
    for item in environment_items:
        missing = _validate_environment_item(item, errors)
        if missing:
            observed_environment_missing.append(missing)
    environment_missing_set = set(observed_environment_missing)
    observed_selector_missing: list[str] = []
    for item in selector_items:
        missing = _validate_selector_item(item, errors)
        if missing:
            observed_selector_missing.append(missing)
    observed_dependency_missing: list[str] = []
    for item in dependency_items:
        missing = _validate_dependency_item(item, errors)
        if missing:
            observed_dependency_missing.append(missing)
    observed_file_issues: list[str] = []
    for item in file_items:
        issue = _validate_file_item(item, environment_missing_set, errors)
        if issue:
            observed_file_issues.append(issue)

    expected_missing = sorted(
        [*observed_environment_missing, *observed_selector_missing, *observed_dependency_missing, *observed_file_issues]
    )
    if sorted(_string_list(summary.get("missing_required"))) != expected_missing:
        errors.append("summary_missing_required_mismatch")
    if summary.get("missing_required_count") != len(expected_missing):
        errors.append("summary_missing_required_count_mismatch")
    if payload.get("environment_handoff_ready") is not (not expected_missing):
        errors.append("environment_handoff_ready_mismatch")
    if summary.get("environment_handoff_ready") is not (not expected_missing):
        errors.append("summary_environment_handoff_ready_mismatch")
    if summary.get("environment_item_count") != len(environment_items):
        errors.append("summary_environment_item_count_mismatch")
    if summary.get("selector_item_count") != len(selector_items):
        errors.append("summary_selector_item_count_mismatch")
    if summary.get("file_item_count") != len(file_items):
        errors.append("summary_file_item_count_mismatch")
    if summary.get("dependency_item_count") != len(dependency_items):
        errors.append("summary_dependency_item_count_mismatch")

    all_items = [*environment_items, *selector_items, *file_items, *dependency_items]
    if summary.get("owner_counts") != _owner_counts(all_items):
        errors.append("summary_owner_counts_mismatch")
    if summary.get("missing_required_by_owner") != _missing_by_owner(
        environment_items,
        selector_items,
        file_items,
        dependency_items,
    ):
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
        "make verify-au-p0b-google-env-template",
        "make au-p0b-google-env-bootstrap",
        "make verify-au-p0b-google-env-bootstrap",
    ):
        if command not in setup_commands:
            errors.append(f"setup_command_missing:{command}")
    for command in (
        "make au-p0b-google-playwright-env",
        "make verify-au-p0b-google-playwright-env",
        "make au-p0b-google-manual-template",
        "make verify-au-p0b-google-manual-backfill",
        "make au-p0b-google-execution-checklist",
        "make verify-au-p0b-google-execution-checklist",
    ):
        if command not in verification_commands:
            errors.append(f"verification_command_missing:{command}")
    for output in (
        "docs/runtime_preflight/au-p0b-google-env-bootstrap-latest.json",
        "docs/runtime_preflight/au-p0b-google-playwright-env-latest.json",
        "docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json",
    ):
        if output not in evidence_outputs:
            errors.append(f"evidence_output_missing:{output}")

    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("redaction_policy_raw_secret_invalid")
    if redaction_policy.get("forbidden_exact_secret_fields_redacted") is not True:
        errors.append("redaction_policy_forbidden_field_redaction_missing")
    if redaction_policy.get("forbidden_exact_secret_field_count") != 2:
        errors.append("redaction_policy_forbidden_field_count_invalid")
    for finding in _find_forbidden_secret_fields(payload):
        errors.append(f"forbidden_secret_field:{finding}")

    if endpoints.get("p0b_google_environment_request") != "GET /v1/p0b-google-environment-request/au":
        errors.append("runtime_endpoint_p0b_google_environment_request_invalid")
    if endpoints.get("p0b_google_execution_checklist") != "GET /v1/p0b-google-execution-checklist/au":
        errors.append("runtime_endpoint_p0b_google_execution_checklist_invalid")
    if endpoints.get("external_dependency_handoff") != "GET /v1/external-dependency-handoff/au":
        errors.append("runtime_endpoint_external_dependency_handoff_invalid")
    for required in (
        "make au-p0b-google-environment-request",
        "make verify-au-p0b-google-environment-request",
        "make au-p0b-google-playwright-env",
        "make verify-au-p0b-google-playwright-env",
    ):
        if required not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{required}")
    if not any(command.endswith("--require-ready-smoke") for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_ready_smoke")
    if require_environment_ready and payload.get("environment_handoff_ready") is not True:
        errors.append("p0b_google_environment_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0b_google_environment_request_packet_version": payload.get(
            "p0b_google_environment_request_packet_version",
            "",
        ),
        "p0b_google_environment_request_packet_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0b_google_environment_request_packet_hash": computed_hash,
        "hash_valid": hash_valid,
        "google_environment_request_packet_ready": expected_ready,
        "environment_handoff_ready": payload.get("environment_handoff_ready") is True,
        "missing_required_count": len(expected_missing),
        "target_env_file": summary.get("target_env_file", ""),
        "next_command": summary.get("next_command", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google environment request packet JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_ENVIRONMENT_REQUEST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google environment request packet JSON.",
    )
    parser.add_argument(
        "--require-environment-ready",
        action="store_true",
        help="Fail unless all required P0b Google environment inputs are recorded as present.",
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
            "errors": ["p0b_google_environment_request_packet_file_missing"],
            "hash_valid": False,
            "google_environment_request_packet_ready": False,
            "environment_handoff_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0b_google_environment_request_packet_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "google_environment_request_packet_ready": False,
            "environment_handoff_ready": False,
        }
    else:
        result = verify_au_p0b_google_environment_request_packet(
            payload,
            path=path,
            require_environment_ready=args.require_environment_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
