"""Authorized, idempotent Recommendation application commands."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from geo_core.access.models import AccessPrincipal
from geo_core.recommendations.application_support import (
    ApprovedRecommendation,
    CommandReceipt,
    InvalidatedRecommendation,
    RecommendationForbidden,
    RecommendationReviewRequired,
    ReviewedRecommendation,
    command_identity as _command_identity,
    recover as _recover,
    require_expected_version as _require_expected_version,
    require_project_role as _require_project_role,
    stored_receipt as _stored_receipt,
    workflow as _workflow,
)
from geo_core.recommendations.errors import RecommendationConflict
from geo_core.recommendations.evidence import (
    RecommendationDecision,
    RecommendationScope,
)
from geo_core.recommendations.lifecycle import (
    approve_and_create_draft,
    expire_recommendation,
    reconcile_approved_inputs,
    reject_recommendation,
    submit_recommendation,
)
from geo_core.recommendations.models import (
    DownstreamDraftKind,
    InputChangeReason,
    Recommendation,
    RecommendationStatus,
    RecommendationType,
    RecommendationWorkflow,
)
from geo_core.recommendations.ports import (
    PreparedDraftAction,
    RecommendationCommandOperation,
    RecommendationReview,
    RecommendationUnitOfWorkFactory,
    RecommendationVersionConflict,
)
from geo_core.recommendations.resolution import (
    RecommendationEvidenceSelector,
    require_unchanged_evidence,
    resolve_current_graph,
    resolve_evidence_graph,
)


_CONTRIBUTOR_ROLES = frozenset({"owner", "admin", "analyst"})
_APPROVER_ROLES = frozenset({"owner", "admin"})


class RecommendationApplication:
    """Authorize and atomically persist all Recommendation mutations."""

    def __init__(
        self,
        unit_of_work_factory: RecommendationUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._id_factory = id_factory
        self._clock = clock

    def create_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_type: RecommendationType,
        scope: RecommendationScope,
        decision: RecommendationDecision,
        evidence_selectors: tuple[RecommendationEvidenceSelector, ...],
        proposed_draft_kind: DownstreamDraftKind | None,
        valid_until: datetime,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[RecommendationWorkflow]:
        _require_project_role(principal, project_id, allowed=_CONTRIBUTOR_ROLES)
        command = _command_identity(
            operation=RecommendationCommandOperation.CREATE,
            principal=principal,
            project_id=project_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            values={
                "recommendation_type": RecommendationType(recommendation_type).value,
                "scope": scope.canonical_value(),
                "decision": decision.canonical_value(),
                "evidence_selectors": [
                    item.canonical_value() for item in evidence_selectors
                ],
                "proposed_draft_kind": (
                    DownstreamDraftKind(proposed_draft_kind).value
                    if proposed_draft_kind is not None
                    else None
                ),
                "valid_until": valid_until,
            },
        )
        with self._unit_of_work_factory(project_id=project_id) as uow:
            replay = _recover(uow, command, RecommendationWorkflow)
            if replay is not None:
                return replay
            if expected_version != 0:
                raise RecommendationVersionConflict(
                    "new Recommendations require expected_version=0"
                )
            resolved_evidence = resolve_evidence_graph(
                uow.evidence,
                project_id=project_id,
                scope=scope,
                decision=decision,
                selectors=evidence_selectors,
            )
            now = self._clock()
            recommendation = Recommendation(
                id=self._id_factory(),
                project_id=project_id,
                recommendation_type=recommendation_type,
                evidence=resolved_evidence,
                proposed_draft_kind=proposed_draft_kind,
                valid_until=valid_until,
                created_by=str(principal.identity_id),
                created_at=now,
                updated_at=now,
            )
            result = RecommendationWorkflow(recommendation)
            stored = uow.recommendations.store_workflow(
                project_id=project_id,
                workflow=result,
                expected_version=expected_version,
                command=command,
                result=result,
            )
            uow.commit()
            return _stored_receipt(stored, RecommendationWorkflow)

    def submit_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[RecommendationWorkflow]:
        _require_project_role(principal, project_id, allowed=_CONTRIBUTOR_ROLES)
        command = _command_identity(
            operation=RecommendationCommandOperation.SUBMIT,
            principal=principal,
            project_id=project_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            values={"recommendation_id": recommendation_id},
        )
        with self._unit_of_work_factory(project_id=project_id) as uow:
            replay = _recover(uow, command, RecommendationWorkflow)
            if replay is not None:
                return replay
            current = _workflow(uow, project_id, recommendation_id)
            _require_expected_version(current, expected_version)
            result = submit_recommendation(
                current,
                expected_version=expected_version,
                actor_id=str(principal.identity_id),
                occurred_at=self._clock(),
            )
            stored = uow.recommendations.store_workflow(
                project_id=project_id,
                workflow=result,
                expected_version=expected_version,
                command=command,
                result=result,
            )
            uow.commit()
            return _stored_receipt(stored, RecommendationWorkflow)

    def review_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        notes: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[ReviewedRecommendation]:
        _require_project_role(principal, project_id, allowed=_APPROVER_ROLES)
        command = _command_identity(
            operation=RecommendationCommandOperation.REVIEW,
            principal=principal,
            project_id=project_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            values={
                "recommendation_id": recommendation_id,
                "notes": notes.strip(),
            },
        )
        with self._unit_of_work_factory(project_id=project_id) as uow:
            replay = _recover(uow, command, ReviewedRecommendation)
            if replay is not None:
                return replay
            current = _workflow(uow, project_id, recommendation_id)
            _require_expected_version(current, expected_version)
            if current.recommendation.status != RecommendationStatus.IN_REVIEW:
                raise RecommendationConflict("only an in-review Recommendation can be reviewed")
            resolved_evidence = resolve_current_graph(
                uow.evidence, current.recommendation.evidence
            )
            require_unchanged_evidence(current.recommendation.evidence, resolved_evidence)
            review = RecommendationReview(
                id=self._id_factory(),
                project_id=project_id,
                recommendation_id=recommendation_id,
                recommendation_version=expected_version,
                evidence_graph_hash=current.recommendation.evidence.graph_hash,
                reviewed_by=principal.identity_id,
                notes=notes,
                reviewed_at=self._clock(),
            )
            result = ReviewedRecommendation(current, review)
            stored = uow.recommendations.store_workflow(
                project_id=project_id,
                workflow=current,
                expected_version=expected_version,
                command=command,
                result=result,
                review=review,
            )
            uow.commit()
            return _stored_receipt(stored, ReviewedRecommendation)

    def approve_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[ApprovedRecommendation]:
        _require_project_role(principal, project_id, allowed=_APPROVER_ROLES)
        command = _command_identity(
            operation=RecommendationCommandOperation.APPROVE,
            principal=principal,
            project_id=project_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            values={"recommendation_id": recommendation_id},
        )
        with self._unit_of_work_factory(project_id=project_id) as uow:
            replay = _recover(uow, command, ApprovedRecommendation)
            if replay is not None:
                return replay
            current = _workflow(uow, project_id, recommendation_id)
            _require_expected_version(current, expected_version)
            resolved_evidence = resolve_current_graph(
                uow.evidence, current.recommendation.evidence
            )
            require_unchanged_evidence(current.recommendation.evidence, resolved_evidence)
            if current.recommendation.created_by == str(principal.identity_id):
                raise RecommendationForbidden("Recommendation creators cannot self-approve")
            review = uow.recommendations.get_review(
                project_id=project_id, recommendation_id=recommendation_id
            )
            if (
                review is None
                or review.recommendation_version != expected_version
                or review.evidence_graph_hash != current.recommendation.evidence.graph_hash
            ):
                raise RecommendationReviewRequired(
                    "approval requires review of the current Recommendation evidence"
                )
            outcome = approve_and_create_draft(
                current,
                expected_version=expected_version,
                approval_id=self._id_factory(),
                actor_id=str(principal.identity_id),
                current_inputs=resolved_evidence.input_versions,
                occurred_at=self._clock(),
                draft_idempotency_key=(
                    f"{command.idempotency_key_hash}:downstream"
                    if current.recommendation.proposed_draft_kind is not None
                    else None
                ),
            )
            created = (
                uow.drafts.create_from_approved_recommendation(outcome.workflow)
                if outcome.draft is not None
                else None
            )
            result = ApprovedRecommendation(outcome.workflow, created)
            stored = uow.recommendations.store_workflow(
                project_id=project_id,
                workflow=outcome.workflow,
                expected_version=expected_version,
                command=command,
                result=result,
            )
            uow.commit()
            return _stored_receipt(stored, ApprovedRecommendation)

    def reject_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        reason: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[RecommendationWorkflow]:
        _require_project_role(principal, project_id, allowed=_APPROVER_ROLES)
        command = _command_identity(
            operation=RecommendationCommandOperation.REJECT,
            principal=principal,
            project_id=project_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            values={"recommendation_id": recommendation_id, "reason": reason.strip()},
        )
        with self._unit_of_work_factory(project_id=project_id) as uow:
            replay = _recover(uow, command, RecommendationWorkflow)
            if replay is not None:
                return replay
            current = _workflow(uow, project_id, recommendation_id)
            _require_expected_version(current, expected_version)
            result = reject_recommendation(
                current,
                expected_version=expected_version,
                actor_id=str(principal.identity_id),
                reason=reason,
                occurred_at=self._clock(),
            )
            stored = uow.recommendations.store_workflow(
                project_id=project_id,
                workflow=result,
                expected_version=expected_version,
                command=command,
                result=result,
            )
            uow.commit()
            return _stored_receipt(stored, RecommendationWorkflow)

    def reconcile_stale(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        change_reason: InputChangeReason,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[InvalidatedRecommendation]:
        _require_project_role(principal, project_id, allowed=_CONTRIBUTOR_ROLES)
        command = _command_identity(
            operation=RecommendationCommandOperation.RECONCILE_STALE,
            principal=principal,
            project_id=project_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            values={
                "recommendation_id": recommendation_id,
                "change_reason": InputChangeReason(change_reason).value,
            },
        )
        with self._unit_of_work_factory(project_id=project_id) as uow:
            replay = _recover(uow, command, InvalidatedRecommendation)
            if replay is not None:
                return replay
            current = _workflow(uow, project_id, recommendation_id)
            _require_expected_version(current, expected_version)
            resolved_evidence = resolve_current_graph(
                uow.evidence, current.recommendation.evidence
            )
            workflow = reconcile_approved_inputs(
                current,
                current_inputs=resolved_evidence.input_versions,
                current_evidence_graph_hash=resolved_evidence.graph_hash,
                change_reason=change_reason,
                actor_id=str(principal.identity_id),
                occurred_at=self._clock(),
            )
            cancelled = (
                uow.outbox.cancel_unpublished_for_recommendation(
                    project_id=project_id,
                    recommendation_id=recommendation_id,
                    reason=workflow.recommendation.status.value,
                )
                if workflow.recommendation.status
                in {RecommendationStatus.STALE, RecommendationStatus.EXPIRED}
                else ()
            )
            result = InvalidatedRecommendation(workflow, cancelled)
            stored = uow.recommendations.store_workflow(
                project_id=project_id,
                workflow=workflow,
                expected_version=expected_version,
                command=command,
                result=result,
            )
            uow.commit()
            return _stored_receipt(stored, InvalidatedRecommendation)

    def expire_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        reason: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[InvalidatedRecommendation]:
        _require_project_role(principal, project_id, allowed=_APPROVER_ROLES)
        command = _command_identity(
            operation=RecommendationCommandOperation.EXPIRE,
            principal=principal,
            project_id=project_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            values={"recommendation_id": recommendation_id, "reason": reason.strip()},
        )
        with self._unit_of_work_factory(project_id=project_id) as uow:
            replay = _recover(uow, command, InvalidatedRecommendation)
            if replay is not None:
                return replay
            current = _workflow(uow, project_id, recommendation_id)
            _require_expected_version(current, expected_version)
            workflow = expire_recommendation(
                current,
                expected_version=expected_version,
                actor_id=str(principal.identity_id),
                reason=reason,
                occurred_at=self._clock(),
            )
            cancelled = uow.outbox.cancel_unpublished_for_recommendation(
                project_id=project_id,
                recommendation_id=recommendation_id,
                reason=workflow.recommendation.status.value,
            )
            result = InvalidatedRecommendation(workflow, cancelled)
            stored = uow.recommendations.store_workflow(
                project_id=project_id,
                workflow=workflow,
                expected_version=expected_version,
                command=command,
                result=result,
            )
            uow.commit()
            return _stored_receipt(stored, InvalidatedRecommendation)

    def prepare_draft_action(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
        draft_id: UUID,
        change_reason: InputChangeReason,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[PreparedDraftAction]:
        _require_project_role(principal, project_id, allowed=_CONTRIBUTOR_ROLES)
        command = _command_identity(
            operation=RecommendationCommandOperation.PREPARE_DRAFT_ACTION,
            principal=principal,
            project_id=project_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            values={
                "recommendation_id": recommendation_id,
                "draft_id": draft_id,
                "change_reason": InputChangeReason(change_reason).value,
            },
        )
        with self._unit_of_work_factory(project_id=project_id) as uow:
            replay = _recover(uow, command, PreparedDraftAction)
            if replay is not None:
                replay.value.check.require_authorized()
                return replay
            stored = uow.prepare_draft_action(
                project_id=project_id,
                recommendation_id=recommendation_id,
                draft_id=draft_id,
                expected_recommendation_version=expected_version,
                occurred_at=self._clock(),
                actor_id=str(principal.identity_id),
                change_reason=change_reason,
                command=command,
            )
            uow.commit()
            receipt = _stored_receipt(stored, PreparedDraftAction)
        receipt.value.check.require_authorized()
        return receipt
