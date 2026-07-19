"""Persistence boundaries for governed monitoring."""

from __future__ import annotations

from types import TracebackType
from typing import Mapping, Protocol
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.monitoring.domain import (
    CampaignDestinationState,
    CitationDraft,
    Device,
    MeasurementWindow,
    MetricSnapshot,
    MetricObservationMembership,
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
from geo_core.monitoring.customer_projection import ApprovedReportSnapshot, CustomerCampaign
from geo_core.monitoring.official_reports import (
    OfficialReportImport,
    OfficialReportImportDraft,
    OfficialReportRowDraft,
)
from geo_core.monitoring.source_contract import SourceStratumKey


class MonitoringRepository(Protocol):
    def list_customer_campaigns(self, *, project_id: UUID) -> tuple[CustomerCampaign, ...]: ...

    def get_customer_campaign(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> CustomerCampaign | None: ...

    def list_customer_approved_report_snapshots(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[ApprovedReportSnapshot, ...]: ...

    def list_customer_approved_verified_urls(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[VerifiedUrl, ...]: ...

    def campaign_matches_market(
        self, *, project_id: UUID, campaign_id: UUID, market_profile_id: UUID
    ) -> bool: ...

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
        minimum_valid_repeats: int,
        window_days: int,
        statistics_method_version: str,
        statistics_contract_version: str,
        source_strata: tuple[SourceStratumKey, ...],
        source_strata_hash: str,
        actor_id: UUID,
    ) -> MonitoringProtocol: ...

    def get_protocol(
        self, *, project_id: UUID, campaign_id: UUID, protocol_id: UUID
    ) -> MonitoringProtocol | None: ...

    def list_protocols(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[MonitoringProtocol, ...]: ...

    def bind_question_set(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
        question_set_id: UUID,
        confirmed_content_hash: str,
        actor_id: UUID,
    ) -> MonitoringProtocol: ...

    def create_suggestion(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
        query_text: str,
        query_kind: str,
        rationale: str,
        query_cluster_key: str,
        actor_id: UUID,
    ) -> QuerySuggestion: ...

    def list_suggestions(
        self, *, project_id: UUID, campaign_id: UUID, protocol_id: UUID
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
        self, *, project_id: UUID, campaign_id: UUID, protocol_id: UUID
    ) -> tuple[ProtocolQuery, ...]: ...

    def get_protocol_query(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
        query_id: UUID,
    ) -> ProtocolQuery | None: ...

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
        self, *, project_id: UUID, campaign_id: UUID, protocol_id: UUID, actor_id: UUID
    ) -> MonitoringProtocol: ...

    def freeze_protocol(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
        actor_id: UUID,
        protocol_hash: str,
    ) -> MonitoringProtocol: ...

    def import_observation(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
        draft: ObservationDraft,
        actor_id: UUID,
        idempotency_key: str,
        payload_hash: str,
    ) -> MonitoringObservation: ...

    def list_observations(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
        window: MeasurementWindow | None,
    ) -> tuple[MonitoringObservation, ...]: ...

    def list_campaign_observations(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID | None,
        window: MeasurementWindow | None,
    ) -> tuple[MonitoringObservation, ...]: ...

    def campaign_destination_state(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> CampaignDestinationState: ...

    def create_metric_snapshot(
        self,
        *,
        snapshot: MetricSnapshot,
        observations: tuple[MonitoringObservation, ...],
        actor_id: UUID,
    ) -> MetricSnapshot: ...

    def list_metric_observation_memberships(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        snapshot_ids: tuple[UUID, ...],
    ) -> tuple[MetricObservationMembership, ...]: ...

    def list_metric_snapshot_observations(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        snapshot_ids: tuple[UUID, ...],
    ) -> Mapping[UUID, tuple[MonitoringObservation, ...]]: ...

    def get_metric_snapshot(
        self, *, project_id: UUID, campaign_id: UUID, snapshot_id: UUID
    ) -> MetricSnapshot | None: ...

    def list_metric_snapshots(
        self, *, project_id: UUID, campaign_id: UUID, latest_only: bool
    ) -> tuple[MetricSnapshot, ...]: ...

    def create_report(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
        snapshot: MetricSnapshot,
        title: str,
        body: str,
        report_hash: str,
        actor_id: UUID,
    ) -> MonitoringReport: ...

    def approve_report(
        self, *, project_id: UUID, campaign_id: UUID, report_id: UUID, actor_id: UUID
    ) -> MonitoringReport: ...

    def list_reports(
        self, *, project_id: UUID, campaign_id: UUID, approved_only: bool
    ) -> tuple[MonitoringReport, ...]: ...

    def list_verified_urls(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[VerifiedUrl, ...]: ...

    def import_official_report(
        self,
        *,
        project_id: UUID,
        draft: OfficialReportImportDraft,
        rows: tuple[OfficialReportRowDraft, ...],
        actor_id: UUID,
        idempotency_key: str,
        payload_hash: str,
    ) -> OfficialReportImport: ...

    def list_official_reports(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[OfficialReportImport, ...]: ...


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
