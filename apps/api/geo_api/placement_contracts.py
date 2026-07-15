"""Strong public contracts for the internal GEO placement API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PlacementContract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class CampaignCreate(PlacementContract):
    market_profile_id: UUID
    primary_product_entity_id: UUID
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(default="recommendation_influence", min_length=1, max_length=200)
    actor_id: UUID
    destination_ids: list[UUID] = Field(min_length=1)
    opportunity_rationale: str = Field(min_length=1, max_length=2000)


class CampaignView(PlacementContract):
    id: UUID
    project_id: UUID
    market_profile_id: UUID
    primary_product_entity_id: UUID
    name: str
    objective: str
    status: str


class OpportunityView(PlacementContract):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    destination_id: UUID
    opportunity_ref: str
    rationale: str
    status: str


class CampaignCreated(PlacementContract):
    campaign: CampaignView
    opportunities: list[OpportunityView]


class MonitoringQueryCreate(PlacementContract):
    market_profile_id: UUID
    query_text: str = Field(min_length=1, max_length=2000)
    query_kind: Literal["recommendation", "comparison", "research", "support"]
    locale: str = Field(min_length=2, max_length=32)


class MonitoringQueryView(MonitoringQueryCreate):
    id: UUID
    project_id: UUID
    status: str


class DestinationCreate(PlacementContract):
    publication_channel: Literal[
        "owned_site", "productreview", "youtube", "reddit", "amazon", "ozbargain",
        "tiktok", "instagram", "quora", "other"
    ]
    destination_key: str = Field(min_length=1, max_length=500)
    operation_mode: Literal["manual", "assisted", "api"] = "manual"
    destination_account_id: str | None = Field(default=None, max_length=500)
    canonical_url: str | None = Field(default=None, max_length=2000)


class DestinationView(DestinationCreate):
    id: UUID
    project_id: UUID
    policy_status: str


class ConsumerExperienceInput(PlacementContract):
    description: str = Field(min_length=1, max_length=10000)
    source: str = Field(min_length=1, max_length=2000)
    usage_rights: str = Field(min_length=1, max_length=200)
    disclosure: str = Field(min_length=1, max_length=2000)


class BriefVersionCreate(PlacementContract):
    primary_brand_entity_id: UUID
    goals: dict[str, object]
    constraints: dict[str, object] = Field(default_factory=dict)
    compared_entity_ids: list[UUID] = Field(default_factory=list)
    allowed_subject_entity_ids: list[UUID] = Field(default_factory=list)
    actor_id: UUID
    base_version_id: UUID | None = None
    consumer_experience: ConsumerExperienceInput | None = None
    authenticity_risks: list[Literal[
        "synthetic_testimonial", "fake_persona", "unsupported_first_person_experience",
        "hidden_commercial_relationship"
    ]] = Field(default_factory=list)


class BriefVersionView(PlacementContract):
    id: UUID
    project_id: UUID
    brief_id: UUID
    version_number: int
    base_version_id: UUID | None
    goals: dict[str, object]
    constraints: dict[str, object]
    content_hash: str


class EvidenceAttemptView(PlacementContract):
    id: UUID
    project_id: UUID
    brief_version_id: UUID
    attempt_number: int
    status: str
    pack_hash: str | None
    failure_reason: str | None


class AsyncResourceCreated(PlacementContract):
    resource: EvidenceAttemptView
    job_id: UUID
    status: Literal["queued", "running"]
    status_url: str


class PromptSkillCreate(PlacementContract):
    skill_key: str = Field(min_length=1, max_length=200)


class PromptSkillView(PlacementContract):
    id: UUID
    project_id: UUID
    skill_key: str
    status: str


class PromptReleaseCreate(PlacementContract):
    source: str = Field(min_length=1, max_length=100000)
    actor_id: UUID
    output_schema: dict[str, object]


class PromptReleaseView(PlacementContract):
    id: UUID
    project_id: UUID
    skill_version_id: UUID
    release_number: int
    release_hash: str


class PromptBundleCreate(PlacementContract):
    evidence_pack_attempt_id: UUID
    template_release_id: UUID
    variables: dict[str, object]
    model_policy_hash: str = Field(pattern="^[0-9a-f]{64}$")


class PromptBundleView(PlacementContract):
    id: UUID
    project_id: UUID
    brief_version_id: UUID
    evidence_pack_attempt_id: UUID
    template_release_id: UUID
    bundle_hash: str
    storage_uri: str


class GenerationCreate(PlacementContract):
    configured_model: str = Field(default="deepseek-chat", min_length=1, max_length=200)
    model_call_budget: int = Field(default=2, ge=1, le=5)


class PackageVersionView(PlacementContract):
    id: UUID
    project_id: UUID
    package_id: UUID
    prompt_bundle_id: UUID
    version_number: int
    base_version_id: UUID | None
    workflow_status: str
    content_json: dict[str, object]
    rendered_text: str
    content_hash: str
    edited_by: UUID | None
    edit_reason: str | None


class PackageEdit(PlacementContract):
    base_version_id: UUID
    base_content_hash: str = Field(pattern="^[0-9a-f]{64}$")
    content_json: dict[str, object]
    rendered_text: str = Field(min_length=1)
    edited_by: UUID
    reason: str = Field(min_length=1, max_length=2000)


class ClaimView(PlacementContract):
    id: UUID
    project_id: UUID
    package_version_id: UUID
    claim_text: str
    claim_kind: str
    support_status: str
    evidence_item_ids: list[UUID]


class ReviewCreate(PlacementContract):
    submitted_for_review_by: UUID
    reviewer_id: UUID
    decision: Literal["approved", "needs_revision", "rejected", "blocked"]
    claim_inventory_complete: bool
    extracted_claim_support_confirmed: bool
    score: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=10000)


class ReviewView(ReviewCreate):
    id: UUID
    project_id: UUID
    package_version_id: UUID


class ExportView(PlacementContract):
    package_version_id: UUID
    content_hash: str
    exported_at: datetime


class PublicationCreate(PlacementContract):
    destination_id: UUID
    requested_by: UUID
    publication_attempt: int = Field(default=1, ge=1)


class PublicationView(PlacementContract):
    id: UUID
    project_id: UUID
    package_version_id: UUID
    destination_id: UUID
    publication_channel: str
    destination_key: str
    publication_attempt: int
    idempotency_key: str
    status: str


class SubmissionCreate(PlacementContract):
    submitted_url: str | None = Field(default=None, max_length=2000)
    provider_submission_id: str | None = Field(default=None, max_length=500)


class SubmissionView(SubmissionCreate):
    id: UUID
    project_id: UUID
    publication_request_id: UUID
    status: str


class MeasurementCreate(PlacementContract):
    monitoring_query_id: UUID
    measured_at: datetime
    citation_present: bool
    recommendation_position: int | None = Field(default=None, ge=1)
    result_snapshot_uri: str = Field(min_length=1, max_length=2000)
    metrics: dict[str, object] = Field(default_factory=dict)


class MeasurementView(MeasurementCreate):
    id: UUID
    project_id: UUID
    submission_id: UUID
