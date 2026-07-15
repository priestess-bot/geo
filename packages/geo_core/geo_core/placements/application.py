"""Transactional application service for the placement workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import UUID, uuid4
from urllib.parse import urlparse

from geo_core.placements.application_operations import PlacementOperationsApplicationMixin
from geo_core.placements.application_publication_operations import (
    PlacementPublicationOperationsMixin,
)
from geo_core.placements.claim_inventory import validate_edited_claims
from geo_core.placements.default_prompts import DEFAULT_SYSTEM_TEMPLATE
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
    MonitoringQuery,
    Opportunity,
    PackageVersion,
    PlacementRuleViolation,
    PromptBundleView,
    PromptReleaseView,
    PromptSkill,
    PublicationRequest,
    Review,
    ReviewSubmission,
    assert_approval_allowed,
    canonical_hash,
    edit_package_version,
    validate_authenticity,
)
from geo_core.placements.ports import GeneratedClaim, UnitOfWorkFactory
from geo_core.placements.prompt_release import compile_executable_release


class PlacementApplication(
    PlacementOperationsApplicationMixin, PlacementPublicationOperationsMixin
):
    """Coordinates domain rules and one short Unit of Work per command/query."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, *, artifact_reader: Any | None = None
    ) -> None:
        self._uow_factory = uow_factory
        self._artifact_reader = artifact_reader

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
                raise PlacementRuleViolation(
                    "every selected destination must create an opportunity"
                )
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
        canonical_url: str,
    ) -> Destination:
        parsed = urlparse(canonical_url or "")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise PlacementRuleViolation("destination canonical URL must be an absolute HTTPS URL")
        if parsed.port not in (None, 443):
            raise PlacementRuleViolation(
                "destination canonical URL must use the standard HTTPS port"
            )
        with self._uow_factory(project_id) as uow:
            result = uow.placements.create_destination(
                project_id=project_id,
                publication_channel=publication_channel,
                destination_key=destination_key,
                operation_mode=operation_mode,
                destination_account_id=destination_account_id,
                canonical_url=canonical_url,
                canonical_host=parsed.hostname.casefold(),
                allowed_hosts=(parsed.hostname.casefold(),),
            )
            uow.commit()
            return result

    def list_destinations(self, *, project_id: UUID) -> tuple[Destination, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_destinations(project_id=project_id)

    def list_opportunities(self, *, project_id: UUID, campaign_id: UUID) -> tuple[Opportunity, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_opportunities(project_id=project_id, campaign_id=campaign_id)

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

    def get_evidence_attempt(
        self, *, project_id: UUID, attempt_id: UUID
    ) -> EvidencePackAttempt | None:
        with self._uow_factory(project_id) as uow:
            return uow.placements.get_evidence_attempt(project_id=project_id, attempt_id=attempt_id)

    def list_evidence_attempt_items(
        self, *, project_id: UUID, attempt_id: UUID
    ) -> tuple[Mapping[str, object], ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_evidence_attempt_items(
                project_id=project_id, attempt_id=attempt_id
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
        client_variable_names: tuple[str, ...],
        system_template: str = DEFAULT_SYSTEM_TEMPLATE,
        user_template: str | None = None,
    ) -> PromptReleaseView:
        with self._uow_factory(project_id) as uow:
            skill_version = uow.placements.create_skill_version(
                project_id=project_id, skill_id=skill_id, source=source, actor_id=actor_id
            )
            template, normalized_system = compile_executable_release(
                skill_version=skill_version,
                system_template=system_template,
                user_template=user_template,
                output_schema=output_schema,
                client_variable_names=client_variable_names,
            )
            result = uow.placements.create_template_release(
                project_id=project_id,
                skill_version_id=skill_version.id,
                template=template,
                source_text=skill_version.source,
                system_template=normalized_system,
                output_schema=output_schema,
                client_variable_names=client_variable_names,
            )
            uow.commit()
            return result

    def list_prompt_skills(self, *, project_id: UUID) -> tuple[PromptSkill, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_prompt_skills(project_id=project_id)

    def list_prompt_releases(
        self, *, project_id: UUID, skill_id: UUID
    ) -> tuple[PromptReleaseView, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_prompt_releases(project_id=project_id, skill_id=skill_id)

    def list_prompt_bundles(
        self, *, project_id: UUID, brief_version_id: UUID
    ) -> tuple[PromptBundleView, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_prompt_bundles(
                project_id=project_id, brief_version_id=brief_version_id
            )

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
            if (
                uow.placements.get_template_release(project_id=project_id, release_id=release_id)
                is None
            ):
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
        requested_by: UUID,
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
                requested_by=requested_by,
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

    def get_package_version(self, *, project_id: UUID, version_id: UUID) -> PackageVersion | None:
        with self._uow_factory(project_id) as uow:
            return uow.placements.get_package_version(project_id=project_id, version_id=version_id)

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
        claims: tuple[GeneratedClaim, ...],
    ) -> PackageVersion:
        validate_edited_claims(claims)
        with self._uow_factory(project_id) as uow:
            base = uow.placements.get_package_version(
                project_id=project_id, version_id=base_version_id
            )
            if base is None:
                raise PlacementRuleViolation("base package version does not exist")
            if base.package_id != package_id:
                raise PlacementRuleViolation(
                    "base version does not belong to the requested package"
                )
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
                version=version, superseded_version_id=base.id, claims=claims
            )
            uow.commit()
            return result

    def list_claims(self, *, project_id: UUID, version_id: UUID) -> tuple[Claim, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_claims(project_id=project_id, version_id=version_id)

    def submit_for_review(
        self, *, project_id: UUID, version_id: UUID, submitted_by: UUID
    ) -> ReviewSubmission:
        with self._uow_factory(project_id) as uow:
            if not uow.placements.list_claims(project_id=project_id, version_id=version_id):
                raise PlacementRuleViolation(
                    "package version requires a non-empty claim inventory before review"
                )
            result = uow.placements.submit_for_review(
                project_id=project_id, version_id=version_id, submitted_by=submitted_by
            )
            uow.commit()
            return result

    def submit_review(
        self,
        *,
        project_id: UUID,
        version_id: UUID,
        reviewer_id: UUID,
        decision: str,
        claim_inventory_complete: bool,
        extracted_claim_support_confirmed: bool,
        score: float | None,
        notes: str | None,
    ) -> Review:
        with self._uow_factory(project_id) as uow:
            submission = uow.placements.get_review_submission(
                project_id=project_id, version_id=version_id
            )
            if submission is None:
                raise PlacementRuleViolation("package version has not been submitted for review")
            review = Review(
                id=uuid4(),
                project_id=project_id,
                package_version_id=version_id,
                submitted_for_review_by=submission.submitted_by,
                reviewer_id=reviewer_id,
                decision=decision,
                claim_inventory_complete=claim_inventory_complete,
                extracted_claim_support_confirmed=extracted_claim_support_confirmed,
                score=score,
                notes=notes,
            )
            claims = uow.placements.list_claims(project_id=project_id, version_id=version_id)
            assert_approval_allowed(review=review, claims=claims)
            result = uow.placements.save_review(review=review)
            uow.commit()
            return result

    def list_reviews(self, *, project_id: UUID, version_id: UUID) -> tuple[Review, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_reviews(project_id=project_id, version_id=version_id)

    def export_package(
        self, *, project_id: UUID, version_id: UUID, requested_by: UUID
    ) -> ExportReceipt:
        with self._uow_factory(project_id) as uow:
            result = uow.placements.export_package(
                project_id=project_id,
                version_id=version_id,
                exported_at=datetime.now(UTC),
                requested_by=requested_by,
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
        restricted_policy_acknowledged: bool,
        policy_basis: str | None,
    ) -> PublicationRequest:
        with self._uow_factory(project_id) as uow:
            result = uow.placements.create_publication_request(
                project_id=project_id,
                version_id=version_id,
                destination_id=destination_id,
                requested_by=requested_by,
                publication_attempt=publication_attempt,
                idempotency_key=idempotency_key,
                restricted_policy_acknowledged=restricted_policy_acknowledged,
                policy_basis=policy_basis,
            )
            uow.commit()
            return result

    def list_publication_requests(
        self, *, project_id: UUID, version_id: UUID
    ) -> tuple[PublicationRequest, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_publication_requests(
                project_id=project_id, version_id=version_id
            )

__all__ = ["ConcurrencyConflict", "PlacementApplication"]
