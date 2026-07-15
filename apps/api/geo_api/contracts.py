"""Stable transport contracts shared by the isolated GEO API surfaces."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictContract(BaseModel):
    """Base model for public API contracts that reject unknown fields."""

    model_config = ConfigDict(extra="forbid")


class ProblemDetails(StrictContract):
    """RFC 9457 compatible error response with a request correlation id."""

    type: str = "about:blank"
    title: str
    status: int = Field(ge=400, le=599)
    detail: str
    instance: str
    request_id: str
    errors: list[dict[str, object]] | None = None


class HealthStatus(StrictContract):
    status: Literal["ok", "ready"]
    service: str
    surface: Literal["internal", "customer"]


class AuthIdentity(StrictContract):
    actor_id: str
    tenant_id: UUID
    project_ids: list[UUID]
    roles: list[str]


class LogoutResult(StrictContract):
    status: Literal["logged_out"] = "logged_out"


class ProjectSummary(StrictContract):
    id: UUID
    key: str
    name: str
    role: str


class CustomerProjectSummary(StrictContract):
    """Customer-safe project projection without internal membership metadata."""

    project_id: UUID
    display_name: str
    market_code: str
    status: str


ItemT = TypeVar("ItemT")


class OffsetPage(StrictContract, Generic[ItemT]):
    items: list[ItemT]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    FINALIZING = "finalizing"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED = "cancelled"


class JobStatus(StrictContract):
    id: UUID
    kind: str
    status: JobState
    created_at: datetime
    updated_at: datetime
    result_ref: str | None = None
    error_code: str | None = None


class JobAccepted(StrictContract):
    job_id: UUID
    status: JobState
    status_url: str


class EngineeringStatus(StrictContract):
    status: Literal["available", "unavailable"]
    surface: Literal["internal"] = "internal"
    capabilities: list[str]
    sources: dict[str, Literal["available", "unavailable"]]


class EngineeringEvidence(StrictContract):
    label: str
    url: str | None = None


class EngineeringAxisStatus(StrEnum):
    SATISFIED = "satisfied"
    PENDING = "pending"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


class EngineeringAxis(StrictContract):
    status: EngineeringAxisStatus
    evidence: list[EngineeringEvidence]
    observed_at: datetime | None = None


class EngineeringAxes(StrictContract):
    planned: EngineeringAxis
    implemented: EngineeringAxis
    verified: EngineeringAxis
    deployed: EngineeringAxis


class EngineeringFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class EngineeringWorkItem(StrictContract):
    id: str
    title: str
    summary: str | None = None
    axes: EngineeringAxes
    blockers: list[str]
    observed_at: datetime
    freshness: EngineeringFreshness


class EngineeringWorkItemList(StrictContract):
    items: list[EngineeringWorkItem]
    observed_at: datetime | None = None


class EngineeringSyncRequest(StrictContract):
    repository_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=240)


class EngineeringHealthProbeRequest(StrictContract):
    repository_id: UUID | None = None
    service_key: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=240)


class GitHubWebhookAccepted(StrictContract):
    delivery_id: str
    duplicate: bool
    job_id: UUID
    status: JobState
    status_url: str


class DevToolsStatus(StrictContract):
    enabled: Literal[True] = True
    isolation: Literal["test-tenant-only"] = "test-tenant-only"
