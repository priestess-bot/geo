"""Internal stable API for frozen protocols, observations, metrics and reports."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response, status

from geo_api.monitoring_dependencies import (
    authorize_monitoring_project as _principal,
    monitoring_application as _application,
    monitoring_call as _call,
)
from geo_api.monitoring_presenters import metric_response, report_response
from geo_api.monitoring_route_adapters import (
    citation_target_response as _citation_target_response,
    observation_draft as _observation_draft,
    observation_response as _observation_response,
    official_report_draft as _official_report_draft,
    official_report_response as _official_report_response,
    official_report_rows as _official_report_rows,
    protocol_response as _protocol_response,
    query_response as _query_response,
    suggestion_response as _suggestion_response,
)
from geo_api.monitoring_contracts import (
    ComputeMetricsRequest,
    BindQuestionSetRequest,
    CreateMonitoringProtocolRequest,
    CreateQuerySuggestionRequest,
    GenerateReportRequest,
    ImportOfficialReportRequest,
    ImportObservationRequest,
    MetricResponse,
    MonitoringObservationResponse,
    MonitoringProtocolResponse,
    MonitoringReportResponse,
    OfficialReportImportResponse,
    ProtocolQueryResponse,
    QuerySuggestionResponse,
    VerifiedCitationTargetResponse,
)
from geo_api.monitoring_source_adapters import (
    raw_evidence,
    source_stratum,
)
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.monitoring.domain import (
    APPROVER_ROLES,
    CONTRIBUTOR_ROLES,
    READER_ROLES,
    Device,
    MeasurementWindow,
    Platform,
)
from geo_core.monitoring.exporter import render_observation_csv
from geo_core.monitoring.source_contract import (
    CaptureMethod,
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
                minimum_valid_repeats=payload.minimum_valid_repeats,
                window_days=payload.window_days,
                source_strata=tuple(source_stratum(item) for item in payload.source_strata),
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
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[MonitoringProtocolResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_protocols(
                principal, project_id=project_id, campaign_id=campaign_id
            )
        )
        return [_protocol_response(item) for item in items]

    @router.post(
        "/monitoring-protocols/{protocol_id}/question-set-binding",
        response_model=MonitoringProtocolResponse,
        operation_id="bindMonitoringProtocolQuestionSet",
    )
    def bind_question_set(
        project_id: UUID,
        protocol_id: UUID,
        payload: BindQuestionSetRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> MonitoringProtocolResponse:
        principal = _principal(request, authorization, project_id, APPROVER_ROLES)
        result = _call(
            lambda: _application(request).bind_question_set(
                principal,
                project_id=project_id,
                campaign_id=payload.campaign_id,
                protocol_id=protocol_id,
                question_set_id=payload.question_set_id,
                confirmed_content_hash=payload.confirmed_content_hash,
            )
        )
        return _protocol_response(result)

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
                campaign_id=payload.campaign_id,
                protocol_id=protocol_id,
                query_text=payload.query_text,
                query_kind=payload.query_kind,
                rationale=payload.rationale,
                query_cluster_key=payload.query_cluster_key,
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
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[QuerySuggestionResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_suggestions(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
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
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ProtocolQueryResponse:
        principal = _principal(request, authorization, project_id, APPROVER_ROLES)
        result = _call(
            lambda: _application(request).approve_suggestion(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
                suggestion_id=suggestion_id,
            )
        )
        return _query_response(result)

    @router.get(
        "/monitoring-protocols/{protocol_id}/queries",
        response_model=list[ProtocolQueryResponse],
        operation_id="listMonitoringProtocolQueries",
    )
    def list_protocol_queries(
        project_id: UUID,
        protocol_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[ProtocolQueryResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_protocol_queries(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
            )
        )
        return [_query_response(item) for item in items]

    @router.get(
        "/monitoring-protocols/{protocol_id}/citation-targets",
        response_model=list[VerifiedCitationTargetResponse],
        operation_id="listMonitoringCitationTargets",
    )
    def list_citation_targets(
        project_id: UUID,
        protocol_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[VerifiedCitationTargetResponse]:
        principal = _principal(request, authorization, project_id, CONTRIBUTOR_ROLES)
        items = _call(
            lambda: _application(request).list_citation_targets(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
            )
        )
        return [_citation_target_response(item) for item in items]

    @router.post(
        "/monitoring-protocols/{protocol_id}/approve",
        response_model=MonitoringProtocolResponse,
        operation_id="approveMonitoringProtocol",
    )
    def approve_protocol(
        project_id: UUID,
        protocol_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> MonitoringProtocolResponse:
        principal = _principal(request, authorization, project_id, APPROVER_ROLES)
        result = _call(
            lambda: _application(request).approve_protocol(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
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
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> MonitoringProtocolResponse:
        principal = _principal(request, authorization, project_id, APPROVER_ROLES)
        result = _call(
            lambda: _application(request).freeze_protocol(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
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
                campaign_id=payload.campaign_id,
                protocol_id=protocol_id,
                draft=_observation_draft(
                    payload,
                    _application(request).verify_raw_evidence(
                        project_id=project_id,
                        capture_method=CaptureMethod(payload.capture_method),
                        evidence=raw_evidence(payload.source.raw_evidence),
                    ),
                ),
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
        campaign_id: UUID,
        measurement_window: MeasurementWindow | None = None,
        authorization: AuthorizationHeader = None,
    ) -> list[MonitoringObservationResponse]:
        principal = _principal(request, authorization, project_id, CONTRIBUTOR_ROLES)
        items = _call(
            lambda: _application(request).list_observations(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
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
                campaign_id=payload.campaign_id,
                protocol_id=protocol_id,
                window=MeasurementWindow(payload.measurement_window),
                source_stratum_hash=payload.source_stratum_hash,
                query_cluster_key=payload.query_cluster_key,
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
        campaign_id: UUID,
        authorization: AuthorizationHeader = None,
    ) -> list[MetricResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_metrics(
                principal, project_id=project_id, campaign_id=campaign_id
            )
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
                campaign_id=payload.campaign_id,
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
        campaign_id: UUID,
        authorization: AuthorizationHeader = None,
    ) -> list[MonitoringReportResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_reports(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                approved_only=False,
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
        campaign_id: UUID,
        authorization: AuthorizationHeader = None,
    ) -> MonitoringReportResponse:
        principal = _principal(request, authorization, project_id, APPROVER_ROLES)
        result = _call(
            lambda: _application(request).approve_report(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                report_id=report_id,
            )
        )
        return report_response(result)

    @router.post(
        "/monitoring-official-report-imports",
        response_model=OfficialReportImportResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="importMonitoringOfficialReport",
    )
    def import_official_report(
        project_id: UUID,
        payload: ImportOfficialReportRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> OfficialReportImportResponse:
        principal = _principal(request, authorization, project_id, CONTRIBUTOR_ROLES)
        evidence = raw_evidence(payload.artifact)
        verified = _call(
            lambda: _application(request).verify_raw_evidence(
                project_id=project_id,
                capture_method=CaptureMethod.OFFICIAL_REPORT_IMPORT,
                evidence=evidence,
            )
        )
        draft = _call(lambda: _official_report_draft(payload, verified))
        rows = _call(lambda: _official_report_rows(payload))
        result = _call(
            lambda: _application(request).import_official_report(
                principal,
                project_id=project_id,
                campaign_id=payload.campaign_id,
                draft=draft,
                rows=rows,
                idempotency_key=idempotency_key,
            )
        )
        return _official_report_response(result)

    @router.get(
        "/monitoring-official-report-imports",
        response_model=list[OfficialReportImportResponse],
        operation_id="listMonitoringOfficialReports",
    )
    def list_official_reports(
        project_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[OfficialReportImportResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_official_reports(
                principal, project_id=project_id, campaign_id=campaign_id
            )
        )
        return [_official_report_response(item) for item in items]

    @router.get(
        "/geo/campaigns/{campaign_id}/monitoring-observations.csv",
        response_class=Response,
        operation_id="exportMonitoringObservationsCsv",
    )
    def export_observations_csv(
        project_id: UUID,
        campaign_id: UUID,
        request: Request,
        protocol_id: UUID | None = None,
        measurement_window: MeasurementWindow | None = None,
        authorization: AuthorizationHeader = None,
    ) -> Response:
        principal = _principal(request, authorization, project_id, CONTRIBUTOR_ROLES)
        items = _call(
            lambda: _application(request).list_campaign_observations(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
                window=measurement_window,
            )
        )
        content = render_observation_csv(items)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="monitoring-observations-{campaign_id}.csv"'
                )
            },
        )

    return router
