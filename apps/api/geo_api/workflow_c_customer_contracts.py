"""Customer transport contracts for immutable Workflow C report snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from geo_api.monitoring_contracts import StrictModel
from geo_api.workflow_c_report_payload_contracts import WorkflowCCustomerSafePayload


class WorkflowCCustomerReportResponse(StrictModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    semantic_snapshot_hash: str
    report_hash: str
    source_kind: Literal["provider_api", "proxy_grounded_api", "automated_ui"]
    approved_safe_payload: WorkflowCCustomerSafePayload
    approved_at: datetime
