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
from scripts.verify_au_p0a_execution_checklist import verify_au_p0a_execution_checklist  # noqa: E402


PACKET_VERSION = "au_p0a_real_batch_request_packet_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-real-batch-request-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0a_real_batch_request_packet_hash(packet: dict[str, Any]) -> str:
    payload = dict(packet)
    payload.pop("p0a_real_batch_request_packet_hash", None)
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


def _load_or_build_p0a_execution_checklist(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        checklist = build_au_p0a_execution_checklist(output_path=path, generated_at=generated_at)
        return checklist, {"path": str(path), "exists": False, "source": "generated_in_memory", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        checklist = build_au_p0a_execution_checklist(output_path=path, generated_at=generated_at)
        return checklist, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if isinstance(payload, dict):
        return payload, {"path": str(path), "exists": True, "source": "existing_file", "errors": []}
    checklist = build_au_p0a_execution_checklist(output_path=path, generated_at=generated_at)
    return checklist, {"path": str(path), "exists": True, "source": "generated_in_memory", "errors": ["not_json_object"]}


def _command_shells(phase: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    for command in _as_list(phase.get("commands")):
        command_dict = _as_dict(command)
        shell = str(command_dict.get("shell") or "").strip()
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
                "ready_for_design_partner": artifact.get("ready_for_design_partner") is True,
                "hash_valid": artifact.get("hash_valid") if "hash_valid" in artifact else None,
                "ready": artifact.get("ready") is True,
                "errors": [str(error) for error in _as_list(artifact.get("errors"))],
            }
            for artifact in artifacts
        ],
        "evidence_outputs": [str(value) for value in _as_list(phase.get("evidence_outputs")) if str(value)],
        "prerequisite_gate_ids": _string_list(phase.get("prerequisite_gate_ids")),
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


def _all_commands(phases: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for phase in phases:
        commands.extend(_string_list(phase.get("commands")))
    return commands


def _all_evidence_outputs(phases: list[dict[str, Any]]) -> list[str]:
    outputs: list[str] = []
    for phase in phases:
        outputs.extend(_string_list(phase.get("evidence_outputs")))
    return sorted(dict.fromkeys(outputs))


def build_au_p0a_real_batch_request_packet(
    *,
    p0a_execution_checklist_path: Path = Path(DEFAULT_P0A_EXECUTION_CHECKLIST_PATH),
    p0a_execution_checklist: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if p0a_execution_checklist is None:
        p0a_execution_checklist, source = _load_or_build_p0a_execution_checklist(
            p0a_execution_checklist_path,
            generated_at=generated_at,
        )
    else:
        source = {"path": str(p0a_execution_checklist_path), "exists": True, "source": "provided_payload", "errors": []}

    verifier = verify_au_p0a_execution_checklist(p0a_execution_checklist, path=p0a_execution_checklist_path)
    handoff = _as_dict(p0a_execution_checklist.get("real_batch_phase_handoff"))
    phases = _phase_requests(handoff)
    setup_commands = [
        "make au-p0a-credential-request",
        "make verify-au-p0a-credential-request",
        "make au-p0a-env",
        "make verify-au-p0a-env",
        "make au-p0a-runbook-dry-run",
        "make verify-au-p0a-runbook-execution",
    ]
    phase_commands = _all_commands(phases)
    verification_commands = [
        "make api-preflight",
        "make verify-api-preflight",
        "make preflight-manifest",
        "make au-p0a-package",
        "make verify-au-p0a-package",
        "make au-p0a-status",
        "make verify-au-p0a-status",
        "make au-p0a-execution-checklist",
        "make verify-au-p0a-execution-checklist",
    ]
    evidence_outputs = _all_evidence_outputs(phases)
    redaction_policy = _as_dict(handoff.get("redaction_policy"))
    packet_ready = verifier.get("status") == "pass" and verifier.get("hash_valid") is True
    blocking_reasons = _blocking_reasons(phases)

    hard_gate_commands = [
        "make au-p0a-real-batch-request",
        "make verify-au-p0a-real-batch-request",
        "make api-preflight",
        "make verify-api-preflight",
        "make preflight-manifest",
        "make au-p0a-status",
        "make verify-au-p0a-status",
        "make au-p0a-execution-checklist",
        "make verify-au-p0a-execution-checklist",
        "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_real_batch_request_packet.py "
        "${GENO_AU_P0A_REAL_BATCH_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-real-batch-request-latest.json} --require-real-batches-ready",
        "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_execution_checklist.py "
        "${GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-execution-checklist-latest.json} --require-design-partner-ready",
    ]

    payload: dict[str, Any] = {
        "p0a_real_batch_request_packet_version": PACKET_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if packet_ready else "fail",
        "real_batch_request_packet_ready": packet_ready,
        "real_batch_phase_handoff_ready": handoff.get("ready") is True,
        "ready_for_design_partner": p0a_execution_checklist.get("ready_for_design_partner") is True,
        "output_path": str(output_path) if output_path else "",
        "source_p0a_execution_checklist": {
            "path": str(p0a_execution_checklist_path),
            "execution_checklist_version": str(p0a_execution_checklist.get("execution_checklist_version") or ""),
            "p0a_execution_checklist_hash": str(p0a_execution_checklist.get("p0a_execution_checklist_hash") or ""),
            "p0a_execution_checklist_ready": p0a_execution_checklist.get("p0a_execution_checklist_ready") is True,
            "ready_for_design_partner": p0a_execution_checklist.get("ready_for_design_partner") is True,
            "source": source,
        },
        "p0a_execution_checklist_verifier": {
            "status": verifier.get("status", ""),
            "hash_valid": verifier.get("hash_valid") is True,
            "p0a_execution_checklist_hash": str(verifier.get("p0a_execution_checklist_hash") or ""),
            "errors": [str(value) for value in _as_list(verifier.get("errors"))],
            "next_action": str(verifier.get("next_action") or ""),
        },
        "summary": {
            "source_real_batch_phase_handoff_version": str(handoff.get("version") or ""),
            "real_batch_phase_handoff_ready": handoff.get("ready") is True,
            "phase_count": _int(handoff.get("phase_count")),
            "ready_phase_count": _int(handoff.get("ready_phase_count")),
            "blocked_phase_count": _int(handoff.get("blocked_phase_count")),
            "next_phase": str(handoff.get("next_phase") or ""),
            "total_planned_runs": _int(handoff.get("total_planned_runs")),
            "phase_order": _string_list(handoff.get("phase_order")),
            "phase_request_count": len(phases),
            "command_count": len(phase_commands),
            "setup_command_count": len(setup_commands),
            "verification_command_count": len(verification_commands),
            "evidence_output_count": len(evidence_outputs),
            "blocking_reason_count": len(blocking_reasons),
            "blocking_reasons": blocking_reasons,
            "raw_secret_values_allowed": redaction_policy.get("raw_secret_values_allowed") is True,
            "phase_entries_reference_command_ids_and_artifact_paths_only": redaction_policy.get(
                "phase_entries_reference_command_ids_and_artifact_paths_only"
            )
            is True,
            "next_command": phase_commands[0] if phase_commands else "",
            "post_update_verification_command": verification_commands[0] if verification_commands else "",
            "p0a_next_action": str(p0a_execution_checklist.get("next_action") or ""),
        },
        "phase_requests": phases,
        "setup_commands": setup_commands,
        "phase_commands": phase_commands,
        "verification_commands": verification_commands,
        "evidence_outputs": evidence_outputs,
        "redaction_policy": {
            "raw_secret_values_allowed": redaction_policy.get("raw_secret_values_allowed") is True,
            "phase_entries_reference_command_ids_and_artifact_paths_only": redaction_policy.get(
                "phase_entries_reference_command_ids_and_artifact_paths_only"
            )
            is True,
        },
        "runtime_endpoints": {
            "p0a_real_batch_request": "GET /v1/p0a-real-batch-request/au",
            "p0a_credential_request": "GET /v1/p0a-credential-request/au",
            "p0a_execution_checklist": "GET /v1/p0a-execution-checklist/au",
            "p0a_environment_checklist": "GET /v1/p0a-environment-checklist/au",
            "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
            "next_work_item": "GET /v1/next-work-item/au",
        },
        "hard_gate_commands": hard_gate_commands,
        "evidence_sources": [_source_file_entry("p0a_execution_checklist", p0a_execution_checklist_path)],
    }
    payload["p0a_real_batch_request_packet_hash"] = compute_p0a_real_batch_request_packet_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0a real batch request packet JSON")
    parser.add_argument(
        "--p0a-execution-checklist-path",
        default=os.environ.get("GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH", DEFAULT_P0A_EXECUTION_CHECKLIST_PATH),
        help="Path to the AU P0a execution checklist JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_REAL_BATCH_REQUEST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0a real batch request packet JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0a_real_batch_request_packet(
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
