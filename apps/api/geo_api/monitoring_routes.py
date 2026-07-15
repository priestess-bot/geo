"""Internal stable API for frozen protocols, observations, metrics and reports."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, status

from geo_api.monitoring_dependencies import (
    authorize_monitoring_project as _principal,
    monitoring_application as _application,
    monitoring_call as _call,
)
from geo_api.monitoring_presenters import metric_response, report_response
from geo_api.monitoring_contracts import (
    ComputeMetricsRequest,
    CreateMonitoringProtocolRequest,
    CreateQuerySuggestionRequest,
    GenerateReportRequest,
    ImportObservationRequest,
    MetricResponse,
    MonitoringObservationResponse,
    MonitoringProtocolResponse,
    MonitoringReportResponse,
    ObservationCitationResponse,
    ProtocolQueryResponse,
    QuerySuggestionResponse,
)
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.monitoring.domain import (
    APPROVER_ROLES,
    CONTRIBUTOR_ROLES,
    READER_ROLES,
    CitationDraft,
    Device,
    MeasurementWindow,
    MonitoringObservation,
    MonitoringProtocol,
    ObservationDraft,
    Platform,
    ProtocolQuery,
    QuerySuggestion,
    ResultStatus,
    VerificationStatus,
)


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


def monitoring_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}",
        tags=["monitoring"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "/monitoring-protocols",
        response_model=MonitoringProtocolResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createMonitoringProtocol",
    )
    def create_protocol(
        project_id: UUID,
        payload: CreateMonitoringProtocolRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> MonitoringProtocolResponse:
        principal = _principal(request, authorization, project_id, CONTRIBUTOR_ROLES)
        result = _call(
            lambda: _application(request).create_protocol(
                principal,
                project_id=project_id,
                campaign_id=payload.campaign_id,
                market_profile_id=payload.market_profile_id,
                name=payload.name,
                platform=Platform(payload.platform),
                locale=payload.locale,
                device=Device(payload.device),
                sample_size=payload.sample_size,
                window_days=payload.window_days,
            )
        )
        return _protocol_response(result)

    @router.get(
        "/monitoring-protocols",
        response_model=list[MonitoringProtocolResponse],
        operation_id="listMonitoringProtocols",
    )
    def list_protocols(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[MonitoringProtocolResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_protocols(principal, project_id=project_id)
        )
        return [_protocol_response(item) for item in items]

    @router.post(
        "/monitoring-protocols/{protocol_id}/query-suggestions",
        response_model=QuerySuggestionResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="suggestMonitoringQuery",
    )
    def suggest_query(
        project_id: UUID,
        protocol_id: UUID,
        payload: CreateQuerySuggestionRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> QuerySuggestionResponse:
        principal = _principal(request, authorization, project_id, CONTRIBUTOR_ROLES)
        result = _call(
            lambda: _application(request).suggest_query(
                principal,
                project_id=project_id,
                protocol_id=protocol_id,
                query_text=payload.query_text,
                query_kind=payload.query_kind,
                rationale=payload.rationale,
            )
        )
        return _suggestion_response(result)

    @router.get(
        "/monitoring-protocols/{protocol_id}/query-suggestions",
        response_model=list[QuerySuggestionResponse],
        operation_id="listMonitoringQuerySuggestions",
    )
    def list_suggestions(
        project_id: UUID,
        protocol_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[QuerySuggestionResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_suggestions(
                principal, project_id=project_id, protocol_id=protocol_id
            )
        )
        return [_suggestion_response(item) for item in items]

    @router.post(
        "/monitoring-protocols/{protocol_id}/query-suggestions/{suggestion_id}/approve",
        response_model=ProtocolQueryResponse,
        operation_id="approveMonitoringQuerySuggestion",
    )
    def approve_suggestion(
        project_id: UUID,
        protocol_id: UUID,
        suggestion_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ProtocolQueryResponse:
        principal = _principal(request, authorization, project_id, APPROVER_ROLES)
        result = _call(
            lambda: _application(request).approve_suggestion(
                principal,
                project_id=project_id,
                protocol_id=protocol_id,
                suggestion_id=suggestion_id,
            )
        )
        return _query_response(result)

    @router.post(
        "/monitoring-protocols/{protocol_id}/approve",
        response_model=MonitoringProtocolResponse,
        operation_id="approveMonitoringProtocol",
    )
    def approve_protocol(
        project_id: UUID,
        protocol_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> MonitoringProtocolResponse:
        principal = _principal(request, authorization, project_id, APPROVER_ROLES)
        result = _call(
            lambda: _application(request).approve_protocol(
                principal, project_id=project_id, protocol_id=protocol_id
            )
        )
        return _protocol_response(result)

    @router.post(
        "/monitoring-protocols/{protocol_id}/freeze",
        response_model=MonitoringProtocolResponse,
        operation_id="freezeMonitoringProtocol",
    )
    def freeze_protocol(
        project_id: UUID,
        protocol_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> MonitoringProtocolResponse:
        principal = _principal(request, authorization, project_id, APPROVER_ROLES)
        result = _call(
            lambda: _application(request).freeze_protocol(
                principal, project_id=project_id, protocol_id=protocol_id
            )
        )
        return _protocol_response(result)

    @router.post(
        "/monitoring-protocols/{protocol_id}/observations",
        response_model=MonitoringObservationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="importMonitoringObservation",
    )
    def import_observation(
        project_id: UUID,
        protocol_id: UUID,
        payload: ImportObservationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> MonitoringObservationResponse:
        principal = _principal(request, authorization, project_id, CONTRIBUTOR_ROLES)
        result = _call(
            lambda: _application(request).import_observation(
                principal,
                project_id=project_id,
                protocol_id=protocol_id,
                draft=_observation_draft(payload),
                idempotency_key=idempotency_key,
            )
        )
        return _observation_response(result)

    @router.get(
        "/monitoring-protocols/{protocol_id}/observations",
        response_model=list[MonitoringObservationResponse],
        operation_id="listMonitoringObservations",
    )
    def list_observations(
        project_id: UUID,
        protocol_id: UUID,
        request: Request,
        measurement_window: MeasurementWindow | None = None,
        authorization: AuthorizationHeader = None,
    ) -> list[MonitoringObservationResponse]:
        principal = _principal(request, authorization, project_id, CONTRIBUTOR_ROLES)
        items = _call(
            lambda: _application(request).list_observations(
                principal,
                project_id=project_id,
                protocol_id=protocol_id,
                window=measurement_window,
            )
        )
        return [_observation_response(item) for item in items]

    @router.post(
        "/monitoring-protocols/{protocol_id}/metrics",
        response_model=MetricResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="computeMonitoringMetrics",
    )
    def compute_metrics(
        project_id: UUID,
        protocol_id: UUID,
        payload: ComputeMetricsRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> MetricResponse:
        principal = _principal(request, authorization, project_id, CONTRIBUTOR_ROLES)
        result = _call(
            lambda: _application(request).compute_metrics(
                principal,
                project_id=project_id,
                protocol_id=protocol_id,
                window=MeasurementWindow(payload.measurement_window),
            )
        )
        return metric_response(result)

    @router.get(
        "/monitoring-metrics",
        response_model=list[MetricResponse],
        operation_id="listMonitoringMetrics",
    )
    def list_metrics(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[MetricResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_metrics(principal, project_id=project_id)
        )
        return [metric_response(item) for item in items]

    @router.post(
        "/monitoring-reports",
        response_model=MonitoringReportResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="generateMonitoringReport",
    )
    def generate_report(
        project_id: UUID,
        payload: GenerateReportRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> MonitoringReportResponse:
        principal = _principal(request, authorization, project_id, CONTRIBUTOR_ROLES)
        result = _call(
            lambda: _application(request).generate_report(
                principal,
                project_id=project_id,
                metric_snapshot_id=payload.metric_snapshot_id,
                title=payload.title,
            )
        )
        return report_response(result)

    @router.get(
        "/monitoring-reports",
        response_model=list[MonitoringReportResponse],
        operation_id="listMonitoringReports",
    )
    def list_reports(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[MonitoringReportResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_reports(
                principal, project_id=project_id, approved_only=False
            )
        )
        return [report_response(item) for item in items]

    @router.post(
        "/monitoring-reports/{report_id}/approve",
        response_model=MonitoringReportResponse,
        operation_id="approveMonitoringReport",
    )
    def approve_report(
        project_id: UUID,
        report_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> MonitoringReportResponse:
        principal = _principal(request, authorization, project_id, APPROVER_ROLES)
        result = _call(
            lambda: _application(request).approve_report(
                principal, project_id=project_id, report_id=report_id
            )
        )
        return report_response(result)

    return router


def _protocol_response(item: MonitoringProtocol) -> MonitoringProtocolResponse:
    return MonitoringProtocolResponse(
        id=item.id, project_id=item.project_id, market_profile_id=item.market_profile_id,
        campaign_id=item.campaign_id,
        name=item.name, platform=item.platform.value, locale=item.locale,
        device=item.device.value, sample_size=item.sample_size, window_days=item.window_days,
        status=item.status.value, protocol_hash=item.protocol_hash, created_at=item.created_at,
        approved_at=item.approved_at, frozen_at=item.frozen_at,
    )


def _suggestion_response(item: QuerySuggestion) -> QuerySuggestionResponse:
    return QuerySuggestionResponse(
        id=item.id, project_id=item.project_id, protocol_id=item.protocol_id,
        query_text=item.query_text, query_kind=item.query_kind, rationale=item.rationale,
        status=item.status.value, monitoring_query_id=item.monitoring_query_id,
        created_at=item.created_at,
    )


def _query_response(item: ProtocolQuery) -> ProtocolQueryResponse:
    return ProtocolQueryResponse(**item.__dict__)


def _observation_draft(payload: ImportObservationRequest) -> ObservationDraft:
    return ObservationDraft(
        monitoring_query_id=payload.monitoring_query_id,
        measurement_window=MeasurementWindow(payload.measurement_window),
        sample_index=payload.sample_index, result_status=ResultStatus(payload.result_status),
        eligible=payload.eligible, ineligible_reasons=tuple(payload.ineligible_reasons),
        url_verification_status=VerificationStatus(payload.url_verification_status),
        recommendation_present=payload.recommendation_present,
        primary_product_mentioned=payload.primary_product_mentioned,
        competitor_mentioned=payload.competitor_mentioned, raw_answer=payload.raw_answer,
        raw_result=payload.raw_result,
        citations=tuple(
            CitationDraft(
                url=item.url, title=item.title,
                verification_status=VerificationStatus(item.verification_status),
                verified_at=item.verified_at, destination_id=item.destination_id,
                submission_id=item.submission_id,
            ) for item in payload.citations
        ),
        artifact_uri=payload.artifact_uri, artifact_hash=payload.artifact_hash,
        configured_model=payload.configured_model,
        provider_reported_model=payload.provider_reported_model,
        ui_surface=payload.ui_surface, ui_metadata=payload.ui_metadata,
        confounding_factors=tuple(payload.confounding_factors), observed_at=payload.observed_at,
    )


def _observation_response(item: MonitoringObservation) -> MonitoringObservationResponse:
    draft = item.draft
    return MonitoringObservationResponse(
        id=item.id, project_id=item.project_id, protocol_id=item.protocol_id,
        campaign_id=item.campaign_id,
        monitoring_query_id=draft.monitoring_query_id,
        measurement_window=draft.measurement_window.value, sample_index=draft.sample_index,
        result_status=draft.result_status.value, eligible=draft.eligible,
        ineligible_reasons=list(draft.ineligible_reasons),
        url_verification_status=draft.url_verification_status.value,
        recommendation_present=draft.recommendation_present,
        primary_product_mentioned=draft.primary_product_mentioned,
        competitor_mentioned=draft.competitor_mentioned, raw_answer=draft.raw_answer,
        raw_result=dict(draft.raw_result),
        citations=[
            ObservationCitationResponse(
                id=value.id, url=value.url, title=value.title,
                verification_status=value.verification_status.value,
                destination_id=value.destination_id, submission_id=value.submission_id,
                verified_placement=value.verified_placement,
            ) for value in item.citations
        ],
        artifact_uri=draft.artifact_uri, artifact_hash=draft.artifact_hash,
        configured_model=draft.configured_model,
        provider_reported_model=draft.provider_reported_model, ui_surface=draft.ui_surface,
        ui_metadata=dict(draft.ui_metadata),
        confounding_factors=list(draft.confounding_factors), observed_at=draft.observed_at,
        payload_hash=item.payload_hash, replayed=item.replayed, created_at=item.created_at,
    )
