"""Persistence boundaries for governed monitoring."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.monitoring.domain import (
    CampaignDestinationState,
    CitationDraft,
    Device,
    MeasurementWindow,
    MetricSnapshot,
    MonitoringObservation,
    MonitoringProtocol,
    MonitoringReport,
    ObservationDraft,
    Platform,
    ProtocolQuery,
    QuerySuggestion,
    VerifiedCitationTarget,
    VerifiedUrl,
)


class MonitoringRepository(Protocol):
    def create_protocol(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        market_profile_id: UUID,
        name: str,
        platform: Platform,
        locale: str,
        device: Device,
        sample_size: int,
        window_days: int,
        actor_id: UUID,
    ) -> MonitoringProtocol: ...

    def get_protocol(
        self, *, project_id: UUID, protocol_id: UUID
    ) -> MonitoringProtocol | None: ...

    def list_protocols(self, *, project_id: UUID) -> tuple[MonitoringProtocol, ...]: ...

    def create_suggestion(
        self,
        *,
        project_id: UUID,
        protocol_id: UUID,
        query_text: str,
        query_kind: str,
        rationale: str,
        actor_id: UUID,
    ) -> QuerySuggestion: ...

    def list_suggestions(
        self, *, project_id: UUID, protocol_id: UUID
    ) -> tuple[QuerySuggestion, ...]: ...

    def approve_suggestion(
        self,
        *,
        project_id: UUID,
        protocol: MonitoringProtocol,
        suggestion_id: UUID,
        actor_id: UUID,
    ) -> tuple[QuerySuggestion, ProtocolQuery]: ...

    def list_protocol_queries(
        self, *, project_id: UUID, protocol_id: UUID
    ) -> tuple[ProtocolQuery, ...]: ...

    def list_verified_citation_targets(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[VerifiedCitationTarget, ...]: ...

    def resolve_citation_lineage(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        citations: tuple[CitationDraft, ...],
    ) -> tuple[CitationDraft, ...]: ...

    def approve_protocol(
        self, *, project_id: UUID, protocol_id: UUID, actor_id: UUID
    ) -> MonitoringProtocol: ...

    def freeze_protocol(
        self,
        *,
        project_id: UUID,
        protocol_id: UUID,
        actor_id: UUID,
        protocol_hash: str,
    ) -> MonitoringProtocol: ...

    def import_observation(
        self,
        *,
        project_id: UUID,
        protocol_id: UUID,
        campaign_id: UUID,
        draft: ObservationDraft,
        actor_id: UUID,
        idempotency_key: str,
        payload_hash: str,
    ) -> MonitoringObservation: ...

    def list_observations(
        self,
        *,
        project_id: UUID,
        protocol_id: UUID,
        window: MeasurementWindow | None,
    ) -> tuple[MonitoringObservation, ...]: ...

    def campaign_destination_state(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> CampaignDestinationState: ...

    def create_metric_snapshot(
        self, *, snapshot: MetricSnapshot, actor_id: UUID
    ) -> MetricSnapshot: ...

    def get_metric_snapshot(
        self, *, project_id: UUID, snapshot_id: UUID
    ) -> MetricSnapshot | None: ...

    def list_metric_snapshots(
        self, *, project_id: UUID, latest_only: bool
    ) -> tuple[MetricSnapshot, ...]: ...

    def create_report(
        self,
        *,
        project_id: UUID,
        protocol_id: UUID,
        snapshot: MetricSnapshot,
        title: str,
        body: str,
        report_hash: str,
        actor_id: UUID,
    ) -> MonitoringReport: ...

    def approve_report(
        self, *, project_id: UUID, report_id: UUID, actor_id: UUID
    ) -> MonitoringReport: ...

    def list_reports(
        self, *, project_id: UUID, approved_only: bool
    ) -> tuple[MonitoringReport, ...]: ...

    def list_verified_urls(self, *, project_id: UUID) -> tuple[VerifiedUrl, ...]: ...


class MonitoringUnitOfWork(Protocol):
    monitoring: MonitoringRepository

    def __enter__(self) -> "MonitoringUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...


class MonitoringUnitOfWorkFactory(Protocol):
    def __call__(self, principal: AccessPrincipal) -> MonitoringUnitOfWork: ...
