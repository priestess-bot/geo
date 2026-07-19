"""Secondary placement application commands kept out of the core workflow coordinator."""

from __future__ import annotations

from typing import Any, Mapping, cast
from uuid import UUID

from geo_core.object_store import RetrievedObject
from geo_core.placements.campaign_context import require_campaign_resource
from geo_core.placements.default_prompts import (
    default_prompt_definitions,
    default_output_schema,
)
from geo_core.placements.generation_contract import validate_generation_schema
from geo_core.placements.domain import (
    CampaignResourceKind,
    CampaignScope,
    DestinationPolicyVersion,
    ExportReceipt,
    JobReference,
    MonitoringQuery,
    Opportunity,
    PlacementRuleViolation,
    PublicationRequest,
    Submission,
)
from geo_core.placements.ports import UnitOfWorkFactory


class PlacementOperationsApplicationMixin:
    _uow_factory: UnitOfWorkFactory
    _artifact_reader: Any | None

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

    def get_prompt_bundle(
        self, *, project_id: UUID, campaign_id: UUID, bundle_id: UUID
    ) -> Mapping[str, object] | None:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.PROMPT_BUNDLE,
                resource_id=bundle_id,
            )
            return uow.placements.get_prompt_bundle(project_id=project_id, bundle_id=bundle_id)

    def select_prompt_release(
        self,
        *,
        project_id: UUID,
        task_key: str,
        release_id: UUID,
        selected_by: UUID,
    ) -> Mapping[str, object]:
        with self._uow_factory(project_id) as uow:
            result = uow.placements.select_prompt_release(
                project_id=project_id,
                task_key=task_key,
                release_id=release_id,
                selected_by=selected_by,
            )
            uow.commit()
            return result

    def list_prompt_release_selections(
        self, *, project_id: UUID
    ) -> tuple[Mapping[str, object], ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_prompt_release_selections(project_id=project_id)

    def install_default_prompt_catalog(
        self, *, project_id: UUID, actor_id: UUID
    ) -> tuple[Mapping[str, object], ...]:
        output_schema = default_output_schema()
        definitions = default_prompt_definitions()
        validate_generation_schema(output_schema)
        with self._uow_factory(project_id) as uow:
            result = uow.placements.install_default_prompt_catalog(
                project_id=project_id,
                definitions=definitions,
                output_schema=output_schema,
                actor_id=actor_id,
            )
            uow.commit()
            return result

    def review_destination_policy(
        self,
        *,
        project_id: UUID,
        destination_id: UUID,
        status: str,
        rules: Mapping[str, object],
        identity_requirements: Mapping[str, object],
        disclosure_requirements: Mapping[str, object],
        allowed_hosts: tuple[str, ...],
        reviewed_by: UUID,
    ) -> DestinationPolicyVersion:
        with self._uow_factory(project_id) as uow:
            result = uow.placements.review_destination_policy(
                project_id=project_id,
                destination_id=destination_id,
                status=status,
                rules=rules,
                identity_requirements=identity_requirements,
                disclosure_requirements=disclosure_requirements,
                allowed_hosts=allowed_hosts,
                reviewed_by=reviewed_by,
            )
            uow.commit()
            return result

    def list_destination_policies(
        self, *, project_id: UUID, destination_id: UUID
    ) -> tuple[DestinationPolicyVersion, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_destination_policies(
                project_id=project_id, destination_id=destination_id
            )

    def transition_opportunity(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        opportunity_id: UUID,
        command: str,
        reason: str | None,
    ) -> Opportunity:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.OPPORTUNITY,
                resource_id=opportunity_id,
                lock=True,
            )
            result = uow.placements.transition_opportunity(
                project_id=project_id,
                opportunity_id=opportunity_id,
                command=command,
                reason=reason,
            )
            uow.commit()
            return result

    def list_exports(
        self, *, project_id: UUID, campaign_id: UUID, version_id: UUID
    ) -> tuple[ExportReceipt, ...]:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.PACKAGE_VERSION,
                resource_id=version_id,
            )
            return uow.placements.list_exports(project_id=project_id, version_id=version_id)

    def list_publication_requests(
        self, *, project_id: UUID, campaign_id: UUID, version_id: UUID
    ) -> tuple[PublicationRequest, ...]:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.PACKAGE_VERSION,
                resource_id=version_id,
            )
            return uow.placements.list_publication_requests(
                project_id=project_id, version_id=version_id
            )

    def download_export(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        version_id: UUID,
        export_id: UUID,
    ) -> RetrievedObject:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.EXPORT,
                resource_id=export_id,
            )
        receipt = next(
            (
                item
                for item in self.list_exports(
                    project_id=project_id, campaign_id=campaign_id, version_id=version_id
                )
                if item.id == export_id
            ),
            None,
        )
        if receipt is None:
            raise PlacementRuleViolation("export receipt does not exist")
        if receipt.artifact_status != "finalized" or receipt.artifact_uri is None:
            raise PlacementRuleViolation("export artifact is not finalized")
        if self._artifact_reader is None:
            raise PlacementRuleViolation("export artifact storage is not configured")
        getter = getattr(self._artifact_reader, "get_object", None)
        if getter is None:
            raise PlacementRuleViolation("export artifact reader is invalid")
        return cast(
            RetrievedObject,
            getter(key=receipt.storage_key, expected_hash=receipt.content_hash),
        )

    def backfill_submission_url(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        submission_id: UUID,
        submitted_url: str,
        actor_id: UUID,
    ) -> Submission:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.SUBMISSION,
                resource_id=submission_id,
                lock=True,
            )
            result = uow.placements.backfill_submission_url(
                project_id=project_id,
                submission_id=submission_id,
                submitted_url=submitted_url,
                actor_id=actor_id,
            )
            uow.commit()
            return result

    def transition_submission(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        submission_id: UUID,
        status: str,
        reason: str,
        actor_id: UUID,
    ) -> Submission:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.SUBMISSION,
                resource_id=submission_id,
                lock=True,
            )
            result = uow.placements.transition_submission(
                project_id=project_id,
                submission_id=submission_id,
                status=status,
                reason=reason,
                actor_id=actor_id,
            )
            uow.commit()
            return result

    def transition_publication(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        publication_request_id: UUID,
        status: str,
        reason: str,
        actor_id: UUID,
    ) -> PublicationRequest:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.PUBLICATION,
                resource_id=publication_request_id,
                lock=True,
            )
            result = uow.placements.transition_publication(
                project_id=project_id,
                publication_request_id=publication_request_id,
                status=status,
                reason=reason,
                actor_id=actor_id,
            )
            uow.commit()
            return result

    def cancel_job(
        self, *, project_id: UUID, campaign_id: UUID, job_id: UUID, actor_id: UUID
    ) -> JobReference:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.JOB,
                resource_id=job_id,
                lock=True,
            )
            result = uow.placements.cancel_job(
                project_id=project_id, job_id=job_id, actor_id=actor_id
            )
            uow.commit()
            return result

    def retry_job_now(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        job_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
    ) -> JobReference:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.JOB,
                resource_id=job_id,
                lock=True,
            )
            result = uow.placements.retry_job_now(
                project_id=project_id,
                job_id=job_id,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
            uow.commit()
            return result

    def replay_job(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        source_job_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
    ) -> JobReference:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.JOB,
                resource_id=source_job_id,
                lock=True,
            )
            result = uow.placements.replay_job(
                project_id=project_id,
                source_job_id=source_job_id,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
            uow.commit()
            return result

    def list_job_events(
        self, *, project_id: UUID, campaign_id: UUID, job_id: UUID
    ) -> tuple[Mapping[str, object], ...]:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.JOB,
                resource_id=job_id,
            )
            return uow.placements.list_job_events(project_id=project_id, job_id=job_id)
