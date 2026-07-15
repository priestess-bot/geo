from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from geo_core.audit import build_audit_event, hash_payload
from geo_core.models import AuditEvent, RawEvidenceRecord
from geo_core.report import build_api_browser_fidelity_payload, methodology_rows_from_runtime_answer_runs


FIDELITY_CHECK_METHOD_VERSION = "api_browser_fidelity_check_v1"


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geo", kind, *(str(part) for part in parts)))))


def _rows_from_records(records: tuple[RawEvidenceRecord, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "id": record.answer_run.id,
            "prompt_question_id": record.answer_run.prompt_question_id,
            "platform": record.answer_run.platform,
            "surface": record.answer_run.surface,
            "access_method": record.answer_run.access_method,
            "city": record.answer_run.city,
            "answer_present": record.answer_run.answer_present,
            "surface_triggered": record.answer_run.surface_triggered,
            "screenshot_count": sum(1 for asset in record.evidence_assets if asset.asset_type == "screenshot"),
            "html_snapshot_count": sum(1 for asset in record.evidence_assets if asset.asset_type == "html_snapshot"),
        }
        for record in records
    )


def build_runtime_fidelity_check(
    *,
    project_id: str,
    report_export_id: str | None,
    answer_run_rows: tuple[dict[str, Any], ...],
    checked_by: str = "collector_worker",
) -> tuple[dict[str, Any], AuditEvent]:
    rows = methodology_rows_from_runtime_answer_runs(answer_run_rows)
    payload = build_api_browser_fidelity_payload(rows)
    answer_run_ids = tuple(str(row.get("id") or "") for row in answer_run_rows if row.get("id"))
    check_id = _stable_id(
        "api-browser-fidelity-check",
        project_id,
        report_export_id or "no-report",
        payload.get("status"),
        payload.get("official_api_records"),
        payload.get("browser_records"),
        payload.get("comparable_prompt_city_pairs"),
        payload.get("mismatch_count"),
        *answer_run_ids,
    )
    checked_at = datetime.now(UTC)
    fidelity_check = {
        "id": check_id,
        "project_id": project_id,
        "report_export_id": report_export_id,
        "status": payload["status"],
        "official_api_records": payload["official_api_records"],
        "browser_records": payload["browser_records"],
        "comparable_prompt_city_pairs": payload["comparable_prompt_city_pairs"],
        "mismatch_count": payload["mismatch_count"],
        "difference_rate": payload["difference_rate"],
        "payload": payload,
        "payload_hash": hash_payload(payload),
        "answer_run_ids": list(answer_run_ids),
        "checked_by": checked_by,
        "checked_at": checked_at,
    }
    audit_event = build_audit_event(
        event_type="api_browser_fidelity_checked",
        project_id=project_id,
        actor_type="system",
        actor_id=checked_by,
        target_type="api_browser_fidelity_check",
        target_id=check_id,
        before=None,
        after=fidelity_check,
        input_refs={
            "report_export_ids": [report_export_id] if report_export_id else [],
            "answer_run_ids": list(answer_run_ids),
        },
        output_refs={"api_browser_fidelity_check_ids": [check_id]},
        method_version=FIDELITY_CHECK_METHOD_VERSION,
        reason="compare official API and browser answer runs for report methodology fidelity disclosure",
    )
    return fidelity_check, audit_event


def build_runtime_fidelity_check_from_records(
    *,
    project_id: str,
    report_export_id: str | None,
    records: tuple[RawEvidenceRecord, ...],
    checked_by: str = "collector_worker",
) -> tuple[dict[str, Any], AuditEvent]:
    rows = _rows_from_records(records)
    check, audit_event = build_runtime_fidelity_check(
        project_id=project_id,
        report_export_id=report_export_id,
        answer_run_rows=rows,
        checked_by=checked_by,
    )
    return check, audit_event
