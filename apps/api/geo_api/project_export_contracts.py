"""Stable transport contracts for durable F027 exports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AdminProjectExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID | None = None


class ProjectExportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    project_id: UUID
    campaign_id: UUID | None
    audience: Literal["admin", "customer"]
    status: Literal[
        "queued",
        "retry_wait",
        "running",
        "finalizing",
        "succeeded",
        "failed",
        "dead_lettered",
        "cancelled",
    ]
    content_hash: str | None
    manifest_hash: str | None
    byte_count: int | None
    file_count: int | None
    created_at: datetime
    finalized_at: datetime | None
    error_code: str | None
    download_url: str | None
