"""Shared command receipts, hashing, authorization, and adapter dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
from typing import Generic, TypeVar
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.recommendations.evidence import (
    RecommendationInputVersion,
    input_fingerprint,
)
from geo_core.recommendations.models import RecommendationWorkflow, normalise_idempotency_key
from geo_core.recommendations.ports import (
    CreatedDownstreamDraft,
    RecommendationCommandIdentity,
    RecommendationCommandOperation,
    RecommendationIdempotencyConflict,
    RecommendationReview,
    RecommendationUnitOfWork,
    RecommendationVersionConflict,
    StoredRecommendationCommand,
)


_ResultT = TypeVar("_ResultT")


class RecommendationApplicationError(RuntimeError):
    """Base error safe to translate at a future transport boundary."""


class RecommendationForbidden(RecommendationApplicationError):
    """The principal lacks the project role or approval separation required."""


class RecommendationNotFound(RecommendationApplicationError):
    """A project-scoped Recommendation is not visible to the principal."""


class RecommendationReviewRequired(RecommendationApplicationError):
    """Approval requires a review of the exact current Recommendation version."""


@dataclass(frozen=True)
class CommandReceipt(Generic[_ResultT]):
    value: _ResultT
    replayed: bool


@dataclass(frozen=True)
class ReviewedRecommendation:
    workflow: RecommendationWorkflow
    review: RecommendationReview


@dataclass(frozen=True)
class ApprovedRecommendation:
    workflow: RecommendationWorkflow
    downstream_draft: CreatedDownstreamDraft | None


@dataclass(frozen=True)
class InvalidatedRecommendation:
    workflow: RecommendationWorkflow
    cancelled_outbox_ids: tuple[UUID, ...]


def recover(
    uow: RecommendationUnitOfWork,
    command: RecommendationCommandIdentity,
    result_type: type[_ResultT],
) -> CommandReceipt[_ResultT] | None:
    existing = uow.recommendations.get_command(
        project_id=command.project_id,
        idempotency_key_hash=command.idempotency_key_hash,
    )
    if existing is None:
        return None
    if (
        existing.identity.operation != command.operation
        or existing.identity.request_hash != command.request_hash
    ):
        raise RecommendationIdempotencyConflict(
            "Recommendation idempotency key was reused for a different request"
        )
    if not isinstance(existing.result, result_type):
        raise RecommendationIdempotencyConflict("Recommendation command result type changed")
    return CommandReceipt(existing.result, replayed=True)


def stored_receipt(
    stored: StoredRecommendationCommand, result_type: type[_ResultT]
) -> CommandReceipt[_ResultT]:
    result = stored.record.result
    if not isinstance(result, result_type):
        raise TypeError("Recommendation repository returned an unexpected result")
    return CommandReceipt(result, stored.replayed)


def workflow(
    uow: RecommendationUnitOfWork, project_id: UUID, recommendation_id: UUID
) -> RecommendationWorkflow:
    value = uow.recommendations.get_workflow(
        project_id=project_id, recommendation_id=recommendation_id
    )
    if value is None:
        raise RecommendationNotFound("Recommendation does not exist in the project scope")
    return value


def require_expected_version(workflow: RecommendationWorkflow, expected_version: int) -> None:
    if workflow.recommendation.version != expected_version:
        raise RecommendationVersionConflict("Recommendation changed after it was read")


def require_project_role(
    principal: AccessPrincipal, project_id: UUID, *, allowed: frozenset[str]
) -> None:
    for membership in principal.memberships:
        if membership.project_id == project_id and membership.tenant_id == principal.tenant_id:
            if membership.role not in allowed:
                raise RecommendationForbidden(
                    "project role cannot perform this Recommendation action"
                )
            return
    raise RecommendationNotFound("Recommendation project is outside the authenticated scope")


def command_identity(
    *,
    operation: RecommendationCommandOperation,
    principal: AccessPrincipal,
    project_id: UUID,
    expected_version: int,
    idempotency_key: str,
    values: Mapping[str, object],
) -> RecommendationCommandIdentity:
    key = normalise_idempotency_key(idempotency_key)
    key_hash = sha256(key.encode("utf-8")).hexdigest()
    payload = {
        "operation": operation.value,
        "actor_id": str(principal.identity_id),
        "project_id": str(project_id),
        "expected_version": expected_version,
        "values": _canonical_value(values),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return RecommendationCommandIdentity(
        project_id=project_id,
        idempotency_key_hash=key_hash,
        operation=operation,
        request_hash=sha256(encoded).hexdigest(),
    )


def input_values(values: tuple[RecommendationInputVersion, ...]) -> dict[str, object]:
    return {
        "fingerprint": input_fingerprint(values),
        "inputs": [
            {
                "kind": item.kind.value,
                "resource_id": item.resource_id,
                "version": item.version,
                "sha256": item.sha256,
            }
            for item in sorted(values, key=lambda item: item.identity)
        ],
    }


def _canonical_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value
