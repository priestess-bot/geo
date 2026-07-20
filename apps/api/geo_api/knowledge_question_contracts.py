"""Strict transport contracts for governed GEO QuestionSets."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QuestionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionDimensionRequest(QuestionContract):
    dimension_key: str | None = Field(default=None, min_length=1, max_length=200)
    turn_index: Literal[1, 2, 3] = 1
    parent_dimension_key: str | None = Field(default=None, min_length=1, max_length=200)
    persona: str = Field(min_length=1, max_length=300)
    scenario: str = Field(min_length=1, max_length=300)
    intent: str = Field(min_length=1, max_length=300)
    funnel: Literal["awareness", "consideration", "decision", "retention"]
    region: str = Field(min_length=1, max_length=300)
    language: str = Field(min_length=1, max_length=300)
    brand_scope: Literal["brand", "non_brand", "competitor"]
    platform: Literal[
        "chatgpt_search",
        "google_ai_overviews",
        "google_search",
        "perplexity",
        "gemini",
        "other",
    ]
    query_kind: Literal["recommendation", "comparison", "research", "support"]
    subject: str = Field(min_length=1, max_length=300)
    competitor_entity_id: UUID | None = None

    @model_validator(mode="after")
    def dimension_shape(self) -> "QuestionDimensionRequest":
        if (self.turn_index == 1) != (self.parent_dimension_key is None):
            raise ValueError("only first-turn dimensions omit a parent")
        if (self.brand_scope == "competitor") != (self.competitor_entity_id is not None):
            raise ValueError("competitor dimensions require exactly one competitor entity")
        return self


class CreateQuestionGenerationRequest(QuestionContract):
    configured_model: str = Field(
        default="deepseek-v4-flash", min_length=1, max_length=200
    )
    model_call_budget: int = Field(default=60, ge=1, le=1000)
    semantic_duplicate_threshold: float = Field(default=0.92, ge=0.8, le=1.0)
    fact_candidate_ids: list[UUID] = Field(min_length=1, max_length=500)
    graph_entity_ids: list[UUID] = Field(default_factory=list, max_length=500)
    dimensions: list[QuestionDimensionRequest] = Field(min_length=1, max_length=200)


class QuestionGenerationResponse(QuestionContract):
    job_id: UUID
    project_id: UUID
    campaign_id: UUID
    status: str
    input_hash: str
    dimension_count: int
    fact_input_count: int
    entity_input_count: int


class QuestionGenerationView(QuestionContract):
    job_id: UUID
    project_id: UUID
    campaign_id: UUID
    status: str
    input_hash: str
    error_code: str | None
    configured_model: str
    model_call_budget: int
    adapter_release: str
    semantic_duplicate_threshold: float
    artifact_uri: str | None
    artifact_hash: str | None
    dimension_count: int | None
    candidate_count: int | None
    supported_dimension_count: int | None
    possible_duplicate_count: int | None
    generated_at: datetime | None
    created_at: datetime


class QuestionCandidateView(QuestionContract):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    generated_by_job_id: UUID
    dimension_key: str
    variant_index: int
    turn_index: int
    parent_candidate_id: UUID | None
    query_text: str
    query_text_hash: str
    semantic_fingerprint: str
    dedup_status: Literal["unique", "possible_duplicate", "exact_duplicate"]
    nearest_candidate_id: UUID | None
    nearest_similarity: float | None
    workflow_status: Literal["pending_review", "approved", "rejected"]
    review_notes: str | None
    reviewed_at: datetime | None
    fact_source_ids: list[UUID]
    entity_source_ids: list[UUID]
    created_at: datetime


class ReviewQuestionCandidateRequest(QuestionContract):
    decision: Literal["approved", "rejected"]
    notes: str = Field(default="", max_length=2000)


class QuestionSetCreateRequest(QuestionContract):
    name: str = Field(min_length=1, max_length=300)
    generation_job_id: UUID
    candidate_ids: list[UUID] = Field(min_length=1, max_length=500)
    series_id: UUID | None = None
    previous_version_id: UUID | None = None


class QuestionSetItemView(QuestionContract):
    id: UUID
    ordinal: int
    question_candidate_id: UUID
    dimension_key: str
    query_text_snapshot: str
    query_text_hash: str
    query_kind_snapshot: str
    query_cluster_key: str
    source_lineage_hash: str


class QuestionSetView(QuestionContract):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    series_id: UUID
    previous_version_id: UUID | None
    version_number: int
    generated_by_job_id: UUID
    name: str
    status: Literal["draft", "approved", "frozen"]
    dimension_count: int
    covered_dimension_count: int
    possible_duplicate_count: int
    coverage_ratio: float
    duplicate_ratio: float
    content_hash: str | None
    created_at: datetime
    approved_at: datetime | None
    frozen_at: datetime | None
    items: list[QuestionSetItemView]
