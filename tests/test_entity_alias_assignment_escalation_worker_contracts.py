from __future__ import annotations

import unittest
from datetime import UTC, datetime

from geno_core.models import (
    RuntimeEntityAliasAssignmentEscalationResult,
    RuntimeProject,
    RuntimeProjectPage,
)
from workers.notification_worker.run_entity_alias_assignment_escalations import (
    escalate_entity_alias_assignment_reviews_for_projects,
)


class FakeEntityAliasAssignmentEscalationRepository:
    def __init__(
        self,
        *,
        project_ids: tuple[str, ...],
        escalation_counts: dict[str, int] | None = None,
        fail_project_id: str | None = None,
    ) -> None:
        self.project_ids = project_ids
        self.escalation_counts = escalation_counts or {}
        self.fail_project_id = fail_project_id
        self.list_project_calls: list[dict[str, object]] = []
        self.escalation_calls: list[dict[str, object]] = []

    def list_runtime_projects(
        self,
        *,
        project_id: str | None = None,
        market_code: str | None = None,
        actor_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeProjectPage:
        self.list_project_calls.append(
            {
                "project_id": project_id,
                "market_code": market_code,
                "actor_id": actor_id,
                "limit": limit,
                "offset": offset,
            }
        )
        selected = self.project_ids[offset : offset + limit]
        records = tuple(
            RuntimeProject(
                project={"id": project_id, "market_code": market_code or "AU"},
                tenant={},
                brand=None,
                competitors=(),
                prompt_count=0,
                audit_events=(),
            )
            for project_id in selected
        )
        return RuntimeProjectPage(total_count=len(self.project_ids), limit=limit, offset=offset, records=records)

    def escalate_entity_alias_assignment_overdue_reviews(
        self,
        *,
        project_id: str,
        assigned_to: str | None = None,
        priority: str | None = None,
        due_before: datetime | None = None,
        escalated_by: str = "entity-alias-assignment-escalation-worker",
        reason: str | None = None,
    ) -> RuntimeEntityAliasAssignmentEscalationResult:
        if project_id == self.fail_project_id:
            raise RuntimeError("alias assignment escalation read model failed")
        self.escalation_calls.append(
            {
                "project_id": project_id,
                "assigned_to": assigned_to,
                "priority": priority,
                "due_before": due_before,
                "escalated_by": escalated_by,
                "reason": reason,
            }
        )
        escalation_count = self.escalation_counts.get(project_id, 0)
        return RuntimeEntityAliasAssignmentEscalationResult(
            project_id=project_id,
            escalation_count=escalation_count,
            skipped_count=0,
            escalated_reviews=tuple({"id": f"review-{index}"} for index in range(escalation_count)),
            audit_events=tuple({"event_type": "entity_alias_candidate_assignment_escalated"} for _ in range(escalation_count)),
        )


class EntityAliasAssignmentEscalationWorkerContractsTest(unittest.TestCase):
    def test_worker_discovers_projects_and_escalates_overdue_assignments(self) -> None:
        due_before = datetime(2026, 6, 14, 9, 0, tzinfo=UTC)
        repository = FakeEntityAliasAssignmentEscalationRepository(
            project_ids=("project-1", "project-2"),
            escalation_counts={"project-1": 2, "project-2": 1},
        )

        result = escalate_entity_alias_assignment_reviews_for_projects(
            repository=repository,
            market_code="AU",
            assigned_to="reviewer@example.com",
            priority="urgent",
            due_before=due_before,
            worker_id="alias-escalation-worker",
            reason="scheduled alias assignment escalation",
        )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["discovered_projects"])
        self.assertEqual(result["project_count"], 2)
        self.assertEqual(result["escalation_count"], 3)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual(repository.list_project_calls[0]["market_code"], "AU")
        self.assertEqual(repository.escalation_calls[0]["assigned_to"], "reviewer@example.com")
        self.assertEqual(repository.escalation_calls[0]["priority"], "urgent")
        self.assertEqual(repository.escalation_calls[0]["due_before"], due_before)
        self.assertEqual(repository.escalation_calls[0]["escalated_by"], "alias-escalation-worker")

    def test_worker_uses_explicit_projects_and_continues_after_failure(self) -> None:
        repository = FakeEntityAliasAssignmentEscalationRepository(
            project_ids=("ignored-project",),
            escalation_counts={"project-2": 1},
            fail_project_id="project-1",
        )

        result = escalate_entity_alias_assignment_reviews_for_projects(
            repository=repository,
            project_ids=("project-1, project-2", "project-2"),
        )

        self.assertEqual(result["status"], "completed_with_errors")
        self.assertFalse(result["discovered_projects"])
        self.assertEqual(result["project_count"], 2)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["escalation_count"], 1)
        self.assertEqual(repository.list_project_calls, [])
        self.assertIn("alias assignment escalation read model failed", str(result["results"][0]["error_message"]))

    def test_worker_idles_when_no_projects_match(self) -> None:
        repository = FakeEntityAliasAssignmentEscalationRepository(project_ids=())

        result = escalate_entity_alias_assignment_reviews_for_projects(repository=repository, market_code="AU")

        self.assertFalse(result["processed"])
        self.assertEqual(result["status"], "idle")
        self.assertEqual(result["project_count"], 0)
        self.assertEqual(repository.escalation_calls, [])


if __name__ == "__main__":
    unittest.main()
