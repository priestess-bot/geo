"""Review, export and publication persistence mixin."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Mapping
from uuid import UUID, uuid4

from geo_core.placements.domain import (
    Claim,
    ExportReceipt,
    JobReference,
    PackageVersion,
    PlacementConflict,
    PlacementNotFound,
    Review,
    ReviewSubmission,
    canonical_hash,
)
from geo_core.placements.postgres_publication_records import PostgresPublicationRecordMixin


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


class PostgresReviewPublicationMixin(PostgresPublicationRecordMixin):
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
        campaign_id = version.campaign_id
        opportunity_id = version.opportunity_id
        destination_id = version.destination_id
        if campaign_id is None or opportunity_id is None or destination_id is None:
            raise RuntimeError("package version is missing immutable Campaign lineage")
        claims = self.list_claims(project_id=project_id, version_id=version_id)
        receipt_id = uuid4()
        manifest = {
            "schema": "geo-placement-export-v2",
            "project_id": str(project_id),
            "campaign_id": str(campaign_id),
            "opportunity_id": str(opportunity_id),
            "destination_id": str(destination_id),
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
                 (id, project_id, campaign_id, opportunity_id, destination_id,
                  package_version_id, export_format, manifest, manifest_hash,
                  requested_by, storage_key, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'json', %s::jsonb,
                       %s, %s, %s, %s)""",
            (
                receipt_id,
                project_id,
                campaign_id,
                opportunity_id,
                destination_id,
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
            campaign_id=campaign_id,
            kind="artifact.finalize",
            input_value={"resource_kind": "package_export", "resource_id": str(receipt_id)},
            idempotency_key=f"artifact:package-export:{receipt_id}",
        )
        self._db.execute(
            """INSERT INTO artifact_finalize_outbox
                 (project_id, campaign_id, opportunity_id, destination_id, job_id,
                  resource_kind, resource_id, pending_uri, storage_key, content_hash)
               VALUES (%s, %s, %s, %s, %s, 'package_export', %s, %s, %s, %s)""",
            (
                project_id,
                campaign_id,
                opportunity_id,
                destination_id,
                artifact_job.id,
                receipt_id,
                f"postgres://placement_export_receipts/{receipt_id}/manifest",
                storage_key,
                manifest_hash,
            ),
        )
        return ExportReceipt(
            id=receipt_id,
            project_id=project_id,
            package_version_id=version.id,
            content_hash=manifest_hash,
            exported_at=exported_at,
            export_format="json",
            requested_by=requested_by,
            artifact_status="pending",
            storage_key=storage_key,
            artifact_uri=None,
            package_version=version,
            claims=claims,
            campaign_id=campaign_id,
            opportunity_id=opportunity_id,
            destination_id=destination_id,
        )

    def list_exports(self, *, project_id: UUID, version_id: UUID) -> tuple[ExportReceipt, ...]:
        rows = _many(
            self._db.execute(
                """SELECT r.id, r.project_id, r.campaign_id, r.opportunity_id,
                          r.destination_id, r.package_version_id, r.manifest_hash,
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
                id=row["id"],
                project_id=row["project_id"],
                package_version_id=row["package_version_id"],
                content_hash=row["manifest_hash"],
                exported_at=row["created_at"],
                export_format=row["export_format"],
                requested_by=row["requested_by"],
                artifact_status=row["artifact_status"],
                storage_key=row["storage_key"],
                artifact_uri=row["artifact_uri"],
                package_version=version,
                claims=claims,
                campaign_id=row["campaign_id"],
                opportunity_id=row["opportunity_id"],
                destination_id=row["destination_id"],
            )
            for row in rows
        )
