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

from scripts.build_au_p0b_google_manual_backfill_fulfillment import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_MANUAL_BACKFILL_FULFILLMENT_PATH,
    build_au_p0b_google_manual_backfill_fulfillment,
)
from scripts.build_au_p0b_google_manual_backfill_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_MANUAL_BACKFILL_REQUEST_PATH,
    build_au_p0b_google_manual_backfill_request_packet,
)
from scripts.run_au_external_dependency_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH,
    run_au_external_dependency_clearance,
)
from scripts.verify_au_p0b_google_manual_backfill_fulfillment import (  # noqa: E402
    verify_au_p0b_google_manual_backfill_fulfillment,
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


CLEARANCE_VERSION = "au_p0b_google_manual_backfill_clearance_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-manual-backfill-clearance-latest.json"
STEP_ID = "p0b_google_manual_backfill"
PREREQUISITE_STEP_ID = "p0b_google_environment"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0b_google_manual_backfill_clearance_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("p0b_google_manual_backfill_clearance_hash", None)
    return hashlib.sha256(_stable_bytes(payload_for_hash)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    items: list[str] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            text = str(item.get("shell") or item.get("command") or item.get("id") or "").strip()
        else:
            text = str(item).strip()
        if text:
            items.append(text)
    return items


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _unique_strings(values: list[str]) -> list[str]:
    observed: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in observed:
            observed.add(value)
            result.append(value)
    return result


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
    return payload, {
        "path": str(path),
        "exists": True,
        "source": "existing_file",
        "file_sha256": _file_sha256(path),
        "errors": [],
    }


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
    summary = _as_dict(request.get("summary"))
    request_payload = _as_dict(request.get("manual_backfill_request"))
    configured = (
        str(summary.get("target_jsonl_path") or "").strip()
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


def _load_or_build_fulfillment(
    path: Path,
    *,
    request_path: Path,
    request: dict[str, Any],
    verification_path: Path,
    verification: dict[str, Any],
    manual_jsonl_path: Path,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    fulfillment = build_au_p0b_google_manual_backfill_fulfillment(
        manual_backfill_request_path=request_path,
        manual_backfill_request=request,
        manual_backfill_verification_path=verification_path,
        manual_backfill_verification=verification,
        manual_jsonl_path=manual_jsonl_path,
        output_path=path,
        generated_at=generated_at,
    )
    return fulfillment, {**source, "source": "generated_in_memory"}


def _load_or_build_external_clearance(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    clearance = run_au_external_dependency_clearance(output_path=path, generated_at=generated_at)
    return clearance, {**source, "source": "generated_in_memory"}


def _step_by_id(external_clearance: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in _as_list(external_clearance.get("steps")):
        step_dict = _as_dict(step)
        if step_dict.get("id") == step_id:
            return step_dict
    return {}


def _manual_items(manual_fulfillment: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for value in _as_list(manual_fulfillment.get("manual_backfill_fulfillment_items")):
        item = _as_dict(value)
        key = str(item.get("key") or "")
        items.append(
            {
                "key": key,
                "category": str(item.get("category") or ""),
                "required": item.get("required") is True,
                "fulfilled": item.get("fulfilled") is True,
                "expected_value": item.get("expected_value"),
                "actual_value": item.get("actual_value"),
                "presence_mismatch": item.get("presence_mismatch") is True,
                "owner_hint": str(item.get("owner_hint") or "google_manual_backfill_operator"),
                "source_request_field": str(item.get("source_request_field") or ""),
                "source_verification_field": str(item.get("source_verification_field") or ""),
                "blocking_reasons": _strings(item.get("blocking_reasons")),
            }
        )
    return items


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


def _operator_steps(
    *,
    manual_fulfillment: dict[str, Any],
    external_clearance: dict[str, Any],
    blocked_by_prerequisite: bool,
) -> list[dict[str, Any]]:
    summary = _as_dict(manual_fulfillment.get("summary"))
    steps: list[dict[str, Any]] = [
        {
            "order": 1,
            "id": "clear_p0b_google_environment",
            "command": "make au-p0b-google-environment-clearance && make verify-au-p0b-google-environment-clearance",
            "purpose": "clear_prerequisite_p0b_google_environment_before_manual_backfill",
            "external_call_risk": "none",
            "required_before_manual_backfill": True,
            "blocked": blocked_by_prerequisite,
        },
        {
            "order": 2,
            "id": "refresh_manual_backfill_request",
            "command": "make au-p0b-google-manual-backfill-request",
            "purpose": "refresh_120_row_manual_backfill_request_packet",
            "external_call_risk": "none",
        },
        {
            "order": 3,
            "id": "build_manual_backfill_template",
            "command": "make au-p0b-google-manual-template",
            "purpose": "create_or_refresh_manual_jsonl_template",
            "external_call_risk": "none",
        },
        {
            "order": 4,
            "id": "verify_manual_jsonl",
            "command": "make verify-au-p0b-google-manual-backfill",
            "purpose": "strictly_verify_120_row_manual_backfill_jsonl",
            "external_call_risk": "manual_operator_input",
        },
        {
            "order": 5,
            "id": "refresh_manual_backfill_fulfillment",
            "command": "make au-p0b-google-manual-backfill-fulfillment",
            "purpose": "align_request_and_strict_verification_into_fulfillment_artifact",
            "external_call_risk": "none",
        },
        {
            "order": 6,
            "id": "apply_current_manual_backfill_fix",
            "command": str(summary.get("next_command") or "make verify-au-p0b-google-manual-backfill"),
            "purpose": "apply_or_verify_current_unfulfilled_manual_backfill_input",
            "external_call_risk": "manual_operator_input",
            "next_action": str(summary.get("next_action") or ""),
        },
        {
            "order": 7,
            "id": "verify_manual_backfill_fulfillment",
            "command": "make verify-au-p0b-google-manual-backfill-fulfillment",
            "purpose": "prove_manual_backfill_fulfillment_is_current_or_still_blocked",
            "external_call_risk": "none",
        },
        {
            "order": 8,
            "id": "run_strict_gate",
            "command": str(summary.get("strict_gate_command") or ""),
            "purpose": "require_manual_backfill_fulfilled",
            "external_call_risk": "none",
        },
        {
            "order": 9,
            "id": "continue_clearance_sequence",
            "command": "then follow p0b_google_manual_backfill recommended_sequence from external dependency clearance",
            "purpose": "continue_to_p0b_google_phase_execution_after_manual_backfill_clear",
            "external_call_risk": "depends_on_next_sequence_step",
        },
    ]
    if _strings(external_clearance.get("current_recommended_sequence")):
        steps[0]["current_global_clearance_sequence"] = _strings(external_clearance.get("current_recommended_sequence"))
    return steps


def _post_update_validation_sequence(
    *,
    manual_request: dict[str, Any],
    manual_fulfillment: dict[str, Any],
    manual_step: dict[str, Any],
) -> list[str]:
    summary = _as_dict(manual_fulfillment.get("summary"))
    commands = [
        "make au-p0b-google-environment-clearance",
        "make verify-au-p0b-google-environment-clearance",
        "make au-p0b-google-manual-backfill-request",
        "make verify-au-p0b-google-manual-backfill-request",
        "make au-p0b-google-manual-template",
        "make verify-au-p0b-google-manual-backfill",
        "make au-p0b-google-manual-backfill-fulfillment",
        "make verify-au-p0b-google-manual-backfill-fulfillment",
        str(summary.get("request_strict_gate_command") or ""),
        str(summary.get("strict_gate_command") or ""),
    ]
    commands.extend(_strings(manual_request.get("setup_commands")))
    commands.extend(_strings(manual_request.get("verification_commands")))
    commands.extend(_strings(manual_fulfillment.get("verification_commands")))
    commands.extend(_strings(manual_fulfillment.get("hard_gate_commands")))
    commands.extend(_strings(manual_step.get("recommended_sequence")))
    return _unique_strings(commands)


def build_au_p0b_google_manual_backfill_clearance(
    *,
    manual_backfill_request_path: Path = Path(DEFAULT_MANUAL_BACKFILL_REQUEST_PATH),
    manual_backfill_verification_path: Path = Path(DEFAULT_MANUAL_BACKFILL_VERIFICATION_PATH),
    manual_backfill_fulfillment_path: Path = Path(DEFAULT_MANUAL_BACKFILL_FULFILLMENT_PATH),
    external_dependency_clearance_path: Path = Path(DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH),
    manual_jsonl_path: Path | None = None,
    manual_backfill_request: dict[str, Any] | None = None,
    manual_backfill_verification: dict[str, Any] | None = None,
    manual_backfill_fulfillment: dict[str, Any] | None = None,
    external_dependency_clearance: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if manual_backfill_request is None:
        manual_backfill_request, request_source = _load_or_build_request(
            manual_backfill_request_path,
            generated_at=generated_at,
        )
    else:
        request_source = {
            "path": str(manual_backfill_request_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

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

    if manual_backfill_fulfillment is None:
        manual_backfill_fulfillment, fulfillment_source = _load_or_build_fulfillment(
            manual_backfill_fulfillment_path,
            request_path=manual_backfill_request_path,
            request=manual_backfill_request,
            verification_path=manual_backfill_verification_path,
            verification=manual_backfill_verification,
            manual_jsonl_path=resolved_manual_jsonl_path,
            generated_at=generated_at,
        )
    else:
        fulfillment_source = {
            "path": str(manual_backfill_fulfillment_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if external_dependency_clearance is None:
        external_dependency_clearance, clearance_source = _load_or_build_external_clearance(
            external_dependency_clearance_path,
            generated_at=generated_at,
        )
    else:
        clearance_source = {
            "path": str(external_dependency_clearance_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    request_verifier = verify_au_p0b_google_manual_backfill_request_packet(
        manual_backfill_request,
        path=manual_backfill_request_path,
    )
    verification_verifier = verify_manual_backfill_verification_result(
        manual_backfill_verification,
        path=manual_backfill_verification_path,
    )
    fulfillment_verifier = verify_au_p0b_google_manual_backfill_fulfillment(
        manual_backfill_fulfillment,
        path=manual_backfill_fulfillment_path,
    )
    request_ok = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    verification_ok = verification_verifier.get("status") == "pass" and verification_verifier.get("hash_valid") is True
    fulfillment_ok = fulfillment_verifier.get("status") == "pass" and fulfillment_verifier.get("hash_valid") is True
    clearance_ok = external_dependency_clearance.get("status") == "pass"
    packet_ready = request_ok and verification_ok and fulfillment_ok and clearance_ok

    manual_step = _step_by_id(external_dependency_clearance, STEP_ID)
    prerequisite_step = _step_by_id(external_dependency_clearance, PREREQUISITE_STEP_ID)
    items = _manual_items(manual_backfill_fulfillment)
    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True)
    presence_mismatches = sorted(str(item.get("key") or "") for item in items if item.get("presence_mismatch") is True)
    manual_backfill_fulfilled = (
        bool(required_items) and len(fulfilled_required) == len(required_items) and not presence_mismatches
    )
    blocked_by_prerequisite = prerequisite_step.get("ready") is not True
    clearance_step_ready = manual_step.get("ready") is True
    clearance_step_can_start = manual_step.get("can_start") is True
    ready_for_next_clearance_step = manual_backfill_fulfilled and not blocked_by_prerequisite
    manual_backfill_clearance_ready = manual_backfill_fulfilled and clearance_step_ready and not blocked_by_prerequisite
    operator_steps = _operator_steps(
        manual_fulfillment=manual_backfill_fulfillment,
        external_clearance=external_dependency_clearance,
        blocked_by_prerequisite=blocked_by_prerequisite,
    )
    validation_sequence = _post_update_validation_sequence(
        manual_request=manual_backfill_request,
        manual_fulfillment=manual_backfill_fulfillment,
        manual_step=manual_step,
    )
    fulfillment_summary = _as_dict(manual_backfill_fulfillment.get("summary"))
    verification_errors = _strings(manual_backfill_verification.get("errors"))
    payload: dict[str, Any] = {
        "p0b_google_manual_backfill_clearance_version": CLEARANCE_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if packet_ready else "fail",
        "manual_backfill_clearance_packet_ready": packet_ready,
        "manual_backfill_fulfilled": manual_backfill_fulfilled,
        "manual_backfill_clearance_ready": manual_backfill_clearance_ready,
        "ready_for_next_clearance_step": ready_for_next_clearance_step,
        "blocked_by_prerequisite_step": blocked_by_prerequisite,
        "output_path": str(output_path) if output_path else "",
        "clearance_step": {
            "id": STEP_ID,
            "current_global_step_id": str(external_dependency_clearance.get("current_step_id") or ""),
            "current_global_step_is_prerequisite": external_dependency_clearance.get("current_step_id")
            == PREREQUISITE_STEP_ID,
            "step_recorded": bool(manual_step),
            "step_ready": clearance_step_ready,
            "step_can_start": clearance_step_can_start,
            "step_status": str(manual_step.get("status") or ""),
            "blocked_by": _strings(manual_step.get("blocked_by")),
            "would_execute": manual_step.get("would_execute") is True,
            "strict_gate_command": str(
                manual_step.get("strict_gate_command") or fulfillment_summary.get("strict_gate_command") or ""
            ),
        },
        "prerequisite_step": {
            "id": PREREQUISITE_STEP_ID,
            "ready": prerequisite_step.get("ready") is True,
            "status": str(prerequisite_step.get("status") or ""),
            "would_execute": prerequisite_step.get("would_execute") is True,
            "strict_gate_command": str(prerequisite_step.get("strict_gate_command") or ""),
            "blocked_by": _strings(prerequisite_step.get("blocked_by")),
            "runtime_endpoint": str(
                _as_dict(prerequisite_step.get("linked_request_context")).get("runtime_endpoint") or ""
            ),
        },
        "source_artifacts": {
            "manual_backfill_request": {
                "path": str(manual_backfill_request_path),
                "source": request_source,
                "hash_field": "p0b_google_manual_backfill_request_packet_hash",
                "hash": str(manual_backfill_request.get("p0b_google_manual_backfill_request_packet_hash") or ""),
                "verifier_status": request_verifier.get("status", ""),
                "hash_valid": request_verifier.get("hash_valid") is True,
            },
            "manual_backfill_verification": {
                "path": str(manual_backfill_verification_path),
                "source": verification_source,
                "manual_jsonl_path": str(manual_backfill_verification.get("path") or resolved_manual_jsonl_path),
                "hash_field": "verification_hash",
                "hash": str(manual_backfill_verification.get("verification_hash") or ""),
                "verifier_status": verification_verifier.get("status", ""),
                "hash_valid": verification_verifier.get("hash_valid") is True,
                "manual_backfill_status": str(manual_backfill_verification.get("status") or ""),
            },
            "manual_backfill_fulfillment": {
                "path": str(manual_backfill_fulfillment_path),
                "source": fulfillment_source,
                "hash_field": "p0b_google_manual_backfill_fulfillment_hash",
                "hash": str(manual_backfill_fulfillment.get("p0b_google_manual_backfill_fulfillment_hash") or ""),
                "verifier_status": fulfillment_verifier.get("status", ""),
                "hash_valid": fulfillment_verifier.get("hash_valid") is True,
            },
            "external_dependency_clearance": {
                "path": str(external_dependency_clearance_path),
                "source": clearance_source,
                "hash_field": "clearance_execution_hash",
                "hash": str(external_dependency_clearance.get("clearance_execution_hash") or ""),
                "verifier_status": str(_as_dict(external_dependency_clearance.get("handoff_verification")).get("status") or ""),
                "hash_valid": _as_dict(external_dependency_clearance.get("handoff_verification")).get("hash_valid")
                is True,
            },
        },
        "p0b_google_manual_backfill_request_verifier": request_verifier,
        "p0b_google_manual_backfill_verification_verifier": verification_verifier,
        "p0b_google_manual_backfill_fulfillment_verifier": fulfillment_verifier,
        "summary": {
            "required_count": len(required_items),
            "fulfilled_required_count": len(fulfilled_required),
            "missing_required_count": len(missing_required),
            "missing_required": missing_required,
            "presence_mismatch_count": len(presence_mismatches),
            "presence_mismatches": presence_mismatches,
            "owner_counts": _owner_counts(items),
            "missing_required_by_owner": _missing_by_owner(items),
            "manual_backfill_fulfilled": manual_backfill_fulfilled,
            "manual_backfill_fulfillment_ready": manual_backfill_fulfillment.get("manual_backfill_fulfillment_ready")
            is True,
            "manual_backfill_request_ready": request_ok,
            "manual_backfill_handoff_ready": manual_backfill_request.get("manual_backfill_handoff_ready") is True,
            "manual_backfill_verification_ready": verification_ok,
            "manual_backfill_verification_status": str(manual_backfill_verification.get("status") or ""),
            "manual_backfill_verification_hash": str(manual_backfill_verification.get("verification_hash") or ""),
            "manual_backfill_ready": fulfillment_summary.get("manual_backfill_ready") is True,
            "manual_backfill_coverage_complete": fulfillment_summary.get("manual_backfill_coverage_complete") is True,
            "manual_backfill_content_complete": fulfillment_summary.get("manual_backfill_content_complete") is True,
            "expected_record_count": _int(fulfillment_summary.get("expected_record_count")),
            "record_count": _int(fulfillment_summary.get("record_count")),
            "expected_prompt_city_count": _int(fulfillment_summary.get("expected_prompt_city_count")),
            "covered_prompt_city_count": _int(fulfillment_summary.get("covered_prompt_city_count")),
            "expected_sample_size": _int(fulfillment_summary.get("expected_sample_size")),
            "verification_expected_sample_size": _int(fulfillment_summary.get("verification_expected_sample_size")),
            "missing_prompt_city_sample_count": _int(fulfillment_summary.get("missing_prompt_city_sample_count")),
            "duplicate_prompt_city_sample_count": _int(fulfillment_summary.get("duplicate_prompt_city_sample_count")),
            "unexpected_prompt_city_record_count": _int(fulfillment_summary.get("unexpected_prompt_city_record_count")),
            "missing_answer_line_count": _int(fulfillment_summary.get("missing_answer_line_count")),
            "missing_citation_line_count": _int(fulfillment_summary.get("missing_citation_line_count")),
            "missing_asset_line_count": _int(fulfillment_summary.get("missing_asset_line_count")),
            "verification_error_count": len(verification_errors),
            "verification_errors": verification_errors,
            "verification_next_action": str(fulfillment_summary.get("verification_next_action") or ""),
            "file_sha256_present": bool(manual_backfill_verification.get("file_sha256")),
            "verification_hash_present": bool(manual_backfill_verification.get("verification_hash")),
            "content_redacted": fulfillment_summary.get("content_redacted") is True,
            "google_main_scoring_allowed": manual_backfill_fulfillment.get("google_main_scoring_allowed") is True,
            "blocked_by_prerequisite_step": blocked_by_prerequisite,
            "prerequisite_step_id": PREREQUISITE_STEP_ID,
            "prerequisite_step_ready": prerequisite_step.get("ready") is True,
            "current_global_clearance_step_id": str(external_dependency_clearance.get("current_step_id") or ""),
            "target_clearance_step_id": STEP_ID,
            "target_clearance_step_can_start": clearance_step_can_start,
            "target_clearance_step_ready": clearance_step_ready,
            "next_action": (
                "clear_p0b_google_environment_first"
                if blocked_by_prerequisite
                else (
                    "continue_external_dependency_clearance"
                    if manual_backfill_fulfilled
                    else str(fulfillment_summary.get("next_action") or "complete_manual_backfill_jsonl")
                )
            ),
            "next_command": (
                "make au-p0b-google-environment-clearance"
                if blocked_by_prerequisite
                else str(fulfillment_summary.get("next_command") or "make verify-au-p0b-google-manual-backfill")
            ),
            "strict_gate_command": str(fulfillment_summary.get("strict_gate_command") or ""),
            "request_strict_gate_command": str(fulfillment_summary.get("request_strict_gate_command") or ""),
            "operator_step_count": len(operator_steps),
            "post_update_validation_command_count": len(validation_sequence),
            "raw_answer_values_allowed": False,
            "raw_citation_values_allowed": False,
            "raw_asset_urls_allowed": False,
            "manual_jsonl_raw_path_allowed": False,
        },
        "manual_backfill_clearance_items": items,
        "operator_steps": operator_steps,
        "post_update_validation_sequence": validation_sequence,
        "runtime_endpoints": {
            "p0b_google_manual_backfill_clearance": "GET /v1/p0b-google-manual-backfill-clearance/au",
            "p0b_google_manual_backfill_request": "GET /v1/p0b-google-manual-backfill-request/au",
            "p0b_google_manual_backfill_fulfillment": "GET /v1/p0b-google-manual-backfill-fulfillment/au",
            "p0b_google_execution_checklist": "GET /v1/p0b-google-execution-checklist/au",
            "p0b_google_environment_clearance": "GET /v1/p0b-google-environment-clearance/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
            "delivery_progress": "GET /v1/delivery-progress/au",
        },
        "hard_gate_commands": _unique_strings(
            [
                "make au-p0b-google-manual-backfill-clearance",
                "make verify-au-p0b-google-manual-backfill-clearance",
                "make au-p0b-google-environment-clearance",
                "make verify-au-p0b-google-environment-clearance",
                "make au-p0b-google-manual-backfill-request",
                "make verify-au-p0b-google-manual-backfill-request",
                "make au-p0b-google-manual-template",
                "make verify-au-p0b-google-manual-backfill",
                "make au-p0b-google-manual-backfill-fulfillment",
                "make verify-au-p0b-google-manual-backfill-fulfillment",
                str(fulfillment_summary.get("request_strict_gate_command") or ""),
                str(fulfillment_summary.get("strict_gate_command") or ""),
                "PYTHONPATH=packages/geno_core:apps/api python3 "
                "scripts/verify_au_p0b_google_manual_backfill_clearance.py "
                "${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-clearance-latest.json} "
                "--require-cleared",
            ]
        ),
        "redaction_policy": {
            "raw_answer_values_allowed": False,
            "raw_citation_values_allowed": False,
            "raw_asset_urls_allowed": False,
            "manual_jsonl_path_redacted": True,
            "manual_jsonl_raw_path_allowed": False,
            "manual_records_reference_counts_hashes_and_error_codes_only": True,
            "forbidden_exact_manual_field_count": 15,
            "recorded_fields": [
                "key",
                "category",
                "required",
                "fulfilled",
                "expected_value",
                "actual_value",
                "source_request_field",
                "source_verification_field",
                "blocking_reasons",
                "file_sha256",
                "verification_hash",
            ],
        },
    }
    payload["p0b_google_manual_backfill_clearance_hash"] = compute_p0b_google_manual_backfill_clearance_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google manual backfill clearance JSON")
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
        "--manual-backfill-fulfillment-path",
        default=os.environ.get(
            "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_OUTPUT_PATH",
            DEFAULT_MANUAL_BACKFILL_FULFILLMENT_PATH,
        ),
        help="Path to the AU P0b Google manual backfill fulfillment JSON.",
    )
    parser.add_argument(
        "--external-dependency-clearance-path",
        default=os.environ.get(
            "GENO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH",
            DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH,
        ),
        help="Path to the AU external dependency clearance JSON.",
    )
    parser.add_argument(
        "--manual-jsonl-path",
        default=os.environ.get("MANUAL_BACKFILL_PATH", DEFAULT_MANUAL_BACKFILL_INPUT_PATH),
        help="Path to the manual JSONL if the verification artifact must be generated in memory.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_CLEARANCE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0b Google manual backfill clearance JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0b_google_manual_backfill_clearance(
        manual_backfill_request_path=Path(args.manual_backfill_request_path),
        manual_backfill_verification_path=Path(args.manual_backfill_verification_path),
        manual_backfill_fulfillment_path=Path(args.manual_backfill_fulfillment_path),
        external_dependency_clearance_path=Path(args.external_dependency_clearance_path),
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
