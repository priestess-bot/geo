"""Durable request and artifact identities for F027 project exports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from geo_core.project_exports.contracts import ExportAudience, ProjectExportScope


@dataclass(frozen=True)
class ProjectExportClaim:
    job_id: UUID
    scope: ProjectExportScope
    audience: ExportAudience
    requested_by: UUID
    generated_at: datetime


@dataclass(frozen=True)
class ProjectExportArtifact:
    job_id: UUID
    project_id: UUID
    campaign_id: UUID | None
    audience: ExportAudience
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
    artifact_uri: str | None
    storage_key: str | None
    content_hash: str | None
    manifest_hash: str | None
    byte_count: int | None
    file_count: int | None
    created_at: datetime
    finalized_at: datetime | None
    error_code: str | None


def project_export_storage_key(claim: ProjectExportClaim, manifest_hash: str) -> str:
    campaign = str(claim.scope.campaign_id) if claim.scope.campaign_id else "all-campaigns"
    return (
        f"project-exports/{claim.scope.project_id}/{claim.audience.value}/"
        f"{campaign}/{manifest_hash}.zip"
    )
