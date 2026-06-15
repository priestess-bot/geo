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

from scripts.build_au_p0b_google_manual_backfill_fulfillment import (  # noqa: E402
    CONTENT_COMPLETION_HANDOFF_VERSION,
    DEFAULT_OUTPUT_PATH,
    FULFILLMENT_VERSION,
    POST_CONTENT_COMPLETION_VALIDATION_COMMANDS,
    compute_p0b_google_manual_backfill_fulfillment_hash,
)


REQUIRED_FIELDS = (
    "p0b_google_manual_backfill_fulfillment_version",
    "generated_at",
    "status",
    "manual_backfill_fulfillment_ready",
    "manual_backfill_fulfilled",
    "google_main_scoring_allowed",
    "output_path",
    "source_p0b_google_manual_backfill_request",
    "source_p0b_google_manual_backfill_verification",
    "p0b_google_manual_backfill_request_verifier",
    "p0b_google_manual_backfill_verification_verifier",
    "summary",
    "manual_backfill_fulfillment_items",
    "manual_content_completion_handoff",
    "post_content_completion_validation_commands",
    "verification_commands",
    "hard_gate_commands",
    "runtime_endpoints",
    "redaction_policy",
    "p0b_google_manual_backfill_fulfillment_hash",
)
FORBIDDEN_MANUAL_FIELDS = {
    "answer_text",
    "answer",
    "content",
    "citation_urls",
    "citations",
    "sources",
    "screenshot_url",
    "screenshot",
    "html_snapshot_url",
    "html_snapshot",
    "raw_answer",
    "raw_citation",
    "raw_asset_url",
    "raw_value",
    "value",
}


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _int_list(value: object, *, limit: int = 20) -> list[int]:
    numbers: list[int] = []
    for item in _as_list(value):
        number = _int(item)
        if number > 0:
            numbers.append(number)
        if len(numbers) >= limit:
            break
    return numbers


def _find_forbidden_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_MANUAL_FIELDS:
                findings.append(child_path)
            findings.extend(_find_forbidden_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_fields(child, path=f"{path}[{index}]"))
    return findings


def _missing_by_owner(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for item in items:
        if item.get("required") is True and item.get("fulfilled") is not True:
            owner = str(item.get("owner_hint") or "unknown")
            owners.setdefault(owner, []).append(str(item.get("key") or ""))
    return {owner: sorted(keys) for owner, keys in sorted(owners.items())}


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def verify_au_p0b_google_manual_backfill_fulfillment(
    payload: Any,
    *,
    path: Path | None = None,
    require_fulfilled: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0b_google_manual_backfill_fulfillment_not_json_object"],
            "hash_valid": False,
            "manual_backfill_fulfillment_ready": False,
            "manual_backfill_fulfilled": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0b_google_manual_backfill_fulfillment_version") != FULFILLMENT_VERSION:
        errors.append("p0b_google_manual_backfill_fulfillment_version_invalid")
    for forbidden_path in _find_forbidden_fields(payload):
        errors.append(f"forbidden_manual_payload_field:{forbidden_path}")

    expected_hash = payload.get("p0b_google_manual_backfill_fulfillment_hash")
    computed_hash = compute_p0b_google_manual_backfill_fulfillment_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0b_google_manual_backfill_fulfillment_hash_mismatch")

    source_request = _as_dict(payload.get("source_p0b_google_manual_backfill_request"))
    source_verification = _as_dict(payload.get("source_p0b_google_manual_backfill_verification"))
    request_verifier = _as_dict(payload.get("p0b_google_manual_backfill_request_verifier"))
    verification_verifier = _as_dict(payload.get("p0b_google_manual_backfill_verification_verifier"))
    summary = _as_dict(payload.get("summary"))
    items = [_as_dict(item) for item in _as_list(payload.get("manual_backfill_fulfillment_items"))]
    manual_content_completion_handoff = _as_dict(payload.get("manual_content_completion_handoff"))
    missing_manual_fields = _as_dict(manual_content_completion_handoff.get("missing_manual_fields"))
    handoff_redaction_policy = _as_dict(manual_content_completion_handoff.get("redaction_policy"))
    post_content_completion_validation_commands = _strings(payload.get("post_content_completion_validation_commands"))
    verification_commands = _strings(payload.get("verification_commands"))
    hard_gate_commands = _strings(payload.get("hard_gate_commands"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))

    request_ok = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    verification_ok = verification_verifier.get("status") == "pass" and verification_verifier.get("hash_valid") is True
    expected_ready = request_ok and verification_ok
    if payload.get("manual_backfill_fulfillment_ready") is not expected_ready:
        errors.append("manual_backfill_fulfillment_ready_mismatch")
    if payload.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")
    if source_request.get("p0b_google_manual_backfill_request_packet_hash") != request_verifier.get(
        "p0b_google_manual_backfill_request_packet_hash"
    ):
        errors.append("source_p0b_google_manual_backfill_request_hash_mismatch")
    if source_verification.get("verification_hash") != verification_verifier.get("verification_hash"):
        errors.append("source_p0b_google_manual_backfill_verification_hash_mismatch")

    required_item_keys = {
        "verification:status",
        "verification:hash",
        "file:manual_jsonl_sha256",
        "count:record_count",
        "count:prompt_city_coverage",
        "count:sample_size",
        "content:answer_text",
        "content:citation_urls",
        "content:evidence_asset",
        "structure:prompt_city_samples",
    }
    item_keys = {str(item.get("key") or "") for item in items}
    for key in required_item_keys:
        if key not in item_keys:
            errors.append(f"manual_backfill_fulfillment_item_missing:{key}")

    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True)
    manual_backfill_fulfilled = bool(required_items) and len(fulfilled_required) == len(required_items)
    if payload.get("manual_backfill_fulfilled") is not manual_backfill_fulfilled:
        errors.append("manual_backfill_fulfilled_mismatch")
    if payload.get("google_main_scoring_allowed") is True and not manual_backfill_fulfilled:
        errors.append("google_main_scoring_allowed_without_manual_backfill_fulfilled")

    if summary.get("manual_backfill_fulfilled") is not manual_backfill_fulfilled:
        errors.append("summary_manual_backfill_fulfilled_mismatch")
    if summary.get("manual_backfill_request_ready") is not request_ok:
        errors.append("summary_manual_backfill_request_ready_mismatch")
    if summary.get("manual_backfill_verification_ready") is not verification_ok:
        errors.append("summary_manual_backfill_verification_ready_mismatch")
    if summary.get("manual_backfill_verification_status") != source_verification.get("manual_backfill_status"):
        errors.append("summary_manual_backfill_verification_status_mismatch")
    if summary.get("manual_backfill_verification_hash") != source_verification.get("verification_hash"):
        errors.append("summary_manual_backfill_verification_hash_mismatch")
    if summary.get("manual_backfill_ready") is not (verification_verifier.get("manual_backfill_ready") is True):
        errors.append("summary_manual_backfill_ready_mismatch")
    if summary.get("manual_backfill_coverage_complete") is not (
        verification_verifier.get("coverage_complete") is True
    ):
        errors.append("summary_manual_backfill_coverage_complete_mismatch")
    if summary.get("manual_backfill_content_complete") is not (verification_verifier.get("content_complete") is True):
        errors.append("summary_manual_backfill_content_complete_mismatch")
    missing_total_content_cell_count = (
        _int(verification_verifier.get("missing_answer_line_count"))
        + _int(verification_verifier.get("missing_citation_line_count"))
        + _int(verification_verifier.get("missing_asset_line_count"))
    )
    expected_content_handoff_ready = (
        request_ok
        and verification_ok
        and verification_verifier.get("coverage_complete") is True
        and verification_verifier.get("content_complete") is not True
        and missing_total_content_cell_count > 0
    )
    if summary.get("manual_content_completion_handoff_ready") is not expected_content_handoff_ready:
        errors.append("summary_manual_content_completion_handoff_ready_mismatch")
    if summary.get("missing_total_content_cell_count") != missing_total_content_cell_count:
        errors.append("summary_missing_total_content_cell_count_mismatch")
    if summary.get("post_content_completion_validation_command_count") != len(POST_CONTENT_COMPLETION_VALIDATION_COMMANDS):
        errors.append("summary_post_content_completion_validation_command_count_mismatch")
    if summary.get("required_count") != len(required_items):
        errors.append("summary_required_count_mismatch")
    if summary.get("fulfilled_required_count") != len(fulfilled_required):
        errors.append("summary_fulfilled_required_count_mismatch")
    if summary.get("missing_required_count") != len(missing_required):
        errors.append("summary_missing_required_count_mismatch")
    if sorted(_strings(summary.get("missing_required"))) != missing_required:
        errors.append("summary_missing_required_mismatch")
    if summary.get("missing_required_by_owner") != _missing_by_owner(items):
        errors.append("summary_missing_required_by_owner_mismatch")
    if summary.get("record_count") != _actual_value(items, "count:record_count"):
        errors.append("summary_record_count_mismatch")
    if summary.get("covered_prompt_city_count") != _actual_value(items, "count:prompt_city_coverage"):
        errors.append("summary_covered_prompt_city_count_mismatch")
    for field in (
        "missing_prompt_city_sample_count",
        "duplicate_prompt_city_sample_count",
        "unexpected_prompt_city_record_count",
        "missing_answer_line_count",
        "missing_citation_line_count",
        "missing_asset_line_count",
    ):
        if summary.get(field) != _int(verification_verifier.get(field)):
            errors.append(f"summary_{field}_mismatch")
    if summary.get("verification_error_count") != len(_strings(summary.get("verification_errors"))):
        errors.append("summary_verification_error_count_mismatch")
    if summary.get("verification_error_count") != _int(verification_verifier.get("error_count")):
        errors.append("summary_verification_error_count_source_mismatch")
    if summary.get("verification_next_action") != verification_verifier.get("next_action"):
        errors.append("summary_verification_next_action_mismatch")
    if summary.get("raw_answer_values_allowed") is not False:
        errors.append("summary_raw_answer_policy_invalid")
    if summary.get("raw_citation_values_allowed") is not False:
        errors.append("summary_raw_citation_policy_invalid")
    if summary.get("raw_asset_urls_allowed") is not False:
        errors.append("summary_raw_asset_policy_invalid")
    if summary.get("content_redacted") is not True:
        errors.append("summary_content_redaction_missing")
    if not isinstance(summary.get("strict_gate_command"), str) or "--require-fulfilled" not in summary.get(
        "strict_gate_command",
        "",
    ):
        errors.append("summary_strict_gate_command_missing")

    if post_content_completion_validation_commands != POST_CONTENT_COMPLETION_VALIDATION_COMMANDS:
        errors.append("post_content_completion_validation_commands_mismatch")
    if manual_content_completion_handoff.get(
        "manual_content_completion_handoff_version"
    ) != CONTENT_COMPLETION_HANDOFF_VERSION:
        errors.append("manual_content_completion_handoff_version_invalid")
    if manual_content_completion_handoff.get("ready_to_complete_content") is not expected_content_handoff_ready:
        errors.append("manual_content_completion_handoff_ready_mismatch")
    if manual_content_completion_handoff.get("manual_backfill_fulfilled") is not manual_backfill_fulfilled:
        errors.append("manual_content_completion_handoff_fulfilled_mismatch")
    if manual_content_completion_handoff.get("target_jsonl_path") != summary.get("target_jsonl_path"):
        errors.append("manual_content_completion_handoff_target_jsonl_path_mismatch")
    if manual_content_completion_handoff.get("resolved_manual_jsonl_path") != summary.get("resolved_manual_jsonl_path"):
        errors.append("manual_content_completion_handoff_resolved_manual_jsonl_path_mismatch")
    if manual_content_completion_handoff.get("verification_path") != summary.get("verification_path"):
        errors.append("manual_content_completion_handoff_verification_path_mismatch")
    for field in (
        "expected_record_count",
        "record_count",
        "expected_prompt_city_count",
        "covered_prompt_city_count",
        "expected_sample_size",
        "verification_expected_sample_size",
    ):
        if manual_content_completion_handoff.get(field) != summary.get(field):
            errors.append(f"manual_content_completion_handoff_{field}_mismatch")
    if manual_content_completion_handoff.get("coverage_complete") is not summary.get(
        "manual_backfill_coverage_complete"
    ):
        errors.append("manual_content_completion_handoff_coverage_complete_mismatch")
    if manual_content_completion_handoff.get("content_complete") is not summary.get("manual_backfill_content_complete"):
        errors.append("manual_content_completion_handoff_content_complete_mismatch")
    if manual_content_completion_handoff.get("missing_total_content_cell_count") != missing_total_content_cell_count:
        errors.append("manual_content_completion_handoff_missing_total_content_cell_count_mismatch")
    if missing_manual_fields.get("answer_line_count") != _int(verification_verifier.get("missing_answer_line_count")):
        errors.append("manual_content_completion_handoff_answer_line_count_mismatch")
    if missing_manual_fields.get("citation_line_count") != _int(
        verification_verifier.get("missing_citation_line_count")
    ):
        errors.append("manual_content_completion_handoff_citation_line_count_mismatch")
    if missing_manual_fields.get("asset_line_count") != _int(verification_verifier.get("missing_asset_line_count")):
        errors.append("manual_content_completion_handoff_asset_line_count_mismatch")
    if _int_list(missing_manual_fields.get("answer_line_number_sample")) != _int_list(
        source_verification.get("missing_answer_line_numbers")
    ):
        errors.append("manual_content_completion_handoff_answer_line_number_sample_mismatch")
    if _int_list(missing_manual_fields.get("citation_line_number_sample")) != _int_list(
        source_verification.get("missing_citation_line_numbers")
    ):
        errors.append("manual_content_completion_handoff_citation_line_number_sample_mismatch")
    if _int_list(missing_manual_fields.get("asset_line_number_sample")) != _int_list(
        source_verification.get("missing_asset_line_numbers")
    ):
        errors.append("manual_content_completion_handoff_asset_line_number_sample_mismatch")
    if _strings(manual_content_completion_handoff.get("required_field_names")) != [
        "answer_text",
        "citation_urls",
        "screenshot_url",
        "html_snapshot_url",
    ]:
        errors.append("manual_content_completion_handoff_required_field_names_mismatch")
    if manual_content_completion_handoff.get(
        "post_content_completion_validation_commands"
    ) != POST_CONTENT_COMPLETION_VALIDATION_COMMANDS:
        errors.append("manual_content_completion_handoff_validation_commands_mismatch")
    if manual_content_completion_handoff.get("post_content_completion_validation_command_count") != len(
        POST_CONTENT_COMPLETION_VALIDATION_COMMANDS
    ):
        errors.append("manual_content_completion_handoff_validation_command_count_mismatch")
    expected_handoff_next_action = (
        "run_p0b_google_manual_backfill_strict_gate"
        if manual_backfill_fulfilled
        else str(verification_verifier.get("next_action") or "rerun_manual_backfill_verification")
    )
    if manual_content_completion_handoff.get("next_action") != expected_handoff_next_action:
        errors.append("manual_content_completion_handoff_next_action_mismatch")
    if manual_backfill_fulfilled:
        expected_handoff_next_command = "make verify-au-p0b-google-manual-backfill-fulfillment"
    elif expected_handoff_next_action == "build_manual_backfill_template":
        expected_handoff_next_command = "make au-p0b-google-manual-template"
    else:
        expected_handoff_next_command = "make verify-au-p0b-google-manual-backfill"
    if manual_content_completion_handoff.get("next_command") != expected_handoff_next_command:
        errors.append("manual_content_completion_handoff_next_command_mismatch")
    for policy_key in ("raw_answer_values_allowed", "raw_citation_values_allowed", "raw_asset_urls_allowed"):
        if handoff_redaction_policy.get(policy_key) is not False:
            errors.append(f"manual_content_completion_handoff_redaction_{policy_key}_invalid")
    if handoff_redaction_policy.get("line_number_samples_allowed") is not True:
        errors.append("manual_content_completion_handoff_line_number_policy_invalid")

    for item in items:
        key = str(item.get("key") or "")
        for field in (
            "category",
            "required",
            "fulfilled",
            "expected_value",
            "actual_value",
            "presence_mismatch",
            "owner_hint",
            "source_request_field",
            "source_verification_field",
            "blocking_reasons",
        ):
            if field not in item:
                errors.append(f"manual_backfill_fulfillment_item_field_missing:{key}:{field}")
        if item.get("required") is True and item.get("fulfilled") is True and _as_list(item.get("blocking_reasons")):
            errors.append(f"manual_backfill_fulfillment_item_blocking_reasons_on_fulfilled:{key}")
        if item.get("presence_mismatch") is not False:
            errors.append(f"manual_backfill_fulfillment_item_presence_mismatch_invalid:{key}")

    for command in (
        "make au-p0b-google-manual-backfill-request",
        "make verify-au-p0b-google-manual-backfill-request",
        "make verify-au-p0b-google-manual-backfill",
        "make verify-au-p0b-google-manual-backfill-fulfillment",
    ):
        if command not in verification_commands:
            errors.append(f"verification_command_missing:{command}")
    if "make verify-au-p0b-google-manual-backfill-fulfillment" not in hard_gate_commands:
        errors.append("hard_gate_missing:make verify-au-p0b-google-manual-backfill-fulfillment")
    if not any("--require-fulfilled" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_fulfilled")
    if not any("--require-manual-backfill-ready" in command for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_manual_backfill_ready")
    if endpoints.get("p0b_google_manual_backfill_fulfillment") != "GET /v1/p0b-google-manual-backfill-fulfillment/au":
        errors.append("runtime_endpoint_p0b_google_manual_backfill_fulfillment_invalid")
    if endpoints.get("p0b_google_manual_backfill_request") != "GET /v1/p0b-google-manual-backfill-request/au":
        errors.append("runtime_endpoint_p0b_google_manual_backfill_request_invalid")
    if redaction_policy.get("raw_answer_values_allowed") is not False:
        errors.append("redaction_policy_raw_answer_invalid")
    if redaction_policy.get("raw_citation_values_allowed") is not False:
        errors.append("redaction_policy_raw_citation_invalid")
    if redaction_policy.get("raw_asset_urls_allowed") is not False:
        errors.append("redaction_policy_raw_asset_invalid")
    if redaction_policy.get("manual_jsonl_path_redacted") is not True:
        errors.append("redaction_policy_manual_path_invalid")
    if require_fulfilled and not manual_backfill_fulfilled:
        errors.append("p0b_google_manual_backfill_not_fulfilled")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0b_google_manual_backfill_fulfillment_version": payload.get(
            "p0b_google_manual_backfill_fulfillment_version",
            "",
        ),
        "p0b_google_manual_backfill_fulfillment_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0b_google_manual_backfill_fulfillment_hash": computed_hash,
        "hash_valid": hash_valid,
        "manual_backfill_fulfillment_ready": expected_ready,
        "manual_backfill_fulfilled": manual_backfill_fulfilled,
        "missing_required_count": len(missing_required),
        "missing_required": missing_required,
        "record_count": summary.get("record_count"),
        "expected_record_count": summary.get("expected_record_count"),
        "covered_prompt_city_count": summary.get("covered_prompt_city_count"),
        "expected_prompt_city_count": summary.get("expected_prompt_city_count"),
        "manual_backfill_ready": summary.get("manual_backfill_ready") is True,
        "manual_backfill_coverage_complete": summary.get("manual_backfill_coverage_complete") is True,
        "manual_backfill_content_complete": summary.get("manual_backfill_content_complete") is True,
        "missing_prompt_city_sample_count": summary.get("missing_prompt_city_sample_count"),
        "duplicate_prompt_city_sample_count": summary.get("duplicate_prompt_city_sample_count"),
        "unexpected_prompt_city_record_count": summary.get("unexpected_prompt_city_record_count"),
        "missing_answer_line_count": summary.get("missing_answer_line_count"),
        "missing_citation_line_count": summary.get("missing_citation_line_count"),
        "missing_asset_line_count": summary.get("missing_asset_line_count"),
        "missing_total_content_cell_count": summary.get("missing_total_content_cell_count"),
        "manual_content_completion_handoff_ready": summary.get("manual_content_completion_handoff_ready") is True,
        "post_content_completion_validation_command_count": summary.get(
            "post_content_completion_validation_command_count",
        ),
        "verification_next_action": summary.get("verification_next_action", ""),
        "next_action": summary.get("next_action", ""),
    }


def _actual_value(items: list[dict[str, Any]], key: str) -> object:
    for item in items:
        if item.get("key") == key:
            return item.get("actual_value")
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google manual backfill fulfillment JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google manual backfill fulfillment JSON.",
    )
    parser.add_argument(
        "--require-fulfilled",
        action="store_true",
        help="Fail unless P0b Google manual backfill verification is fulfilled.",
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
            "errors": ["p0b_google_manual_backfill_fulfillment_file_missing"],
            "hash_valid": False,
            "manual_backfill_fulfillment_ready": False,
            "manual_backfill_fulfilled": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0b_google_manual_backfill_fulfillment_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "manual_backfill_fulfillment_ready": False,
            "manual_backfill_fulfilled": False,
        }
    else:
        result = verify_au_p0b_google_manual_backfill_fulfillment(
            payload,
            path=path,
            require_fulfilled=args.require_fulfilled,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
