"""Public contracts for versioned publication URL verification evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from geo_api.placement_contracts import PlacementContract


class PublicationVerificationCheckView(PlacementContract):
    name: Literal[
        "input_contract",
        "public_url",
        "redirect_policy",
        "http_2xx",
        "html_response",
        "approved_content",
        "required_disclosures",
        "expected_links",
    ]
    passed: bool
    failure_code: str | None


class PublicationVerificationFailureView(PlacementContract):
    code: str
    disposition: Literal["retryable", "permanent"]
    check: str
    retryable: bool


class PublicationVerificationAttemptView(PlacementContract):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    opportunity_id: UUID
    submission_id: UUID
    job_id: UUID
    attempt_number: int
    verifier_version: Literal["publication-url-verifier-v2"]
    outcome: Literal["passed", "failed", "retryable_error", "permanent_error"]
    checked_at: datetime
    status_code: int | None
    final_url: str | None
    metadata_hash: str | None
    body_hash: str | None
    visible_text_hash: str | None
    content_rule_hash: str | None
    verification_rule_hash: str | None
    redirect_count: int
    checks: list[PublicationVerificationCheckView]
    failures: list[PublicationVerificationFailureView]
    error_code: str | None
    failure_disposition: Literal["retryable", "permanent"] | None
    result_hash: str
    created_at: datetime
