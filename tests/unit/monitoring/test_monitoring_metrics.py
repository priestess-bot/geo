from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from geo_core.monitoring.domain import (
    REPORT_METHODOLOGY,
    CampaignDestinationState,
    CitationDraft,
    Device,
    MeasurementWindow,
    MonitoringObservation,
    MonitoringProtocol,
    ObservationCitation,
    ObservationDraft,
    Platform,
    ProtocolStatus,
    ResultStatus,
    VerificationStatus,
    calculate_metric_snapshot,
    render_report,
)


NOW = datetime(2026, 7, 16, tzinfo=UTC)


def test_metric_denominator_is_frozen_and_ineligible_or_unverified_samples_are_excluded() -> None:
    project_id, protocol_id, campaign_id, market_id = uuid4(), uuid4(), uuid4(), uuid4()
    destination_id, submission_id = uuid4(), uuid4()
    protocol = MonitoringProtocol(
        protocol_id,
        project_id,
        campaign_id,
        market_id,
        "Recommendation protocol",
        Platform.CHATGPT_SEARCH,
        "en-AU",
        Device.DESKTOP,
        2,
        28,
        ProtocolStatus.FROZEN,
        "a" * 64,
        NOW,
        NOW,
        NOW,
    )
    included = _observation(
        project_id=project_id,
        protocol_id=protocol_id,
        campaign_id=campaign_id,
        sample_index=1,
        verified=True,
        eligible=True,
    )
    unverified = _observation(
        project_id=project_id,
        protocol_id=protocol_id,
        campaign_id=campaign_id,
        sample_index=2,
        verified=False,
        eligible=True,
        destination_id=destination_id,
        submission_id=submission_id,
    )
    ineligible = _observation(
        project_id=project_id,
        protocol_id=protocol_id,
        campaign_id=campaign_id,
        sample_index=2,
        verified=True,
        eligible=False,
    )
    other_campaign = _observation(
        project_id=project_id,
        protocol_id=protocol_id,
        campaign_id=uuid4(),
        sample_index=1,
        verified=True,
        eligible=True,
    )

    metric = calculate_metric_snapshot(
        snapshot_id=uuid4(),
        protocol=protocol,
        query_count=1,
        window=MeasurementWindow.BASELINE,
        observations=(included, unverified, ineligible, other_campaign),
        destination_state=CampaignDestinationState(
            selected_destination_ids=frozenset({destination_id, uuid4()}),
            qualified_destination_ids=frozenset({destination_id}),
            verified_destination_ids=frozenset({destination_id}),
        ),
        computed_at=NOW,
    )

    assert metric.expected_sample_count == 2
    assert metric.eligible_sample_count == 2
    assert metric.recommendation_share == Decimal("1.000000")
    assert metric.product_mention_share == Decimal("1.000000")
    assert metric.placement_citation_share == Decimal("0.000000")
    assert metric.qualified_destination_coverage == Decimal("0.500000")
    assert metric.verified_placement_coverage == Decimal("1.000000")
    assert metric.competitive_delta == Decimal("1.000000")
    assert metric.status == "complete"
    assert metric.confounded_reasons == ()


def test_report_is_explicitly_observational_and_non_causal() -> None:
    protocol = MonitoringProtocol(
        uuid4(), uuid4(), uuid4(), uuid4(), "P", Platform.GOOGLE_SEARCH, "en-AU",
        Device.MOBILE, 1, 28, ProtocolStatus.FROZEN, "b" * 64, NOW, NOW, NOW,
    )
    observation = _observation(
        project_id=protocol.project_id,
        protocol_id=protocol.id,
        campaign_id=protocol.campaign_id,
        sample_index=1,
        verified=True,
        eligible=True,
    )
    metric = calculate_metric_snapshot(
        snapshot_id=uuid4(), protocol=protocol, query_count=1,
        window=MeasurementWindow.T28, observations=(observation,),
        destination_state=CampaignDestinationState(
            frozenset({uuid4()}), frozenset({uuid4()}), frozenset()
        ),
        computed_at=NOW,
    )

    body, report_hash = render_report(metric, "T28 result")

    assert REPORT_METHODOLOGY in body
    assert "non-causal" in body
    assert len(report_hash) == 64


def test_failed_and_mixed_collection_windows_are_confounded() -> None:
    campaign_id = uuid4()
    protocol = MonitoringProtocol(
        uuid4(), uuid4(), campaign_id, uuid4(), "Mixed", Platform.GEMINI, "en-AU",
        Device.DESKTOP, 2, 28, ProtocolStatus.FROZEN, "c" * 64, NOW, NOW, NOW,
    )
    first = _observation(
        project_id=protocol.project_id,
        protocol_id=protocol.id,
        campaign_id=campaign_id,
        sample_index=1,
        verified=True,
        eligible=True,
    )
    mixed_draft = replace(first.draft, sample_index=2, configured_model="other-model")
    mixed = replace(
        first, id=uuid4(), draft=mixed_draft, payload_hash=mixed_draft.payload_hash()
    )
    failed_draft = replace(
        first.draft,
        sample_index=3,
        result_status=ResultStatus.FAILED,
        eligible=False,
        ineligible_reasons=("provider_failure",),
    )
    failed = replace(
        first, id=uuid4(), draft=failed_draft, payload_hash=failed_draft.payload_hash()
    )
    destination_id = uuid4()

    metric = calculate_metric_snapshot(
        snapshot_id=uuid4(),
        protocol=protocol,
        query_count=1,
        window=MeasurementWindow.BASELINE,
        observations=(first, mixed, failed),
        destination_state=CampaignDestinationState(
            frozenset({destination_id}), frozenset({destination_id}), frozenset()
        ),
        computed_at=NOW,
    )

    assert metric.status == "confounded"
    assert "failed_samples" in metric.confounded_reasons
    assert "mixed_collection_configuration" in metric.confounded_reasons


def _observation(
    *,
    project_id: object,
    protocol_id: object,
    campaign_id: object,
    sample_index: int,
    verified: bool,
    eligible: bool,
    destination_id: object | None = None,
    submission_id: object | None = None,
) -> MonitoringObservation:
    query_id = uuid4()
    verification = VerificationStatus.PASSED if verified else VerificationStatus.FAILED
    citation_drafts = ()
    citations = ()
    if destination_id is not None:
        citation_drafts = (
            CitationDraft(
                "https://example.com/verified",
                "Verified",
                VerificationStatus.PASSED,
                NOW,
                destination_id,
                submission_id,
            ),
        )
        citations = (
            ObservationCitation(
                uuid4(), "https://example.com/verified", "Verified",
                VerificationStatus.PASSED, destination_id, submission_id, True,
            ),
        )
    draft = ObservationDraft(
        monitoring_query_id=query_id,
        measurement_window=MeasurementWindow.BASELINE,
        sample_index=sample_index,
        result_status=ResultStatus.SUCCEEDED,
        eligible=eligible,
        ineligible_reasons=() if eligible else ("manual_exclusion",),
        url_verification_status=verification,
        recommendation_present=True,
        primary_product_mentioned=True,
        competitor_mentioned=False,
        raw_answer="Internal raw answer",
        raw_result={"internal": True},
        citations=citation_drafts,
        artifact_uri=None,
        artifact_hash=None,
        configured_model="model-v1",
        provider_reported_model="model-v1",
        ui_surface="search",
        ui_metadata={},
        confounding_factors=(),
        observed_at=NOW,
    )
    return MonitoringObservation(
        uuid4(), project_id, protocol_id, campaign_id, draft, draft.payload_hash(), citations, NOW
    )
