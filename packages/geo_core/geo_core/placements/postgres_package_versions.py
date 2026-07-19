"""Persistence for immutable package edits and their replacement claim inventory."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID, uuid4

from geo_core.placements.domain import (
    Claim,
    ConcurrencyConflict,
    PackageVersion,
    PlacementNotFound,
    PlacementRuleViolation,
    WorkflowStatus,
)
from geo_core.placements.ports import GeneratedClaim


class PostgresPackageVersionMixin:
    _db: Any

    def list_package_versions(
        self, *, project_id: UUID, opportunity_id: UUID
    ) -> tuple[PackageVersion, ...]:
        records = _rows(
            self._db.execute(
                """SELECT v.id, v.project_id, v.campaign_id, v.opportunity_id,
                          v.destination_id, v.package_id, v.prompt_bundle_id,
                          v.version_number, v.base_version_id, v.workflow_status,
                          v.content_json, v.rendered_text, v.content_hash, v.edited_by,
                          v.edit_reason, v.generated_by_job_id
                   FROM placement_package_versions v JOIN placement_packages p
                     ON p.id = v.package_id AND p.project_id = v.project_id
                   WHERE v.project_id = %s AND p.opportunity_id = %s
                   ORDER BY v.version_number""",
                (project_id, opportunity_id),
            )
        )
        return tuple(_package(item) for item in records)

    def get_package_version(
        self, *, project_id: UUID, version_id: UUID
    ) -> PackageVersion | None:
        records = _rows(
            self._db.execute(
                """SELECT id, project_id, campaign_id, opportunity_id, destination_id,
                          package_id, prompt_bundle_id, version_number, base_version_id,
                          workflow_status, content_json, rendered_text, content_hash,
                          edited_by, edit_reason, generated_by_job_id
                   FROM placement_package_versions WHERE project_id = %s AND id = %s""",
                (project_id, version_id),
            )
        )
        return _package(records[0]) if records else None

    def list_claims(self, *, project_id: UUID, version_id: UUID) -> tuple[Claim, ...]:
        records = _rows(
            self._db.execute(
                """SELECT c.id, c.project_id, c.package_version_id, c.claim_text,
                          c.claim_kind, c.support_status,
                          COALESCE(array_agg(ce.evidence_item_id)
                            FILTER (WHERE ce.evidence_item_id IS NOT NULL), '{}')
                            AS evidence_item_ids
                   FROM placement_claims c LEFT JOIN placement_claim_evidence ce
                     ON ce.claim_id = c.id AND ce.project_id = c.project_id
                   WHERE c.project_id = %s AND c.package_version_id = %s
                   GROUP BY c.id ORDER BY c.created_at""",
                (project_id, version_id),
            )
        )
        return tuple(
            Claim(**{**item, "evidence_item_ids": tuple(item["evidence_item_ids"])})
            for item in records
        )

    def save_edited_version(
        self,
        *,
        version: PackageVersion,
        superseded_version_id: UUID,
        claims: tuple[GeneratedClaim, ...],
    ) -> PackageVersion:
        base = self.get_package_version(
            project_id=version.project_id, version_id=superseded_version_id
        )
        if base is None:
            raise PlacementNotFound("base package version does not exist")
        evidence_ids = {evidence_id for claim in claims for evidence_id in claim.evidence_item_ids}
        if evidence_ids:
            frozen_ids = {
                row[0]
                for row in self._db.execute(
                    """SELECT pi.evidence_item_id
                       FROM prompt_bundles pb JOIN evidence_pack_items pi
                         ON pi.pack_attempt_id = pb.evidence_pack_attempt_id
                        AND pi.project_id = pb.project_id
                       WHERE pb.id = %s AND pb.project_id = %s
                         AND pi.evidence_item_id = ANY(%s::uuid[])""",
                    (version.prompt_bundle_id, version.project_id, list(evidence_ids)),
                ).fetchall()
            }
            if frozen_ids != evidence_ids:
                raise PlacementRuleViolation(
                    "edited claims reference evidence outside the frozen pack"
                )
        changed = self._db.execute(
            """UPDATE placement_package_versions SET workflow_status = 'superseded'
               WHERE project_id = %s AND id = %s AND content_hash = %s
                 AND workflow_status <> 'superseded'""",
            (version.project_id, superseded_version_id, base.content_hash),
        ).rowcount
        if changed != 1:
            raise ConcurrencyConflict("base package version changed concurrently")
        self._db.execute(
            """INSERT INTO placement_package_versions
                 (id, project_id, campaign_id, opportunity_id, destination_id,
                  package_id, prompt_bundle_id, version_number, base_version_id,
                  content_json, rendered_text, content_hash, edited_by, edit_reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                       %s, %s, %s, %s)""",
            (
                version.id,
                version.project_id,
                version.campaign_id,
                version.opportunity_id,
                version.destination_id,
                version.package_id,
                version.prompt_bundle_id,
                version.version_number,
                version.base_version_id,
                json.dumps(dict(version.content_json)),
                version.rendered_text,
                version.content_hash,
                version.edited_by,
                version.edit_reason,
            ),
        )
        for claim in claims:
            self._insert_claim(version=version, claim=claim)
        return version

    def _insert_claim(self, *, version: PackageVersion, claim: GeneratedClaim) -> None:
        claim_id = uuid4()
        self._db.execute(
            """INSERT INTO placement_claims
                 (id, project_id, package_version_id, claim_text, claim_kind, support_status)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                claim_id,
                version.project_id,
                version.id,
                claim.text.strip(),
                claim.kind,
                claim.support_status,
            ),
        )
        for evidence_id in claim.evidence_item_ids:
            classification = "conflicts" if claim.support_status == "conflict" else "supports"
            self._db.execute(
                """INSERT INTO placement_claim_evidence
                     (claim_id, project_id, evidence_item_id, support_classification)
                   VALUES (%s, %s, %s, %s)""",
                (claim_id, version.project_id, evidence_id, classification),
            )


def _rows(cursor: Any) -> list[dict[str, Any]]:
    records = cursor.fetchall()
    if not records:
        return []
    if isinstance(records[0], Mapping):
        return [dict(record) for record in records]
    names = [item.name for item in cursor.description]
    return [dict(zip(names, record, strict=True)) for record in records]


def _package(value: Mapping[str, Any]) -> PackageVersion:
    return PackageVersion(
        id=value["id"],
        project_id=value["project_id"],
        package_id=value["package_id"],
        prompt_bundle_id=value["prompt_bundle_id"],
        version_number=value["version_number"],
        base_version_id=value.get("base_version_id"),
        workflow_status=WorkflowStatus(value["workflow_status"]),
        content_json=value["content_json"],
        rendered_text=value["rendered_text"],
        content_hash=value["content_hash"],
        edited_by=value.get("edited_by"),
        edit_reason=value.get("edit_reason"),
        generated_by_job_id=value.get("generated_by_job_id"),
        campaign_id=value.get("campaign_id"),
        opportunity_id=value.get("opportunity_id"),
        destination_id=value.get("destination_id"),
    )
