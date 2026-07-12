from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Protocol

from geno_core.models import RuntimeAlertEventInput
from geno_core.repository import PostgresEvidenceRepository
from geno_core.runtime import (
    build_repository_from_env,
    close_repository_connection,
    validate_runtime_schema_compatibility,
)


WORKER_ID = "runtime-alert-escalation-worker"
DEFAULT_ESCALATION_STATUSES = {"acknowledged", "resolved", "snoozed", "escalated"}
DEFAULT_SEVERITY_THRESHOLDS_HOURS = {"critical": 4, "high": 24}


class RuntimeAlertEscalationRepository(Protocol):
    def list_runtime_projects(
        self,
        *,
        project_id: str | None = None,
        market_code: str | None = None,
        actor_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> object:
        ...

    def list_runtime_alerts(
        self,
        *,
        project_id: str | None = None,
        alert_type: str | None = None,
        severity: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> object:
        ...

    def record_runtime_alert_event(self, event: RuntimeAlertEventInput) -> object:
        ...


def _split_values(values: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in str(value).split(","):
            normalized = item.strip()
            if normalized and normalized not in seen:
                selected.append(normalized)
                seen.add(normalized)
    return tuple(selected)


def _project_id_from_record(record: object) -> str | None:
    project = getattr(record, "project", None)
    if not isinstance(project, dict):
        return None
    project_id = str(project.get("id") or "").strip()
    return project_id or None


def _discover_project_ids(
    repository: RuntimeAlertEscalationRepository,
    *,
    market_code: str | None,
    max_projects: int,
    page_size: int,
) -> tuple[str, ...]:
    max_projects = max(1, int(max_projects))
    page_size = max(1, min(int(page_size), 200, max_projects))
    project_ids: list[str] = []
    offset = 0
    while len(project_ids) < max_projects:
        page = repository.list_runtime_projects(
            market_code=market_code,
            limit=min(page_size, max_projects - len(project_ids)),
            offset=offset,
        )
        records = tuple(getattr(page, "records", ()))
        if not records:
            break
        for record in records:
            project_id = _project_id_from_record(record)
            if project_id:
                project_ids.append(project_id)
                if len(project_ids) >= max_projects:
                    break
        offset += len(records)
        total_count = int(getattr(page, "total_count", 0) or 0)
        if offset >= total_count:
            break
    return tuple(project_ids)


def _parse_severity_thresholds(raw: str | None) -> dict[str, int]:
    if not raw:
        return dict(DEFAULT_SEVERITY_THRESHOLDS_HOURS)
    thresholds: dict[str, int] = {}
    for item in raw.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError("severity thresholds must use severity=hours entries")
        severity, hours = item.split("=", 1)
        severity = severity.strip().lower()
        if not severity:
            raise ValueError("severity threshold severity is required")
        thresholds[severity] = max(0, int(hours.strip()))
    if not thresholds:
        raise ValueError("at least one severity threshold is required")
    return thresholds


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _is_due(alert: dict[str, Any], *, threshold_hours: int, now: datetime) -> tuple[bool, int | None]:
    created_at = _parse_datetime(alert.get("created_at"))
    if created_at is None:
        return False, None
    age_hours = int((now - created_at).total_seconds() // 3600)
    return age_hours >= threshold_hours, age_hours


def escalate_runtime_alerts_for_projects(
    *,
    repository: RuntimeAlertEscalationRepository,
    project_ids: tuple[str, ...] = (),
    market_code: str | None = None,
    alert_type: str | None = None,
    severity_thresholds_hours: dict[str, int] | None = None,
    skip_statuses: set[str] | None = None,
    worker_id: str = WORKER_ID,
    note: str = "Runtime alert breached escalation threshold",
    max_projects: int = 50,
    page_size: int = 50,
    max_alerts_per_project: int = 200,
    now: datetime | None = None,
) -> dict[str, Any]:
    thresholds = severity_thresholds_hours or DEFAULT_SEVERITY_THRESHOLDS_HOURS
    selected_project_ids = _split_values(project_ids)
    selected_skip_statuses = {status.strip().lower() for status in (skip_statuses or DEFAULT_ESCALATION_STATUSES)}
    clock = now or datetime.now(UTC)
    discovered = False
    if not selected_project_ids:
        selected_project_ids = _discover_project_ids(
            repository,
            market_code=market_code,
            max_projects=max_projects,
            page_size=page_size,
        )
        discovered = True
    if not selected_project_ids:
        return {
            "processed": False,
            "status": "idle",
            "reason": "no runtime projects matched alert escalation worker filters",
            "project_count": 0,
            "alert_count": 0,
            "escalated_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "results": [],
            "discovered_projects": discovered,
        }

    results: list[dict[str, Any]] = []
    alert_count = 0
    escalated_count = 0
    skipped_count = 0
    failed_count = 0
    for project_id in selected_project_ids:
        project_result = {
            "project_id": project_id,
            "status": "scanned",
            "alert_count": 0,
            "escalated_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "audit_event_count": 0,
        }
        try:
            for severity, threshold_hours in thresholds.items():
                page = repository.list_runtime_alerts(
                    project_id=project_id,
                    alert_type=alert_type,
                    severity=severity,
                    limit=max_alerts_per_project,
                    offset=0,
                )
                for item in tuple(getattr(page, "records", ())):
                    alert = dict(getattr(item, "alert", {}) or {})
                    management_events = tuple(getattr(item, "management_events", ()) or ())
                    latest_status = (
                        str(management_events[0].get("status") or "").strip().lower()
                        if management_events and isinstance(management_events[0], dict)
                        else ""
                    )
                    project_result["alert_count"] += 1
                    alert_count += 1
                    due, age_hours = _is_due(alert, threshold_hours=threshold_hours, now=clock)
                    if latest_status in selected_skip_statuses or not due:
                        project_result["skipped_count"] += 1
                        skipped_count += 1
                        continue
                    event = RuntimeAlertEventInput(
                        project_id=project_id,
                        alert_id=str(alert.get("id") or "").strip(),
                        alert_type=str(alert.get("alert_type") or "runtime_alert").strip(),
                        source=str(alert.get("source") or "runtime_alert").strip(),
                        source_id=str(alert.get("source_id") or alert.get("id") or "").strip(),
                        status="escalated",
                        updated_by=worker_id,
                        note=note,
                        metadata={
                            "escalation_policy_version": "runtime_alert_escalation_worker_v1",
                            "severity": severity,
                            "threshold_hours": threshold_hours,
                            "alert_age_hours": age_hours,
                            "latest_management_status": latest_status or None,
                        },
                    )
                    record = repository.record_runtime_alert_event(event)
                    payload = asdict(record)
                    project_result["escalated_count"] += 1
                    project_result["audit_event_count"] += len(payload.get("audit_events") or ())
                    escalated_count += 1
        except Exception as exc:
            project_result["status"] = "failed"
            project_result["error_message"] = str(exc)
            project_result["failed_count"] += 1
            failed_count += 1
        results.append(project_result)

    return {
        "processed": True,
        "status": "completed_with_errors" if failed_count else "completed",
        "project_count": len(selected_project_ids),
        "alert_count": alert_count,
        "escalated_count": escalated_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "results": results,
        "discovered_projects": discovered,
        "severity_thresholds_hours": thresholds,
        "skip_statuses": sorted(selected_skip_statuses),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Escalate overdue GENO runtime alerts for matching projects")
    parser.add_argument(
        "--project-id",
        action="append",
        default=[],
        help="Project id to scan. May be repeated or comma-separated. If omitted, projects are discovered.",
    )
    parser.add_argument("--market-code", default=None, help="Optional market code filter when discovering projects.")
    parser.add_argument("--alert-type", default=None, help="Optional runtime alert type filter.")
    parser.add_argument(
        "--severity-threshold-hours",
        default="critical=4,high=24",
        help="Comma-separated severity=hours policy. Default: critical=4,high=24.",
    )
    parser.add_argument(
        "--skip-status",
        action="append",
        default=["acknowledged,resolved,snoozed,escalated"],
        help="Latest management status to skip. May be repeated or comma-separated.",
    )
    parser.add_argument("--worker-id", default=WORKER_ID, help="Actor id used in escalation audit events.")
    parser.add_argument("--note", default="Runtime alert breached escalation threshold", help="Alert event note.")
    parser.add_argument("--max-projects", type=int, default=50, help="Maximum discovered projects to scan.")
    parser.add_argument("--page-size", type=int, default=50, help="Project discovery page size.")
    parser.add_argument("--max-alerts-per-project", type=int, default=200, help="Alert page size per project/severity.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_runtime_schema_compatibility()
    repository: PostgresEvidenceRepository | None = None
    try:
        repository = build_repository_from_env()
        result = escalate_runtime_alerts_for_projects(
            repository=repository,
            project_ids=tuple(args.project_id),
            market_code=args.market_code,
            alert_type=args.alert_type,
            severity_thresholds_hours=_parse_severity_thresholds(args.severity_threshold_hours),
            skip_statuses=set(_split_values(args.skip_status)),
            worker_id=args.worker_id,
            note=args.note,
            max_projects=args.max_projects,
            page_size=args.page_size,
            max_alerts_per_project=args.max_alerts_per_project,
        )
    finally:
        if repository is not None:
            close_repository_connection(repository)
    print(json.dumps({"worker": WORKER_ID, **result}, default=str))


if __name__ == "__main__":
    main()
