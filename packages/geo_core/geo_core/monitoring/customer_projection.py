"""Customer-safe campaign and approved measurement projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from geo_core.monitoring.domain import MetricSnapshot, MonitoringReport


STATISTICS_V2_METHOD = "geo-observation-statistics-v2"


@dataclass(frozen=True)
class CustomerCampaign:
    """The only Campaign fields exposed by the Customer API."""

    id: UUID
    project_id: UUID
    name: str
    objective: str
    status: str
    approved_report_count: int
    latest_approved_at: datetime | None


@dataclass(frozen=True)
class ApprovedReportSnapshot:
    """An approved report paired with the exact immutable snapshot it approved."""

    report: MonitoringReport
    snapshot: MetricSnapshot

    def __post_init__(self) -> None:
        if self.report.status != "approved" or self.report.approved_at is None:
            raise ValueError("customer projections require an approved report")
        if self.report.metric_snapshot_id != self.snapshot.id:
            raise ValueError("approved report does not reference this metric snapshot")
        report_lineage = (
            self.report.project_id,
            self.report.campaign_id,
            self.report.protocol_id,
        )
        snapshot_lineage = (
            self.snapshot.project_id,
            self.snapshot.campaign_id,
            self.snapshot.protocol_id,
        )
        if report_lineage != snapshot_lineage:
            raise ValueError("approved report crosses metric snapshot lineage")

    @property
    def snapshot_contract(self) -> Literal["statistics_v2", "legacy_unknown"]:
        return (
            "statistics_v2"
            if self.snapshot.method_version == STATISTICS_V2_METHOD
            and self.snapshot.statistics_contract_version == STATISTICS_V2_METHOD
            else "legacy_unknown"
        )
