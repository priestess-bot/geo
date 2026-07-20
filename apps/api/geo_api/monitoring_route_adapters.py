"""Transport adapters shared by the internal monitoring route registrations."""

from __future__ import annotations

from geo_api.monitoring_contracts import (
    ImportOfficialReportRequest,
    ImportObservationRequest,
    MonitoringObservationResponse,
    MonitoringProtocolResponse,
    ObservationCitationResponse,
    OfficialReportImportResponse,
    OfficialReportRowResponse,
    ProtocolQueryResponse,
    QuerySuggestionResponse,
    VerifiedCitationTargetResponse,
)
from geo_api.monitoring_source_adapters import (
    model_identity,
    run_parameters,
    source_response,
    source_stratum_contract,
)
from geo_core.monitoring.domain import (
    CitationDraft,
    MeasurementWindow,
    MonitoringObservation,
    MonitoringProtocol,
    MonitoringRuleViolation,
    ObservationDraft,
    ProtocolQuery,
    QuerySuggestion,
    ResultStatus,
    VerificationStatus,
    VerifiedCitationTarget,
)
from geo_core.monitoring.official_reports import (
    OfficialReportImport,
    OfficialReportImportDraft,
    OfficialReportRuleViolation,
    OfficialReportRowDraft,
)
from geo_core.monitoring.source_contract import (
    CaptureMethod,
    ObservationPlatform,
    ObservationSource,
    ObservationSurface,
    RawEvidence,
    SurfaceKind,
)


def protocol_response(item: MonitoringProtocol) -> MonitoringProtocolResponse:
    return MonitoringProtocolResponse(
        id=item.id,
        project_id=item.project_id,
        market_profile_id=item.market_profile_id,
        campaign_id=item.campaign_id,
        name=item.name,
        platform=item.platform.value,
        locale=item.locale,
        device=item.device.value,
        sample_size=item.sample_size,
        window_days=item.window_days,
        minimum_valid_repeats=item.minimum_valid_repeats,
        status=item.status.value,
        protocol_hash=item.protocol_hash,
        created_at=item.created_at,
        approved_at=item.approved_at,
        frozen_at=item.frozen_at,
        source_strata=[source_stratum_contract(value) for value in item.source_strata],
        source_strata_hash=item.source_strata_hash,
        statistics_method_version=item.statistics_method_version,
        statistics_contract_version=item.statistics_contract_version,
        question_set_id=item.question_set_id,
        question_set_hash=item.question_set_hash,
        question_set_bound_by=item.question_set_bound_by,
        question_set_bound_at=item.question_set_bound_at,
    )


def suggestion_response(item: QuerySuggestion) -> QuerySuggestionResponse:
    return QuerySuggestionResponse(
        id=item.id,
        project_id=item.project_id,
        protocol_id=item.protocol_id,
        query_text=item.query_text,
        query_kind=item.query_kind,
        rationale=item.rationale,
        status=item.status.value,
        monitoring_query_id=item.monitoring_query_id,
        created_at=item.created_at,
        query_cluster_key=item.query_cluster_key,
    )


def query_response(item: ProtocolQuery) -> ProtocolQueryResponse:
    return ProtocolQueryResponse(**item.__dict__)


def citation_target_response(
    item: VerifiedCitationTarget,
) -> VerifiedCitationTargetResponse:
    return VerifiedCitationTargetResponse(**item.__dict__)


def observation_draft(payload: ImportObservationRequest, evidence: RawEvidence) -> ObservationDraft:
    source = ObservationSource(
        capture_method=CaptureMethod(payload.capture_method),
        platform=ObservationPlatform(payload.source.platform),
        surface=ObservationSurface(payload.source.surface),
        surface_kind=SurfaceKind(payload.source.surface_kind),
        platform_detail=payload.source.platform_detail,
        surface_detail=payload.source.surface_detail,
        configured_model=model_identity(payload.source.configured_model),
        reported_model=model_identity(payload.source.reported_model),
        run=run_parameters(payload.source.run),
        raw_evidence=evidence,
        citations_captured=True,
    )
    return ObservationDraft(
        monitoring_query_id=payload.monitoring_query_id,
        measurement_window=MeasurementWindow(payload.measurement_window),
        sample_index=payload.sample_index,
        result_status=ResultStatus(payload.result_status),
        requested_eligible=payload.requested_eligible,
        eligible=payload.requested_eligible,
        ineligible_reasons=tuple(payload.operator_ineligible_reasons),
        url_verification_status=VerificationStatus(payload.url_verification_status),
        recommendation_present=payload.recommendation_present,
        primary_product_mentioned=payload.primary_product_mentioned,
        competitor_mentioned=payload.competitor_mentioned,
        raw_answer=evidence.answer,
        raw_result=dict(evidence.inline_response or {}),
        citations=tuple(
            CitationDraft(
                url=item.url,
                title=item.title,
                verification_status=VerificationStatus.UNKNOWN,
                verified_at=None,
                destination_id=None,
                submission_id=item.submission_id,
            )
            for item in payload.citations
        ),
        artifact_uri=evidence.artifact_uri,
        artifact_hash=evidence.artifact_hash,
        configured_model=source.configured_model.value,
        provider_reported_model=source.reported_model.value,
        ui_surface=source.surface.value,
        ui_metadata=payload.ui_metadata,
        confounding_factors=tuple(payload.confounding_factors),
        observed_at=payload.observed_at,
        source=source,
    )


def observation_response(item: MonitoringObservation) -> MonitoringObservationResponse:
    draft = item.draft
    return MonitoringObservationResponse(
        id=item.id,
        project_id=item.project_id,
        protocol_id=item.protocol_id,
        campaign_id=item.campaign_id,
        monitoring_query_id=draft.monitoring_query_id,
        measurement_window=draft.measurement_window.value,
        sample_index=draft.sample_index,
        result_status=draft.result_status.value,
        requested_eligible=draft.requested_eligible,
        eligible=draft.eligible,
        ineligible_reasons=list(draft.ineligible_reasons),
        url_verification_status=draft.url_verification_status.value,
        recommendation_present=draft.recommendation_present,
        primary_product_mentioned=draft.primary_product_mentioned,
        competitor_mentioned=draft.competitor_mentioned,
        raw_answer=draft.raw_answer,
        raw_result=dict(draft.raw_result),
        citations=[
            ObservationCitationResponse(
                id=value.id,
                citation_index=value.citation_index,
                url=value.url,
                title=value.title,
                verification_status=value.verification_status.value,
                destination_id=value.destination_id,
                submission_id=value.submission_id,
                verified_placement=value.verified_placement,
            )
            for value in item.citations
        ],
        artifact_uri=draft.artifact_uri,
        artifact_hash=draft.artifact_hash,
        configured_model=draft.configured_model,
        provider_reported_model=draft.provider_reported_model,
        ui_surface=draft.ui_surface,
        ui_metadata=dict(draft.ui_metadata),
        confounding_factors=list(draft.confounding_factors),
        capture_method=draft.source.capture_method.value,
        source=source_response(draft.source),
        source_stratum=(
            source_stratum_contract(draft.source.stratum_key()) if draft.eligible else None
        ),
        source_stratum_hash=(
            None
            if draft.source.capture_method == CaptureMethod.UNKNOWN
            else draft.source_stratum_hash
        ),
        query_cluster_key=draft.query_cluster_key,
        captured_by=item.captured_by,
        observed_at=draft.observed_at,
        payload_hash=item.payload_hash,
        replayed=item.replayed,
        created_at=item.created_at,
    )


def official_report_draft(
    payload: ImportOfficialReportRequest, evidence: RawEvidence
) -> OfficialReportImportDraft:
    try:
        return OfficialReportImportDraft(
            campaign_id=payload.campaign_id,
            platform=ObservationPlatform(payload.platform),
            surface=ObservationSurface(payload.surface),
            platform_detail=payload.platform_detail,
            surface_detail=payload.surface_detail,
            artifact=evidence,
            parser_name=payload.parser_name,
            parser_version=payload.parser_version,
            report_period_start=payload.report_period_start,
            report_period_end=payload.report_period_end,
            account_ref=payload.account_ref,
        )
    except OfficialReportRuleViolation as error:
        raise MonitoringRuleViolation(str(error)) from error


def official_report_rows(
    payload: ImportOfficialReportRequest,
) -> tuple[OfficialReportRowDraft, ...]:
    try:
        return tuple(
            OfficialReportRowDraft(
                row_index=item.row_index,
                row_data=item.row_data,
                eligible=item.requested_eligible,
                ineligible_reasons=tuple(item.operator_ineligible_reasons),
            )
            for item in payload.rows
        )
    except OfficialReportRuleViolation as error:
        raise MonitoringRuleViolation(str(error)) from error


def official_report_response(
    item: OfficialReportImport,
) -> OfficialReportImportResponse:
    draft = item.draft
    assert draft.artifact.artifact_uri is not None
    assert draft.artifact.artifact_hash is not None
    return OfficialReportImportResponse(
        id=item.id,
        project_id=item.project_id,
        campaign_id=draft.campaign_id,
        capture_method="official_report_import",
        platform=draft.platform.value,
        surface=draft.surface.value,
        platform_detail=draft.platform_detail,
        surface_detail=draft.surface_detail,
        artifact_uri=draft.artifact.artifact_uri,
        artifact_hash=draft.artifact.artifact_hash,
        parser_name=draft.parser_name,
        parser_version=draft.parser_version,
        report_period_start=draft.report_period_start,
        report_period_end=draft.report_period_end,
        account_ref=draft.account_ref,
        payload_hash=item.payload_hash,
        imported_by=item.imported_by,
        rows=[
            OfficialReportRowResponse(
                id=row.id,
                row_index=row.draft.row_index,
                row_data=dict(row.draft.row_data),
                eligible=row.draft.eligible,
                ineligible_reasons=list(row.draft.ineligible_reasons),
                row_hash=row.row_hash,
                created_at=row.created_at,
            )
            for row in item.rows
        ],
        created_at=item.created_at,
        replayed=item.replayed,
    )
