"""Project-scoped persistence and side-effect ports for Recommendation commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from types import TracebackType
from typing import Literal, Protocol
from uuid import UUID

from geo_core.recommendations.models import (
    DownstreamDraftKind,
    DraftActionCheck,
    InputChangeReason,
    RecommendationWorkflow,
)
from geo_core.recommendations.resolution import RecommendationEvidenceResolverPort


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RecommendationPersistenceError(RuntimeError):
    """A Recommendation transaction could not be persisted."""


class RecommendationVersionConflict(RecommendationPersistenceError):
    """The aggregate changed after the caller read its expected version."""


class RecommendationIdempotencyConflict(RecommendationPersistenceError):
    """An idempotency key was reused for a different immutable request."""


class RecommendationSourceCheckRequired(RecommendationPersistenceError):
    """A caller attempted to start a draft without the mandatory source recheck."""


class RecommendationCommandOperation(StrEnum):
    CREATE = "create"
    SUBMIT = "submit"
    REVIEW = "review"
    APPROVE = "approve"
    REJECT = "reject"
    RECONCILE_STALE = "reconcile_stale"
    EXPIRE = "expire"
    PREPARE_DRAFT_ACTION = "prepare_draft_action"


@dataclass(frozen=True)
class RecommendationCommandIdentity:
    project_id: UUID
    idempotency_key_hash: str
    operation: RecommendationCommandOperation
    request_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", RecommendationCommandOperation(self.operation))
        if not _SHA256.fullmatch(self.idempotency_key_hash):
            raise ValueError("Recommendation idempotency key hash must be SHA-256")
        if not _SHA256.fullmatch(self.request_hash):
            raise ValueError("Recommendation request hash must be SHA-256")


@dataclass(frozen=True)
class RecommendationCommandRecord:
    identity: RecommendationCommandIdentity
    result: object


@dataclass(frozen=True)
class StoredRecommendationCommand:
    record: RecommendationCommandRecord
    replayed: bool


@dataclass(frozen=True)
class RecommendationReview:
    id: UUID
    project_id: UUID
    recommendation_id: UUID
    recommendation_version: int
    evidence_graph_hash: str
    reviewed_by: UUID
    notes: str
    reviewed_at: datetime

    def __post_init__(self) -> None:
        if self.recommendation_version < 1:
            raise ValueError("Recommendation review version must be positive")
        if not _SHA256.fullmatch(self.evidence_graph_hash):
            raise ValueError("Recommendation review evidence hash must be SHA-256")
        notes = self.notes.strip()
        if not notes:
            raise ValueError("Recommendation review notes are required")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("Recommendation review time must be timezone-aware")
        object.__setattr__(self, "notes", notes)


@dataclass(frozen=True)
class CreatedDownstreamDraft:
    project_id: UUID
    draft_id: UUID
    kind: DownstreamDraftKind
    status: Literal["draft"] = "draft"
    enqueued: Literal[False] = False
    executed: Literal[False] = False
    published: Literal[False] = False


@dataclass(frozen=True)
class PreparedDraftAction:
    check: DraftActionCheck
    cancelled_outbox_ids: tuple[UUID, ...] = ()


class RecommendationRepository(Protocol):
    """No repository method may start a linked draft directly."""

    def get_command(
        self, *, project_id: UUID, idempotency_key_hash: str
    ) -> RecommendationCommandRecord | None: ...

    def get_workflow(
        self, *, project_id: UUID, recommendation_id: UUID
    ) -> RecommendationWorkflow | None: ...

    def get_review(
        self, *, project_id: UUID, recommendation_id: UUID
    ) -> RecommendationReview | None: ...

    def store_workflow(
        self,
        *,
        project_id: UUID,
        workflow: RecommendationWorkflow,
        expected_version: int,
        command: RecommendationCommandIdentity,
        result: object,
        review: RecommendationReview | None = None,
    ) -> StoredRecommendationCommand: ...


class DownstreamDraftPort(Protocol):
    """Derive one concrete shell from the complete approved aggregate."""

    def create_from_approved_recommendation(
        self, workflow: RecommendationWorkflow
    ) -> CreatedDownstreamDraft: ...


class RecommendationOutboxPort(Protocol):
    def cancel_unpublished_for_recommendation(
        self, *, project_id: UUID, recommendation_id: UUID, reason: str
    ) -> tuple[UUID, ...]: ...


class RecommendationUnitOfWork(Protocol):
    recommendations: RecommendationRepository
    evidence: RecommendationEvidenceResolverPort
    drafts: DownstreamDraftPort
    outbox: RecommendationOutboxPort

    def __enter__(self) -> "RecommendationUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

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
        """Lock, recheck source version/inputs, persist blocking, then issue a receipt."""
        ...

    def commit(self) -> None: ...


class RecommendationUnitOfWorkFactory(Protocol):
    def __call__(self, *, project_id: UUID) -> RecommendationUnitOfWork: ...
