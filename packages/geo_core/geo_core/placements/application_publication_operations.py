"""Submission idempotency and post-publication measurement operations."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping
from uuid import UUID

from geo_core.placements.campaign_context import require_campaign_resource
from geo_core.placements.domain import (
    CampaignResourceKind,
    CampaignScope,
    JobReference,
    Measurement,
    MeasurementCollectionTask,
    Submission,
    canonical_hash,
)
from geo_core.placements.ports import UnitOfWorkFactory
from geo_core.placements.publication_verification_records import (
    PublicationVerificationAttempt,
)


class PlacementPublicationOperationsMixin:
    _uow_factory: UnitOfWorkFactory

    def create_submission(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        publication_request_id: UUID,
        submitted_url: str | None,
        provider_submission_id: str | None,
        idempotency_key: str,
        submitted_by: UUID,
    ) -> Submission:
        payload_hash = canonical_hash(
            {
                "campaign_id": str(campaign_id),
                "publication_request_id": str(publication_request_id),
                "provider_submission_id": provider_submission_id,
                "submitted_url": submitted_url,
            }
        )
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.PUBLICATION,
                resource_id=publication_request_id,
                lock=True,
            )
            result = uow.placements.create_submission(
                project_id=project_id,
                publication_request_id=publication_request_id,
                submitted_url=submitted_url,
                provider_submission_id=provider_submission_id,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                submitted_by=submitted_by,
            )
            uow.commit()
            return result

    def list_submissions(
        self, *, project_id: UUID, campaign_id: UUID, publication_request_id: UUID
    ) -> tuple[Submission, ...]:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.PUBLICATION,
                resource_id=publication_request_id,
            )
            return uow.placements.list_submissions(
                project_id=project_id, publication_request_id=publication_request_id
            )

    def get_submission(
        self, *, project_id: UUID, campaign_id: UUID, submission_id: UUID
    ) -> Submission | None:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.SUBMISSION,
                resource_id=submission_id,
            )
            return uow.placements.get_submission(project_id=project_id, submission_id=submission_id)

    def list_verification_attempts(
        self, *, project_id: UUID, campaign_id: UUID, submission_id: UUID
    ) -> tuple[PublicationVerificationAttempt, ...]:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.SUBMISSION,
                resource_id=submission_id,
            )
            return uow.placements.list_verification_attempts(
                project_id=project_id, submission_id=submission_id
            )

    def request_verification(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        submission_id: UUID,
        idempotency_key: str,
    ) -> JobReference:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.SUBMISSION,
                resource_id=submission_id,
                lock=True,
            )
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
        campaign_id: UUID,
        submission_id: UUID,
        monitoring_query_id: UUID,
        measured_at: datetime,
        citation_present: bool,
        recommendation_position: int | None,
        result_snapshot_uri: str,
        metrics: Mapping[str, object],
    ) -> Measurement:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.SUBMISSION,
                resource_id=submission_id,
                lock=True,
            )
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
        self, *, project_id: UUID, campaign_id: UUID, submission_id: UUID
    ) -> tuple[Measurement, ...]:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.SUBMISSION,
                resource_id=submission_id,
            )
            return uow.placements.list_measurements(
                project_id=project_id, submission_id=submission_id
            )

    def list_measurement_collection_tasks(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        submission_id: UUID | None = None,
        status: str | None = None,
    ) -> tuple[MeasurementCollectionTask, ...]:
        with self._uow_factory(project_id) as uow:
            if submission_id is not None:
                require_campaign_resource(
                    uow.placements,
                    scope=CampaignScope(project_id, campaign_id),
                    kind=CampaignResourceKind.SUBMISSION,
                    resource_id=submission_id,
                )
            return uow.placements.list_measurement_collection_tasks(
                project_id=project_id,
                campaign_id=campaign_id,
                submission_id=submission_id,
                status=status,
            )

    def complete_measurement_collection_task(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        task_id: UUID,
        actor_id: UUID,
    ) -> MeasurementCollectionTask:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.MEASUREMENT_TASK,
                resource_id=task_id,
                lock=True,
            )
            result = uow.placements.complete_measurement_collection_task(
                project_id=project_id, task_id=task_id, actor_id=actor_id
            )
            uow.commit()
            return result

    def cancel_measurement_collection_task(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        task_id: UUID,
        actor_id: UUID,
        reason: str,
    ) -> MeasurementCollectionTask:
        with self._uow_factory(project_id) as uow:
            require_campaign_resource(
                uow.placements,
                scope=CampaignScope(project_id, campaign_id),
                kind=CampaignResourceKind.MEASUREMENT_TASK,
                resource_id=task_id,
                lock=True,
            )
            result = uow.placements.cancel_measurement_collection_task(
                project_id=project_id,
                task_id=task_id,
                actor_id=actor_id,
                reason=reason,
            )
            uow.commit()
            return result
