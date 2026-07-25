"""Strict Internal API contracts for Workflow C report publication."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from geo_api.workflow_c_report_payload_contracts import WorkflowCCustomerSafePayload


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateWorkflowCReportRequest(StrictModel):
    campaign_id: UUID
    monitoring_report_id: UUID
    monitoring_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_kind: Literal["provider_api", "proxy_grounded_api", "automated_ui"]
    approved_safe_payload: WorkflowCCustomerSafePayload


class WorkflowCReportTransitionRequest(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, min_length=1, max_length=500)


class WorkflowCReportTerminalTransitionRequest(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class WorkflowCReportVersionResponse(StrictModel):
    report_id: UUID
    project_id: UUID
    version: int
    status: Literal["draft", "in_review", "approved", "stale", "superseded", "revoked"]
    campaign_id: UUID
    monitoring_report_id: UUID
    monitoring_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_kind: Literal["provider_api", "proxy_grounded_api", "automated_ui"]
    approved_safe_payload: WorkflowCCustomerSafePayload
    approved_safe_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    version_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_id: UUID
    reason: str | None
    occurred_at: datetime


class WorkflowCReportVersionPageResponse(StrictModel):
    items: list[WorkflowCReportVersionResponse]
    total: int
