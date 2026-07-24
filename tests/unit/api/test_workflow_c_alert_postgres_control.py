from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from geo_api.workflow_c_alert_contracts import (
    AlertTransitionRequest,
    SuppressAlertRequest,
)
from geo_api.workflow_c_alert_postgres_control import PostgresWorkflowCAlertControl


NOW = datetime(2026, 7, 23, tzinfo=UTC)


def test_postgres_alert_control_preserves_route_command_shape() -> None:
    repository = _Repository()
    control = PostgresWorkflowCAlertControl(repository=repository)  # type: ignore[arg-type]
    project_id, alert_id = uuid4(), uuid4()

    control.acknowledge(
        project_id=project_id,
        alert_id=alert_id,
        actor_id="operator-1",
        idempotency_key="alert:acknowledge:one",
        payload=AlertTransitionRequest(expected_version=1, reason="investigating"),
    )
    control.suppress(
        project_id=project_id,
        alert_id=alert_id,
        actor_id="operator-1",
        idempotency_key="alert:suppress:one",
        payload=SuppressAlertRequest(
            expected_version=2,
            reason="maintenance",
            suppressed_until=NOW + timedelta(hours=1),
        ),
    )

    assert control.persistence == "durable"
    assert repository.calls == [
        {
            "project_id": project_id,
            "alert_id": alert_id,
            "expected_version": 1,
            "operation": "acknowledge",
            "actor_id": "operator-1",
            "reason": "investigating",
            "command_key": "alert:acknowledge:one",
            "suppressed_until": None,
        },
        {
            "project_id": project_id,
            "alert_id": alert_id,
            "expected_version": 2,
            "operation": "suppress",
            "actor_id": "operator-1",
            "reason": "maintenance",
            "command_key": "alert:suppress:one",
            "suppressed_until": NOW + timedelta(hours=1),
        },
    ]


class _Repository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def transition(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(dict(kwargs))
        return SimpleNamespace()
