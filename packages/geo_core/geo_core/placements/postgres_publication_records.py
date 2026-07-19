"""Campaign-scoped publication, submission, verification, and measurement records."""

from __future__ import annotations

import json
from typing import Any, Literal, Mapping, cast
from urllib.parse import urlparse
from uuid import UUID

from geo_core.placements.domain import (
    JobReference,
    Measurement,
    PlacementConflict,
    PlacementRuleViolation,
    PublicationRequest,
    Submission,
)
from geo_core.placements.errors import PlacementContractMigrationRequired
from geo_core.placements.package_execution_eligibility import (
    package_approved_fact_evidence_is_current,
)
from geo_core.placements.postgres_publication_idempotency import (
    find_publication_request_replay,
    find_submission_replay,
)
from geo_core.placements.publication_verification_records import (
    PublicationVerificationAttempt,
    VerificationOutcome,
)
from geo_core.placements.publication_contract import (
    parse_frozen_publication_verification_contract,
)


class PostgresPublicationRecordMixin:
    _db: Any

    def _enqueue_job(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        kind: str,
        input_value: Mapping[str, object],
        idempotency_key: str,
    ) -> JobReference:
        raise NotImplementedError

    def create_publication_request(self, **values: Any) -> PublicationRequest:
        replay = find_publication_request_replay(self._db, values)
        if replay is not None:
            return PublicationRequest(**replay)
        context = _one(
            self._db.execute(
                """SELECT version.campaign_id, version.opportunity_id,
                          version.destination_id, version.workflow_status,
                          version.content_json, bundle.input_snapshot,
                          bundle.binding_contract_version
                   FROM placement_package_versions AS version
                   JOIN prompt_bundles AS bundle
                     ON bundle.id = version.prompt_bundle_id
                    AND bundle.project_id = version.project_id
                   WHERE version.id = %s AND version.project_id = %s
                     AND version.destination_id = %s
                   FOR UPDATE OF version""",
                (values["version_id"], values["project_id"], values["destination_id"]),
            )
        )
        if context["workflow_status"] != "approved":
            raise PlacementRuleViolation("publication requires an approved Package Version")
        if context["binding_contract_version"] != "opportunity-binding-v2":
            raise PlacementRuleViolation(
                "publication requires a current Opportunity-bound Prompt Bundle"
            )
        if not package_approved_fact_evidence_is_current(
            self._db,
            project_id=values["project_id"],
            package_version_id=values["version_id"],
        ):
            raise PlacementRuleViolation("publication requires current approved Fact Evidence")
        parse_frozen_publication_verification_contract(
            context["content_json"], {"manifest": context["input_snapshot"]}
        )
        for field in (
            "workflow_status",
            "content_json",
            "input_snapshot",
            "binding_contract_version",
        ):
            context.pop(field)
        params = {**values, **context}
        records = _many(
            self._db.execute(
                """INSERT INTO publication_requests
                     (project_id, campaign_id, opportunity_id, package_version_id,
                      destination_id, requested_by, publication_attempt, idempotency_key,
                      restricted_policy_acknowledged, policy_basis)
                   VALUES (%(project_id)s, %(campaign_id)s, %(opportunity_id)s,
                           %(version_id)s, %(destination_id)s, %(requested_by)s,
                           %(publication_attempt)s, %(idempotency_key)s,
                           %(restricted_policy_acknowledged)s, %(policy_basis)s)
                   ON CONFLICT (project_id, idempotency_key) DO UPDATE
                     SET idempotency_key = EXCLUDED.idempotency_key
                     WHERE publication_requests.package_version_id = EXCLUDED.package_version_id
                       AND publication_requests.destination_id = EXCLUDED.destination_id
                       AND publication_requests.publication_attempt = EXCLUDED.publication_attempt
                   RETURNING id, project_id, campaign_id, opportunity_id,
                             package_version_id, destination_id, publication_attempt,
                             idempotency_key, restricted_policy_acknowledged,
                             policy_basis, status""",
                params,
            )
        )
        if not records:
            replay = find_publication_request_replay(self._db, values)
            if replay is None:
                raise RuntimeError("publication idempotency conflict lost its row")
            return PublicationRequest(**replay)
        destination = _one(
            self._db.execute(
                """SELECT publication_channel, destination_key FROM publication_destinations
                   WHERE project_id = %s AND id = %s""",
                (values["project_id"], values["destination_id"]),
            )
        )
        return PublicationRequest(**records[0], **destination)

    def create_submission(self, **values: Any) -> Submission:
        replay = find_submission_replay(
            self._db,
            project_id=values["project_id"],
            idempotency_key=values["idempotency_key"],
            payload_hash=values["payload_hash"],
        )
        if replay is not None:
            return Submission(**replay)
        request = _one(
            self._db.execute(
                """SELECT r.campaign_id, r.opportunity_id, r.destination_id,
                          r.status AS request_status, d.allowed_hosts,
                          bundle.binding_contract_version
                   FROM publication_requests r
                   JOIN publication_destinations d
                     ON d.id = r.destination_id AND d.project_id = r.project_id
                   JOIN placement_package_versions version
                     ON version.id = r.package_version_id
                    AND version.project_id = r.project_id
                    AND version.campaign_id = r.campaign_id
                    AND version.opportunity_id = r.opportunity_id
                    AND version.destination_id = r.destination_id
                   JOIN prompt_bundles bundle
                     ON bundle.id = version.prompt_bundle_id
                    AND bundle.project_id = version.project_id
                    AND bundle.campaign_id = version.campaign_id
                    AND bundle.opportunity_id = version.opportunity_id
                    AND bundle.destination_id = version.destination_id
                   WHERE r.id = %s AND r.project_id = %s FOR UPDATE OF r""",
                (values["publication_request_id"], values["project_id"]),
            )
        )
        if request["request_status"] in {"blocked", "cancelled"}:
            raise PlacementRuleViolation(
                "blocked or cancelled publication requests cannot accept new submissions"
            )
        if request["binding_contract_version"] != "opportunity-binding-v2":
            raise PlacementRuleViolation(
                "new submissions require a current Opportunity-bound Prompt Bundle"
            )
        if values["submitted_url"]:
            _validate_submitted_url(values["submitted_url"], request["allowed_hosts"])
        status = "submitted" if values["submitted_url"] else "awaiting_url"
        created = _many(
            self._db.execute(
                """INSERT INTO publication_submissions
                     (project_id, campaign_id, opportunity_id, destination_id,
                      publication_request_id, submitted_url, provider_submission_id,
                      status, submitted_at, idempotency_key, payload_hash, submitted_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                     CASE WHEN %s = 'submitted' THEN clock_timestamp() ELSE NULL END,
                     %s, %s, %s)
                   ON CONFLICT (project_id, idempotency_key) DO NOTHING
                   RETURNING id, project_id, campaign_id, opportunity_id, destination_id,
                             publication_request_id, status, submitted_url,
                             provider_submission_id, verification_result,
                             url_backfilled_by, url_backfilled_at,
                             idempotency_key, submitted_by""",
                (
                    values["project_id"],
                    request["campaign_id"],
                    request["opportunity_id"],
                    request["destination_id"],
                    values["publication_request_id"],
                    values["submitted_url"],
                    values["provider_submission_id"],
                    status,
                    status,
                    values["idempotency_key"],
                    values["payload_hash"],
                    values["submitted_by"],
                ),
            )
        )
        if created:
            return Submission(**created[0])
        replay = find_submission_replay(
            self._db,
            project_id=values["project_id"],
            idempotency_key=values["idempotency_key"],
            payload_hash=values["payload_hash"],
        )
        if replay is None:
            raise RuntimeError("submission idempotency conflict lost its row")
        return Submission(**replay)

    def backfill_submission_url(
        self, *, project_id: UUID, submission_id: UUID, submitted_url: str, actor_id: UUID
    ) -> Submission:
        record = _one(
            self._db.execute(
                """SELECT s.id, s.project_id, s.campaign_id, s.opportunity_id,
                          s.destination_id, s.publication_request_id, s.status,
                          s.submitted_url, s.provider_submission_id, s.verification_result,
                          s.url_backfilled_by, s.url_backfilled_at, s.idempotency_key,
                          s.submitted_by, d.allowed_hosts,
                          r.status AS publication_status
                   FROM publication_submissions s JOIN publication_requests r
                     ON r.id = s.publication_request_id AND r.project_id = s.project_id
                   JOIN publication_destinations d
                     ON d.id = r.destination_id AND d.project_id = r.project_id
                   WHERE s.id = %s AND s.project_id = %s FOR UPDATE OF s, r""",
                (submission_id, project_id),
            )
        )
        if record["submitted_url"] == submitted_url:
            record.pop("allowed_hosts")
            record.pop("publication_status")
            return Submission(**record)
        if record["publication_status"] in {"blocked", "cancelled"}:
            raise PlacementRuleViolation(
                "blocked or cancelled publication requests cannot accept a URL backfill"
            )
        _validate_submitted_url(submitted_url, record["allowed_hosts"])
        if record["status"] != "awaiting_url" or record["submitted_url"] is not None:
            raise PlacementRuleViolation("submission URL cannot be overwritten")
        updated = _one(
            self._db.execute(
                """UPDATE publication_submissions
                   SET submitted_url = %s, status = 'submitted', submitted_at = clock_timestamp(),
                       url_backfilled_by = %s, url_backfilled_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s
                   RETURNING id, project_id, campaign_id, opportunity_id, destination_id,
                     publication_request_id, status, submitted_url, provider_submission_id,
                     verification_result, url_backfilled_by, url_backfilled_at,
                     idempotency_key, submitted_by""",
                (submitted_url, actor_id, submission_id, project_id),
            )
        )
        return Submission(**updated)

    def transition_submission(self, **values: Any) -> Submission:
        record = _one(
            self._db.execute(
                """UPDATE publication_submissions SET status = %(status)s,
                     state_reason = %(reason)s, state_changed_by = %(actor_id)s,
                     state_changed_at = clock_timestamp()
                   WHERE id = %(submission_id)s AND project_id = %(project_id)s
                     AND status IN ('awaiting_url', 'submitted', 'failed', 'blocked')
                   RETURNING id, project_id, campaign_id, opportunity_id, destination_id,
                     publication_request_id, status, submitted_url, provider_submission_id,
                     verification_result, url_backfilled_by, url_backfilled_at,
                     idempotency_key, submitted_by""",
                values,
            )
        )
        return Submission(**record)

    def transition_publication(self, **values: Any) -> PublicationRequest:
        record = _one(
            self._db.execute(
                """UPDATE publication_requests SET status = %(status)s,
                     state_reason = %(reason)s, state_changed_by = %(actor_id)s,
                     state_changed_at = clock_timestamp()
                   WHERE id = %(publication_request_id)s AND project_id = %(project_id)s
                     AND status IN ('requested', 'scheduled', 'retrying', 'failed', 'blocked')
                   RETURNING id, project_id, campaign_id, opportunity_id,
                     package_version_id, destination_id, publication_attempt,
                     idempotency_key, restricted_policy_acknowledged, policy_basis, status""",
                values,
            )
        )
        destination = _one(
            self._db.execute(
                """SELECT publication_channel, destination_key FROM publication_destinations
                   WHERE id = %s AND project_id = %s""",
                (record["destination_id"], values["project_id"]),
            )
        )
        return PublicationRequest(**record, **destination)

    def list_publication_requests(
        self, *, project_id: UUID, version_id: UUID
    ) -> tuple[PublicationRequest, ...]:
        records = _many(
            self._db.execute(
                """SELECT r.id, r.project_id, r.campaign_id, r.opportunity_id,
                          r.package_version_id, r.destination_id, d.publication_channel,
                          d.destination_key, r.publication_attempt, r.idempotency_key,
                          r.restricted_policy_acknowledged, r.policy_basis, r.status
                   FROM publication_requests r JOIN publication_destinations d
                     ON d.id = r.destination_id AND d.project_id = r.project_id
                   WHERE r.project_id = %s AND r.package_version_id = %s
                   ORDER BY r.requested_at""",
                (project_id, version_id),
            )
        )
        return tuple(PublicationRequest(**record) for record in records)

    def list_submissions(
        self, *, project_id: UUID, publication_request_id: UUID
    ) -> tuple[Submission, ...]:
        return tuple(
            Submission(**record)
            for record in _many(
                self._db.execute(
                    _SUBMISSION_SELECT
                    + " WHERE project_id = %s AND publication_request_id = %s"
                    + " ORDER BY created_at",
                    (project_id, publication_request_id),
                )
            )
        )

    def get_submission(self, *, project_id: UUID, submission_id: UUID) -> Submission | None:
        records = _many(
            self._db.execute(
                _SUBMISSION_SELECT + " WHERE project_id = %s AND id = %s",
                (project_id, submission_id),
            )
        )
        return Submission(**records[0]) if records else None

    def list_verification_attempts(
        self, *, project_id: UUID, submission_id: UUID
    ) -> tuple[PublicationVerificationAttempt, ...]:
        records = _many(
            self._db.execute(
                """SELECT id, project_id, campaign_id, opportunity_id, submission_id,
                          job_id, attempt_number, verifier_version, outcome, checked_at,
                          status_code, final_url, metadata_hash, body_hash,
                          visible_text_hash, content_rule_hash, verification_rule_hash,
                          redirect_count, checks, failures, error_code,
                          failure_disposition, result_hash, created_at
                   FROM publication_verification_attempts
                   WHERE project_id = %s AND submission_id = %s
                   ORDER BY checked_at DESC, created_at DESC, id DESC""",
                (project_id, submission_id),
            )
        )
        return tuple(_verification_attempt(record) for record in records)

    def enqueue_verification(
        self, *, project_id: UUID, submission_id: UUID, idempotency_key: str
    ) -> JobReference:
        context = _one(
            self._db.execute(
                """SELECT submission.campaign_id, submission.opportunity_id,
                          submission.submitted_url, submission.status,
                          bundle.binding_contract_version,
                          request.status AS publication_request_status
                   FROM publication_submissions submission
                   JOIN publication_requests request
                     ON request.id = submission.publication_request_id
                    AND request.project_id = submission.project_id
                    AND request.campaign_id = submission.campaign_id
                    AND request.opportunity_id = submission.opportunity_id
                   JOIN placement_package_versions version
                     ON version.id = request.package_version_id
                    AND version.project_id = request.project_id
                    AND version.campaign_id = request.campaign_id
                    AND version.opportunity_id = request.opportunity_id
                   JOIN prompt_bundles bundle
                     ON bundle.id = version.prompt_bundle_id
                    AND bundle.project_id = version.project_id
                    AND bundle.campaign_id = version.campaign_id
                    AND bundle.opportunity_id = version.opportunity_id
                   WHERE submission.id = %s AND submission.project_id = %s
                   FOR UPDATE OF submission, request""",
                (submission_id, project_id),
            )
        )
        exact = _many(
            self._db.execute(
                """SELECT job.id, job.project_id, job.campaign_id, job.kind,
                          job.status
                   FROM verification_job_specs spec
                   JOIN durable_jobs job
                     ON job.id = spec.job_id AND job.project_id = spec.project_id
                    AND job.campaign_id = spec.campaign_id
                   WHERE spec.project_id = %s AND spec.campaign_id = %s
                     AND spec.opportunity_id = %s AND spec.submission_id = %s
                     AND job.idempotency_key = %s
                     AND job.replay_nonce = 0
                   ORDER BY job.created_at DESC LIMIT 1""",
                (
                    project_id,
                    context["campaign_id"],
                    context["opportunity_id"],
                    submission_id,
                    idempotency_key,
                ),
            )
        )
        if exact:
            return JobReference(**exact[0])
        if context["publication_request_status"] in {"blocked", "cancelled"}:
            raise PlacementRuleViolation(
                "blocked or cancelled publication requests cannot be verified"
            )
        if context["status"] in {"blocked", "cancelled"}:
            raise PlacementRuleViolation("blocked or cancelled submissions cannot be verified")
        if not context["submitted_url"]:
            raise PlacementRuleViolation("verification requires a submitted URL")
        if context["binding_contract_version"] != "opportunity-binding-v2":
            raise PlacementContractMigrationRequired(
                "legacy submissions cannot create new publication verification jobs",
                error_code="legacy_verification_enqueue_rebuild_required",
                operator_action=(
                    "Rebuild and reapprove a Package Version from a current "
                    "Opportunity-bound Prompt Bundle, then create a new submission; "
                    "keep the legacy submission and job history."
                ),
            )
        active = _many(
            self._db.execute(
                """SELECT job.id, job.project_id, job.campaign_id, job.kind, job.status
                   FROM verification_job_specs spec
                   JOIN durable_jobs job
                     ON job.id = spec.job_id AND job.project_id = spec.project_id
                    AND job.campaign_id = spec.campaign_id
                   WHERE spec.project_id = %s AND spec.campaign_id = %s
                     AND spec.opportunity_id = %s AND spec.submission_id = %s
                     AND job.status IN ('queued', 'running', 'finalizing', 'retry_wait')
                   ORDER BY job.created_at DESC LIMIT 1""",
                (
                    project_id,
                    context["campaign_id"],
                    context["opportunity_id"],
                    submission_id,
                ),
            )
        )
        if active:
            raise PlacementConflict("publication verification is already active")
        job = self._enqueue_job(
            project_id=project_id,
            campaign_id=context["campaign_id"],
            kind="publication.verify",
            input_value={"submission_id": str(submission_id)},
            idempotency_key=idempotency_key,
        )
        self._db.execute(
            """INSERT INTO verification_job_specs
                 (job_id, project_id, campaign_id, opportunity_id, submission_id)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (job_id) DO NOTHING""",
            (
                job.id,
                project_id,
                context["campaign_id"],
                context["opportunity_id"],
                submission_id,
            ),
        )
        return job

    def record_measurement(self, **values: Any) -> Measurement:
        context = _one(
            self._db.execute(
                """SELECT campaign_id, opportunity_id, destination_id, status, verified_at
                   FROM publication_submissions
                   WHERE id = %s AND project_id = %s FOR UPDATE""",
                (values["submission_id"], values["project_id"]),
            )
        )
        if context["status"] != "verified" or context["verified_at"] is None:
            raise PlacementRuleViolation("measurements require a currently verified submission")
        context.pop("status")
        context.pop("verified_at")
        record = _one(
            self._db.execute(
                """INSERT INTO placement_measurements
                     (project_id, campaign_id, opportunity_id, destination_id,
                      submission_id, monitoring_query_id, measured_at, citation_present,
                      recommendation_position, result_snapshot_uri, metrics)
                   VALUES (%(project_id)s, %(campaign_id)s, %(opportunity_id)s,
                           %(destination_id)s, %(submission_id)s, %(monitoring_query_id)s,
                           %(measured_at)s, %(citation_present)s,
                           %(recommendation_position)s, %(result_snapshot_uri)s,
                           %(metrics)s::jsonb)
                   RETURNING id, project_id, campaign_id, opportunity_id, destination_id,
                             submission_id, monitoring_query_id, measured_at,
                             citation_present, recommendation_position,
                             result_snapshot_uri, metrics""",
                {**values, **context, "metrics": json.dumps(values["metrics"])},
            )
        )
        return Measurement(**record)

    def list_measurements(
        self, *, project_id: UUID, submission_id: UUID
    ) -> tuple[Measurement, ...]:
        rows = _many(
            self._db.execute(
                """SELECT id, project_id, campaign_id, opportunity_id, destination_id,
                          submission_id, monitoring_query_id, measured_at,
                          citation_present, recommendation_position,
                          result_snapshot_uri, metrics
                   FROM placement_measurements
                   WHERE project_id = %s AND submission_id = %s
                   ORDER BY measured_at DESC""",
                (project_id, submission_id),
            )
        )
        return tuple(Measurement(**row) for row in rows)


_SUBMISSION_SELECT = """
    SELECT id, project_id, campaign_id, opportunity_id, destination_id,
           publication_request_id, status, submitted_url, provider_submission_id,
           verification_result, url_backfilled_by, url_backfilled_at,
           idempotency_key, submitted_by
    FROM publication_submissions
"""


def _validate_submitted_url(url: str, allowed_hosts: list[str]) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.hostname.casefold() not in allowed_hosts
    ):
        raise PlacementRuleViolation("submitted URL must match the destination HTTPS host")


def _one(cursor: Any) -> dict[str, Any]:
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("expected PostgreSQL row was not returned")
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip((item.name for item in cursor.description), row, strict=True))


def _many(cursor: Any) -> list[dict[str, Any]]:
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], Mapping):
        return [dict(row) for row in rows]
    names = [item.name for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in rows]


def _verification_attempt(record: dict[str, Any]) -> PublicationVerificationAttempt:
    return PublicationVerificationAttempt(
        **{
            **record,
            "outcome": cast(VerificationOutcome, record["outcome"]),
            "checks": tuple(record["checks"]),
            "failures": tuple(record["failures"]),
            "failure_disposition": cast(
                Literal["retryable", "permanent"] | None,
                record["failure_disposition"],
            ),
        }
    )
