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

from scripts.build_au_handoff_dossier import (  # noqa: E402
    DEFAULT_MARKDOWN_OUTPUT_PATH as DEFAULT_HANDOFF_DOSSIER_MARKDOWN_PATH,
    DEFAULT_OUTPUT_PATH as DEFAULT_HANDOFF_DOSSIER_PATH,
    build_au_handoff_dossier,
)
from scripts.build_au_external_dependency_handoff import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_EXTERNAL_DEPENDENCY_HANDOFF_PATH,
)
from scripts.verify_au_handoff_dossier import verify_au_handoff_dossier  # noqa: E402


PACKET_VERSION = "au_next_work_item_packet_v1"
EXECUTION_CONTEXT_VERSION = "au_next_work_item_execution_context_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-next-work-item-latest.json"

REQUEST_PACKET_CONTEXTS: dict[str, dict[str, str]] = {
    "p0a_environment": {
        "linked_dependency_group_id": "p0a_provider_credentials",
        "artifact_type": "request_packet",
        "request_packet_id": "p0a_credential_request",
        "request_packet_title": "P0a credential request packet",
        "output_path": "docs/runtime_preflight/au-p0a-credential-request-latest.json",
        "hash_field": "p0a_credential_request_packet_hash",
        "build_command": "make au-p0a-credential-request",
        "verify_command": "make verify-au-p0a-credential-request",
        "strict_gate_command": (
            "PYTHONPATH=packages/geno_core:apps/api python3 "
            "scripts/verify_au_p0a_credential_request_packet.py "
            "${GENO_AU_P0A_CREDENTIAL_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-request-latest.json} "
            "--require-credentials-ready"
        ),
        "runtime_endpoint": "GET /v1/p0a-credential-request/au",
    },
    "p0a_small_batch": {
        "linked_dependency_group_id": "p0a_real_batches",
        "artifact_type": "fulfillment_artifact",
        "request_packet_id": "p0a_real_batch_fulfillment",
        "request_packet_title": "P0a real batch fulfillment artifact",
        "output_path": "docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json",
        "hash_field": "p0a_real_batch_fulfillment_hash",
        "build_command": "make au-p0a-real-batch-fulfillment",
        "verify_command": "make verify-au-p0a-real-batch-fulfillment",
        "strict_gate_command": (
            "PYTHONPATH=packages/geno_core:apps/api python3 "
            "scripts/verify_au_p0a_real_batch_fulfillment.py "
            "${GENO_AU_P0A_REAL_BATCH_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json} "
            "--require-fulfilled"
        ),
        "runtime_endpoint": "GET /v1/p0a-real-batch-fulfillment/au",
    },
    "p0a_full_batch": {
        "linked_dependency_group_id": "p0a_real_batches",
        "artifact_type": "fulfillment_artifact",
        "request_packet_id": "p0a_real_batch_fulfillment",
        "request_packet_title": "P0a real batch fulfillment artifact",
        "output_path": "docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json",
        "hash_field": "p0a_real_batch_fulfillment_hash",
        "build_command": "make au-p0a-real-batch-fulfillment",
        "verify_command": "make verify-au-p0a-real-batch-fulfillment",
        "strict_gate_command": (
            "PYTHONPATH=packages/geno_core:apps/api python3 "
            "scripts/verify_au_p0a_real_batch_fulfillment.py "
            "${GENO_AU_P0A_REAL_BATCH_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json} "
            "--require-fulfilled"
        ),
        "runtime_endpoint": "GET /v1/p0a-real-batch-fulfillment/au",
    },
    "p0b_google_playwright_env": {
        "linked_dependency_group_id": "p0b_google_environment",
        "artifact_type": "fulfillment_artifact",
        "request_packet_id": "p0b_google_environment_fulfillment",
        "request_packet_title": "P0b Google environment fulfillment artifact",
        "output_path": "docs/runtime_preflight/au-p0b-google-environment-fulfillment-latest.json",
        "hash_field": "p0b_google_environment_fulfillment_hash",
        "build_command": "make au-p0b-google-environment-fulfillment",
        "verify_command": "make verify-au-p0b-google-environment-fulfillment",
        "strict_gate_command": (
            "PYTHONPATH=packages/geno_core:apps/api python3 "
            "scripts/verify_au_p0b_google_environment_fulfillment.py "
            "${GENO_AU_P0B_GOOGLE_ENVIRONMENT_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-environment-fulfillment-latest.json} "
            "--require-fulfilled"
        ),
        "runtime_endpoint": "GET /v1/p0b-google-environment-fulfillment/au",
    },
    "p0b_google_manual_backfill": {
        "linked_dependency_group_id": "p0b_google_manual_backfill",
        "artifact_type": "fulfillment_artifact",
        "request_packet_id": "p0b_google_manual_backfill_fulfillment",
        "request_packet_title": "P0b Google manual backfill fulfillment artifact",
        "output_path": "docs/runtime_preflight/au-p0b-google-manual-backfill-fulfillment-latest.json",
        "hash_field": "p0b_google_manual_backfill_fulfillment_hash",
        "build_command": "make au-p0b-google-manual-backfill-fulfillment",
        "verify_command": "make verify-au-p0b-google-manual-backfill-fulfillment",
        "strict_gate_command": (
            "PYTHONPATH=packages/geno_core:apps/api python3 "
            "scripts/verify_au_p0b_google_manual_backfill_fulfillment.py "
            "${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-fulfillment-latest.json} "
            "--require-fulfilled"
        ),
        "runtime_endpoint": "GET /v1/p0b-google-manual-backfill-fulfillment/au",
    },
    "p0b_google_playwright_smoke": {
        "linked_dependency_group_id": "p0b_google_phase_execution",
        "artifact_type": "fulfillment_artifact",
        "request_packet_id": "p0b_google_phase_execution_fulfillment",
        "request_packet_title": "P0b Google phase execution fulfillment artifact",
        "output_path": "docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json",
        "hash_field": "p0b_google_phase_execution_fulfillment_hash",
        "build_command": "make au-p0b-google-phase-execution-fulfillment",
        "verify_command": "make verify-au-p0b-google-phase-execution-fulfillment",
        "strict_gate_command": (
            "PYTHONPATH=packages/geno_core:apps/api python3 "
            "scripts/verify_au_p0b_google_phase_execution_fulfillment.py "
            "${GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json} "
            "--require-fulfilled"
        ),
        "runtime_endpoint": "GET /v1/p0b-google-phase-execution-fulfillment/au",
    },
    "p0b_google_spike_health": {
        "linked_dependency_group_id": "p0b_google_phase_execution",
        "artifact_type": "fulfillment_artifact",
        "request_packet_id": "p0b_google_phase_execution_fulfillment",
        "request_packet_title": "P0b Google phase execution fulfillment artifact",
        "output_path": "docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json",
        "hash_field": "p0b_google_phase_execution_fulfillment_hash",
        "build_command": "make au-p0b-google-phase-execution-fulfillment",
        "verify_command": "make verify-au-p0b-google-phase-execution-fulfillment",
        "strict_gate_command": (
            "PYTHONPATH=packages/geno_core:apps/api python3 "
            "scripts/verify_au_p0b_google_phase_execution_fulfillment.py "
            "${GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json} "
            "--require-fulfilled"
        ),
        "runtime_endpoint": "GET /v1/p0b-google-phase-execution-fulfillment/au",
    },
    "p0b_google_full_spike": {
        "linked_dependency_group_id": "p0b_google_phase_execution",
        "artifact_type": "fulfillment_artifact",
        "request_packet_id": "p0b_google_phase_execution_fulfillment",
        "request_packet_title": "P0b Google phase execution fulfillment artifact",
        "output_path": "docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json",
        "hash_field": "p0b_google_phase_execution_fulfillment_hash",
        "build_command": "make au-p0b-google-phase-execution-fulfillment",
        "verify_command": "make verify-au-p0b-google-phase-execution-fulfillment",
        "strict_gate_command": (
            "PYTHONPATH=packages/geno_core:apps/api python3 "
            "scripts/verify_au_p0b_google_phase_execution_fulfillment.py "
            "${GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json} "
            "--require-fulfilled"
        ),
        "runtime_endpoint": "GET /v1/p0b-google-phase-execution-fulfillment/au",
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_next_work_item_packet_hash(packet: dict[str, Any]) -> str:
    payload = dict(packet)
    payload.pop("next_work_item_packet_hash", None)
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


def _append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


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


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _dependency_group_context(
    external_dependency_handoff: dict[str, Any],
    source_external_dependency_handoff: dict[str, Any],
    group_id: str,
) -> dict[str, Any]:
    for group in _as_list(external_dependency_handoff.get("dependency_groups")):
        group_payload = _as_dict(group)
        if group_payload.get("id") == group_id:
            return {
                "id": group_id,
                "source": "external_dependency_handoff",
                "source_path": str(source_external_dependency_handoff.get("path") or ""),
                "source_external_dependency_handoff_hash": str(
                    source_external_dependency_handoff.get("external_dependency_handoff_hash") or ""
                ),
                "status": str(group_payload.get("status") or ""),
                "dependency_class": str(group_payload.get("dependency_class") or ""),
                "ready": group_payload.get("ready") is True,
                "target_env_file": str(group_payload.get("target_env_file") or ""),
                "next_command": str(group_payload.get("next_command") or ""),
                "commands": _string_list(group_payload.get("commands")),
                "verification_commands": _string_list(group_payload.get("verification_commands")),
                "evidence_outputs": _string_list(group_payload.get("evidence_outputs")),
                "command_count": len(_string_list(group_payload.get("commands"))),
                "verification_command_count": len(_string_list(group_payload.get("verification_commands"))),
                "evidence_output_count": len(_string_list(group_payload.get("evidence_outputs"))),
                "blocking_reason_count": len(_string_list(group_payload.get("blocking_reasons"))),
                "blocking_reasons": _string_list(group_payload.get("blocking_reasons")),
            }
    return {
        "id": group_id,
        "source": "missing",
        "source_path": str(source_external_dependency_handoff.get("path") or ""),
        "source_external_dependency_handoff_hash": str(
            source_external_dependency_handoff.get("external_dependency_handoff_hash") or ""
        ),
        "status": "missing",
        "dependency_class": "",
        "ready": False,
        "target_env_file": "",
        "next_command": "",
        "commands": [],
        "verification_commands": [],
        "evidence_outputs": [],
        "command_count": 0,
        "verification_command_count": 0,
        "evidence_output_count": 0,
        "blocking_reason_count": 0,
        "blocking_reasons": [],
    }


def _request_packet_context(next_work_item_id: str) -> dict[str, Any]:
    context = REQUEST_PACKET_CONTEXTS.get(next_work_item_id)
    if not context:
        return {
            "request_packet_available": False,
            "request_packet_id": "",
            "request_packet_title": "",
            "artifact_type": "",
            "output_path": "",
            "exists": False,
            "hash_field": "",
            "packet_hash": "",
            "file_sha256": "",
            "build_command": "",
            "verify_command": "",
            "strict_gate_command": "",
            "runtime_endpoint": "",
        }
    output_path = Path(context["output_path"])
    payload = _load_json_file(output_path)
    packet_hash = str(payload.get(context["hash_field"]) or "")
    return {
        "request_packet_available": True,
        "request_packet_id": context["request_packet_id"],
        "request_packet_title": context["request_packet_title"],
        "artifact_type": context["artifact_type"],
        "output_path": str(output_path),
        "exists": output_path.is_file(),
        "hash_field": context["hash_field"],
        "packet_hash": packet_hash,
        "file_sha256": _file_sha256(output_path) if output_path.is_file() else "",
        "build_command": context["build_command"],
        "verify_command": context["verify_command"],
        "strict_gate_command": context["strict_gate_command"],
        "runtime_endpoint": context["runtime_endpoint"],
    }


def _execution_context(
    *,
    external_dependency_handoff: dict[str, Any],
    source_external_dependency_handoff: dict[str, Any],
    next_work_item_id: str,
    commands: list[str],
    verification_commands: list[str],
    evidence_outputs: list[str],
) -> dict[str, Any]:
    mapped_context = REQUEST_PACKET_CONTEXTS.get(next_work_item_id, {})
    request_packet = _request_packet_context(next_work_item_id)
    dependency_group = _dependency_group_context(
        external_dependency_handoff,
        source_external_dependency_handoff,
        str(mapped_context.get("linked_dependency_group_id") or ""),
    )
    group_commands = _string_list(dependency_group.get("commands"))
    group_verification_commands = _string_list(dependency_group.get("verification_commands"))
    group_evidence_outputs = _string_list(dependency_group.get("evidence_outputs"))
    combined_commands: list[str] = []
    combined_verification_commands: list[str] = []
    combined_evidence_outputs: list[str] = []
    for command in (*commands, *group_commands):
        if command:
            _append_unique(combined_commands, command)
    for command in (*verification_commands, *group_verification_commands):
        if command:
            _append_unique(combined_verification_commands, command)
    for evidence_output in (*evidence_outputs, *group_evidence_outputs):
        if evidence_output:
            _append_unique(combined_evidence_outputs, evidence_output)
    recommended_sequence: list[str] = []
    for command in (
        request_packet.get("build_command", ""),
        request_packet.get("verify_command", ""),
        *combined_commands,
        *combined_verification_commands,
        request_packet.get("strict_gate_command", ""),
    ):
        if isinstance(command, str) and command and command not in recommended_sequence:
            recommended_sequence.append(command)
    return {
        "execution_context_version": EXECUTION_CONTEXT_VERSION,
        "next_work_item_id": next_work_item_id,
        "linked_dependency_group_id": str(mapped_context.get("linked_dependency_group_id") or ""),
        "linked_dependency_group": dependency_group,
        "linked_request_packet": request_packet,
        "work_item_commands": commands,
        "work_item_verification_commands": verification_commands,
        "work_item_evidence_outputs": evidence_outputs,
        "group_commands": group_commands,
        "group_verification_commands": group_verification_commands,
        "group_evidence_outputs": group_evidence_outputs,
        "combined_commands": combined_commands,
        "combined_verification_commands": combined_verification_commands,
        "combined_evidence_outputs": combined_evidence_outputs,
        "group_command_count": len(group_commands),
        "group_verification_command_count": len(group_verification_commands),
        "group_evidence_output_count": len(group_evidence_outputs),
        "recommended_sequence": recommended_sequence,
        "recommended_sequence_count": len(recommended_sequence),
        "strict_gate_command": str(request_packet.get("strict_gate_command") or ""),
        "requires_request_packet_before_execution": bool(request_packet.get("request_packet_available")),
        "request_packet_hash_available": bool(request_packet.get("packet_hash")),
    }


def _load_or_build_handoff_dossier(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        dossier = build_au_handoff_dossier(
            output_path=path,
            markdown_output_path=Path(DEFAULT_HANDOFF_DOSSIER_MARKDOWN_PATH),
            generated_at=generated_at,
        )
        return dossier, {"path": str(path), "exists": False, "source": "generated_in_memory", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        dossier = build_au_handoff_dossier(
            output_path=path,
            markdown_output_path=Path(DEFAULT_HANDOFF_DOSSIER_MARKDOWN_PATH),
            generated_at=generated_at,
        )
        return dossier, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if isinstance(payload, dict):
        return payload, {"path": str(path), "exists": True, "source": "existing_file"}
    dossier = build_au_handoff_dossier(
        output_path=path,
        markdown_output_path=Path(DEFAULT_HANDOFF_DOSSIER_MARKDOWN_PATH),
        generated_at=generated_at,
    )
    return dossier, {"path": str(path), "exists": True, "source": "generated_in_memory", "errors": ["not_json_object"]}


def _load_external_dependency_handoff(
    path: Path,
    external_dependency_handoff: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if external_dependency_handoff is not None:
        return external_dependency_handoff, {
            "path": str(path),
            "exists": True,
            "source": "provided_payload",
            "external_dependency_handoff_version": str(
                external_dependency_handoff.get("external_dependency_handoff_version") or ""
            ),
            "external_dependency_handoff_hash": str(
                external_dependency_handoff.get("external_dependency_handoff_hash") or ""
            ),
            "external_dependency_handoff_ready": external_dependency_handoff.get(
                "external_dependency_handoff_ready"
            )
            is True,
            "errors": [],
        }
    payload = _load_json_file(path)
    if payload:
        return payload, {
            "path": str(path),
            "exists": True,
            "source": "existing_file",
            "external_dependency_handoff_version": str(payload.get("external_dependency_handoff_version") or ""),
            "external_dependency_handoff_hash": str(payload.get("external_dependency_handoff_hash") or ""),
            "external_dependency_handoff_ready": payload.get("external_dependency_handoff_ready") is True,
            "errors": [],
        }
    return {}, {
        "path": str(path),
        "exists": path.exists(),
        "source": "missing_or_invalid_file",
        "external_dependency_handoff_version": "",
        "external_dependency_handoff_hash": "",
        "external_dependency_handoff_ready": False,
        "errors": ["external_dependency_handoff_missing_or_invalid"],
    }


def build_au_next_work_item_packet(
    *,
    handoff_dossier_path: Path = Path(DEFAULT_HANDOFF_DOSSIER_PATH),
    external_dependency_handoff_path: Path = Path(DEFAULT_EXTERNAL_DEPENDENCY_HANDOFF_PATH),
    handoff_dossier: dict[str, Any] | None = None,
    external_dependency_handoff: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if handoff_dossier is None:
        handoff_dossier, source = _load_or_build_handoff_dossier(handoff_dossier_path, generated_at=generated_at)
    else:
        source = {"path": str(handoff_dossier_path), "exists": True, "source": "provided_payload"}
    external_dependency_handoff, external_source = _load_external_dependency_handoff(
        external_dependency_handoff_path,
        external_dependency_handoff,
    )

    verifier = verify_au_handoff_dossier(handoff_dossier, path=handoff_dossier_path)
    summary = _as_dict(handoff_dossier.get("summary"))
    next_work_item = _as_dict(handoff_dossier.get("next_work_item"))
    next_work_item_id = str(summary.get("next_work_item_id") or next_work_item.get("id") or "none")
    commands = _string_list(next_work_item.get("commands"))
    verification_commands = _string_list(next_work_item.get("verification_commands"))
    evidence_outputs = _string_list(next_work_item.get("evidence_outputs"))
    execution_context = _execution_context(
        external_dependency_handoff=external_dependency_handoff,
        source_external_dependency_handoff=external_source,
        next_work_item_id=next_work_item_id,
        commands=commands,
        verification_commands=verification_commands,
        evidence_outputs=evidence_outputs,
    )
    combined_commands = _string_list(execution_context.get("combined_commands"))
    combined_verification_commands = _string_list(execution_context.get("combined_verification_commands"))
    combined_evidence_outputs = _string_list(execution_context.get("combined_evidence_outputs"))
    blocked_customer_gate_ids = _string_list(
        _as_dict(handoff_dossier.get("customer_handoff_readiness_audit")).get("blocked_customer_gate_ids")
    )
    packet_ready = (
        verifier.get("status") == "pass"
        and verifier.get("hash_valid") is True
        and bool(next_work_item_id)
        and (next_work_item_id == "none" or next_work_item.get("id") == next_work_item_id)
    )

    hard_gate_commands = [
        "make au-next-work-item",
        "make verify-au-next-work-item",
        "make au-customer-handoff-readiness",
        "make verify-au-customer-handoff-readiness",
    ]
    _append_unique(
        hard_gate_commands,
        "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_readiness.py "
        "${GENO_AU_CUSTOMER_HANDOFF_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-readiness-latest.json} "
        "--require-customer-ready",
    )
    for command in combined_verification_commands:
        _append_unique(hard_gate_commands, command)
    linked_request_packet = _as_dict(execution_context.get("linked_request_packet"))
    for command in (
        str(linked_request_packet.get("build_command") or ""),
        str(linked_request_packet.get("verify_command") or ""),
        str(linked_request_packet.get("strict_gate_command") or ""),
    ):
        if command:
            _append_unique(hard_gate_commands, command)

    payload: dict[str, Any] = {
        "next_work_item_packet_version": PACKET_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if packet_ready else "fail",
        "next_work_item_packet_ready": packet_ready,
        "ready_for_customer_report_handoff": handoff_dossier.get("ready_for_customer_report_handoff") is True,
        "output_path": str(output_path) if output_path else "",
        "source_handoff_dossier": {
            "path": str(handoff_dossier_path),
            "handoff_dossier_version": handoff_dossier.get("handoff_dossier_version", ""),
            "handoff_dossier_hash": str(handoff_dossier.get("handoff_dossier_hash") or ""),
            "handoff_dossier_ready": handoff_dossier.get("handoff_dossier_ready") is True,
            "ready_for_customer_report_handoff": handoff_dossier.get("ready_for_customer_report_handoff") is True,
            "source": source,
        },
        "source_external_dependency_handoff": external_source,
        "handoff_dossier_verifier": {
            "status": verifier.get("status", ""),
            "hash_valid": verifier.get("hash_valid") is True,
            "handoff_dossier_hash": str(verifier.get("handoff_dossier_hash") or ""),
            "errors": [str(value) for value in _as_list(verifier.get("errors"))],
            "handoff_posture": verifier.get("handoff_posture", ""),
            "remaining_blocker_count": int(verifier.get("remaining_blocker_count") or 0),
            "work_item_count": int(verifier.get("work_item_count") or 0),
            "next_work_item_id": str(verifier.get("next_work_item_id") or ""),
        },
        "summary": {
            "next_work_item_id": next_work_item_id,
            "next_action": str(summary.get("next_action") or next_work_item_id),
            "stage": str(next_work_item.get("stage") or ""),
            "title": str(next_work_item.get("title") or ""),
            "status": str(next_work_item.get("status") or ""),
            "dependency_class": str(next_work_item.get("dependency_class") or ""),
            "external_dependency": next_work_item.get("external_dependency") is True,
            "blocker_count": int(next_work_item.get("blocker_count") or 0),
            "remaining_blocker_count": int(summary.get("remaining_blocker_count") or 0),
            "external_dependency_blocker_count": int(summary.get("external_dependency_blocker_count") or 0),
            "customer_report_handoff_readiness_percent": _as_dict(
                handoff_dossier.get("customer_handoff_readiness_audit")
            ).get("customer_report_handoff_readiness_percent", 0.0),
            "structural_auditability_percent": _as_dict(
                handoff_dossier.get("customer_handoff_readiness_audit")
            ).get("structural_auditability_percent", 0.0),
            "runnable_now": bool(combined_commands),
            "command_count": len(combined_commands),
            "verification_command_count": len(combined_verification_commands),
            "evidence_output_count": len(combined_evidence_outputs),
            "work_item_command_count": len(commands),
            "work_item_verification_command_count": len(verification_commands),
            "work_item_evidence_output_count": len(evidence_outputs),
            "group_command_count": int(execution_context.get("group_command_count") or 0),
            "group_verification_command_count": int(execution_context.get("group_verification_command_count") or 0),
            "group_evidence_output_count": int(execution_context.get("group_evidence_output_count") or 0),
            "blocked_customer_gate_count": len(blocked_customer_gate_ids),
            "blocked_customer_gate_ids": blocked_customer_gate_ids,
            "linked_dependency_group_id": str(execution_context.get("linked_dependency_group_id") or ""),
            "linked_dependency_group_status": str(
                _as_dict(execution_context.get("linked_dependency_group")).get("status") or ""
            ),
            "linked_dependency_group_next_command": str(
                _as_dict(execution_context.get("linked_dependency_group")).get("next_command") or ""
            ),
            "linked_dependency_group_blocking_reason_count": int(
                _as_dict(execution_context.get("linked_dependency_group")).get("blocking_reason_count") or 0
            ),
            "linked_request_packet_id": str(linked_request_packet.get("request_packet_id") or ""),
            "linked_request_artifact_type": str(linked_request_packet.get("artifact_type") or ""),
            "linked_request_packet_hash": str(linked_request_packet.get("packet_hash") or ""),
            "linked_request_packet_exists": linked_request_packet.get("exists") is True,
            "recommended_sequence_count": int(execution_context.get("recommended_sequence_count") or 0),
            "request_packet_hash_available": execution_context.get("request_packet_hash_available") is True,
        },
        "next_work_item": next_work_item,
        "execution_context": execution_context,
        "commands": combined_commands,
        "verification_commands": combined_verification_commands,
        "evidence_outputs": combined_evidence_outputs,
        "runtime_endpoints": {
            "next_work_item": "GET /v1/next-work-item/au",
            "handoff_dossier": "GET /v1/handoff-dossier/au",
            "launch_status": "GET /v1/launch-status/au",
            "launch_remediation_plan": "GET /v1/launch-remediation-plan/au",
            "customer_handoff_readiness": "GET /v1/customer-handoff-readiness/au",
            "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
        },
        "hard_gate_commands": hard_gate_commands,
        "evidence_sources": [
            _source_file_entry("handoff_dossier", handoff_dossier_path),
            _source_file_entry("external_dependency_handoff", external_dependency_handoff_path),
        ],
    }
    payload["next_work_item_packet_hash"] = compute_next_work_item_packet_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU next work item packet JSON")
    parser.add_argument(
        "--handoff-dossier-path",
        default=os.environ.get("GENO_AU_HANDOFF_DOSSIER_OUTPUT_PATH", DEFAULT_HANDOFF_DOSSIER_PATH),
        help="Path to the AU handoff dossier JSON.",
    )
    parser.add_argument(
        "--external-dependency-handoff-path",
        default=os.environ.get(
            "GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH",
            DEFAULT_EXTERNAL_DEPENDENCY_HANDOFF_PATH,
        ),
        help="Path to the AU external dependency handoff JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_NEXT_WORK_ITEM_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU next work item packet JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_next_work_item_packet(
        handoff_dossier_path=Path(args.handoff_dossier_path),
        external_dependency_handoff_path=Path(args.external_dependency_handoff_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
