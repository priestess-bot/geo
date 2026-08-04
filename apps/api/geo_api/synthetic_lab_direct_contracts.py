"""Strict Internal API contracts for direct Synthetic Lab generation."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from geo_api.synthetic_lab_contracts import (
    Channel,
    Sha256,
    SyntheticBoundaryResponse,
    SyntheticContract,
    SyntheticMutationResponse,
    SyntheticPageResponse,
)


class EnqueueDirectGenerationRequest(SyntheticContract):
    channel: Channel
    subject_entity_id: UUID
    generation_goal: str = Field(min_length=1, max_length=4000)
    runtime_selection_id: UUID
    channel_style_version_id: UUID
    channel_style_hash: Sha256
    knowledge_snapshot_hash: Sha256
    style_pass_threshold: float = Field(default=4.2, ge=0, le=5)
    include_competitor_context: bool = False


class CreateChannelStyleRequest(SyntheticContract):
    expected_current_version: int = Field(ge=0)
    directive: str = Field(min_length=1, max_length=16_000)


class ChannelStyleResponse(SyntheticMutationResponse):
    id: UUID
    project_id: UUID
    style_id: UUID
    version_number: int = Field(ge=1)
    previous_version_id: UUID | None = None
    channel: Channel
    locale: Literal["en-AU"]
    directive: str = Field(min_length=1, max_length=16_000)
    provenance: Literal["manual_initial", "manual_edit"]
    calibration_status: Literal["pending_sample_calibration", "sample_calibrated"]
    style_hash: Sha256


class DirectKnowledgeItemResponse(SyntheticContract):
    evidence_id: UUID
    kind: Literal["approved_fact", "citation"]
    subject_entity_id: UUID
    subject_name: str
    summary: str
    snapshot_hash: Sha256
    source_title: str | None = None
    source_url: str | None = None
    trace_href: str
    matched: bool = False
    conflicting: bool = False


class DirectGenerationSubjectResponse(SyntheticContract):
    id: UUID
    name: str
    canonical_url: str | None = None
    knowledge_snapshot_hash: Sha256 | None = None
    knowledge_items: list[DirectKnowledgeItemResponse]
    competitor_knowledge_snapshot_hash: Sha256 | None = None
    competitor_knowledge_items: list[DirectKnowledgeItemResponse] = Field(default_factory=list)


class DirectGenerationOptionsResponse(SyntheticBoundaryResponse):
    subjects: list[DirectGenerationSubjectResponse]
    channel_styles: list[ChannelStyleResponse]
    has_competitor_knowledge: bool


class SyntheticClaimAssessmentResponse(SyntheticContract):
    claim_hash: Sha256
    status: Literal[
        "current_approved",
        "derived_or_unknown",
        "explicit_conflict",
        "subject_mixup",
    ]
    fact_id: UUID | None = None
    fact_hash: Sha256 | None = None
    expected_subject_id: UUID | None = None
    observed_subject_id: UUID | None = None
    output_annotation: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class SyntheticCandidateEvaluationResponse(SyntheticContract):
    id: UUID
    candidate_id: UUID
    candidate_output_hash: Sha256
    style_score: float = Field(ge=0, le=5)
    style_passed: bool
    disposition: Literal["pass", "warning", "revise"]
    correctable_issue_codes: list[str]
    soft_issue_codes: list[str]
    warning_codes: list[str]
    claim_assessments: list[SyntheticClaimAssessmentResponse]
    provider: str
    configured_model: str
    evidence_artifact_hash: Sha256


class SyntheticCandidateRevisionResponse(SyntheticContract):
    id: UUID
    round_number: int = Field(ge=1, le=2)
    parent_candidate_id: UUID
    parent_output_hash: Sha256
    revised_candidate_id: UUID
    revised_output_hash: Sha256
    issue_codes: list[str]
    provider: str
    configured_model: str


class SyntheticGenerationBatchResponse(SyntheticContract):
    id: UUID
    batch_number: int = Field(ge=1, le=2)
    kind: Literal["initial", "regenerated"]
    scenario_mode: Literal["autonomous_scenario", "guided_scenario"]
    candidate_count: int = Field(ge=1)
    provider: str
    configured_model: str


class SyntheticReviewResultResponse(SyntheticBoundaryResponse):
    job_id: UUID
    project_id: UUID
    review_run_id: UUID
    run_origin: Literal["direct", "regression"] = "regression"
    input_snapshot_id: UUID | None = None
    review_suite_version_id: UUID | None = None
    review_case_id: UUID | None = None
    scenario_id: UUID
    case_key: str
    channel: Channel
    scenario_mode: Literal["autonomous_scenario", "guided_scenario"]
    competitor_scenario: bool
    style_pass_threshold: float = Field(ge=0, le=5)
    runtime_selection_id: UUID
    profile_version_id: UUID
    fact_snapshot_id: UUID
    generation_goal: str | None = None
    channel_style_version_id: UUID | None = None
    channel_style_version_number: int | None = Field(default=None, ge=1)
    channel_style_hash: Sha256 | None = None
    knowledge_snapshot_hash: Sha256 | None = None
    knowledge_context_items: list[DirectKnowledgeItemResponse] = Field(default_factory=list)
    final_text: str | None = Field(default=None, max_length=100_000)
    status: Literal["passed", "completed_with_warning", "failed"]
    warning_codes: list[str]
    failure_code: str | None = None
    resolution_candidate_id: UUID
    result_hash: Sha256
    batches: list[SyntheticGenerationBatchResponse]
    evaluations: list[SyntheticCandidateEvaluationResponse]
    revisions: list[SyntheticCandidateRevisionResponse]
    model_call_ids: list[UUID]
    workflow_attempt_ids: list[UUID]


ChannelStylePageResponse = SyntheticPageResponse[ChannelStyleResponse]
