"""Persistence for immutable package edits and their replacement claim inventory."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from geo_core.placements.domain import PackageVersion
from geo_core.placements.ports import GeneratedClaim


class PostgresPackageVersionMixin:
    _db: Any

    def get_package_version(self, *, project_id: UUID, version_id: UUID) -> PackageVersion | None:
        raise NotImplementedError

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
            raise RuntimeError("base package version does not exist")
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
                raise RuntimeError("edited claims reference evidence outside the frozen pack")
        changed = self._db.execute(
            """UPDATE placement_package_versions SET workflow_status = 'superseded'
               WHERE project_id = %s AND id = %s AND content_hash = %s
                 AND workflow_status <> 'superseded'""",
            (version.project_id, superseded_version_id, base.content_hash),
        ).rowcount
        if changed != 1:
            raise RuntimeError("base package version changed concurrently")
        self._db.execute(
            """INSERT INTO placement_package_versions
                 (id, project_id, package_id, prompt_bundle_id, version_number, base_version_id,
                  content_json, rendered_text, content_hash, edited_by, edit_reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)""",
            (
                version.id,
                version.project_id,
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
