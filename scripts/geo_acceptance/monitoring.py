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

from scripts.geo_acceptance.setup import AcceptanceSetup


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
        sample_size=1,
        window_days=28,
    )
    suggestion = application.suggest_query(
        setup.owner,
        project_id=setup.project_id,
        protocol_id=protocol.id,
        query_text="Which robotic lawn mower should I consider in Australia?",
        query_kind="recommendation",
        rationale="Represents a non-branded consumer recommendation question.",
    )
    query = application.approve_suggestion(
        setup.owner,
        project_id=setup.project_id,
        protocol_id=protocol.id,
        suggestion_id=suggestion.id,
    )
    application.approve_protocol(
        setup.owner, project_id=setup.project_id, protocol_id=protocol.id
    )
    protocol = application.freeze_protocol(
        setup.owner, project_id=setup.project_id, protocol_id=protocol.id
    )
    observation = application.import_observation(
        setup.owner,
        project_id=setup.project_id,
        protocol_id=protocol.id,
        draft=_observation(
            query_id=query.monitoring_query_id,
            window=MeasurementWindow.BASELINE,
            recommendation_present=False,
            product_mentioned=False,
        ),
        idempotency_key=f"acceptance-baseline-{setup.suffix}",
    )
    metric = application.compute_metrics(
        setup.owner,
        project_id=setup.project_id,
        protocol_id=protocol.id,
        window=MeasurementWindow.BASELINE,
    )
    return BaselineResult(application, protocol, query, observation, metric)


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
    observation = baseline.application.import_observation(
        setup.owner,
        project_id=setup.project_id,
        protocol_id=baseline.protocol.id,
        draft=_observation(
            query_id=baseline.query.monitoring_query_id,
            window=window,
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
        idempotency_key=f"acceptance-{window.value}-observation-{setup.suffix}",
    )
    metric = baseline.application.compute_metrics(
        setup.owner,
        project_id=setup.project_id,
        protocol_id=baseline.protocol.id,
        window=window,
    )
    return FollowUpResult(observation, metric)


def _observation(
    *,
    query_id: UUID,
    window: MeasurementWindow,
    recommendation_present: bool,
    product_mentioned: bool,
    citation: CitationDraft | None = None,
) -> ObservationDraft:
    return ObservationDraft(
        monitoring_query_id=query_id,
        measurement_window=window,
        sample_index=1,
        result_status=ResultStatus.SUCCEEDED,
        eligible=True,
        ineligible_reasons=(),
        url_verification_status=(
            VerificationStatus.PASSED if citation else VerificationStatus.UNKNOWN
        ),
        recommendation_present=recommendation_present,
        primary_product_mentioned=product_mentioned,
        competitor_mentioned=False,
        raw_answer="Controlled acceptance observation; not a live AI search result.",
        raw_result={"mode": "controlled_acceptance"},
        citations=(citation,) if citation else (),
        artifact_uri=None,
        artifact_hash=None,
        configured_model="controlled-observation",
        provider_reported_model=None,
        ui_surface="acceptance-harness",
        ui_metadata={"locale": "en-AU"},
        confounding_factors=("controlled_acceptance_data",),
        observed_at=datetime.now(UTC),
    )
