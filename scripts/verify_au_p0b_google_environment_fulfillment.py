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

from scripts.build_au_p0b_google_environment_fulfillment import (  # noqa: E402
    ACTION_PLAN_VERSION,
    DEFAULT_OUTPUT_PATH,
    FULFILLMENT_VERSION,
    compute_p0b_google_environment_fulfillment_hash,
)


REQUIRED_FIELDS = (
    "p0b_google_environment_fulfillment_version",
    "generated_at",
    "status",
    "environment_fulfillment_ready",
    "environment_fulfilled",
    "ready_for_playwright_smoke",
    "ready_for_full_google_run",
    "google_main_scoring_allowed",
    "output_path",
    "source_p0b_google_environment_request",
    "source_p0b_google_playwright_env_report",
    "p0b_google_environment_request_verifier",
    "p0b_google_playwright_env_report_verifier",
    "summary",
    "google_environment_action_plan",
    "environment_fulfillment_items",
    "verification_commands",
    "hard_gate_commands",
    "runtime_endpoints",
    "redaction_policy",
    "p0b_google_environment_fulfillment_hash",
)
FORBIDDEN_EXACT_FIELDS = {
    "value",
    "raw_value",
    "database_url",
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


def _find_forbidden_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_EXACT_FIELDS:
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
    return {owner: sorted(names) for owner, names in sorted(owners.items())}


def _required_missing_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item.get("required") is True and item.get("fulfilled") is not True]


def _action_owner_counts(action_items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in action_items:
        owner = str(item.get("owner_hint") or "unknown")
        counts[owner] = counts.get(owner, 0) + 1
    return dict(sorted(counts.items()))


def verify_au_p0b_google_environment_fulfillment(
    payload: Any,
    *,
    path: Path | None = None,
    require_fulfilled: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0b_google_environment_fulfillment_not_json_object"],
            "hash_valid": False,
            "environment_fulfillment_ready": False,
            "environment_fulfilled": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0b_google_environment_fulfillment_version") != FULFILLMENT_VERSION:
        errors.append("p0b_google_environment_fulfillment_version_invalid")
    for forbidden_path in _find_forbidden_fields(payload):
        errors.append(f"forbidden_raw_field:{forbidden_path}")

    expected_hash = payload.get("p0b_google_environment_fulfillment_hash")
    computed_hash = compute_p0b_google_environment_fulfillment_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0b_google_environment_fulfillment_hash_mismatch")

    request_verifier = _as_dict(payload.get("p0b_google_environment_request_verifier"))
    env_verifier = _as_dict(payload.get("p0b_google_playwright_env_report_verifier"))
    source_request = _as_dict(payload.get("source_p0b_google_environment_request"))
    source_env = _as_dict(payload.get("source_p0b_google_playwright_env_report"))
    summary = _as_dict(payload.get("summary"))
    action_plan = _as_dict(payload.get("google_environment_action_plan"))
    action_items = [_as_dict(item) for item in _as_list(action_plan.get("action_items"))]
    items = [_as_dict(item) for item in _as_list(payload.get("environment_fulfillment_items"))]
    verification_commands = _strings(payload.get("verification_commands"))
    hard_gate_commands = _strings(payload.get("hard_gate_commands"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))

    request_ok = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    env_ok = env_verifier.get("status") == "pass" and env_verifier.get("hash_valid") is True
    expected_ready = request_ok and env_ok
    if payload.get("environment_fulfillment_ready") is not expected_ready:
        errors.append("environment_fulfillment_ready_mismatch")
    if payload.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")
    if source_request.get("p0b_google_environment_request_packet_hash") != request_verifier.get(
        "p0b_google_environment_request_packet_hash"
    ):
        errors.append("source_p0b_google_environment_request_hash_mismatch")
    if source_env.get("environment_report_hash") != env_verifier.get("environment_report_hash"):
        errors.append("source_p0b_google_playwright_env_report_hash_mismatch")

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
            errors.append(f"environment_fulfillment_item_missing:{key}")

    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True)
    missing_items = _required_missing_items(items)
    missing_item_lookup = {str(item.get("key") or ""): item for item in missing_items}
    mismatches = sorted(str(item.get("key") or "") for item in items if item.get("presence_mismatch") is True)
    environment_fulfilled = bool(required_items) and len(fulfilled_required) == len(required_items) and not mismatches
    if payload.get("environment_fulfilled") is not environment_fulfilled:
        errors.append("environment_fulfilled_mismatch")
    if payload.get("ready_for_playwright_smoke") is not (
        environment_fulfilled and env_verifier.get("ready_for_playwright_smoke") is True
    ):
        errors.append("ready_for_playwright_smoke_mismatch")
    if payload.get("ready_for_full_google_run") is not (
        environment_fulfilled and env_verifier.get("ready_for_full_google_run") is True
    ):
        errors.append("ready_for_full_google_run_mismatch")
    if payload.get("google_main_scoring_allowed") is True and not payload.get("ready_for_full_google_run"):
        errors.append("google_main_scoring_allowed_without_full_run_ready")
    if summary.get("environment_fulfilled") is not environment_fulfilled:
        errors.append("summary_environment_fulfilled_mismatch")
    if summary.get("environment_handoff_ready") is not source_request.get("environment_handoff_ready"):
        errors.append("summary_environment_handoff_ready_mismatch")
    if summary.get("playwright_env_ready_for_smoke") is not env_verifier.get("ready_for_playwright_smoke"):
        errors.append("summary_playwright_env_ready_for_smoke_mismatch")
    if summary.get("playwright_env_ready_for_full_google_run") is not env_verifier.get("ready_for_full_google_run"):
        errors.append("summary_playwright_env_ready_for_full_google_run_mismatch")
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
    if summary.get("google_environment_action_plan_ready") is not True:
        errors.append("summary_google_environment_action_plan_ready_mismatch")
    if summary.get("google_environment_action_required") is not (not environment_fulfilled):
        errors.append("summary_google_environment_action_required_mismatch")
    if summary.get("google_environment_action_item_count") != len(missing_items):
        errors.append("summary_google_environment_action_item_count_mismatch")
    if summary.get("google_environment_action_owner_counts") != _action_owner_counts(action_items):
        errors.append("summary_google_environment_action_owner_counts_mismatch")
    if summary.get("google_environment_post_update_validation_command_count") != len(
        _strings(action_plan.get("post_update_validation_sequence"))
    ):
        errors.append("summary_google_environment_post_update_validation_command_count_mismatch")
    if summary.get("raw_secret_values_allowed") is not False:
        errors.append("summary_raw_secret_policy_invalid")
    if not isinstance(summary.get("strict_gate_command"), str) or "--require-fulfilled" not in summary.get(
        "strict_gate_command",
        "",
    ):
        errors.append("summary_strict_gate_command_missing")
    if not isinstance(summary.get("ready_smoke_strict_gate_command"), str) or "--require-ready-smoke" not in summary.get(
        "ready_smoke_strict_gate_command",
        "",
    ):
        errors.append("summary_ready_smoke_strict_gate_command_missing")

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
                errors.append(f"environment_fulfillment_item_field_missing:{key}:{field}")
        if item.get("required") is True:
            expected_fulfilled = (
                item.get("requested_present") is True
                and item.get("environment_present") is True
                and item.get("presence_mismatch") is not True
            )
            if item.get("fulfilled") is not expected_fulfilled:
                errors.append(f"environment_fulfillment_item_fulfilled_mismatch:{key}")
        if item.get("presence_mismatch") is not (item.get("requested_present") is not item.get("environment_present")):
            errors.append(f"environment_fulfillment_item_presence_mismatch_invalid:{key}")
        if item.get("secret_redacted") is not True:
            errors.append(f"environment_fulfillment_item_secret_redaction_missing:{key}")
        if item.get("fulfilled") is True and _as_list(item.get("blocking_reasons")):
            errors.append(f"environment_fulfillment_item_blocking_reasons_on_fulfilled:{key}")

    if action_plan.get("version") != ACTION_PLAN_VERSION:
        errors.append("google_environment_action_plan_version_invalid")
    if action_plan.get("ready") is not True:
        errors.append("google_environment_action_plan_ready_mismatch")
    if action_plan.get("complete") is not environment_fulfilled:
        errors.append("google_environment_action_plan_complete_mismatch")
    if action_plan.get("action_required") is not (not environment_fulfilled):
        errors.append("google_environment_action_required_mismatch")
    if action_plan.get("action_item_count") != len(missing_items):
        errors.append("google_environment_action_item_count_mismatch")
    if sorted(str(item.get("key") or "") for item in action_items) != missing_required:
        errors.append("google_environment_action_item_keys_mismatch")
    if action_plan.get("owner_counts") != _action_owner_counts(action_items):
        errors.append("google_environment_action_owner_counts_mismatch")
    if not str(action_plan.get("target_env_file") or ""):
        errors.append("google_environment_action_target_env_file_missing")
    if action_plan.get("next_command") not in {
        "make au-p0b-google-playwright-env",
        "make verify-au-p0b-google-environment-fulfillment",
    }:
        errors.append("google_environment_action_next_command_invalid")
    action_validation_sequence = _strings(action_plan.get("post_update_validation_sequence"))
    if action_plan.get("post_update_validation_command_count") != len(action_validation_sequence):
        errors.append("google_environment_action_validation_count_mismatch")
    if not any("--require-fulfilled" in command for command in action_validation_sequence):
        errors.append("google_environment_action_validation_missing_require_fulfilled")
    if not any("--require-ready-smoke" in command for command in action_validation_sequence):
        errors.append("google_environment_action_validation_missing_require_ready_smoke")
    if "--require-fulfilled" not in str(action_plan.get("strict_gate_command") or ""):
        errors.append("google_environment_action_strict_gate_invalid")
    if "--require-ready-smoke" not in str(action_plan.get("ready_smoke_strict_gate_command") or ""):
        errors.append("google_environment_action_ready_smoke_gate_invalid")
    action_redaction_policy = _as_dict(action_plan.get("redaction_policy"))
    for field in ("raw_secret_values_allowed", "selector_values_allowed", "database_urls_allowed"):
        if action_redaction_policy.get(field) is not False:
            errors.append(f"google_environment_action_redaction_policy_invalid:{field}")
    if action_redaction_policy.get("source_payloads_embedded") is not False:
        errors.append("google_environment_action_redaction_policy_source_payload_invalid")
    if action_redaction_policy.get("hash_path_status_only") is not True:
        errors.append("google_environment_action_redaction_policy_hash_path_invalid")
    for index, action_item in enumerate(action_items, start=1):
        key = str(action_item.get("key") or "")
        source_item = missing_item_lookup.get(key, {})
        if action_item.get("order") != index:
            errors.append(f"google_environment_action_item_order_invalid:{key}")
        for field in (
            "item_type",
            "name",
            "owner_hint",
            "target_env_file",
            "env_file_key",
            "accepted_injection_methods",
            "next_command_after_update",
            "strict_gate_command",
            "ready_smoke_strict_gate_command",
            "blocking_reasons",
        ):
            if field not in action_item:
                errors.append(f"google_environment_action_item_field_missing:{key}:{field}")
        if action_item.get("item_type") != source_item.get("item_type"):
            errors.append(f"google_environment_action_item_type_mismatch:{key}")
        if action_item.get("owner_hint") != source_item.get("owner_hint"):
            errors.append(f"google_environment_action_item_owner_mismatch:{key}")
        if _strings(action_item.get("accepted_injection_methods")) != _strings(
            source_item.get("accepted_injection_methods")
        ):
            errors.append(f"google_environment_action_item_injection_methods_mismatch:{key}")
        if action_item.get("next_command_after_update") != "make au-p0b-google-playwright-env":
            errors.append(f"google_environment_action_item_next_command_invalid:{key}")
        if "--require-fulfilled" not in str(action_item.get("strict_gate_command") or ""):
            errors.append(f"google_environment_action_item_strict_gate_invalid:{key}")
        if "--require-ready-smoke" not in str(action_item.get("ready_smoke_strict_gate_command") or ""):
            errors.append(f"google_environment_action_item_ready_smoke_gate_invalid:{key}")
        if _strings(action_item.get("blocking_reasons")) != _strings(source_item.get("blocking_reasons")):
            errors.append(f"google_environment_action_item_blocking_reasons_mismatch:{key}")
        for field in ("raw_secret_values_allowed", "selector_values_allowed", "database_urls_allowed"):
            if action_item.get(field) is not False:
                errors.append(f"google_environment_action_item_policy_invalid:{key}:{field}")
        if action_item.get("secret_redacted") is not True:
            errors.append(f"google_environment_action_item_secret_redaction_missing:{key}")

    for command in (
        "make au-p0b-google-environment-request",
        "make verify-au-p0b-google-environment-request",
        "make au-p0b-google-playwright-env",
        "make verify-au-p0b-google-playwright-env",
        "make verify-au-p0b-google-environment-fulfillment",
    ):
        if command not in verification_commands:
            errors.append(f"verification_command_missing:{command}")
    if "make verify-au-p0b-google-environment-fulfillment" not in hard_gate_commands:
        errors.append("hard_gate_missing:make verify-au-p0b-google-environment-fulfillment")
    if not any("--require-fulfilled" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_fulfilled")
    if not any("--require-ready-smoke" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_ready_smoke")
    if endpoints.get("p0b_google_environment_fulfillment") != "GET /v1/p0b-google-environment-fulfillment/au":
        errors.append("runtime_endpoint_p0b_google_environment_fulfillment_invalid")
    if endpoints.get("p0b_google_environment_request") != "GET /v1/p0b-google-environment-request/au":
        errors.append("runtime_endpoint_p0b_google_environment_request_invalid")
    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("redaction_policy_raw_secret_invalid")
    if redaction_policy.get("secret_redacted") is not True:
        errors.append("redaction_policy_secret_redaction_missing")
    if require_fulfilled and not environment_fulfilled:
        errors.append("p0b_google_environment_not_fulfilled")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0b_google_environment_fulfillment_version": payload.get(
            "p0b_google_environment_fulfillment_version",
            "",
        ),
        "p0b_google_environment_fulfillment_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0b_google_environment_fulfillment_hash": computed_hash,
        "hash_valid": hash_valid,
        "environment_fulfillment_ready": expected_ready,
        "environment_fulfilled": environment_fulfilled,
        "ready_for_playwright_smoke": payload.get("ready_for_playwright_smoke") is True,
        "ready_for_full_google_run": payload.get("ready_for_full_google_run") is True,
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
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google environment fulfillment JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_ENVIRONMENT_FULFILLMENT_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google environment fulfillment JSON.",
    )
    parser.add_argument(
        "--require-fulfilled",
        action="store_true",
        help="Fail unless P0b Google environment inputs are fulfilled.",
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
            "errors": ["p0b_google_environment_fulfillment_file_missing"],
            "hash_valid": False,
            "environment_fulfillment_ready": False,
            "environment_fulfilled": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0b_google_environment_fulfillment_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "environment_fulfillment_ready": False,
            "environment_fulfilled": False,
        }
    else:
        result = verify_au_p0b_google_environment_fulfillment(
            payload,
            path=path,
            require_fulfilled=args.require_fulfilled,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
