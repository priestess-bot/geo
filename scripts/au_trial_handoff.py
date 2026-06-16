from __future__ import annotations

from typing import Any


TRIAL_HANDOFF_VERSION = "au_trial_customer_handoff_v1"
TRIAL_GOOGLE_COVERAGE_MODE = "limited_coverage_appendix_allowed"
TRIAL_FULL_BATCH_STATUS = "deferred_to_formal_launch"

TRIAL_GATE_ORDER: tuple[str, ...] = (
    "trial_p0a_credentials_ready",
    "trial_p0a_preflight_ready",
    "trial_p0a_small_batch_ready",
    "trial_p0c_report_contract_ready",
    "trial_google_limited_coverage_conclusion_ready",
    "trial_customer_package_manifest_ready",
    "trial_traceability_ready",
    "trial_structural_auditability_ready",
)

TRIAL_SUMMARY_FIELDS: tuple[str, ...] = (
    "trial_handoff_version",
    "ready_for_trial_customer_handoff",
    "trial_customer_handoff_readiness_percent",
    "trial_ready_gate_count",
    "trial_total_gate_count",
    "trial_blocked_gate_count",
    "trial_blocked_gate_ids",
    "trial_google_coverage_mode",
    "trial_full_batch_required",
    "trial_full_batch_status",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _percent(ready_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return round((ready_count / total_count) * 100, 1)


def _bool(value: object) -> bool:
    return value is True


def _number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _has_hash(payload: dict[str, Any], *fields: str) -> bool:
    return any(isinstance(payload.get(field), str) and bool(payload.get(field)) for field in fields)


def _launch_p0a_preflight_ready(p0a_design_partner: dict[str, Any]) -> bool:
    blockers = [str(item) for item in _as_list(p0a_design_partner.get("remaining_blockers"))]
    return not any("preflight" in blocker and "missing" in blocker for blocker in blockers)


def _launch_p0a_small_batch_ready(p0a_design_partner: dict[str, Any]) -> bool:
    blockers = [str(item) for item in _as_list(p0a_design_partner.get("remaining_blockers"))]
    return not any("small_batch" in blocker and "missing" in blocker for blocker in blockers)


def _phase_ready(p0a_real_batch_clearance: dict[str, Any], phase_id: str) -> bool:
    phase_items = [_as_dict(item) for item in _as_list(p0a_real_batch_clearance.get("phase_clearance_items"))]
    if phase_items:
        return any(
            item.get("phase_id") == phase_id
            and item.get("fulfilled") is True
            and item.get("request_ready") is True
            for item in phase_items
        )
    return _as_dict(p0a_real_batch_clearance.get("summary")).get(f"{phase_id}_ready") is True


def _launch_google_conclusion_ready(p0b_google: dict[str, Any]) -> bool:
    return (
        _has_hash(p0b_google, "status_report_hash")
        and _has_hash(p0b_google, "package_payload_hash")
        and p0b_google.get("status_verifier_status") == "pass"
        and p0b_google.get("package_verifier_status") == "pass"
    )


def build_trial_handoff_audit(
    *,
    launch_status: dict[str, Any] | None = None,
    p0a_credential_update_receipt: dict[str, Any] | None = None,
    p0a_credential_clearance: dict[str, Any] | None = None,
    p0a_real_batch_clearance: dict[str, Any] | None = None,
    p0b_google_environment_clearance: dict[str, Any] | None = None,
    p0b_google_manual_backfill_clearance: dict[str, Any] | None = None,
    p0b_google_phase_execution_clearance: dict[str, Any] | None = None,
    p0c_report_package: dict[str, Any] | None = None,
    handoff_dossier: dict[str, Any] | None = None,
    customer_handoff_package_manifest_ready: bool | None = None,
) -> dict[str, Any]:
    launch_status = _as_dict(launch_status)
    p0a_credential_update_receipt = _as_dict(p0a_credential_update_receipt)
    p0a_credential_clearance = _as_dict(p0a_credential_clearance)
    p0a_real_batch_clearance = _as_dict(p0a_real_batch_clearance)
    p0b_google_environment_clearance = _as_dict(p0b_google_environment_clearance)
    p0b_google_manual_backfill_clearance = _as_dict(p0b_google_manual_backfill_clearance)
    p0b_google_phase_execution_clearance = _as_dict(p0b_google_phase_execution_clearance)
    p0c_report_package = _as_dict(p0c_report_package)
    handoff_dossier = _as_dict(handoff_dossier)

    p0a_design_partner = _as_dict(launch_status.get("p0a_design_partner"))
    p0b_google = _as_dict(launch_status.get("p0b_google"))
    p0c_customer_report = _as_dict(launch_status.get("p0c_customer_report"))
    dossier_audit = _as_dict(handoff_dossier.get("customer_handoff_readiness_audit"))
    package_summary = _as_dict(p0c_report_package.get("summary"))
    p0a_receipt_summary = _as_dict(p0a_credential_update_receipt.get("summary"))
    p0a_clearance_summary = _as_dict(p0a_credential_clearance.get("summary"))

    p0a_credentials_ready = (
        p0a_credential_update_receipt.get("credential_update_receipt_complete") is True
        or p0a_credential_update_receipt.get("credentials_fulfilled") is True
        or (
            p0a_receipt_summary.get("credentials_fulfilled") is True
            and _number(p0a_receipt_summary.get("missing_required_count")) == 0.0
        )
        or p0a_credential_clearance.get("credential_clearance_ready") is True
        or p0a_credential_clearance.get("credentials_fulfilled") is True
        or (
            p0a_clearance_summary.get("credentials_fulfilled") is True
            and _number(p0a_clearance_summary.get("missing_required_count")) == 0.0
        )
    )
    p0a_preflight_ready = (
        p0a_real_batch_clearance.get("preflight_ready") is True
        or _phase_ready(p0a_real_batch_clearance, "preflight")
        or _launch_p0a_preflight_ready(p0a_design_partner)
    )
    p0a_small_batch_ready = (
        p0a_real_batch_clearance.get("small_batch_ready") is True
        or _phase_ready(p0a_real_batch_clearance, "small_batch")
        or _launch_p0a_small_batch_ready(p0a_design_partner)
    )
    p0c_ready = (
        p0c_report_package.get("p0c_report_contract_ready") is True
        or p0c_customer_report.get("p0c_report_contract_ready") is True
        or p0c_customer_report.get("status") == "pass"
    )
    google_conclusion_ready = (
        _launch_google_conclusion_ready(p0b_google)
        or p0b_google_environment_clearance.get("environment_clearance_packet_ready") is True
        or p0b_google_manual_backfill_clearance.get("manual_backfill_clearance_packet_ready") is True
        or p0b_google_phase_execution_clearance.get("phase_execution_clearance_packet_ready") is True
    )
    package_manifest_ready = customer_handoff_package_manifest_ready is True
    traceability_ready = (
        p0c_report_package.get("traceability_contract_ready") is True
        or package_summary.get("traceability_contract_ready") is True
        or "traceability_contract" in _as_list(p0c_customer_report.get("ready_artifacts"))
        or "traceability_contract" in _as_list(package_summary.get("ready_artifacts"))
    )
    structural_auditability_ready = (
        _number(dossier_audit.get("structural_auditability_percent")) == 100.0
        or _number(_as_dict(handoff_dossier.get("summary")).get("structural_auditability_percent")) == 100.0
    )

    gate_specs = {
        "trial_p0a_credentials_ready": (
            "P0a provider credentials are complete for the trial run",
            "P0a",
            p0a_credentials_ready,
            "p0a_credential_update_receipt",
        ),
        "trial_p0a_preflight_ready": (
            "P0a provider preflight evidence is ready",
            "P0a",
            p0a_preflight_ready,
            "p0a_real_batch_clearance",
        ),
        "trial_p0a_small_batch_ready": (
            "P0a 30-run small batch evidence is ready",
            "P0a",
            p0a_small_batch_ready,
            "p0a_real_batch_clearance",
        ),
        "trial_p0c_report_contract_ready": (
            "P0c report contract and artifacts are ready",
            "P0c",
            p0c_ready,
            "p0c_report_package",
        ),
        "trial_google_limited_coverage_conclusion_ready": (
            "Google limited/full coverage conclusion is ready",
            "P0b",
            google_conclusion_ready,
            "p0b_google_status",
        ),
        "trial_customer_package_manifest_ready": (
            "Customer package manifest is structurally ready",
            "handoff",
            package_manifest_ready,
            "customer_handoff_package",
        ),
        "trial_traceability_ready": (
            "Trial report traceability contract is ready",
            "audit",
            traceability_ready,
            "p0c_report_package.traceability_contract",
        ),
        "trial_structural_auditability_ready": (
            "Structural auditability remains complete",
            "audit",
            structural_auditability_ready,
            "handoff_dossier.customer_handoff_readiness_audit",
        ),
    }
    gates: list[dict[str, Any]] = []
    for gate_id in TRIAL_GATE_ORDER:
        label, stage, ready, evidence_ref = gate_specs[gate_id]
        gates.append(
            {
                "id": gate_id,
                "label": label,
                "stage": stage,
                "ready": bool(ready),
                "status": "ready" if ready else "blocked",
                "required_for_trial_handoff": True,
                "evidence_ref": evidence_ref,
            }
        )
    ready_count = len([gate for gate in gates if gate["ready"]])
    blocked_gate_ids = [str(gate["id"]) for gate in gates if not gate["ready"]]
    ready = ready_count == len(gates)
    return {
        "trial_handoff_version": TRIAL_HANDOFF_VERSION,
        "ready_for_trial_customer_handoff": ready,
        "trial_customer_handoff_readiness_percent": _percent(ready_count, len(gates)),
        "trial_ready_gate_count": ready_count,
        "trial_total_gate_count": len(gates),
        "trial_blocked_gate_count": len(blocked_gate_ids),
        "trial_blocked_gate_ids": blocked_gate_ids,
        "trial_google_coverage_mode": TRIAL_GOOGLE_COVERAGE_MODE,
        "trial_full_batch_required": False,
        "trial_full_batch_status": TRIAL_FULL_BATCH_STATUS,
        "trial_gates": gates,
    }


def compact_trial_handoff_summary(trial_audit: dict[str, Any]) -> dict[str, Any]:
    trial_audit = _as_dict(trial_audit)
    return {
        "trial_handoff_version": trial_audit.get("trial_handoff_version", TRIAL_HANDOFF_VERSION),
        "ready_for_trial_customer_handoff": trial_audit.get("ready_for_trial_customer_handoff") is True,
        "trial_customer_handoff_readiness_percent": trial_audit.get("trial_customer_handoff_readiness_percent", 0.0),
        "trial_ready_gate_count": trial_audit.get("trial_ready_gate_count", 0),
        "trial_total_gate_count": trial_audit.get("trial_total_gate_count", len(TRIAL_GATE_ORDER)),
        "trial_blocked_gate_count": trial_audit.get("trial_blocked_gate_count", len(TRIAL_GATE_ORDER)),
        "trial_blocked_gate_ids": [str(item) for item in _as_list(trial_audit.get("trial_blocked_gate_ids"))],
        "trial_google_coverage_mode": trial_audit.get("trial_google_coverage_mode", TRIAL_GOOGLE_COVERAGE_MODE),
        "trial_full_batch_required": trial_audit.get("trial_full_batch_required") is True,
        "trial_full_batch_status": trial_audit.get("trial_full_batch_status", TRIAL_FULL_BATCH_STATUS),
    }
