"""PostgreSQL source guard adapters for concrete Recommendation drafts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from geo_core.project_scope import set_project_scope
from geo_core.recommendations.downstream_contracts import (
    ConcreteDraftStatus,
    ConcreteRecommendationDraft,
)
from geo_core.recommendations.downstream_ports import ResolvedSourceRecommendation
from geo_core.recommendations.errors import RecommendationSourceStale
from geo_core.recommendations.generation_contracts import canonical_hash
from geo_core.recommendations.ports import (
    RecommendationPersistenceError,
    RecommendationSourceCheckRequired,
)
from geo_core.recommendations.postgres.downstream_codec import concrete_draft_payload
from geo_core.recommendations.postgres.evidence import (
    PostgresRecommendationEvidenceResolver,
)
from geo_core.recommendations.postgres.repository import BlockDrafts
from geo_core.recommendations.postgres.rows import (
    concrete_draft_from_row,
    workflow_from_row,
)
from geo_core.recommendations.resolution import resolve_current_graph


class PsycopgConcreteDraftStorage:
    """Guard-only storage. Approval creation remains inside the Recommendation UoW."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        project_id: UUID,
        block_drafts: BlockDrafts,
    ) -> None:
        self._connect = connection_factory
        self._project_id = project_id
        self._block_drafts = block_drafts

    def create_draft(self, draft: ConcreteRecommendationDraft) -> ConcreteRecommendationDraft:
        del draft
        raise RecommendationSourceCheckRequired(
            "concrete Recommendation drafts can only be created by approval"
        )

    def load_for_source_guard(
        self, *, draft_id: UUID
    ) -> ConcreteRecommendationDraft | None:
        connection = self._connect()
        try:
            set_project_scope(connection, self._project_id)
            scoped = connection.execute(
                """SELECT id, project_id, recommendation_id, recommendation_version,
                          approval_id, kind, idempotency_key,
                          frozen_input_fingerprint, frozen_evidence_graph_hash,
                          source_valid_until, status, draft_payload, draft_payload_hash,
                          created_at, blocked_at, blocked_reason
                   FROM recommendation_drafts WHERE project_id = %s AND id = %s""",
                (self._project_id, draft_id),
            ).fetchone()
            connection.rollback()
            return concrete_draft_from_row(scoped) if scoped is not None else None
        except psycopg.Error as error:
            connection.rollback()
            raise RecommendationPersistenceError(
                "PostgreSQL could not load the concrete Recommendation draft"
            ) from error
        finally:
            connection.close()

    def synchronize_blocked(
        self, draft: ConcreteRecommendationDraft
    ) -> ConcreteRecommendationDraft:
        if draft.status not in {
            ConcreteDraftStatus.BLOCKED_SOURCE_STALE,
            ConcreteDraftStatus.BLOCKED_SOURCE_EXPIRED,
        }:
            raise RecommendationSourceCheckRequired(
                "only a source-guard block can synchronize a concrete draft"
            )
        assert draft.blocked_at is not None
        assert draft.blocked_reason is not None
        source = draft.source
        if source.project_id != self._project_id:
            raise RecommendationSourceCheckRequired(
                "concrete Recommendation draft crosses Project scope"
            )
        connection = self._connect()
        try:
            set_project_scope(connection, source.project_id)
            self._block_drafts(
                connection,
                source.project_id,
                source.recommendation_id,
                draft.status.value.removeprefix("blocked_source_"),
                draft.blocked_at,
                draft.blocked_reason,
            )
            payload = concrete_draft_payload(draft)
            changed = connection.execute(
                """UPDATE recommendation_drafts
                   SET status = %s, blocked_at = %s, blocked_reason = %s,
                       draft_payload = %s, draft_payload_hash = %s
                   WHERE project_id = %s AND id = %s AND status = %s""",
                (
                    draft.status.value,
                    draft.blocked_at,
                    draft.blocked_reason,
                    Jsonb(payload),
                    canonical_hash(payload),
                    source.project_id,
                    draft.id,
                    draft.status.value,
                ),
            ).rowcount
            if changed != 1:
                raise RecommendationSourceCheckRequired(
                    "concrete Recommendation draft changed during source blocking"
                )
            connection.commit()
            return draft
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


class PsycopgSourceRecommendationResolver:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connect = connection_factory

    def resolve_source_recommendation(
        self, *, project_id: UUID, recommendation_id: UUID
    ) -> ResolvedSourceRecommendation:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT project_id, recommendation_id, version, status,
                          recommendation_type, proposed_draft_kind, evidence_graph_hash,
                          input_fingerprint, valid_until, created_by,
                          workflow_payload, workflow_payload_hash
                   FROM recommendation_workflow_versions
                   WHERE project_id = %s AND recommendation_id = %s
                   ORDER BY version DESC LIMIT 1""",
                (project_id, recommendation_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                return ResolvedSourceRecommendation(None, ())
            workflow = workflow_from_row(row)
            resolver = PostgresRecommendationEvidenceResolver(connection, project_id)
            try:
                current = resolve_current_graph(resolver, workflow.recommendation.evidence)
                inputs = current.input_versions
            except (RecommendationSourceStale, RecommendationPersistenceError):
                inputs = ()
            connection.rollback()
            return ResolvedSourceRecommendation(workflow, inputs)
        except psycopg.Error as error:
            connection.rollback()
            raise RecommendationPersistenceError(
                "PostgreSQL could not resolve the source Recommendation"
            ) from error
        finally:
            connection.close()


__all__ = [
    "PsycopgConcreteDraftStorage",
    "PsycopgSourceRecommendationResolver",
]
