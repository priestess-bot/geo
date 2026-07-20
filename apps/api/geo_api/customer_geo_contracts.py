"""Stable Customer-only GEO read contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from geo_api.monitoring_contracts import (
    MetricResponse,
    MonitoringReportResponse,
    StrictModel,
    VerifiedUrlResponse,
)


class CustomerCampaignResponse(StrictModel):
    id: UUID
    project_id: UUID
    name: str
    objective: str
    status: str
    approved_report_count: int
    latest_approved_at: datetime | None


class CustomerApprovedMeasurementResponse(StrictModel):
    report: MonitoringReportResponse
    snapshot: MetricResponse
    snapshot_contract: Literal["statistics_v2", "legacy_unknown"]


class CustomerCampaignSummaryResponse(StrictModel):
    project_id: UUID
    campaign_id: UUID
    campaign_name: str
    campaign_objective: str
    campaign_status: str
    frozen_protocol_count: int
    measurement_window_count: int
    verified_url_count: int
    approved_report_count: int
    latest_metrics: list[MetricResponse]
    interpretation: str


class CustomerCampaignReadModelResponse(StrictModel):
    campaign: CustomerCampaignResponse
    summary: CustomerCampaignSummaryResponse
    approved_measurements: list[CustomerApprovedMeasurementResponse]
    verified_urls: list[VerifiedUrlResponse]
