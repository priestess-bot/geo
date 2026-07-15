from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from geo_core.models import RuntimeAlertEvent, RuntimeAlertItem, RuntimeAlertPage, RuntimeProject, RuntimeProjectPage
from workers.notification_worker.run_runtime_alert_escalations import (
    _parse_severity_thresholds,
    escalate_runtime_alerts_for_projects,
)


class FakeRuntimeAlertEscalationRepository:
    def __init__(
        self,
        *,
        project_ids: tuple[str, ...],
        alerts_by_project: dict[str, tuple[RuntimeAlertItem, ...]] | None = None,
        fail_project_id: str | None = None,
    ) -> None:
        self.project_ids = project_ids
        self.alerts_by_project = alerts_by_project or {}
        self.fail_project_id = fail_project_id
        self.list_project_calls: list[dict[str, object]] = []
        self.list_alert_calls: list[dict[str, object]] = []
        self.recorded_events: list[object] = []

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

    def list_runtime_alerts(
        self,
        *,
        project_id: str | None = None,
        alert_type: str | None = None,
        severity: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> RuntimeAlertPage:
        if project_id == self.fail_project_id:
            raise RuntimeError("alert escalation read model failed")
        self.list_alert_calls.append(
            {
                "project_id": project_id,
                "alert_type": alert_type,
                "severity": severity,
                "limit": limit,
                "offset": offset,
            }
        )
        selected = tuple(
            item
            for item in self.alerts_by_project.get(str(project_id), ())
            if not severity or item.alert.get("severity") == severity
        )
        return RuntimeAlertPage(total_count=len(selected), limit=limit, offset=offset, records=selected)

    def record_runtime_alert_event(self, event: object) -> RuntimeAlertEvent:
        self.recorded_events.append(event)
        return RuntimeAlertEvent(
            alert_event={
                "id": f"event-{len(self.recorded_events)}",
                "project_id": event.project_id,
                "alert_id": event.alert_id,
                "status": event.status,
                "metadata": event.metadata,
            },
            audit_events=({"event_type": "runtime_alert_event_recorded"},),
        )


def _alert(
    *,
    alert_id: str,
    project_id: str = "project-1",
    severity: str,
    created_at: datetime,
    latest_status: str | None = None,
) -> RuntimeAlertItem:
    management_events = ({"status": latest_status, "created_at": created_at},) if latest_status else ()
    return RuntimeAlertItem(
        alert={
            "id": alert_id,
            "project_id": project_id,
            "alert_type": "negative_sentiment",
            "severity": severity,
            "source": "answer_analysis",
            "source_id": f"source-{alert_id}",
            "created_at": created_at,
        },
        evidence_refs=(),
        related_actions=(),
        audit_events=(),
        management_events=management_events,
    )


class RuntimeAlertEscalationWorkerContractsTest(unittest.TestCase):
    def test_worker_escalates_overdue_critical_and_high_alerts(self) -> None:
        now = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
        repository = FakeRuntimeAlertEscalationRepository(
            project_ids=("project-1",),
            alerts_by_project={
                "project-1": (
                    _alert(alert_id="critical-overdue", severity="critical", created_at=now - timedelta(hours=5)),
                    _alert(alert_id="critical-fresh", severity="critical", created_at=now - timedelta(hours=2)),
                    _alert(alert_id="high-overdue", severity="high", created_at=now - timedelta(hours=30)),
                    _alert(
                        alert_id="high-acknowledged",
                        severity="high",
                        created_at=now - timedelta(hours=30),
                        latest_status="acknowledged",
                    ),
                )
            },
        )

        result = escalate_runtime_alerts_for_projects(
            repository=repository,
            market_code="AU",
            severity_thresholds_hours={"critical": 4, "high": 24},
            worker_id="sla-worker",
            now=now,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["alert_count"], 4)
        self.assertEqual(result["escalated_count"], 2)
        self.assertEqual(result["skipped_count"], 2)
        self.assertEqual([event.alert_id for event in repository.recorded_events], ["critical-overdue", "high-overdue"])
        self.assertEqual(repository.recorded_events[0].status, "escalated")
        self.assertEqual(repository.recorded_events[0].updated_by, "sla-worker")
        self.assertEqual(repository.recorded_events[0].metadata["threshold_hours"], 4)
        self.assertEqual(repository.recorded_events[1].metadata["threshold_hours"], 24)
        self.assertEqual(repository.list_project_calls[0]["market_code"], "AU")

    def test_worker_uses_explicit_projects_and_continues_after_failure(self) -> None:
        now = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
        repository = FakeRuntimeAlertEscalationRepository(
            project_ids=("ignored-project",),
            alerts_by_project={
                "project-2": (
                    _alert(
                        alert_id="critical-overdue",
                        project_id="project-2",
                        severity="critical",
                        created_at=now - timedelta(hours=5),
                    ),
                )
            },
            fail_project_id="project-1",
        )

        result = escalate_runtime_alerts_for_projects(
            repository=repository,
            project_ids=("project-1, project-2", "project-2"),
            severity_thresholds_hours={"critical": 4},
            now=now,
        )

        self.assertEqual(result["status"], "completed_with_errors")
        self.assertFalse(result["discovered_projects"])
        self.assertEqual(result["project_count"], 2)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["escalated_count"], 1)
        self.assertEqual(repository.list_project_calls, [])
        self.assertIn("alert escalation read model failed", str(result["results"][0]["error_message"]))

    def test_worker_idles_when_no_projects_match(self) -> None:
        repository = FakeRuntimeAlertEscalationRepository(project_ids=())

        result = escalate_runtime_alerts_for_projects(repository=repository, market_code="AU")

        self.assertFalse(result["processed"])
        self.assertEqual(result["status"], "idle")
        self.assertEqual(result["project_count"], 0)
        self.assertEqual(repository.recorded_events, [])

    def test_threshold_parser_requires_severity_hours_pairs(self) -> None:
        self.assertEqual(_parse_severity_thresholds("critical=2,high=12"), {"critical": 2, "high": 12})
        with self.assertRaises(ValueError):
            _parse_severity_thresholds("critical")


if __name__ == "__main__":
    unittest.main()
