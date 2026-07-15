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

from scripts.build_au_p0b_google_environment_clearance import (  # noqa: E402
    CLEARANCE_VERSION,
    DEFAULT_OUTPUT_PATH,
    PREREQUISITE_STEP_ID,
    STEP_ID,
    compute_p0b_google_environment_clearance_hash,
)


REQUIRED_FIELDS = (
    "p0b_google_environment_clearance_version",
    "generated_at",
    "status",
    "environment_clearance_packet_ready",
    "environment_fulfilled",
    "environment_clearance_ready",
    "ready_for_next_clearance_step",
    "blocked_by_prerequisite_step",
    "output_path",
    "clearance_step",
    "prerequisite_step",
    "source_artifacts",
    "p0b_google_environment_request_verifier",
    "p0b_google_playwright_env_report_verifier",
    "p0b_google_environment_fulfillment_verifier",
    "summary",
    "environment_clearance_items",
    "operator_steps",
    "post_update_validation_sequence",
    "runtime_endpoints",
    "hard_gate_commands",
    "redaction_policy",
    "p0b_google_environment_clearance_hash",
)
FORBIDDEN_EXACT_FIELDS = {
    "value",
    "raw_value",
    "database_url",
    "secret",
    "token",
    "selector_value",
    "answer_text",
    "citation_urls",
    "screenshot_url",
    "html_snapshot_url",
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
            if key in FORBIDDEN_EXACT_FIELDS:
                findings.append(child_path)
            findings.extend(_find_forbidden_raw_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_raw_fields(child, path=f"{path}[{index}]"))
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


def verify_au_p0b_google_environment_clearance(
    payload: Any,
    *,
    path: Path | None = None,
    require_cleared: bool = False,
    verify_current_files: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0b_google_environment_clearance_not_json_object"],
            "hash_valid": False,
            "environment_clearance_packet_ready": False,
            "environment_clearance_ready": False,
            "current_file_check_enabled": path is not None if verify_current_files is None else verify_current_files,
        }

    current_file_check_enabled = path is not None if verify_current_files is None else verify_current_files
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0b_google_environment_clearance_version") != CLEARANCE_VERSION:
        errors.append("p0b_google_environment_clearance_version_invalid")
    for forbidden_path in _find_forbidden_raw_fields(payload):
        errors.append(f"forbidden_raw_field:{forbidden_path}")

    expected_hash = payload.get("p0b_google_environment_clearance_hash")
    computed_hash = compute_p0b_google_environment_clearance_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0b_google_environment_clearance_hash_mismatch")

    request_verifier = _as_dict(payload.get("p0b_google_environment_request_verifier"))
    env_verifier = _as_dict(payload.get("p0b_google_playwright_env_report_verifier"))
    fulfillment_verifier = _as_dict(payload.get("p0b_google_environment_fulfillment_verifier"))
    source_artifacts = _as_dict(payload.get("source_artifacts"))
    request_source = _as_dict(source_artifacts.get("environment_request"))
    env_source = _as_dict(source_artifacts.get("playwright_env_report"))
    fulfillment_source = _as_dict(source_artifacts.get("environment_fulfillment"))
    clearance_source = _as_dict(source_artifacts.get("external_dependency_clearance"))
    summary = _as_dict(payload.get("summary"))
    clearance_step = _as_dict(payload.get("clearance_step"))
    prerequisite_step = _as_dict(payload.get("prerequisite_step"))
    items = [_as_dict(item) for item in _as_list(payload.get("environment_clearance_items"))]
    operator_steps = [_as_dict(item) for item in _as_list(payload.get("operator_steps"))]
    validation_sequence = _strings(payload.get("post_update_validation_sequence"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    hard_gate_commands = _strings(payload.get("hard_gate_commands"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))

    request_ok = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    env_ok = env_verifier.get("status") == "pass" and env_verifier.get("hash_valid") is True
    fulfillment_ok = fulfillment_verifier.get("status") == "pass" and fulfillment_verifier.get("hash_valid") is True
    clearance_ok = str(clearance_source.get("verifier_status") or "") in {"pass", ""}
    expected_packet_ready = request_ok and env_ok and fulfillment_ok and clearance_ok
    if payload.get("environment_clearance_packet_ready") is not expected_packet_ready:
        errors.append("environment_clearance_packet_ready_mismatch")
    if payload.get("status") != ("pass" if expected_packet_ready else "fail"):
        errors.append("status_mismatch")

    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True)
    presence_mismatches = sorted(str(item.get("key") or "") for item in items if item.get("presence_mismatch") is True)
    environment_fulfilled = (
        bool(required_items) and len(fulfilled_required) == len(required_items) and not presence_mismatches
    )
    blocked_by_prerequisite = prerequisite_step.get("ready") is not True
    expected_next_ready = environment_fulfilled and not blocked_by_prerequisite
    expected_clearance_ready = (
        environment_fulfilled and clearance_step.get("step_ready") is True and not blocked_by_prerequisite
    )
    if payload.get("environment_fulfilled") is not environment_fulfilled:
        errors.append("environment_fulfilled_mismatch")
    if payload.get("blocked_by_prerequisite_step") is not blocked_by_prerequisite:
        errors.append("blocked_by_prerequisite_step_mismatch")
    if payload.get("ready_for_next_clearance_step") is not expected_next_ready:
        errors.append("ready_for_next_clearance_step_mismatch")
    if payload.get("environment_clearance_ready") is not expected_clearance_ready:
        errors.append("environment_clearance_ready_mismatch")
    if require_cleared and not expected_clearance_ready:
        errors.append("p0b_google_environment_not_cleared")

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

    if request_source.get("hash") != request_verifier.get("p0b_google_environment_request_packet_hash"):
        errors.append("source_environment_request_hash_mismatch")
    if env_source.get("hash") != env_verifier.get("environment_report_hash"):
        errors.append("source_playwright_env_report_hash_mismatch")
    if fulfillment_source.get("hash") != fulfillment_verifier.get("p0b_google_environment_fulfillment_hash"):
        errors.append("source_environment_fulfillment_hash_mismatch")
    expected_hash_fields = {
        "environment_request": "p0b_google_environment_request_packet_hash",
        "playwright_env_report": "environment_report_hash",
        "environment_fulfillment": "p0b_google_environment_fulfillment_hash",
        "external_dependency_clearance": "clearance_execution_hash",
    }
    for key, expected_field in expected_hash_fields.items():
        if _as_dict(source_artifacts.get(key)).get("hash_field") != expected_field:
            errors.append(f"source_hash_field_invalid:{key}")
    if current_file_check_enabled:
        _check_current_source_file(
            errors,
            source_key="source_environment_request",
            source=request_source,
            hash_field="p0b_google_environment_request_packet_hash",
            expected_hash=str(request_source.get("hash") or ""),
        )
        _check_current_source_file(
            errors,
            source_key="source_playwright_env_report",
            source=env_source,
            hash_field="environment_report_hash",
            expected_hash=str(env_source.get("hash") or ""),
        )
        _check_current_source_file(
            errors,
            source_key="source_environment_fulfillment",
            source=fulfillment_source,
            hash_field="p0b_google_environment_fulfillment_hash",
            expected_hash=str(fulfillment_source.get("hash") or ""),
        )
        _check_current_source_file(
            errors,
            source_key="source_clearance",
            source=clearance_source,
            hash_field="clearance_execution_hash",
            expected_hash=str(clearance_source.get("hash") or ""),
        )

    required_item_keys = {
        "environment:GOOGLE_PLAYWRIGHT_ENABLED",
        "environment:DATABASE_URL",
        "environment:MANUAL_BACKFILL_PATH",
        "selector:google_aio_prompt_selector",
        "selector:google_aio_answer_selector",
        "file:MANUAL_BACKFILL_PATH",
        "dependency:python_playwright_package",
    }
    item_keys = {str(item.get("key") or "") for item in items}
    for key in required_item_keys:
        if key not in item_keys:
            errors.append(f"environment_clearance_item_missing:{key}")

    if summary.get("required_count") != len(required_items):
        errors.append("summary_required_count_mismatch")
    if summary.get("fulfilled_required_count") != len(fulfilled_required):
        errors.append("summary_fulfilled_required_count_mismatch")
    if summary.get("missing_required_count") != len(missing_required):
        errors.append("summary_missing_required_count_mismatch")
    if sorted(_strings(summary.get("missing_required"))) != missing_required:
        errors.append("summary_missing_required_mismatch")
    if summary.get("presence_mismatch_count") != len(presence_mismatches):
        errors.append("summary_presence_mismatch_count_mismatch")
    if sorted(_strings(summary.get("presence_mismatches"))) != presence_mismatches:
        errors.append("summary_presence_mismatches_mismatch")
    if summary.get("owner_counts") != _owner_counts(items):
        errors.append("summary_owner_counts_mismatch")
    if summary.get("missing_required_by_owner") != _missing_by_owner(items):
        errors.append("summary_missing_required_by_owner_mismatch")
    if summary.get("environment_fulfilled") is not environment_fulfilled:
        errors.append("summary_environment_fulfilled_mismatch")
    if summary.get("environment_fulfillment_ready") is not (fulfillment_verifier.get("environment_fulfillment_ready") is True):
        errors.append("summary_environment_fulfillment_ready_mismatch")
    if summary.get("ready_for_playwright_smoke") is not (fulfillment_verifier.get("ready_for_playwright_smoke") is True):
        errors.append("summary_ready_for_playwright_smoke_mismatch")
    if summary.get("ready_for_full_google_run") is not (fulfillment_verifier.get("ready_for_full_google_run") is True):
        errors.append("summary_ready_for_full_google_run_mismatch")
    if summary.get("prerequisite_step_ready") is not (prerequisite_step.get("ready") is True):
        errors.append("summary_prerequisite_step_ready_mismatch")
    if summary.get("target_clearance_step_ready") is not (clearance_step.get("step_ready") is True):
        errors.append("summary_target_clearance_step_ready_mismatch")
    if summary.get("target_clearance_step_can_start") is not (clearance_step.get("step_can_start") is True):
        errors.append("summary_target_clearance_step_can_start_mismatch")
    if summary.get("operator_step_count") != len(operator_steps):
        errors.append("summary_operator_step_count_mismatch")
    if summary.get("post_update_validation_command_count") != len(validation_sequence):
        errors.append("summary_post_update_validation_command_count_mismatch")
    if summary.get("raw_secret_values_allowed") is not False:
        errors.append("summary_raw_secret_policy_invalid")
    if summary.get("selector_values_allowed") is not False:
        errors.append("summary_selector_policy_invalid")
    if summary.get("database_urls_allowed") is not False:
        errors.append("summary_database_url_policy_invalid")
    if summary.get("provider_response_values_allowed") is not False:
        errors.append("summary_provider_response_policy_invalid")
    if summary.get("google_environment_action_plan_ready") is not (
        fulfillment_verifier.get("google_environment_action_plan_ready") is True
    ):
        errors.append("summary_google_environment_action_plan_ready_mismatch")
    if summary.get("google_environment_action_required") is not (
        fulfillment_verifier.get("google_environment_action_required") is True
    ):
        errors.append("summary_google_environment_action_required_mismatch")
    if summary.get("google_environment_action_item_count") != fulfillment_verifier.get(
        "google_environment_action_item_count"
    ):
        errors.append("summary_google_environment_action_item_count_mismatch")
    if summary.get("google_environment_action_owner_counts") != _as_dict(
        fulfillment_verifier.get("google_environment_action_owner_counts")
    ):
        errors.append("summary_google_environment_action_owner_counts_mismatch")
    if summary.get("google_environment_post_update_validation_command_count") != fulfillment_verifier.get(
        "google_environment_post_update_validation_command_count"
    ):
        errors.append("summary_google_environment_post_update_validation_command_count_mismatch")

    required_step_ids = {
        "clear_p0a_real_batches",
        "refresh_environment_request",
        "refresh_playwright_env_report",
        "refresh_environment_fulfillment",
        "apply_current_environment_fix",
        "verify_environment_fulfillment",
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

    for item in items:
        key = str(item.get("key") or "")
        for field in (
            "item_type",
            "name",
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
                errors.append(f"environment_clearance_item_field_missing:{key}:{field}")
        if item.get("required") is True:
            expected_fulfilled = (
                item.get("requested_present") is True
                and item.get("environment_present") is True
                and item.get("presence_mismatch") is not True
            )
            if item.get("fulfilled") is not expected_fulfilled:
                errors.append(f"environment_clearance_item_fulfilled_mismatch:{key}")
        if item.get("presence_mismatch") is not (item.get("requested_present") is not item.get("environment_present")):
            errors.append(f"environment_clearance_item_presence_mismatch_invalid:{key}")
        if item.get("secret_redacted") is not True:
            errors.append(f"environment_clearance_item_secret_redaction_missing:{key}")
        if item.get("fulfilled") is True and _as_list(item.get("blocking_reasons")):
            errors.append(f"environment_clearance_item_blocking_reasons_on_fulfilled:{key}")

    for command in (
        "make au-p0a-real-batch-clearance",
        "make verify-au-p0a-real-batch-clearance",
        "make au-p0b-google-environment-request",
        "make verify-au-p0b-google-environment-request",
        "make au-p0b-google-playwright-env",
        "make verify-au-p0b-google-playwright-env",
        "make au-p0b-google-environment-fulfillment",
        "make verify-au-p0b-google-environment-fulfillment",
    ):
        if command not in validation_sequence:
            errors.append(f"post_update_validation_command_missing:{command}")
        if command not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{command}")
    if not any("--require-fulfilled" in command for command in validation_sequence):
        errors.append("post_update_validation_missing_require_fulfilled")
    if not any("--require-ready-smoke" in command for command in validation_sequence):
        errors.append("post_update_validation_missing_require_ready_smoke")
    if not any("--require-cleared" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_cleared")

    expected_endpoints = {
        "p0b_google_environment_clearance": "GET /v1/p0b-google-environment-clearance/au",
        "p0b_google_environment_request": "GET /v1/p0b-google-environment-request/au",
        "p0b_google_environment_fulfillment": "GET /v1/p0b-google-environment-fulfillment/au",
        "p0b_google_execution_checklist": "GET /v1/p0b-google-execution-checklist/au",
        "p0a_real_batch_clearance": "GET /v1/p0a-real-batch-clearance/au",
        "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
        "delivery_progress": "GET /v1/delivery-progress/au",
    }
    for key, expected in expected_endpoints.items():
        if endpoints.get(key) != expected:
            errors.append(f"runtime_endpoint_invalid:{key}")
    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("redaction_policy_raw_secret_invalid")
    if redaction_policy.get("selector_values_allowed") is not False:
        errors.append("redaction_policy_selector_invalid")
    if redaction_policy.get("database_urls_allowed") is not False:
        errors.append("redaction_policy_database_url_invalid")
    if redaction_policy.get("provider_response_values_allowed") is not False:
        errors.append("redaction_policy_provider_response_invalid")
    if redaction_policy.get("environment_entries_reference_presence_and_hash_prefix_only") is not True:
        errors.append("redaction_policy_environment_reference_invalid")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0b_google_environment_clearance_version": payload.get("p0b_google_environment_clearance_version", ""),
        "p0b_google_environment_clearance_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0b_google_environment_clearance_hash": computed_hash,
        "hash_valid": hash_valid,
        "current_file_check_enabled": current_file_check_enabled,
        "environment_clearance_packet_ready": expected_packet_ready,
        "environment_clearance_ready": expected_clearance_ready,
        "environment_fulfilled": environment_fulfilled,
        "blocked_by_prerequisite_step": blocked_by_prerequisite,
        "missing_required_count": len(missing_required),
        "missing_required": missing_required,
        "google_environment_action_plan_ready": summary.get("google_environment_action_plan_ready") is True,
        "google_environment_action_required": summary.get("google_environment_action_required") is True,
        "google_environment_action_item_count": summary.get("google_environment_action_item_count"),
        "google_environment_action_owner_counts": _as_dict(summary.get("google_environment_action_owner_counts")),
        "google_environment_post_update_validation_command_count": summary.get(
            "google_environment_post_update_validation_command_count"
        ),
        "next_action": summary.get("next_action", ""),
        "next_command": summary.get("next_command", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google environment clearance JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google environment clearance JSON.",
    )
    parser.add_argument("--require-cleared", action="store_true", help="Fail unless P0b Google environment is cleared.")
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
            "errors": ["p0b_google_environment_clearance_file_missing"],
            "hash_valid": False,
            "environment_clearance_packet_ready": False,
            "environment_clearance_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0b_google_environment_clearance_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "environment_clearance_packet_ready": False,
            "environment_clearance_ready": False,
        }
    else:
        result = verify_au_p0b_google_environment_clearance(payload, path=path, require_cleared=args.require_cleared)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
