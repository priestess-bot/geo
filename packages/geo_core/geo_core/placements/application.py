"""Transactional application service for the placement workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping
from uuid import UUID, uuid4

from geo_core.placements.domain import (
    AuthenticityRisk,
    BriefVersion,
    Campaign,
    Claim,
    ConcurrencyConflict,
    ConsumerExperience,
    Destination,
    EvidencePackAttempt,
    ExportReceipt,
    JobReference,
    Measurement,
    MonitoringQuery,
    Opportunity,
    PackageVersion,
    PlacementRuleViolation,
    PromptBundleView,
    PromptReleaseView,
    PromptSkill,
    PublicationRequest,
    Review,
    Submission,
    assert_approval_allowed,
    canonical_hash,
    edit_package_version,
    validate_authenticity,
)
from geo_core.placements.ports import UnitOfWorkFactory
from geo_core.prompts.domain import compile_template


class PlacementApplication:
    """Coordinates domain rules and one short Unit of Work per command/query."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def create_campaign(
        self,
        *,
        project_id: UUID,
        market_profile_id: UUID,
        primary_product_entity_id: UUID,
        name: str,
        objective: str,
        actor_id: UUID,
        destination_ids: tuple[UUID, ...],
        rationale: str,
    ) -> tuple[Campaign, tuple[Opportunity, ...]]:
        if not destination_ids:
            raise PlacementRuleViolation("a campaign must select at least one destination")
        if len(set(destination_ids)) != len(destination_ids):
            raise PlacementRuleViolation("selected destinations must be unique")
        with self._uow_factory(project_id) as uow:
            campaign = uow.placements.create_campaign(
                project_id=project_id,
                market_profile_id=market_profile_id,
                primary_product_entity_id=primary_product_entity_id,
                name=name,
                objective=objective,
                actor_id=actor_id,
            )
            opportunities = uow.placements.create_opportunities(
                project_id=project_id,
                campaign_id=campaign.id,
                destination_ids=destination_ids,
                rationale=rationale,
            )
            if {item.destination_id for item in opportunities} != set(destination_ids):
                raise PlacementRuleViolation("every selected destination must create an opportunity")
            uow.commit()
            return campaign, opportunities

    def list_campaigns(self, *, project_id: UUID) -> tuple[Campaign, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_campaigns(project_id=project_id)

    def get_campaign(self, *, project_id: UUID, campaign_id: UUID) -> Campaign | None:
        with self._uow_factory(project_id) as uow:
            return uow.placements.get_campaign(project_id=project_id, campaign_id=campaign_id)

    def create_monitoring_query(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        market_profile_id: UUID,
        query_text: str,
        query_kind: str,
        locale: str,
    ) -> MonitoringQuery:
        with self._uow_factory(project_id) as uow:
            result = uow.placements.create_monitoring_query(
                campaign_id=campaign_id,
                project_id=project_id,
                market_profile_id=market_profile_id,
                query_text=query_text,
                query_kind=query_kind,
                locale=locale,
            )
            uow.commit()
            return result

    def list_monitoring_queries(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[MonitoringQuery, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_monitoring_queries(
                project_id=project_id, campaign_id=campaign_id
            )

    def create_destination(
        self,
        *,
        project_id: UUID,
        publication_channel: str,
        destination_key: str,
        operation_mode: str,
        destination_account_id: str | None,
        canonical_url: str | None,
    ) -> Destination:
        with self._uow_factory(project_id) as uow:
            result = uow.placements.create_destination(
                project_id=project_id,
                publication_channel=publication_channel,
                destination_key=destination_key,
                operation_mode=operation_mode,
                destination_account_id=destination_account_id,
                canonical_url=canonical_url,
            )
            uow.commit()
            return result

    def list_destinations(self, *, project_id: UUID) -> tuple[Destination, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_destinations(project_id=project_id)

    def list_opportunities(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[Opportunity, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_opportunities(
                project_id=project_id, campaign_id=campaign_id
            )

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
        consumer_experience: ConsumerExperience | None,
        authenticity_risks: tuple[AuthenticityRisk, ...],
    ) -> BriefVersion:
        validate_authenticity(experience=consumer_experience, risks=authenticity_risks)
        snapshot: dict[str, object] = {"goals": dict(goals), "constraints": dict(constraints)}
        if consumer_experience:
            snapshot["consumer_experience"] = {
                "description": consumer_experience.description,
                "source": consumer_experience.source,
                "usage_rights": consumer_experience.usage_rights,
                "disclosure": consumer_experience.disclosure,
            }
        with self._uow_factory(project_id) as uow:
            result = uow.placements.create_brief_version(
                project_id=project_id,
                opportunity_id=opportunity_id,
                primary_brand_entity_id=primary_brand_entity_id,
                goals=snapshot,
                constraints=constraints,
                compared_entity_ids=compared_entity_ids,
                allowed_subject_entity_ids=allowed_subject_entity_ids,
                actor_id=actor_id,
                base_version_id=base_version_id,
                content_hash=canonical_hash(snapshot),
            )
            uow.commit()
            return result

    def list_brief_versions(
        self, *, project_id: UUID, opportunity_id: UUID
    ) -> tuple[BriefVersion, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_brief_versions(
                project_id=project_id, opportunity_id=opportunity_id
            )

    def create_evidence_attempt(
        self, *, project_id: UUID, brief_version_id: UUID, idempotency_key: str
    ) -> tuple[EvidencePackAttempt, JobReference]:
        with self._uow_factory(project_id) as uow:
            result = uow.placements.create_evidence_attempt(
                project_id=project_id,
                brief_version_id=brief_version_id,
                idempotency_key=idempotency_key,
            )
            uow.commit()
            return result

    def list_evidence_attempts(
        self, *, project_id: UUID, brief_version_id: UUID
    ) -> tuple[EvidencePackAttempt, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_evidence_attempts(
                project_id=project_id, brief_version_id=brief_version_id
            )

    def create_prompt_skill(self, *, project_id: UUID, skill_key: str) -> PromptSkill:
        with self._uow_factory(project_id) as uow:
            result = uow.placements.create_prompt_skill(project_id=project_id, skill_key=skill_key)
            uow.commit()
            return result

    def publish_skill_version(
        self,
        *,
        project_id: UUID,
        skill_id: UUID,
        source: str,
        actor_id: UUID,
        output_schema: Mapping[str, object],
    ) -> PromptReleaseView:
        with self._uow_factory(project_id) as uow:
            skill_version = uow.placements.create_skill_version(
                project_id=project_id, skill_id=skill_id, source=source, actor_id=actor_id
            )
            template = compile_template(release_id=uuid4(), skill=skill_version)
            result = uow.placements.create_template_release(
                project_id=project_id,
                skill_version_id=skill_version.id,
                template=template,
                output_schema=output_schema,
            )
            uow.commit()
            return result

    def create_prompt_bundle(
        self,
        *,
        project_id: UUID,
        brief_version_id: UUID,
        evidence_pack_attempt_id: UUID,
        release_id: UUID,
        variables: Mapping[str, object],
        model_policy_hash: str,
    ) -> PromptBundleView:
        with self._uow_factory(project_id) as uow:
            if uow.placements.get_template_release(
                project_id=project_id, release_id=release_id
            ) is None:
                raise PlacementRuleViolation("template release does not exist")
            result = uow.placements.create_prompt_bundle(
                project_id=project_id,
                brief_version_id=brief_version_id,
                evidence_pack_attempt_id=evidence_pack_attempt_id,
                release_id=release_id,
                variables=variables,
                model_policy_hash=model_policy_hash,
            )
            uow.commit()
            return result

    def request_generation(
        self,
        *,
        project_id: UUID,
        prompt_bundle_id: UUID,
        configured_model: str,
        model_call_budget: int,
        idempotency_key: str,
    ) -> JobReference:
        if not 1 <= model_call_budget <= 5:
            raise PlacementRuleViolation("model call budget must be between 1 and 5")
        with self._uow_factory(project_id) as uow:
            job = uow.placements.enqueue_generation(
                project_id=project_id,
                prompt_bundle_id=prompt_bundle_id,
                configured_model=configured_model,
                model_call_budget=model_call_budget,
                idempotency_key=idempotency_key,
            )
            uow.commit()
            return job

    def list_package_versions(
        self, *, project_id: UUID, opportunity_id: UUID
    ) -> tuple[PackageVersion, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_package_versions(
                project_id=project_id, opportunity_id=opportunity_id
            )

    def edit_package_version(
        self,
        *,
        project_id: UUID,
        package_id: UUID,
        base_version_id: UUID,
        base_content_hash: str,
        content_json: Mapping[str, object],
        rendered_text: str,
        edited_by: UUID,
        reason: str,
    ) -> PackageVersion:
        with self._uow_factory(project_id) as uow:
            base = uow.placements.get_package_version(
                project_id=project_id, version_id=base_version_id
            )
            if base is None:
                raise PlacementRuleViolation("base package version does not exist")
            if base.package_id != package_id:
                raise PlacementRuleViolation("base version does not belong to the requested package")
            version = edit_package_version(
                base=base,
                new_id=uuid4(),
                expected_hash=base_content_hash,
                content_json=content_json,
                rendered_text=rendered_text,
                edited_by=edited_by,
                reason=reason,
            )
            result = uow.placements.save_edited_version(
                version=version, superseded_version_id=base.id
            )
            uow.commit()
            return result

    def list_claims(self, *, project_id: UUID, version_id: UUID) -> tuple[Claim, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_claims(project_id=project_id, version_id=version_id)

    def submit_review(self, *, review: Review) -> Review:
        with self._uow_factory(review.project_id) as uow:
            claims = uow.placements.list_claims(
                project_id=review.project_id, version_id=review.package_version_id
            )
            assert_approval_allowed(review=review, claims=claims)
            result = uow.placements.save_review(review=review)
            uow.commit()
            return result

    def export_package(
        self, *, project_id: UUID, version_id: UUID
    ) -> ExportReceipt:
        with self._uow_factory(project_id) as uow:
            result = uow.placements.export_package(
                project_id=project_id, version_id=version_id, exported_at=datetime.now(UTC)
            )
            uow.commit()
            return result

    def request_publication(
        self,
        *,
        project_id: UUID,
        version_id: UUID,
        destination_id: UUID,
        requested_by: UUID,
        publication_attempt: int,
        idempotency_key: str,
    ) -> PublicationRequest:
        with self._uow_factory(project_id) as uow:
            result = uow.placements.create_publication_request(
                project_id=project_id,
                version_id=version_id,
                destination_id=destination_id,
                requested_by=requested_by,
                publication_attempt=publication_attempt,
                idempotency_key=idempotency_key,
            )
            uow.commit()
            return result

    def create_submission(
        self,
        *,
        project_id: UUID,
        publication_request_id: UUID,
        submitted_url: str | None,
        provider_submission_id: str | None,
    ) -> Submission:
        with self._uow_factory(project_id) as uow:
            result = uow.placements.create_submission(
                project_id=project_id,
                publication_request_id=publication_request_id,
                submitted_url=submitted_url,
                provider_submission_id=provider_submission_id,
            )
            uow.commit()
            return result

    def request_verification(
        self, *, project_id: UUID, submission_id: UUID, idempotency_key: str
    ) -> JobReference:
        with self._uow_factory(project_id) as uow:
            result = uow.placements.enqueue_verification(
                project_id=project_id,
                submission_id=submission_id,
                idempotency_key=idempotency_key,
            )
            uow.commit()
            return result

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
    ) -> Measurement:
        with self._uow_factory(project_id) as uow:
            result = uow.placements.record_measurement(
                project_id=project_id,
                submission_id=submission_id,
                monitoring_query_id=monitoring_query_id,
                measured_at=measured_at,
                citation_present=citation_present,
                recommendation_position=recommendation_position,
                result_snapshot_uri=result_snapshot_uri,
                metrics=metrics,
            )
            uow.commit()
            return result

    def list_measurements(
        self, *, project_id: UUID, submission_id: UUID
    ) -> tuple[Measurement, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_measurements(
                project_id=project_id, submission_id=submission_id
            )


__all__ = ["ConcurrencyConflict", "PlacementApplication"]
