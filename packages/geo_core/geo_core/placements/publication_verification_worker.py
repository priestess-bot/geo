"""Atomic worker persistence for versioned publication verification attempts."""

from __future__ import annotations

from datetime import timedelta
import json
from typing import Any, Mapping

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.placements.domain import canonical_hash
from geo_core.placements.domain import PlacementRuleViolation
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
from geo_core.placements.publication_verification_evidence import (
    AttemptEvidence,
    completed_evidence,
    error_evidence,
    input_contract_failure_evidence,
)
from geo_core.placements.publication_verification_reconciliation import (
    publication_verification_job_owns_projection,
    update_publication_request_projection,
)
from geo_core.placements.url_verification_contracts import (
    PermanentVerificationError,
    UrlVerificationResult,
    VerificationCheckName,
    VerificationError,
    VerificationFailureDisposition,
)
from geo_core.placements.worker_models import VerificationSnapshot


class PublicationVerificationContractError(PermanentVerificationError):
    """A publication input needs operator action before URL verification."""

    def __init__(
        self,
        message: str,
        *,
        snapshot: VerificationSnapshot,
        code: str,
        operator_action: str,
    ) -> None:
        super().__init__(message, code=code, check=VerificationCheckName.INPUT_CONTRACT)
        self.snapshot = snapshot
        self.operator_action = operator_action


def begin_publication_verification(
    store: PostgresDurableJobStore, lease: WorkerLease
) -> VerificationSnapshot:
    with store.fenced_transaction(lease) as connection:
        _lock_verification_opportunity(connection, lease)
        record = _row(
            connection.execute(
                """SELECT s.id AS submission_id, s.submitted_url,
                          s.status AS submission_status,
                          s.publication_request_id, spec.campaign_id,
                          spec.opportunity_id, v.rendered_text, v.content_json,
                          d.allowed_hosts, bundle.binding_contract_version,
                          r.status AS publication_request_status
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
                   JOIN prompt_bundles bundle
                     ON bundle.id = v.prompt_bundle_id AND bundle.project_id = v.project_id
                    AND bundle.campaign_id = v.campaign_id
                    AND bundle.opportunity_id = v.opportunity_id
                   WHERE spec.job_id = %s AND spec.project_id = %s
                     AND spec.campaign_id = %s
                   FOR UPDATE OF s, r""",
                (lease.job_id, lease.project_id, _campaign_id(connection, lease)),
            )
        )
        if record is None or not record["submitted_url"]:
            raise RuntimeError("verification requires a submitted URL")
        snapshot_values = {
            "submission_id": record["submission_id"],
            "publication_request_id": record["publication_request_id"],
            "submitted_url": record["submitted_url"],
            "expected_text_fragments": content_fragments(record["rendered_text"]),
            "allowed_hosts": tuple(record["allowed_hosts"]),
            "campaign_id": record["campaign_id"],
            "opportunity_id": record["opportunity_id"],
        }
        if record["submission_status"] in {"blocked", "cancelled"} or record[
            "publication_request_status"
        ] in {"blocked", "cancelled"}:
            raise PublicationVerificationContractError(
                "blocked or cancelled publication state cannot be verified",
                snapshot=VerificationSnapshot(
                    **snapshot_values,
                    required_disclosures=(),
                    expected_links=(),
                ),
                code="publication_state_terminal",
                operator_action=(
                    "Create a new eligible publication request and submission; keep this "
                    "verification job as terminal audit history."
                ),
            )
        if not publication_verification_job_owns_projection(
            connection,
            job_id=lease.job_id,
            project_id=lease.project_id,
            campaign_id=record["campaign_id"],
            opportunity_id=record["opportunity_id"],
            submission_id=record["submission_id"],
        ):
            raise PublicationVerificationContractError(
                "a newer publication verification job owns this submission projection",
                snapshot=VerificationSnapshot(
                    **snapshot_values,
                    required_disclosures=(),
                    expected_links=(),
                ),
                code="verification_job_superseded",
                operator_action="Keep the newer verification job as the active authority.",
            )
        try:
            verification_contract = parse_publication_verification_contract(
                record["content_json"], disclosure_required=False
            )
        except PlacementRuleViolation as exc:
            snapshot = VerificationSnapshot(
                **snapshot_values,
                required_disclosures=(),
                expected_links=(),
            )
            legacy = record["binding_contract_version"] == "legacy-v1"
            action = (
                "Rebuild and reapprove the Package Version with explicit "
                "required_disclosures and expected_links arrays, then submit a new "
                "publication verification job; keep this job as migration history."
            )
            raise PublicationVerificationContractError(
                (
                    "legacy publication content cannot be verified under the current "
                    "frozen-content contract"
                    if legacy
                    else "publication content has an invalid frozen verification contract"
                ),
                snapshot=snapshot,
                code=(
                    "legacy_publication_contract_rebuild_required"
                    if legacy
                    else "publication_contract_rebuild_required"
                ),
                operator_action=action,
            ) from exc
        connection.execute(
            """UPDATE publication_submissions SET status = 'verifying'
               WHERE id = %s AND project_id = %s AND campaign_id = %s
                 AND opportunity_id = %s
                 AND status NOT IN ('blocked', 'cancelled', 'verified')""",
            (
                record["submission_id"],
                lease.project_id,
                record["campaign_id"],
                record["opportunity_id"],
            ),
        )
        update_publication_request_projection(
            connection,
            project_id=lease.project_id,
            campaign_id=record["campaign_id"],
            opportunity_id=record["opportunity_id"],
            publication_request_id=record["publication_request_id"],
            submission_id=record["submission_id"],
            target_status="publishing",
        )
        return VerificationSnapshot(
            **snapshot_values,
            required_disclosures=verification_contract.required_disclosures,
            expected_links=verification_contract.expected_links,
        )


def persist_completed_verification(
    store: PostgresDurableJobStore,
    lease: WorkerLease,
    snapshot: VerificationSnapshot,
    result: UrlVerificationResult,
) -> bool:
    with store.fenced_transaction(lease) as connection:
        _lock_verification_opportunity(connection, lease)
        publication_state_current = _publication_state_is_current(
            connection, lease=lease, snapshot=snapshot
        )
        owns_projection = publication_verification_job_owns_projection(
            connection,
            job_id=lease.job_id,
            project_id=lease.project_id,
            campaign_id=snapshot.campaign_id,
            opportunity_id=snapshot.opportunity_id,
            submission_id=snapshot.submission_id,
        )
        lineage_current = (
            not result.success
            or publication_request_approved_fact_evidence_is_current(
                connection,
                project_id=lease.project_id,
                publication_request_id=snapshot.publication_request_id,
            )
        )
        verified = (
            result.success and lineage_current and publication_state_current and owns_projection
        )
        if not owns_projection:
            evidence = input_contract_failure_evidence(result, code="verification_job_superseded")
        elif not lineage_current:
            evidence = input_contract_failure_evidence(result, code="lineage_stale")
        elif result.success and not publication_state_current:
            evidence = input_contract_failure_evidence(result, code="publication_state_terminal")
        else:
            evidence = completed_evidence(result)
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
                "publication_state_current": publication_state_current,
                "owns_projection": owns_projection,
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
    evidence = error_evidence(error)
    with store.fenced_transaction(lease) as connection:
        _lock_verification_opportunity(connection, lease)
        projection_values: dict[str, object] = {
            "success": False,
            "accessibility": False,
            "content_match": False,
            "disclosure_match": False,
            "link_match": False,
        }
        if isinstance(error, PublicationVerificationContractError):
            projection_values.update(
                {
                    "message": str(error),
                    "operator_action": error.operator_action,
                }
            )
        projection = _insert_attempt(
            connection,
            lease,
            snapshot,
            evidence,
            projection_values=projection_values,
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
                preserve_verified=True,
            )
            return status
        _update_submission_projection(
            connection,
            lease,
            snapshot,
            projection,
            submission_status="failed",
            publication_status="failed",
            preserve_existing_projection=isinstance(error, PublicationVerificationContractError),
        )
        store.fail_in_transaction(
            connection,
            lease,
            error_code=error.failure.code,
            details=projection,
        )
        return "failed"


def _insert_attempt(
    connection: Any,
    lease: WorkerLease,
    snapshot: VerificationSnapshot,
    evidence: AttemptEvidence,
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
    preserve_existing_projection: bool = False,
    preserve_verified: bool = False,
) -> None:
    _publication_state_record(connection, lease=lease, snapshot=snapshot)
    if not publication_verification_job_owns_projection(
        connection,
        job_id=lease.job_id,
        project_id=lease.project_id,
        campaign_id=snapshot.campaign_id,
        opportunity_id=snapshot.opportunity_id,
        submission_id=snapshot.submission_id,
    ):
        return
    verified_at = projection["checked_at"] if submission_status == "verified" else None
    connection.execute(
        """UPDATE publication_submissions SET status = %s, verified_at = %s,
             verification_result = CASE WHEN %s THEN verification_result ELSE %s::jsonb END
           WHERE id = %s AND project_id = %s AND campaign_id = %s
             AND opportunity_id = %s
             AND status NOT IN ('blocked', 'cancelled')
             AND (NOT %s OR status <> 'verified' OR %s = 'verified')""",
        (
            submission_status,
            verified_at,
            preserve_existing_projection,
            json.dumps(dict(projection)),
            snapshot.submission_id,
            lease.project_id,
            snapshot.campaign_id,
            snapshot.opportunity_id,
            preserve_verified,
            submission_status,
        ),
    )
    update_publication_request_projection(
        connection,
        project_id=lease.project_id,
        campaign_id=snapshot.campaign_id,
        opportunity_id=snapshot.opportunity_id,
        publication_request_id=snapshot.publication_request_id,
        submission_id=snapshot.submission_id,
        target_status=publication_status,
    )


def _publication_state_is_current(
    connection: Any, *, lease: WorkerLease, snapshot: VerificationSnapshot
) -> bool:
    record = _publication_state_record(connection, lease=lease, snapshot=snapshot)
    return record["submission_status"] not in {"blocked", "cancelled"} and record[
        "publication_request_status"
    ] not in {"blocked", "cancelled"}


def _publication_state_record(
    connection: Any, *, lease: WorkerLease, snapshot: VerificationSnapshot
) -> Mapping[str, object]:
    record = _row(
        connection.execute(
            """SELECT submission.status AS submission_status,
                      request.status AS publication_request_status
               FROM publication_submissions submission
               JOIN publication_requests request
                 ON request.id = submission.publication_request_id
                AND request.project_id = submission.project_id
                AND request.campaign_id = submission.campaign_id
                AND request.opportunity_id = submission.opportunity_id
               WHERE submission.id = %s AND submission.project_id = %s
                 AND submission.campaign_id = %s AND submission.opportunity_id = %s
                 AND request.id = %s
               FOR UPDATE OF submission, request""",
            (
                snapshot.submission_id,
                lease.project_id,
                snapshot.campaign_id,
                snapshot.opportunity_id,
                snapshot.publication_request_id,
            ),
        )
    )
    if record is None:
        raise RuntimeError("publication verification context disappeared")
    return record


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


def _lock_verification_opportunity(connection: Any, lease: WorkerLease) -> None:
    record = _row(
        connection.execute(
            """SELECT opportunity.id
               FROM verification_job_specs spec
               JOIN placement_opportunities opportunity
                 ON opportunity.id = spec.opportunity_id
                AND opportunity.project_id = spec.project_id
                AND opportunity.campaign_id = spec.campaign_id
               WHERE spec.job_id = %s AND spec.project_id = %s
               FOR UPDATE OF opportunity""",
            (lease.job_id, lease.project_id),
        )
    )
    if record is None:
        raise RuntimeError("verification opportunity context disappeared")


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((item.name for item in cursor.description), value, strict=True))
