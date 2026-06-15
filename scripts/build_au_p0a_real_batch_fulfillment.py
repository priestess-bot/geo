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
from scripts.build_au_p0a_real_batch_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_REAL_BATCH_REQUEST_PATH,
    build_au_p0a_real_batch_request_packet,
)
from scripts.verify_au_p0a_execution_checklist import verify_au_p0a_execution_checklist  # noqa: E402
from scripts.verify_au_p0a_real_batch_request_packet import verify_au_p0a_real_batch_request_packet  # noqa: E402


FULFILLMENT_VERSION = "au_p0a_real_batch_fulfillment_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json"

PHASE_ORDER = ["preflight", "small_batch", "full_batch"]
PHASE_OWNER_HINTS = {
    "preflight": "p0a_provider_operator",
    "small_batch": "p0a_batch_operator",
    "full_batch": "p0a_batch_operator",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0a_real_batch_fulfillment_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("p0a_real_batch_fulfillment_hash", None)
    return hashlib.sha256(_stable_bytes(payload_for_hash)).hexdigest()


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


def _phase_by_id(phases: object) -> dict[str, dict[str, Any]]:
    return {str(_as_dict(phase).get("id") or ""): _as_dict(phase) for phase in _as_list(phases)}


def _command_shells(phase: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    for command in _as_list(phase.get("commands")):
        command_dict = _as_dict(command)
        shell = str(command_dict.get("shell") or "").strip()
        if shell:
            commands.append(shell)
    return commands or _strings(phase.get("commands"))


def _blocking_reasons(*parts: object) -> list[str]:
    reasons: list[str] = []
    for part in parts:
        reasons.extend(_strings(part))
    return sorted(dict.fromkeys(reasons))


def _phase_item(request_phase: dict[str, Any], checklist_phase: dict[str, Any], phase_id: str) -> dict[str, Any]:
    request_ready = request_phase.get("ready") is True
    checklist_ready = checklist_phase.get("ready") is True
    request_can_start = request_phase.get("can_start") is True
    checklist_can_start = checklist_phase.get("can_start") is True
    ready_mismatch = request_ready != checklist_ready
    can_start_mismatch = request_can_start != checklist_can_start
    fulfilled = request_ready and checklist_ready and not ready_mismatch and not can_start_mismatch
    blocking_reasons = _blocking_reasons(
        request_phase.get("blocking_reasons"),
        checklist_phase.get("blocking_reasons"),
    )
    if not request_phase:
        blocking_reasons.append("phase_request_missing")
    if not checklist_phase:
        blocking_reasons.append("execution_checklist_phase_missing")
    if not request_ready:
        blocking_reasons.append("real_batch_request_phase_not_ready")
    if not checklist_ready:
        blocking_reasons.append("execution_checklist_phase_not_ready")
    if ready_mismatch:
        blocking_reasons.append("real_batch_request_checklist_ready_mismatch")
    if can_start_mismatch:
        blocking_reasons.append("real_batch_request_checklist_can_start_mismatch")
    blocking_reasons = sorted(dict.fromkeys(blocking_reasons))
    return {
        "key": f"phase:{phase_id}",
        "phase_id": phase_id,
        "title": str(request_phase.get("title") or checklist_phase.get("title") or phase_id),
        "required": True,
        "fulfilled": fulfilled,
        "request_ready": request_ready,
        "checklist_ready": checklist_ready,
        "request_can_start": request_can_start,
        "checklist_can_start": checklist_can_start,
        "presence_mismatch": ready_mismatch or can_start_mismatch,
        "planned_runs": _int(request_phase.get("planned_runs") or checklist_phase.get("planned_runs")),
        "command_ids": _strings(request_phase.get("command_ids") or checklist_phase.get("command_ids")),
        "commands": _strings(request_phase.get("commands")) or _command_shells(checklist_phase),
        "artifact_keys": _strings(request_phase.get("artifact_keys") or checklist_phase.get("artifact_keys")),
        "prerequisite_gate_ids": _strings(
            request_phase.get("prerequisite_gate_ids") or checklist_phase.get("prerequisite_gate_ids")
        ),
        "evidence_outputs": _strings(request_phase.get("evidence_outputs") or checklist_phase.get("evidence_outputs")),
        "owner_hint": PHASE_OWNER_HINTS.get(phase_id, "p0a_batch_operator"),
        "source_request_field": f"phase_requests[{phase_id}]",
        "source_checklist_field": f"real_batch_phase_handoff.phases[{phase_id}]",
        "blocking_reasons": blocking_reasons,
    }


def _fulfillment_items(request: dict[str, Any], checklist: dict[str, Any]) -> list[dict[str, Any]]:
    request_phases = _phase_by_id(request.get("phase_requests"))
    checklist_phases = _phase_by_id(_as_dict(checklist.get("real_batch_phase_handoff")).get("phases"))
    return [_phase_item(request_phases.get(phase_id, {}), checklist_phases.get(phase_id, {}), phase_id) for phase_id in PHASE_ORDER]


def _missing_by_owner(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for item in items:
        if item.get("required") is True and item.get("fulfilled") is not True:
            owner = str(item.get("owner_hint") or "unknown")
            owners.setdefault(owner, []).append(str(item.get("key") or ""))
    return {owner: sorted(keys) for owner, keys in sorted(owners.items())}


def _owner_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        owner = str(item.get("owner_hint") or "unknown")
        counts[owner] = counts.get(owner, 0) + 1
    return dict(sorted(counts.items()))


def _next_phase(items: list[dict[str, Any]]) -> str:
    for item in items:
        if item.get("fulfilled") is not True:
            return str(item.get("phase_id") or "")
    return "complete"


def _next_command(items: list[dict[str, Any]]) -> str:
    for item in items:
        if item.get("fulfilled") is not True:
            commands = _strings(item.get("commands"))
            return commands[0] if commands else "make au-p0a-real-batch-fulfillment"
    return "make verify-au-p0a-real-batch-fulfillment"


def _next_action(*, missing_required: list[str], mismatches: list[str], checklist_ready: bool) -> str:
    if missing_required:
        return "complete_p0a_real_batch_prerequisites"
    if mismatches:
        return "refresh_p0a_real_batch_request"
    if not checklist_ready:
        return "refresh_p0a_execution_checklist"
    return "run_p0a_real_batch_strict_gate"


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


def build_au_p0a_real_batch_fulfillment(
    *,
    real_batch_request_path: Path = Path(DEFAULT_REAL_BATCH_REQUEST_PATH),
    p0a_execution_checklist_path: Path = Path(DEFAULT_P0A_EXECUTION_CHECKLIST_PATH),
    real_batch_request: dict[str, Any] | None = None,
    p0a_execution_checklist: dict[str, Any] | None = None,
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
        request_source = {
            "path": str(real_batch_request_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    request_verifier = verify_au_p0a_real_batch_request_packet(real_batch_request, path=real_batch_request_path)
    checklist_verifier = verify_au_p0a_execution_checklist(p0a_execution_checklist, path=p0a_execution_checklist_path)
    request_ready = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    checklist_ready = checklist_verifier.get("status") == "pass" and checklist_verifier.get("hash_valid") is True
    request_source_checklist_hash = str(
        _as_dict(real_batch_request.get("source_p0a_execution_checklist")).get("p0a_execution_checklist_hash") or ""
    )
    current_checklist_hash = str(p0a_execution_checklist.get("p0a_execution_checklist_hash") or "")
    source_checklist_hash_aligned = bool(request_source_checklist_hash) and request_source_checklist_hash == current_checklist_hash
    fulfillment_ready = request_ready and checklist_ready and source_checklist_hash_aligned
    items = _fulfillment_items(real_batch_request, p0a_execution_checklist)
    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True)
    mismatches = sorted(str(item.get("key") or "") for item in items if item.get("presence_mismatch") is True)
    real_batches_fulfilled = bool(required_items) and len(fulfilled_required) == len(required_items) and not mismatches
    request_summary = _as_dict(real_batch_request.get("summary"))
    checklist_handoff = _as_dict(p0a_execution_checklist.get("real_batch_phase_handoff"))
    checklist_summary = _as_dict(p0a_execution_checklist.get("summary"))
    blocking_reasons = sorted(
        dict.fromkeys(
            f"{item.get('phase_id')}:{reason}"
            for item in items
            for reason in _strings(item.get("blocking_reasons"))
        )
    )
    phase_commands = _phase_commands(items)
    evidence_outputs = _evidence_outputs(items)
    total_planned_runs = _int(request_summary.get("total_planned_runs") or checklist_handoff.get("total_planned_runs"))
    real_batch_execution_plan_ready = (
        fulfillment_ready
        and len(items) == len(PHASE_ORDER)
        and total_planned_runs == sum(_int(item.get("planned_runs")) for item in items)
        and bool(phase_commands)
        and bool(evidence_outputs)
    )
    strict_gate_command = (
        "PYTHONPATH=packages/geno_core:apps/api python3 "
        "scripts/verify_au_p0a_real_batch_fulfillment.py "
        "${GENO_AU_P0A_REAL_BATCH_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json} "
        "--require-fulfilled"
    )
    request_strict_gate_command = (
        "PYTHONPATH=packages/geno_core:apps/api python3 "
        "scripts/verify_au_p0a_real_batch_request_packet.py "
        "${GENO_AU_P0A_REAL_BATCH_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-real-batch-request-latest.json} "
        "--require-real-batches-ready"
    )
    design_partner_strict_gate_command = (
        "PYTHONPATH=packages/geno_core:apps/api python3 "
        "scripts/verify_au_p0a_execution_checklist.py "
        "${GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-execution-checklist-latest.json} "
        "--require-design-partner-ready"
    )
    summary = {
        "real_batches_fulfilled": real_batches_fulfilled,
        "real_batch_request_ready": request_ready,
        "execution_checklist_ready": checklist_ready,
        "source_checklist_hash_aligned": source_checklist_hash_aligned,
        "real_batch_execution_plan_ready": real_batch_execution_plan_ready,
        "real_batch_phase_handoff_ready": real_batches_fulfilled,
        "ready_for_design_partner": (
            real_batches_fulfilled
            and real_batch_request.get("ready_for_design_partner") is True
            and p0a_execution_checklist.get("ready_for_design_partner") is True
        ),
        "phase_count": len(items),
        "phase_order": PHASE_ORDER,
        "ready_phase_count": len(fulfilled_required),
        "blocked_phase_count": len(required_items) - len(fulfilled_required),
        "next_phase": _next_phase(items),
        "total_planned_runs": total_planned_runs,
        "required_count": len(required_items),
        "fulfilled_required_count": len(fulfilled_required),
        "missing_required_count": len(missing_required),
        "missing_required": missing_required,
        "presence_mismatch_count": len(mismatches),
        "presence_mismatches": mismatches,
        "owner_counts": _owner_counts(items),
        "missing_required_by_owner": _missing_by_owner(items),
        "blocking_reason_count": len(blocking_reasons),
        "blocking_reasons": blocking_reasons,
        "checklist_remaining_blocker_count": _int(checklist_summary.get("remaining_blocker_count")),
        "checklist_next_action": str(p0a_execution_checklist.get("next_action") or ""),
        "command_count": len(phase_commands),
        "evidence_output_count": len(evidence_outputs),
        "next_action": _next_action(
            missing_required=missing_required,
            mismatches=mismatches,
            checklist_ready=checklist_ready,
        ),
        "next_command": _next_command(items),
        "strict_gate_command": strict_gate_command,
        "request_strict_gate_command": request_strict_gate_command,
        "design_partner_strict_gate_command": design_partner_strict_gate_command,
        "raw_secret_values_allowed": False,
        "phase_entries_reference_command_ids_and_artifact_paths_only": True,
    }

    payload: dict[str, Any] = {
        "p0a_real_batch_fulfillment_version": FULFILLMENT_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if fulfillment_ready else "fail",
        "real_batch_fulfillment_ready": fulfillment_ready,
        "real_batches_fulfilled": real_batches_fulfilled,
        "real_batch_phase_handoff_ready": real_batches_fulfilled,
        "ready_for_design_partner": summary["ready_for_design_partner"],
        "output_path": str(output_path) if output_path else "",
        "source_p0a_real_batch_request": {
            "path": str(real_batch_request_path),
            "source": request_source,
            "p0a_real_batch_request_packet_hash": str(real_batch_request.get("p0a_real_batch_request_packet_hash") or ""),
            "source_p0a_execution_checklist_hash": request_source_checklist_hash,
            "real_batch_request_packet_ready": real_batch_request.get("real_batch_request_packet_ready") is True,
            "real_batch_phase_handoff_ready": real_batch_request.get("real_batch_phase_handoff_ready") is True,
            "ready_for_design_partner": real_batch_request.get("ready_for_design_partner") is True,
        },
        "source_p0a_execution_checklist": {
            "path": str(p0a_execution_checklist_path),
            "source": checklist_source,
            "execution_checklist_version": str(p0a_execution_checklist.get("execution_checklist_version") or ""),
            "p0a_execution_checklist_hash": current_checklist_hash,
            "p0a_execution_checklist_ready": p0a_execution_checklist.get("p0a_execution_checklist_ready") is True,
            "real_batch_phase_handoff_ready": checklist_handoff.get("ready") is True,
            "ready_for_design_partner": p0a_execution_checklist.get("ready_for_design_partner") is True,
        },
        "p0a_real_batch_request_verifier": {
            "status": request_verifier.get("status", ""),
            "hash_valid": request_verifier.get("hash_valid") is True,
            "p0a_real_batch_request_packet_hash": str(request_verifier.get("p0a_real_batch_request_packet_hash") or ""),
            "real_batch_request_packet_ready": request_verifier.get("real_batch_request_packet_ready") is True,
            "real_batch_phase_handoff_ready": request_verifier.get("real_batch_phase_handoff_ready") is True,
            "errors": _strings(request_verifier.get("errors")),
            "next_phase": str(request_verifier.get("next_phase") or ""),
        },
        "p0a_execution_checklist_verifier": {
            "status": checklist_verifier.get("status", ""),
            "hash_valid": checklist_verifier.get("hash_valid") is True,
            "p0a_execution_checklist_hash": str(checklist_verifier.get("p0a_execution_checklist_hash") or ""),
            "p0a_execution_checklist_ready": checklist_verifier.get("p0a_execution_checklist_ready") is True,
            "real_batch_phase_handoff_ready": checklist_verifier.get("real_batch_phase_handoff_ready") is True,
            "ready_for_design_partner": checklist_verifier.get("ready_for_design_partner") is True,
            "errors": _strings(checklist_verifier.get("errors")),
            "next_action": str(checklist_verifier.get("next_action") or ""),
        },
        "summary": summary,
        "real_batch_fulfillment_items": items,
        "phase_commands": phase_commands,
        "verification_commands": [
            "make au-p0a-real-batch-request",
            "make verify-au-p0a-real-batch-request",
            "make au-p0a-execution-checklist",
            "make verify-au-p0a-execution-checklist",
            "make verify-au-p0a-real-batch-fulfillment",
        ],
        "evidence_outputs": evidence_outputs,
        "hard_gate_commands": [
            "make verify-au-p0a-real-batch-fulfillment",
            strict_gate_command,
            request_strict_gate_command,
            design_partner_strict_gate_command,
        ],
        "runtime_endpoints": {
            "p0a_real_batch_fulfillment": "GET /v1/p0a-real-batch-fulfillment/au",
            "p0a_real_batch_request": "GET /v1/p0a-real-batch-request/au",
            "p0a_execution_checklist": "GET /v1/p0a-execution-checklist/au",
            "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
        },
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "phase_entries_reference_command_ids_and_artifact_paths_only": True,
            "recorded_fields": [
                "phase_id",
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
    payload["p0a_real_batch_fulfillment_hash"] = compute_p0a_real_batch_fulfillment_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0a real batch fulfillment JSON")
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
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_REAL_BATCH_FULFILLMENT_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0a real batch fulfillment JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0a_real_batch_fulfillment(
        real_batch_request_path=Path(args.real_batch_request_path),
        p0a_execution_checklist_path=Path(args.p0a_execution_checklist_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
