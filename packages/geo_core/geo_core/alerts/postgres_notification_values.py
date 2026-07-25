"""Durable notification values emitted by Workflow C alert evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from geo_core.alerts.notifications import NotificationOutboxCommand
from geo_core.alerts.postgres_operation_values import (
    canonical_hash,
    deterministic_id,
)


def _notification_value(
    command: NotificationOutboxCommand, project_id: UUID
) -> Mapping[str, object]:
    spec_payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "workflow_c.alert.notify",
        "notification_id": str(command.id),
    }
    spec_hash = canonical_hash(spec_payload)
    job_key = f"workflow-c-alert-notify:{command.idempotency_key}"
    return {
        "id": str(command.id),
        "alert_id": str(command.alert_id),
        "alert_version": command.alert_version,
        "channel": command.channel.value,
        "topic": command.topic,
        "idempotency_key": command.idempotency_key,
        "payload_hash": command.payload_hash,
        "payload": {"summary": command.summary.payload()},
        "safe_summary": (
            f"Workflow C {command.summary.severity.value} alert "
            f"{command.alert_id} {command.summary.event_type}"
        ),
        "created_at": command.created_at.isoformat(),
        "notify_job_id": str(deterministic_id(project_id, "notify", job_key)),
        "notify_spec_hash": spec_hash,
        "notify_spec_payload": spec_payload,
    }
