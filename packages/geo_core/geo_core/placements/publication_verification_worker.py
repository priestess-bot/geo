"""Atomic worker persistence for versioned publication verification attempts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from typing import Any, Mapping

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.placements.domain import canonical_hash
from geo_core.placements.package_execution_eligibility import (
    publication_request_approved_fact_evidence_is_current,
)
from geo_core.placements.publication_worker_support import (
    advance_verified_opportunity,
    content_fragments,
    schedule_measurements,
)
from geo_core.placements.publication_contract import (
    parse_publication_verification_contract,
)
from geo_core.placements.publication_verification_records import VerificationOutcome
from geo_core.placements.url_verification_contracts import (
    UrlVerificationResult,
    VerificationCheck,
    VerificationCheckName,
    VerificationError,
    VerificationFailure,
    VerificationFailureDisposition,
)
from geo_core.placements.worker_models import VerificationSnapshot


@dataclass(frozen=True)
class _AttemptEvidence:
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


def begin_publication_verification(
    store: PostgresDurableJobStore, lease: WorkerLease
) -> VerificationSnapshot:
    with store.fenced_transaction(lease) as connection:
        record = _row(
            connection.execute(
                """SELECT s.id AS submission_id, s.submitted_url,
                          s.publication_request_id, spec.campaign_id,
                          spec.opportunity_id, v.rendered_text, v.content_json,
                          d.allowed_hosts
                   FROM verification_job_specs spec
                   JOIN publication_submissions s
                     ON s.id = spec.submission_id AND s.project_id = spec.project_id
                    AND s.campaign_id = spec.campaign_id
                    AND s.opportunity_id = spec.opportunity_id
                   JOIN publication_requests r
                     ON r.id = s.publication_request_id AND r.project_id = s.project_id
                    AND r.campaign_id = s.campaign_id
                    AND r.opportunity_id = s.opportunity_id
                   JOIN publication_destinations d
                     ON d.id = r.destination_id AND d.project_id = r.project_id
                   JOIN placement_package_versions v
                     ON v.id = r.package_version_id AND v.project_id = r.project_id
                    AND v.campaign_id = r.campaign_id
                    AND v.opportunity_id = r.opportunity_id
                   WHERE spec.job_id = %s AND spec.project_id = %s
                     AND spec.campaign_id = %s""",
                (lease.job_id, lease.project_id, _campaign_id(connection, lease)),
            )
        )
        if record is None or not record["submitted_url"]:
            raise RuntimeError("verification requires a submitted URL")
        connection.execute(
            """UPDATE publication_submissions SET status = 'verifying'
               WHERE id = %s AND project_id = %s""",
            (record["submission_id"], lease.project_id),
        )
        connection.execute(
            """UPDATE publication_requests SET status = 'publishing'
               WHERE id = %s AND project_id = %s""",
            (record["publication_request_id"], lease.project_id),
        )
        verification_contract = parse_publication_verification_contract(
            record["content_json"], disclosure_required=False
        )
        return VerificationSnapshot(
            submission_id=record["submission_id"],
            publication_request_id=record["publication_request_id"],
            submitted_url=record["submitted_url"],
            expected_text_fragments=content_fragments(record["rendered_text"]),
            required_disclosures=verification_contract.required_disclosures,
            expected_links=verification_contract.expected_links,
            allowed_hosts=tuple(record["allowed_hosts"]),
            campaign_id=record["campaign_id"],
            opportunity_id=record["opportunity_id"],
        )


def persist_completed_verification(
    store: PostgresDurableJobStore,
    lease: WorkerLease,
    snapshot: VerificationSnapshot,
    result: UrlVerificationResult,
) -> bool:
    with store.fenced_transaction(lease) as connection:
        lineage_current = (
            not result.success
            or publication_request_approved_fact_evidence_is_current(
                connection,
                project_id=lease.project_id,
                publication_request_id=snapshot.publication_request_id,
            )
        )
        verified = result.success and lineage_current
        evidence = (
            _completed_evidence(result) if lineage_current else _lineage_stale_evidence(result)
        )
        projection = _insert_attempt(
            connection,
            lease,
            snapshot,
            evidence,
            projection_values={
                "success": verified,
                "accessibility": result.accessibility,
                "content_match": result.content_match,
                "disclosure_match": result.disclosure_match,
                "link_match": result.link_match,
                "lineage_current": lineage_current,
            },
        )
        _update_submission_projection(
            connection,
            lease,
            snapshot,
            projection,
            submission_status="verified" if verified else "failed",
            publication_status="published" if verified else "failed",
        )
        if verified:
            advance_verified_opportunity(connection, lease.project_id, snapshot.submission_id)
        scheduled = (
            schedule_measurements(connection, lease, snapshot.submission_id) if verified else 0
        )
        details = {**projection, "verified": verified, "measurement_jobs": scheduled}
        store.complete_in_transaction(
            connection,
            lease,
            result_ref=f"publication-verification:{snapshot.submission_id}",
            details=details,
        )
    return verified


def persist_verification_error(
    store: PostgresDurableJobStore,
    lease: WorkerLease,
    snapshot: VerificationSnapshot,
    error: VerificationError,
) -> str:
    evidence = _error_evidence(error)
    with store.fenced_transaction(lease) as connection:
        projection = _insert_attempt(
            connection,
            lease,
            snapshot,
            evidence,
            projection_values={
                "success": False,
                "accessibility": False,
                "content_match": False,
                "disclosure_match": False,
                "link_match": False,
            },
        )
        if error.failure.disposition is VerificationFailureDisposition.RETRYABLE:
            status = store.fail_with_retry_in_transaction(
                connection,
                lease,
                error_code=error.failure.code,
                details=projection,
                retry_delay=timedelta(seconds=30),
            )
            terminal = status == "dead_lettered"
            _update_submission_projection(
                connection,
                lease,
                snapshot,
                projection,
                submission_status="failed" if terminal else "verifying",
                publication_status="failed" if terminal else "retrying",
            )
            return status
        _update_submission_projection(
            connection,
            lease,
            snapshot,
            projection,
            submission_status="failed",
            publication_status="failed",
        )
        store.fail_in_transaction(
            connection,
            lease,
            error_code=error.failure.code,
            details=projection,
        )
        return "failed"


def _completed_evidence(result: UrlVerificationResult) -> _AttemptEvidence:
    checks = tuple(check.to_persistence_dict() for check in result.checks)
    failures = tuple(failure.to_persistence_dict() for failure in result.failures)
    if not result.success and not failures:
        raise ValueError("failed verification results require stable failure evidence")
    return _AttemptEvidence(
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


def _lineage_stale_evidence(result: UrlVerificationResult) -> _AttemptEvidence:
    failure = VerificationFailure(
        code="lineage_stale",
        disposition=VerificationFailureDisposition.PERMANENT,
        check=VerificationCheckName.INPUT_CONTRACT,
    )
    stale_check = VerificationCheck(
        name=VerificationCheckName.INPUT_CONTRACT,
        passed=False,
        failure_code=failure.code,
    )
    checks = tuple(
        stale_check if check.name is VerificationCheckName.INPUT_CONTRACT else check
        for check in result.checks
    )
    if not any(check.name is VerificationCheckName.INPUT_CONTRACT for check in result.checks):
        checks = (stale_check, *checks)
    return _AttemptEvidence(
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


def _error_evidence(error: VerificationError) -> _AttemptEvidence:
    failure = error.failure.to_persistence_dict()
    disposition = error.failure.disposition.value
    return _AttemptEvidence(
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


def _insert_attempt(
    connection: Any,
    lease: WorkerLease,
    snapshot: VerificationSnapshot,
    evidence: _AttemptEvidence,
    *,
    projection_values: Mapping[str, object] | None = None,
) -> dict[str, object]:
    result_hash = canonical_hash(evidence.hash_input())
    record = _row(
        connection.execute(
            """INSERT INTO publication_verification_attempts
                 (project_id, campaign_id, opportunity_id, submission_id, job_id,
                  attempt_number, verifier_version, outcome, checked_at, status_code,
                  final_url, metadata_hash, body_hash, visible_text_hash,
                  content_rule_hash, verification_rule_hash, redirect_count,
                  checks, failures, error_code, failure_disposition, result_hash)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
               RETURNING id, created_at""",
            (
                lease.project_id,
                snapshot.campaign_id,
                snapshot.opportunity_id,
                snapshot.submission_id,
                lease.job_id,
                lease.attempt_count,
                evidence.verifier_version,
                evidence.outcome,
                evidence.checked_at,
                evidence.status_code,
                evidence.final_url,
                evidence.metadata_hash,
                evidence.body_hash,
                evidence.visible_text_hash,
                evidence.content_rule_hash,
                evidence.verification_rule_hash,
                evidence.redirect_count,
                json.dumps(list(evidence.checks)),
                json.dumps(list(evidence.failures)),
                evidence.error_code,
                evidence.failure_disposition,
                result_hash,
            ),
        )
    )
    if record is None:
        raise RuntimeError("publication verification attempt was not persisted")
    return {
        "schema_version": "publication-verification-projection-v2",
        "attempt_id": str(record["id"]),
        "job_id": str(lease.job_id),
        "attempt_number": lease.attempt_count,
        **evidence.hash_input(),
        **dict(projection_values or {}),
        "result_hash": result_hash,
        "created_at": record["created_at"].isoformat(),
    }


def _update_submission_projection(
    connection: Any,
    lease: WorkerLease,
    snapshot: VerificationSnapshot,
    projection: Mapping[str, object],
    *,
    submission_status: str,
    publication_status: str,
) -> None:
    verified_at = projection["checked_at"] if submission_status == "verified" else None
    updated = connection.execute(
        """UPDATE publication_submissions SET status = %s, verified_at = %s,
             verification_result = %s::jsonb
           WHERE id = %s AND project_id = %s AND campaign_id = %s
             AND opportunity_id = %s""",
        (
            submission_status,
            verified_at,
            json.dumps(dict(projection)),
            snapshot.submission_id,
            lease.project_id,
            snapshot.campaign_id,
            snapshot.opportunity_id,
        ),
    ).rowcount
    if updated != 1:
        raise RuntimeError("publication verification submission context disappeared")
    changed = connection.execute(
        """UPDATE publication_requests SET status = %s
           WHERE id = %s AND project_id = %s AND campaign_id = %s
             AND opportunity_id = %s""",
        (
            publication_status,
            snapshot.publication_request_id,
            lease.project_id,
            snapshot.campaign_id,
            snapshot.opportunity_id,
        ),
    ).rowcount
    if changed != 1:
        raise RuntimeError("publication verification request context disappeared")


def _campaign_id(connection: Any, lease: WorkerLease) -> object:
    record = _row(
        connection.execute(
            """SELECT campaign_id FROM durable_jobs
               WHERE id = %s AND project_id = %s""",
            (lease.job_id, lease.project_id),
        )
    )
    if record is None or record["campaign_id"] is None:
        raise RuntimeError("verification job campaign context does not exist")
    return record["campaign_id"]


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((item.name for item in cursor.description), value, strict=True))
