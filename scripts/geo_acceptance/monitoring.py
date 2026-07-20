"""Frozen monitoring baseline and controlled follow-up observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.domain import (
    CitationDraft,
    Device,
    MeasurementWindow,
    MetricSnapshot,
    MonitoringObservation,
    MonitoringProtocol,
    ObservationDraft,
    Platform,
    ProtocolQuery,
    ResultStatus,
    VerificationStatus,
)
from geo_core.monitoring.postgres import PsycopgMonitoringUnitOfWorkFactory
from geo_core.monitoring.source_contract import (
    CaptureMethod,
    ClientKind,
    ModelIdentity,
    ModelIdentityState,
    ObservationDevice,
    ObservationPlatform,
    ObservationRunParameters,
    ObservationSource,
    ObservationSurface,
    RawEvidence,
    RawEvidenceKind,
    SearchMode,
    SurfaceKind,
)

from scripts.geo_acceptance.setup import AcceptanceSetup


SAMPLE_SIZE = 3
MINIMUM_VALID_REPEATS = 3
QUERY_CLUSTER_KEY = "recommendation-consideration"
CONTROLLED_MODEL = "controlled-observation"
CONTROLLED_PROMPT = "Which robotic lawn mower should I consider in Australia?"


@dataclass(frozen=True)
class BaselineResult:
    application: MonitoringApplication
    protocol: MonitoringProtocol
    query: ProtocolQuery
    observation: MonitoringObservation
    metric: MetricSnapshot


@dataclass(frozen=True)
class FollowUpResult:
    observation: MonitoringObservation
    metric: MetricSnapshot


def run_baseline(setup: AcceptanceSetup, *, app_database_url: str) -> BaselineResult:
    application = MonitoringApplication(
        PsycopgMonitoringUnitOfWorkFactory(app_database_url)
    )
    protocol = application.create_protocol(
        setup.owner,
        project_id=setup.project_id,
        campaign_id=setup.campaign.id,
        market_profile_id=setup.market.id,
        name=f"Controlled recommendation protocol {setup.suffix}",
        platform=Platform.CHATGPT_SEARCH,
        locale="en-AU",
        device=Device.DESKTOP,
        sample_size=SAMPLE_SIZE,
        minimum_valid_repeats=MINIMUM_VALID_REPEATS,
        window_days=28,
        source_strata=(_source("Controlled source inventory.").stratum_key(),),
    )
    suggestion = application.suggest_query(
        setup.owner,
        project_id=setup.project_id,
        campaign_id=setup.campaign.id,
        protocol_id=protocol.id,
        query_text=CONTROLLED_PROMPT,
        query_kind="recommendation",
        rationale="Represents a non-branded consumer recommendation question.",
        query_cluster_key=QUERY_CLUSTER_KEY,
    )
    query = application.approve_suggestion(
        setup.owner,
        project_id=setup.project_id,
        campaign_id=setup.campaign.id,
        protocol_id=protocol.id,
        suggestion_id=suggestion.id,
    )
    application.approve_protocol(
        setup.owner,
        project_id=setup.project_id,
        campaign_id=setup.campaign.id,
        protocol_id=protocol.id,
    )
    protocol = application.freeze_protocol(
        setup.owner,
        project_id=setup.project_id,
        campaign_id=setup.campaign.id,
        protocol_id=protocol.id,
    )
    observations = tuple(
        application.import_observation(
            setup.owner,
            project_id=setup.project_id,
            campaign_id=setup.campaign.id,
            protocol_id=protocol.id,
            draft=_observation(
                query_id=query.monitoring_query_id,
                window=MeasurementWindow.BASELINE,
                sample_index=sample_index,
                recommendation_present=False,
                product_mentioned=False,
            ),
            idempotency_key=(
                f"acceptance-baseline-{sample_index}-{setup.suffix}"
            ),
        )
        for sample_index in range(1, SAMPLE_SIZE + 1)
    )
    metric = application.compute_metrics(
        setup.owner,
        project_id=setup.project_id,
        campaign_id=setup.campaign.id,
        protocol_id=protocol.id,
        window=MeasurementWindow.BASELINE,
        source_stratum_hash=protocol.source_strata[0].canonical_hash(),
        query_cluster_key=QUERY_CLUSTER_KEY,
    )
    return BaselineResult(application, protocol, query, observations[0], metric)


FOLLOW_UP_WINDOWS = (
    MeasurementWindow.T28,
    MeasurementWindow.T56,
    MeasurementWindow.T84,
)


def run_follow_up(
    setup: AcceptanceSetup,
    baseline: BaselineResult,
    *,
    window: MeasurementWindow,
    submitted_url: str,
    submission_id: UUID,
) -> FollowUpResult:
    if window not in FOLLOW_UP_WINDOWS:
        raise ValueError("follow-up window must be T+28, T+56 or T+84")
    observations = tuple(
        baseline.application.import_observation(
            setup.owner,
            project_id=setup.project_id,
            campaign_id=setup.campaign.id,
            protocol_id=baseline.protocol.id,
            draft=_observation(
                query_id=baseline.query.monitoring_query_id,
                window=window,
                sample_index=sample_index,
                recommendation_present=True,
                product_mentioned=True,
                citation=CitationDraft(
                    url=submitted_url,
                    title="Controlled ADVINSYS acceptance placement",
                    verification_status=VerificationStatus.PASSED,
                    verified_at=datetime.now(UTC),
                    destination_id=setup.destinations[0].id,
                    submission_id=submission_id,
                ),
            ),
            idempotency_key=(
                f"acceptance-{window.value}-{sample_index}-observation-{setup.suffix}"
            ),
        )
        for sample_index in range(1, SAMPLE_SIZE + 1)
    )
    metric = baseline.application.compute_metrics(
        setup.owner,
        project_id=setup.project_id,
        campaign_id=setup.campaign.id,
        protocol_id=baseline.protocol.id,
        window=window,
        source_stratum_hash=baseline.protocol.source_strata[0].canonical_hash(),
        query_cluster_key=QUERY_CLUSTER_KEY,
    )
    return FollowUpResult(observations[0], metric)


def _observation(
    *,
    query_id: UUID,
    window: MeasurementWindow,
    sample_index: int,
    recommendation_present: bool,
    product_mentioned: bool,
    citation: CitationDraft | None = None,
) -> ObservationDraft:
    raw_answer = (
        f"Controlled manual acceptance observation {sample_index}; "
        "this is not a live AI search result."
    )
    source = _source(raw_answer)
    return ObservationDraft(
        monitoring_query_id=query_id,
        measurement_window=window,
        sample_index=sample_index,
        result_status=ResultStatus.SUCCEEDED,
        requested_eligible=True,
        eligible=True,
        ineligible_reasons=(),
        url_verification_status=(
            VerificationStatus.PASSED if citation else VerificationStatus.UNKNOWN
        ),
        recommendation_present=recommendation_present,
        primary_product_mentioned=product_mentioned,
        competitor_mentioned=False,
        raw_answer=raw_answer,
        raw_result={"mode": "controlled_acceptance"},
        citations=(citation,) if citation else (),
        artifact_uri=None,
        artifact_hash=None,
        configured_model=CONTROLLED_MODEL,
        provider_reported_model=None,
        ui_surface=ObservationSurface.CHATGPT_SEARCH.value,
        ui_metadata={"locale": "en-AU"},
        confounding_factors=("controlled_acceptance_data",),
        observed_at=datetime.now(UTC),
        source=source,
        query_cluster_key=QUERY_CLUSTER_KEY,
    )


def _source(raw_answer: str) -> ObservationSource:
    return ObservationSource(
        capture_method=CaptureMethod.MANUAL_UI,
        platform=ObservationPlatform.OPENAI,
        surface=ObservationSurface.CHATGPT_SEARCH,
        surface_kind=SurfaceKind.CONSUMER_UI,
        platform_detail=None,
        surface_detail=None,
        configured_model=ModelIdentity(
            ModelIdentityState.DISCLOSED, CONTROLLED_MODEL
        ),
        reported_model=ModelIdentity(ModelIdentityState.NOT_DISCLOSED),
        run=ObservationRunParameters(
            engine="chatgpt",
            locale="en-AU",
            region="AU",
            language="en",
            device=ObservationDevice.DESKTOP,
            client_kind=ClientKind.BROWSER,
            search_enabled=True,
            search_mode=SearchMode.LIVE_WEB,
            prompt_text=CONTROLLED_PROMPT,
            adapter_name="controlled-acceptance-manual-record",
            adapter_version="1",
        ),
        raw_evidence=RawEvidence(RawEvidenceKind.ANSWER, answer=raw_answer),
        citations_captured=True,
    )
