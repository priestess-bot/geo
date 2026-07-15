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
from scripts.build_au_delivery_progress import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_DELIVERY_PROGRESS_PATH,
    build_au_delivery_progress,
)
from scripts.build_au_external_dependency_handoff import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_EXTERNAL_DEPENDENCY_HANDOFF_PATH,
    build_au_external_dependency_handoff,
)
from scripts.build_au_handoff_dossier import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_HANDOFF_DOSSIER_PATH,
    build_au_handoff_dossier,
)
from scripts.build_au_p0a_credential_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_CREDENTIAL_CLEARANCE_PATH,
    build_au_p0a_credential_clearance,
)
from scripts.build_au_p0a_credential_update_receipt import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_CREDENTIAL_UPDATE_RECEIPT_PATH,
    build_au_p0a_credential_update_receipt,
)
from scripts.build_au_p0a_real_batch_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_REAL_BATCH_CLEARANCE_PATH,
    build_au_p0a_real_batch_clearance,
)
from scripts.build_au_p0b_google_environment_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_PATH,
    build_au_p0b_google_environment_clearance,
)
from scripts.build_au_p0b_google_manual_backfill_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_MANUAL_BACKFILL_CLEARANCE_PATH,
    build_au_p0b_google_manual_backfill_clearance,
)
from scripts.build_au_p0b_google_phase_execution_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_PATH,
    build_au_p0b_google_phase_execution_clearance,
)
from scripts.run_au_external_dependency_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH,
    run_au_external_dependency_clearance,
)
from scripts.verify_au_customer_handoff_readiness import verify_au_customer_handoff_readiness  # noqa: E402
from scripts.verify_au_delivery_progress import verify_au_delivery_progress  # noqa: E402
from scripts.verify_au_external_dependency_clearance import verify_au_external_dependency_clearance  # noqa: E402
from scripts.verify_au_external_dependency_handoff import verify_au_external_dependency_handoff  # noqa: E402
from scripts.verify_au_handoff_dossier import verify_au_handoff_dossier  # noqa: E402
from scripts.verify_au_p0a_credential_clearance import verify_au_p0a_credential_clearance  # noqa: E402
from scripts.verify_au_p0a_credential_update_receipt import verify_au_p0a_credential_update_receipt  # noqa: E402
from scripts.verify_au_p0a_real_batch_clearance import verify_au_p0a_real_batch_clearance  # noqa: E402
from scripts.verify_au_p0b_google_environment_clearance import (  # noqa: E402
    verify_au_p0b_google_environment_clearance,
)
from scripts.verify_au_p0b_google_manual_backfill_clearance import (  # noqa: E402
    verify_au_p0b_google_manual_backfill_clearance,
)
from scripts.verify_au_p0b_google_phase_execution_clearance import (  # noqa: E402
    verify_au_p0b_google_phase_execution_clearance,
)


CLEARANCE_VERSION = "au_customer_handoff_clearance_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-customer-handoff-clearance-latest.json"
STEP_ID = "customer_report_handoff_gate"
PREREQUISITE_STEP_IDS = ("p0a_real_batches", "p0b_google_phase_execution")

EXPECTED_CUSTOMER_GATE_ORDER = (
    "p0a_credentials_configured",
    "p0a_real_batches_ready",
    "p0a_design_partner_data_ready",
    "p0b_google_environment_ready",
    "p0b_google_manual_backfill_ready",
    "p0b_google_phase_execution_ready",
    "p0b_google_main_scoring_ready",
    "p0c_report_contract_ready",
    "external_dependencies_clear",
    STEP_ID,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_customer_handoff_clearance_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("customer_handoff_clearance_hash", None)
    return hashlib.sha256(_stable_bytes(payload_for_hash)).hexdigest()


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


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _unique_strings(values: list[str]) -> list[str]:
    observed: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in observed:
            observed.add(value)
            result.append(value)
    return result


def _path_for_current_file_check(source: dict[str, Any], path: Path) -> Path | None:
    if source.get("source") == "existing_file":
        return path
    return None


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


def _load_or_build_handoff_dossier(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    dossier = build_au_handoff_dossier(output_path=path, generated_at=generated_at)
    return dossier, {**source, "source": "generated_in_memory"}


def _load_or_build_customer_readiness(
    path: Path,
    *,
    handoff_dossier_path: Path,
    handoff_dossier: dict[str, Any],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    readiness = build_au_customer_handoff_readiness(
        handoff_dossier_path=handoff_dossier_path,
        handoff_dossier=handoff_dossier,
        output_path=path,
        generated_at=generated_at,
    )
    return readiness, {**source, "source": "generated_in_memory"}


def _load_or_build_external_handoff(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    handoff = build_au_external_dependency_handoff(output_path=path, generated_at=generated_at)
    return handoff, {**source, "source": "generated_in_memory"}


def _load_or_build_external_clearance(
    path: Path,
    *,
    external_dependency_handoff_path: Path,
    external_dependency_handoff: dict[str, Any],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    clearance = run_au_external_dependency_clearance(
        handoff_path=external_dependency_handoff_path,
        handoff=external_dependency_handoff,
        output_path=path,
        generated_at=generated_at,
    )
    return clearance, {**source, "source": "generated_in_memory"}


def _load_or_build_delivery_progress(
    path: Path,
    *,
    handoff_dossier_path: Path,
    customer_handoff_readiness_path: Path,
    external_dependency_handoff_path: Path,
    external_dependency_clearance_path: Path,
    p0a_credential_clearance_path: Path,
    p0a_credential_update_receipt_path: Path,
    p0a_real_batch_clearance_path: Path,
    p0b_google_environment_clearance_path: Path,
    p0b_google_manual_backfill_clearance_path: Path,
    p0b_google_phase_execution_clearance_path: Path,
    handoff_dossier: dict[str, Any],
    customer_handoff_readiness: dict[str, Any],
    external_dependency_handoff: dict[str, Any],
    external_dependency_clearance: dict[str, Any],
    p0a_credential_clearance: dict[str, Any],
    p0a_credential_update_receipt: dict[str, Any],
    p0a_real_batch_clearance: dict[str, Any],
    p0b_google_environment_clearance: dict[str, Any],
    p0b_google_manual_backfill_clearance: dict[str, Any],
    p0b_google_phase_execution_clearance: dict[str, Any],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    progress = build_au_delivery_progress(
        handoff_dossier_path=handoff_dossier_path,
        customer_handoff_readiness_path=customer_handoff_readiness_path,
        external_dependency_handoff_path=external_dependency_handoff_path,
        external_dependency_clearance_path=external_dependency_clearance_path,
        p0a_credential_clearance_path=p0a_credential_clearance_path,
        p0a_credential_update_receipt_path=p0a_credential_update_receipt_path,
        p0a_real_batch_clearance_path=p0a_real_batch_clearance_path,
        p0b_google_environment_clearance_path=p0b_google_environment_clearance_path,
        p0b_google_manual_backfill_clearance_path=p0b_google_manual_backfill_clearance_path,
        p0b_google_phase_execution_clearance_path=p0b_google_phase_execution_clearance_path,
        handoff_dossier=handoff_dossier,
        customer_handoff_readiness=customer_handoff_readiness,
        external_dependency_handoff=external_dependency_handoff,
        external_dependency_clearance=external_dependency_clearance,
        p0a_credential_clearance=p0a_credential_clearance,
        p0a_credential_update_receipt=p0a_credential_update_receipt,
        p0a_real_batch_clearance=p0a_real_batch_clearance,
        p0b_google_environment_clearance=p0b_google_environment_clearance,
        p0b_google_manual_backfill_clearance=p0b_google_manual_backfill_clearance,
        p0b_google_phase_execution_clearance=p0b_google_phase_execution_clearance,
        output_path=path,
        generated_at=generated_at,
    )
    return progress, {**source, "source": "generated_in_memory"}


def _load_or_build_p0a_credential_clearance(
    path: Path,
    *,
    external_dependency_clearance_path: Path,
    external_dependency_clearance: dict[str, Any],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        payload_clearance_hash = str(
            _as_dict(_as_dict(payload.get("source_artifacts")).get("external_dependency_clearance")).get("hash") or ""
        )
        current_clearance_hash = str(external_dependency_clearance.get("clearance_execution_hash") or "")
        if payload_clearance_hash == current_clearance_hash:
            return payload, source
    clearance = build_au_p0a_credential_clearance(
        external_dependency_clearance_path=external_dependency_clearance_path,
        external_dependency_clearance=external_dependency_clearance,
        output_path=path,
        generated_at=generated_at,
    )
    return clearance, {**source, "source": "generated_in_memory"}


def _load_or_build_p0a_credential_update_receipt(
    path: Path,
    *,
    p0a_credential_clearance_path: Path,
    p0a_credential_clearance: dict[str, Any],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        payload_clearance_hash = str(
            _as_dict(_as_dict(payload.get("source_artifacts")).get("credential_clearance")).get("hash") or ""
        )
        current_clearance_hash = str(p0a_credential_clearance.get("p0a_credential_clearance_hash") or "")
        if payload_clearance_hash == current_clearance_hash:
            return payload, source
    receipt = build_au_p0a_credential_update_receipt(
        credential_clearance_path=p0a_credential_clearance_path,
        credential_clearance=p0a_credential_clearance,
        output_path=path,
        generated_at=generated_at,
    )
    return receipt, {**source, "source": "generated_in_memory"}


def _load_or_build_p0a_real_batch_clearance(
    path: Path,
    *,
    external_dependency_clearance_path: Path,
    external_dependency_clearance: dict[str, Any],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        payload_clearance_hash = str(
            _as_dict(_as_dict(payload.get("source_artifacts")).get("external_dependency_clearance")).get("hash") or ""
        )
        current_clearance_hash = str(external_dependency_clearance.get("clearance_execution_hash") or "")
        if payload_clearance_hash == current_clearance_hash:
            return payload, source
    clearance = build_au_p0a_real_batch_clearance(
        external_dependency_clearance_path=external_dependency_clearance_path,
        external_dependency_clearance=external_dependency_clearance,
        output_path=path,
        generated_at=generated_at,
    )
    return clearance, {**source, "source": "generated_in_memory"}


def _load_or_build_external_clearance_bound_packet(
    path: Path,
    *,
    external_dependency_clearance_path: Path,
    external_dependency_clearance: dict[str, Any],
    generated_at: str | None,
    builder: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        payload_clearance_hash = str(
            _as_dict(_as_dict(payload.get("source_artifacts")).get("external_dependency_clearance")).get("hash") or ""
        )
        current_clearance_hash = str(external_dependency_clearance.get("clearance_execution_hash") or "")
        if payload_clearance_hash == current_clearance_hash:
            return payload, source
    packet = builder(
        external_dependency_clearance_path=external_dependency_clearance_path,
        external_dependency_clearance=external_dependency_clearance,
        output_path=path,
        generated_at=generated_at,
    )
    return packet, {**source, "source": "generated_in_memory"}


def _step_by_id(external_clearance: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in _as_list(external_clearance.get("steps")):
        step_dict = _as_dict(step)
        if step_dict.get("id") == step_id:
            return step_dict
    return {}


def _customer_gate_items(customer_handoff_readiness: dict[str, Any]) -> list[dict[str, Any]]:
    audit = _as_dict(customer_handoff_readiness.get("readiness_audit"))
    items: list[dict[str, Any]] = []
    for value in _as_list(audit.get("customer_gates")):
        gate = _as_dict(value)
        gate_id = str(gate.get("id") or "")
        ready = gate.get("ready") is True
        items.append(
            {
                "key": f"customer_gate:{gate_id}",
                "gate_id": gate_id,
                "title": str(gate.get("label") or gate_id),
                "stage": str(gate.get("stage") or ""),
                "required": True,
                "fulfilled": ready,
                "ready": ready,
                "status": str(gate.get("status") or ("ready" if ready else "blocked")),
                "evidence_ref": str(gate.get("evidence_ref") or ""),
                "next_action": str(gate.get("next_action") or ""),
                "owner_hint": _owner_hint_for_gate(gate_id),
                "blocking_reasons": _strings(gate.get("blocked_by")),
            }
        )
    return items


def _owner_hint_for_gate(gate_id: str) -> str:
    if gate_id.startswith("p0a_"):
        return "p0a_operator"
    if gate_id.startswith("p0b_"):
        return "google_spike_operator"
    if gate_id.startswith("p0c_"):
        return "report_operator"
    if gate_id == "external_dependencies_clear":
        return "delivery_lead"
    if gate_id == STEP_ID:
        return "customer_delivery_owner"
    return "delivery_lead"


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
            f"{item.get('gate_id')}:{reason}"
            for item in items
            for reason in _strings(item.get("blocking_reasons"))
        )
    )


def _operator_steps(
    *,
    delivery_progress: dict[str, Any],
    external_dependency_clearance: dict[str, Any],
    blocked_by_prerequisite: bool,
) -> list[dict[str, Any]]:
    progress_summary = _as_dict(delivery_progress.get("summary"))
    steps: list[dict[str, Any]] = [
        {
            "order": 1,
            "id": "clear_p0a_provider_credentials",
            "command": "make au-p0a-credential-clearance && make verify-au-p0a-credential-clearance",
            "purpose": "clear_p0a_provider_credentials_before_customer_handoff",
            "external_call_risk": "none",
            "required_before_customer_handoff": True,
            "blocked": blocked_by_prerequisite,
        },
        {
            "order": 2,
            "id": "clear_p0a_real_batches",
            "command": "make au-p0a-real-batch-clearance && make verify-au-p0a-real-batch-clearance",
            "purpose": "clear_design_partner_batch_evidence_before_customer_handoff",
            "external_call_risk": "may_execute_collection_after_credentials_ready",
            "required_before_customer_handoff": True,
            "blocked": blocked_by_prerequisite,
        },
        {
            "order": 3,
            "id": "clear_p0b_google_environment",
            "command": "make au-p0b-google-environment-clearance && make verify-au-p0b-google-environment-clearance",
            "purpose": "clear_google_runtime_environment_before_customer_handoff",
            "external_call_risk": "none",
            "required_before_customer_handoff": True,
            "blocked": blocked_by_prerequisite,
        },
        {
            "order": 4,
            "id": "clear_p0b_google_manual_backfill",
            "command": "make au-p0b-google-manual-backfill-clearance && make verify-au-p0b-google-manual-backfill-clearance",
            "purpose": "clear_manual_google_backfill_evidence_before_customer_handoff",
            "external_call_risk": "manual_evidence_required",
            "required_before_customer_handoff": True,
            "blocked": blocked_by_prerequisite,
        },
        {
            "order": 5,
            "id": "clear_p0b_google_phase_execution",
            "command": "make au-p0b-google-phase-execution-clearance && make verify-au-p0b-google-phase-execution-clearance",
            "purpose": "clear_google_phase_execution_before_customer_handoff",
            "external_call_risk": "depends_on_google_phase_commands",
            "required_before_customer_handoff": True,
            "blocked": blocked_by_prerequisite,
        },
        {
            "order": 6,
            "id": "refresh_external_dependency_handoff",
            "command": "make au-external-dependency-handoff && make verify-au-external-dependency-handoff",
            "purpose": "refresh_external_dependency_boundary_after_clearance_steps",
            "external_call_risk": "none",
        },
        {
            "order": 7,
            "id": "refresh_external_dependency_clearance",
            "command": "make au-external-dependency-clearance && make verify-au-external-dependency-clearance",
            "purpose": "prove_final_customer_handoff_gate_is_current_or_still_blocked",
            "external_call_risk": "none",
        },
        {
            "order": 8,
            "id": "refresh_handoff_dossier",
            "command": "make au-handoff-dossier && make verify-au-handoff-dossier",
            "purpose": "refresh_customer_facing_dossier_after_dependency_clearance",
            "external_call_risk": "none",
        },
        {
            "order": 9,
            "id": "refresh_customer_handoff_readiness",
            "command": "make au-customer-handoff-readiness && make verify-au-customer-handoff-readiness",
            "purpose": "refresh_customer_report_handoff_readiness",
            "external_call_risk": "none",
        },
        {
            "order": 10,
            "id": "refresh_delivery_progress",
            "command": "make au-delivery-progress && make verify-au-delivery-progress",
            "purpose": "refresh_machine_readable_progress_percentages",
            "external_call_risk": "none",
        },
        {
            "order": 11,
            "id": "run_customer_ready_strict_gates",
            "command": (
                "PYTHONPATH=packages/geo_core:apps/api python3 "
                "scripts/verify_au_customer_handoff_clearance.py "
                "${GEO_AU_CUSTOMER_HANDOFF_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-clearance-latest.json} "
                "--require-cleared"
            ),
            "purpose": "require_final_customer_report_handoff_clearance",
            "external_call_risk": "none",
            "next_work_item_id": str(progress_summary.get("next_work_item_id") or ""),
        },
    ]
    if _strings(external_dependency_clearance.get("current_recommended_sequence")):
        steps[0]["current_global_clearance_sequence"] = _strings(
            external_dependency_clearance.get("current_recommended_sequence")
        )
    return steps


def _post_update_validation_sequence(
    *,
    customer_handoff_readiness: dict[str, Any],
    delivery_progress: dict[str, Any],
    external_dependency_handoff: dict[str, Any],
    external_dependency_clearance: dict[str, Any],
    p0a_credential_clearance: dict[str, Any],
    p0a_credential_update_receipt: dict[str, Any],
    p0a_real_batch_clearance: dict[str, Any],
    p0b_google_environment_clearance: dict[str, Any],
    p0b_google_manual_backfill_clearance: dict[str, Any],
    p0b_google_phase_execution_clearance: dict[str, Any],
    target_step: dict[str, Any],
) -> list[str]:
    commands = [
        "make au-p0a-credential-clearance",
        "make verify-au-p0a-credential-clearance",
        "make au-p0a-credential-update-receipt",
        "make verify-au-p0a-credential-update-receipt",
        "make au-p0a-real-batch-clearance",
        "make verify-au-p0a-real-batch-clearance",
        "make au-p0b-google-environment-clearance",
        "make verify-au-p0b-google-environment-clearance",
        "make au-p0b-google-manual-backfill-clearance",
        "make verify-au-p0b-google-manual-backfill-clearance",
        "make au-p0b-google-phase-execution-clearance",
        "make verify-au-p0b-google-phase-execution-clearance",
        "make au-customer-handoff-clearance",
        "make verify-au-customer-handoff-clearance",
        "make au-handoff-dossier",
        "make verify-au-handoff-dossier",
        "make au-customer-handoff-readiness",
        "make verify-au-customer-handoff-readiness",
        "make au-delivery-progress",
        "make verify-au-delivery-progress",
        "make au-external-dependency-handoff",
        "make verify-au-external-dependency-handoff",
        "make au-external-dependency-clearance",
        "make verify-au-external-dependency-clearance",
        "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_handoff_dossier.py "
        "${GEO_AU_HANDOFF_DOSSIER_OUTPUT_PATH:-docs/runtime_preflight/au-handoff-dossier-latest.json} "
        "--require-customer-ready",
        "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_customer_handoff_readiness.py "
        "${GEO_AU_CUSTOMER_HANDOFF_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-readiness-latest.json} "
        "--require-customer-ready",
        "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_delivery_progress.py "
        "${GEO_AU_DELIVERY_PROGRESS_OUTPUT_PATH:-docs/runtime_preflight/au-delivery-progress-latest.json} "
        "--require-customer-ready",
        "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_external_dependency_handoff.py "
        "${GEO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH:-docs/runtime_preflight/au-external-dependency-handoff-latest.json} "
        "--require-ready",
        "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_external_dependency_clearance.py "
        "${GEO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-external-dependency-clearance-latest.json} "
        "--require-handoff-ready",
        "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_customer_handoff_clearance.py "
        "${GEO_AU_CUSTOMER_HANDOFF_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-clearance-latest.json} "
        "--require-cleared",
    ]
    commands.extend(_strings(customer_handoff_readiness.get("hard_gate_commands")))
    commands.extend(_strings(delivery_progress.get("hard_gate_commands")))
    commands.extend(_strings(external_dependency_handoff.get("hard_gate_commands")))
    commands.extend(_strings(external_dependency_clearance.get("hard_gate_commands")))
    commands.extend(_strings(p0a_credential_clearance.get("hard_gate_commands")))
    commands.extend(_strings(p0a_credential_update_receipt.get("strict_gate_commands")))
    commands.extend(_strings(p0a_real_batch_clearance.get("hard_gate_commands")))
    commands.extend(_strings(p0b_google_environment_clearance.get("hard_gate_commands")))
    commands.extend(_strings(p0b_google_manual_backfill_clearance.get("hard_gate_commands")))
    commands.extend(_strings(p0b_google_phase_execution_clearance.get("hard_gate_commands")))
    commands.extend(_strings(target_step.get("recommended_sequence")))
    return _unique_strings(commands)


def _clearance_next_command(delivery_progress: dict[str, Any], external_clearance: dict[str, Any]) -> str:
    progress_summary = _as_dict(delivery_progress.get("summary"))
    return str(progress_summary.get("next_command") or external_clearance.get("next_command") or "")


def build_au_customer_handoff_clearance(
    *,
    handoff_dossier_path: Path = Path(DEFAULT_HANDOFF_DOSSIER_PATH),
    customer_handoff_readiness_path: Path = Path(DEFAULT_CUSTOMER_HANDOFF_READINESS_PATH),
    delivery_progress_path: Path = Path(DEFAULT_DELIVERY_PROGRESS_PATH),
    external_dependency_handoff_path: Path = Path(DEFAULT_EXTERNAL_DEPENDENCY_HANDOFF_PATH),
    external_dependency_clearance_path: Path = Path(DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH),
    p0a_credential_clearance_path: Path = Path(DEFAULT_P0A_CREDENTIAL_CLEARANCE_PATH),
    p0a_credential_update_receipt_path: Path = Path(DEFAULT_P0A_CREDENTIAL_UPDATE_RECEIPT_PATH),
    p0a_real_batch_clearance_path: Path = Path(DEFAULT_P0A_REAL_BATCH_CLEARANCE_PATH),
    p0b_google_environment_clearance_path: Path = Path(DEFAULT_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_PATH),
    p0b_google_manual_backfill_clearance_path: Path = Path(DEFAULT_P0B_GOOGLE_MANUAL_BACKFILL_CLEARANCE_PATH),
    p0b_google_phase_execution_clearance_path: Path = Path(DEFAULT_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_PATH),
    handoff_dossier: dict[str, Any] | None = None,
    customer_handoff_readiness: dict[str, Any] | None = None,
    delivery_progress: dict[str, Any] | None = None,
    external_dependency_handoff: dict[str, Any] | None = None,
    external_dependency_clearance: dict[str, Any] | None = None,
    p0a_credential_clearance: dict[str, Any] | None = None,
    p0a_credential_update_receipt: dict[str, Any] | None = None,
    p0a_real_batch_clearance: dict[str, Any] | None = None,
    p0b_google_environment_clearance: dict[str, Any] | None = None,
    p0b_google_manual_backfill_clearance: dict[str, Any] | None = None,
    p0b_google_phase_execution_clearance: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if handoff_dossier is None:
        handoff_dossier, handoff_source = _load_or_build_handoff_dossier(
            handoff_dossier_path,
            generated_at=generated_at,
        )
    else:
        handoff_source = {"path": str(handoff_dossier_path), "exists": True, "source": "provided_payload", "errors": []}

    if customer_handoff_readiness is None:
        customer_handoff_readiness, readiness_source = _load_or_build_customer_readiness(
            customer_handoff_readiness_path,
            handoff_dossier_path=handoff_dossier_path,
            handoff_dossier=handoff_dossier,
            generated_at=generated_at,
        )
    else:
        readiness_source = {
            "path": str(customer_handoff_readiness_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if external_dependency_handoff is None:
        external_dependency_handoff, external_handoff_source = _load_or_build_external_handoff(
            external_dependency_handoff_path,
            generated_at=generated_at,
        )
    else:
        external_handoff_source = {
            "path": str(external_dependency_handoff_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if external_dependency_clearance is None:
        external_dependency_clearance, external_clearance_source = _load_or_build_external_clearance(
            external_dependency_clearance_path,
            external_dependency_handoff_path=external_dependency_handoff_path,
            external_dependency_handoff=external_dependency_handoff,
            generated_at=generated_at,
        )
    else:
        external_clearance_source = {
            "path": str(external_dependency_clearance_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
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
            "errors": [],
        }

    if p0a_credential_update_receipt is None:
        p0a_credential_update_receipt, p0a_credential_update_receipt_source = (
            _load_or_build_p0a_credential_update_receipt(
                p0a_credential_update_receipt_path,
                p0a_credential_clearance_path=p0a_credential_clearance_path,
                p0a_credential_clearance=p0a_credential_clearance,
                generated_at=generated_at,
            )
        )
    else:
        p0a_credential_update_receipt_source = {
            "path": str(p0a_credential_update_receipt_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
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
            "errors": [],
        }

    if p0b_google_environment_clearance is None:
        (
            p0b_google_environment_clearance,
            p0b_google_environment_clearance_source,
        ) = _load_or_build_external_clearance_bound_packet(
            p0b_google_environment_clearance_path,
            external_dependency_clearance_path=external_dependency_clearance_path,
            external_dependency_clearance=external_dependency_clearance,
            generated_at=generated_at,
            builder=build_au_p0b_google_environment_clearance,
        )
    else:
        p0b_google_environment_clearance_source = {
            "path": str(p0b_google_environment_clearance_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if p0b_google_manual_backfill_clearance is None:
        (
            p0b_google_manual_backfill_clearance,
            p0b_google_manual_backfill_clearance_source,
        ) = _load_or_build_external_clearance_bound_packet(
            p0b_google_manual_backfill_clearance_path,
            external_dependency_clearance_path=external_dependency_clearance_path,
            external_dependency_clearance=external_dependency_clearance,
            generated_at=generated_at,
            builder=build_au_p0b_google_manual_backfill_clearance,
        )
    else:
        p0b_google_manual_backfill_clearance_source = {
            "path": str(p0b_google_manual_backfill_clearance_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if p0b_google_phase_execution_clearance is None:
        (
            p0b_google_phase_execution_clearance,
            p0b_google_phase_execution_clearance_source,
        ) = _load_or_build_external_clearance_bound_packet(
            p0b_google_phase_execution_clearance_path,
            external_dependency_clearance_path=external_dependency_clearance_path,
            external_dependency_clearance=external_dependency_clearance,
            generated_at=generated_at,
            builder=build_au_p0b_google_phase_execution_clearance,
        )
    else:
        p0b_google_phase_execution_clearance_source = {
            "path": str(p0b_google_phase_execution_clearance_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if delivery_progress is None:
        delivery_progress, delivery_source = _load_or_build_delivery_progress(
            delivery_progress_path,
            handoff_dossier_path=handoff_dossier_path,
            customer_handoff_readiness_path=customer_handoff_readiness_path,
            external_dependency_handoff_path=external_dependency_handoff_path,
            external_dependency_clearance_path=external_dependency_clearance_path,
            p0a_credential_clearance_path=p0a_credential_clearance_path,
            p0a_credential_update_receipt_path=p0a_credential_update_receipt_path,
            p0a_real_batch_clearance_path=p0a_real_batch_clearance_path,
            p0b_google_environment_clearance_path=p0b_google_environment_clearance_path,
            p0b_google_manual_backfill_clearance_path=p0b_google_manual_backfill_clearance_path,
            p0b_google_phase_execution_clearance_path=p0b_google_phase_execution_clearance_path,
            handoff_dossier=handoff_dossier,
            customer_handoff_readiness=customer_handoff_readiness,
            external_dependency_handoff=external_dependency_handoff,
            external_dependency_clearance=external_dependency_clearance,
            p0a_credential_clearance=p0a_credential_clearance,
            p0a_credential_update_receipt=p0a_credential_update_receipt,
            p0a_real_batch_clearance=p0a_real_batch_clearance,
            p0b_google_environment_clearance=p0b_google_environment_clearance,
            p0b_google_manual_backfill_clearance=p0b_google_manual_backfill_clearance,
            p0b_google_phase_execution_clearance=p0b_google_phase_execution_clearance,
            generated_at=generated_at,
        )
    else:
        delivery_source = {"path": str(delivery_progress_path), "exists": True, "source": "provided_payload", "errors": []}

    handoff_verifier = verify_au_handoff_dossier(handoff_dossier, path=handoff_dossier_path)
    readiness_verifier = verify_au_customer_handoff_readiness(
        customer_handoff_readiness,
        path=customer_handoff_readiness_path,
    )
    progress_verifier = verify_au_delivery_progress(
        delivery_progress,
        path=_path_for_current_file_check(delivery_source, delivery_progress_path),
    )
    external_handoff_verifier = verify_au_external_dependency_handoff(
        external_dependency_handoff,
        path=external_dependency_handoff_path,
    )
    external_clearance_verifier = verify_au_external_dependency_clearance(
        external_dependency_clearance,
        path=external_dependency_clearance_path,
    )
    p0a_credential_clearance_verifier = verify_au_p0a_credential_clearance(
        p0a_credential_clearance,
        path=_path_for_current_file_check(p0a_credential_clearance_source, p0a_credential_clearance_path),
    )
    p0a_credential_update_receipt_verifier = verify_au_p0a_credential_update_receipt(
        p0a_credential_update_receipt,
        path=_path_for_current_file_check(p0a_credential_update_receipt_source, p0a_credential_update_receipt_path),
    )
    p0a_real_batch_clearance_verifier = verify_au_p0a_real_batch_clearance(
        p0a_real_batch_clearance,
        path=_path_for_current_file_check(p0a_real_batch_clearance_source, p0a_real_batch_clearance_path),
    )
    p0b_google_environment_clearance_verifier = verify_au_p0b_google_environment_clearance(
        p0b_google_environment_clearance,
        path=_path_for_current_file_check(
            p0b_google_environment_clearance_source,
            p0b_google_environment_clearance_path,
        ),
    )
    p0b_google_manual_backfill_clearance_verifier = verify_au_p0b_google_manual_backfill_clearance(
        p0b_google_manual_backfill_clearance,
        path=_path_for_current_file_check(
            p0b_google_manual_backfill_clearance_source,
            p0b_google_manual_backfill_clearance_path,
        ),
    )
    p0b_google_phase_execution_clearance_verifier = verify_au_p0b_google_phase_execution_clearance(
        p0b_google_phase_execution_clearance,
        path=_path_for_current_file_check(
            p0b_google_phase_execution_clearance_source,
            p0b_google_phase_execution_clearance_path,
        ),
    )

    handoff_ok = handoff_verifier.get("status") == "pass" and handoff_verifier.get("hash_valid") is True
    readiness_ok = readiness_verifier.get("status") == "pass" and readiness_verifier.get("hash_valid") is True
    progress_ok = progress_verifier.get("status") == "pass" and progress_verifier.get("hash_valid") is True
    external_handoff_ok = (
        external_handoff_verifier.get("status") == "pass" and external_handoff_verifier.get("hash_valid") is True
    )
    external_clearance_ok = (
        external_clearance_verifier.get("status") == "pass" and external_clearance_verifier.get("hash_valid") is True
    )
    p0a_credential_clearance_ok = (
        p0a_credential_clearance_verifier.get("status") == "pass"
        and p0a_credential_clearance_verifier.get("hash_valid") is True
    )
    p0a_credential_update_receipt_ok = (
        p0a_credential_update_receipt_verifier.get("status") == "pass"
        and p0a_credential_update_receipt_verifier.get("hash_valid") is True
    )
    p0a_real_batch_clearance_ok = (
        p0a_real_batch_clearance_verifier.get("status") == "pass"
        and p0a_real_batch_clearance_verifier.get("hash_valid") is True
    )
    p0b_google_environment_clearance_ok = (
        p0b_google_environment_clearance_verifier.get("status") == "pass"
        and p0b_google_environment_clearance_verifier.get("hash_valid") is True
    )
    p0b_google_manual_backfill_clearance_ok = (
        p0b_google_manual_backfill_clearance_verifier.get("status") == "pass"
        and p0b_google_manual_backfill_clearance_verifier.get("hash_valid") is True
    )
    p0b_google_phase_execution_clearance_ok = (
        p0b_google_phase_execution_clearance_verifier.get("status") == "pass"
        and p0b_google_phase_execution_clearance_verifier.get("hash_valid") is True
    )
    packet_ready = (
        handoff_ok
        and readiness_ok
        and progress_ok
        and external_handoff_ok
        and external_clearance_ok
        and p0a_credential_clearance_ok
        and p0a_credential_update_receipt_ok
        and p0a_real_batch_clearance_ok
        and p0b_google_environment_clearance_ok
        and p0b_google_manual_backfill_clearance_ok
        and p0b_google_phase_execution_clearance_ok
    )

    target_step = _step_by_id(external_dependency_clearance, STEP_ID)
    prerequisite_steps = [_step_by_id(external_dependency_clearance, step_id) for step_id in PREREQUISITE_STEP_IDS]
    prerequisite_steps_ready = all(step.get("ready") is True for step in prerequisite_steps)
    blocked_by_prerequisite = not prerequisite_steps_ready
    target_step_ready = target_step.get("ready") is True
    target_step_can_start = target_step.get("can_start") is True
    customer_ready = customer_handoff_readiness.get("ready_for_customer_report_handoff") is True
    progress_customer_ready = delivery_progress.get("ready_for_customer_report_handoff") is True
    external_handoff_ready = external_dependency_handoff.get("external_dependency_handoff_ready") is True
    customer_handoff_clearance_ready = (
        customer_ready
        and progress_customer_ready
        and external_handoff_ready
        and target_step_ready
        and prerequisite_steps_ready
    )
    ready_for_report_export_handoff = packet_ready and customer_handoff_clearance_ready

    items = _customer_gate_items(customer_handoff_readiness)
    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True)
    blocking_reasons = _blocking_reasons(items)
    operator_steps = _operator_steps(
        delivery_progress=delivery_progress,
        external_dependency_clearance=external_dependency_clearance,
        blocked_by_prerequisite=blocked_by_prerequisite,
    )
    validation_sequence = _post_update_validation_sequence(
        customer_handoff_readiness=customer_handoff_readiness,
        delivery_progress=delivery_progress,
        external_dependency_handoff=external_dependency_handoff,
        external_dependency_clearance=external_dependency_clearance,
        p0a_credential_clearance=p0a_credential_clearance,
        p0a_credential_update_receipt=p0a_credential_update_receipt,
        p0a_real_batch_clearance=p0a_real_batch_clearance,
        p0b_google_environment_clearance=p0b_google_environment_clearance,
        p0b_google_manual_backfill_clearance=p0b_google_manual_backfill_clearance,
        p0b_google_phase_execution_clearance=p0b_google_phase_execution_clearance,
        target_step=target_step,
    )
    progress_summary = _as_dict(delivery_progress.get("summary"))
    readiness_summary = _as_dict(customer_handoff_readiness.get("summary"))
    trial_summary = {
        "trial_handoff_version": progress_summary.get("trial_handoff_version", ""),
        "ready_for_trial_customer_handoff": progress_summary.get("ready_for_trial_customer_handoff") is True,
        "trial_customer_handoff_readiness_percent": progress_summary.get(
            "trial_customer_handoff_readiness_percent",
            0.0,
        ),
        "trial_ready_gate_count": progress_summary.get("trial_ready_gate_count", 0),
        "trial_total_gate_count": progress_summary.get("trial_total_gate_count", 0),
        "trial_blocked_gate_count": progress_summary.get("trial_blocked_gate_count", 0),
        "trial_blocked_gate_ids": progress_summary.get("trial_blocked_gate_ids", []),
        "trial_google_coverage_mode": progress_summary.get("trial_google_coverage_mode", ""),
        "trial_full_batch_required": progress_summary.get("trial_full_batch_required") is True,
        "trial_full_batch_status": progress_summary.get("trial_full_batch_status", ""),
    }
    payload: dict[str, Any] = {
        "customer_handoff_clearance_version": CLEARANCE_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if packet_ready else "fail",
        "customer_handoff_clearance_packet_ready": packet_ready,
        "customer_handoff_ready": customer_ready,
        "customer_handoff_clearance_ready": customer_handoff_clearance_ready,
        "ready_for_report_export_handoff": ready_for_report_export_handoff,
        "ready_for_trial_customer_handoff": trial_summary["ready_for_trial_customer_handoff"],
        "blocked_by_prerequisite_step": blocked_by_prerequisite,
        "output_path": str(output_path) if output_path else "",
        "clearance_step": {
            "id": STEP_ID,
            "current_global_step_id": str(external_dependency_clearance.get("current_step_id") or ""),
            "step_recorded": bool(target_step),
            "step_ready": target_step_ready,
            "step_can_start": target_step_can_start,
            "step_status": str(target_step.get("status") or ""),
            "blocked_by": _strings(target_step.get("blocked_by")),
            "would_execute": target_step.get("would_execute") is True,
            "strict_gate_command": str(target_step.get("strict_gate_command") or ""),
        },
        "prerequisite_steps": [
            {
                "id": step_id,
                "ready": step.get("ready") is True,
                "status": str(step.get("status") or ""),
                "would_execute": step.get("would_execute") is True,
                "strict_gate_command": str(step.get("strict_gate_command") or ""),
                "blocked_by": _strings(step.get("blocked_by")),
                "runtime_endpoint": str(_as_dict(step.get("linked_request_context")).get("runtime_endpoint") or ""),
            }
            for step_id, step in zip(PREREQUISITE_STEP_IDS, prerequisite_steps, strict=True)
        ],
        "source_artifacts": {
            "handoff_dossier": {
                "path": str(handoff_dossier_path),
                "source": handoff_source,
                "hash_field": "handoff_dossier_hash",
                "hash": str(handoff_dossier.get("handoff_dossier_hash") or ""),
                "verifier_status": handoff_verifier.get("status", ""),
                "hash_valid": handoff_verifier.get("hash_valid") is True,
            },
            "customer_handoff_readiness": {
                "path": str(customer_handoff_readiness_path),
                "source": readiness_source,
                "hash_field": "customer_handoff_readiness_hash",
                "hash": str(customer_handoff_readiness.get("customer_handoff_readiness_hash") or ""),
                "verifier_status": readiness_verifier.get("status", ""),
                "hash_valid": readiness_verifier.get("hash_valid") is True,
            },
            "delivery_progress": {
                "path": str(delivery_progress_path),
                "source": delivery_source,
                "hash_field": "delivery_progress_hash",
                "hash": str(delivery_progress.get("delivery_progress_hash") or ""),
                "verifier_status": progress_verifier.get("status", ""),
                "hash_valid": progress_verifier.get("hash_valid") is True,
            },
            "external_dependency_handoff": {
                "path": str(external_dependency_handoff_path),
                "source": external_handoff_source,
                "hash_field": "external_dependency_handoff_hash",
                "hash": str(external_dependency_handoff.get("external_dependency_handoff_hash") or ""),
                "verifier_status": external_handoff_verifier.get("status", ""),
                "hash_valid": external_handoff_verifier.get("hash_valid") is True,
            },
            "external_dependency_clearance": {
                "path": str(external_dependency_clearance_path),
                "source": external_clearance_source,
                "hash_field": "clearance_execution_hash",
                "hash": str(external_dependency_clearance.get("clearance_execution_hash") or ""),
                "verifier_status": external_clearance_verifier.get("status", ""),
                "hash_valid": external_clearance_verifier.get("hash_valid") is True,
            },
            "p0a_credential_clearance": {
                "path": str(p0a_credential_clearance_path),
                "source": p0a_credential_clearance_source,
                "hash_field": "p0a_credential_clearance_hash",
                "hash": str(p0a_credential_clearance.get("p0a_credential_clearance_hash") or ""),
                "verifier_status": p0a_credential_clearance_verifier.get("status", ""),
                "hash_valid": p0a_credential_clearance_verifier.get("hash_valid") is True,
            },
            "p0a_credential_update_receipt": {
                "path": str(p0a_credential_update_receipt_path),
                "source": p0a_credential_update_receipt_source,
                "hash_field": "p0a_credential_update_receipt_hash",
                "hash": str(p0a_credential_update_receipt.get("p0a_credential_update_receipt_hash") or ""),
                "verifier_status": p0a_credential_update_receipt_verifier.get("status", ""),
                "hash_valid": p0a_credential_update_receipt_verifier.get("hash_valid") is True,
            },
            "p0a_real_batch_clearance": {
                "path": str(p0a_real_batch_clearance_path),
                "source": p0a_real_batch_clearance_source,
                "hash_field": "p0a_real_batch_clearance_hash",
                "hash": str(p0a_real_batch_clearance.get("p0a_real_batch_clearance_hash") or ""),
                "verifier_status": p0a_real_batch_clearance_verifier.get("status", ""),
                "hash_valid": p0a_real_batch_clearance_verifier.get("hash_valid") is True,
            },
            "p0b_google_environment_clearance": {
                "path": str(p0b_google_environment_clearance_path),
                "source": p0b_google_environment_clearance_source,
                "hash_field": "p0b_google_environment_clearance_hash",
                "hash": str(p0b_google_environment_clearance.get("p0b_google_environment_clearance_hash") or ""),
                "verifier_status": p0b_google_environment_clearance_verifier.get("status", ""),
                "hash_valid": p0b_google_environment_clearance_verifier.get("hash_valid") is True,
            },
            "p0b_google_manual_backfill_clearance": {
                "path": str(p0b_google_manual_backfill_clearance_path),
                "source": p0b_google_manual_backfill_clearance_source,
                "hash_field": "p0b_google_manual_backfill_clearance_hash",
                "hash": str(
                    p0b_google_manual_backfill_clearance.get("p0b_google_manual_backfill_clearance_hash") or ""
                ),
                "verifier_status": p0b_google_manual_backfill_clearance_verifier.get("status", ""),
                "hash_valid": p0b_google_manual_backfill_clearance_verifier.get("hash_valid") is True,
            },
            "p0b_google_phase_execution_clearance": {
                "path": str(p0b_google_phase_execution_clearance_path),
                "source": p0b_google_phase_execution_clearance_source,
                "hash_field": "p0b_google_phase_execution_clearance_hash",
                "hash": str(
                    p0b_google_phase_execution_clearance.get("p0b_google_phase_execution_clearance_hash") or ""
                ),
                "verifier_status": p0b_google_phase_execution_clearance_verifier.get("status", ""),
                "hash_valid": p0b_google_phase_execution_clearance_verifier.get("hash_valid") is True,
            },
        },
        "verifiers": {
            "handoff_dossier": handoff_verifier,
            "customer_handoff_readiness": readiness_verifier,
            "delivery_progress": progress_verifier,
            "external_dependency_handoff": external_handoff_verifier,
            "external_dependency_clearance": external_clearance_verifier,
            "p0a_credential_clearance": p0a_credential_clearance_verifier,
            "p0a_credential_update_receipt": p0a_credential_update_receipt_verifier,
            "p0a_real_batch_clearance": p0a_real_batch_clearance_verifier,
            "p0b_google_environment_clearance": p0b_google_environment_clearance_verifier,
            "p0b_google_manual_backfill_clearance": p0b_google_manual_backfill_clearance_verifier,
            "p0b_google_phase_execution_clearance": p0b_google_phase_execution_clearance_verifier,
        },
        "summary": {
            "required_count": len(required_items),
            "fulfilled_required_count": len(fulfilled_required),
            "missing_required_count": len(missing_required),
            "missing_required": missing_required,
            "owner_counts": _owner_counts(items),
            "missing_required_by_owner": _missing_by_owner(items),
            "blocking_reason_count": len(blocking_reasons),
            "blocking_reasons": blocking_reasons,
            "customer_handoff_ready": customer_ready,
            "customer_report_handoff_readiness_percent": readiness_summary.get(
                "customer_report_handoff_readiness_percent",
                0.0,
            ),
            "engineering_progress_percent": progress_summary.get("engineering_progress_percent", 0.0),
            "structural_auditability_percent": readiness_summary.get("structural_auditability_percent", 0.0),
            **trial_summary,
            "customer_gate_count": len(items),
            "ready_customer_gate_count": len(fulfilled_required),
            "blocked_customer_gate_count": len(required_items) - len(fulfilled_required),
            "blocked_customer_gate_ids": readiness_summary.get("blocked_customer_gate_ids", []),
            "delivery_progress_ready": delivery_progress.get("delivery_progress_ready") is True,
            "delivery_progress_customer_ready": progress_customer_ready,
            "external_dependency_handoff_ready": external_handoff_ready,
            "ready_progress_gate_count": progress_summary.get("ready_progress_gate_count", 0),
            "blocked_progress_gate_ids": progress_summary.get("blocked_progress_gate_ids", []),
            "blocked_by_prerequisite_step": blocked_by_prerequisite,
            "prerequisite_step_ids": list(PREREQUISITE_STEP_IDS),
            "prerequisite_steps_ready": prerequisite_steps_ready,
            "current_global_clearance_step_id": str(external_dependency_clearance.get("current_step_id") or ""),
            "current_clearance_request_artifact_id": str(
                progress_summary.get("current_clearance_request_artifact_id") or ""
            ),
            "current_clearance_request_artifact_hash": str(
                progress_summary.get("current_clearance_request_artifact_hash") or ""
            ),
            "current_clearance_completion_contract_ready": progress_summary.get(
                "current_clearance_completion_contract_ready"
            )
            is True,
            "current_clearance_completion_contract_version": str(
                progress_summary.get("current_clearance_completion_contract_version") or ""
            ),
            "current_clearance_credential_update_receipt_required": progress_summary.get(
                "current_clearance_credential_update_receipt_required"
            )
            is True,
            "current_clearance_credential_update_receipt_endpoint": str(
                progress_summary.get("current_clearance_credential_update_receipt_endpoint") or ""
            ),
            "current_clearance_credential_update_receipt_strict_gate": str(
                progress_summary.get("current_clearance_credential_update_receipt_strict_gate") or ""
            ),
            "current_clearance_post_update_validation_command_count": progress_summary.get(
                "current_clearance_post_update_validation_command_count",
                0,
            ),
            "current_clearance_completion_contract_missing_required_count": progress_summary.get(
                "current_clearance_completion_contract_missing_required_count",
                0,
            ),
            "current_clearance_completion_contract_raw_secret_values_allowed": progress_summary.get(
                "current_clearance_completion_contract_raw_secret_values_allowed"
            )
            is True,
            "target_clearance_step_id": STEP_ID,
            "target_clearance_step_can_start": target_step_can_start,
            "target_clearance_step_ready": target_step_ready,
            "customer_handoff_clearance_ready": customer_handoff_clearance_ready,
            "ready_for_report_export_handoff": ready_for_report_export_handoff,
            "next_action": (
                "clear_customer_handoff_prerequisites_first"
                if blocked_by_prerequisite
                else (
                    "run_final_customer_handoff_strict_gates"
                    if customer_ready
                    else "clear_customer_report_handoff_gate"
                )
            ),
            "next_command": _clearance_next_command(delivery_progress, external_dependency_clearance),
            "operator_step_count": len(operator_steps),
            "post_update_validation_command_count": len(validation_sequence),
            "handoff_dossier_hash": handoff_dossier.get("handoff_dossier_hash", ""),
            "customer_handoff_readiness_hash": customer_handoff_readiness.get("customer_handoff_readiness_hash", ""),
            "delivery_progress_hash": delivery_progress.get("delivery_progress_hash", ""),
            "external_dependency_handoff_hash": external_dependency_handoff.get("external_dependency_handoff_hash", ""),
            "clearance_execution_hash": external_dependency_clearance.get("clearance_execution_hash", ""),
            "p0a_credential_clearance_hash": p0a_credential_clearance.get("p0a_credential_clearance_hash", ""),
            "p0a_credential_clearance_ready": p0a_credential_clearance.get("credential_clearance_ready") is True,
            "p0a_credentials_fulfilled": p0a_credential_clearance.get("credentials_fulfilled") is True,
            "p0a_credential_missing_required_count": _as_dict(p0a_credential_clearance.get("summary")).get(
                "missing_required_count",
                0,
            ),
            "p0a_credential_update_receipt_hash": p0a_credential_update_receipt.get(
                "p0a_credential_update_receipt_hash",
                "",
            ),
            "p0a_credential_update_receipt_ready": p0a_credential_update_receipt.get(
                "credential_update_receipt_ready"
            )
            is True,
            "p0a_credential_update_receipt_complete": p0a_credential_update_receipt.get(
                "credential_update_receipt_complete"
            )
            is True,
            "p0a_credential_update_receipt_missing_required_count": _as_dict(
                p0a_credential_update_receipt.get("summary")
            ).get("missing_required_count", 0),
            "p0a_credential_update_env_file_hygiene_ready": _as_dict(
                p0a_credential_update_receipt.get("summary")
            ).get("env_file_hygiene_ready")
            is True,
            "p0a_real_batch_clearance_hash": p0a_real_batch_clearance.get("p0a_real_batch_clearance_hash", ""),
            "p0a_real_batch_clearance_ready": p0a_real_batch_clearance.get("real_batch_clearance_ready") is True,
            "p0a_real_batches_fulfilled": p0a_real_batch_clearance.get("real_batches_fulfilled") is True,
            "p0a_real_batch_blocked_by_prerequisite": p0a_real_batch_clearance.get("blocked_by_prerequisite_step")
            is True,
            "p0a_real_batch_execution_plan_ready": progress_summary.get("p0a_real_batch_execution_plan_ready") is True,
            "p0a_real_batch_total_planned_runs": progress_summary.get("p0a_real_batch_total_planned_runs", 0),
            "p0a_real_batch_ready_phase_count": progress_summary.get("p0a_real_batch_ready_phase_count", 0),
            "p0a_real_batch_blocked_phase_count": progress_summary.get("p0a_real_batch_blocked_phase_count", 0),
            "p0a_real_batch_missing_required_count": _as_dict(p0a_real_batch_clearance.get("summary")).get(
                "missing_required_count",
                0,
            ),
            "p0a_real_batch_next_phase": _as_dict(p0a_real_batch_clearance.get("summary")).get("next_phase", ""),
            "p0a_real_batch_phase_command_count": progress_summary.get("p0a_real_batch_phase_command_count", 0),
            "p0a_real_batch_evidence_output_count": progress_summary.get(
                "p0a_real_batch_evidence_output_count",
                0,
            ),
            "p0b_google_environment_clearance_hash": p0b_google_environment_clearance.get(
                "p0b_google_environment_clearance_hash",
                "",
            ),
            "p0b_google_environment_clearance_ready": p0b_google_environment_clearance.get(
                "environment_clearance_ready"
            )
            is True,
            "p0b_google_environment_fulfilled": p0b_google_environment_clearance.get("environment_fulfilled") is True,
            "p0b_google_environment_missing_required_count": _as_dict(
                p0b_google_environment_clearance.get("summary")
            ).get("missing_required_count", 0),
            "p0b_google_environment_action_plan_ready": progress_summary.get(
                "p0b_google_environment_action_plan_ready"
            )
            is True,
            "p0b_google_environment_action_required": progress_summary.get(
                "p0b_google_environment_action_required"
            )
            is True,
            "p0b_google_environment_action_item_count": progress_summary.get(
                "p0b_google_environment_action_item_count",
                0,
            ),
            "p0b_google_environment_action_owner_counts": progress_summary.get(
                "p0b_google_environment_action_owner_counts",
                {},
            ),
            "p0b_google_environment_post_update_validation_command_count": progress_summary.get(
                "p0b_google_environment_post_update_validation_command_count",
                0,
            ),
            "p0b_google_manual_backfill_clearance_hash": p0b_google_manual_backfill_clearance.get(
                "p0b_google_manual_backfill_clearance_hash",
                "",
            ),
            "p0b_google_manual_backfill_clearance_ready": p0b_google_manual_backfill_clearance.get(
                "manual_backfill_clearance_ready"
            )
            is True,
            "p0b_google_manual_backfill_fulfilled": p0b_google_manual_backfill_clearance.get(
                "manual_backfill_fulfilled"
            )
            is True,
            "p0b_google_manual_backfill_missing_required_count": _as_dict(
                p0b_google_manual_backfill_clearance.get("summary")
            ).get("missing_required_count", 0),
            "p0b_google_manual_backfill_record_count": _as_dict(
                p0b_google_manual_backfill_clearance.get("summary")
            ).get("record_count", 0),
            "p0b_google_manual_backfill_expected_record_count": _as_dict(
                p0b_google_manual_backfill_clearance.get("summary")
            ).get("expected_record_count", 0),
            "p0b_google_manual_backfill_ready": progress_summary.get("p0b_google_manual_backfill_ready") is True,
            "p0b_google_manual_backfill_coverage_complete": progress_summary.get(
                "p0b_google_manual_backfill_coverage_complete"
            )
            is True,
            "p0b_google_manual_backfill_content_complete": progress_summary.get(
                "p0b_google_manual_backfill_content_complete"
            )
            is True,
            "p0b_google_manual_backfill_content_completion_handoff_ready": progress_summary.get(
                "p0b_google_manual_backfill_content_completion_handoff_ready"
            )
            is True,
            "p0b_google_manual_backfill_missing_prompt_city_sample_count": progress_summary.get(
                "p0b_google_manual_backfill_missing_prompt_city_sample_count",
                0,
            ),
            "p0b_google_manual_backfill_duplicate_prompt_city_sample_count": progress_summary.get(
                "p0b_google_manual_backfill_duplicate_prompt_city_sample_count",
                0,
            ),
            "p0b_google_manual_backfill_unexpected_prompt_city_record_count": progress_summary.get(
                "p0b_google_manual_backfill_unexpected_prompt_city_record_count",
                0,
            ),
            "p0b_google_manual_backfill_missing_answer_line_count": progress_summary.get(
                "p0b_google_manual_backfill_missing_answer_line_count",
                0,
            ),
            "p0b_google_manual_backfill_missing_citation_line_count": progress_summary.get(
                "p0b_google_manual_backfill_missing_citation_line_count",
                0,
            ),
            "p0b_google_manual_backfill_missing_asset_line_count": progress_summary.get(
                "p0b_google_manual_backfill_missing_asset_line_count",
                0,
            ),
            "p0b_google_manual_backfill_missing_total_content_cell_count": progress_summary.get(
                "p0b_google_manual_backfill_missing_total_content_cell_count",
                0,
            ),
            "p0b_google_manual_backfill_post_content_completion_validation_command_count": progress_summary.get(
                "p0b_google_manual_backfill_post_content_completion_validation_command_count",
                0,
            ),
            "p0b_google_manual_backfill_verification_next_action": progress_summary.get(
                "p0b_google_manual_backfill_verification_next_action",
                "",
            ),
            "p0b_google_phase_execution_clearance_hash": p0b_google_phase_execution_clearance.get(
                "p0b_google_phase_execution_clearance_hash",
                "",
            ),
            "p0b_google_phase_execution_clearance_ready": p0b_google_phase_execution_clearance.get(
                "phase_execution_clearance_ready"
            )
            is True,
            "p0b_google_phase_execution_fulfilled": p0b_google_phase_execution_clearance.get(
                "phase_execution_fulfilled"
            )
            is True,
            "p0b_google_phase_execution_missing_required_count": _as_dict(
                p0b_google_phase_execution_clearance.get("summary")
            ).get("missing_required_count", 0),
            "p0b_google_phase_execution_next_phase": _as_dict(
                p0b_google_phase_execution_clearance.get("summary")
            ).get("next_phase", ""),
            "raw_secret_values_allowed": False,
            "raw_answer_values_allowed": False,
            "raw_citation_values_allowed": False,
            "raw_asset_urls_allowed": False,
            "raw_provider_response_allowed": False,
            "customer_gate_entries_reference_hashes_status_and_evidence_refs_only": True,
        },
        "customer_handoff_clearance_items": items,
        "operator_steps": operator_steps,
        "post_update_validation_sequence": validation_sequence,
        "runtime_endpoints": {
            "customer_handoff_clearance": "GET /v1/customer-handoff-clearance/au",
            "handoff_dossier": "GET /v1/handoff-dossier/au",
            "customer_handoff_readiness": "GET /v1/customer-handoff-readiness/au",
            "delivery_progress": "GET /v1/delivery-progress/au",
            "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
            "p0a_credential_clearance": "GET /v1/p0a-credential-clearance/au",
            "p0a_credential_update_receipt": "GET /v1/p0a-credential-update-receipt/au",
            "p0a_real_batch_clearance": "GET /v1/p0a-real-batch-clearance/au",
            "p0b_google_environment_clearance": "GET /v1/p0b-google-environment-clearance/au",
            "p0b_google_manual_backfill_clearance": "GET /v1/p0b-google-manual-backfill-clearance/au",
            "p0b_google_phase_execution_clearance": "GET /v1/p0b-google-phase-execution-clearance/au",
        },
        "hard_gate_commands": _unique_strings(
            [
                "make au-customer-handoff-clearance",
                "make verify-au-customer-handoff-clearance",
                *validation_sequence,
            ]
        ),
        "evidence_sources": [
            _source_file_entry("handoff_dossier", handoff_dossier_path),
            _source_file_entry("customer_handoff_readiness", customer_handoff_readiness_path),
            _source_file_entry("delivery_progress", delivery_progress_path),
            _source_file_entry("external_dependency_handoff", external_dependency_handoff_path),
            _source_file_entry("external_dependency_clearance", external_dependency_clearance_path),
            _source_file_entry("p0a_credential_clearance", p0a_credential_clearance_path),
            _source_file_entry("p0a_credential_update_receipt", p0a_credential_update_receipt_path),
            _source_file_entry("p0a_real_batch_clearance", p0a_real_batch_clearance_path),
            _source_file_entry("p0b_google_environment_clearance", p0b_google_environment_clearance_path),
            _source_file_entry("p0b_google_manual_backfill_clearance", p0b_google_manual_backfill_clearance_path),
            _source_file_entry("p0b_google_phase_execution_clearance", p0b_google_phase_execution_clearance_path),
        ],
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "raw_answer_values_allowed": False,
            "raw_citation_values_allowed": False,
            "raw_asset_urls_allowed": False,
            "raw_provider_response_allowed": False,
            "customer_gate_entries_reference_hashes_status_and_evidence_refs_only": True,
            "forbidden_exact_customer_payload_field_count": 14,
            "recorded_fields": [
                "key",
                "gate_id",
                "stage",
                "required",
                "fulfilled",
                "ready",
                "status",
                "evidence_ref",
                "next_action",
                "owner_hint",
                "blocking_reasons",
            ],
        },
    }
    payload["customer_handoff_clearance_hash"] = compute_customer_handoff_clearance_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU customer handoff clearance JSON")
    parser.add_argument(
        "--handoff-dossier-path",
        default=os.environ.get("GEO_AU_HANDOFF_DOSSIER_OUTPUT_PATH", DEFAULT_HANDOFF_DOSSIER_PATH),
        help="Path to the AU handoff dossier JSON.",
    )
    parser.add_argument(
        "--customer-handoff-readiness-path",
        default=os.environ.get("GEO_AU_CUSTOMER_HANDOFF_READINESS_OUTPUT_PATH", DEFAULT_CUSTOMER_HANDOFF_READINESS_PATH),
        help="Path to the AU customer handoff readiness JSON.",
    )
    parser.add_argument(
        "--delivery-progress-path",
        default=os.environ.get("GEO_AU_DELIVERY_PROGRESS_OUTPUT_PATH", DEFAULT_DELIVERY_PROGRESS_PATH),
        help="Path to the AU delivery progress JSON.",
    )
    parser.add_argument(
        "--external-dependency-handoff-path",
        default=os.environ.get("GEO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH", DEFAULT_EXTERNAL_DEPENDENCY_HANDOFF_PATH),
        help="Path to the AU external dependency handoff JSON.",
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
        "--p0a-credential-clearance-path",
        default=os.environ.get("GEO_AU_P0A_CREDENTIAL_CLEARANCE_OUTPUT_PATH", DEFAULT_P0A_CREDENTIAL_CLEARANCE_PATH),
        help="Path to the AU P0a credential clearance JSON.",
    )
    parser.add_argument(
        "--p0a-credential-update-receipt-path",
        default=os.environ.get(
            "GEO_AU_P0A_CREDENTIAL_UPDATE_RECEIPT_OUTPUT_PATH",
            DEFAULT_P0A_CREDENTIAL_UPDATE_RECEIPT_PATH,
        ),
        help="Path to the AU P0a credential update receipt JSON.",
    )
    parser.add_argument(
        "--p0a-real-batch-clearance-path",
        default=os.environ.get("GEO_AU_P0A_REAL_BATCH_CLEARANCE_OUTPUT_PATH", DEFAULT_P0A_REAL_BATCH_CLEARANCE_PATH),
        help="Path to the AU P0a real batch clearance JSON.",
    )
    parser.add_argument(
        "--p0b-google-environment-clearance-path",
        default=os.environ.get(
            "GEO_AU_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_OUTPUT_PATH",
            DEFAULT_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_PATH,
        ),
        help="Path to the AU P0b Google environment clearance JSON.",
    )
    parser.add_argument(
        "--p0b-google-manual-backfill-clearance-path",
        default=os.environ.get(
            "GEO_AU_P0B_GOOGLE_MANUAL_BACKFILL_CLEARANCE_OUTPUT_PATH",
            DEFAULT_P0B_GOOGLE_MANUAL_BACKFILL_CLEARANCE_PATH,
        ),
        help="Path to the AU P0b Google manual backfill clearance JSON.",
    )
    parser.add_argument(
        "--p0b-google-phase-execution-clearance-path",
        default=os.environ.get(
            "GEO_AU_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_OUTPUT_PATH",
            DEFAULT_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_PATH,
        ),
        help="Path to the AU P0b Google phase execution clearance JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GEO_AU_CUSTOMER_HANDOFF_CLEARANCE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU customer handoff clearance JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_customer_handoff_clearance(
        handoff_dossier_path=Path(args.handoff_dossier_path),
        customer_handoff_readiness_path=Path(args.customer_handoff_readiness_path),
        delivery_progress_path=Path(args.delivery_progress_path),
        external_dependency_handoff_path=Path(args.external_dependency_handoff_path),
        external_dependency_clearance_path=Path(args.external_dependency_clearance_path),
        p0a_credential_clearance_path=Path(args.p0a_credential_clearance_path),
        p0a_credential_update_receipt_path=Path(args.p0a_credential_update_receipt_path),
        p0a_real_batch_clearance_path=Path(args.p0a_real_batch_clearance_path),
        p0b_google_environment_clearance_path=Path(args.p0b_google_environment_clearance_path),
        p0b_google_manual_backfill_clearance_path=Path(args.p0b_google_manual_backfill_clearance_path),
        p0b_google_phase_execution_clearance_path=Path(args.p0b_google_phase_execution_clearance_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
