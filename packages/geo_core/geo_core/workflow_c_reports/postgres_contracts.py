"""Commands and immutable versions for approved Workflow C reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from geo_core.workflow_c_reports.customer_projection import (
    WorkflowCCustomerApprovedReport,
    WorkflowCCustomerReportPayload,
)


WorkflowCReportSnapshotStatus = Literal[
    "draft", "in_review", "approved", "stale", "superseded", "revoked"
]
_TERMINAL_STATUSES = frozenset({"stale", "superseded", "revoked"})
_TRANSITION_STATUSES = frozenset(
    {"in_review", "approved", "stale", "superseded", "revoked"}
)


class WorkflowCReportError(RuntimeError):
    """Base error for a Workflow C report lifecycle operation."""


class WorkflowCReportNotFound(WorkflowCReportError):
    """The project-scoped report or immutable result version does not exist."""


class WorkflowCReportConflict(WorkflowCReportError):
    """The command conflicts with a version or an Idempotency-Key receipt."""


class WorkflowCReportRuleViolation(WorkflowCReportError):
    """The requested lifecycle operation violates a publication rule."""


class WorkflowCReportApprovalError(WorkflowCReportRuleViolation):
    """A Workflow C Report Snapshot lifecycle command is invalid or unsafe."""


@dataclass(frozen=True)
class CreateWorkflowCReportSnapshot:
    """Freeze immutable lineage and a Customer-safe payload as version one."""

    report_id: UUID
    project_id: UUID
    campaign_id: UUID
    monitoring_report_id: UUID
    monitoring_report_hash: str
    semantic_snapshot_hash: str
    source_kind: Literal["provider_api", "proxy_grounded_api", "automated_ui"]
    approved_safe_payload: WorkflowCCustomerReportPayload
    actor_id: UUID
    occurred_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_aware(self.occurred_at, "Workflow C report draft timestamp")
        object.__setattr__(self, "idempotency_key", _idempotency_key(self.idempotency_key))
        object.__setattr__(
            self,
            "approved_safe_payload",
            WorkflowCCustomerReportPayload.from_mapping(self.approved_safe_payload),
        )
        _validated_customer_payload(self)


@dataclass(frozen=True)
class AdvanceWorkflowCReportSnapshot:
    """Append exactly one legal transition to an immutable Report Snapshot."""

    report_id: UUID
    project_id: UUID
    expected_version: int
    status: Literal["in_review", "approved", "stale", "superseded", "revoked"]
    actor_id: UUID
    occurred_at: datetime
    idempotency_key: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.expected_version < 1:
            raise WorkflowCReportApprovalError("Workflow C report expected version is invalid")
        if self.status not in _TRANSITION_STATUSES:
            raise WorkflowCReportApprovalError("Workflow C report target status is invalid")
        _require_aware(self.occurred_at, "Workflow C report transition timestamp")
        object.__setattr__(self, "idempotency_key", _idempotency_key(self.idempotency_key))
        if self.status in _TERMINAL_STATUSES:
            if not isinstance(self.reason, str) or not self.reason.strip() or len(self.reason) > 500:
                raise WorkflowCReportApprovalError("Workflow C terminal report transition needs a reason")
        elif self.reason is not None:
            raise WorkflowCReportApprovalError("Workflow C non-terminal report transition cannot have a reason")


@dataclass(frozen=True)
class WorkflowCReportSnapshotVersion:
    """One immutable version, returned to Admin lifecycle callers."""

    report_id: UUID
    project_id: UUID
    version: int
    status: WorkflowCReportSnapshotStatus
    campaign_id: UUID
    monitoring_report_id: UUID
    monitoring_report_hash: str
    semantic_snapshot_hash: str
    source_kind: Literal["provider_api", "proxy_grounded_api", "automated_ui"]
    approved_safe_payload: WorkflowCCustomerReportPayload
    approved_safe_payload_hash: str
    version_hash: str
    actor_id: UUID
    reason: str | None
    occurred_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "approved_safe_payload",
            WorkflowCCustomerReportPayload.from_mapping(self.approved_safe_payload),
        )


def _validated_customer_payload(command: CreateWorkflowCReportSnapshot) -> None:
    WorkflowCCustomerApprovedReport(
        id=command.report_id,
        project_id=command.project_id,
        campaign_id=command.campaign_id,
        semantic_snapshot_hash=command.semantic_snapshot_hash,
        report_hash=command.monitoring_report_hash,
        source_kind=command.source_kind,
        approved_safe_payload=command.approved_safe_payload,
        approved_at=command.occurred_at,
    )


def _require_aware(value: object, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowCReportApprovalError(f"{label} must be timezone-aware")


def _idempotency_key(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise WorkflowCReportApprovalError("Workflow C report Idempotency-Key is invalid")
    return value.strip()
