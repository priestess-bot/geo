from __future__ import annotations

import unittest
from datetime import UTC, datetime

from geno_core.models import (
    RuntimeEntityAliasAssignmentDispatchApplyResult,
    RuntimeEntityAliasAssignmentDispatchPlan,
    RuntimeEntityAliasCandidateReview,
    RuntimeProject,
    RuntimeProjectPage,
)
from workers.notification_worker.run_entity_alias_assignment_dispatch_apply import (
    apply_entity_alias_assignment_dispatch_for_projects,
)


class FakeEntityAliasAssignmentDispatchApplyRepository:
    def __init__(
        self,
        *,
        project_ids: tuple[str, ...],
        applied_counts: dict[str, int] | None = None,
        failed_counts: dict[str, int] | None = None,
        fail_project_id: str | None = None,
    ) -> None:
        self.project_ids = project_ids
        self.applied_counts = applied_counts or {}
        self.failed_counts = failed_counts or {}
        self.fail_project_id = fail_project_id
        self.list_project_calls: list[dict[str, object]] = []
        self.apply_calls: list[object] = []

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

    def apply_entity_alias_assignment_dispatch_plan(self, apply_input) -> RuntimeEntityAliasAssignmentDispatchApplyResult:
        if apply_input.project_id == self.fail_project_id:
            raise RuntimeError("alias assignment dispatch apply failed")
        self.apply_calls.append(apply_input)
        applied_count = self.applied_counts.get(apply_input.project_id, 0)
        failed_count = self.failed_counts.get(apply_input.project_id, 0)
        requested_count = applied_count + failed_count
        plan = RuntimeEntityAliasAssignmentDispatchPlan(
            project_id=apply_input.project_id,
            generated_at=datetime(2026, 6, 15, tzinfo=UTC),
            method_version="entity_alias_assignment_dispatch_plan_v1",
            dry_run=True,
            strategy="least_loaded_round_robin",
            include_statuses=apply_input.include_statuses,
            reviewer_ids=apply_input.reviewer_ids,
            active_statuses=("assigned", "in_progress", "blocked", "escalated"),
            max_per_reviewer=apply_input.max_per_reviewer,
            candidate_count=requested_count,
            planned_assignment_count=requested_count,
            skipped_count=0,
            reviewer_loads=(),
            proposed_assignments=tuple({"candidate_id": f"candidate-{index}"} for index in range(requested_count)),
            skipped_candidates=(),
            source_summary={"dry_run_does_not_write_assignment_state": True},
        )
        return RuntimeEntityAliasAssignmentDispatchApplyResult(
            project_id=apply_input.project_id,
            method_version="entity_alias_assignment_dispatch_apply_v1",
            requested_count=requested_count,
            applied_count=applied_count,
            failed_count=failed_count,
            records=tuple(
                RuntimeEntityAliasCandidateReview(
                    review={"id": f"review-{index}", "candidate_id": f"candidate-{index}"},
                    audit_events=({"event_type": "entity_alias_candidate_assignment_dispatch_applied"},),
                )
                for index in range(applied_count)
            ),
            errors=tuple({"candidate_id": f"failed-{index}", "error": "status changed"} for index in range(failed_count)),
            dispatch_plan=plan,
            audit_summary={"event_type": "entity_alias_assignment_dispatch_plan_applied"},
        )


class EntityAliasAssignmentDispatchApplyWorkerContractsTest(unittest.TestCase):
    def test_worker_discovers_projects_and_applies_dispatch_plans(self) -> None:
        due_at = datetime(2026, 6, 21, tzinfo=UTC)
        due_soon_before = datetime(2026, 6, 20, tzinfo=UTC)
        repository = FakeEntityAliasAssignmentDispatchApplyRepository(
            project_ids=("project-1", "project-2", "project-3"),
            applied_counts={"project-1": 2, "project-2": 1},
        )

        result = apply_entity_alias_assignment_dispatch_for_projects(
            repository=repository,
            market_code="AU",
            reviewer_ids=("reviewer-a@example.com", "reviewer-b@example.com"),
            include_statuses=("unassigned", "escalated"),
            max_per_reviewer=2,
            due_soon_before=due_soon_before,
            limit_per_project=20,
            worker_id="alias-dispatch-worker",
            assignment_status="assigned",
            priority="high",
            due_at=due_at,
            reason="scheduled alias assignment dispatch apply",
            max_projects=2,
            page_size=1,
        )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["discovered_projects"])
        self.assertEqual(result["project_count"], 2)
        self.assertEqual(result["requested_count"], 3)
        self.assertEqual(result["applied_count"], 3)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual(repository.list_project_calls[0]["market_code"], "AU")
        self.assertEqual(repository.list_project_calls[0]["limit"], 1)
        self.assertEqual(repository.apply_calls[0].reviewer_ids, ("reviewer-a@example.com", "reviewer-b@example.com"))
        self.assertEqual(repository.apply_calls[0].include_statuses, ("unassigned", "escalated"))
        self.assertEqual(repository.apply_calls[0].max_per_reviewer, 2)
        self.assertEqual(repository.apply_calls[0].due_soon_before, due_soon_before)
        self.assertEqual(repository.apply_calls[0].due_at, due_at)
        self.assertEqual(repository.apply_calls[0].applied_by, "alias-dispatch-worker")

    def test_worker_uses_explicit_projects_and_continues_after_project_failure(self) -> None:
        repository = FakeEntityAliasAssignmentDispatchApplyRepository(
            project_ids=("ignored-project",),
            applied_counts={"project-2": 1},
            fail_project_id="project-1",
        )

        result = apply_entity_alias_assignment_dispatch_for_projects(
            repository=repository,
            project_ids=("project-1, project-2", "project-2"),
        )

        self.assertEqual(result["status"], "completed_with_errors")
        self.assertFalse(result["discovered_projects"])
        self.assertEqual(result["project_count"], 2)
        self.assertEqual(result["project_failure_count"], 1)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(repository.list_project_calls, [])
        self.assertIn("alias assignment dispatch apply failed", str(result["results"][0]["error_message"]))

    def test_worker_reports_per_candidate_failures(self) -> None:
        repository = FakeEntityAliasAssignmentDispatchApplyRepository(
            project_ids=("project-1",),
            applied_counts={"project-1": 1},
            failed_counts={"project-1": 2},
        )

        result = apply_entity_alias_assignment_dispatch_for_projects(
            repository=repository,
            project_ids=("project-1",),
        )

        self.assertEqual(result["status"], "completed_with_errors")
        self.assertEqual(result["requested_count"], 3)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["failed_count"], 2)
        self.assertEqual(result["results"][0]["status"], "applied_with_errors")

    def test_worker_idles_when_no_projects_match(self) -> None:
        repository = FakeEntityAliasAssignmentDispatchApplyRepository(project_ids=())

        result = apply_entity_alias_assignment_dispatch_for_projects(repository=repository, market_code="AU")

        self.assertFalse(result["processed"])
        self.assertEqual(result["status"], "idle")
        self.assertEqual(result["project_count"], 0)
        self.assertEqual(repository.apply_calls, [])


if __name__ == "__main__":
    unittest.main()
