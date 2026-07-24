"""Durable API-shaped control surface for Workflow C alert dispositions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from geo_api.workflow_c_alert_contracts import (
    AlertTransitionRequest,
    SuppressAlertRequest,
)
from geo_core.alerts import Alert, AlertCommandResult, NotificationOutboxCommand
from geo_core.alerts.postgres_lifecycle import PostgresWorkflowCAlertRepository


class PostgresWorkflowCAlertControl:
    """Match the Internal API alert port while state remains database-authoritative."""

    persistence = "durable"

    def __init__(self, *, repository: PostgresWorkflowCAlertRepository) -> None:
        self._repository = repository

    def get_alert(self, *, project_id: UUID, alert_id: UUID) -> Alert:
        return self._repository.get(project_id=project_id, alert_id=alert_id)

    def list_alerts(self, *, project_id: UUID) -> tuple[Alert, ...]:
        return self._repository.list(project_id=project_id)

    def notifications(
        self, *, project_id: UUID, alert_id: UUID
    ) -> tuple[NotificationOutboxCommand, ...]:
        return self._repository.notifications(project_id=project_id, alert_id=alert_id)

    def acknowledge(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: AlertTransitionRequest,
    ) -> AlertCommandResult:
        return self._transition(
            project_id=project_id,
            alert_id=alert_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            expected_version=payload.expected_version,
            reason=payload.reason,
            operation="acknowledge",
        )

    def suppress(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: SuppressAlertRequest,
    ) -> AlertCommandResult:
        return self._transition(
            project_id=project_id,
            alert_id=alert_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            expected_version=payload.expected_version,
            reason=payload.reason,
            operation="suppress",
            suppressed_until=payload.suppressed_until,
        )

    def unsuppress(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: AlertTransitionRequest,
    ) -> AlertCommandResult:
        return self._transition(
            project_id=project_id,
            alert_id=alert_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            expected_version=payload.expected_version,
            reason=payload.reason,
            operation="unsuppress",
        )

    def resolve(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: AlertTransitionRequest,
    ) -> AlertCommandResult:
        return self._transition(
            project_id=project_id,
            alert_id=alert_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            expected_version=payload.expected_version,
            reason=payload.reason,
            operation="resolve",
        )

    def _transition(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        actor_id: str,
        idempotency_key: str,
        expected_version: int,
        reason: str,
        operation: str,
        suppressed_until: datetime | None = None,
    ) -> AlertCommandResult:
        return self._repository.transition(
            project_id=project_id,
            alert_id=alert_id,
            expected_version=expected_version,
            operation=operation,
            actor_id=actor_id,
            reason=reason,
            command_key=idempotency_key,
            suppressed_until=suppressed_until,
        )


__all__ = ["PostgresWorkflowCAlertControl"]
