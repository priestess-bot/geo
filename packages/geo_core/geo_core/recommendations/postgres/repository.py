"""Append-only PostgreSQL persistence for Recommendation workflows."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from geo_core.recommendations.downstream_contracts import ConcreteRecommendationDraft
from geo_core.recommendations.downstream_service import concrete_draft_from_approval
from geo_core.recommendations.generation_contracts import canonical_hash
from geo_core.recommendations.models import (
    DownstreamDraftStatus,
    RecommendationStatus,
    RecommendationWorkflow,
)
from geo_core.recommendations.ports import (
    CreatedDownstreamDraft,
    RecommendationCommandIdentity,
    RecommendationCommandRecord,
    RecommendationIdempotencyConflict,
    RecommendationPersistenceError,
    RecommendationReview,
    RecommendationSourceCheckRequired,
    RecommendationVersionConflict,
    StoredRecommendationCommand,
)
from geo_core.recommendations.postgres.codec import (
    command_result_payload,
    workflow_payload,
)
from geo_core.recommendations.postgres.downstream_codec import concrete_draft_payload
from geo_core.recommendations.postgres.rows import (
    command_record_from_row,
    review_from_row,
    workflow_from_row,
)


BlockDrafts = Callable[[Any, UUID, UUID, str, datetime, str], tuple[UUID, ...]]


class PsycopgRecommendationRepository:
    """Project-scoped CAS repository; it has no operation that starts a draft."""

    def __init__(
        self,
        connection: Any,
        project_id: UUID,
        *,
        pending_drafts: list[ConcreteRecommendationDraft],
        block_drafts: BlockDrafts,
    ) -> None:
        self._connection = connection
        self._project_id = project_id
        self._pending_drafts = pending_drafts
        self._block_drafts = block_drafts

    def get_command(
        self, *, project_id: UUID, idempotency_key_hash: str
    ) -> RecommendationCommandRecord | None:
        self._require_scope(project_id)
        row = self._connection.execute(
            """SELECT project_id, idempotency_key_hash, operation, request_hash,
                      result_kind, result_payload, result_payload_hash
               FROM recommendation_command_receipts
               WHERE project_id = %s AND idempotency_key_hash = %s""",
            (project_id, idempotency_key_hash),
        ).fetchone()
        return command_record_from_row(row) if row is not None else None

    def get_workflow(
        self, *, project_id: UUID, recommendation_id: UUID
    ) -> RecommendationWorkflow | None:
        return self._workflow(project_id, recommendation_id, for_update=False)

    def get_workflow_for_update(
        self, *, project_id: UUID, recommendation_id: UUID
    ) -> RecommendationWorkflow | None:
        self._lock_lifecycle(project_id, recommendation_id)
        return self._workflow(project_id, recommendation_id, for_update=True)

    def get_review(
        self, *, project_id: UUID, recommendation_id: UUID
    ) -> RecommendationReview | None:
        self._require_scope(project_id)
        row = self._connection.execute(
            """SELECT id, project_id, recommendation_id, recommendation_version,
                      evidence_graph_hash, reviewed_by, notes, reviewed_at
               FROM recommendation_reviews
               WHERE project_id = %s AND recommendation_id = %s
               ORDER BY recommendation_version DESC, reviewed_at DESC LIMIT 1""",
            (project_id, recommendation_id),
        ).fetchone()
        return review_from_row(row) if row is not None else None

    def store_workflow(
        self,
        *,
        project_id: UUID,
        workflow: RecommendationWorkflow,
        expected_version: int,
        command: RecommendationCommandIdentity,
        result: object,
        review: RecommendationReview | None = None,
    ) -> StoredRecommendationCommand:
        self._require_scope(project_id)
        item = workflow.recommendation
        if item.project_id != project_id or command.project_id != project_id:
            raise RecommendationPersistenceError("Recommendation write scope mismatch")
        self._lock_lifecycle(project_id, item.id)
        existing_command = self.get_command(
            project_id=project_id,
            idempotency_key_hash=command.idempotency_key_hash,
        )
        if existing_command is not None:
            return _replay(existing_command, command)
        current = self.get_workflow_for_update(
            project_id=project_id,
            recommendation_id=item.id,
        )
        self._assert_transition(
            current=current,
            candidate=workflow,
            expected_version=expected_version,
            has_review=review is not None,
        )
        try:
            if current is None or item.version > current.recommendation.version:
                self._insert_workflow(workflow)
                self._insert_evidence_bindings(workflow)
                if item.status is RecommendationStatus.APPROVED and item.approval is not None:
                    self._insert_approval(workflow)
            if review is not None:
                self._insert_review(review, workflow)
            self._flush_pending_drafts(workflow)
            if item.status in {RecommendationStatus.STALE, RecommendationStatus.EXPIRED}:
                reason = item.transitions[-1].reason if item.transitions else item.status.value
                self._block_drafts(
                    self._connection,
                    project_id,
                    item.id,
                    item.status.value,
                    item.updated_at,
                    reason,
                )
            record = RecommendationCommandRecord(command, result)
            self._insert_command(record)
            return StoredRecommendationCommand(record, replayed=False)
        except psycopg.errors.UniqueViolation as error:
            raise RecommendationVersionConflict(
                "Recommendation version, review, draft, or command changed concurrently"
            ) from error
        except psycopg.Error as error:
            raise RecommendationPersistenceError(
                "PostgreSQL rejected the Recommendation transaction"
            ) from error

    def _workflow(
        self,
        project_id: UUID,
        recommendation_id: UUID,
        *,
        for_update: bool,
    ) -> RecommendationWorkflow | None:
        self._require_scope(project_id)
        # ``geo_app`` is deliberately append-only on Recommendation versions.
        # A transaction-scoped advisory lock serializes transitions without
        # requiring UPDATE privilege merely to read the current version.
        del for_update
        row = self._connection.execute(
            """SELECT project_id, recommendation_id, version, status,
                      recommendation_type, proposed_draft_kind, evidence_graph_hash,
                      input_fingerprint, valid_until, created_by,
                      workflow_payload, workflow_payload_hash
               FROM recommendation_workflow_versions
               WHERE project_id = %s AND recommendation_id = %s
               ORDER BY version DESC LIMIT 1""",
            (project_id, recommendation_id),
        ).fetchone()
        return workflow_from_row(row) if row is not None else None

    def _lock_lifecycle(self, project_id: UUID, recommendation_id: UUID) -> None:
        self._require_scope(project_id)
        self._connection.execute(
            """SELECT pg_advisory_xact_lock(
                   hashtextextended(%s::text || ':' || %s::text, 0)
               )""",
            (project_id, recommendation_id),
        )

    def _insert_workflow(self, workflow: RecommendationWorkflow) -> None:
        item = workflow.recommendation
        payload = workflow_payload(workflow)
        self._connection.execute(
            """INSERT INTO recommendation_workflow_versions(
                   project_id, recommendation_id, version, status,
                   recommendation_type, proposed_draft_kind, evidence_graph_hash,
                   input_fingerprint, valid_until, created_by, created_at, updated_at,
                   workflow_payload, workflow_payload_hash
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                item.project_id,
                item.id,
                item.version,
                item.status.value,
                item.recommendation_type.value,
                item.proposed_draft_kind.value if item.proposed_draft_kind else None,
                item.evidence.graph_hash,
                item.evidence.input_fingerprint,
                item.valid_until,
                UUID(item.created_by),
                item.created_at,
                item.updated_at,
                Jsonb(payload),
                canonical_hash(payload),
            ),
        )

    def _insert_evidence_bindings(self, workflow: RecommendationWorkflow) -> None:
        item = workflow.recommendation
        for ordinal, reference in enumerate(item.evidence.all_refs):
            self._connection.execute(
                """INSERT INTO recommendation_evidence_bindings(
                       project_id, recommendation_id, recommendation_version,
                       ordinal, evidence_kind, resource_id, resource_version,
                       resource_hash, locator, input_versions
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    item.project_id,
                    item.id,
                    item.version,
                    ordinal,
                    reference.ref_kind,
                    reference.resource_id,
                    reference.version,
                    reference.sha256,
                    Jsonb(dict(reference.locator)),
                    Jsonb(
                        [
                            {
                                "kind": value.kind.value,
                                "resource_id": value.resource_id,
                                "version": value.version,
                                "sha256": value.sha256,
                            }
                            for value in reference.input_versions()
                        ]
                    ),
                ),
            )

    def _insert_approval(self, workflow: RecommendationWorkflow) -> None:
        item = workflow.recommendation
        approval = item.approval
        assert approval is not None
        self._connection.execute(
            """INSERT INTO recommendation_approvals(
                   id, project_id, recommendation_id, recommendation_version,
                   approved_by, approved_at, frozen_input_versions,
                   frozen_input_fingerprint, frozen_evidence_graph_hash, valid_until
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                approval.id,
                item.project_id,
                item.id,
                approval.recommendation_version,
                UUID(approval.approved_by),
                approval.approved_at,
                Jsonb(
                    [
                        {
                            "kind": value.kind.value,
                            "resource_id": value.resource_id,
                            "version": value.version,
                            "sha256": value.sha256,
                        }
                        for value in approval.frozen_input_versions
                    ]
                ),
                approval.frozen_input_fingerprint,
                approval.frozen_evidence_graph_hash,
                approval.valid_until,
            ),
        )

    def _insert_review(
        self, review: RecommendationReview, workflow: RecommendationWorkflow
    ) -> None:
        item = workflow.recommendation
        if (
            review.project_id != item.project_id
            or review.recommendation_id != item.id
            or review.recommendation_version != item.version
            or review.evidence_graph_hash != item.evidence.graph_hash
        ):
            raise RecommendationPersistenceError("Recommendation review scope is invalid")
        self._connection.execute(
            """INSERT INTO recommendation_reviews(
                   id, project_id, recommendation_id, recommendation_version,
                   evidence_graph_hash, reviewed_by, notes, reviewed_at
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                review.id,
                review.project_id,
                review.recommendation_id,
                review.recommendation_version,
                review.evidence_graph_hash,
                review.reviewed_by,
                review.notes,
                review.reviewed_at,
            ),
        )

    def _flush_pending_drafts(self, workflow: RecommendationWorkflow) -> None:
        item = workflow.recommendation
        if item.status is not RecommendationStatus.APPROVED or item.approval is None:
            if self._pending_drafts:
                raise RecommendationPersistenceError(
                    "only an approved Recommendation can stage a downstream draft"
                )
            return
        expected = concrete_draft_from_approval(workflow)
        assert expected is not None
        if self._pending_drafts != [expected]:
            raise RecommendationPersistenceError(
                "approved Recommendation must stage its exact concrete draft"
            )
        _insert_concrete_draft(self._connection, expected)
        self._pending_drafts.clear()

    def _insert_command(self, record: RecommendationCommandRecord) -> None:
        result_kind, payload = command_result_payload(record.result)
        identity = record.identity
        self._connection.execute(
            """INSERT INTO recommendation_command_receipts(
                   project_id, idempotency_key_hash, operation, request_hash,
                   result_kind, result_payload, result_payload_hash, created_at
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, clock_timestamp())""",
            (
                identity.project_id,
                identity.idempotency_key_hash,
                identity.operation.value,
                identity.request_hash,
                result_kind,
                Jsonb(payload),
                canonical_hash(payload),
            ),
        )

    def _assert_transition(
        self,
        *,
        current: RecommendationWorkflow | None,
        candidate: RecommendationWorkflow,
        expected_version: int,
        has_review: bool,
    ) -> None:
        version = candidate.recommendation.version
        if current is None:
            if expected_version != 0 or version != 1 or has_review:
                raise RecommendationVersionConflict("Recommendation create CAS failed")
            return
        current_version = current.recommendation.version
        if current_version != expected_version:
            raise RecommendationVersionConflict("Recommendation transition CAS failed")
        allowed = {expected_version + 1}
        if has_review:
            allowed.add(expected_version)
        if version not in allowed:
            raise RecommendationVersionConflict("Recommendation version increment is invalid")
        _reject_unchecked_start(current, candidate)

    def _require_scope(self, project_id: UUID) -> None:
        if project_id != self._project_id:
            raise RecommendationPersistenceError("Recommendation repository Project mismatch")


class ApprovalDraftBuffer:
    """Stage one exact concrete draft until its approval row exists in this transaction."""

    def __init__(self, pending: list[ConcreteRecommendationDraft]) -> None:
        self._pending = pending

    def create_from_approved_recommendation(
        self, workflow: RecommendationWorkflow
    ) -> CreatedDownstreamDraft:
        draft = concrete_draft_from_approval(workflow)
        if draft is None:
            raise RecommendationPersistenceError(
                "approved Recommendation does not create a concrete draft"
            )
        if self._pending and self._pending != [draft]:
            raise RecommendationVersionConflict("downstream draft identity already staged")
        if not self._pending:
            self._pending.append(draft)
        return CreatedDownstreamDraft(draft.source.project_id, draft.id, draft.kind)


def _insert_concrete_draft(connection: Any, draft: ConcreteRecommendationDraft) -> None:
    payload = concrete_draft_payload(draft)
    source = draft.source
    connection.execute(
        """INSERT INTO recommendation_drafts(
               id, project_id, recommendation_id, recommendation_version,
               approval_id, kind, idempotency_key, frozen_input_fingerprint,
               frozen_evidence_graph_hash, source_valid_until, status,
               draft_payload, draft_payload_hash, created_at, blocked_at, blocked_reason
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            draft.id,
            source.project_id,
            source.recommendation_id,
            source.recommendation_version,
            source.approval_id,
            draft.kind.value,
            draft.idempotency_key,
            source.input_fingerprint,
            source.evidence_graph_hash,
            source.valid_until,
            draft.status.value,
            Jsonb(payload),
            canonical_hash(payload),
            draft.created_at,
            draft.blocked_at,
            draft.blocked_reason,
        ),
    )


def _reject_unchecked_start(
    current: RecommendationWorkflow, candidate: RecommendationWorkflow
) -> None:
    prior = {draft.id: draft for draft in current.drafts}
    if any(draft.id not in {item.id for item in candidate.drafts} for draft in current.drafts):
        raise RecommendationPersistenceError("linked drafts cannot be removed")
    for draft in candidate.drafts:
        previous = prior.get(draft.id)
        if draft.status is DownstreamDraftStatus.STARTED and (
            previous is None or previous.status is not DownstreamDraftStatus.STARTED
        ):
            raise RecommendationSourceCheckRequired(
                "draft start requires RecommendationUnitOfWork.prepare_draft_action"
            )


def _replay(
    existing: RecommendationCommandRecord,
    command: RecommendationCommandIdentity,
) -> StoredRecommendationCommand:
    if (
        existing.identity.operation != command.operation
        or existing.identity.request_hash != command.request_hash
    ):
        raise RecommendationIdempotencyConflict(
            "Recommendation idempotency key was reused for a different request"
        )
    return StoredRecommendationCommand(existing, replayed=True)


__all__ = [
    "ApprovalDraftBuffer",
    "BlockDrafts",
    "PsycopgRecommendationRepository",
]
