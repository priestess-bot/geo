"""Stable API contracts for first-party collection and local attribution."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from geo_api.contracts import StrictContract


class CreateAttributionPolicyRequest(StrictContract):
    last_click_days: int = Field(default=30, ge=1, le=365)
    assisted_days: int = Field(default=90, ge=1, le=730)
    eligible_touch_types: list[Literal["page_view", "click"]] = Field(
        default_factory=lambda: ["page_view", "click"], min_length=1
    )


class AttributionPolicyResponse(StrictContract):
    id: UUID
    project_id: UUID
    version: int
    last_click_days: int
    assisted_days: int
    direct_rule: str
    eligible_touch_types: list[str]
    policy_hash: str
    status: str
    created_by: UUID
    created_at: datetime
    retired_at: datetime | None = None


class CreateAttributionCollectorRequest(StrictContract):
    name: str = Field(min_length=1, max_length=200)
    allowed_origins: list[str] = Field(min_length=1, max_length=50)
    event_schema_version: str = Field(default="geo-attribution-event-v1", max_length=100)
    sdk_release: str = Field(default="geo-browser-sdk-v1", max_length=100)


class AttributionCollectorCreatedResponse(StrictContract):
    id: UUID
    project_id: UUID
    name: str
    allowed_origins: list[str]
    event_schema_version: str
    sdk_release: str
    consent_mode: Literal["explicit"]
    status: str
    created_at: datetime
    write_key: str


class IssueAttributionTraceRequest(StrictContract):
    campaign_id: UUID
    question_set_id: UUID | None = None
    package_version_id: UUID | None = None
    content_asset_key: str = Field(min_length=1, max_length=300)
    verified_url: str = Field(pattern=r"^https://", max_length=2_000)
    ttl_days: int = Field(default=180, ge=1, le=730)


class AttributionTraceCreatedResponse(StrictContract):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    question_set_id: UUID | None = None
    package_version_id: UUID | None = None
    content_asset_key: str
    verified_url: str
    issued_at: datetime
    expires_at: datetime
    trace_token: str


class CollectAttributionEventRequest(StrictContract):
    client_session_id: UUID
    source_event_id: str = Field(min_length=1, max_length=240)
    event_type: Literal["session_start", "page_view", "click", "direct"]
    occurred_at: datetime
    consent: bool
    consent_schema_version: str = Field(min_length=1, max_length=100)
    trace_token: str | None = Field(default=None, max_length=200)
    utm: dict[str, str] = Field(default_factory=dict)


class AttributionEventAcceptedResponse(StrictContract):
    project_id: UUID
    session_id: UUID
    touch_id: UUID | None = None
    replayed: bool


class RecordBusinessEventRequest(StrictContract):
    kind: Literal["lead", "stage", "conversion", "deal", "revenue"]
    source_event_id: str = Field(min_length=1, max_length=240)
    parent_id: UUID
    occurred_at: datetime
    local_business_id: str | None = Field(default=None, max_length=240)
    label: str | None = Field(default=None, max_length=240)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    amount: Decimal | None = Field(default=None, ge=0)
    source_type: Literal["admin", "file_import"] = "admin"
    schema_version: str = Field(default="attribution-business-v1", max_length=100)
    import_id: UUID | None = None


class BusinessEventResponse(StrictContract):
    id: UUID
    project_id: UUID
    source_event_id: str
    occurred_at: datetime
    received_at: datetime
    source_type: str
    schema_version: str
    replayed: bool


class BusinessImportRow(StrictContract):
    id: UUID
    kind: Literal["lead", "stage", "conversion", "deal", "revenue"]
    source_event_id: str = Field(min_length=1, max_length=240)
    parent_id: UUID
    occurred_at: datetime
    local_business_id: str | None = Field(default=None, max_length=240)
    label: str | None = Field(default=None, max_length=240)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    amount: Decimal | None = Field(default=None, ge=0)


class ImportBusinessEventsRequest(StrictContract):
    template_schema_version: str = Field(
        default="attribution-business-import-v1", min_length=1, max_length=100
    )
    rows: list[BusinessImportRow] = Field(min_length=1, max_length=1_000)


class BusinessImportResponse(StrictContract):
    id: UUID
    project_id: UUID
    template_schema_version: str
    file_hash: str
    row_count: int
    accepted_count: int
    rejected_count: int
    requested_by: UUID
    requested_at: datetime
    result: dict[str, object]
    replayed: bool


class CreateAttributionSnapshotRequest(StrictContract):
    cutoff_at: datetime
    policy_id: UUID | None = None


class AttributionSnapshotResponse(StrictContract):
    id: UUID
    project_id: UUID
    policy_id: UUID
    cutoff_at: datetime
    input_hash: str
    result: dict[str, object]
    result_hash: str
    created_by: UUID
    created_at: datetime
    replayed: bool


class AttributionCollectorResponse(StrictContract):
    id: UUID
    project_id: UUID
    name: str
    allowed_origins: list[str]
    event_schema_version: str
    sdk_release: str
    consent_mode: Literal["explicit"]
    status: str
    created_at: datetime


class AttributionInventoryResponse(StrictContract):
    policies: list[AttributionPolicyResponse]
    collectors: list[AttributionCollectorResponse]
    counts: dict[str, int]
    snapshots: list[AttributionSnapshotResponse]


__all__ = [name for name in globals() if name.endswith(("Request", "Response"))]
