"""Read models for append-only publication verification evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping
from uuid import UUID


VerificationOutcome = Literal[
    "passed", "failed", "retryable_error", "permanent_error"
]


@dataclass(frozen=True)
class PublicationVerificationAttempt:
    id: UUID
    project_id: UUID
    campaign_id: UUID
    opportunity_id: UUID
    submission_id: UUID
    job_id: UUID
    attempt_number: int
    verifier_version: str
    outcome: VerificationOutcome
    checked_at: datetime
    status_code: int | None
    final_url: str | None
    metadata_hash: str | None
    body_hash: str | None
    visible_text_hash: str | None
    content_rule_hash: str | None
    verification_rule_hash: str | None
    redirect_count: int
    checks: tuple[Mapping[str, object], ...]
    failures: tuple[Mapping[str, object], ...]
    error_code: str | None
    failure_disposition: Literal["retryable", "permanent"] | None
    result_hash: str
    created_at: datetime
