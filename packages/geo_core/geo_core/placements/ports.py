"""Ports owned by the placement application layer."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from geo_core.placements.domain import (
    BriefVersion,
    Campaign,
    Claim,
    Destination,
    DestinationPolicyVersion,
    EvidencePackAttempt,
    ExportReceipt,
    JobReference,
    Measurement,
    MeasurementCollectionTask,
    MonitoringQuery,
    Opportunity,
    PackageVersion,
    PromptBundleView,
    PromptReleaseView,
    PromptSkill,
    PublicationRequest,
    Review,
    ReviewSubmission,
    Submission,
)
from geo_core.prompts.domain import SkillVersion, TemplateRelease


@dataclass(frozen=True)
class GenerationClaim:
    job_id: UUID
    project_id: UUID
    lease_token: UUID
    fencing_generation: int
    prompt_bundle_id: UUID
    prompt_bundle_hash: str
    system_prompt: str
    rendered_prompt: str
    configured_model: str
    model_call_budget: int
    package_id: UUID
    next_version_number: int
    base_version_id: UUID | None
    evidence_item_ids: tuple[UUID, ...]
    public_citation_item_ids: tuple[UUID, ...]
    output_schema: Mapping[str, object]


@dataclass(frozen=True)
class GeneratedClaim:
    text: str
    kind: str
    support_status: str
    evidence_item_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class GeneratedPlacement:
    content_json: Mapping[str, object]
    rendered_text: str
    claims: tuple[GeneratedClaim, ...]
    internal_evidence_refs: tuple[UUID, ...]
    public_citation_refs: tuple[UUID, ...]


class PlacementRepository(Protocol):
    def create_campaign(
        self,
        *,
        project_id: UUID,
        market_profile_id: UUID,
        primary_product_entity_id: UUID,
        name: str,
        objective: str,
        actor_id: UUID,
    ) -> Campaign: ...

    def list_campaigns(self, *, project_id: UUID) -> tuple[Campaign, ...]: ...
    def get_campaign(self, *, project_id: UUID, campaign_id: UUID) -> Campaign | None: ...

    def create_monitoring_query(
        self,
        *,
        campaign_id: UUID,
        project_id: UUID,
        market_profile_id: UUID,
        query_text: str,
        query_kind: str,
        locale: str,
    ) -> MonitoringQuery: ...

    def list_monitoring_queries(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[MonitoringQuery, ...]: ...

    def create_destination(
        self,
        *,
        project_id: UUID,
        publication_channel: str,
        destination_key: str,
        operation_mode: str,
        destination_account_id: str | None,
        canonical_url: str,
        canonical_host: str,
        allowed_hosts: tuple[str, ...],
    ) -> Destination: ...

    def list_destinations(self, *, project_id: UUID) -> tuple[Destination, ...]: ...

    def review_destination_policy(self, **values: object) -> DestinationPolicyVersion: ...

    def list_destination_policies(
        self, *, project_id: UUID, destination_id: UUID
    ) -> tuple[DestinationPolicyVersion, ...]: ...

    def transition_opportunity(
        self, *, project_id: UUID, opportunity_id: UUID, command: str, reason: str | None
    ) -> Opportunity: ...

    def create_opportunities(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        destination_ids: tuple[UUID, ...],
        rationale: str,
    ) -> tuple[Opportunity, ...]: ...

    def list_opportunities(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[Opportunity, ...]: ...

    def create_brief_version(
        self,
        *,
        project_id: UUID,
        opportunity_id: UUID,
        primary_brand_entity_id: UUID,
        goals: Mapping[str, object],
        constraints: Mapping[str, object],
        compared_entity_ids: tuple[UUID, ...],
        allowed_subject_entity_ids: tuple[UUID, ...],
        actor_id: UUID,
        base_version_id: UUID | None,
        content_hash: str,
    ) -> BriefVersion: ...

    def list_brief_versions(
        self, *, project_id: UUID, opportunity_id: UUID
    ) -> tuple[BriefVersion, ...]: ...

    def create_evidence_attempt(
        self, *, project_id: UUID, brief_version_id: UUID, idempotency_key: str
    ) -> tuple[EvidencePackAttempt, JobReference]: ...

    def list_evidence_attempts(
        self, *, project_id: UUID, brief_version_id: UUID
    ) -> tuple[EvidencePackAttempt, ...]: ...

    def get_evidence_attempt(
        self, *, project_id: UUID, attempt_id: UUID
    ) -> EvidencePackAttempt | None: ...

    def list_evidence_attempt_items(
        self, *, project_id: UUID, attempt_id: UUID
    ) -> tuple[Mapping[str, object], ...]: ...

    def create_prompt_skill(self, *, project_id: UUID, skill_key: str) -> PromptSkill: ...

    def create_skill_version(
        self, *, project_id: UUID, skill_id: UUID, source: str, actor_id: UUID
    ) -> SkillVersion: ...

    def create_template_release(
        self,
        *,
        project_id: UUID,
        skill_version_id: UUID,
        template: TemplateRelease,
        source_text: str,
        system_template: str,
        output_schema: Mapping[str, object],
        client_variable_names: tuple[str, ...],
    ) -> PromptReleaseView: ...

    def get_template_release(
        self, *, project_id: UUID, release_id: UUID
    ) -> TemplateRelease | None: ...

    def list_prompt_skills(self, *, project_id: UUID) -> tuple[PromptSkill, ...]: ...
    def list_prompt_releases(
        self, *, project_id: UUID, skill_id: UUID
    ) -> tuple[PromptReleaseView, ...]: ...
    def list_prompt_bundles(
        self, *, project_id: UUID, brief_version_id: UUID
    ) -> tuple[PromptBundleView, ...]: ...

    def get_prompt_bundle(
        self, *, project_id: UUID, bundle_id: UUID
    ) -> Mapping[str, object] | None: ...

    def select_prompt_release(self, **values: object) -> Mapping[str, object]: ...

    def list_prompt_release_selections(
        self, *, project_id: UUID
    ) -> tuple[Mapping[str, object], ...]: ...

    def install_default_prompt_catalog(
        self, **values: object
    ) -> tuple[Mapping[str, object], ...]: ...

    def create_prompt_bundle(
        self,
        *,
        project_id: UUID,
        brief_version_id: UUID,
        evidence_pack_attempt_id: UUID,
        release_id: UUID,
        variables: Mapping[str, object],
        model_policy_hash: str,
    ) -> PromptBundleView: ...

    def enqueue_generation(
        self,
        *,
        project_id: UUID,
        prompt_bundle_id: UUID,
        configured_model: str,
        model_call_budget: int,
        idempotency_key: str,
        requested_by: UUID,
    ) -> JobReference: ...

    def list_package_versions(
        self, *, project_id: UUID, opportunity_id: UUID
    ) -> tuple[PackageVersion, ...]: ...

    def get_package_version(
        self, *, project_id: UUID, version_id: UUID
    ) -> PackageVersion | None: ...

    def save_edited_version(
        self,
        *,
        version: PackageVersion,
        superseded_version_id: UUID,
        claims: tuple[GeneratedClaim, ...],
    ) -> PackageVersion: ...

    def list_claims(self, *, project_id: UUID, version_id: UUID) -> tuple[Claim, ...]: ...
    def submit_for_review(
        self, *, project_id: UUID, version_id: UUID, submitted_by: UUID
    ) -> ReviewSubmission: ...
    def get_review_submission(
        self, *, project_id: UUID, version_id: UUID
    ) -> ReviewSubmission | None: ...
    def save_review(self, *, review: Review) -> Review: ...

    def list_reviews(self, *, project_id: UUID, version_id: UUID) -> tuple[Review, ...]: ...

    def export_package(
        self,
        *,
        project_id: UUID,
        version_id: UUID,
        exported_at: datetime,
        requested_by: UUID,
    ) -> ExportReceipt: ...

    def list_exports(self, *, project_id: UUID, version_id: UUID) -> tuple[ExportReceipt, ...]: ...

    def create_publication_request(
        self,
        *,
        project_id: UUID,
        version_id: UUID,
        destination_id: UUID,
        requested_by: UUID,
        publication_attempt: int,
        idempotency_key: str,
        restricted_policy_acknowledged: bool,
        policy_basis: str | None,
    ) -> PublicationRequest: ...

    def create_submission(
        self,
        *,
        project_id: UUID,
        publication_request_id: UUID,
        submitted_url: str | None,
        provider_submission_id: str | None,
        idempotency_key: str,
        payload_hash: str,
        submitted_by: UUID,
    ) -> Submission: ...

    def list_publication_requests(
        self, *, project_id: UUID, version_id: UUID
    ) -> tuple[PublicationRequest, ...]: ...

    def list_submissions(
        self, *, project_id: UUID, publication_request_id: UUID
    ) -> tuple[Submission, ...]: ...

    def get_submission(self, *, project_id: UUID, submission_id: UUID) -> Submission | None: ...

    def backfill_submission_url(
        self, *, project_id: UUID, submission_id: UUID, submitted_url: str, actor_id: UUID
    ) -> Submission: ...

    def transition_submission(self, **values: object) -> Submission: ...

    def transition_publication(self, **values: object) -> PublicationRequest: ...

    def enqueue_verification(
        self, *, project_id: UUID, submission_id: UUID, idempotency_key: str
    ) -> JobReference: ...

    def record_measurement(
        self,
        *,
        project_id: UUID,
        submission_id: UUID,
        monitoring_query_id: UUID,
        measured_at: datetime,
        citation_present: bool,
        recommendation_position: int | None,
        result_snapshot_uri: str,
        metrics: Mapping[str, object],
    ) -> Measurement: ...

    def list_measurements(
        self, *, project_id: UUID, submission_id: UUID
    ) -> tuple[Measurement, ...]: ...

    def list_measurement_collection_tasks(
        self, *, project_id: UUID, submission_id: UUID | None, status: str | None
    ) -> tuple[MeasurementCollectionTask, ...]: ...

    def complete_measurement_collection_task(
        self, *, project_id: UUID, task_id: UUID, actor_id: UUID
    ) -> MeasurementCollectionTask: ...

    def cancel_measurement_collection_task(
        self, *, project_id: UUID, task_id: UUID, actor_id: UUID, reason: str
    ) -> MeasurementCollectionTask: ...

    def cancel_job(self, *, project_id: UUID, job_id: UUID, actor_id: UUID) -> JobReference: ...

    def retry_job_now(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
    ) -> JobReference: ...

    def replay_job(
        self,
        *,
        project_id: UUID,
        source_job_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
    ) -> JobReference: ...

    def list_job_events(
        self, *, project_id: UUID, job_id: UUID
    ) -> tuple[Mapping[str, object], ...]: ...


class PlacementUnitOfWork(Protocol):
    placements: PlacementRepository

    def __enter__(self) -> "PlacementUnitOfWork": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
    def commit(self) -> None: ...


UnitOfWorkFactory = Callable[[UUID], AbstractContextManager[PlacementUnitOfWork]]
