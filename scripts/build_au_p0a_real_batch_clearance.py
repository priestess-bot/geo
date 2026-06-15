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

from scripts.build_au_p0a_execution_checklist import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_EXECUTION_CHECKLIST_PATH,
    build_au_p0a_execution_checklist,
)
from scripts.build_au_p0a_real_batch_fulfillment import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_REAL_BATCH_FULFILLMENT_PATH,
    build_au_p0a_real_batch_fulfillment,
)
from scripts.build_au_p0a_real_batch_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_REAL_BATCH_REQUEST_PATH,
    build_au_p0a_real_batch_request_packet,
)
from scripts.run_au_external_dependency_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH,
    run_au_external_dependency_clearance,
)
from scripts.verify_au_p0a_execution_checklist import verify_au_p0a_execution_checklist  # noqa: E402
from scripts.verify_au_p0a_real_batch_fulfillment import verify_au_p0a_real_batch_fulfillment  # noqa: E402
from scripts.verify_au_p0a_real_batch_request_packet import verify_au_p0a_real_batch_request_packet  # noqa: E402


CLEARANCE_VERSION = "au_p0a_real_batch_clearance_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-real-batch-clearance-latest.json"
STEP_ID = "p0a_real_batches"
PREREQUISITE_STEP_ID = "p0a_provider_credentials"
PHASE_ORDER = ["preflight", "small_batch", "full_batch"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0a_real_batch_clearance_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("p0a_real_batch_clearance_hash", None)
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
    checklist = build_au_p0a_execution_checklist(output_path=path, generated_at=generated_at)
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
    request = build_au_p0a_real_batch_request_packet(
        p0a_execution_checklist_path=checklist_path,
        p0a_execution_checklist=checklist,
        output_path=path,
        generated_at=generated_at,
    )
    return request, {**source, "source": "generated_in_memory"}


def _load_or_build_fulfillment(
    path: Path,
    *,
    real_batch_request_path: Path,
    real_batch_request: dict[str, Any],
    checklist_path: Path,
    checklist: dict[str, Any],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    fulfillment = build_au_p0a_real_batch_fulfillment(
        real_batch_request_path=real_batch_request_path,
        p0a_execution_checklist_path=checklist_path,
        real_batch_request=real_batch_request,
        p0a_execution_checklist=checklist,
        output_path=path,
        generated_at=generated_at,
    )
    return fulfillment, {**source, "source": "generated_in_memory"}


def _load_or_build_clearance(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
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


def _phase_items(real_batch_fulfillment: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in [_as_dict(value) for value in _as_list(real_batch_fulfillment.get("real_batch_fulfillment_items"))]:
        phase_id = str(item.get("phase_id") or "")
        items.append(
            {
                "key": str(item.get("key") or f"phase:{phase_id}"),
                "phase_id": phase_id,
                "title": str(item.get("title") or phase_id),
                "owner_hint": str(item.get("owner_hint") or "p0a_batch_operator"),
                "fulfilled": item.get("fulfilled") is True,
                "request_ready": item.get("request_ready") is True,
                "checklist_ready": item.get("checklist_ready") is True,
                "can_start": item.get("request_can_start") is True and item.get("checklist_can_start") is True,
                "planned_runs": int(item.get("planned_runs") or 0),
                "command_ids": _strings(item.get("command_ids")),
                "commands": _strings(item.get("commands")),
                "artifact_keys": _strings(item.get("artifact_keys")),
                "prerequisite_gate_ids": _strings(item.get("prerequisite_gate_ids")),
                "evidence_outputs": _strings(item.get("evidence_outputs")),
                "blocking_reasons": _strings(item.get("blocking_reasons")) or ["real_batch_phase_not_fulfilled"],
            }
        )
    return items


def _missing_by_owner(phase_items: list[dict[str, Any]]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for item in phase_items:
        if item.get("fulfilled") is not True:
            owner = str(item.get("owner_hint") or "unknown")
            owners.setdefault(owner, []).append(str(item.get("key") or ""))
    return {owner: sorted(keys) for owner, keys in sorted(owners.items())}


def _operator_steps(
    *,
    real_batch_fulfillment: dict[str, Any],
    external_clearance: dict[str, Any],
    blocked_by_prerequisite: bool,
) -> list[dict[str, Any]]:
    summary = _as_dict(real_batch_fulfillment.get("summary"))
    steps = [
        {
            "order": 1,
            "id": "clear_p0a_provider_credentials",
            "command": "make au-p0a-credential-clearance && make verify-au-p0a-credential-clearance",
            "purpose": "clear_prerequisite_provider_credentials_before_real_batch_execution",
            "external_call_risk": "none",
            "required_before_real_batches": True,
            "blocked": blocked_by_prerequisite,
        },
        {
            "order": 2,
            "id": "refresh_real_batch_request",
            "command": "make au-p0a-real-batch-request",
            "purpose": "refresh_preflight_small_full_batch_request_packet",
            "external_call_risk": "none",
        },
        {
            "order": 3,
            "id": "refresh_real_batch_fulfillment",
            "command": "make au-p0a-real-batch-fulfillment",
            "purpose": "align_real_batch_request_with_current_execution_checklist",
            "external_call_risk": "none",
        },
        {
            "order": 4,
            "id": "run_current_real_batch_phase",
            "command": str(summary.get("next_command") or "make api-preflight"),
            "purpose": "execute_current_unfulfilled_p0a_real_batch_phase",
            "external_call_risk": "provider_api_calls",
            "next_phase": str(summary.get("next_phase") or ""),
        },
        {
            "order": 5,
            "id": "verify_real_batch_fulfillment",
            "command": "make verify-au-p0a-real-batch-fulfillment",
            "purpose": "prove_preflight_small_full_batch_fulfillment_state",
            "external_call_risk": "none",
        },
        {
            "order": 6,
            "id": "run_strict_gate",
            "command": str(summary.get("strict_gate_command") or ""),
            "purpose": "require_all_p0a_real_batches_fulfilled",
            "external_call_risk": "none",
        },
        {
            "order": 7,
            "id": "continue_clearance_sequence",
            "command": "then follow p0a_real_batches recommended_sequence from external dependency clearance",
            "purpose": "continue_to_p0b_google_environment_after_real_batches_clear",
            "external_call_risk": "depends_on_next_sequence_step",
        },
    ]
    if _strings(external_clearance.get("current_recommended_sequence")):
        steps[0]["current_global_clearance_sequence"] = _strings(external_clearance.get("current_recommended_sequence"))
    return steps


def _post_update_validation_sequence(
    *,
    real_batch_request: dict[str, Any],
    real_batch_fulfillment: dict[str, Any],
    p0a_execution_checklist: dict[str, Any],
    batch_step: dict[str, Any],
) -> list[str]:
    commands = [
        "make au-p0a-credential-clearance",
        "make verify-au-p0a-credential-clearance",
        "make au-p0a-real-batch-request",
        "make verify-au-p0a-real-batch-request",
        "make au-p0a-real-batch-fulfillment",
        "make verify-au-p0a-real-batch-fulfillment",
        str(_as_dict(real_batch_fulfillment.get("summary")).get("strict_gate_command") or ""),
        str(_as_dict(real_batch_fulfillment.get("summary")).get("design_partner_strict_gate_command") or ""),
    ]
    commands.extend(_strings(real_batch_request.get("phase_commands")))
    commands.extend(_strings(real_batch_fulfillment.get("phase_commands")))
    commands.extend(_strings(p0a_execution_checklist.get("verification_commands")))
    commands.extend(_strings(batch_step.get("recommended_sequence")))
    return _unique_strings(commands)


def build_au_p0a_real_batch_clearance(
    *,
    real_batch_request_path: Path = Path(DEFAULT_REAL_BATCH_REQUEST_PATH),
    p0a_execution_checklist_path: Path = Path(DEFAULT_P0A_EXECUTION_CHECKLIST_PATH),
    real_batch_fulfillment_path: Path = Path(DEFAULT_REAL_BATCH_FULFILLMENT_PATH),
    external_dependency_clearance_path: Path = Path(DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH),
    real_batch_request: dict[str, Any] | None = None,
    p0a_execution_checklist: dict[str, Any] | None = None,
    real_batch_fulfillment: dict[str, Any] | None = None,
    external_dependency_clearance: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if p0a_execution_checklist is None:
        p0a_execution_checklist, checklist_source = _load_or_build_checklist(
            p0a_execution_checklist_path,
            generated_at=generated_at,
        )
    else:
        checklist_source = {
            "path": str(p0a_execution_checklist_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if real_batch_request is None:
        real_batch_request, request_source = _load_or_build_request(
            real_batch_request_path,
            checklist_path=p0a_execution_checklist_path,
            checklist=p0a_execution_checklist,
            generated_at=generated_at,
        )
    else:
        request_source = {"path": str(real_batch_request_path), "exists": True, "source": "provided_payload", "errors": []}

    if real_batch_fulfillment is None:
        real_batch_fulfillment, fulfillment_source = _load_or_build_fulfillment(
            real_batch_fulfillment_path,
            real_batch_request_path=real_batch_request_path,
            real_batch_request=real_batch_request,
            checklist_path=p0a_execution_checklist_path,
            checklist=p0a_execution_checklist,
            generated_at=generated_at,
        )
    else:
        fulfillment_source = {
            "path": str(real_batch_fulfillment_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if external_dependency_clearance is None:
        external_dependency_clearance, clearance_source = _load_or_build_clearance(
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

    request_verifier = verify_au_p0a_real_batch_request_packet(real_batch_request, path=real_batch_request_path)
    checklist_verifier = verify_au_p0a_execution_checklist(p0a_execution_checklist, path=p0a_execution_checklist_path)
    fulfillment_verifier = verify_au_p0a_real_batch_fulfillment(
        real_batch_fulfillment,
        path=real_batch_fulfillment_path,
    )
    request_ok = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    checklist_ok = checklist_verifier.get("status") == "pass" and checklist_verifier.get("hash_valid") is True
    fulfillment_ok = fulfillment_verifier.get("status") == "pass" and fulfillment_verifier.get("hash_valid") is True
    clearance_ok = external_dependency_clearance.get("status") == "pass"
    packet_ready = request_ok and checklist_ok and fulfillment_ok and clearance_ok

    batch_step = _step_by_id(external_dependency_clearance, STEP_ID)
    prerequisite_step = _step_by_id(external_dependency_clearance, PREREQUISITE_STEP_ID)
    phase_items = _phase_items(real_batch_fulfillment)
    missing_required = sorted(str(item.get("key") or "") for item in phase_items if item.get("fulfilled") is not True)
    blocked_by_prerequisite = prerequisite_step.get("ready") is not True
    real_batches_fulfilled = real_batch_fulfillment.get("real_batches_fulfilled") is True
    clearance_step_ready = batch_step.get("ready") is True
    clearance_step_can_start = batch_step.get("can_start") is True
    ready_for_next_clearance_step = real_batches_fulfilled and not blocked_by_prerequisite
    batch_clearance_ready = real_batches_fulfilled and clearance_step_ready and not blocked_by_prerequisite
    operator_steps = _operator_steps(
        real_batch_fulfillment=real_batch_fulfillment,
        external_clearance=external_dependency_clearance,
        blocked_by_prerequisite=blocked_by_prerequisite,
    )
    validation_sequence = _post_update_validation_sequence(
        real_batch_request=real_batch_request,
        real_batch_fulfillment=real_batch_fulfillment,
        p0a_execution_checklist=p0a_execution_checklist,
        batch_step=batch_step,
    )
    fulfillment_summary = _as_dict(real_batch_fulfillment.get("summary"))
    payload: dict[str, Any] = {
        "p0a_real_batch_clearance_version": CLEARANCE_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if packet_ready else "fail",
        "real_batch_clearance_packet_ready": packet_ready,
        "real_batches_fulfilled": real_batches_fulfilled,
        "real_batch_clearance_ready": batch_clearance_ready,
        "ready_for_next_clearance_step": ready_for_next_clearance_step,
        "blocked_by_prerequisite_step": blocked_by_prerequisite,
        "output_path": str(output_path) if output_path else "",
        "clearance_step": {
            "id": STEP_ID,
            "current_global_step_id": str(external_dependency_clearance.get("current_step_id") or ""),
            "current_global_step_is_prerequisite": external_dependency_clearance.get("current_step_id")
            == PREREQUISITE_STEP_ID,
            "step_recorded": bool(batch_step),
            "step_ready": clearance_step_ready,
            "step_can_start": clearance_step_can_start,
            "step_status": str(batch_step.get("status") or ""),
            "blocked_by": _strings(batch_step.get("blocked_by")),
            "would_execute": batch_step.get("would_execute") is True,
            "strict_gate_command": str(batch_step.get("strict_gate_command") or fulfillment_summary.get("strict_gate_command") or ""),
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
            "real_batch_request": {
                "path": str(real_batch_request_path),
                "source": request_source,
                "hash_field": "p0a_real_batch_request_packet_hash",
                "hash": str(real_batch_request.get("p0a_real_batch_request_packet_hash") or ""),
                "verifier_status": request_verifier.get("status", ""),
                "hash_valid": request_verifier.get("hash_valid") is True,
            },
            "p0a_execution_checklist": {
                "path": str(p0a_execution_checklist_path),
                "source": checklist_source,
                "hash_field": "p0a_execution_checklist_hash",
                "hash": str(p0a_execution_checklist.get("p0a_execution_checklist_hash") or ""),
                "verifier_status": checklist_verifier.get("status", ""),
                "hash_valid": checklist_verifier.get("hash_valid") is True,
            },
            "real_batch_fulfillment": {
                "path": str(real_batch_fulfillment_path),
                "source": fulfillment_source,
                "hash_field": "p0a_real_batch_fulfillment_hash",
                "hash": str(real_batch_fulfillment.get("p0a_real_batch_fulfillment_hash") or ""),
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
        "p0a_real_batch_request_verifier": request_verifier,
        "p0a_execution_checklist_verifier": checklist_verifier,
        "p0a_real_batch_fulfillment_verifier": fulfillment_verifier,
        "summary": {
            "phase_order": PHASE_ORDER,
            "phase_count": len(phase_items),
            "ready_phase_count": len([item for item in phase_items if item.get("fulfilled") is True]),
            "blocked_phase_count": len([item for item in phase_items if item.get("fulfilled") is not True]),
            "total_planned_runs": int(fulfillment_summary.get("total_planned_runs") or 0),
            "next_phase": str(fulfillment_summary.get("next_phase") or ""),
            "real_batches_fulfilled": real_batches_fulfilled,
            "real_batch_fulfillment_ready": real_batch_fulfillment.get("real_batch_fulfillment_ready") is True,
            "ready_for_design_partner": real_batch_fulfillment.get("ready_for_design_partner") is True,
            "blocked_by_prerequisite_step": blocked_by_prerequisite,
            "prerequisite_step_id": PREREQUISITE_STEP_ID,
            "prerequisite_step_ready": prerequisite_step.get("ready") is True,
            "current_global_clearance_step_id": str(external_dependency_clearance.get("current_step_id") or ""),
            "target_clearance_step_id": STEP_ID,
            "target_clearance_step_can_start": clearance_step_can_start,
            "target_clearance_step_ready": clearance_step_ready,
            "missing_required_count": len(missing_required),
            "missing_required": missing_required,
            "missing_required_by_owner": _missing_by_owner(phase_items),
            "blocking_reason_count": len(_strings(fulfillment_summary.get("blocking_reasons"))),
            "blocking_reasons": _strings(fulfillment_summary.get("blocking_reasons")),
            "next_action": (
                "clear_p0a_provider_credentials_first"
                if blocked_by_prerequisite
                else ("continue_external_dependency_clearance" if real_batches_fulfilled else "run_p0a_real_batch_phase")
            ),
            "next_command": (
                "make au-p0a-credential-clearance"
                if blocked_by_prerequisite
                else str(fulfillment_summary.get("next_command") or "make api-preflight")
            ),
            "strict_gate_command": str(fulfillment_summary.get("strict_gate_command") or ""),
            "design_partner_strict_gate_command": str(fulfillment_summary.get("design_partner_strict_gate_command") or ""),
            "operator_step_count": len(operator_steps),
            "post_update_validation_command_count": len(validation_sequence),
            "raw_secret_values_allowed": False,
            "provider_response_values_allowed": False,
        },
        "phase_clearance_items": phase_items,
        "operator_steps": operator_steps,
        "post_update_validation_sequence": validation_sequence,
        "runtime_endpoints": {
            "p0a_real_batch_clearance": "GET /v1/p0a-real-batch-clearance/au",
            "p0a_real_batch_request": "GET /v1/p0a-real-batch-request/au",
            "p0a_real_batch_fulfillment": "GET /v1/p0a-real-batch-fulfillment/au",
            "p0a_execution_checklist": "GET /v1/p0a-execution-checklist/au",
            "p0a_credential_clearance": "GET /v1/p0a-credential-clearance/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
            "delivery_progress": "GET /v1/delivery-progress/au",
        },
        "hard_gate_commands": _unique_strings(
            [
                "make au-p0a-real-batch-clearance",
                "make verify-au-p0a-real-batch-clearance",
                "make au-p0a-real-batch-request",
                "make verify-au-p0a-real-batch-request",
                "make au-p0a-real-batch-fulfillment",
                "make verify-au-p0a-real-batch-fulfillment",
                "make au-p0a-credential-clearance",
                "make verify-au-p0a-credential-clearance",
                str(fulfillment_summary.get("strict_gate_command") or ""),
                str(fulfillment_summary.get("design_partner_strict_gate_command") or ""),
                "PYTHONPATH=packages/geno_core:apps/api python3 "
                "scripts/verify_au_p0a_real_batch_clearance.py "
                "${GENO_AU_P0A_REAL_BATCH_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-real-batch-clearance-latest.json} "
                "--require-cleared",
            ]
        ),
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "provider_response_values_allowed": False,
            "phase_entries_reference_command_ids_and_artifact_paths_only": True,
            "forbidden_exact_secret_field_count": 8,
            "recorded_fields": [
                "phase_id",
                "fulfilled",
                "ready",
                "can_start",
                "planned_runs",
                "command_ids",
                "artifact_keys",
                "evidence_outputs",
                "blocking_reasons",
            ],
        },
    }
    payload["p0a_real_batch_clearance_hash"] = compute_p0a_real_batch_clearance_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0a real batch clearance JSON")
    parser.add_argument(
        "--real-batch-request-path",
        default=os.environ.get("GENO_AU_P0A_REAL_BATCH_REQUEST_OUTPUT_PATH", DEFAULT_REAL_BATCH_REQUEST_PATH),
        help="Path to the AU P0a real batch request packet JSON.",
    )
    parser.add_argument(
        "--p0a-execution-checklist-path",
        default=os.environ.get("GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH", DEFAULT_P0A_EXECUTION_CHECKLIST_PATH),
        help="Path to the AU P0a execution checklist JSON.",
    )
    parser.add_argument(
        "--real-batch-fulfillment-path",
        default=os.environ.get("GENO_AU_P0A_REAL_BATCH_FULFILLMENT_OUTPUT_PATH", DEFAULT_REAL_BATCH_FULFILLMENT_PATH),
        help="Path to the AU P0a real batch fulfillment JSON.",
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
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_REAL_BATCH_CLEARANCE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0a real batch clearance JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0a_real_batch_clearance(
        real_batch_request_path=Path(args.real_batch_request_path),
        p0a_execution_checklist_path=Path(args.p0a_execution_checklist_path),
        real_batch_fulfillment_path=Path(args.real_batch_fulfillment_path),
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
