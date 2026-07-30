"""Transport contracts for approved Connector and official-report projections."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from geo_api.contracts import StrictContract


class CreateConnectorExternalReportRequest(StrictContract):
    campaign_id: UUID
    projection_batch_id: UUID
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=2_000)


class CreateOfficialExternalReportRequest(StrictContract):
    campaign_id: UUID
    import_id: UUID
    customer_fields: list[str] = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=2_000)


class CreateAttributionExternalReportRequest(StrictContract):
    campaign_id: UUID
    attribution_snapshot_id: UUID
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=2_000)


class DecideExternalReportRequest(StrictContract):
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=2_000)
    review_evidence: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=240)


class InvalidateExternalReportRequest(StrictContract):
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["stale", "revoked"]
    reason: str = Field(min_length=1, max_length=2_000)
    evidence: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=240)


class ExternalReportResponse(StrictContract):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    snapshot_id: UUID
    snapshot_hash: str
    partition_key: str
    title: str
    summary: str
    approval_policy_version: str
    approval_rubric_version: str
    customer_schema_version: str
    status: Literal[
        "draft", "in_review", "approved", "rejected", "stale", "superseded", "revoked"
    ]
    version: int
    created_by: UUID
    created_at: datetime
    submitted_at: datetime | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    terminal_reason: str | None = None
    source_kind: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    as_of: datetime | None = None
    freshness_status: str | None = None
    row_count: int | None = None
    lineage: dict[str, object] | None = None


class ExternalOperationalAlertInputResponse(StrictContract):
    id: UUID
    source_kind: Literal["connector_error", "connector_freshness", "browser_surface_drift"]
    source_id: UUID
    source_version: int
    signal_kind: Literal[
        "connector_auth", "connector_schema", "connector_quota", "connector_rate",
        "connector_failure", "connector_freshness", "surface_parser", "browser_build",
    ]
    severity: Literal["info", "warning", "critical"]
    reason_code: str
    action_path: str
    payload: dict[str, object]
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    created_at: datetime


class CustomerExternalDataResponse(StrictContract):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    snapshot_id: UUID
    partition_key: str
    title: str
    summary: str
    customer_schema_version: str
    approved_at: datetime
    source_kind: str
    period_start: date
    period_end: date
    as_of: datetime
    freshness_status: str
    row_count: int
    customer_payload: dict[str, object]


__all__ = [
    "CreateConnectorExternalReportRequest",
    "CreateAttributionExternalReportRequest",
    "CreateOfficialExternalReportRequest",
    "CustomerExternalDataResponse",
    "DecideExternalReportRequest",
    "ExternalReportResponse",
    "ExternalOperationalAlertInputResponse",
    "InvalidateExternalReportRequest",
]
