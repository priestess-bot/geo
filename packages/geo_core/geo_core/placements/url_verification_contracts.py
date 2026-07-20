"""Stable contracts for versioned publication URL verification evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


VERIFIER_CONTRACT_VERSION = "publication-url-verifier-v2"


class VerificationFailureDisposition(StrEnum):
    """Whether the same verifier input may succeed without an operator correction."""

    RETRYABLE = "retryable"
    PERMANENT = "permanent"


class VerificationCheckName(StrEnum):
    """Stable identifiers stored with a publication verification attempt."""

    INPUT_CONTRACT = "input_contract"
    PUBLIC_URL = "public_url"
    REDIRECT_POLICY = "redirect_policy"
    HTTP_2XX = "http_2xx"
    HTML_RESPONSE = "html_response"
    APPROVED_CONTENT = "approved_content"
    REQUIRED_DISCLOSURES = "required_disclosures"
    EXPECTED_LINKS = "expected_links"


@dataclass(frozen=True)
class VerificationCheck:
    name: VerificationCheckName
    passed: bool
    failure_code: str | None = None

    def to_persistence_dict(self) -> dict[str, object]:
        return {
            "name": self.name.value,
            "passed": self.passed,
            "failure_code": self.failure_code,
        }


@dataclass(frozen=True)
class VerificationFailure:
    code: str
    disposition: VerificationFailureDisposition
    check: VerificationCheckName

    @property
    def retryable(self) -> bool:
        return self.disposition is VerificationFailureDisposition.RETRYABLE

    def to_persistence_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "disposition": self.disposition.value,
            "check": self.check.value,
            "retryable": self.retryable,
        }


class VerificationError(RuntimeError):
    """Base error carrying a stable, non-sensitive failure DTO."""

    disposition: VerificationFailureDisposition
    default_code = "verification_error"
    default_check = VerificationCheckName.INPUT_CONTRACT

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        check: VerificationCheckName | None = None,
    ) -> None:
        super().__init__(message)
        self.failure = VerificationFailure(
            code=code or self.default_code,
            disposition=self.disposition,
            check=check or self.default_check,
        )

    def to_persistence_dict(self) -> dict[str, object]:
        return {
            "verifier_version": VERIFIER_CONTRACT_VERSION,
            "failure": self.failure.to_persistence_dict(),
        }


class RetryableVerificationError(VerificationError):
    """A network, throttling, or upstream availability failure."""

    disposition = VerificationFailureDisposition.RETRYABLE
    default_code = "verification_temporarily_unavailable"
    default_check = VerificationCheckName.PUBLIC_URL


class PermanentVerificationError(VerificationError):
    """A URL, response, or verification contract requires operator correction."""

    disposition = VerificationFailureDisposition.PERMANENT
    default_code = "verification_policy_failure"
    default_check = VerificationCheckName.INPUT_CONTRACT


@dataclass(frozen=True)
class UrlVerificationResult:
    # The first nine fields are retained in their original order for caller compatibility.
    success: bool
    status_code: int
    final_url: str
    checked_at: datetime
    metadata_hash: str
    accessibility: bool
    content_match: bool
    disclosure_match: bool
    link_match: bool
    verifier_version: str = VERIFIER_CONTRACT_VERSION
    checks: tuple[VerificationCheck, ...] = ()
    failures: tuple[VerificationFailure, ...] = ()
    body_hash: str = ""
    visible_text_hash: str = ""
    content_rule_hash: str = ""
    verification_rule_hash: str = ""
    redirect_count: int = 0

    @property
    def evidence_hash(self) -> str:
        return self.metadata_hash

    def to_persistence_dict(self) -> dict[str, object]:
        """Return versioned evidence without retaining the fetched page body."""

        return {
            "success": self.success,
            "status_code": self.status_code,
            "final_url": self.final_url,
            "checked_at": self.checked_at.isoformat(),
            "verifier_version": self.verifier_version,
            "metadata_hash": self.metadata_hash,
            "body_hash": self.body_hash,
            "visible_text_hash": self.visible_text_hash,
            "content_rule_hash": self.content_rule_hash,
            "verification_rule_hash": self.verification_rule_hash,
            "redirect_count": self.redirect_count,
            "accessibility": self.accessibility,
            "content_match": self.content_match,
            "disclosure_match": self.disclosure_match,
            "link_match": self.link_match,
            "checks": [check.to_persistence_dict() for check in self.checks],
            "failures": [failure.to_persistence_dict() for failure in self.failures],
        }
