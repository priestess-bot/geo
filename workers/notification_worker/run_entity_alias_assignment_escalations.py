from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Protocol

from geno_core.repository import PostgresEvidenceRepository
from geno_core.runtime import (
    build_repository_from_env,
    close_repository_connection,
    validate_runtime_schema_compatibility,
)


WORKER_ID = "entity-alias-assignment-escalation-worker"


class EntityAliasAssignmentEscalationRepository(Protocol):
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

    def escalate_entity_alias_assignment_overdue_reviews(
        self,
        *,
        project_id: str,
        assigned_to: str | None = None,
        priority: str | None = None,
        due_before: datetime | None = None,
        escalated_by: str = WORKER_ID,
        reason: str | None = None,
    ) -> object:
        ...


def _split_project_ids(values: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    project_ids: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in str(value).split(","):
            project_id = item.strip()
            if project_id and project_id not in seen:
                project_ids.append(project_id)
                seen.add(project_id)
    return tuple(project_ids)


def _project_id_from_record(record: object) -> str | None:
    project = getattr(record, "project", None)
    if not isinstance(project, dict):
        return None
    project_id = str(project.get("id") or "").strip()
    return project_id or None


def _discover_project_ids(
    repository: EntityAliasAssignmentEscalationRepository,
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


def _parse_due_before(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).astimezone(UTC)


def escalate_entity_alias_assignment_reviews_for_projects(
    *,
    repository: EntityAliasAssignmentEscalationRepository,
    project_ids: tuple[str, ...] = (),
    market_code: str | None = None,
    assigned_to: str | None = None,
    priority: str | None = None,
    due_before: datetime | None = None,
    worker_id: str = WORKER_ID,
    reason: str = "entity alias assignment escalation worker scan",
    max_projects: int = 50,
    page_size: int = 50,
) -> dict[str, Any]:
    selected_project_ids = _split_project_ids(project_ids)
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
            "reason": "no runtime projects matched alias assignment escalation worker filters",
            "project_count": 0,
            "escalation_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "results": [],
            "discovered_projects": discovered,
        }

    results: list[dict[str, Any]] = []
    escalation_count = 0
    skipped_count = 0
    failed_count = 0
    for project_id in selected_project_ids:
        try:
            record = repository.escalate_entity_alias_assignment_overdue_reviews(
                project_id=project_id,
                assigned_to=assigned_to,
                priority=priority,
                due_before=due_before,
                escalated_by=worker_id,
                reason=reason,
            )
            payload = asdict(record)
            project_escalation_count = int(payload.get("escalation_count") or 0)
            project_skipped_count = int(payload.get("skipped_count") or 0)
            escalation_count += project_escalation_count
            skipped_count += project_skipped_count
            results.append(
                {
                    "project_id": project_id,
                    "status": "escalated",
                    "escalation_count": project_escalation_count,
                    "skipped_count": project_skipped_count,
                    "audit_event_count": len(payload.get("audit_events") or ()),
                }
            )
        except Exception as exc:
            failed_count += 1
            results.append({"project_id": project_id, "status": "failed", "error_message": str(exc)})

    return {
        "processed": True,
        "status": "completed_with_errors" if failed_count else "completed",
        "project_count": len(selected_project_ids),
        "escalation_count": escalation_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "results": results,
        "discovered_projects": discovered,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Escalate overdue GENO entity alias assignment reviews")
    parser.add_argument(
        "--project-id",
        action="append",
        default=[],
        help="Project id to scan. May be repeated or comma-separated. If omitted, projects are discovered.",
    )
    parser.add_argument("--market-code", default=None, help="Optional market code filter when discovering projects.")
    parser.add_argument("--assigned-to", default=None, help="Optional reviewer assignee filter.")
    parser.add_argument("--priority", default=None, help="Optional priority filter.")
    parser.add_argument("--due-before", default=None, help="Optional ISO datetime cutoff. Defaults to now.")
    parser.add_argument("--worker-id", default=WORKER_ID, help="Actor id used in escalation audit events.")
    parser.add_argument("--reason", default="entity alias assignment escalation worker scan", help="Audit reason.")
    parser.add_argument("--max-projects", type=int, default=50, help="Maximum discovered projects to scan.")
    parser.add_argument("--page-size", type=int, default=50, help="Project discovery page size.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_runtime_schema_compatibility()
    repository: PostgresEvidenceRepository | None = None
    try:
        repository = build_repository_from_env()
        result = escalate_entity_alias_assignment_reviews_for_projects(
            repository=repository,
            project_ids=tuple(args.project_id),
            market_code=args.market_code,
            assigned_to=args.assigned_to,
            priority=args.priority,
            due_before=_parse_due_before(args.due_before),
            worker_id=args.worker_id,
            reason=args.reason,
            max_projects=args.max_projects,
            page_size=args.page_size,
        )
    finally:
        if repository is not None:
            close_repository_connection(repository)
    print(json.dumps({"worker": WORKER_ID, **result}, default=str))


if __name__ == "__main__":
    main()
