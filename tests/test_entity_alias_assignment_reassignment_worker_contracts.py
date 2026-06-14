from __future__ import annotations

import unittest
from datetime import UTC, datetime

from geno_core.models import (
    RuntimeEntityAliasAssignmentReassignmentResult,
    RuntimeProject,
    RuntimeProjectPage,
)
from workers.notification_worker.run_entity_alias_assignment_reassignments import (
    reassign_entity_alias_assignment_reviews_for_projects,
)


class FakeEntityAliasAssignmentReassignmentRepository:
    def __init__(
        self,
        *,
        project_ids: tuple[str, ...],
        reassignment_counts: dict[str, int] | None = None,
        fail_project_id: str | None = None,
    ) -> None:
        self.project_ids = project_ids
        self.reassignment_counts = reassignment_counts or {}
        self.fail_project_id = fail_project_id
        self.list_project_calls: list[dict[str, object]] = []
        self.reassignment_calls: list[object] = []

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

    def reassign_entity_alias_candidate_reviews(self, reassignment) -> RuntimeEntityAliasAssignmentReassignmentResult:
        if reassignment.project_id == self.fail_project_id:
            raise RuntimeError("alias assignment reassignment read model failed")
        self.reassignment_calls.append(reassignment)
        reassignment_count = self.reassignment_counts.get(reassignment.project_id, 0)
        return RuntimeEntityAliasAssignmentReassignmentResult(
            project_id=reassignment.project_id,
            reassignment_count=reassignment_count,
            skipped_count=0,
            reassigned_reviews=tuple({"id": f"review-{index}"} for index in range(reassignment_count)),
            audit_events=tuple(
                {"event_type": "entity_alias_candidate_assignment_reassigned"} for _ in range(reassignment_count)
            ),
        )


class EntityAliasAssignmentReassignmentWorkerContractsTest(unittest.TestCase):
    def test_worker_discovers_projects_and_reassigns_escalated_assignments(self) -> None:
        due_at = datetime(2026, 6, 21, tzinfo=UTC)
        repository = FakeEntityAliasAssignmentReassignmentRepository(
            project_ids=("project-1", "project-2"),
            reassignment_counts={"project-1": 2, "project-2": 1},
        )

        result = reassign_entity_alias_assignment_reviews_for_projects(
            repository=repository,
            market_code="AU",
            assigned_to="reviewer-b@example.com",
            from_assignment_status="escalated",
            priority="high",
            due_at=due_at,
            worker_id="alias-reassignment-worker",
            reason="scheduled alias assignment reassignment",
        )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["discovered_projects"])
        self.assertEqual(result["project_count"], 2)
        self.assertEqual(result["reassignment_count"], 3)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual(repository.list_project_calls[0]["market_code"], "AU")
        self.assertEqual(repository.reassignment_calls[0].assigned_to, "reviewer-b@example.com")
        self.assertEqual(repository.reassignment_calls[0].from_assignment_status, "escalated")
        self.assertEqual(repository.reassignment_calls[0].due_at, due_at)
        self.assertEqual(repository.reassignment_calls[0].reassigned_by, "alias-reassignment-worker")

    def test_worker_uses_explicit_projects_and_continues_after_failure(self) -> None:
        repository = FakeEntityAliasAssignmentReassignmentRepository(
            project_ids=("ignored-project",),
            reassignment_counts={"project-2": 1},
            fail_project_id="project-1",
        )

        result = reassign_entity_alias_assignment_reviews_for_projects(
            repository=repository,
            project_ids=("project-1, project-2", "project-2"),
            assigned_to="reviewer-b@example.com",
        )

        self.assertEqual(result["status"], "completed_with_errors")
        self.assertFalse(result["discovered_projects"])
        self.assertEqual(result["project_count"], 2)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["reassignment_count"], 1)
        self.assertEqual(repository.list_project_calls, [])
        self.assertIn("alias assignment reassignment read model failed", str(result["results"][0]["error_message"]))

    def test_worker_requires_target_assignee(self) -> None:
        repository = FakeEntityAliasAssignmentReassignmentRepository(project_ids=("project-1",))

        with self.assertRaisesRegex(ValueError, "assigned_to is required"):
            reassign_entity_alias_assignment_reviews_for_projects(repository=repository, assigned_to=" ")


if __name__ == "__main__":
    unittest.main()
