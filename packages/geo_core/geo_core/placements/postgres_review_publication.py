"""Review, export and publication persistence mixin."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Mapping
from uuid import UUID, uuid4
from urllib.parse import urlparse

from geo_core.placements.domain import (
    Claim,
    ExportReceipt,
    JobReference,
    Measurement,
    PackageVersion,
    PlacementConflict,
    PlacementNotFound,
    PlacementRuleViolation,
    PublicationRequest,
    Review,
    ReviewSubmission,
    Submission,
    canonical_hash,
)


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


class PostgresReviewPublicationMixin:
    _db: Any

    def _enqueue_job(
        self,
        *,
        project_id: UUID,
        kind: str,
        input_value: Mapping[str, object],
        idempotency_key: str,
    ) -> JobReference:
        raise NotImplementedError

    def get_package_version(self, *, project_id: UUID, version_id: UUID) -> PackageVersion | None:
        raise NotImplementedError

    def list_claims(self, *, project_id: UUID, version_id: UUID) -> tuple[Claim, ...]:
        raise NotImplementedError

    def submit_for_review(
        self, *, project_id: UUID, version_id: UUID, submitted_by: UUID
    ) -> ReviewSubmission:
        record = _one(
            self._db.execute(
                """INSERT INTO placement_review_submissions
                     (project_id, package_version_id, submitted_by)
                   VALUES (%s, %s, %s)
                   RETURNING id, project_id, package_version_id, submitted_by, submitted_at""",
                (project_id, version_id, submitted_by),
            )
        )
        changed = self._db.execute(
            """UPDATE placement_package_versions SET workflow_status = 'pending_human_review'
               WHERE project_id = %s AND id = %s
                 AND workflow_status IN ('generated', 'needs_revision')""",
            (project_id, version_id),
        ).rowcount
        if changed != 1:
            raise PlacementConflict("package version cannot be submitted from its current state")
        return ReviewSubmission(**record)

    def get_review_submission(
        self, *, project_id: UUID, version_id: UUID
    ) -> ReviewSubmission | None:
        rows = _many(
            self._db.execute(
                """SELECT id, project_id, package_version_id, submitted_by, submitted_at
                   FROM placement_review_submissions
                   WHERE project_id = %s AND package_version_id = %s""",
                (project_id, version_id),
            )
        )
        return ReviewSubmission(**rows[0]) if rows else None

    def save_review(self, *, review: Review) -> Review:
        reviewed_at = self._db.execute(
            """INSERT INTO placement_reviews
                 (id, project_id, package_version_id, submitted_for_review_by, reviewer_id,
                  decision, claim_inventory_complete, extracted_claim_support_confirmed,
                  score, notes)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING reviewed_at""",
            (
                review.id,
                review.project_id,
                review.package_version_id,
                review.submitted_for_review_by,
                review.reviewer_id,
                review.decision,
                review.claim_inventory_complete,
                review.extracted_claim_support_confirmed,
                review.score,
                review.notes,
            ),
        ).fetchone()[0]
        changed = self._db.execute(
            """UPDATE placement_package_versions SET workflow_status = %s
               WHERE id = %s AND project_id = %s AND workflow_status = 'pending_human_review'""",
            (review.decision, review.package_version_id, review.project_id),
        ).rowcount
        if changed != 1:
            raise PlacementConflict("package review lost its pending-review state")
        return Review(
            id=review.id,
            project_id=review.project_id,
            package_version_id=review.package_version_id,
            submitted_for_review_by=review.submitted_for_review_by,
            reviewer_id=review.reviewer_id,
            decision=review.decision,
            claim_inventory_complete=review.claim_inventory_complete,
            extracted_claim_support_confirmed=review.extracted_claim_support_confirmed,
            score=review.score,
            notes=review.notes,
            reviewed_at=reviewed_at,
        )

    def list_reviews(self, *, project_id: UUID, version_id: UUID) -> tuple[Review, ...]:
        return tuple(
            Review(**row)
            for row in _many(
                self._db.execute(
                    """SELECT id, project_id, package_version_id,
                              submitted_for_review_by, reviewer_id, decision,
                              claim_inventory_complete, extracted_claim_support_confirmed,
                              score, notes, reviewed_at
                       FROM placement_reviews
                       WHERE project_id = %s AND package_version_id = %s
                       ORDER BY reviewed_at""",
                    (project_id, version_id),
                )
            )
        )

    def export_package(
        self,
        *,
        project_id: UUID,
        version_id: UUID,
        exported_at: datetime,
        requested_by: UUID,
    ) -> ExportReceipt:
        version = self.get_package_version(project_id=project_id, version_id=version_id)
        if version is None:
            raise PlacementNotFound("package version does not exist")
        claims = self.list_claims(project_id=project_id, version_id=version_id)
        receipt_id = uuid4()
        manifest = {
            "schema": "geo-placement-export-v1",
            "project_id": str(project_id),
            "package_version": {
                "id": str(version.id),
                "package_id": str(version.package_id),
                "prompt_bundle_id": str(version.prompt_bundle_id),
                "version_number": version.version_number,
                "base_version_id": str(version.base_version_id)
                if version.base_version_id
                else None,
                "workflow_status": version.workflow_status.value,
                "content_json": dict(version.content_json),
                "rendered_text": version.rendered_text,
                "content_hash": version.content_hash,
            },
            "claims": [
                {
                    "id": str(claim.id),
                    "text": claim.claim_text,
                    "kind": claim.claim_kind,
                    "support_status": claim.support_status,
                    "evidence_item_ids": [str(value) for value in claim.evidence_item_ids],
                }
                for claim in claims
            ],
            "requested_by": str(requested_by),
            "exported_at": exported_at.isoformat(),
        }
        manifest_hash = canonical_hash(manifest)
        storage_key = (
            f"content-artifacts/{project_id}/{version.package_id}/{version.version_number}/"
            f"export-{receipt_id}-{manifest_hash}.json"
        )
        self._db.execute(
            """INSERT INTO placement_export_receipts
                 (id, project_id, package_version_id, export_format, manifest,
                  manifest_hash, requested_by, storage_key, created_at)
               VALUES (%s, %s, %s, 'json', %s::jsonb, %s, %s, %s, %s)""",
            (
                receipt_id,
                project_id,
                version_id,
                json.dumps(manifest),
                manifest_hash,
                requested_by,
                storage_key,
                exported_at,
            ),
        )
        artifact_job = self._enqueue_job(
            project_id=project_id,
            kind="artifact.finalize",
            input_value={"resource_kind": "package_export", "resource_id": str(receipt_id)},
            idempotency_key=f"artifact:package-export:{receipt_id}",
        )
        self._db.execute(
            """INSERT INTO artifact_finalize_outbox
                 (project_id, job_id, resource_kind, resource_id, pending_uri,
                  storage_key, content_hash)
               VALUES (%s, %s, 'package_export', %s, %s, %s, %s)""",
            (
                project_id,
                artifact_job.id,
                receipt_id,
                f"postgres://placement_export_receipts/{receipt_id}/manifest",
                storage_key,
                manifest_hash,
            ),
        )
        return ExportReceipt(
            receipt_id,
            project_id,
            version.id,
            manifest_hash,
            exported_at,
            "json",
            requested_by,
            "pending",
            storage_key,
            None,
            version,
            claims,
        )

    def list_exports(self, *, project_id: UUID, version_id: UUID) -> tuple[ExportReceipt, ...]:
        rows = _many(
            self._db.execute(
                """SELECT r.id, r.project_id, r.package_version_id, r.manifest_hash,
                          r.created_at, r.export_format, r.requested_by, r.storage_key,
                          a.status AS artifact_status, a.final_uri AS artifact_uri
                   FROM placement_export_receipts r JOIN artifact_finalize_outbox a
                     ON a.resource_id = r.id AND a.project_id = r.project_id
                    AND a.resource_kind = 'package_export'
                   WHERE r.project_id = %s AND r.package_version_id = %s
                   ORDER BY r.created_at DESC""",
                (project_id, version_id),
            )
        )
        version = self.get_package_version(project_id=project_id, version_id=version_id)
        if version is None:
            return ()
        claims = self.list_claims(project_id=project_id, version_id=version_id)
        return tuple(
            ExportReceipt(
                row["id"],
                row["project_id"],
                row["package_version_id"],
                row["manifest_hash"],
                row["created_at"],
                row["export_format"],
                row["requested_by"],
                row["artifact_status"],
                row["storage_key"],
                row["artifact_uri"],
                version,
                claims,
            )
            for row in rows
        )

    def create_publication_request(self, **values: Any) -> PublicationRequest:
        record = _one(
            self._db.execute(
                """INSERT INTO publication_requests
                     (project_id, package_version_id, destination_id, requested_by,
                      publication_attempt, idempotency_key, restricted_policy_acknowledged,
                      policy_basis)
                   VALUES (%(project_id)s, %(version_id)s, %(destination_id)s,
                           %(requested_by)s, %(publication_attempt)s, %(idempotency_key)s,
                           %(restricted_policy_acknowledged)s, %(policy_basis)s)
                   ON CONFLICT (project_id, idempotency_key) DO UPDATE
                     SET idempotency_key = EXCLUDED.idempotency_key
                     WHERE publication_requests.package_version_id = EXCLUDED.package_version_id
                       AND publication_requests.destination_id = EXCLUDED.destination_id
                       AND publication_requests.publication_attempt = EXCLUDED.publication_attempt
                   RETURNING id, project_id, package_version_id, destination_id,
                             publication_attempt, idempotency_key,
                             restricted_policy_acknowledged, policy_basis, status""",
                values,
            )
        )
        destination = _one(
            self._db.execute(
                """SELECT publication_channel, destination_key FROM publication_destinations
                   WHERE project_id = %s AND id = %s""",
                (values["project_id"], values["destination_id"]),
            )
        )
        return PublicationRequest(**record, **destination)

    def create_submission(self, **values: Any) -> Submission:
        destination = _one(
            self._db.execute(
                """SELECT d.allowed_hosts FROM publication_requests r
                   JOIN publication_destinations d
                     ON d.id = r.destination_id AND d.project_id = r.project_id
                   WHERE r.id = %s AND r.project_id = %s""",
                (values["publication_request_id"], values["project_id"]),
            )
        )
        if values["submitted_url"]:
            parsed = urlparse(values["submitted_url"])
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
                or parsed.hostname.casefold() not in destination["allowed_hosts"]
            ):
                raise PlacementRuleViolation("submitted URL must match the destination HTTPS host")
        status = "submitted" if values["submitted_url"] else "awaiting_url"
        created = _many(
            self._db.execute(
                """INSERT INTO publication_submissions
                     (project_id, publication_request_id, submitted_url,
                      provider_submission_id, status, submitted_at,
                      idempotency_key, payload_hash, submitted_by)
                   VALUES (%s, %s, %s, %s, %s,
                     CASE WHEN %s = 'submitted' THEN clock_timestamp() ELSE NULL END,
                     %s, %s, %s)
                   ON CONFLICT (project_id, idempotency_key) DO NOTHING
                   RETURNING id, project_id, publication_request_id, status,
                             submitted_url, provider_submission_id, verification_result,
                             url_backfilled_by, url_backfilled_at,
                             idempotency_key, submitted_by""",
                (
                    values["project_id"],
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
        existing = _one(
            self._db.execute(
                """SELECT id, project_id, publication_request_id, status,
                          submitted_url, provider_submission_id, verification_result,
                          url_backfilled_by, url_backfilled_at, idempotency_key,
                          submitted_by, payload_hash
                   FROM publication_submissions
                   WHERE project_id = %s AND idempotency_key = %s""",
                (values["project_id"], values["idempotency_key"]),
            )
        )
        if existing.pop("payload_hash") != values["payload_hash"]:
            raise PlacementConflict(
                "submission idempotency key was already used with a different payload"
            )
        return Submission(**existing)

    def backfill_submission_url(
        self, *, project_id: UUID, submission_id: UUID, submitted_url: str, actor_id: UUID
    ) -> Submission:
        record = _one(
            self._db.execute(
                """SELECT s.id, s.project_id, s.publication_request_id, s.status,
                          s.submitted_url, s.provider_submission_id, s.verification_result,
                          s.url_backfilled_by, s.url_backfilled_at,
                          s.idempotency_key, s.submitted_by, d.allowed_hosts
                   FROM publication_submissions s JOIN publication_requests r
                     ON r.id = s.publication_request_id AND r.project_id = s.project_id
                   JOIN publication_destinations d
                     ON d.id = r.destination_id AND d.project_id = r.project_id
                   WHERE s.id = %s AND s.project_id = %s FOR UPDATE OF s""",
                (submission_id, project_id),
            )
        )
        parsed = urlparse(submitted_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.hostname.casefold() not in record["allowed_hosts"]
        ):
            raise PlacementRuleViolation("submitted URL must match the destination HTTPS host")
        if record["submitted_url"] == submitted_url:
            record.pop("allowed_hosts")
            return Submission(**record)
        if record["status"] != "awaiting_url" or record["submitted_url"] is not None:
            raise PlacementRuleViolation("submission URL cannot be overwritten")
        updated = _one(
            self._db.execute(
                """UPDATE publication_submissions
                   SET submitted_url = %s, status = 'submitted', submitted_at = clock_timestamp(),
                       url_backfilled_by = %s, url_backfilled_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s
                   RETURNING id, project_id, publication_request_id, status,
                     submitted_url, provider_submission_id, verification_result,
                     url_backfilled_by, url_backfilled_at, idempotency_key, submitted_by""",
                (submitted_url, actor_id, submission_id, project_id),
            )
        )
        return Submission(**updated)

    def transition_submission(
        self,
        *,
        project_id: UUID,
        submission_id: UUID,
        status: str,
        reason: str,
        actor_id: UUID,
    ) -> Submission:
        record = _one(
            self._db.execute(
                """UPDATE publication_submissions SET status = %s, state_reason = %s,
                     state_changed_by = %s, state_changed_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s
                     AND status IN ('awaiting_url', 'submitted', 'failed', 'blocked')
                   RETURNING id, project_id, publication_request_id, status,
                     submitted_url, provider_submission_id, verification_result,
                     url_backfilled_by, url_backfilled_at, idempotency_key, submitted_by""",
                (status, reason, actor_id, submission_id, project_id),
            )
        )
        return Submission(**record)

    def transition_publication(
        self,
        *,
        project_id: UUID,
        publication_request_id: UUID,
        status: str,
        reason: str,
        actor_id: UUID,
    ) -> PublicationRequest:
        record = _one(
            self._db.execute(
                """UPDATE publication_requests SET status = %s, state_reason = %s,
                     state_changed_by = %s, state_changed_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s
                     AND status IN ('requested', 'scheduled', 'retrying', 'failed', 'blocked')
                   RETURNING id, project_id, package_version_id, destination_id,
                     publication_attempt, idempotency_key, restricted_policy_acknowledged,
                     policy_basis, status""",
                (status, reason, actor_id, publication_request_id, project_id),
            )
        )
        destination = _one(
            self._db.execute(
                """SELECT publication_channel, destination_key FROM publication_destinations
                   WHERE id = %s AND project_id = %s""",
                (record["destination_id"], project_id),
            )
        )
        return PublicationRequest(**record, **destination)

    def list_publication_requests(
        self, *, project_id: UUID, version_id: UUID
    ) -> tuple[PublicationRequest, ...]:
        records = _many(
            self._db.execute(
                """SELECT r.id, r.project_id, r.package_version_id, r.destination_id,
                          d.publication_channel, d.destination_key, r.publication_attempt,
                          r.idempotency_key, r.restricted_policy_acknowledged,
                          r.policy_basis, r.status
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
        records = _many(
            self._db.execute(
                """SELECT id, project_id, publication_request_id, status,
                          submitted_url, provider_submission_id, verification_result,
                          url_backfilled_by, url_backfilled_at, idempotency_key, submitted_by
                   FROM publication_submissions
                   WHERE project_id = %s AND publication_request_id = %s
                   ORDER BY created_at""",
                (project_id, publication_request_id),
            )
        )
        return tuple(Submission(**record) for record in records)

    def get_submission(self, *, project_id: UUID, submission_id: UUID) -> Submission | None:
        records = _many(
            self._db.execute(
                """SELECT id, project_id, publication_request_id, status,
                          submitted_url, provider_submission_id, verification_result,
                          url_backfilled_by, url_backfilled_at, idempotency_key, submitted_by
                   FROM publication_submissions WHERE project_id = %s AND id = %s""",
                (project_id, submission_id),
            )
        )
        return Submission(**records[0]) if records else None

    def enqueue_verification(
        self, *, project_id: UUID, submission_id: UUID, idempotency_key: str
    ) -> JobReference:
        job = self._enqueue_job(
            project_id=project_id,
            kind="publication.verify",
            input_value={"submission_id": str(submission_id)},
            idempotency_key=idempotency_key,
        )
        self._db.execute(
            """INSERT INTO verification_job_specs (job_id, project_id, submission_id)
               VALUES (%s, %s, %s) ON CONFLICT (job_id) DO NOTHING""",
            (job.id, project_id, submission_id),
        )
        return job

    def record_measurement(self, **values: Any) -> Measurement:
        record = _one(
            self._db.execute(
                """INSERT INTO placement_measurements
                     (project_id, submission_id, monitoring_query_id, measured_at,
                      citation_present, recommendation_position, result_snapshot_uri, metrics)
                   VALUES (%(project_id)s, %(submission_id)s, %(monitoring_query_id)s,
                           %(measured_at)s, %(citation_present)s, %(recommendation_position)s,
                           %(result_snapshot_uri)s, %(metrics)s::jsonb)
                   RETURNING id, project_id, submission_id, monitoring_query_id, measured_at,
                             citation_present, recommendation_position, result_snapshot_uri, metrics""",
                {**values, "metrics": json.dumps(values["metrics"])},
            )
        )
        return Measurement(**record)

    def list_measurements(
        self, *, project_id: UUID, submission_id: UUID
    ) -> tuple[Measurement, ...]:
        rows = _many(
            self._db.execute(
                """SELECT id, project_id, submission_id, monitoring_query_id, measured_at,
                          citation_present, recommendation_position, result_snapshot_uri, metrics
                   FROM placement_measurements WHERE project_id = %s AND submission_id = %s
                   ORDER BY measured_at DESC""",
                (project_id, submission_id),
            )
        )
        return tuple(Measurement(**row) for row in rows)
