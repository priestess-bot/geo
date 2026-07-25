"""Strict Internal API contracts for governed alerts and notification projection."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


AlertChannelValue = Literal["admin_inbox", "local_smtp", "internal_webhook"]


def default_alert_channels() -> list[AlertChannelValue]:
    return ["admin_inbox", "local_smtp", "internal_webhook"]


class AlertRuleContract(StrictModel):
    id: UUID
    rule_key: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)
    kind: Literal[
        "threshold",
        "baseline_delta",
        "negative_question",
        "completion_freshness",
        "model_drift",
        "source_drift",
    ]
    severity: Literal["info", "warning", "critical"]
    parameters: dict[str, object] = Field(min_length=1, max_length=100)
    frozen_by: str = Field(min_length=1, max_length=200)
    frozen_at: datetime


class AlertScopeContract(StrictModel):
    resource_kind: str = Field(min_length=1, max_length=200)
    resource_key: str = Field(min_length=1, max_length=500)
    dimensions: dict[str, str] = Field(default_factory=dict, max_length=100)


class AlertEvidenceContract(StrictModel):
    kind: str = Field(min_length=1, max_length=200)
    resource_id: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str | None = Field(default=None, max_length=1000)


class AlertTransitionRequest(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class SuppressAlertRequest(AlertTransitionRequest):
    suppressed_until: datetime


class AlertDispositionResponse(StrictModel):
    disposition: str
    from_status: str
    to_status: str
    actor_id: str
    occurred_at: datetime
    reason: str
    command_key: str
    resulting_version: int
    suppressed_until: datetime | None
    command_hash: str


class AlertResponse(StrictModel):
    id: UUID
    project_id: UUID
    rule: AlertRuleContract
    rule_hash: str
    scope: AlertScopeContract
    trigger_values: dict[str, object]
    trigger_snapshot_hash: str
    evidence: list[AlertEvidenceContract]
    severity: Literal["info", "warning", "critical"]
    dedupe_key: str
    status: Literal["open", "acknowledged", "suppressed", "resolved"]
    opened_at: datetime
    updated_at: datetime
    version: int
    dispositions: list[AlertDispositionResponse]
    suppressed_until: datetime | None
    suppression_reason: str | None
    replayed: bool = False


class AlertPageResponse(StrictModel):
    items: list[AlertResponse]
    total: int


class NotificationProjectionResponse(StrictModel):
    id: UUID
    project_id: UUID
    alert_id: UUID
    alert_version: int
    channel: AlertChannelValue
    topic: str
    idempotency_key: str
    created_at: datetime
    payload_hash: str
    summary: dict[str, object]


class AlertCommandResponse(StrictModel):
    alert: AlertResponse
    notifications: list[NotificationProjectionResponse]
    replayed: bool


class CreateAlertRuleRequest(StrictModel):
    rule_key: str = Field(pattern=r"^[a-z][a-z0-9_.:-]{0,199}$")
    version: int = Field(ge=1)
    kind: Literal[
        "threshold",
        "baseline_delta",
        "negative_question",
        "completion_freshness",
        "model_drift",
        "source_drift",
    ]
    severity: Literal["info", "warning", "critical"]
    parameters: dict[str, object] = Field(min_length=1, max_length=100)


class AlertRuleTransitionRequest(StrictModel):
    expected_aggregate_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2_000)


class AlertRuleReleaseResponse(StrictModel):
    id: UUID
    project_id: UUID
    rule_key: str
    version: int
    kind: Literal[
        "threshold",
        "baseline_delta",
        "negative_question",
        "completion_freshness",
        "model_drift",
        "source_drift",
    ]
    severity: Literal["info", "warning", "critical"]
    parameters: dict[str, object]
    rule_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["draft", "approved", "retired"]
    aggregate_version: int
    created_by: str
    created_at: datetime
    approved_by: str | None
    approved_at: datetime | None
    retired_by: str | None
    retired_at: datetime | None
    decision_reason: str | None


class AlertRuleReleasePageResponse(StrictModel):
    items: list[AlertRuleReleaseResponse]
    total: int


class EnqueueAlertEvaluationRequest(StrictModel):
    alert_rule_id: UUID
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_source_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_item_key: str | None = Field(default=None, min_length=1, max_length=500)
    channels: list[AlertChannelValue] = Field(
        default_factory=default_alert_channels,
        min_length=1,
        max_length=3,
    )
    max_attempts: int = Field(default=3, ge=1, le=10)


class AlertEvaluationJobAccepted(StrictModel):
    job_id: UUID
    status: Literal["queued"] = "queued"
    status_url: str
    spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    replayed: bool
