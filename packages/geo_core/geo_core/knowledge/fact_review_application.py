"""Human review boundary for Knowledge Fact candidates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.knowledge.domain import (
    KnowledgeConflict,
    KnowledgeNotFound,
    KnowledgeValidationError,
)


class KnowledgeFactReviewApplicationMixin:
    def review_fact(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        fact_id: UUID,
        decision: str,
        notes: str,
    ) -> Mapping[str, object]:
        if decision not in {"approved", "rejected"}:
            raise KnowledgeValidationError("fact decision must be approved or rejected")
        with self._connection(principal, project_id, manage=True) as connection:  # type: ignore[attr-defined]
            candidate = _one(
                connection.execute(
                    """SELECT chunk.status AS chunk_status,
                              EXISTS (
                                SELECT 1 FROM knowledge_fact_evidence_lineages lineage
                                WHERE lineage.project_id = fact.project_id
                                  AND lineage.knowledge_fact_id = fact.id
                              ) AS has_evidence_lineage
                       FROM knowledge_fact_candidates AS fact
                       JOIN knowledge_chunks AS chunk
                         ON chunk.id = fact.chunk_id AND chunk.project_id = fact.project_id
                       WHERE fact.id = %s AND fact.project_id = %s
                         AND fact.lifecycle_status = 'active'
                       FOR UPDATE OF fact, chunk""",
                    (fact_id, project_id),
                )
            )
            if candidate is None:
                raise KnowledgeNotFound("knowledge fact candidate does not exist")
            if candidate["has_evidence_lineage"]:
                raise KnowledgeConflict("promoted knowledge facts cannot be reviewed again")
            if decision == "approved" and candidate["chunk_status"] != "active":
                raise KnowledgeConflict("knowledge facts from a disabled chunk cannot be approved")
            row = _one(
                connection.execute(
                    """UPDATE knowledge_fact_candidates
                       SET status = %s, reviewed_by = %s, review_notes = %s,
                           reviewed_at = clock_timestamp(), updated_at = clock_timestamp()
                       WHERE id = %s AND project_id = %s AND lifecycle_status = 'active'
                       RETURNING id, project_id, statement, status, reviewed_by,
                                 review_notes, reviewed_at""",
                    (decision, principal.identity_id, notes.strip() or None, fact_id, project_id),
                )
            )
            if row is None:
                raise KnowledgeNotFound("knowledge fact candidate does not exist")
            return row


def _one(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    return dict(value) if value is not None else None
