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

from scripts.build_au_p0b_google_execution_checklist import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH,
    build_au_p0b_google_execution_checklist,
)
from scripts.build_au_p0b_google_phase_execution_fulfillment import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_PHASE_EXECUTION_FULFILLMENT_PATH,
    PHASE_ORDER,
    build_au_p0b_google_phase_execution_fulfillment,
)
from scripts.build_au_p0b_google_phase_execution_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_PHASE_EXECUTION_REQUEST_PATH,
    build_au_p0b_google_phase_execution_request_packet,
)
from scripts.run_au_external_dependency_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH,
    run_au_external_dependency_clearance,
)
from scripts.verify_au_p0b_google_execution_checklist import (  # noqa: E402
    verify_au_p0b_google_execution_checklist,
)
from scripts.verify_au_p0b_google_phase_execution_fulfillment import (  # noqa: E402
    verify_au_p0b_google_phase_execution_fulfillment,
)
from scripts.verify_au_p0b_google_phase_execution_request_packet import (  # noqa: E402
    verify_au_p0b_google_phase_execution_request_packet,
)


CLEARANCE_VERSION = "au_p0b_google_phase_execution_clearance_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-phase-execution-clearance-latest.json"
STEP_ID = "p0b_google_phase_execution"
PREREQUISITE_STEP_ID = "p0b_google_manual_backfill"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0b_google_phase_execution_clearance_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("p0b_google_phase_execution_clearance_hash", None)
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


def _load_or_build_checklist(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    checklist = build_au_p0b_google_execution_checklist(output_path=path, generated_at=generated_at)
    return checklist, {**source, "source": "generated_in_memory"}


def _load_or_build_request(
    path: Path,
    *,
    checklist_path: Path,
    checklist: dict[str, Any],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    request = build_au_p0b_google_phase_execution_request_packet(
        p0b_google_execution_checklist_path=checklist_path,
        p0b_google_execution_checklist=checklist,
        output_path=path,
        generated_at=generated_at,
    )
    return request, {**source, "source": "generated_in_memory"}


def _load_or_build_fulfillment(
    path: Path,
    *,
    request_path: Path,
    checklist_path: Path,
    request: dict[str, Any],
    checklist: dict[str, Any],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    fulfillment = build_au_p0b_google_phase_execution_fulfillment(
        phase_execution_request_path=request_path,
        p0b_google_execution_checklist_path=checklist_path,
        phase_execution_request=request,
        p0b_google_execution_checklist=checklist,
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


def _phase_items(phase_fulfillment: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for value in _as_list(phase_fulfillment.get("phase_fulfillment_items")):
        item = _as_dict(value)
        phase_id = str(item.get("phase_id") or "")
        items.append(
            {
                "key": str(item.get("key") or f"phase:{phase_id}"),
                "phase_id": phase_id,
                "title": str(item.get("title") or phase_id),
                "required": item.get("required") is True,
                "fulfilled": item.get("fulfilled") is True,
                "request_ready": item.get("request_ready") is True,
                "checklist_ready": item.get("checklist_ready") is True,
                "request_can_start": item.get("request_can_start") is True,
                "checklist_can_start": item.get("checklist_can_start") is True,
                "presence_mismatch": item.get("presence_mismatch") is True,
                "planned_runs": _int(item.get("planned_runs")),
                "command_ids": _strings(item.get("command_ids")),
                "commands": _strings(item.get("commands")),
                "artifact_keys": _strings(item.get("artifact_keys")),
                "evidence_outputs": _strings(item.get("evidence_outputs")),
                "owner_hint": str(item.get("owner_hint") or "google_spike_operator"),
                "source_request_field": str(item.get("source_request_field") or ""),
                "source_checklist_field": str(item.get("source_checklist_field") or ""),
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


def _blocking_reasons(items: list[dict[str, Any]]) -> list[str]:
    return sorted(
        dict.fromkeys(
            f"{item.get('phase_id')}:{reason}"
            for item in items
            for reason in _strings(item.get("blocking_reasons"))
        )
    )


def _phase_commands(items: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for item in items:
        commands.extend(_strings(item.get("commands")))
    return commands


def _evidence_outputs(items: list[dict[str, Any]]) -> list[str]:
    outputs: list[str] = []
    for item in items:
        outputs.extend(_strings(item.get("evidence_outputs")))
    return sorted(dict.fromkeys(outputs))


def _operator_steps(
    *,
    phase_fulfillment: dict[str, Any],
    external_clearance: dict[str, Any],
    blocked_by_prerequisite: bool,
) -> list[dict[str, Any]]:
    summary = _as_dict(phase_fulfillment.get("summary"))
    steps: list[dict[str, Any]] = [
        {
            "order": 1,
            "id": "clear_p0b_google_manual_backfill",
            "command": "make au-p0b-google-manual-backfill-clearance && make verify-au-p0b-google-manual-backfill-clearance",
            "purpose": "clear_prerequisite_p0b_google_manual_backfill_before_phase_execution",
            "external_call_risk": "none",
            "required_before_phase_execution": True,
            "blocked": blocked_by_prerequisite,
        },
        {
            "order": 2,
            "id": "refresh_phase_execution_request",
            "command": "make au-p0b-google-phase-execution-request",
            "purpose": "refresh_google_six_phase_request_packet",
            "external_call_risk": "none",
        },
        {
            "order": 3,
            "id": "refresh_execution_checklist",
            "command": "make au-p0b-google-execution-checklist",
            "purpose": "refresh_google_execution_checklist_before_phase_alignment",
            "external_call_risk": "none",
        },
        {
            "order": 4,
            "id": "refresh_phase_execution_fulfillment",
            "command": "make au-p0b-google-phase-execution-fulfillment",
            "purpose": "align_request_and_checklist_into_phase_fulfillment_artifact",
            "external_call_risk": "none",
        },
        {
            "order": 5,
            "id": "apply_current_phase_fix",
            "command": str(summary.get("next_command") or "make au-p0b-google-phase-execution-fulfillment"),
            "purpose": "apply_or_verify_current_unfulfilled_google_phase",
            "external_call_risk": "depends_on_phase_command",
            "next_action": str(summary.get("next_action") or ""),
            "next_phase": str(summary.get("next_phase") or ""),
        },
        {
            "order": 6,
            "id": "verify_phase_execution_fulfillment",
            "command": "make verify-au-p0b-google-phase-execution-fulfillment",
            "purpose": "prove_phase_execution_fulfillment_is_current_or_still_blocked",
            "external_call_risk": "none",
        },
        {
            "order": 7,
            "id": "run_strict_gate",
            "command": str(summary.get("strict_gate_command") or ""),
            "purpose": "require_google_phase_execution_fulfilled",
            "external_call_risk": "none",
        },
        {
            "order": 8,
            "id": "continue_clearance_sequence",
            "command": "then follow p0b_google_phase_execution recommended_sequence from external dependency clearance",
            "purpose": "continue_to_customer_report_handoff_after_phase_execution_clear",
            "external_call_risk": "depends_on_next_sequence_step",
        },
    ]
    if _strings(external_clearance.get("current_recommended_sequence")):
        steps[0]["current_global_clearance_sequence"] = _strings(external_clearance.get("current_recommended_sequence"))
    return steps


def _post_update_validation_sequence(
    *,
    phase_request: dict[str, Any],
    phase_fulfillment: dict[str, Any],
    phase_step: dict[str, Any],
) -> list[str]:
    summary = _as_dict(phase_fulfillment.get("summary"))
    commands = [
        "make au-p0b-google-manual-backfill-clearance",
        "make verify-au-p0b-google-manual-backfill-clearance",
        "make au-p0b-google-phase-execution-request",
        "make verify-au-p0b-google-phase-execution-request",
        "make au-p0b-google-execution-checklist",
        "make verify-au-p0b-google-execution-checklist",
        "make au-p0b-google-phase-execution-fulfillment",
        "make verify-au-p0b-google-phase-execution-fulfillment",
        str(summary.get("request_strict_gate_command") or ""),
        str(summary.get("scoring_strict_gate_command") or ""),
        str(summary.get("strict_gate_command") or ""),
    ]
    commands.extend(_strings(phase_request.get("phase_commands")))
    commands.extend(_strings(phase_request.get("verification_commands")))
    commands.extend(_strings(phase_fulfillment.get("verification_commands")))
    commands.extend(_strings(phase_fulfillment.get("hard_gate_commands")))
    commands.extend(_strings(phase_step.get("recommended_sequence")))
    return _unique_strings(commands)


def build_au_p0b_google_phase_execution_clearance(
    *,
    phase_execution_request_path: Path = Path(DEFAULT_PHASE_EXECUTION_REQUEST_PATH),
    p0b_google_execution_checklist_path: Path = Path(DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH),
    phase_execution_fulfillment_path: Path = Path(DEFAULT_PHASE_EXECUTION_FULFILLMENT_PATH),
    external_dependency_clearance_path: Path = Path(DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH),
    phase_execution_request: dict[str, Any] | None = None,
    p0b_google_execution_checklist: dict[str, Any] | None = None,
    phase_execution_fulfillment: dict[str, Any] | None = None,
    external_dependency_clearance: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if p0b_google_execution_checklist is None:
        p0b_google_execution_checklist, checklist_source = _load_or_build_checklist(
            p0b_google_execution_checklist_path,
            generated_at=generated_at,
        )
    else:
        checklist_source = {
            "path": str(p0b_google_execution_checklist_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if phase_execution_request is None:
        phase_execution_request, request_source = _load_or_build_request(
            phase_execution_request_path,
            checklist_path=p0b_google_execution_checklist_path,
            checklist=p0b_google_execution_checklist,
            generated_at=generated_at,
        )
    else:
        request_source = {
            "path": str(phase_execution_request_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if phase_execution_fulfillment is None:
        phase_execution_fulfillment, fulfillment_source = _load_or_build_fulfillment(
            phase_execution_fulfillment_path,
            request_path=phase_execution_request_path,
            checklist_path=p0b_google_execution_checklist_path,
            request=phase_execution_request,
            checklist=p0b_google_execution_checklist,
            generated_at=generated_at,
        )
    else:
        fulfillment_source = {
            "path": str(phase_execution_fulfillment_path),
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

    request_verifier = verify_au_p0b_google_phase_execution_request_packet(
        phase_execution_request,
        path=phase_execution_request_path,
    )
    checklist_verifier = verify_au_p0b_google_execution_checklist(
        p0b_google_execution_checklist,
        path=p0b_google_execution_checklist_path,
    )
    fulfillment_verifier = verify_au_p0b_google_phase_execution_fulfillment(
        phase_execution_fulfillment,
        path=phase_execution_fulfillment_path,
    )
    request_ok = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    checklist_ok = checklist_verifier.get("status") == "pass" and checklist_verifier.get("hash_valid") is True
    fulfillment_ok = fulfillment_verifier.get("status") == "pass" and fulfillment_verifier.get("hash_valid") is True
    clearance_ok = external_dependency_clearance.get("status") == "pass"
    packet_ready = request_ok and checklist_ok and fulfillment_ok and clearance_ok

    phase_step = _step_by_id(external_dependency_clearance, STEP_ID)
    prerequisite_step = _step_by_id(external_dependency_clearance, PREREQUISITE_STEP_ID)
    items = _phase_items(phase_execution_fulfillment)
    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True)
    presence_mismatches = sorted(str(item.get("key") or "") for item in items if item.get("presence_mismatch") is True)
    phase_execution_fulfilled = (
        bool(required_items) and len(fulfilled_required) == len(required_items) and not presence_mismatches
    )
    blocked_by_prerequisite = prerequisite_step.get("ready") is not True
    clearance_step_ready = phase_step.get("ready") is True
    clearance_step_can_start = phase_step.get("can_start") is True
    ready_for_next_clearance_step = phase_execution_fulfilled and not blocked_by_prerequisite
    phase_execution_clearance_ready = phase_execution_fulfilled and clearance_step_ready and not blocked_by_prerequisite
    operator_steps = _operator_steps(
        phase_fulfillment=phase_execution_fulfillment,
        external_clearance=external_dependency_clearance,
        blocked_by_prerequisite=blocked_by_prerequisite,
    )
    validation_sequence = _post_update_validation_sequence(
        phase_request=phase_execution_request,
        phase_fulfillment=phase_execution_fulfillment,
        phase_step=phase_step,
    )
    fulfillment_summary = _as_dict(phase_execution_fulfillment.get("summary"))
    blocking_reasons = _blocking_reasons(items)
    payload: dict[str, Any] = {
        "p0b_google_phase_execution_clearance_version": CLEARANCE_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if packet_ready else "fail",
        "phase_execution_clearance_packet_ready": packet_ready,
        "phase_execution_fulfilled": phase_execution_fulfilled,
        "phase_execution_clearance_ready": phase_execution_clearance_ready,
        "ready_for_next_clearance_step": ready_for_next_clearance_step,
        "blocked_by_prerequisite_step": blocked_by_prerequisite,
        "output_path": str(output_path) if output_path else "",
        "clearance_step": {
            "id": STEP_ID,
            "current_global_step_id": str(external_dependency_clearance.get("current_step_id") or ""),
            "current_global_step_is_prerequisite": external_dependency_clearance.get("current_step_id")
            == PREREQUISITE_STEP_ID,
            "step_recorded": bool(phase_step),
            "step_ready": clearance_step_ready,
            "step_can_start": clearance_step_can_start,
            "step_status": str(phase_step.get("status") or ""),
            "blocked_by": _strings(phase_step.get("blocked_by")),
            "would_execute": phase_step.get("would_execute") is True,
            "strict_gate_command": str(
                phase_step.get("strict_gate_command") or fulfillment_summary.get("strict_gate_command") or ""
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
            "phase_execution_request": {
                "path": str(phase_execution_request_path),
                "source": request_source,
                "hash_field": "p0b_google_phase_execution_request_packet_hash",
                "hash": str(phase_execution_request.get("p0b_google_phase_execution_request_packet_hash") or ""),
                "verifier_status": request_verifier.get("status", ""),
                "hash_valid": request_verifier.get("hash_valid") is True,
            },
            "p0b_google_execution_checklist": {
                "path": str(p0b_google_execution_checklist_path),
                "source": checklist_source,
                "hash_field": "google_execution_checklist_hash",
                "hash": str(p0b_google_execution_checklist.get("google_execution_checklist_hash") or ""),
                "verifier_status": checklist_verifier.get("status", ""),
                "hash_valid": checklist_verifier.get("hash_valid") is True,
            },
            "phase_execution_fulfillment": {
                "path": str(phase_execution_fulfillment_path),
                "source": fulfillment_source,
                "hash_field": "p0b_google_phase_execution_fulfillment_hash",
                "hash": str(phase_execution_fulfillment.get("p0b_google_phase_execution_fulfillment_hash") or ""),
                "verifier_status": fulfillment_verifier.get("status", ""),
                "hash_valid": fulfillment_verifier.get("hash_valid") is True,
            },
            "external_dependency_clearance": {
                "path": str(external_dependency_clearance_path),
                "source": clearance_source,
                "hash_field": "clearance_execution_hash",
                "hash": str(external_dependency_clearance.get("clearance_execution_hash") or ""),
                "status": str(external_dependency_clearance.get("status") or ""),
                "verifier_status": str(_as_dict(external_dependency_clearance.get("handoff_verification")).get("status") or ""),
                "hash_valid": _as_dict(external_dependency_clearance.get("handoff_verification")).get("hash_valid")
                is True,
            },
        },
        "p0b_google_phase_execution_request_verifier": request_verifier,
        "p0b_google_execution_checklist_verifier": checklist_verifier,
        "p0b_google_phase_execution_fulfillment_verifier": fulfillment_verifier,
        "summary": {
            "required_count": len(required_items),
            "fulfilled_required_count": len(fulfilled_required),
            "missing_required_count": len(missing_required),
            "missing_required": missing_required,
            "presence_mismatch_count": len(presence_mismatches),
            "presence_mismatches": presence_mismatches,
            "owner_counts": _owner_counts(items),
            "missing_required_by_owner": _missing_by_owner(items),
            "blocking_reason_count": len(blocking_reasons),
            "blocking_reasons": blocking_reasons,
            "phase_execution_fulfilled": phase_execution_fulfilled,
            "phase_execution_fulfillment_ready": phase_execution_fulfillment.get(
                "phase_execution_fulfillment_ready"
            )
            is True,
            "phase_execution_request_ready": request_ok,
            "execution_checklist_ready": checklist_ok,
            "source_checklist_hash_aligned": fulfillment_summary.get("source_checklist_hash_aligned") is True,
            "google_spike_phase_handoff_ready": phase_execution_fulfilled,
            "google_main_scoring_allowed": phase_execution_fulfillment.get("google_main_scoring_allowed") is True,
            "phase_count": len(items),
            "phase_order": PHASE_ORDER,
            "ready_phase_count": len(fulfilled_required),
            "blocked_phase_count": len(required_items) - len(fulfilled_required),
            "next_phase": str(fulfillment_summary.get("next_phase") or ""),
            "full_spike_planned_runs": _int(fulfillment_summary.get("full_spike_planned_runs")),
            "manual_expected_record_count": _int(fulfillment_summary.get("manual_expected_record_count")),
            "blocked_by_prerequisite_step": blocked_by_prerequisite,
            "prerequisite_step_id": PREREQUISITE_STEP_ID,
            "prerequisite_step_ready": prerequisite_step.get("ready") is True,
            "current_global_clearance_step_id": str(external_dependency_clearance.get("current_step_id") or ""),
            "target_clearance_step_id": STEP_ID,
            "target_clearance_step_can_start": clearance_step_can_start,
            "target_clearance_step_ready": clearance_step_ready,
            "phase_execution_clearance_ready": phase_execution_clearance_ready,
            "ready_for_next_clearance_step": ready_for_next_clearance_step,
            "next_action": (
                "clear_p0b_google_manual_backfill_first"
                if blocked_by_prerequisite
                else (
                    "continue_external_dependency_clearance"
                    if phase_execution_fulfilled
                    else str(fulfillment_summary.get("next_action") or "complete_google_phase_prerequisites")
                )
            ),
            "next_command": (
                "make au-p0b-google-manual-backfill-clearance"
                if blocked_by_prerequisite
                else str(
                    fulfillment_summary.get("next_command")
                    or "make au-p0b-google-phase-execution-fulfillment"
                )
            ),
            "strict_gate_command": str(fulfillment_summary.get("strict_gate_command") or ""),
            "request_strict_gate_command": str(fulfillment_summary.get("request_strict_gate_command") or ""),
            "scoring_strict_gate_command": str(fulfillment_summary.get("scoring_strict_gate_command") or ""),
            "operator_step_count": len(operator_steps),
            "post_update_validation_command_count": len(validation_sequence),
            "raw_secret_values_allowed": False,
            "raw_answer_values_allowed": False,
            "raw_citation_values_allowed": False,
            "raw_asset_urls_allowed": False,
            "raw_provider_response_allowed": False,
            "phase_entries_reference_command_ids_and_artifact_paths_only": True,
        },
        "phase_execution_clearance_items": items,
        "operator_steps": operator_steps,
        "post_update_validation_sequence": validation_sequence,
        "runtime_endpoints": {
            "p0b_google_phase_execution_clearance": "GET /v1/p0b-google-phase-execution-clearance/au",
            "p0b_google_phase_execution_fulfillment": "GET /v1/p0b-google-phase-execution-fulfillment/au",
            "p0b_google_phase_execution_request": "GET /v1/p0b-google-phase-execution-request/au",
            "p0b_google_execution_checklist": "GET /v1/p0b-google-execution-checklist/au",
            "p0b_google_manual_backfill_clearance": "GET /v1/p0b-google-manual-backfill-clearance/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
            "customer_handoff_readiness": "GET /v1/customer-handoff-readiness/au",
            "delivery_progress": "GET /v1/delivery-progress/au",
        },
        "hard_gate_commands": _unique_strings(
            [
                "make au-p0b-google-phase-execution-clearance",
                "make verify-au-p0b-google-phase-execution-clearance",
                "make au-p0b-google-manual-backfill-clearance",
                "make verify-au-p0b-google-manual-backfill-clearance",
                "make au-p0b-google-phase-execution-request",
                "make verify-au-p0b-google-phase-execution-request",
                "make au-p0b-google-execution-checklist",
                "make verify-au-p0b-google-execution-checklist",
                "make au-p0b-google-phase-execution-fulfillment",
                "make verify-au-p0b-google-phase-execution-fulfillment",
                str(fulfillment_summary.get("request_strict_gate_command") or ""),
                str(fulfillment_summary.get("scoring_strict_gate_command") or ""),
                str(fulfillment_summary.get("strict_gate_command") or ""),
                "PYTHONPATH=packages/geo_core:apps/api python3 "
                "scripts/verify_au_p0b_google_phase_execution_clearance.py "
                "${GEO_AU_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-phase-execution-clearance-latest.json} "
                "--require-cleared",
            ]
        ),
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "raw_answer_values_allowed": False,
            "raw_citation_values_allowed": False,
            "raw_asset_urls_allowed": False,
            "raw_provider_response_allowed": False,
            "phase_entries_reference_command_ids_and_artifact_paths_only": True,
            "phase_records_reference_counts_hashes_commands_and_artifact_paths_only": True,
            "forbidden_exact_phase_payload_field_count": 13,
            "recorded_fields": [
                "key",
                "phase_id",
                "required",
                "fulfilled",
                "request_ready",
                "checklist_ready",
                "request_can_start",
                "checklist_can_start",
                "planned_runs",
                "command_ids",
                "artifact_keys",
                "evidence_outputs",
                "blocking_reasons",
            ],
        },
    }
    payload["p0b_google_phase_execution_clearance_hash"] = compute_p0b_google_phase_execution_clearance_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google phase execution clearance JSON")
    parser.add_argument(
        "--phase-execution-request-path",
        default=os.environ.get(
            "GEO_AU_P0B_GOOGLE_PHASE_EXECUTION_REQUEST_OUTPUT_PATH",
            DEFAULT_PHASE_EXECUTION_REQUEST_PATH,
        ),
        help="Path to the AU P0b Google phase execution request packet JSON.",
    )
    parser.add_argument(
        "--p0b-google-execution-checklist-path",
        default=os.environ.get(
            "GEO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH",
            DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH,
        ),
        help="Path to the AU P0b Google execution checklist JSON.",
    )
    parser.add_argument(
        "--phase-execution-fulfillment-path",
        default=os.environ.get(
            "GEO_AU_P0B_GOOGLE_PHASE_EXECUTION_FULFILLMENT_OUTPUT_PATH",
            DEFAULT_PHASE_EXECUTION_FULFILLMENT_PATH,
        ),
        help="Path to the AU P0b Google phase execution fulfillment JSON.",
    )
    parser.add_argument(
        "--external-dependency-clearance-path",
        default=os.environ.get(
            "GEO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH",
            DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH,
        ),
        help="Path to the AU external dependency clearance JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0b Google phase execution clearance JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0b_google_phase_execution_clearance(
        phase_execution_request_path=Path(args.phase_execution_request_path),
        p0b_google_execution_checklist_path=Path(args.p0b_google_execution_checklist_path),
        phase_execution_fulfillment_path=Path(args.phase_execution_fulfillment_path),
        external_dependency_clearance_path=Path(args.external_dependency_clearance_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
