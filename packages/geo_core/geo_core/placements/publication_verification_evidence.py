"""Immutable attempt evidence builders for publication verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping

from geo_core.placements.publication_verification_records import VerificationOutcome
from geo_core.placements.url_verification_contracts import (
    UrlVerificationResult,
    VerificationCheck,
    VerificationCheckName,
    VerificationError,
    VerificationFailure,
    VerificationFailureDisposition,
)


@dataclass(frozen=True)
class AttemptEvidence:
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
    failure_disposition: str | None

    def hash_input(self) -> dict[str, object]:
        return {
            "verifier_version": self.verifier_version,
            "outcome": self.outcome,
            "checked_at": self.checked_at.isoformat(),
            "status_code": self.status_code,
            "final_url": self.final_url,
            "metadata_hash": self.metadata_hash,
            "body_hash": self.body_hash,
            "visible_text_hash": self.visible_text_hash,
            "content_rule_hash": self.content_rule_hash,
            "verification_rule_hash": self.verification_rule_hash,
            "redirect_count": self.redirect_count,
            "checks": list(self.checks),
            "failures": list(self.failures),
            "error_code": self.error_code,
            "failure_disposition": self.failure_disposition,
        }


def completed_evidence(result: UrlVerificationResult) -> AttemptEvidence:
    checks = tuple(check.to_persistence_dict() for check in result.checks)
    failures = tuple(failure.to_persistence_dict() for failure in result.failures)
    if not result.success and not failures:
        raise ValueError("failed verification results require stable failure evidence")
    return AttemptEvidence(
        verifier_version=result.verifier_version,
        outcome="passed" if result.success else "failed",
        checked_at=result.checked_at,
        status_code=result.status_code,
        final_url=result.final_url,
        metadata_hash=result.metadata_hash,
        body_hash=result.body_hash,
        visible_text_hash=result.visible_text_hash,
        content_rule_hash=result.content_rule_hash,
        verification_rule_hash=result.verification_rule_hash,
        redirect_count=result.redirect_count,
        checks=checks,
        failures=failures,
        error_code=None if result.success else str(failures[0]["code"]),
        failure_disposition=None if result.success else "permanent",
    )


def input_contract_failure_evidence(
    result: UrlVerificationResult, *, code: str
) -> AttemptEvidence:
    failure = VerificationFailure(
        code=code,
        disposition=VerificationFailureDisposition.PERMANENT,
        check=VerificationCheckName.INPUT_CONTRACT,
    )
    failed_check = VerificationCheck(
        name=VerificationCheckName.INPUT_CONTRACT,
        passed=False,
        failure_code=failure.code,
    )
    checks = tuple(
        failed_check if check.name is VerificationCheckName.INPUT_CONTRACT else check
        for check in result.checks
    )
    if not any(check.name is VerificationCheckName.INPUT_CONTRACT for check in result.checks):
        checks = (failed_check, *checks)
    return AttemptEvidence(
        verifier_version=result.verifier_version,
        outcome="failed",
        checked_at=result.checked_at,
        status_code=result.status_code,
        final_url=result.final_url,
        metadata_hash=result.metadata_hash,
        body_hash=result.body_hash,
        visible_text_hash=result.visible_text_hash,
        content_rule_hash=result.content_rule_hash,
        verification_rule_hash=result.verification_rule_hash,
        redirect_count=result.redirect_count,
        checks=tuple(check.to_persistence_dict() for check in checks),
        failures=(failure.to_persistence_dict(),),
        error_code=failure.code,
        failure_disposition=failure.disposition.value,
    )


def error_evidence(error: VerificationError) -> AttemptEvidence:
    failure = error.failure.to_persistence_dict()
    disposition = error.failure.disposition.value
    return AttemptEvidence(
        verifier_version="publication-url-verifier-v2",
        outcome="retryable_error" if disposition == "retryable" else "permanent_error",
        checked_at=datetime.now(UTC),
        status_code=None,
        final_url=None,
        metadata_hash=None,
        body_hash=None,
        visible_text_hash=None,
        content_rule_hash=None,
        verification_rule_hash=None,
        redirect_count=0,
        checks=(),
        failures=(failure,),
        error_code=error.failure.code,
        failure_disposition=disposition,
    )
