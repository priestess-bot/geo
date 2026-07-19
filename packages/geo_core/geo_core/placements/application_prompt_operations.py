"""Opportunity-owned Prompt Release binding and Bundle operations."""

from __future__ import annotations

from typing import Mapping
from uuid import UUID

from geo_core.placements.campaign_context import require_campaign_resource
from geo_core.placements.domain import (
    CampaignPlacementReadiness,
    CampaignResourceKind,
    CampaignScope,
    JobReference,
    OpportunityPromptReleaseBinding,
    PlacementConflict,
    PlacementNotFound,
    PlacementRuleViolation,
    PromptBundleView,
    PromptReleaseView,
    assert_same_campaign_lineage,
    transition_prompt_release_status,
)
from geo_core.placements.ports import UnitOfWorkFactory


class PlacementPromptOperationsMixin:
    _uow_factory: UnitOfWorkFactory

    def transition_prompt_release(
        self,
        *,
        project_id: UUID,
        release_id: UUID,
        command: str,
        expected_state_version: int,
        reason: str | None,
        actor_id: UUID,
        idempotency_key: str,
    ) -> PromptReleaseView:
        if expected_state_version < 1:
            raise PlacementRuleViolation("expected Prompt Release state version must be positive")
        if command == "revoke" and not (reason or "").strip():
            raise PlacementRuleViolation("revoking a Prompt Release requires a reason")
        with self._uow_factory(project_id) as uow:
            current = uow.placements.get_prompt_release_view(
                project_id=project_id, release_id=release_id
            )
            if current is None:
                raise PlacementNotFound("The Prompt Release does not exist in this project.")
            target = transition_prompt_release_status(
                status=current.status.value, command=command
            )
            result = uow.placements.transition_prompt_release_state(
                project_id=project_id,
                release_id=release_id,
                expected_state_version=expected_state_version,
                target_status=target.value,
                reason=(reason or "").strip() or None,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
            uow.commit()
            return result

    def get_current_prompt_release_binding(
        self, *, project_id: UUID, campaign_id: UUID, opportunity_id: UUID
    ) -> OpportunityPromptReleaseBinding | None:
        scope = CampaignScope(project_id, campaign_id)
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=scope,
                kind=CampaignResourceKind.OPPORTUNITY,
                resource_id=opportunity_id,
            )
            return uow.placements.get_current_prompt_release_binding(
                scope=scope, opportunity_id=opportunity_id
            )

    def list_prompt_release_binding_history(
        self, *, project_id: UUID, campaign_id: UUID, opportunity_id: UUID
    ) -> tuple[OpportunityPromptReleaseBinding, ...]:
        scope = CampaignScope(project_id, campaign_id)
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=scope,
                kind=CampaignResourceKind.OPPORTUNITY,
                resource_id=opportunity_id,
            )
            return uow.placements.list_prompt_release_binding_history(
                scope=scope, opportunity_id=opportunity_id
            )

    def bind_opportunity_prompt_release(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        opportunity_id: UUID,
        release_id: UUID,
        expected_binding_version: int,
        reason: str | None,
        actor_id: UUID,
        idempotency_key: str,
    ) -> OpportunityPromptReleaseBinding:
        if expected_binding_version < 0:
            raise PlacementRuleViolation("expected Prompt binding version cannot be negative")
        scope = CampaignScope(project_id, campaign_id)
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=scope,
                kind=CampaignResourceKind.OPPORTUNITY,
                resource_id=opportunity_id,
                lock=True,
            )
            release = uow.placements.get_prompt_release_view(
                project_id=project_id, release_id=release_id
            )
            if release is None:
                raise PlacementNotFound("The Prompt Release does not exist in this project.")
            if release.status.value != "approved":
                raise PlacementConflict("only an approved Prompt Release can be bound")
            result = uow.placements.bind_opportunity_prompt_release(
                scope=scope,
                opportunity_id=opportunity_id,
                release_id=release_id,
                expected_binding_version=expected_binding_version,
                reason=(reason or "").strip() or None,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
            uow.commit()
            return result

    def get_campaign_placement_readiness(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> CampaignPlacementReadiness:
        scope = CampaignScope(project_id, campaign_id)
        with self._uow_factory(project_id) as uow:
            if uow.placements.get_campaign(
                project_id=project_id, campaign_id=campaign_id
            ) is None:
                raise PlacementNotFound("The Campaign does not exist in this project.")
            return uow.placements.get_campaign_placement_readiness(scope=scope)

    def list_prompt_bundles(
        self, *, project_id: UUID, campaign_id: UUID, brief_version_id: UUID
    ) -> tuple[PromptBundleView, ...]:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.BRIEF_VERSION,
                resource_id=brief_version_id,
            )
            return uow.placements.list_prompt_bundles(
                project_id=project_id, brief_version_id=brief_version_id
            )

    def create_prompt_bundle(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        opportunity_id: UUID,
        brief_version_id: UUID,
        evidence_pack_attempt_id: UUID,
        prompt_release_binding_id: UUID,
        confirmed_release_hash: str,
        variables: Mapping[str, object],
        model_policy_hash: str,
        idempotency_key: str,
        requested_by: UUID,
    ) -> PromptBundleView:
        if not _is_sha256(confirmed_release_hash):
            raise PlacementRuleViolation("confirmed Prompt Release hash must be SHA-256")
        scope = CampaignScope(project_id, campaign_id)
        with self._uow_factory(project_id) as uow:
            opportunity = require_campaign_resource(
                uow.placements,
                scope=scope,
                kind=CampaignResourceKind.OPPORTUNITY,
                resource_id=opportunity_id,
                lock=True,
            )
            brief = require_campaign_resource(
                uow.placements,
                scope=scope,
                kind=CampaignResourceKind.BRIEF_VERSION,
                resource_id=brief_version_id,
                lock=True,
            )
            attempt = require_campaign_resource(
                uow.placements,
                scope=scope,
                kind=CampaignResourceKind.EVIDENCE_ATTEMPT,
                resource_id=evidence_pack_attempt_id,
                lock=True,
            )
            assert_same_campaign_lineage(opportunity, brief, attempt)
            result = uow.placements.create_prompt_bundle(
                scope=scope,
                opportunity_id=opportunity_id,
                brief_version_id=brief_version_id,
                evidence_pack_attempt_id=evidence_pack_attempt_id,
                prompt_release_binding_id=prompt_release_binding_id,
                confirmed_release_hash=confirmed_release_hash,
                variables=variables,
                model_policy_hash=model_policy_hash,
                idempotency_key=idempotency_key,
                requested_by=requested_by,
            )
            uow.commit()
            return result

    def request_generation(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        prompt_bundle_id: UUID,
        configured_model: str,
        model_call_budget: int,
        idempotency_key: str,
        requested_by: UUID,
    ) -> JobReference:
        if not 1 <= model_call_budget <= 5:
            raise PlacementRuleViolation("model call budget must be between 1 and 5")
        scope = CampaignScope(project_id, campaign_id)
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=scope,
                kind=CampaignResourceKind.PROMPT_BUNDLE,
                resource_id=prompt_bundle_id,
                lock=True,
            )
            job = uow.placements.enqueue_generation(
                scope=scope,
                prompt_bundle_id=prompt_bundle_id,
                configured_model=configured_model,
                model_call_budget=model_call_budget,
                idempotency_key=idempotency_key,
                requested_by=requested_by,
            )
            uow.commit()
            return job


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
