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
from scripts.verify_au_p0b_google_execution_checklist import (  # noqa: E402
    verify_au_p0b_google_execution_checklist,
)


PACKET_VERSION = "au_p0b_google_phase_execution_request_packet_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-phase-execution-request-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0b_google_phase_execution_request_packet_hash(packet: dict[str, Any]) -> str:
    payload = dict(packet)
    payload.pop("p0b_google_phase_execution_request_packet_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_file_entry(name: str, path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": name, "path": str(path), "exists": path.exists()}
    if path.is_file():
        entry["size_bytes"] = path.stat().st_size
        entry["file_sha256"] = _file_sha256(path)
    return entry


def _load_or_build_p0b_google_execution_checklist(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        checklist = build_au_p0b_google_execution_checklist(output_path=path, generated_at=generated_at)
        return checklist, {"path": str(path), "exists": False, "source": "generated_in_memory", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        checklist = build_au_p0b_google_execution_checklist(output_path=path, generated_at=generated_at)
        return checklist, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if isinstance(payload, dict):
        return payload, {"path": str(path), "exists": True, "source": "existing_file", "errors": []}
    checklist = build_au_p0b_google_execution_checklist(output_path=path, generated_at=generated_at)
    return checklist, {"path": str(path), "exists": True, "source": "generated_in_memory", "errors": ["not_json_object"]}


def _command_shells(phase: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    for command in _as_list(phase.get("commands")):
        shell = str(_as_dict(command).get("shell") or "").strip()
        if shell:
            commands.append(shell)
    return commands


def _phase_request(phase: dict[str, Any]) -> dict[str, Any]:
    artifacts = [_as_dict(artifact) for artifact in _as_list(phase.get("artifacts"))]
    return {
        "id": str(phase.get("id") or ""),
        "title": str(phase.get("title") or ""),
        "planned_runs": _int(phase.get("planned_runs")),
        "ready": phase.get("ready") is True,
        "can_start": phase.get("can_start") is True,
        "command_ids": _string_list(phase.get("command_ids")),
        "commands": _command_shells(phase),
        "artifact_keys": _string_list(phase.get("artifact_keys")),
        "artifacts": [
            {
                "key": str(artifact.get("key") or ""),
                "path": str(artifact.get("path") or ""),
                "exists": artifact.get("exists") is True,
                "status": str(artifact.get("status") or ""),
                "ready": artifact.get("ready") is True,
                "hash_valid": artifact.get("hash_valid") if "hash_valid" in artifact else None,
                "errors": [str(error) for error in _as_list(artifact.get("errors"))],
                "ready_for_playwright_smoke": artifact.get("ready_for_playwright_smoke")
                if "ready_for_playwright_smoke" in artifact
                else None,
                "ready_for_full_google_run": artifact.get("ready_for_full_google_run")
                if "ready_for_full_google_run" in artifact
                else None,
                "smoke_success": artifact.get("smoke_success") if "smoke_success" in artifact else None,
                "manual_backfill_ready": artifact.get("manual_backfill_ready")
                if "manual_backfill_ready" in artifact
                else None,
                "collector_health_ready": artifact.get("collector_health_ready")
                if "collector_health_ready" in artifact
                else None,
                "google_gates_ready": artifact.get("google_gates_ready")
                if "google_gates_ready" in artifact
                else None,
                "google_main_scoring_allowed": artifact.get("google_main_scoring_allowed")
                if "google_main_scoring_allowed" in artifact
                else None,
            }
            for artifact in artifacts
        ],
        "evidence_outputs": [str(value) for value in _as_list(phase.get("evidence_outputs")) if str(value)],
        "prerequisite_gate_ids": _string_list(phase.get("prerequisite_gate_ids")),
        "prerequisite_phase_id": str(phase.get("prerequisite_phase_id") or ""),
        "blocking_reasons": _string_list(phase.get("blocking_reasons")),
    }


def _phase_requests(handoff: dict[str, Any]) -> list[dict[str, Any]]:
    return [_phase_request(_as_dict(phase)) for phase in _as_list(handoff.get("phases"))]


def _blocking_reasons(phases: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for phase in phases:
        phase_id = str(phase.get("id") or "")
        for reason in _string_list(phase.get("blocking_reasons")):
            reasons.append(f"{phase_id}:{reason}")
    return sorted(dict.fromkeys(reasons))


def _all_phase_commands(phases: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for phase in phases:
        commands.extend(_string_list(phase.get("commands")))
    return commands


def _all_evidence_outputs(phases: list[dict[str, Any]]) -> list[str]:
    outputs: list[str] = []
    for phase in phases:
        outputs.extend(_string_list(phase.get("evidence_outputs")))
    return sorted(dict.fromkeys(outputs))


def build_au_p0b_google_phase_execution_request_packet(
    *,
    p0b_google_execution_checklist_path: Path = Path(DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH),
    p0b_google_execution_checklist: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if p0b_google_execution_checklist is None:
        p0b_google_execution_checklist, source = _load_or_build_p0b_google_execution_checklist(
            p0b_google_execution_checklist_path,
            generated_at=generated_at,
        )
    else:
        source = {
            "path": str(p0b_google_execution_checklist_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    verifier = verify_au_p0b_google_execution_checklist(
        p0b_google_execution_checklist,
        path=p0b_google_execution_checklist_path,
    )
    handoff = _as_dict(p0b_google_execution_checklist.get("google_spike_phase_handoff"))
    phases = _phase_requests(handoff)
    setup_commands = [
        "make au-p0b-google-environment-request",
        "make verify-au-p0b-google-environment-request",
        "make au-p0b-google-manual-backfill-request",
        "make verify-au-p0b-google-manual-backfill-request",
        "make au-p0b-google-runbook-dry-run",
        "make verify-au-p0b-google-runbook-execution",
    ]
    phase_commands = _all_phase_commands(phases)
    verification_commands = [
        "make au-p0b-google-playwright-env",
        "make verify-au-p0b-google-playwright-env",
        "make au-p0b-google-playwright-smoke",
        "make verify-au-p0b-google-playwright-smoke",
        "make verify-au-p0b-google-manual-backfill",
        "make au-p0b-google-spike-health",
        "make au-p0b-google-spike-health-manifest",
        "make au-p0b-google-spike",
        "make au-p0b-google-spike-manifest",
        "make au-p0b-google-status",
        "make verify-au-p0b-google-status",
        "make au-p0b-google-package",
        "make verify-au-p0b-google-package",
        "make au-p0b-google-execution-checklist",
        "make verify-au-p0b-google-execution-checklist",
    ]
    evidence_outputs = _all_evidence_outputs(phases)
    redaction_policy = _as_dict(handoff.get("redaction_policy"))
    packet_ready = verifier.get("status") == "pass" and verifier.get("hash_valid") is True
    blocking_reasons = _blocking_reasons(phases)

    hard_gate_commands = [
        "make au-p0b-google-phase-execution-request",
        "make verify-au-p0b-google-phase-execution-request",
        "make au-p0b-google-playwright-env",
        "make verify-au-p0b-google-playwright-env",
        "make au-p0b-google-playwright-smoke",
        "make verify-au-p0b-google-playwright-smoke",
        "make verify-au-p0b-google-manual-backfill",
        "make au-p0b-google-spike-health",
        "make au-p0b-google-spike-health-manifest",
        "make au-p0b-google-spike",
        "make au-p0b-google-spike-manifest",
        "make au-p0b-google-status",
        "make verify-au-p0b-google-status",
        "make au-p0b-google-package",
        "make verify-au-p0b-google-package",
        "make au-p0b-google-execution-checklist",
        "make verify-au-p0b-google-execution-checklist",
        "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_phase_execution_request_packet.py "
        "${GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-phase-execution-request-latest.json} --require-google-phases-ready",
        "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_execution_checklist.py "
        "${GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json} --require-google-main-scoring-ready",
    ]

    payload: dict[str, Any] = {
        "p0b_google_phase_execution_request_packet_version": PACKET_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if packet_ready else "fail",
        "phase_execution_request_packet_ready": packet_ready,
        "google_spike_phase_handoff_ready": handoff.get("ready") is True,
        "google_main_scoring_allowed": p0b_google_execution_checklist.get("google_main_scoring_allowed") is True,
        "output_path": str(output_path) if output_path else "",
        "source_p0b_google_execution_checklist": {
            "path": str(p0b_google_execution_checklist_path),
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
            "google_main_scoring_allowed": p0b_google_execution_checklist.get("google_main_scoring_allowed") is True,
            "source": source,
        },
        "p0b_google_execution_checklist_verifier": {
            "status": verifier.get("status", ""),
            "hash_valid": verifier.get("hash_valid") is True,
            "google_execution_checklist_hash": str(verifier.get("google_execution_checklist_hash") or ""),
            "errors": [str(value) for value in _as_list(verifier.get("errors"))],
            "next_action": str(verifier.get("next_action") or ""),
        },
        "summary": {
            "source_google_spike_phase_handoff_version": str(handoff.get("version") or ""),
            "google_spike_phase_handoff_ready": handoff.get("ready") is True,
            "phase_count": _int(handoff.get("phase_count")),
            "ready_phase_count": _int(handoff.get("ready_phase_count")),
            "blocked_phase_count": _int(handoff.get("blocked_phase_count")),
            "next_phase": str(handoff.get("next_phase") or ""),
            "full_spike_planned_runs": _int(handoff.get("full_spike_planned_runs")),
            "manual_expected_record_count": _int(handoff.get("manual_expected_record_count")),
            "phase_order": _string_list(handoff.get("phase_order")),
            "phase_request_count": len(phases),
            "command_count": len(phase_commands),
            "setup_command_count": len(setup_commands),
            "verification_command_count": len(verification_commands),
            "evidence_output_count": len(evidence_outputs),
            "blocking_reason_count": len(blocking_reasons),
            "blocking_reasons": blocking_reasons,
            "raw_secret_values_allowed": redaction_policy.get("raw_secret_values_allowed") is True,
            "raw_answer_values_allowed": redaction_policy.get("raw_answer_values_allowed") is True,
            "raw_citation_values_allowed": redaction_policy.get("raw_citation_values_allowed") is True,
            "raw_asset_urls_allowed": redaction_policy.get("raw_asset_urls_allowed") is True,
            "phase_entries_reference_command_ids_and_artifact_paths_only": redaction_policy.get(
                "phase_entries_reference_command_ids_and_artifact_paths_only"
            )
            is True,
            "next_command": phase_commands[0] if phase_commands else "",
            "post_update_verification_command": verification_commands[0] if verification_commands else "",
            "google_next_action": str(p0b_google_execution_checklist.get("next_action") or ""),
        },
        "phase_requests": phases,
        "setup_commands": setup_commands,
        "phase_commands": phase_commands,
        "verification_commands": verification_commands,
        "evidence_outputs": evidence_outputs,
        "redaction_policy": {
            "raw_secret_values_allowed": redaction_policy.get("raw_secret_values_allowed") is True,
            "raw_answer_values_allowed": redaction_policy.get("raw_answer_values_allowed") is True,
            "raw_citation_values_allowed": redaction_policy.get("raw_citation_values_allowed") is True,
            "raw_asset_urls_allowed": redaction_policy.get("raw_asset_urls_allowed") is True,
            "phase_entries_reference_command_ids_and_artifact_paths_only": redaction_policy.get(
                "phase_entries_reference_command_ids_and_artifact_paths_only"
            )
            is True,
        },
        "runtime_endpoints": {
            "p0b_google_phase_execution_request": "GET /v1/p0b-google-phase-execution-request/au",
            "p0b_google_execution_checklist": "GET /v1/p0b-google-execution-checklist/au",
            "p0b_google_environment_request": "GET /v1/p0b-google-environment-request/au",
            "p0b_google_manual_backfill_request": "GET /v1/p0b-google-manual-backfill-request/au",
            "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
            "next_work_item": "GET /v1/next-work-item/au",
        },
        "hard_gate_commands": hard_gate_commands,
        "evidence_sources": [_source_file_entry("p0b_google_execution_checklist", p0b_google_execution_checklist_path)],
    }
    payload["p0b_google_phase_execution_request_packet_hash"] = (
        compute_p0b_google_phase_execution_request_packet_hash(payload)
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google phase execution request packet JSON")
    parser.add_argument(
        "--p0b-google-execution-checklist-path",
        default=os.environ.get(
            "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH",
            DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH,
        ),
        help="Path to the AU P0b Google execution checklist JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_REQUEST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0b Google phase execution request packet JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0b_google_phase_execution_request_packet(
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
