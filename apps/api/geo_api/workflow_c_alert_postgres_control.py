"""Durable API-shaped control surface for Workflow C alert dispositions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from geo_api.workflow_c_alert_contracts import (
    AlertRuleTransitionRequest,
    AlertTransitionRequest,
    CreateAlertRuleRequest,
    EnqueueAlertEvaluationRequest,
    SuppressAlertRequest,
)
from geo_api.workflow_c_alert_runtime import (
    AlertEvaluationJobReceipt,
    WorkflowCAlertUnavailable,
)
from geo_core.alerts import Alert, AlertCommandResult, NotificationOutboxCommand
from geo_core.alerts import AlertRuleKind, AlertSeverity, NotificationChannel
from geo_core.alerts.postgres_lifecycle import PostgresWorkflowCAlertRepository
from geo_core.workflow_c_alert_admission import (
    AlertEvaluationSelector,
    PostgresWorkflowCAlertAdmissionRepository,
)
from geo_core.workflow_c_alert_rules import (
    AlertRuleRelease,
    AlertRuleReleaseStatus,
    PostgresWorkflowCAlertRuleRepository,
)


class PostgresWorkflowCAlertControl:
    """Match the Internal API alert port while state remains database-authoritative."""

    persistence = "durable"

    def __init__(
        self,
        *,
        repository: PostgresWorkflowCAlertRepository,
        rules: PostgresWorkflowCAlertRuleRepository | None = None,
        admission: PostgresWorkflowCAlertAdmissionRepository | None = None,
    ) -> None:
        self._repository = repository
        self._rules = rules
        self._admission = admission

    def create_rule(
        self,
        *,
        project_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: CreateAlertRuleRequest,
    ) -> AlertRuleRelease:
        rules = self._require_rules()
        return rules.create(
            project_id=project_id,
            rule_key=payload.rule_key,
            version=payload.version,
            kind=AlertRuleKind(payload.kind),
            severity=AlertSeverity(payload.severity),
            parameters=payload.parameters,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )

    def transition_rule(
        self,
        *,
        project_id: UUID,
        rule_id: UUID,
        actor_id: str,
        idempotency_key: str,
        target_status: AlertRuleReleaseStatus,
        payload: AlertRuleTransitionRequest,
    ) -> AlertRuleRelease:
        rules = self._require_rules()
        return rules.transition(
            project_id=project_id,
            rule_id=rule_id,
            expected_aggregate_version=payload.expected_aggregate_version,
            target_status=target_status,
            actor_id=actor_id,
            reason=payload.reason,
            idempotency_key=idempotency_key,
        )

    def get_rule(self, *, project_id: UUID, rule_id: UUID) -> AlertRuleRelease:
        return self._require_rules().get(project_id=project_id, rule_id=rule_id)

    def list_rules(self, *, project_id: UUID) -> tuple[AlertRuleRelease, ...]:
        return self._require_rules().list(project_id=project_id)

    def enqueue_evaluation(
        self,
        *,
        project_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: EnqueueAlertEvaluationRequest,
    ) -> AlertEvaluationJobReceipt:
        if self._admission is None:
            raise WorkflowCAlertUnavailable("alert admission repository is not configured")
        result = self._admission.enqueue(
            project_id=project_id,
            selector=AlertEvaluationSelector(
                alert_rule_id=payload.alert_rule_id,
                source_hash=payload.source_hash,
                baseline_source_hash=payload.baseline_source_hash,
                source_item_key=payload.source_item_key,
                channels=tuple(NotificationChannel(item) for item in payload.channels),
                max_attempts=payload.max_attempts,
            ),
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
        return AlertEvaluationJobReceipt(
            job_id=result.job_id,
            spec_hash=result.spec_hash,
            replayed=result.replayed,
        )

    def _require_rules(self) -> PostgresWorkflowCAlertRuleRepository:
        if self._rules is None:
            raise WorkflowCAlertUnavailable("alert rule repository is not configured")
        return self._rules

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
