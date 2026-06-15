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

from scripts.build_au_customer_handoff_readiness import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_CUSTOMER_HANDOFF_READINESS_PATH,
    build_au_customer_handoff_readiness,
)
from scripts.build_au_external_dependency_handoff import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_EXTERNAL_DEPENDENCY_HANDOFF_PATH,
    build_au_external_dependency_handoff,
)
from scripts.build_au_handoff_dossier import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_HANDOFF_DOSSIER_PATH,
    build_au_handoff_dossier,
)
from scripts.build_au_launch_status import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_LAUNCH_STATUS_PATH,
    build_au_launch_status,
)
from scripts.build_au_next_work_item_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_NEXT_WORK_ITEM_PATH,
    build_au_next_work_item_packet,
)
from scripts.build_au_p0a_credential_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_CREDENTIAL_CLEARANCE_PATH,
    build_au_p0a_credential_clearance,
)
from scripts.build_au_p0a_real_batch_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_REAL_BATCH_CLEARANCE_PATH,
    build_au_p0a_real_batch_clearance,
)
from scripts.run_au_external_dependency_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH,
    run_au_external_dependency_clearance,
)
from scripts.verify_au_customer_handoff_readiness import verify_au_customer_handoff_readiness  # noqa: E402
from scripts.verify_au_external_dependency_clearance import verify_au_external_dependency_clearance  # noqa: E402
from scripts.verify_au_external_dependency_handoff import verify_au_external_dependency_handoff  # noqa: E402
from scripts.verify_au_handoff_dossier import verify_au_handoff_dossier  # noqa: E402
from scripts.verify_au_launch_status import verify_au_launch_status  # noqa: E402
from scripts.verify_au_next_work_item_packet import verify_au_next_work_item_packet  # noqa: E402
from scripts.verify_au_p0a_credential_clearance import verify_au_p0a_credential_clearance  # noqa: E402
from scripts.verify_au_p0a_real_batch_clearance import verify_au_p0a_real_batch_clearance  # noqa: E402


PROGRESS_VERSION = "au_delivery_progress_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-delivery-progress-latest.json"

PROGRESS_GATES: tuple[tuple[str, str, str], ...] = (
    ("launch_status_structural", "Launch status structural gate", "launch_status"),
    ("handoff_dossier_structural", "Handoff dossier structural gate", "handoff_dossier"),
    ("customer_readiness_artifact", "Customer readiness artifact gate", "customer_handoff_readiness"),
    ("next_work_item_artifact", "Next work item artifact gate", "next_work_item"),
    ("external_dependency_handoff_structural", "External dependency handoff structural gate", "external_dependency_handoff"),
    ("external_dependency_clearance_dry_run", "External dependency clearance dry-run gate", "external_dependency_clearance"),
    ("p0a_credentials_fulfilled", "P0a credentials fulfilled gate", "customer_handoff_readiness"),
    ("p0a_real_batches_fulfilled", "P0a real batches fulfilled gate", "customer_handoff_readiness"),
    ("p0b_google_environment_fulfilled", "P0b Google environment fulfilled gate", "customer_handoff_readiness"),
    ("p0b_google_manual_backfill_fulfilled", "P0b Google manual backfill fulfilled gate", "customer_handoff_readiness"),
    ("p0b_google_phase_execution_fulfilled", "P0b Google phase execution fulfilled gate", "customer_handoff_readiness"),
    ("external_dependencies_clear", "External dependencies clear gate", "external_dependency_handoff"),
    ("customer_report_handoff_ready", "Customer report handoff ready gate", "customer_handoff_readiness"),
)

CUSTOMER_GATE_TO_PROGRESS_GATE = {
    "p0a_credentials_configured": "p0a_credentials_fulfilled",
    "p0a_real_batches_ready": "p0a_real_batches_fulfilled",
    "p0a_design_partner_data_ready": "p0a_real_batches_fulfilled",
    "p0b_google_environment_ready": "p0b_google_environment_fulfilled",
    "p0b_google_manual_backfill_ready": "p0b_google_manual_backfill_fulfilled",
    "p0b_google_phase_execution_ready": "p0b_google_phase_execution_fulfilled",
    "p0b_google_main_scoring_ready": "p0b_google_phase_execution_fulfilled",
    "external_dependencies_clear": "external_dependencies_clear",
    "customer_report_handoff_gate": "customer_report_handoff_ready",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_delivery_progress_hash(progress: dict[str, Any]) -> str:
    payload = dict(progress)
    payload.pop("delivery_progress_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


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


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _load_or_build(path: Path, builder: Any, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = builder(generated_at=generated_at)
        return payload, {"path": str(path), "exists": False, "source": "generated_in_memory", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        payload = builder(generated_at=generated_at)
        return payload, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if isinstance(payload, dict):
        return payload, {"path": str(path), "exists": True, "source": "existing_file"}
    payload = builder(generated_at=generated_at)
    return payload, {"path": str(path), "exists": True, "source": "generated_in_memory", "errors": ["not_json_object"]}


def _load_or_build_p0a_credential_clearance(
    path: Path,
    *,
    external_dependency_clearance_path: Path,
    external_dependency_clearance: dict[str, Any],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_or_build(
        path,
        lambda generated_at=None: build_au_p0a_credential_clearance(
            external_dependency_clearance_path=external_dependency_clearance_path,
            external_dependency_clearance=external_dependency_clearance,
            output_path=path,
            generated_at=generated_at,
        ),
        generated_at=generated_at,
    )
    payload_clearance_hash = str(
        _as_dict(_as_dict(payload.get("source_artifacts")).get("external_dependency_clearance")).get("hash") or ""
    )
    current_clearance_hash = str(external_dependency_clearance.get("clearance_execution_hash") or "")
    if payload_clearance_hash == current_clearance_hash:
        return payload, source
    refreshed = build_au_p0a_credential_clearance(
        external_dependency_clearance_path=external_dependency_clearance_path,
        external_dependency_clearance=external_dependency_clearance,
        output_path=path,
        generated_at=generated_at,
    )
    return refreshed, {**source, "source": "generated_in_memory", "errors": ["source_clearance_hash_stale"]}


def _load_or_build_p0a_real_batch_clearance(
    path: Path,
    *,
    external_dependency_clearance_path: Path,
    external_dependency_clearance: dict[str, Any],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_or_build(
        path,
        lambda generated_at=None: build_au_p0a_real_batch_clearance(
            external_dependency_clearance_path=external_dependency_clearance_path,
            external_dependency_clearance=external_dependency_clearance,
            output_path=path,
            generated_at=generated_at,
        ),
        generated_at=generated_at,
    )
    payload_clearance_hash = str(
        _as_dict(_as_dict(payload.get("source_artifacts")).get("external_dependency_clearance")).get("hash") or ""
    )
    current_clearance_hash = str(external_dependency_clearance.get("clearance_execution_hash") or "")
    if payload_clearance_hash == current_clearance_hash:
        return payload, source
    refreshed = build_au_p0a_real_batch_clearance(
        external_dependency_clearance_path=external_dependency_clearance_path,
        external_dependency_clearance=external_dependency_clearance,
        output_path=path,
        generated_at=generated_at,
    )
    return refreshed, {**source, "source": "generated_in_memory", "errors": ["source_clearance_hash_stale"]}


def _percent(ready_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return round((ready_count / total_count) * 100, 1)


def _customer_gate_lookup(readiness: dict[str, Any]) -> dict[str, dict[str, Any]]:
    audit = _as_dict(readiness.get("readiness_audit"))
    return {str(gate.get("id") or ""): _as_dict(gate) for gate in _as_list(audit.get("customer_gates"))}


def _structural_progress_gates(
    *,
    launch_verifier: dict[str, Any],
    handoff_verifier: dict[str, Any],
    readiness_verifier: dict[str, Any],
    next_work_item_verifier: dict[str, Any],
    dependency_handoff_verifier: dict[str, Any],
    clearance_verifier: dict[str, Any],
    customer_gate_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    structural_ready = {
        "launch_status_structural": launch_verifier.get("hash_valid") is True,
        "handoff_dossier_structural": handoff_verifier.get("status") == "pass",
        "customer_readiness_artifact": readiness_verifier.get("status") == "pass",
        "next_work_item_artifact": next_work_item_verifier.get("status") == "pass",
        "external_dependency_handoff_structural": dependency_handoff_verifier.get("status") == "pass",
        "external_dependency_clearance_dry_run": clearance_verifier.get("status") == "pass",
    }
    gates: list[dict[str, Any]] = []
    for gate_id, label, source in PROGRESS_GATES:
        customer_gate_ids = [
            customer_gate_id
            for customer_gate_id, progress_gate_id in CUSTOMER_GATE_TO_PROGRESS_GATE.items()
            if progress_gate_id == gate_id
        ]
        if gate_id in structural_ready:
            ready = structural_ready[gate_id]
            evidence_ref = source
            blocking_reasons: list[str] = [] if ready else [f"{source}_not_ready"]
        else:
            related_customer_gates = [customer_gate_lookup.get(customer_gate_id, {}) for customer_gate_id in customer_gate_ids]
            ready = bool(related_customer_gates) and all(gate.get("ready") is True for gate in related_customer_gates)
            evidence_ref = ",".join(customer_gate_ids) if customer_gate_ids else source
            blocking_reasons = [
                str(gate.get("id") or "")
                for gate in related_customer_gates
                if gate.get("ready") is not True and gate.get("id")
            ]
        gates.append(
            {
                "id": gate_id,
                "label": label,
                "ready": ready,
                "status": "pass" if ready else "blocked",
                "source": source,
                "evidence_ref": evidence_ref,
                "customer_gate_ids": customer_gate_ids,
                "blocking_reasons": blocking_reasons,
            }
        )
    return gates


def _append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def build_au_delivery_progress(
    *,
    launch_status_path: Path = Path(DEFAULT_LAUNCH_STATUS_PATH),
    handoff_dossier_path: Path = Path(DEFAULT_HANDOFF_DOSSIER_PATH),
    customer_handoff_readiness_path: Path = Path(DEFAULT_CUSTOMER_HANDOFF_READINESS_PATH),
    next_work_item_path: Path = Path(DEFAULT_NEXT_WORK_ITEM_PATH),
    external_dependency_handoff_path: Path = Path(DEFAULT_EXTERNAL_DEPENDENCY_HANDOFF_PATH),
    external_dependency_clearance_path: Path = Path(DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH),
    p0a_credential_clearance_path: Path = Path(DEFAULT_P0A_CREDENTIAL_CLEARANCE_PATH),
    p0a_real_batch_clearance_path: Path = Path(DEFAULT_P0A_REAL_BATCH_CLEARANCE_PATH),
    launch_status: dict[str, Any] | None = None,
    handoff_dossier: dict[str, Any] | None = None,
    customer_handoff_readiness: dict[str, Any] | None = None,
    next_work_item: dict[str, Any] | None = None,
    external_dependency_handoff: dict[str, Any] | None = None,
    external_dependency_clearance: dict[str, Any] | None = None,
    p0a_credential_clearance: dict[str, Any] | None = None,
    p0a_real_batch_clearance: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if launch_status is None:
        launch_status, launch_source = _load_or_build(
            launch_status_path,
            lambda generated_at=None: build_au_launch_status(output_path=launch_status_path, generated_at=generated_at),
            generated_at=generated_at,
        )
    else:
        launch_source = {"path": str(launch_status_path), "exists": True, "source": "provided_payload"}
    if handoff_dossier is None:
        handoff_dossier, handoff_source = _load_or_build(
            handoff_dossier_path,
            lambda generated_at=None: build_au_handoff_dossier(output_path=handoff_dossier_path, generated_at=generated_at),
            generated_at=generated_at,
        )
    else:
        handoff_source = {"path": str(handoff_dossier_path), "exists": True, "source": "provided_payload"}
    if customer_handoff_readiness is None:
        customer_handoff_readiness, readiness_source = _load_or_build(
            customer_handoff_readiness_path,
            lambda generated_at=None: build_au_customer_handoff_readiness(
                handoff_dossier_path=handoff_dossier_path,
                handoff_dossier=handoff_dossier,
                output_path=customer_handoff_readiness_path,
                generated_at=generated_at,
            ),
            generated_at=generated_at,
        )
    else:
        readiness_source = {"path": str(customer_handoff_readiness_path), "exists": True, "source": "provided_payload"}
    if external_dependency_handoff is None:
        external_dependency_handoff, dependency_handoff_source = _load_or_build(
            external_dependency_handoff_path,
            lambda generated_at=None: build_au_external_dependency_handoff(
                output_path=external_dependency_handoff_path,
                generated_at=generated_at,
            ),
            generated_at=generated_at,
        )
    else:
        dependency_handoff_source = {
            "path": str(external_dependency_handoff_path),
            "exists": True,
            "source": "provided_payload",
        }
    if next_work_item is None:
        next_work_item, next_work_item_source = _load_or_build(
            next_work_item_path,
            lambda generated_at=None: build_au_next_work_item_packet(
                handoff_dossier_path=handoff_dossier_path,
                external_dependency_handoff_path=external_dependency_handoff_path,
                handoff_dossier=handoff_dossier,
                external_dependency_handoff=external_dependency_handoff,
                output_path=next_work_item_path,
                generated_at=generated_at,
            ),
            generated_at=generated_at,
        )
    else:
        next_work_item_source = {"path": str(next_work_item_path), "exists": True, "source": "provided_payload"}
    if external_dependency_clearance is None:
        external_dependency_clearance, clearance_source = _load_or_build(
            external_dependency_clearance_path,
            lambda generated_at=None: run_au_external_dependency_clearance(
                handoff_path=external_dependency_handoff_path,
                handoff=external_dependency_handoff,
                output_path=external_dependency_clearance_path,
                generated_at=generated_at,
            ),
            generated_at=generated_at,
        )
    else:
        clearance_source = {
            "path": str(external_dependency_clearance_path),
            "exists": True,
            "source": "provided_payload",
        }
    if p0a_credential_clearance is None:
        p0a_credential_clearance, p0a_credential_clearance_source = _load_or_build_p0a_credential_clearance(
            p0a_credential_clearance_path,
            external_dependency_clearance_path=external_dependency_clearance_path,
            external_dependency_clearance=external_dependency_clearance,
            generated_at=generated_at,
        )
    else:
        p0a_credential_clearance_source = {
            "path": str(p0a_credential_clearance_path),
            "exists": True,
            "source": "provided_payload",
        }
    if p0a_real_batch_clearance is None:
        p0a_real_batch_clearance, p0a_real_batch_clearance_source = _load_or_build_p0a_real_batch_clearance(
            p0a_real_batch_clearance_path,
            external_dependency_clearance_path=external_dependency_clearance_path,
            external_dependency_clearance=external_dependency_clearance,
            generated_at=generated_at,
        )
    else:
        p0a_real_batch_clearance_source = {
            "path": str(p0a_real_batch_clearance_path),
            "exists": True,
            "source": "provided_payload",
        }

    launch_verifier = verify_au_launch_status(launch_status)
    handoff_verifier = verify_au_handoff_dossier(handoff_dossier, path=handoff_dossier_path)
    readiness_verifier = verify_au_customer_handoff_readiness(customer_handoff_readiness, path=customer_handoff_readiness_path)
    next_work_item_verifier = verify_au_next_work_item_packet(next_work_item, path=next_work_item_path)
    dependency_handoff_verifier = verify_au_external_dependency_handoff(
        external_dependency_handoff,
        path=external_dependency_handoff_path,
    )
    clearance_verifier = verify_au_external_dependency_clearance(
        external_dependency_clearance,
        path=external_dependency_clearance_path,
    )
    p0a_credential_clearance_verifier = verify_au_p0a_credential_clearance(
        p0a_credential_clearance,
        path=p0a_credential_clearance_path,
    )
    p0a_real_batch_clearance_verifier = verify_au_p0a_real_batch_clearance(
        p0a_real_batch_clearance,
        path=p0a_real_batch_clearance_path,
    )

    readiness_summary = _as_dict(customer_handoff_readiness.get("summary"))
    next_work_item_summary = _as_dict(next_work_item.get("summary"))
    dependency_summary = _as_dict(external_dependency_handoff.get("summary"))
    customer_gate_lookup = _customer_gate_lookup(customer_handoff_readiness)
    progress_gates = _structural_progress_gates(
        launch_verifier=launch_verifier,
        handoff_verifier=handoff_verifier,
        readiness_verifier=readiness_verifier,
        next_work_item_verifier=next_work_item_verifier,
        dependency_handoff_verifier=dependency_handoff_verifier,
        clearance_verifier=clearance_verifier,
        customer_gate_lookup=customer_gate_lookup,
    )
    ready_progress_gate_count = len([gate for gate in progress_gates if gate["ready"] is True])
    blocked_progress_gates = [gate for gate in progress_gates if gate["ready"] is not True]
    hard_gate_commands = [
        "make au-delivery-progress",
        "make verify-au-delivery-progress",
        "make au-customer-handoff-readiness",
        "make verify-au-customer-handoff-readiness",
        "make au-next-work-item",
        "make verify-au-next-work-item",
        "make au-external-dependency-handoff",
        "make verify-au-external-dependency-handoff",
        "make au-external-dependency-clearance",
        "make verify-au-external-dependency-clearance",
    ]
    for command in _as_list(customer_handoff_readiness.get("hard_gate_commands")):
        _append_unique(hard_gate_commands, str(command))
    for command in _as_list(next_work_item.get("hard_gate_commands")):
        _append_unique(hard_gate_commands, str(command))
    if isinstance(external_dependency_handoff.get("hard_gate_commands"), list):
        for command in _as_list(external_dependency_handoff.get("hard_gate_commands")):
            _append_unique(hard_gate_commands, str(command))
    for command in _as_list(p0a_credential_clearance.get("hard_gate_commands")):
        _append_unique(hard_gate_commands, str(command))
    for command in _as_list(p0a_real_batch_clearance.get("hard_gate_commands")):
        _append_unique(hard_gate_commands, str(command))

    next_command = str(
        external_dependency_clearance.get("next_command")
        or next_work_item_summary.get("linked_dependency_group_next_command")
        or readiness_summary.get("next_action")
        or launch_status.get("next_action")
        or ""
    )
    payload: dict[str, Any] = {
        "delivery_progress_version": PROGRESS_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass"
        if all(
            verifier.get("status") == "pass"
            for verifier in (
                handoff_verifier,
                readiness_verifier,
                next_work_item_verifier,
                dependency_handoff_verifier,
                clearance_verifier,
                p0a_credential_clearance_verifier,
                p0a_real_batch_clearance_verifier,
            )
        )
        and launch_verifier.get("hash_valid") is True
        else "fail",
        "delivery_progress_ready": True,
        "ready_for_customer_report_handoff": customer_handoff_readiness.get("ready_for_customer_report_handoff") is True,
        "output_path": str(output_path) if output_path else "",
        "summary": {
            "engineering_progress_percent": _percent(ready_progress_gate_count, len(progress_gates)),
            "customer_report_handoff_readiness_percent": readiness_summary.get(
                "customer_report_handoff_readiness_percent",
                0.0,
            ),
            "structural_auditability_percent": readiness_summary.get("structural_auditability_percent", 0.0),
            "ready_progress_gate_count": ready_progress_gate_count,
            "total_progress_gate_count": len(progress_gates),
            "blocked_progress_gate_count": len(blocked_progress_gates),
            "blocked_progress_gate_ids": [str(gate["id"]) for gate in blocked_progress_gates],
            "blocked_customer_gate_count": readiness_summary.get("blocked_customer_gate_count", 0),
            "blocked_customer_gate_ids": readiness_summary.get("blocked_customer_gate_ids", []),
            "remaining_blocker_count": readiness_summary.get(
                "remaining_blocker_count",
                launch_verifier.get("remaining_blocker_count", 0),
            ),
            "external_dependency_blocker_count": readiness_summary.get(
                "external_dependency_blocker_count",
                dependency_summary.get("external_dependency_blocker_count", 0),
            ),
            "next_action": launch_status.get("next_action") or readiness_summary.get("next_action", ""),
            "next_work_item_id": next_work_item_summary.get("next_work_item_id", ""),
            "next_work_item_title": next_work_item_summary.get("title", ""),
            "next_work_item_stage": next_work_item_summary.get("stage", ""),
            "next_command": next_command,
            "current_clearance_step_id": external_dependency_clearance.get("current_step_id", ""),
            "would_execute_step_count": external_dependency_clearance.get("would_execute_step_count", 0),
            "external_dependency_handoff_ready": external_dependency_handoff.get("external_dependency_handoff_ready") is True,
            "handoff_posture": dependency_summary.get("handoff_posture", ""),
            "launch_status_hash": launch_status.get("launch_status_hash", ""),
            "handoff_dossier_hash": handoff_dossier.get("handoff_dossier_hash", ""),
            "customer_handoff_readiness_hash": customer_handoff_readiness.get("customer_handoff_readiness_hash", ""),
            "next_work_item_packet_hash": next_work_item.get("next_work_item_packet_hash", ""),
            "external_dependency_handoff_hash": external_dependency_handoff.get("external_dependency_handoff_hash", ""),
            "clearance_execution_hash": external_dependency_clearance.get("clearance_execution_hash", ""),
            "p0a_credential_clearance_hash": p0a_credential_clearance.get("p0a_credential_clearance_hash", ""),
            "p0a_credential_clearance_ready": p0a_credential_clearance.get("credential_clearance_ready") is True,
            "p0a_credentials_fulfilled": p0a_credential_clearance.get("credentials_fulfilled") is True,
            "p0a_credential_missing_required_count": _as_dict(p0a_credential_clearance.get("summary")).get(
                "missing_required_count",
                0,
            ),
            "p0a_credential_missing_required": _as_dict(p0a_credential_clearance.get("summary")).get(
                "missing_required",
                [],
            ),
            "p0a_real_batch_clearance_hash": p0a_real_batch_clearance.get("p0a_real_batch_clearance_hash", ""),
            "p0a_real_batch_clearance_ready": p0a_real_batch_clearance.get("real_batch_clearance_ready") is True,
            "p0a_real_batches_fulfilled": p0a_real_batch_clearance.get("real_batches_fulfilled") is True,
            "p0a_real_batch_blocked_by_prerequisite": p0a_real_batch_clearance.get("blocked_by_prerequisite_step")
            is True,
            "p0a_real_batch_missing_required_count": _as_dict(p0a_real_batch_clearance.get("summary")).get(
                "missing_required_count",
                0,
            ),
            "p0a_real_batch_missing_required": _as_dict(p0a_real_batch_clearance.get("summary")).get(
                "missing_required",
                [],
            ),
            "p0a_real_batch_next_phase": _as_dict(p0a_real_batch_clearance.get("summary")).get("next_phase", ""),
        },
        "progress_gates": progress_gates,
        "source_artifacts": {
            "launch_status": {
                "path": str(launch_status_path),
                "source": launch_source,
                "hash_field": "launch_status_hash",
                "hash": launch_status.get("launch_status_hash", ""),
                "verifier_status": launch_verifier.get("status", ""),
                "hash_valid": launch_verifier.get("hash_valid") is True,
            },
            "handoff_dossier": {
                "path": str(handoff_dossier_path),
                "source": handoff_source,
                "hash_field": "handoff_dossier_hash",
                "hash": handoff_dossier.get("handoff_dossier_hash", ""),
                "verifier_status": handoff_verifier.get("status", ""),
                "hash_valid": handoff_verifier.get("hash_valid") is True,
            },
            "customer_handoff_readiness": {
                "path": str(customer_handoff_readiness_path),
                "source": readiness_source,
                "hash_field": "customer_handoff_readiness_hash",
                "hash": customer_handoff_readiness.get("customer_handoff_readiness_hash", ""),
                "verifier_status": readiness_verifier.get("status", ""),
                "hash_valid": readiness_verifier.get("hash_valid") is True,
            },
            "next_work_item": {
                "path": str(next_work_item_path),
                "source": next_work_item_source,
                "hash_field": "next_work_item_packet_hash",
                "hash": next_work_item.get("next_work_item_packet_hash", ""),
                "verifier_status": next_work_item_verifier.get("status", ""),
                "hash_valid": next_work_item_verifier.get("hash_valid") is True,
            },
            "external_dependency_handoff": {
                "path": str(external_dependency_handoff_path),
                "source": dependency_handoff_source,
                "hash_field": "external_dependency_handoff_hash",
                "hash": external_dependency_handoff.get("external_dependency_handoff_hash", ""),
                "verifier_status": dependency_handoff_verifier.get("status", ""),
                "hash_valid": dependency_handoff_verifier.get("hash_valid") is True,
            },
            "external_dependency_clearance": {
                "path": str(external_dependency_clearance_path),
                "source": clearance_source,
                "hash_field": "clearance_execution_hash",
                "hash": external_dependency_clearance.get("clearance_execution_hash", ""),
                "verifier_status": clearance_verifier.get("status", ""),
                "hash_valid": clearance_verifier.get("hash_valid") is True,
            },
            "p0a_credential_clearance": {
                "path": str(p0a_credential_clearance_path),
                "source": p0a_credential_clearance_source,
                "hash_field": "p0a_credential_clearance_hash",
                "hash": p0a_credential_clearance.get("p0a_credential_clearance_hash", ""),
                "verifier_status": p0a_credential_clearance_verifier.get("status", ""),
                "hash_valid": p0a_credential_clearance_verifier.get("hash_valid") is True,
            },
            "p0a_real_batch_clearance": {
                "path": str(p0a_real_batch_clearance_path),
                "source": p0a_real_batch_clearance_source,
                "hash_field": "p0a_real_batch_clearance_hash",
                "hash": p0a_real_batch_clearance.get("p0a_real_batch_clearance_hash", ""),
                "verifier_status": p0a_real_batch_clearance_verifier.get("status", ""),
                "hash_valid": p0a_real_batch_clearance_verifier.get("hash_valid") is True,
            },
        },
        "verifiers": {
            "launch_status": launch_verifier,
            "handoff_dossier": handoff_verifier,
            "customer_handoff_readiness": readiness_verifier,
            "next_work_item": next_work_item_verifier,
            "external_dependency_handoff": dependency_handoff_verifier,
            "external_dependency_clearance": clearance_verifier,
            "p0a_credential_clearance": p0a_credential_clearance_verifier,
            "p0a_real_batch_clearance": p0a_real_batch_clearance_verifier,
        },
        "runtime_endpoints": {
            "delivery_progress": "GET /v1/delivery-progress/au",
            "launch_status": "GET /v1/launch-status/au",
            "handoff_dossier": "GET /v1/handoff-dossier/au",
            "customer_handoff_readiness": "GET /v1/customer-handoff-readiness/au",
            "next_work_item": "GET /v1/next-work-item/au",
            "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
            "p0a_credential_clearance": "GET /v1/p0a-credential-clearance/au",
            "p0a_real_batch_clearance": "GET /v1/p0a-real-batch-clearance/au",
        },
        "hard_gate_commands": hard_gate_commands,
        "evidence_sources": [
            _source_file_entry("launch_status", launch_status_path),
            _source_file_entry("handoff_dossier", handoff_dossier_path),
            _source_file_entry("customer_handoff_readiness", customer_handoff_readiness_path),
            _source_file_entry("next_work_item", next_work_item_path),
            _source_file_entry("external_dependency_handoff", external_dependency_handoff_path),
            _source_file_entry("external_dependency_clearance", external_dependency_clearance_path),
            _source_file_entry("p0a_credential_clearance", p0a_credential_clearance_path),
            _source_file_entry("p0a_real_batch_clearance", p0a_real_batch_clearance_path),
        ],
    }
    payload["delivery_progress_hash"] = compute_delivery_progress_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU delivery progress JSON")
    parser.add_argument(
        "--launch-status-path",
        default=os.environ.get("GENO_AU_LAUNCH_STATUS_OUTPUT_PATH", DEFAULT_LAUNCH_STATUS_PATH),
        help="Path to the AU launch status JSON.",
    )
    parser.add_argument(
        "--handoff-dossier-path",
        default=os.environ.get("GENO_AU_HANDOFF_DOSSIER_OUTPUT_PATH", DEFAULT_HANDOFF_DOSSIER_PATH),
        help="Path to the AU handoff dossier JSON.",
    )
    parser.add_argument(
        "--customer-handoff-readiness-path",
        default=os.environ.get(
            "GENO_AU_CUSTOMER_HANDOFF_READINESS_OUTPUT_PATH",
            DEFAULT_CUSTOMER_HANDOFF_READINESS_PATH,
        ),
        help="Path to the AU customer handoff readiness JSON.",
    )
    parser.add_argument(
        "--next-work-item-path",
        default=os.environ.get("GENO_AU_NEXT_WORK_ITEM_OUTPUT_PATH", DEFAULT_NEXT_WORK_ITEM_PATH),
        help="Path to the AU next work item JSON.",
    )
    parser.add_argument(
        "--external-dependency-handoff-path",
        default=os.environ.get("GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH", DEFAULT_EXTERNAL_DEPENDENCY_HANDOFF_PATH),
        help="Path to the AU external dependency handoff JSON.",
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
        "--p0a-credential-clearance-path",
        default=os.environ.get("GENO_AU_P0A_CREDENTIAL_CLEARANCE_OUTPUT_PATH", DEFAULT_P0A_CREDENTIAL_CLEARANCE_PATH),
        help="Path to the AU P0a credential clearance JSON.",
    )
    parser.add_argument(
        "--p0a-real-batch-clearance-path",
        default=os.environ.get("GENO_AU_P0A_REAL_BATCH_CLEARANCE_OUTPUT_PATH", DEFAULT_P0A_REAL_BATCH_CLEARANCE_PATH),
        help="Path to the AU P0a real batch clearance JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_DELIVERY_PROGRESS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU delivery progress JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_delivery_progress(
        launch_status_path=Path(args.launch_status_path),
        handoff_dossier_path=Path(args.handoff_dossier_path),
        customer_handoff_readiness_path=Path(args.customer_handoff_readiness_path),
        next_work_item_path=Path(args.next_work_item_path),
        external_dependency_handoff_path=Path(args.external_dependency_handoff_path),
        external_dependency_clearance_path=Path(args.external_dependency_clearance_path),
        p0a_credential_clearance_path=Path(args.p0a_credential_clearance_path),
        p0a_real_batch_clearance_path=Path(args.p0a_real_batch_clearance_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
