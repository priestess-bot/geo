"""Governed manual-UI evidence admission without answer text transport."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from geo_core.sampling.contracts import (
    SHA256_PATTERN,
    SamplingRuleViolation,
    _require_aware,
    _text,
    canonical_hash,
)


class ManualEvidenceStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMMITTED = "committed"


class ManualEvidenceKind(StrEnum):
    SCREENSHOT = "screenshot"
    HTML_EXPORT = "html_export"
    TRANSCRIPT_EXPORT = "transcript_export"


class ManualCaptureDevice(StrEnum):
    DESKTOP = "desktop"
    MOBILE = "mobile"
    TABLET = "tablet"


@dataclass(frozen=True)
class ManualEvidenceImport:
    id: UUID
    project_id: UUID
    run_id: UUID
    task_id: UUID
    task_key: str
    attempt_id: UUID
    expected_task_version: int
    artifact_manifest_id: UUID
    artifact_manifest_hash: str
    artifact_content_hash: str
    governance_policy_hash: str
    capture_session_id: UUID
    evidence_kind: ManualEvidenceKind
    device: ManualCaptureDevice
    locale: str
    captured_at: datetime
    submitted_by: str
    submitted_at: datetime
    status: ManualEvidenceStatus = ManualEvidenceStatus.PENDING_REVIEW
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_reason: str | None = None
    committed_at: datetime | None = None
    aggregate_version: int = 1
    definition_hash: str = field(init=False)

    def __post_init__(self) -> None:
        status = ManualEvidenceStatus(self.status)
        kind = ManualEvidenceKind(self.evidence_kind)
        device = ManualCaptureDevice(self.device)
        if self.expected_task_version < 1 or self.aggregate_version < 1:
            raise SamplingRuleViolation("manual evidence versions must be positive")
        for digest in (
            self.task_key,
            self.artifact_manifest_hash,
            self.artifact_content_hash,
            self.governance_policy_hash,
        ):
            if not SHA256_PATTERN.fullmatch(digest):
                raise SamplingRuleViolation("manual evidence lineage must use SHA-256")
        locale = _text(self.locale, "manual evidence locale")
        submitted_by = _text(self.submitted_by, "manual evidence submitter")
        _require_aware(self.captured_at, "manual evidence capture time")
        _require_aware(self.submitted_at, "manual evidence submission time")
        if self.captured_at > self.submitted_at:
            raise SamplingRuleViolation("manual evidence cannot be submitted before capture")
        if (self.reviewed_by is None) != (self.reviewed_at is None):
            raise SamplingRuleViolation("manual evidence review audit is incomplete")
        if status is ManualEvidenceStatus.PENDING_REVIEW:
            if any(
                item is not None
                for item in (self.reviewed_by, self.reviewed_at, self.review_reason)
            ):
                raise SamplingRuleViolation("pending manual evidence cannot have a decision")
        elif self.reviewed_by is None or self.review_reason is None:
            raise SamplingRuleViolation("decided manual evidence requires reviewer audit")
        if status is ManualEvidenceStatus.COMMITTED and self.committed_at is None:
            raise SamplingRuleViolation("committed manual evidence requires commit time")
        if self.reviewed_at is not None:
            _require_aware(self.reviewed_at, "manual evidence review time")
            if self.reviewed_at < self.submitted_at:
                raise SamplingRuleViolation("manual evidence review cannot predate submission")
        if self.committed_at is not None:
            _require_aware(self.committed_at, "manual evidence commit time")
            if self.reviewed_at is None or self.committed_at < self.reviewed_at:
                raise SamplingRuleViolation("manual evidence commit cannot predate approval")
        definition = {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "run_id": str(self.run_id),
            "task_id": str(self.task_id),
            "task_key": self.task_key,
            "attempt_id": str(self.attempt_id),
            "expected_task_version": self.expected_task_version,
            "artifact_manifest_id": str(self.artifact_manifest_id),
            "artifact_manifest_hash": self.artifact_manifest_hash,
            "artifact_content_hash": self.artifact_content_hash,
            "governance_policy_hash": self.governance_policy_hash,
            "capture_session_id": str(self.capture_session_id),
            "evidence_kind": kind.value,
            "device": device.value,
            "locale": locale,
            "captured_at": self.captured_at.isoformat(),
            "submitted_by": submitted_by,
            "submitted_at": self.submitted_at.isoformat(),
        }
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "evidence_kind", kind)
        object.__setattr__(self, "device", device)
        object.__setattr__(self, "locale", locale)
        object.__setattr__(self, "submitted_by", submitted_by)
        object.__setattr__(self, "definition_hash", canonical_hash(definition))


def decide_manual_evidence(
    item: ManualEvidenceImport,
    *,
    reviewer_id: str,
    reviewed_at: datetime,
    reason: str,
    approved: bool,
) -> ManualEvidenceImport:
    if item.status is not ManualEvidenceStatus.PENDING_REVIEW:
        raise SamplingRuleViolation("manual evidence is not pending review")
    reviewer = _text(reviewer_id, "manual evidence reviewer")
    if reviewer == item.submitted_by:
        raise SamplingRuleViolation("manual evidence maker cannot review it")
    review_reason = _text(reason, "manual evidence review reason")
    _require_aware(reviewed_at, "manual evidence review time")
    return replace(
        item,
        status=(ManualEvidenceStatus.APPROVED if approved else ManualEvidenceStatus.REJECTED),
        reviewed_by=reviewer,
        reviewed_at=reviewed_at,
        review_reason=review_reason,
        aggregate_version=item.aggregate_version + 1,
    )


def commit_manual_evidence(
    item: ManualEvidenceImport, *, committed_at: datetime
) -> ManualEvidenceImport:
    if item.status is not ManualEvidenceStatus.APPROVED:
        raise SamplingRuleViolation("only approved manual evidence can be committed")
    _require_aware(committed_at, "manual evidence commit time")
    return replace(
        item,
        status=ManualEvidenceStatus.COMMITTED,
        committed_at=committed_at,
        aggregate_version=item.aggregate_version + 1,
    )
