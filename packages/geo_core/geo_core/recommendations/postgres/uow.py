"""Project-scoped PostgreSQL Unit of Work for Recommendation commands."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import Any
from uuid import UUID

import psycopg

from geo_core.project_scope import set_project_scope
from geo_core.recommendations.draft_operations import prepare_draft_action
from geo_core.recommendations.downstream_contracts import ConcreteRecommendationDraft
from geo_core.recommendations.models import (
    InputChangeReason,
    RecommendationStatus,
)
from geo_core.recommendations.ports import (
    DownstreamDraftPort,
    PreparedDraftAction,
    RecommendationCommandIdentity,
    RecommendationCommandOperation,
    RecommendationCommandRecord,
    RecommendationIdempotencyConflict,
    RecommendationOutboxPort,
    RecommendationPersistenceError,
    RecommendationRepository,
    RecommendationUnitOfWork,
    StoredRecommendationCommand,
)
from geo_core.recommendations.postgres.evidence import (
    PostgresRecommendationEvidenceResolver,
)
from geo_core.recommendations.postgres.repository import (
    ApprovalDraftBuffer,
    BlockDrafts,
    PsycopgRecommendationRepository,
)
from geo_core.recommendations.resolution import (
    RecommendationEvidenceResolverPort,
    resolve_current_graph,
)


def block_recommendation_drafts(
    connection: Any,
    project_id: UUID,
    recommendation_id: UUID,
    source_status: str,
    blocked_at: datetime,
    reason: str,
) -> tuple[UUID, ...]:
    """Synchronize only unstarted drafts; the workflow trigger is the backstop."""

    if source_status not in {"stale", "expired"}:
        raise RecommendationPersistenceError("Recommendation draft block status is invalid")
    rows = connection.execute(
        """UPDATE recommendation_drafts
           SET status = %s, blocked_at = %s, blocked_reason = %s
           WHERE project_id = %s AND recommendation_id = %s
             AND status IN ('draft', 'started')
           RETURNING id""",
        (
            f"blocked_source_{source_status}",
            blocked_at,
            reason,
            project_id,
            recommendation_id,
        ),
    ).fetchall()
    return tuple(sorted((row["id"] for row in rows), key=str))


class PsycopgRecommendationOutbox:
    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection = connection
        self._project_id = project_id

    def cancel_unpublished_for_recommendation(
        self, *, project_id: UUID, recommendation_id: UUID, reason: str
    ) -> tuple[UUID, ...]:
        if project_id != self._project_id:
            raise RecommendationPersistenceError("Recommendation outbox Project mismatch")
        try:
            rows = self._connection.execute(
                """UPDATE recommendation_outbox_messages
                   SET cancelled_at = clock_timestamp(), cancellation_reason = %s
                   WHERE project_id = %s AND recommendation_id = %s
                     AND delivered_at IS NULL AND cancelled_at IS NULL
                   RETURNING id""",
                (reason, project_id, recommendation_id),
            ).fetchall()
        except psycopg.Error as error:
            raise RecommendationPersistenceError(
                "PostgreSQL could not cancel Recommendation outbox messages"
            ) from error
        return tuple(sorted((row["id"] for row in rows), key=str))


class PsycopgRecommendationUnitOfWork:
    """Keep source resolution, approval, blocking, receipt and outbox atomic."""

    def __init__(
        self,
        *,
        connection_factory: Callable[[], Any],
        project_id: UUID,
        block_drafts: BlockDrafts,
    ) -> None:
        self._connection_factory = connection_factory
        self._project_id = project_id
        self._block_drafts = block_drafts
        self._connection: Any | None = None
        self._committed = False
        self._repository: PsycopgRecommendationRepository
        self.recommendations: RecommendationRepository
        self.evidence: RecommendationEvidenceResolverPort
        self.drafts: DownstreamDraftPort
        self.outbox: RecommendationOutboxPort

    def __enter__(self) -> "PsycopgRecommendationUnitOfWork":
        if self._connection is not None:
            raise RecommendationPersistenceError("Recommendation Unit of Work is active")
        connection = self._connection_factory()
        set_project_scope(connection, self._project_id)
        pending: list[ConcreteRecommendationDraft] = []
        self._connection = connection
        repository = PsycopgRecommendationRepository(
            connection,
            self._project_id,
            pending_drafts=pending,
            block_drafts=self._block_drafts,
        )
        self._repository = repository
        self.recommendations = repository
        self.evidence = PostgresRecommendationEvidenceResolver(connection, self._project_id)
        self.drafts = ApprovalDraftBuffer(pending)
        self.outbox = PsycopgRecommendationOutbox(connection, self._project_id)
        return self

    def prepare_draft_action(
        self,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        draft_id: UUID,
        expected_recommendation_version: int,
        occurred_at: datetime,
        actor_id: str,
        change_reason: InputChangeReason,
        command: RecommendationCommandIdentity,
    ) -> StoredRecommendationCommand:
        self._require_scope(project_id)
        existing = self.recommendations.get_command(
            project_id=project_id,
            idempotency_key_hash=command.idempotency_key_hash,
        )
        if existing is not None:
            return _replay(existing, command)
        workflow = self._repository.get_workflow_for_update(
            project_id=project_id,
            recommendation_id=recommendation_id,
        )
        if workflow is None:
            raise RecommendationPersistenceError("Recommendation does not exist")
        current = resolve_current_graph(self.evidence, workflow.recommendation.evidence)
        check = prepare_draft_action(
            workflow,
            draft_id=draft_id,
            expected_recommendation_version=expected_recommendation_version,
            current_inputs=current.input_versions,
            current_evidence_graph_hash=current.graph_hash,
            occurred_at=occurred_at,
            actor_id=actor_id,
            change_reason=change_reason,
        )
        cancelled: tuple[UUID, ...] = ()
        if check.workflow.recommendation.status in {
            RecommendationStatus.STALE,
            RecommendationStatus.EXPIRED,
        }:
            cancelled = self.outbox.cancel_unpublished_for_recommendation(
                project_id=project_id,
                recommendation_id=recommendation_id,
                reason=check.workflow.recommendation.status.value,
            )
        result = PreparedDraftAction(check, cancelled)
        return self.recommendations.store_workflow(
            project_id=project_id,
            workflow=check.workflow,
            expected_version=workflow.recommendation.version,
            command=command,
            result=result,
        )

    def commit(self) -> None:
        connection = self._require_connection()
        try:
            connection.commit()
        except psycopg.Error as error:
            raise RecommendationPersistenceError(
                "PostgreSQL could not commit the Recommendation transaction"
            ) from error
        self._committed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            if exc_type is not None or not self._committed:
                connection.rollback()
        finally:
            connection.close()

    def _require_connection(self) -> Any:
        if self._connection is None:
            raise RecommendationPersistenceError("Recommendation Unit of Work is not active")
        return self._connection

    def _require_scope(self, project_id: UUID) -> None:
        self._require_connection()
        if project_id != self._project_id:
            raise RecommendationPersistenceError("Recommendation Unit of Work Project mismatch")


class RecommendationUnitOfWorkFactory:
    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        block_drafts: BlockDrafts,
    ) -> None:
        self._connection_factory = connection_factory
        self._block_drafts = block_drafts

    def __call__(self, *, project_id: UUID) -> RecommendationUnitOfWork:
        return PsycopgRecommendationUnitOfWork(
            connection_factory=self._connection_factory,
            project_id=project_id,
            block_drafts=self._block_drafts,
        )


def _replay(
    existing: RecommendationCommandRecord,
    command: RecommendationCommandIdentity,
) -> StoredRecommendationCommand:
    if (
        existing.identity.operation != command.operation
        or existing.identity.request_hash != command.request_hash
        or existing.identity.operation is not RecommendationCommandOperation.PREPARE_DRAFT_ACTION
    ):
        raise RecommendationIdempotencyConflict(
            "Recommendation idempotency key was reused for a different request"
        )
    return StoredRecommendationCommand(existing, replayed=True)


__all__ = [
    "block_recommendation_drafts",
    "PsycopgRecommendationOutbox",
    "PsycopgRecommendationUnitOfWork",
    "RecommendationUnitOfWorkFactory",
]
