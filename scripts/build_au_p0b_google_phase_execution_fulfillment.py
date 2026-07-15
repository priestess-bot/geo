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
from scripts.build_au_p0b_google_phase_execution_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_PHASE_EXECUTION_REQUEST_PATH,
    build_au_p0b_google_phase_execution_request_packet,
)
from scripts.verify_au_p0b_google_execution_checklist import (  # noqa: E402
    verify_au_p0b_google_execution_checklist,
)
from scripts.verify_au_p0b_google_phase_execution_request_packet import (  # noqa: E402
    verify_au_p0b_google_phase_execution_request_packet,
)


FULFILLMENT_VERSION = "au_p0b_google_phase_execution_fulfillment_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json"

PHASE_ORDER = [
    "environment",
    "browser_smoke",
    "manual_backfill",
    "health_check",
    "full_spike",
    "main_scoring",
]
PHASE_OWNER_HINTS = {
    "environment": "google_environment_operator",
    "browser_smoke": "google_browser_operator",
    "manual_backfill": "google_manual_backfill_operator",
    "health_check": "google_spike_operator",
    "full_spike": "google_spike_operator",
    "main_scoring": "google_scoring_operator",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0b_google_phase_execution_fulfillment_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("p0b_google_phase_execution_fulfillment_hash", None)
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
        blocking_reasons.append("phase_request_not_ready")
    if not checklist_ready:
        blocking_reasons.append("execution_checklist_phase_not_ready")
    if ready_mismatch:
        blocking_reasons.append("phase_request_checklist_ready_mismatch")
    if can_start_mismatch:
        blocking_reasons.append("phase_request_checklist_can_start_mismatch")
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
        "evidence_outputs": _strings(request_phase.get("evidence_outputs") or checklist_phase.get("evidence_outputs")),
        "owner_hint": PHASE_OWNER_HINTS.get(phase_id, "google_spike_operator"),
        "source_request_field": f"phase_requests[{phase_id}]",
        "source_checklist_field": f"google_spike_phase_handoff.phases[{phase_id}]",
        "blocking_reasons": blocking_reasons,
    }


def _fulfillment_items(request: dict[str, Any], checklist: dict[str, Any]) -> list[dict[str, Any]]:
    request_phases = _phase_by_id(request.get("phase_requests"))
    checklist_phases = _phase_by_id(_as_dict(checklist.get("google_spike_phase_handoff")).get("phases"))
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
            return commands[0] if commands else "make au-p0b-google-phase-execution-fulfillment"
    return "make verify-au-p0b-google-phase-execution-fulfillment"


def _next_action(*, missing_required: list[str], mismatches: list[str], checklist_ready: bool) -> str:
    if missing_required:
        return "complete_google_phase_prerequisites"
    if mismatches:
        return "refresh_p0b_google_phase_execution_request"
    if not checklist_ready:
        return "refresh_p0b_google_execution_checklist"
    return "run_p0b_google_phase_execution_strict_gate"


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


def build_au_p0b_google_phase_execution_fulfillment(
    *,
    phase_execution_request_path: Path = Path(DEFAULT_PHASE_EXECUTION_REQUEST_PATH),
    p0b_google_execution_checklist_path: Path = Path(DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH),
    phase_execution_request: dict[str, Any] | None = None,
    p0b_google_execution_checklist: dict[str, Any] | None = None,
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

    request_verifier = verify_au_p0b_google_phase_execution_request_packet(
        phase_execution_request,
        path=phase_execution_request_path,
    )
    checklist_verifier = verify_au_p0b_google_execution_checklist(
        p0b_google_execution_checklist,
        path=p0b_google_execution_checklist_path,
    )
    request_ready = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    checklist_ready = checklist_verifier.get("status") == "pass" and checklist_verifier.get("hash_valid") is True
    request_source_checklist_hash = str(
        _as_dict(phase_execution_request.get("source_p0b_google_execution_checklist")).get(
            "google_execution_checklist_hash"
        )
        or ""
    )
    current_checklist_hash = str(p0b_google_execution_checklist.get("google_execution_checklist_hash") or "")
    source_checklist_hash_aligned = bool(request_source_checklist_hash) and request_source_checklist_hash == current_checklist_hash
    fulfillment_ready = request_ready and checklist_ready and source_checklist_hash_aligned
    items = _fulfillment_items(phase_execution_request, p0b_google_execution_checklist)
    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True)
    mismatches = sorted(str(item.get("key") or "") for item in items if item.get("presence_mismatch") is True)
    phase_execution_fulfilled = bool(required_items) and len(fulfilled_required) == len(required_items) and not mismatches
    request_summary = _as_dict(phase_execution_request.get("summary"))
    checklist_handoff = _as_dict(p0b_google_execution_checklist.get("google_spike_phase_handoff"))
    checklist_summary = _as_dict(p0b_google_execution_checklist.get("summary"))
    blocking_reasons = sorted(
        dict.fromkeys(
            f"{item.get('phase_id')}:{reason}"
            for item in items
            for reason in _strings(item.get("blocking_reasons"))
        )
    )
    strict_gate_command = (
        "PYTHONPATH=packages/geo_core:apps/api python3 "
        "scripts/verify_au_p0b_google_phase_execution_fulfillment.py "
        "${GEO_AU_P0B_GOOGLE_PHASE_EXECUTION_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json} "
        "--require-fulfilled"
    )
    request_strict_gate_command = (
        "PYTHONPATH=packages/geo_core:apps/api python3 "
        "scripts/verify_au_p0b_google_phase_execution_request_packet.py "
        "${GEO_AU_P0B_GOOGLE_PHASE_EXECUTION_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-phase-execution-request-latest.json} "
        "--require-google-phases-ready"
    )
    scoring_strict_gate_command = (
        "PYTHONPATH=packages/geo_core:apps/api python3 "
        "scripts/verify_au_p0b_google_execution_checklist.py "
        "${GEO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json} "
        "--require-google-main-scoring-ready"
    )
    summary = {
        "phase_execution_fulfilled": phase_execution_fulfilled,
        "phase_execution_request_ready": request_ready,
        "execution_checklist_ready": checklist_ready,
        "source_checklist_hash_aligned": source_checklist_hash_aligned,
        "google_spike_phase_handoff_ready": phase_execution_fulfilled,
        "google_main_scoring_allowed": (
            phase_execution_fulfilled
            and phase_execution_request.get("google_main_scoring_allowed") is True
            and p0b_google_execution_checklist.get("google_main_scoring_allowed") is True
        ),
        "phase_count": len(items),
        "phase_order": PHASE_ORDER,
        "ready_phase_count": len(fulfilled_required),
        "blocked_phase_count": len(required_items) - len(fulfilled_required),
        "next_phase": _next_phase(items),
        "full_spike_planned_runs": _int(
            request_summary.get("full_spike_planned_runs") or checklist_handoff.get("full_spike_planned_runs")
        ),
        "manual_expected_record_count": _int(
            request_summary.get("manual_expected_record_count")
            or checklist_handoff.get("manual_expected_record_count")
        ),
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
        "checklist_next_action": str(p0b_google_execution_checklist.get("next_action") or ""),
        "command_count": len(_phase_commands(items)),
        "evidence_output_count": len(_evidence_outputs(items)),
        "next_action": _next_action(
            missing_required=missing_required,
            mismatches=mismatches,
            checklist_ready=checklist_ready,
        ),
        "next_command": _next_command(items),
        "strict_gate_command": strict_gate_command,
        "request_strict_gate_command": request_strict_gate_command,
        "scoring_strict_gate_command": scoring_strict_gate_command,
        "raw_secret_values_allowed": False,
        "raw_answer_values_allowed": False,
        "raw_citation_values_allowed": False,
        "raw_asset_urls_allowed": False,
        "phase_entries_reference_command_ids_and_artifact_paths_only": True,
    }

    payload: dict[str, Any] = {
        "p0b_google_phase_execution_fulfillment_version": FULFILLMENT_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if fulfillment_ready else "fail",
        "phase_execution_fulfillment_ready": fulfillment_ready,
        "phase_execution_fulfilled": phase_execution_fulfilled,
        "google_spike_phase_handoff_ready": phase_execution_fulfilled,
        "google_main_scoring_allowed": summary["google_main_scoring_allowed"],
        "output_path": str(output_path) if output_path else "",
        "source_p0b_google_phase_execution_request": {
            "path": str(phase_execution_request_path),
            "source": request_source,
            "p0b_google_phase_execution_request_packet_hash": str(
                phase_execution_request.get("p0b_google_phase_execution_request_packet_hash") or ""
            ),
            "source_google_execution_checklist_hash": request_source_checklist_hash,
            "phase_execution_request_packet_ready": phase_execution_request.get(
                "phase_execution_request_packet_ready"
            )
            is True,
            "google_spike_phase_handoff_ready": phase_execution_request.get(
                "google_spike_phase_handoff_ready"
            )
            is True,
            "google_main_scoring_allowed": phase_execution_request.get("google_main_scoring_allowed") is True,
        },
        "source_p0b_google_execution_checklist": {
            "path": str(p0b_google_execution_checklist_path),
            "source": checklist_source,
            "execution_checklist_version": str(
                p0b_google_execution_checklist.get("execution_checklist_version") or ""
            ),
            "google_execution_checklist_hash": str(
                p0b_google_execution_checklist.get("google_execution_checklist_hash") or ""
            ),
            "google_execution_checklist_ready": p0b_google_execution_checklist.get(
                "google_execution_checklist_ready"
            )
            is True,
            "google_spike_phase_handoff_ready": checklist_handoff.get("ready") is True,
            "google_main_scoring_allowed": p0b_google_execution_checklist.get("google_main_scoring_allowed") is True,
        },
        "p0b_google_phase_execution_request_verifier": {
            "status": request_verifier.get("status", ""),
            "hash_valid": request_verifier.get("hash_valid") is True,
            "p0b_google_phase_execution_request_packet_hash": str(
                request_verifier.get("p0b_google_phase_execution_request_packet_hash") or ""
            ),
            "phase_execution_request_packet_ready": request_verifier.get(
                "phase_execution_request_packet_ready"
            )
            is True,
            "google_spike_phase_handoff_ready": request_verifier.get("google_spike_phase_handoff_ready") is True,
            "google_main_scoring_allowed": request_verifier.get("google_main_scoring_allowed") is True,
            "errors": _strings(request_verifier.get("errors")),
        },
        "p0b_google_execution_checklist_verifier": {
            "status": checklist_verifier.get("status", ""),
            "hash_valid": checklist_verifier.get("hash_valid") is True,
            "google_execution_checklist_hash": str(checklist_verifier.get("google_execution_checklist_hash") or ""),
            "google_execution_checklist_ready": checklist_verifier.get("google_execution_checklist_ready") is True,
            "google_spike_phase_handoff_ready": checklist_verifier.get("google_spike_phase_handoff_ready") is True,
            "google_main_scoring_allowed": checklist_verifier.get("google_main_scoring_allowed") is True,
            "errors": _strings(checklist_verifier.get("errors")),
            "next_action": str(checklist_verifier.get("next_action") or ""),
        },
        "summary": summary,
        "phase_fulfillment_items": items,
        "phase_commands": _phase_commands(items),
        "verification_commands": [
            "make au-p0b-google-phase-execution-request",
            "make verify-au-p0b-google-phase-execution-request",
            "make au-p0b-google-execution-checklist",
            "make verify-au-p0b-google-execution-checklist",
            "make verify-au-p0b-google-phase-execution-fulfillment",
        ],
        "evidence_outputs": _evidence_outputs(items),
        "hard_gate_commands": [
            "make verify-au-p0b-google-phase-execution-fulfillment",
            strict_gate_command,
            request_strict_gate_command,
            scoring_strict_gate_command,
        ],
        "runtime_endpoints": {
            "p0b_google_phase_execution_fulfillment": "GET /v1/p0b-google-phase-execution-fulfillment/au",
            "p0b_google_phase_execution_request": "GET /v1/p0b-google-phase-execution-request/au",
            "p0b_google_execution_checklist": "GET /v1/p0b-google-execution-checklist/au",
            "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
        },
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "raw_answer_values_allowed": False,
            "raw_citation_values_allowed": False,
            "raw_asset_urls_allowed": False,
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
    payload["p0b_google_phase_execution_fulfillment_hash"] = compute_p0b_google_phase_execution_fulfillment_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google phase execution fulfillment JSON")
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
        "--output-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_PHASE_EXECUTION_FULFILLMENT_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0b Google phase execution fulfillment JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0b_google_phase_execution_fulfillment(
        phase_execution_request_path=Path(args.phase_execution_request_path),
        p0b_google_execution_checklist_path=Path(args.p0b_google_execution_checklist_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
