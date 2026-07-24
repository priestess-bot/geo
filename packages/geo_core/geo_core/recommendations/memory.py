"""Transactional in-memory Recommendation adapters for application tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from threading import RLock
from types import TracebackType
from typing import TypeVar
from uuid import UUID, uuid4

from geo_core.recommendations.draft_operations import prepare_draft_action
from geo_core.recommendations.evidence import EvidenceRef
from geo_core.recommendations.models import (
    DownstreamDraftStatus,
    InputChangeReason,
    RecommendationStatus,
    RecommendationWorkflow,
)
from geo_core.recommendations.ports import (
    CreatedDownstreamDraft,
    PreparedDraftAction,
    RecommendationCommandIdentity,
    RecommendationCommandRecord,
    RecommendationIdempotencyConflict,
    RecommendationOutboxPort,
    RecommendationPersistenceError,
    RecommendationRepository,
    RecommendationReview,
    RecommendationSourceCheckRequired,
    RecommendationUnitOfWork,
    RecommendationUnitOfWorkFactory,
    RecommendationVersionConflict,
    StoredRecommendationCommand,
)
from geo_core.recommendations.resolution import (
    RecommendationEvidenceResolverPort,
    RecommendationEvidenceSelector,
    resolve_current_graph,
)


@dataclass(frozen=True)
class MemoryOutboxMessage:
    id: UUID
    project_id: UUID
    recommendation_id: UUID
    delivered: bool = False
    cancelled: bool = False
    cancellation_reason: str | None = None


_KeyT = TypeVar("_KeyT")
_ValueT = TypeVar("_ValueT")


class InMemoryRecommendationStore:
    """Shared committed state; each UoW works on an isolated snapshot."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._workflows: dict[tuple[UUID, UUID], RecommendationWorkflow] = {}
        self._commands: dict[tuple[UUID, str], RecommendationCommandRecord] = {}
        self._reviews: dict[tuple[UUID, UUID], RecommendationReview] = {}
        self._evidence_refs: dict[tuple[UUID, str, str], EvidenceRef] = {}
        self._drafts: dict[tuple[UUID, UUID], CreatedDownstreamDraft] = {}
        self._outbox: dict[UUID, MemoryOutboxMessage] = {}
        self._fail_next_commit = False

    def unit_of_work_factory(self) -> RecommendationUnitOfWorkFactory:
        return InMemoryRecommendationUnitOfWorkFactory(self)

    def workflow(
        self, *, project_id: UUID, recommendation_id: UUID
    ) -> RecommendationWorkflow | None:
        with self._lock:
            return self._workflows.get((project_id, recommendation_id))

    def downstream_drafts(self, *, project_id: UUID) -> tuple[CreatedDownstreamDraft, ...]:
        with self._lock:
            return tuple(
                value
                for (draft_project_id, _), value in self._drafts.items()
                if draft_project_id == project_id
            )

    def install_evidence(self, *references: EvidenceRef) -> None:
        """Install authoritative current-source fixtures for application tests."""

        with self._lock:
            for reference in references:
                key = (reference.project_id, reference.ref_kind, reference.resource_id)
                self._evidence_refs[key] = reference

    def seed_outbox(
        self, *, project_id: UUID, recommendation_id: UUID, delivered: bool = False
    ) -> MemoryOutboxMessage:
        message = MemoryOutboxMessage(uuid4(), project_id, recommendation_id, delivered=delivered)
        with self._lock:
            self._outbox[message.id] = message
        return message

    def outbox_message(self, message_id: UUID) -> MemoryOutboxMessage | None:
        with self._lock:
            return self._outbox.get(message_id)

    def fail_next_commit(self) -> None:
        with self._lock:
            self._fail_next_commit = True


class InMemoryRecommendationUnitOfWorkFactory:
    def __init__(self, store: InMemoryRecommendationStore) -> None:
        self.store = store

    def __call__(self, *, project_id: UUID) -> RecommendationUnitOfWork:
        return InMemoryRecommendationUnitOfWork(self.store, project_id=project_id)


class InMemoryRecommendationUnitOfWork:
    def __init__(self, store: InMemoryRecommendationStore, *, project_id: UUID) -> None:
        self._store = store
        self.project_id = project_id
        self._active = False
        self._committed = False
        self._touched_workflows: set[tuple[UUID, UUID]] = set()
        self._touched_commands: set[tuple[UUID, str]] = set()
        self._touched_reviews: set[tuple[UUID, UUID]] = set()
        self._touched_drafts: set[tuple[UUID, UUID]] = set()
        self._touched_outbox: set[UUID] = set()
        self.recommendations: RecommendationRepository = _MemoryRecommendationRepository(self)
        self.evidence: RecommendationEvidenceResolverPort = _MemoryEvidenceResolver(self)
        self.drafts = _MemoryDownstreamDraftPort(self)
        self.outbox: RecommendationOutboxPort = _MemoryRecommendationOutbox(self)

    def __enter__(self) -> "InMemoryRecommendationUnitOfWork":
        if self._active:
            raise RecommendationPersistenceError("Recommendation UoW is already active")
        with self._store._lock:
            self._base_workflows = dict(self._store._workflows)
            self._base_commands = dict(self._store._commands)
            self._base_reviews = dict(self._store._reviews)
            self._base_evidence_refs = dict(self._store._evidence_refs)
            self._base_drafts = dict(self._store._drafts)
            self._base_outbox = dict(self._store._outbox)
        self._workflows = dict(self._base_workflows)
        self._commands = dict(self._base_commands)
        self._reviews = dict(self._base_reviews)
        self._evidence_refs = dict(self._base_evidence_refs)
        self._draft_records = dict(self._base_drafts)
        self._outbox_records = dict(self._base_outbox)
        self._active = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self._active = False
        return None

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
        repository = self.recommendations
        existing = repository.get_command(
            project_id=project_id,
            idempotency_key_hash=command.idempotency_key_hash,
        )
        if existing is not None:
            return _replay(existing, command)
        workflow = repository.get_workflow(
            project_id=project_id, recommendation_id=recommendation_id
        )
        if workflow is None:
            raise RecommendationPersistenceError("Recommendation does not exist")
        current_evidence = resolve_current_graph(self.evidence, workflow.recommendation.evidence)
        check = prepare_draft_action(
            workflow,
            draft_id=draft_id,
            expected_recommendation_version=expected_recommendation_version,
            current_inputs=current_evidence.input_versions,
            current_evidence_graph_hash=current_evidence.graph_hash,
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
        return repository.store_workflow(
            project_id=project_id,
            workflow=check.workflow,
            expected_version=workflow.recommendation.version,
            command=command,
            result=result,
        )

    def commit(self) -> None:
        self._ensure_active()
        with self._store._lock:
            if self._store._fail_next_commit:
                self._store._fail_next_commit = False
                raise RecommendationPersistenceError("simulated Recommendation commit failure")
            self._verify_unchanged(
                self._touched_workflows,
                self._base_workflows,
                self._store._workflows,
                RecommendationVersionConflict,
            )
            self._verify_unchanged(
                self._touched_commands,
                self._base_commands,
                self._store._commands,
                RecommendationIdempotencyConflict,
            )
            self._verify_unchanged(
                self._touched_reviews,
                self._base_reviews,
                self._store._reviews,
                RecommendationVersionConflict,
            )
            self._verify_unchanged(
                self._touched_drafts,
                self._base_drafts,
                self._store._drafts,
                RecommendationVersionConflict,
            )
            self._verify_unchanged(
                self._touched_outbox,
                self._base_outbox,
                self._store._outbox,
                RecommendationVersionConflict,
            )
            _apply_touched(self._store._workflows, self._workflows, self._touched_workflows)
            _apply_touched(self._store._commands, self._commands, self._touched_commands)
            _apply_touched(self._store._reviews, self._reviews, self._touched_reviews)
            _apply_touched(self._store._drafts, self._draft_records, self._touched_drafts)
            _apply_touched(self._store._outbox, self._outbox_records, self._touched_outbox)
        self._committed = True

    def _verify_unchanged(
        self,
        keys: set[_KeyT],
        base: dict[_KeyT, _ValueT],
        current: dict[_KeyT, _ValueT],
        error_type: type[RecommendationPersistenceError],
    ) -> None:
        for key in keys:
            if current.get(key) != base.get(key):
                raise error_type("concurrent Recommendation transaction changed committed state")

    def _require_scope(self, project_id: UUID) -> None:
        self._ensure_active()
        if project_id != self.project_id:
            raise RecommendationPersistenceError("Recommendation UoW project scope mismatch")

    def _ensure_active(self) -> None:
        if not self._active:
            raise RecommendationPersistenceError("Recommendation UoW is not active")


class _MemoryRecommendationRepository:
    def __init__(self, uow: InMemoryRecommendationUnitOfWork) -> None:
        self._uow = uow

    def get_command(
        self, *, project_id: UUID, idempotency_key_hash: str
    ) -> RecommendationCommandRecord | None:
        self._uow._require_scope(project_id)
        return self._uow._commands.get((project_id, idempotency_key_hash))

    def get_workflow(
        self, *, project_id: UUID, recommendation_id: UUID
    ) -> RecommendationWorkflow | None:
        self._uow._require_scope(project_id)
        return self._uow._workflows.get((project_id, recommendation_id))

    def get_review(
        self, *, project_id: UUID, recommendation_id: UUID
    ) -> RecommendationReview | None:
        self._uow._require_scope(project_id)
        return self._uow._reviews.get((project_id, recommendation_id))

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
        self._uow._require_scope(project_id)
        if command.project_id != project_id or workflow.recommendation.project_id != project_id:
            raise RecommendationPersistenceError("Recommendation write scope mismatch")
        command_key = (project_id, command.idempotency_key_hash)
        existing = self._uow._commands.get(command_key)
        if existing is not None:
            return _replay(existing, command)
        workflow_key = (project_id, workflow.recommendation.id)
        current = self._uow._workflows.get(workflow_key)
        if current is None:
            if expected_version != 0 or workflow.recommendation.version != 1:
                raise RecommendationVersionConflict("Recommendation create CAS failed")
        else:
            if current.recommendation.version != expected_version:
                raise RecommendationVersionConflict("Recommendation transition CAS failed")
            if workflow.recommendation.version not in {expected_version, expected_version + 1}:
                raise RecommendationVersionConflict("Recommendation version increment is invalid")
            _reject_unchecked_start(current, workflow)
        if review is not None:
            if (
                review.project_id != project_id
                or review.recommendation_id != workflow.recommendation.id
                or review.recommendation_version != workflow.recommendation.version
                or review.evidence_graph_hash != workflow.recommendation.evidence.graph_hash
            ):
                raise RecommendationPersistenceError("Recommendation review scope is invalid")
            review_key = (project_id, workflow.recommendation.id)
            self._uow._reviews[review_key] = review
            self._uow._touched_reviews.add(review_key)
        record = RecommendationCommandRecord(command, result)
        self._uow._workflows[workflow_key] = workflow
        self._uow._commands[command_key] = record
        self._uow._touched_workflows.add(workflow_key)
        self._uow._touched_commands.add(command_key)
        return StoredRecommendationCommand(record, replayed=False)


class _MemoryEvidenceResolver:
    def __init__(self, uow: InMemoryRecommendationUnitOfWork) -> None:
        self._uow = uow

    def resolve_current(
        self,
        *,
        project_id: UUID,
        selectors: tuple[RecommendationEvidenceSelector, ...],
    ) -> tuple[EvidenceRef, ...]:
        self._uow._require_scope(project_id)
        resolved: list[EvidenceRef] = []
        for selector in selectors:
            key = (project_id, selector.kind.value, selector.resource_id)
            reference = self._uow._evidence_refs.get(key)
            if reference is None:
                raise RecommendationPersistenceError(
                    "authoritative Recommendation evidence does not exist in this Project"
                )
            resolved.append(reference)
        return tuple(resolved)


class _MemoryDownstreamDraftPort:
    def __init__(self, uow: InMemoryRecommendationUnitOfWork) -> None:
        self._uow = uow

    def create_from_approved_recommendation(
        self, workflow: RecommendationWorkflow
    ) -> CreatedDownstreamDraft:
        from geo_core.recommendations.downstream_service import (
            concrete_draft_from_approval,
        )

        recommendation = workflow.recommendation
        self._uow._require_scope(recommendation.project_id)
        concrete = concrete_draft_from_approval(workflow)
        if concrete is None:
            raise RecommendationPersistenceError(
                "approved Recommendation does not produce a concrete draft"
            )
        key = (recommendation.project_id, concrete.id)
        created = CreatedDownstreamDraft(
            recommendation.project_id,
            concrete.id,
            concrete.kind,
        )
        existing = self._uow._draft_records.get(key)
        if existing is not None and existing != created:
            raise RecommendationVersionConflict("downstream draft identity already exists")
        self._uow._draft_records[key] = created
        self._uow._touched_drafts.add(key)
        return created


class _MemoryRecommendationOutbox:
    def __init__(self, uow: InMemoryRecommendationUnitOfWork) -> None:
        self._uow = uow

    def cancel_unpublished_for_recommendation(
        self, *, project_id: UUID, recommendation_id: UUID, reason: str
    ) -> tuple[UUID, ...]:
        self._uow._require_scope(project_id)
        cancelled: list[UUID] = []
        for message_id, message in tuple(self._uow._outbox_records.items()):
            if (
                message.project_id == project_id
                and message.recommendation_id == recommendation_id
                and not message.delivered
                and not message.cancelled
            ):
                self._uow._outbox_records[message_id] = replace(
                    message, cancelled=True, cancellation_reason=reason
                )
                self._uow._touched_outbox.add(message_id)
                cancelled.append(message_id)
        return tuple(sorted(cancelled, key=str))


def _replay(
    existing: RecommendationCommandRecord, command: RecommendationCommandIdentity
) -> StoredRecommendationCommand:
    if (
        existing.identity.operation != command.operation
        or existing.identity.request_hash != command.request_hash
    ):
        raise RecommendationIdempotencyConflict(
            "Recommendation idempotency key was reused for a different request"
        )
    return StoredRecommendationCommand(existing, replayed=True)


def _reject_unchecked_start(
    current: RecommendationWorkflow, candidate: RecommendationWorkflow
) -> None:
    current_drafts = {draft.id: draft for draft in current.drafts}
    if any(draft.id not in {item.id for item in candidate.drafts} for draft in current.drafts):
        raise RecommendationPersistenceError("linked drafts cannot be removed")
    for draft in candidate.drafts:
        previous = current_drafts.get(draft.id)
        if draft.status == DownstreamDraftStatus.STARTED and (
            previous is None or previous.status != DownstreamDraftStatus.STARTED
        ):
            raise RecommendationSourceCheckRequired(
                "draft start requires RecommendationUnitOfWork.prepare_draft_action"
            )


def _apply_touched(
    target: dict[_KeyT, _ValueT],
    source: dict[_KeyT, _ValueT],
    keys: set[_KeyT],
) -> None:
    for key in keys:
        target[key] = source[key]
