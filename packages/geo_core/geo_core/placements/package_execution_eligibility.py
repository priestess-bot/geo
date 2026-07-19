"""Execution-time currency checks for frozen Package Evidence lineage."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from geo_core.placements.execution_eligibility import approved_fact_evidence_is_current


def package_approved_fact_evidence_is_current(
    db: Any,
    *,
    project_id: UUID,
    package_version_id: UUID,
) -> bool:
    """Lock and validate approved-Fact Evidence referenced by Package claims."""

    evidence_ids = tuple(
        _first(row)
        for row in db.execute(
            """SELECT DISTINCT relation.evidence_item_id
               FROM placement_claims AS claim
               JOIN placement_claim_evidence AS relation
                 ON relation.claim_id = claim.id
                AND relation.project_id = claim.project_id
               WHERE claim.project_id = %s AND claim.package_version_id = %s
               ORDER BY relation.evidence_item_id""",
            (project_id, package_version_id),
        ).fetchall()
    )
    return approved_fact_evidence_is_current(
        db,
        project_id=project_id,
        evidence_ids=evidence_ids,
    )


def publication_request_approved_fact_evidence_is_current(
    db: Any,
    *,
    project_id: UUID,
    publication_request_id: UUID,
) -> bool:
    """Resolve a publication snapshot and validate its approved-Fact Evidence."""

    row = db.execute(
        """SELECT package_version_id
           FROM publication_requests
           WHERE project_id = %s AND id = %s""",
        (project_id, publication_request_id),
    ).fetchone()
    if row is None:
        return False
    return package_approved_fact_evidence_is_current(
        db,
        project_id=project_id,
        package_version_id=_first(row),
    )


def _first(row: Any) -> Any:
    if isinstance(row, Mapping):
        return next(iter(row.values()))
    return row[0]
