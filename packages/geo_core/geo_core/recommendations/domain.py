"""Compatibility facade for the Recommendation pure domain.

The implementation is split by responsibility, but established imports from
``geo_core.recommendations.domain`` remain stable.
"""

from geo_core.recommendations.draft_operations import (
    mark_draft_started,
    prepare_draft_action,
)
from geo_core.recommendations.errors import (
    SOURCE_STALE_PROBLEM_CODE,
    RecommendationConflict,
    RecommendationRuleViolation,
    RecommendationSourceStale,
)
from geo_core.recommendations.evidence import (
    RecommendationEvidenceGraph,
    RecommendationInputVersion,
)
from geo_core.recommendations.lifecycle import (
    approve_and_create_draft,
    expire_recommendation,
    reconcile_approved_inputs,
    reject_recommendation,
    submit_recommendation,
)
from geo_core.recommendations.models import (
    ApprovalOutcome,
    DownstreamDraftKind,
    DownstreamDraftStatus,
    DraftActionCheck,
    InputChangeReason,
    LinkedDraft,
    Recommendation,
    RecommendationApproval,
    RecommendationStatus,
    RecommendationTransition,
    RecommendationType,
    RecommendationWorkflow,
)

__all__ = (
    "SOURCE_STALE_PROBLEM_CODE",
    "ApprovalOutcome",
    "DownstreamDraftKind",
    "DownstreamDraftStatus",
    "DraftActionCheck",
    "InputChangeReason",
    "LinkedDraft",
    "Recommendation",
    "RecommendationApproval",
    "RecommendationConflict",
    "RecommendationEvidenceGraph",
    "RecommendationInputVersion",
    "RecommendationRuleViolation",
    "RecommendationSourceStale",
    "RecommendationStatus",
    "RecommendationTransition",
    "RecommendationType",
    "RecommendationWorkflow",
    "approve_and_create_draft",
    "expire_recommendation",
    "mark_draft_started",
    "prepare_draft_action",
    "reconcile_approved_inputs",
    "reject_recommendation",
    "submit_recommendation",
)
