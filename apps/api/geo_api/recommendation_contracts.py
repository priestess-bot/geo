"""Strict Internal API contracts for governed Recommendations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


RecommendationTypeValue = Literal[
    "hard_blocker",
    "gap",
    "experiment",
    "optional",
    "no_change",
    "insufficient_evidence",
]
RecommendationStatusValue = Literal[
    "draft", "in_review", "approved", "rejected", "stale", "expired"
]
DraftKindValue = Literal["experiment_plan", "question_set", "content_brief", "sampling_plan"]
DraftStatusValue = Literal["draft", "started", "blocked_source_stale", "blocked_source_expired"]
InputKindValue = Literal[
    "observation",
    "comparison",
    "fact",
    "rule_version",
    "prompt_release",
    "model_call",
    "method_version",
    "content_version",
    "question_version",
    "surface_release",
    "attribution_availability",
]
ChangeReasonValue = Literal[
    "fact_retired",
    "data_refreshed",
    "alert_resolved",
    "method_replaced",
    "content_version_changed",
    "prompt_release_changed",
    "input_added_or_removed",
]
EvidenceClassValue = Literal["real_observation", "official_projection", "synthetic"]
MetricComparisonConclusionValue = Literal[
    "win", "equivalent", "loss", "inconclusive", "insufficient_evidence"
]
RecommendationRuleKindValue = Literal[
    "threshold",
    "baseline_delta",
    "negative_question",
    "completion_freshness",
    "model_drift",
    "source_drift",
    "connector_failure",
]
RecommendationRuleSeverityValue = Literal["info", "warning", "critical"]
RecommendationRuleTriggerStatusValue = Literal[
    "not_triggered", "open", "acknowledged", "suppressed", "resolved"
]
EvidenceSelectorKindValue = Literal[
    "observation",
    "metric_comparison",
    "fact",
    "rule",
    "prompt_release",
    "model_call",
    "content",
    "question",
    "surface",
    "attribution",
]
GenerationJobStatusValue = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "rejected_stale_input",
]


class RecommendationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScopeContract(RecommendationContract):
    project_id: UUID
    applicable_version: str = Field(min_length=1, max_length=200)
    campaign_id: UUID | None = None
    question_or_cluster_ref: str | None = Field(default=None, max_length=500)
    surface_ref: str | None = Field(default=None, max_length=500)
    content_asset_ref: str | None = Field(default=None, max_length=500)
    url_ref: str | None = Field(default=None, max_length=2000)


class ScopeSelectionContract(RecommendationContract):
    applicable_version: str = Field(min_length=1, max_length=200)
    campaign_id: UUID | None = None
    question_or_cluster_ref: str | None = Field(default=None, max_length=500)
    surface_ref: str | None = Field(default=None, max_length=500)
    content_asset_ref: str | None = Field(default=None, max_length=500)
    url_ref: str | None = Field(default=None, max_length=2000)


class DecisionContract(RecommendationContract):
    impact_chain: list[str] = Field(min_length=1, max_length=50)
    risk: str = Field(min_length=1, max_length=1000)
    effort: str = Field(min_length=1, max_length=1000)
    business_value: str = Field(min_length=1, max_length=5000)
    confidence: Decimal = Field(ge=0, le=1)
    counterevidence: list[str] = Field(max_length=100)
    validation_plan: list[str] = Field(min_length=1, max_length=100)
    stale_conditions: list[str] = Field(min_length=1, max_length=100)


class VersionedRefContract(RecommendationContract):
    project_id: UUID
    resource_id: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: dict[str, str] = Field(min_length=1, max_length=50)
    valid: bool = True


class ObservationRefContract(VersionedRefContract):
    capture_method: str = Field(min_length=1, max_length=100)
    evidence_class: EvidenceClassValue
    question_resource_id: str = Field(min_length=1, max_length=500)
    surface_resource_id: str = Field(min_length=1, max_length=500)
    eligible: bool


class MetricComparisonRefContract(VersionedRefContract):
    observation_resource_ids: list[str] = Field(min_length=1, max_length=10_000)
    method_version: str = Field(min_length=1, max_length=200)
    method_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sufficient_evidence: bool
    conclusion: MetricComparisonConclusionValue = "inconclusive"


class FactRefContract(VersionedRefContract):
    approved: bool
    retired: bool


class RuleRefContract(VersionedRefContract):
    active: bool
    rule_kind: RecommendationRuleKindValue = "threshold"
    severity: RecommendationRuleSeverityValue = "info"
    trigger_status: RecommendationRuleTriggerStatusValue = "not_triggered"


class PromptReleaseRefContract(VersionedRefContract):
    approved: bool
    frozen: bool


class ModelCallRefContract(VersionedRefContract):
    prompt_release_resource_id: str = Field(min_length=1, max_length=500)
    model_identity: str = Field(min_length=1, max_length=500)
    succeeded: bool


class ContentRefContract(VersionedRefContract):
    current: bool


class QuestionRefContract(VersionedRefContract):
    active: bool


class SurfaceRefContract(VersionedRefContract):
    active: bool


class AttributionRefContract(VersionedRefContract):
    available: bool
    reason: str = Field(min_length=1, max_length=500)


class EvidenceGraphContract(RecommendationContract):
    scope: ScopeContract
    decision: DecisionContract
    observations: list[ObservationRefContract] = Field(max_length=100_000)
    metric_comparisons: list[MetricComparisonRefContract] = Field(max_length=100_000)
    facts: list[FactRefContract] = Field(max_length=100_000)
    rules: list[RuleRefContract] = Field(max_length=100_000)
    prompt_releases: list[PromptReleaseRefContract] = Field(max_length=10_000)
    model_calls: list[ModelCallRefContract] = Field(max_length=100_000)
    contents: list[ContentRefContract] = Field(max_length=100_000)
    questions: list[QuestionRefContract] = Field(max_length=100_000)
    surfaces: list[SurfaceRefContract] = Field(max_length=10_000)
    attributions: list[AttributionRefContract] = Field(max_length=10_000)


class InputVersionContract(RecommendationContract):
    kind: InputKindValue
    resource_id: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceSelectorContract(RecommendationContract):
    kind: EvidenceSelectorKindValue
    resource_id: str = Field(min_length=1, max_length=500)


class CreateRecommendationRequest(RecommendationContract):
    recommendation_type: RecommendationTypeValue
    scope: ScopeSelectionContract
    decision: DecisionContract
    evidence_selectors: list[EvidenceSelectorContract] = Field(min_length=1, max_length=100)
    proposed_draft_kind: DraftKindValue | None
    valid_until: datetime
    expected_version: int = Field(ge=0)


class VersionedRecommendationRequest(RecommendationContract):
    expected_version: int = Field(ge=1)


class ReviewRecommendationRequest(VersionedRecommendationRequest):
    notes: str = Field(min_length=1, max_length=20_000)


class ApproveRecommendationRequest(VersionedRecommendationRequest):
    pass


class ReasonedRecommendationRequest(VersionedRecommendationRequest):
    reason: str = Field(min_length=1, max_length=5000)


class ReconcileRecommendationRequest(VersionedRecommendationRequest):
    change_reason: ChangeReasonValue


class PrepareDraftActionRequest(ReconcileRecommendationRequest):
    pass


class GenerationModelSelectorContract(RecommendationContract):
    runtime_selection_id: UUID
    search_mode: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_.-]{0,63}$")


class EnqueueRecommendationGenerationRequest(RecommendationContract):
    scope: ScopeSelectionContract
    evidence_selectors: list[EvidenceSelectorContract] = Field(min_length=1, max_length=100)
    prompt_binding_id: UUID
    model: GenerationModelSelectorContract
    valid_until: datetime
    minimum_real_observations: int = Field(default=3, ge=1, le=1000)
    arbiter_prompt_binding_id: UUID | None = None
    arbiter_model: GenerationModelSelectorContract | None = None
    recovery_of_attempt_id: UUID | None = None
    dify_reconciliation_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_dify_recovery_pair(self) -> EnqueueRecommendationGenerationRequest:
        if (self.recovery_of_attempt_id is None) != (self.dify_reconciliation_token is None):
            raise ValueError(
                "recovery_of_attempt_id and dify_reconciliation_token must be supplied together"
            )
        return self


class CancelRecommendationGenerationRequest(RecommendationContract):
    expected_version: int = Field(ge=1)


class GenerationPromptLineageResponse(RecommendationContract):
    binding_id: UUID
    binding_version: int
    frozen_state_id: UUID
    frozen_state_version: int
    release_id: UUID
    release_version: int
    release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    program_kind: Literal["recommendation", "arbiter"]
    purpose: str


class GenerationModelLineageResponse(RecommendationContract):
    runtime_selection_id: UUID
    runtime_manifest_id: UUID
    runtime_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_option_id: UUID
    runtime_option_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    adapter_release_id: str
    adapter_release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_release_id: str
    model_release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    configured_model: str
    policy_version_id: UUID | None
    policy_version_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    capture_method: Literal["provider_api", "proxy_grounded_api"]
    search_mode: str | None


class RecommendationGenerationJobResponse(RecommendationContract):
    id: UUID
    project_id: UUID
    status: GenerationJobStatusValue
    version: int
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    consumed_model_calls: int
    maximum_model_calls: int
    cancel_requested: bool
    error_code: str | None
    valid_until: datetime
    prompt: GenerationPromptLineageResponse
    model: GenerationModelLineageResponse
    arbiter_prompt: GenerationPromptLineageResponse | None
    arbiter_model: GenerationModelLineageResponse | None
    result: RecommendationResponse | None
    model_call_ids: list[UUID]
    insufficient_reasons: list[str]
    workflow_attempt_ids: list[UUID] = Field(default_factory=list)
    replayed: bool = False


class ApprovalResponse(RecommendationContract):
    id: UUID
    approved_by: str
    approved_at: datetime
    recommendation_version: int
    frozen_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_evidence_graph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    valid_until: datetime


class RecommendationResponse(RecommendationContract):
    id: UUID
    project_id: UUID
    recommendation_type: RecommendationTypeValue
    status: RecommendationStatusValue
    version: int = Field(ge=1)
    proposed_draft_kind: DraftKindValue | None
    valid_until: datetime
    created_by: str
    created_at: datetime
    updated_at: datetime
    evidence: EvidenceGraphContract
    evidence_graph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_versions: list[InputVersionContract]
    approval: ApprovalResponse | None


class LinkedDraftResponse(RecommendationContract):
    id: UUID
    recommendation_id: UUID
    recommendation_version: int
    approval_id: UUID
    kind: DraftKindValue
    status: DraftStatusValue
    frozen_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_evidence_graph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    started_at: datetime | None
    blocked_at: datetime | None
    blocked_reason: str | None
    draft_only: Literal[True] = True
    enqueued: Literal[False] = False
    executed: Literal[False] = False
    published: Literal[False] = False


class RecommendationWorkflowResponse(RecommendationContract):
    recommendation: RecommendationResponse
    drafts: list[LinkedDraftResponse]


class RecommendationCommandResponse(RecommendationWorkflowResponse):
    replayed: bool


class RecommendationReviewResponse(RecommendationContract):
    id: UUID
    recommendation_id: UUID
    recommendation_version: int
    evidence_graph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_by: UUID
    notes: str
    reviewed_at: datetime


class ReviewedRecommendationResponse(RecommendationWorkflowResponse):
    review: RecommendationReviewResponse
    replayed: bool


class ApprovedRecommendationResponse(RecommendationWorkflowResponse):
    downstream_draft: LinkedDraftResponse | None
    action_boundary: Literal["draft_only_unstarted"] = "draft_only_unstarted"
    replayed: bool


class InvalidatedRecommendationResponse(RecommendationWorkflowResponse):
    cancelled_outbox_ids: list[UUID]
    replayed: bool


class PreparedDraftActionResponse(RecommendationWorkflowResponse):
    draft: LinkedDraftResponse
    authorized: Literal[True]
    action_boundary: Literal["source_checked_draft_only"] = "source_checked_draft_only"
    replayed: bool


class RecommendationPageResponse(RecommendationContract):
    items: list[RecommendationWorkflowResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
