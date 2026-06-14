from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Protocol

from geno_core.models import EntityAliasAssignmentDispatchApplyInput
from geno_core.repository import PostgresEvidenceRepository
from geno_core.runtime import build_repository_from_env, close_repository_connection


WORKER_ID = "entity-alias-assignment-dispatch-apply-worker"


class EntityAliasAssignmentDispatchApplyRepository(Protocol):
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

    def apply_entity_alias_assignment_dispatch_plan(
        self,
        apply_input: EntityAliasAssignmentDispatchApplyInput,
    ) -> object:
        ...


def _split_csv_values(values: tuple[str, ...] | list[str] | str | None) -> tuple[str, ...]:
    if not values:
        return ()
    raw_values: tuple[str, ...]
    if isinstance(values, str):
        raw_values = (values,)
    else:
        raw_values = tuple(values)
    items: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        for item in str(value).split(","):
            normalized = item.strip()
            if normalized and normalized not in seen:
                items.append(normalized)
                seen.add(normalized)
    return tuple(items)


def _project_id_from_record(record: object) -> str | None:
    project = getattr(record, "project", None)
    if not isinstance(project, dict):
        return None
    project_id = str(project.get("id") or "").strip()
    return project_id or None


def _discover_project_ids(
    repository: EntityAliasAssignmentDispatchApplyRepository,
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


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).astimezone(UTC)


def apply_entity_alias_assignment_dispatch_for_projects(
    *,
    repository: EntityAliasAssignmentDispatchApplyRepository,
    project_ids: tuple[str, ...] = (),
    market_code: str | None = None,
    reviewer_ids: tuple[str, ...] = (),
    include_statuses: tuple[str, ...] = ("unassigned", "escalated"),
    max_per_reviewer: int = 10,
    due_soon_before: datetime | None = None,
    limit_per_project: int = 50,
    worker_id: str = WORKER_ID,
    assignment_status: str = "assigned",
    priority: str | None = None,
    due_at: datetime | None = None,
    assignment_note: str | None = None,
    reason: str = "entity alias assignment dispatch apply worker scan",
    continue_on_error: bool = True,
    max_projects: int = 50,
    page_size: int = 50,
) -> dict[str, Any]:
    selected_project_ids = _split_csv_values(project_ids)
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
            "reason": "no runtime projects matched alias assignment dispatch apply worker filters",
            "project_count": 0,
            "requested_count": 0,
            "applied_count": 0,
            "failed_count": 0,
            "results": [],
            "discovered_projects": discovered,
        }

    normalized_reviewer_ids = _split_csv_values(reviewer_ids)
    normalized_statuses = _split_csv_values(include_statuses) or ("unassigned", "escalated")
    results: list[dict[str, Any]] = []
    requested_count = 0
    applied_count = 0
    failed_count = 0
    project_failure_count = 0
    for project_id in selected_project_ids:
        try:
            record = repository.apply_entity_alias_assignment_dispatch_plan(
                EntityAliasAssignmentDispatchApplyInput(
                    project_id=project_id,
                    reviewer_ids=normalized_reviewer_ids,
                    include_statuses=normalized_statuses,
                    max_per_reviewer=max_per_reviewer,
                    due_soon_before=due_soon_before,
                    limit=limit_per_project,
                    applied_by=worker_id,
                    assignment_status=assignment_status,
                    priority=priority,
                    due_at=due_at,
                    assignment_note=assignment_note or reason,
                    reason=reason,
                    continue_on_error=continue_on_error,
                )
            )
            payload = asdict(record)
            project_requested_count = int(payload.get("requested_count") or 0)
            project_applied_count = int(payload.get("applied_count") or 0)
            project_failed_count = int(payload.get("failed_count") or 0)
            requested_count += project_requested_count
            applied_count += project_applied_count
            failed_count += project_failed_count
            results.append(
                {
                    "project_id": project_id,
                    "status": "applied" if project_failed_count == 0 else "applied_with_errors",
                    "requested_count": project_requested_count,
                    "applied_count": project_applied_count,
                    "failed_count": project_failed_count,
                    "planned_assignment_count": int(
                        (payload.get("dispatch_plan") or {}).get("planned_assignment_count") or 0
                    ),
                    "audit_event_count": len(payload.get("records") or ()) + (1 if payload.get("audit_summary") else 0),
                }
            )
        except Exception as exc:
            project_failure_count += 1
            results.append({"project_id": project_id, "status": "failed", "error_message": str(exc)})

    return {
        "processed": True,
        "status": "completed_with_errors" if project_failure_count or failed_count else "completed",
        "project_count": len(selected_project_ids),
        "requested_count": requested_count,
        "applied_count": applied_count,
        "failed_count": failed_count,
        "project_failure_count": project_failure_count,
        "results": results,
        "discovered_projects": discovered,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply GENO entity alias assignment dispatch plans")
    parser.add_argument(
        "--project-id",
        action="append",
        default=[],
        help="Project id to scan. May be repeated or comma-separated. If omitted, projects are discovered.",
    )
    parser.add_argument("--market-code", default=None, help="Optional market code filter when discovering projects.")
    parser.add_argument("--reviewer-id", action="append", default=[], help="Eligible reviewer id. May be repeated.")
    parser.add_argument(
        "--include-statuses",
        default="unassigned,escalated",
        help="Comma-separated current statuses eligible for dispatch apply.",
    )
    parser.add_argument("--max-per-reviewer", type=int, default=10, help="Maximum active assignments per reviewer.")
    parser.add_argument("--due-soon-before", default=None, help="Optional ISO datetime used in workload summary.")
    parser.add_argument("--limit-per-project", type=int, default=50, help="Maximum planned assignments per project.")
    parser.add_argument("--assignment-status", default="assigned", help="Target assignment status.")
    parser.add_argument("--priority", default=None, help="Optional target priority override.")
    parser.add_argument("--due-at", default=None, help="Optional target due date override.")
    parser.add_argument("--worker-id", default=WORKER_ID, help="Actor id used in dispatch apply audit events.")
    parser.add_argument("--reason", default="entity alias assignment dispatch apply worker scan", help="Audit reason.")
    parser.add_argument("--max-projects", type=int, default=50, help="Maximum discovered projects to scan.")
    parser.add_argument("--page-size", type=int, default=50, help="Project discovery page size.")
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop a project dispatch apply on the first per-candidate error.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repository: PostgresEvidenceRepository | None = None
    try:
        repository = build_repository_from_env()
        result = apply_entity_alias_assignment_dispatch_for_projects(
            repository=repository,
            project_ids=tuple(args.project_id),
            market_code=args.market_code,
            reviewer_ids=tuple(args.reviewer_id),
            include_statuses=_split_csv_values(args.include_statuses) or ("unassigned", "escalated"),
            max_per_reviewer=args.max_per_reviewer,
            due_soon_before=_parse_datetime(args.due_soon_before),
            limit_per_project=args.limit_per_project,
            worker_id=args.worker_id,
            assignment_status=args.assignment_status,
            priority=args.priority,
            due_at=_parse_datetime(args.due_at),
            assignment_note=args.reason,
            reason=args.reason,
            continue_on_error=not args.stop_on_error,
            max_projects=args.max_projects,
            page_size=args.page_size,
        )
    finally:
        if repository is not None:
            close_repository_connection(repository)
    print(json.dumps({"worker": WORKER_ID, **result}, default=str))


if __name__ == "__main__":
    main()
