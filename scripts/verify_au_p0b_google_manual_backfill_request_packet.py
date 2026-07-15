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

from scripts.build_au_p0b_google_manual_backfill_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    PACKET_VERSION,
    compute_p0b_google_manual_backfill_request_packet_hash,
)


REQUIRED_FIELDS = (
    "p0b_google_manual_backfill_request_packet_version",
    "generated_at",
    "status",
    "manual_backfill_request_packet_ready",
    "manual_backfill_handoff_ready",
    "google_main_scoring_allowed",
    "output_path",
    "source_p0b_google_execution_checklist",
    "p0b_google_execution_checklist_verifier",
    "summary",
    "manual_backfill_request",
    "required_fields",
    "operator_requirements",
    "setup_commands",
    "verification_commands",
    "evidence_outputs",
    "redaction_policy",
    "runtime_endpoints",
    "hard_gate_commands",
    "evidence_sources",
    "p0b_google_manual_backfill_request_packet_hash",
)

FORBIDDEN_MANUAL_PAYLOAD_FIELDS = {
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


def _string_list(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _find_forbidden_manual_payload_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_MANUAL_PAYLOAD_FIELDS:
                findings.append(child_path)
            findings.extend(_find_forbidden_manual_payload_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_manual_payload_fields(child, path=f"{path}[{index}]"))
    return findings


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _expected_ready(request: dict[str, Any]) -> bool:
    missing_reasons = _string_list(request.get("missing_reasons"))
    return (
        request.get("ready") is True
        and request.get("status") == "pass"
        and request.get("hash_valid") is True
        and request.get("manual_backfill_ready") is True
        and not missing_reasons
    )


def verify_au_p0b_google_manual_backfill_request_packet(
    payload: Any,
    *,
    path: Path | None = None,
    require_manual_backfill_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0b_google_manual_backfill_request_packet_not_json_object"],
            "hash_valid": False,
            "manual_backfill_request_packet_ready": False,
            "manual_backfill_handoff_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0b_google_manual_backfill_request_packet_version") != PACKET_VERSION:
        errors.append("p0b_google_manual_backfill_request_packet_version_invalid")

    expected_hash = payload.get("p0b_google_manual_backfill_request_packet_hash")
    computed_hash = compute_p0b_google_manual_backfill_request_packet_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0b_google_manual_backfill_request_packet_hash_mismatch")

    verifier = _as_dict(payload.get("p0b_google_execution_checklist_verifier"))
    source = _as_dict(payload.get("source_p0b_google_execution_checklist"))
    summary = _as_dict(payload.get("summary"))
    request = _as_dict(payload.get("manual_backfill_request"))
    required_fields = _string_list(payload.get("required_fields"))
    operator_requirements = _string_list(payload.get("operator_requirements"))
    setup_commands = _string_list(payload.get("setup_commands"))
    verification_commands = _string_list(payload.get("verification_commands"))
    evidence_outputs = _string_list(payload.get("evidence_outputs"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    hard_gate_commands = _string_list(payload.get("hard_gate_commands"))

    packet_ready = verifier.get("status") == "pass" and verifier.get("hash_valid") is True
    if payload.get("manual_backfill_request_packet_ready") is not packet_ready:
        errors.append("manual_backfill_request_packet_ready_mismatch")
    if payload.get("status") != ("pass" if packet_ready else "fail"):
        errors.append("status_mismatch")
    if source.get("google_execution_checklist_hash") != verifier.get("google_execution_checklist_hash") and verifier.get(
        "google_execution_checklist_hash"
    ):
        errors.append("source_p0b_google_execution_checklist_hash_mismatch")

    missing_reasons = _string_list(request.get("missing_reasons"))
    if request.get("source_manual_backfill_handoff_version") != "au_p0b_google_manual_backfill_handoff_v1":
        errors.append("manual_backfill_request_source_version_invalid")
    if request.get("manual_jsonl_env_var") != "MANUAL_BACKFILL_PATH":
        errors.append("manual_backfill_request_env_var_invalid")
    if request.get("manual_jsonl_path_redacted") is not True:
        errors.append("manual_backfill_request_path_redaction_missing")
    if request.get("template_path") != "docs/runtime_preflight/au-p0b-google-manual-backfill-template.jsonl":
        errors.append("manual_backfill_request_template_path_invalid")
    if request.get("template_manifest_path") != "docs/runtime_preflight/au-p0b-google-manual-backfill-template-manifest.json":
        errors.append("manual_backfill_request_template_manifest_path_invalid")
    if not isinstance(request.get("verification_path"), str) or not request.get("verification_path"):
        errors.append("manual_backfill_request_verification_path_missing")
    if request.get("missing_reason_count") != len(missing_reasons):
        errors.append("manual_backfill_request_missing_reason_count_mismatch")
    if payload.get("manual_backfill_handoff_ready") is not _expected_ready(request):
        errors.append("manual_backfill_handoff_ready_mismatch")
    if summary.get("manual_backfill_handoff_ready") is not _expected_ready(request):
        errors.append("summary_manual_backfill_handoff_ready_mismatch")

    prompt_count = _int(request.get("prompt_count"))
    geo_city_count = len(_string_list(request.get("geo_cities")))
    expected_prompt_city_count = _int(request.get("expected_prompt_city_count"))
    expected_sample_size = _int(request.get("expected_sample_size"))
    expected_record_count = _int(request.get("expected_record_count"))
    record_count = _int(request.get("record_count"))
    covered_prompt_city_count = _int(request.get("covered_prompt_city_count"))
    if prompt_count <= 0:
        errors.append("manual_backfill_request_prompt_count_empty")
    if geo_city_count <= 0:
        errors.append("manual_backfill_request_geo_cities_empty")
    if expected_sample_size <= 0:
        errors.append("manual_backfill_request_expected_sample_size_empty")
    if expected_prompt_city_count != prompt_count * geo_city_count:
        errors.append("manual_backfill_request_prompt_city_count_mismatch")
    if expected_record_count != expected_prompt_city_count * expected_sample_size:
        errors.append("manual_backfill_request_expected_record_count_mismatch")
    if record_count > expected_record_count:
        errors.append("manual_backfill_request_record_count_exceeds_expected")
    if covered_prompt_city_count > expected_prompt_city_count:
        errors.append("manual_backfill_request_covered_prompt_city_count_exceeds_expected")
    if _expected_ready(request):
        if record_count != expected_record_count:
            errors.append("manual_backfill_request_ready_record_count_mismatch")
        if covered_prompt_city_count != expected_prompt_city_count:
            errors.append("manual_backfill_request_ready_prompt_city_coverage_mismatch")
        if not request.get("file_sha256") or not request.get("verification_hash"):
            errors.append("manual_backfill_request_ready_hashes_missing")

    for summary_field, request_field in (
        ("source_manual_backfill_handoff_version", "source_manual_backfill_handoff_version"),
        ("manual_backfill_handoff_status", "status"),
        ("hash_valid", "hash_valid"),
        ("manual_backfill_ready", "manual_backfill_ready"),
        ("manual_jsonl_env_var", "manual_jsonl_env_var"),
        ("target_jsonl_path", "target_jsonl_path"),
        ("target_jsonl_path_source", "target_jsonl_path_source"),
        ("manual_jsonl_path_redacted", "manual_jsonl_path_redacted"),
        ("template_path", "template_path"),
        ("template_manifest_path", "template_manifest_path"),
        ("verification_path", "verification_path"),
        ("expected_record_count", "expected_record_count"),
        ("record_count", "record_count"),
        ("expected_prompt_city_count", "expected_prompt_city_count"),
        ("covered_prompt_city_count", "covered_prompt_city_count"),
        ("expected_sample_size", "expected_sample_size"),
        ("prompt_count", "prompt_count"),
        ("missing_reason_count", "missing_reason_count"),
    ):
        if summary.get(summary_field) != request.get(request_field):
            errors.append(f"summary_{summary_field}_mismatch")
    if summary.get("geo_city_count") != geo_city_count:
        errors.append("summary_geo_city_count_mismatch")
    if _string_list(summary.get("geo_cities")) != _string_list(request.get("geo_cities")):
        errors.append("summary_geo_cities_mismatch")
    if _string_list(summary.get("missing_reasons")) != missing_reasons:
        errors.append("summary_missing_reasons_mismatch")

    for required in ("answer_text", "citation_urls", "screenshot_url or html_snapshot_url"):
        if required not in required_fields:
            errors.append(f"required_field_missing:{required}")
    for requirement in (
        "fill_answer_text_for_each_record",
        "include_at_least_one_citation_url_for_each_record",
        "include_screenshot_url_or_html_snapshot_url_for_each_record",
        "preserve_prompt_city_sample_index_and_sample_size",
    ):
        if requirement not in operator_requirements:
            errors.append(f"operator_requirement_missing:{requirement}")
    if summary.get("required_field_count") != len(required_fields):
        errors.append("summary_required_field_count_mismatch")
    if summary.get("operator_requirement_count") != len(operator_requirements):
        errors.append("summary_operator_requirement_count_mismatch")
    if summary.get("setup_command_count") != len(setup_commands):
        errors.append("summary_setup_command_count_mismatch")
    if summary.get("verification_command_count") != len(verification_commands):
        errors.append("summary_verification_command_count_mismatch")
    if summary.get("evidence_output_count") != len(evidence_outputs):
        errors.append("summary_evidence_output_count_mismatch")
    if setup_commands and summary.get("next_command") != setup_commands[0]:
        errors.append("summary_next_command_mismatch")
    if verification_commands and summary.get("post_update_verification_command") != verification_commands[0]:
        errors.append("summary_post_update_verification_command_mismatch")

    if "make au-p0b-google-manual-template" not in setup_commands:
        errors.append("setup_command_missing:make au-p0b-google-manual-template")
    for command in (
        "make verify-au-p0b-google-manual-backfill",
        "make au-p0b-google-status",
        "make verify-au-p0b-google-status",
        "make au-p0b-google-package",
        "make verify-au-p0b-google-package",
        "make au-p0b-google-execution-checklist",
        "make verify-au-p0b-google-execution-checklist",
    ):
        if command not in verification_commands:
            errors.append(f"verification_command_missing:{command}")
    for output in (
        "docs/runtime_preflight/au-p0b-google-manual-backfill-template.jsonl",
        "docs/runtime_preflight/au-p0b-google-manual-backfill-template-manifest.json",
    ):
        if output not in evidence_outputs:
            errors.append(f"evidence_output_missing:{output}")
    if request.get("verification_path") not in evidence_outputs:
        errors.append("evidence_output_missing:manual_backfill_verification_path")

    if redaction_policy.get("raw_answer_values_allowed") is not False:
        errors.append("redaction_policy_raw_answer_invalid")
    if redaction_policy.get("raw_citation_values_allowed") is not False:
        errors.append("redaction_policy_raw_citation_invalid")
    if redaction_policy.get("raw_asset_urls_allowed") is not False:
        errors.append("redaction_policy_raw_asset_invalid")
    if redaction_policy.get("manual_jsonl_path_redacted") is not True:
        errors.append("redaction_policy_manual_path_invalid")
    if summary.get("raw_answer_values_allowed") is not False:
        errors.append("summary_raw_answer_policy_invalid")
    if summary.get("raw_citation_values_allowed") is not False:
        errors.append("summary_raw_citation_policy_invalid")
    if summary.get("raw_asset_urls_allowed") is not False:
        errors.append("summary_raw_asset_policy_invalid")
    if summary.get("content_redacted") is not True:
        errors.append("summary_content_redaction_missing")
    for finding in _find_forbidden_manual_payload_fields(payload):
        errors.append(f"forbidden_manual_payload_field:{finding}")

    if endpoints.get("p0b_google_manual_backfill_request") != "GET /v1/p0b-google-manual-backfill-request/au":
        errors.append("runtime_endpoint_p0b_google_manual_backfill_request_invalid")
    if endpoints.get("p0b_google_execution_checklist") != "GET /v1/p0b-google-execution-checklist/au":
        errors.append("runtime_endpoint_p0b_google_execution_checklist_invalid")
    if endpoints.get("p0b_google_environment_request") != "GET /v1/p0b-google-environment-request/au":
        errors.append("runtime_endpoint_p0b_google_environment_request_invalid")
    if endpoints.get("external_dependency_handoff") != "GET /v1/external-dependency-handoff/au":
        errors.append("runtime_endpoint_external_dependency_handoff_invalid")
    for required in (
        "make au-p0b-google-manual-backfill-request",
        "make verify-au-p0b-google-manual-backfill-request",
        "make au-p0b-google-manual-template",
        "make verify-au-p0b-google-manual-backfill",
    ):
        if required not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{required}")
    if not any(command.endswith("--require-manual-backfill-ready") for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_manual_backfill_ready")
    if require_manual_backfill_ready and payload.get("manual_backfill_handoff_ready") is not True:
        errors.append("p0b_google_manual_backfill_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0b_google_manual_backfill_request_packet_version": payload.get(
            "p0b_google_manual_backfill_request_packet_version",
            "",
        ),
        "p0b_google_manual_backfill_request_packet_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0b_google_manual_backfill_request_packet_hash": computed_hash,
        "hash_valid": hash_valid,
        "manual_backfill_request_packet_ready": packet_ready,
        "manual_backfill_handoff_ready": payload.get("manual_backfill_handoff_ready") is True,
        "missing_reason_count": len(missing_reasons),
        "expected_record_count": expected_record_count,
        "record_count": record_count,
        "covered_prompt_city_count": covered_prompt_city_count,
        "template_path": summary.get("template_path", ""),
        "next_command": summary.get("next_command", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google manual backfill request packet JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_MANUAL_BACKFILL_REQUEST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google manual backfill request packet JSON.",
    )
    parser.add_argument(
        "--require-manual-backfill-ready",
        action="store_true",
        help="Fail unless the 120-row manual backfill JSONL has passed strict verification.",
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
            "errors": ["p0b_google_manual_backfill_request_packet_file_missing"],
            "hash_valid": False,
            "manual_backfill_request_packet_ready": False,
            "manual_backfill_handoff_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0b_google_manual_backfill_request_packet_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "manual_backfill_request_packet_ready": False,
            "manual_backfill_handoff_ready": False,
        }
    else:
        result = verify_au_p0b_google_manual_backfill_request_packet(
            payload,
            path=path,
            require_manual_backfill_ready=args.require_manual_backfill_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
