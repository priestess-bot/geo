"""Customer transport contracts for immutable Workflow C report snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from geo_api.monitoring_contracts import StrictModel


class WorkflowCCustomerReportResponse(StrictModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    semantic_snapshot_hash: str
    report_hash: str
    source_kind: Literal["provider_api", "proxy_grounded_api", "automated_ui"]
    approved_safe_payload: dict[str, object]
    approved_at: datetime
