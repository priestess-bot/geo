from __future__ import annotations

import unittest

from geo_core.models import RuntimeAlertNotificationResult, RuntimeProject, RuntimeProjectPage
from workers.notification_worker.run_runtime_alert_notifications import (
    enqueue_runtime_alert_notifications_for_projects,
)


class FakeRuntimeAlertNotificationRepository:
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

    def enqueue_runtime_alert_notifications(
        self,
        *,
        project_id: str,
        alert_type: str | None = None,
        severity: str | None = None,
        created_by: str = "runtime-alert-notification-worker",
        reason: str | None = None,
        include_resolved: bool = False,
    ) -> RuntimeAlertNotificationResult:
        self.enqueue_calls.append(
            {
                "project_id": project_id,
                "alert_type": alert_type,
                "severity": severity,
                "created_by": created_by,
                "reason": reason,
                "include_resolved": include_resolved,
            }
        )
        if project_id == self.fail_project_id:
            raise RuntimeError("alert read model failed")
        return RuntimeAlertNotificationResult(
            project_id=project_id,
            notification_count=2,
            delivery_count=1,
            skipped_count=1,
            notifications=({"id": f"notification-{project_id}"},),
            audit_events=({"event_type": "runtime_notification_created"},),
        )


class RuntimeAlertNotificationWorkerContractsTest(unittest.TestCase):
    def test_worker_discovers_projects_and_enqueues_runtime_alert_notifications(self) -> None:
        repository = FakeRuntimeAlertNotificationRepository(project_ids=("project-1", "project-2", "project-3"))

        result = enqueue_runtime_alert_notifications_for_projects(
            repository=repository,
            market_code="AU",
            alert_type="negative_sentiment",
            severity="critical",
            include_resolved=True,
            worker_id="alert-worker",
            reason="scheduled alert scan",
            max_projects=2,
            page_size=1,
        )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["discovered_projects"])
        self.assertEqual(result["project_count"], 2)
        self.assertEqual(result["notification_count"], 4)
        self.assertEqual(result["delivery_count"], 2)
        self.assertEqual(result["skipped_count"], 2)
        self.assertEqual([call["project_id"] for call in repository.enqueue_calls], ["project-1", "project-2"])
        self.assertEqual(repository.list_calls[0]["market_code"], "AU")
        self.assertEqual(repository.list_calls[0]["limit"], 1)
        self.assertEqual(repository.enqueue_calls[0]["alert_type"], "negative_sentiment")
        self.assertEqual(repository.enqueue_calls[0]["severity"], "critical")
        self.assertEqual(repository.enqueue_calls[0]["created_by"], "alert-worker")
        self.assertEqual(repository.enqueue_calls[0]["reason"], "scheduled alert scan")
        self.assertTrue(repository.enqueue_calls[0]["include_resolved"])

    def test_worker_uses_explicit_project_ids_without_project_discovery(self) -> None:
        repository = FakeRuntimeAlertNotificationRepository(project_ids=("ignored-project",))

        result = enqueue_runtime_alert_notifications_for_projects(
            repository=repository,
            project_ids=("project-1, project-2", "project-1"),
            max_projects=10,
        )

        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["discovered_projects"])
        self.assertEqual([call["project_id"] for call in repository.enqueue_calls], ["project-1", "project-2"])
        self.assertEqual(repository.list_calls, [])

    def test_worker_reports_per_project_failures_and_continues(self) -> None:
        repository = FakeRuntimeAlertNotificationRepository(
            project_ids=("project-1", "project-2"),
            fail_project_id="project-2",
        )

        result = enqueue_runtime_alert_notifications_for_projects(repository=repository, market_code="AU")

        self.assertEqual(result["status"], "completed_with_errors")
        self.assertEqual(result["project_count"], 2)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["notification_count"], 2)
        self.assertEqual(result["results"][1]["status"], "failed")
        self.assertIn("alert read model failed", str(result["results"][1]["error_message"]))

    def test_worker_idles_when_no_projects_match(self) -> None:
        repository = FakeRuntimeAlertNotificationRepository(project_ids=())

        result = enqueue_runtime_alert_notifications_for_projects(repository=repository, market_code="AU")

        self.assertFalse(result["processed"])
        self.assertEqual(result["status"], "idle")
        self.assertEqual(result["project_count"], 0)
        self.assertEqual(repository.enqueue_calls, [])


if __name__ == "__main__":
    unittest.main()
