from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_au_p0b_google_manual_backfill_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_MANUAL_BACKFILL_REQUEST_PATH,
    build_au_p0b_google_manual_backfill_request_packet,
)
from scripts.verify_au_p0b_google_manual_backfill_request_packet import (  # noqa: E402
    verify_au_p0b_google_manual_backfill_request_packet,
)
from scripts.verify_au_p0b_manual_backfill import (  # noqa: E402
    DEFAULT_INPUT_PATH as DEFAULT_MANUAL_BACKFILL_INPUT_PATH,
    DEFAULT_VERIFICATION_PATH as DEFAULT_MANUAL_BACKFILL_VERIFICATION_PATH,
    verify_manual_backfill,
    verify_manual_backfill_verification_result,
)


FULFILLMENT_VERSION = "au_p0b_google_manual_backfill_fulfillment_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-manual-backfill-fulfillment-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0b_google_manual_backfill_fulfillment_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("p0b_google_manual_backfill_fulfillment_hash", None)
    return hashlib.sha256(_stable_bytes(payload_for_hash)).hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _load_json(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, {"path": str(path), "exists": False, "source": "missing_file", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        return None, {
            "path": str(path),
            "exists": True,
            "source": "invalid_file",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if not isinstance(payload, dict):
        return None, {"path": str(path), "exists": True, "source": "invalid_file", "errors": ["not_json_object"]}
    return payload, {"path": str(path), "exists": True, "source": "existing_file", "errors": []}


def _load_or_build_request(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    request = build_au_p0b_google_manual_backfill_request_packet(output_path=path, generated_at=generated_at)
    return request, {**source, "source": "generated_in_memory"}


def _manual_jsonl_path(
    *,
    manual_jsonl_path: Path | None,
    request: dict[str, Any],
) -> Path:
    if manual_jsonl_path is not None:
        return manual_jsonl_path
    request_summary = _as_dict(request.get("summary"))
    request_payload = _as_dict(request.get("manual_backfill_request"))
    configured = (
        str(request_summary.get("target_jsonl_path") or "").strip()
        or str(request_payload.get("target_jsonl_path") or "").strip()
        or DEFAULT_MANUAL_BACKFILL_INPUT_PATH
    )
    return Path(configured)


def _load_or_build_verification(
    path: Path,
    *,
    manual_jsonl_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    verification = verify_manual_backfill(manual_jsonl_path)
    return verification, {
        **source,
        "source": "generated_in_memory",
        "manual_jsonl_path": str(manual_jsonl_path),
    }


def _error_count(prefix: str, errors: list[str]) -> int:
    for error in errors:
        if error.startswith(prefix):
            _, _, raw_count = error.partition(":")
            return _int(raw_count.split("/", maxsplit=1)[0])
    return 0


def _has_error_prefix(prefix: str, errors: list[str]) -> bool:
    return any(error.startswith(prefix) for error in errors)


def _fulfillment_items(request: dict[str, Any], verification: dict[str, Any], *, verification_hash_valid: bool) -> list[dict[str, Any]]:
    request_summary = _as_dict(request.get("summary"))
    request_payload = _as_dict(request.get("manual_backfill_request"))
    errors = _strings(verification.get("errors"))
    expected_record_count = _int(request_summary.get("expected_record_count") or request_payload.get("expected_record_count"))
    expected_prompt_city_count = _int(
        request_summary.get("expected_prompt_city_count") or request_payload.get("expected_prompt_city_count")
    )
    expected_sample_size = _int(request_summary.get("expected_sample_size") or request_payload.get("expected_sample_size"))
    verification_record_count = _int(verification.get("record_count"))
    verification_prompt_city_count = _int(verification.get("covered_prompt_city_count"))
    verification_expected_sample_size = _int(verification.get("expected_sample_size"))
    request_file_sha = str(request_payload.get("file_sha256") or "")
    verification_file_sha = str(verification.get("file_sha256") or "")
    request_verification_hash = str(request_payload.get("verification_hash") or "")
    verification_hash = str(verification.get("verification_hash") or "")
    item_specs = [
        {
            "key": "verification:status",
            "category": "verification",
            "expected_value": "pass",
            "actual_value": str(verification.get("status") or ""),
            "fulfilled": verification.get("status") == "pass" and verification_hash_valid,
            "blocking_reasons": []
            if verification.get("status") == "pass" and verification_hash_valid
            else ["manual_backfill_verification_not_pass"],
        },
        {
            "key": "verification:hash",
            "category": "verification",
            "expected_value": request_verification_hash,
            "actual_value": verification_hash,
            "fulfilled": bool(verification_hash) and verification_hash_valid and (not request_verification_hash or request_verification_hash == verification_hash),
            "blocking_reasons": []
            if bool(verification_hash)
            and verification_hash_valid
            and (not request_verification_hash or request_verification_hash == verification_hash)
            else ["manual_backfill_verification_hash_missing_or_mismatch"],
        },
        {
            "key": "file:manual_jsonl_sha256",
            "category": "file",
            "expected_value": request_file_sha,
            "actual_value": verification_file_sha,
            "fulfilled": bool(verification_file_sha),
            "blocking_reasons": []
            if bool(verification_file_sha)
            else ["manual_backfill_file_sha_missing"],
        },
        {
            "key": "count:record_count",
            "category": "coverage",
            "expected_value": expected_record_count,
            "actual_value": verification_record_count,
            "fulfilled": expected_record_count > 0 and verification_record_count == expected_record_count,
            "blocking_reasons": []
            if expected_record_count > 0 and verification_record_count == expected_record_count
            else ["manual_backfill_record_count_incomplete"],
        },
        {
            "key": "count:prompt_city_coverage",
            "category": "coverage",
            "expected_value": expected_prompt_city_count,
            "actual_value": verification_prompt_city_count,
            "fulfilled": expected_prompt_city_count > 0 and verification_prompt_city_count == expected_prompt_city_count,
            "blocking_reasons": []
            if expected_prompt_city_count > 0 and verification_prompt_city_count == expected_prompt_city_count
            else ["manual_backfill_prompt_city_coverage_incomplete"],
        },
        {
            "key": "count:sample_size",
            "category": "coverage",
            "expected_value": expected_sample_size,
            "actual_value": verification_expected_sample_size,
            "fulfilled": expected_sample_size > 0 and verification_expected_sample_size == expected_sample_size,
            "blocking_reasons": []
            if expected_sample_size > 0 and verification_expected_sample_size == expected_sample_size
            else ["manual_backfill_sample_size_mismatch"],
        },
        {
            "key": "content:answer_text",
            "category": "content",
            "expected_value": 0,
            "actual_value": _error_count("answer_text_missing", errors),
            "fulfilled": not _has_error_prefix("answer_text_missing", errors),
            "blocking_reasons": []
            if not _has_error_prefix("answer_text_missing", errors)
            else ["manual_backfill_answer_text_missing"],
        },
        {
            "key": "content:citation_urls",
            "category": "content",
            "expected_value": 0,
            "actual_value": _error_count("citation_urls_missing", errors),
            "fulfilled": not _has_error_prefix("citation_urls_missing", errors),
            "blocking_reasons": []
            if not _has_error_prefix("citation_urls_missing", errors)
            else ["manual_backfill_citation_urls_missing"],
        },
        {
            "key": "content:evidence_asset",
            "category": "content",
            "expected_value": 0,
            "actual_value": _error_count("evidence_asset_missing", errors),
            "fulfilled": not _has_error_prefix("evidence_asset_missing", errors),
            "blocking_reasons": []
            if not _has_error_prefix("evidence_asset_missing", errors)
            else ["manual_backfill_evidence_asset_missing"],
        },
        {
            "key": "structure:prompt_city_samples",
            "category": "structure",
            "expected_value": "complete_unique_expected_matrix",
            "actual_value": ",".join(
                error
                for error in errors
                if error.startswith(("missing_prompt_city_samples", "duplicate_prompt_city_samples", "unexpected_prompt_city_records"))
            ),
            "fulfilled": not any(
                error.startswith(("missing_prompt_city_samples", "duplicate_prompt_city_samples", "unexpected_prompt_city_records"))
                for error in errors
            ),
            "blocking_reasons": []
            if not any(
                error.startswith(("missing_prompt_city_samples", "duplicate_prompt_city_samples", "unexpected_prompt_city_records"))
                for error in errors
            )
            else ["manual_backfill_prompt_city_samples_invalid"],
        },
    ]
    items: list[dict[str, Any]] = []
    for spec in item_specs:
        blocking_reasons = [str(reason) for reason in spec["blocking_reasons"]]
        items.append(
            {
                "key": spec["key"],
                "category": spec["category"],
                "required": True,
                "fulfilled": spec["fulfilled"] is True,
                "expected_value": spec["expected_value"],
                "actual_value": spec["actual_value"],
                "presence_mismatch": False,
                "owner_hint": "google_manual_backfill_operator",
                "source_request_field": _source_request_field(str(spec["key"])),
                "source_verification_field": _source_verification_field(str(spec["key"])),
                "blocking_reasons": blocking_reasons,
            }
        )
    return items


def _source_request_field(key: str) -> str:
    return {
        "verification:status": "manual_backfill_request.status",
        "verification:hash": "manual_backfill_request.verification_hash",
        "file:manual_jsonl_sha256": "manual_backfill_request.file_sha256",
        "count:record_count": "summary.expected_record_count",
        "count:prompt_city_coverage": "summary.expected_prompt_city_count",
        "count:sample_size": "summary.expected_sample_size",
        "content:answer_text": "required_fields.answer_text",
        "content:citation_urls": "required_fields.citation_urls",
        "content:evidence_asset": "required_fields.screenshot_url_or_html_snapshot_url",
        "structure:prompt_city_samples": "operator_requirements.preserve_prompt_city_sample_index_and_sample_size",
    }.get(key, "")


def _source_verification_field(key: str) -> str:
    return {
        "verification:status": "status",
        "verification:hash": "verification_hash",
        "file:manual_jsonl_sha256": "file_sha256",
        "count:record_count": "record_count",
        "count:prompt_city_coverage": "covered_prompt_city_count",
        "count:sample_size": "expected_sample_size",
        "content:answer_text": "errors.answer_text_missing",
        "content:citation_urls": "errors.citation_urls_missing",
        "content:evidence_asset": "errors.evidence_asset_missing",
        "structure:prompt_city_samples": "errors.prompt_city_sample_set",
    }.get(key, "")


def _missing_by_owner(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for item in items:
        if item.get("required") is True and item.get("fulfilled") is not True:
            owner = str(item.get("owner_hint") or "unknown")
            owners.setdefault(owner, []).append(str(item.get("key") or ""))
    return {owner: sorted(keys) for owner, keys in sorted(owners.items())}


def _next_action(missing_required: list[str], verification_status: str) -> str:
    if "verification:status" in missing_required and verification_status != "pass":
        return "complete_manual_backfill_jsonl"
    if missing_required:
        return "refresh_manual_backfill_verification"
    return "run_p0b_google_manual_backfill_strict_gate"


def build_au_p0b_google_manual_backfill_fulfillment(
    *,
    manual_backfill_request_path: Path = Path(DEFAULT_MANUAL_BACKFILL_REQUEST_PATH),
    manual_backfill_verification_path: Path = Path(DEFAULT_MANUAL_BACKFILL_VERIFICATION_PATH),
    manual_jsonl_path: Path | None = None,
    manual_backfill_request: dict[str, Any] | None = None,
    manual_backfill_verification: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if manual_backfill_request is None:
        manual_backfill_request, request_source = _load_or_build_request(
            manual_backfill_request_path,
            generated_at=generated_at,
        )
    else:
        request_source = {"path": str(manual_backfill_request_path), "exists": True, "source": "provided_payload", "errors": []}
    resolved_manual_jsonl_path = _manual_jsonl_path(
        manual_jsonl_path=manual_jsonl_path,
        request=manual_backfill_request,
    )
    if manual_backfill_verification is None:
        manual_backfill_verification, verification_source = _load_or_build_verification(
            manual_backfill_verification_path,
            manual_jsonl_path=resolved_manual_jsonl_path,
        )
    else:
        verification_source = {
            "path": str(manual_backfill_verification_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
            "manual_jsonl_path": str(resolved_manual_jsonl_path),
        }

    request_verifier = verify_au_p0b_google_manual_backfill_request_packet(
        manual_backfill_request,
        path=manual_backfill_request_path,
    )
    verification_verifier = verify_manual_backfill_verification_result(
        manual_backfill_verification,
        path=manual_backfill_verification_path,
    )
    request_ready = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    verification_ready = verification_verifier.get("status") == "pass" and verification_verifier.get("hash_valid") is True
    items = _fulfillment_items(
        manual_backfill_request,
        manual_backfill_verification,
        verification_hash_valid=verification_verifier.get("hash_valid") is True,
    )
    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True)
    manual_backfill_fulfilled = bool(required_items) and len(fulfilled_required) == len(required_items)
    request_summary = _as_dict(manual_backfill_request.get("summary"))
    request_payload = _as_dict(manual_backfill_request.get("manual_backfill_request"))
    verification_summary = _as_dict(manual_backfill_verification.get("summary"))
    verification_errors = _strings(manual_backfill_verification.get("errors"))
    strict_gate_command = (
        "PYTHONPATH=packages/geno_core:apps/api python3 "
        "scripts/verify_au_p0b_google_manual_backfill_fulfillment.py "
        "${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-fulfillment-latest.json} "
        "--require-fulfilled"
    )
    request_strict_gate_command = (
        "PYTHONPATH=packages/geno_core:apps/api python3 "
        "scripts/verify_au_p0b_google_manual_backfill_request_packet.py "
        "${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-request-latest.json} "
        "--require-manual-backfill-ready"
    )
    summary = {
        "manual_backfill_fulfilled": manual_backfill_fulfilled,
        "manual_backfill_request_ready": request_ready,
        "manual_backfill_handoff_ready": manual_backfill_request.get("manual_backfill_handoff_ready") is True,
        "manual_backfill_verification_ready": verification_ready,
        "manual_backfill_verification_status": str(manual_backfill_verification.get("status") or ""),
        "manual_backfill_verification_hash": str(manual_backfill_verification.get("verification_hash") or ""),
        "manual_backfill_ready": verification_summary.get("manual_backfill_ready") is True,
        "manual_backfill_coverage_complete": verification_summary.get("coverage_complete") is True,
        "manual_backfill_content_complete": verification_summary.get("content_complete") is True,
        "expected_record_count": _int(request_summary.get("expected_record_count") or request_payload.get("expected_record_count")),
        "record_count": _int(manual_backfill_verification.get("record_count")),
        "expected_prompt_city_count": _int(
            request_summary.get("expected_prompt_city_count") or request_payload.get("expected_prompt_city_count")
        ),
        "covered_prompt_city_count": _int(manual_backfill_verification.get("covered_prompt_city_count")),
        "expected_sample_size": _int(request_summary.get("expected_sample_size") or request_payload.get("expected_sample_size")),
        "verification_expected_sample_size": _int(manual_backfill_verification.get("expected_sample_size")),
        "missing_prompt_city_sample_count": _int(
            verification_summary.get("missing_prompt_city_sample_count")
            or manual_backfill_verification.get("missing_prompt_city_sample_count")
        ),
        "duplicate_prompt_city_sample_count": _int(
            verification_summary.get("duplicate_prompt_city_sample_count")
            or manual_backfill_verification.get("duplicate_prompt_city_sample_count")
        ),
        "unexpected_prompt_city_record_count": _int(
            verification_summary.get("unexpected_prompt_city_record_count")
            or manual_backfill_verification.get("unexpected_prompt_city_record_count")
        ),
        "missing_answer_line_count": _int(
            verification_summary.get("missing_answer_line_count") or manual_backfill_verification.get("missing_answer_line_count")
        ),
        "missing_citation_line_count": _int(
            verification_summary.get("missing_citation_line_count")
            or manual_backfill_verification.get("missing_citation_line_count")
        ),
        "missing_asset_line_count": _int(
            verification_summary.get("missing_asset_line_count") or manual_backfill_verification.get("missing_asset_line_count")
        ),
        "verification_error_count": len(verification_errors),
        "verification_errors": verification_errors,
        "required_count": len(required_items),
        "fulfilled_required_count": len(fulfilled_required),
        "missing_required_count": len(missing_required),
        "missing_required": missing_required,
        "missing_required_by_owner": _missing_by_owner(items),
        "target_jsonl_path": str(request_summary.get("target_jsonl_path") or request_payload.get("target_jsonl_path") or ""),
        "resolved_manual_jsonl_path": str(resolved_manual_jsonl_path),
        "verification_path": str(request_summary.get("verification_path") or request_payload.get("verification_path") or ""),
        "file_sha256_present": bool(manual_backfill_verification.get("file_sha256")),
        "verification_hash_present": bool(manual_backfill_verification.get("verification_hash")),
        "content_redacted": request_summary.get("content_redacted") is True,
        "raw_answer_values_allowed": False,
        "raw_citation_values_allowed": False,
        "raw_asset_urls_allowed": False,
        "verification_next_action": str(verification_summary.get("next_action") or ""),
        "next_action": _next_action(missing_required, str(manual_backfill_verification.get("status") or "")),
        "next_command": "make verify-au-p0b-google-manual-backfill"
        if missing_required
        else "make verify-au-p0b-google-manual-backfill-fulfillment",
        "strict_gate_command": strict_gate_command,
        "request_strict_gate_command": request_strict_gate_command,
    }

    payload: dict[str, Any] = {
        "p0b_google_manual_backfill_fulfillment_version": FULFILLMENT_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if request_ready and verification_ready else "fail",
        "manual_backfill_fulfillment_ready": request_ready and verification_ready,
        "manual_backfill_fulfilled": manual_backfill_fulfilled,
        "google_main_scoring_allowed": (
            manual_backfill_fulfilled and manual_backfill_request.get("google_main_scoring_allowed") is True
        ),
        "output_path": str(output_path) if output_path else "",
        "source_p0b_google_manual_backfill_request": {
            "path": str(manual_backfill_request_path),
            "source": request_source,
            "p0b_google_manual_backfill_request_packet_hash": str(
                manual_backfill_request.get("p0b_google_manual_backfill_request_packet_hash") or ""
            ),
            "manual_backfill_request_packet_ready": manual_backfill_request.get(
                "manual_backfill_request_packet_ready"
            )
            is True,
            "manual_backfill_handoff_ready": manual_backfill_request.get("manual_backfill_handoff_ready") is True,
            "google_main_scoring_allowed": manual_backfill_request.get("google_main_scoring_allowed") is True,
        },
        "source_p0b_google_manual_backfill_verification": {
            "path": str(manual_backfill_verification_path),
            "source": verification_source,
            "manual_jsonl_path": str(manual_backfill_verification.get("path") or resolved_manual_jsonl_path),
            "verification_hash": str(manual_backfill_verification.get("verification_hash") or ""),
            "manual_backfill_status": str(manual_backfill_verification.get("status") or ""),
            "file_sha256": str(manual_backfill_verification.get("file_sha256") or ""),
            "allow_template_placeholders": manual_backfill_verification.get("allow_template_placeholders") is True,
        },
        "p0b_google_manual_backfill_request_verifier": {
            "status": request_verifier.get("status", ""),
            "hash_valid": request_verifier.get("hash_valid") is True,
            "p0b_google_manual_backfill_request_packet_hash": str(
                request_verifier.get("p0b_google_manual_backfill_request_packet_hash") or ""
            ),
            "manual_backfill_request_packet_ready": request_verifier.get("manual_backfill_request_packet_ready") is True,
            "manual_backfill_handoff_ready": request_verifier.get("manual_backfill_handoff_ready") is True,
            "errors": _strings(request_verifier.get("errors")),
        },
        "p0b_google_manual_backfill_verification_verifier": {
            "status": verification_verifier.get("status", ""),
            "hash_valid": verification_verifier.get("hash_valid") is True,
            "verification_hash": str(verification_verifier.get("verification_hash") or ""),
            "manual_backfill_status": str(verification_verifier.get("manual_backfill_status") or ""),
            "manual_backfill_ready": verification_verifier.get("manual_backfill_ready") is True,
            "coverage_complete": verification_verifier.get("coverage_complete") is True,
            "content_complete": verification_verifier.get("content_complete") is True,
            "expected_prompt_city_count": _int(verification_verifier.get("expected_prompt_city_count")),
            "expected_sample_size": _int(verification_verifier.get("expected_sample_size")),
            "expected_record_count": _int(verification_verifier.get("expected_record_count")),
            "record_count": _int(verification_verifier.get("record_count")),
            "covered_prompt_city_count": _int(verification_verifier.get("covered_prompt_city_count")),
            "missing_prompt_city_sample_count": _int(verification_verifier.get("missing_prompt_city_sample_count")),
            "duplicate_prompt_city_sample_count": _int(verification_verifier.get("duplicate_prompt_city_sample_count")),
            "unexpected_prompt_city_record_count": _int(verification_verifier.get("unexpected_prompt_city_record_count")),
            "missing_answer_line_count": _int(verification_verifier.get("missing_answer_line_count")),
            "missing_citation_line_count": _int(verification_verifier.get("missing_citation_line_count")),
            "missing_asset_line_count": _int(verification_verifier.get("missing_asset_line_count")),
            "error_count": _int(verification_verifier.get("error_count")),
            "next_action": str(verification_verifier.get("next_action") or ""),
            "errors": _strings(verification_verifier.get("errors")),
        },
        "summary": summary,
        "manual_backfill_fulfillment_items": items,
        "verification_commands": [
            "make au-p0b-google-manual-backfill-request",
            "make verify-au-p0b-google-manual-backfill-request",
            "make verify-au-p0b-google-manual-backfill",
            "make verify-au-p0b-google-manual-backfill-fulfillment",
        ],
        "hard_gate_commands": [
            "make verify-au-p0b-google-manual-backfill-fulfillment",
            strict_gate_command,
            request_strict_gate_command,
        ],
        "runtime_endpoints": {
            "p0b_google_manual_backfill_fulfillment": "GET /v1/p0b-google-manual-backfill-fulfillment/au",
            "p0b_google_manual_backfill_request": "GET /v1/p0b-google-manual-backfill-request/au",
            "p0b_google_execution_checklist": "GET /v1/p0b-google-execution-checklist/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
        },
        "redaction_policy": {
            "raw_answer_values_allowed": False,
            "raw_citation_values_allowed": False,
            "raw_asset_urls_allowed": False,
            "manual_jsonl_path_redacted": True,
            "recorded_fields": [
                "status",
                "errors",
                "counts",
                "line_number_samples",
                "file_sha256",
                "verification_hash",
            ],
            "forbidden_exact_manual_field_count": 10,
        },
    }
    payload["p0b_google_manual_backfill_fulfillment_hash"] = compute_p0b_google_manual_backfill_fulfillment_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google manual backfill fulfillment JSON")
    parser.add_argument(
        "--manual-backfill-request-path",
        default=os.environ.get(
            "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_REQUEST_OUTPUT_PATH",
            DEFAULT_MANUAL_BACKFILL_REQUEST_PATH,
        ),
        help="Path to the AU P0b Google manual backfill request packet JSON.",
    )
    parser.add_argument(
        "--manual-backfill-verification-path",
        default=os.environ.get(
            "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_VERIFICATION_PATH",
            DEFAULT_MANUAL_BACKFILL_VERIFICATION_PATH,
        ),
        help="Path to the AU P0b Google manual backfill verification JSON.",
    )
    parser.add_argument(
        "--manual-jsonl-path",
        default=os.environ.get("MANUAL_BACKFILL_PATH", ""),
        help="Path to the manual JSONL when the verification artifact must be generated in memory.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0b Google manual backfill fulfillment JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0b_google_manual_backfill_fulfillment(
        manual_backfill_request_path=Path(args.manual_backfill_request_path),
        manual_backfill_verification_path=Path(args.manual_backfill_verification_path),
        manual_jsonl_path=Path(args.manual_jsonl_path) if args.manual_jsonl_path else None,
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
