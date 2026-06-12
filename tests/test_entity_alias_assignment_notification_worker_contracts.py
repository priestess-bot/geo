from __future__ import annotations

import unittest
from datetime import UTC, datetime

from geno_core.models import RuntimeEntityAliasAssignmentNotificationResult, RuntimeProject, RuntimeProjectPage
from workers.notification_worker.run_entity_alias_assignment_notifications import (
    enqueue_entity_alias_assignment_notifications_for_projects,
)


class FakeEntityAliasAssignmentNotificationRepository:
    def __init__(self, *, project_ids: tuple[str, ...], fail_project_id: str | None = None) -> None:
        self.project_ids = project_ids
        self.fail_project_id = fail_project_id
        self.list_calls: list[dict[str, object]] = []
        self.enqueue_calls: list[dict[str, object]] = []

    def list_runtime_projects(
        self,
        *,
        project_id: str | None = None,
        market_code: str | None = None,
        actor_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeProjectPage:
        self.list_calls.append(
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

    def enqueue_entity_alias_assignment_overdue_notifications(
        self,
        *,
        project_id: str,
        assigned_to: str | None = None,
        priority: str | None = None,
        due_before: datetime | None = None,
        created_by: str = "entity-alias-assignment-notification-worker",
        reason: str | None = None,
    ) -> RuntimeEntityAliasAssignmentNotificationResult:
        self.enqueue_calls.append(
            {
                "project_id": project_id,
                "assigned_to": assigned_to,
                "priority": priority,
                "due_before": due_before,
                "created_by": created_by,
                "reason": reason,
            }
        )
        if project_id == self.fail_project_id:
            raise RuntimeError("alias assignment read model failed")
        return RuntimeEntityAliasAssignmentNotificationResult(
            project_id=project_id,
            notification_count=2,
            delivery_count=1,
            skipped_count=0,
            notifications=({"id": f"notification-{project_id}"},),
            audit_events=({"event_type": "runtime_notification_created"},),
        )


class EntityAliasAssignmentNotificationWorkerContractsTest(unittest.TestCase):
    def test_worker_discovers_projects_and_enqueues_assignment_notifications(self) -> None:
        repository = FakeEntityAliasAssignmentNotificationRepository(project_ids=("project-1", "project-2", "project-3"))
        due_before = datetime(2026, 6, 13, tzinfo=UTC)

        result = enqueue_entity_alias_assignment_notifications_for_projects(
            repository=repository,
            market_code="AU",
            assigned_to="reviewer@example.com",
            priority="urgent",
            due_before=due_before,
            worker_id="alias-assignment-worker",
            reason="scheduled alias assignment scan",
            max_projects=2,
            page_size=1,
        )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["discovered_projects"])
        self.assertEqual(result["project_count"], 2)
        self.assertEqual(result["notification_count"], 4)
        self.assertEqual(result["delivery_count"], 2)
        self.assertEqual([call["project_id"] for call in repository.enqueue_calls], ["project-1", "project-2"])
        self.assertEqual(repository.list_calls[0]["market_code"], "AU")
        self.assertEqual(repository.list_calls[0]["limit"], 1)
        self.assertEqual(repository.enqueue_calls[0]["assigned_to"], "reviewer@example.com")
        self.assertEqual(repository.enqueue_calls[0]["priority"], "urgent")
        self.assertEqual(repository.enqueue_calls[0]["due_before"], due_before)
        self.assertEqual(repository.enqueue_calls[0]["created_by"], "alias-assignment-worker")
        self.assertEqual(repository.enqueue_calls[0]["reason"], "scheduled alias assignment scan")

    def test_worker_uses_explicit_project_ids_without_project_discovery(self) -> None:
        repository = FakeEntityAliasAssignmentNotificationRepository(project_ids=("ignored-project",))

        result = enqueue_entity_alias_assignment_notifications_for_projects(
            repository=repository,
            project_ids=("project-1, project-2", "project-1"),
            max_projects=10,
        )

        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["discovered_projects"])
        self.assertEqual([call["project_id"] for call in repository.enqueue_calls], ["project-1", "project-2"])
        self.assertEqual(repository.list_calls, [])

    def test_worker_reports_per_project_failures_and_continues(self) -> None:
        repository = FakeEntityAliasAssignmentNotificationRepository(
            project_ids=("project-1", "project-2"),
            fail_project_id="project-2",
        )

        result = enqueue_entity_alias_assignment_notifications_for_projects(repository=repository, market_code="AU")

        self.assertEqual(result["status"], "completed_with_errors")
        self.assertEqual(result["project_count"], 2)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["notification_count"], 2)
        self.assertEqual(result["results"][1]["status"], "failed")
        self.assertIn("alias assignment read model failed", str(result["results"][1]["error_message"]))

    def test_worker_idles_when_no_projects_match(self) -> None:
        repository = FakeEntityAliasAssignmentNotificationRepository(project_ids=())

        result = enqueue_entity_alias_assignment_notifications_for_projects(repository=repository, market_code="AU")

        self.assertFalse(result["processed"])
        self.assertEqual(result["status"], "idle")
        self.assertEqual(result["project_count"], 0)
        self.assertEqual(repository.enqueue_calls, [])


if __name__ == "__main__":
    unittest.main()
