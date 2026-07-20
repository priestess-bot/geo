from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
from uuid import UUID, uuid4

import pytest

from geo_core.monitoring.domain import (
    METRIC_METHOD_VERSION,
    OBSERVATION_MEMBERSHIP_VERSION,
    REPORT_METHODOLOGY,
    STATISTICS_CONTRACT_VERSION,
    CampaignDestinationState,
    CitationDraft,
    Device,
    MeasurementWindow,
    MonitoringObservation,
    MonitoringProtocol,
    MonitoringRuleViolation,
    ObservationCitation,
    ObservationDraft,
    Platform,
    ProtocolQuery,
    ProtocolStatus,
    ResultStatus,
    VerificationStatus,
    calculate_metric_snapshot,
    canonical_hash,
    metric_observation_membership,
    observation_membership_hash,
    render_report,
    source_strata_inventory_hash,
)
from geo_core.monitoring.source_contract import (
    CaptureMethod,
    ClientKind,
    LEGACY_SOURCE_STRATUM_CONTRACT_VERSION,
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


NOW = datetime(2026, 7, 16, tzinfo=UTC)
DESTINATION_ID = UUID("00000000-0000-0000-0000-000000000071")
SUBMISSION_ID = UUID("00000000-0000-0000-0000-000000000072")
SOURCE = ObservationSource(
    capture_method=CaptureMethod.MANUAL_UI,
    platform=ObservationPlatform.OPENAI,
    surface=ObservationSurface.CHATGPT_SEARCH,
    surface_kind=SurfaceKind.CONSUMER_UI,
    platform_detail=None,
    surface_detail=None,
    configured_model=ModelIdentity(ModelIdentityState.DISCLOSED, "model-v1"),
    reported_model=ModelIdentity(ModelIdentityState.DISCLOSED, "model-v1"),
    run=ObservationRunParameters(
        engine="chatgpt",
        locale="en-AU",
        region="AU",
        language="en",
        device=ObservationDevice.DESKTOP,
        client_kind=ClientKind.BROWSER,
        search_enabled=True,
        search_mode=SearchMode.LIVE_WEB,
        prompt_text="Which product?",
    ),
    raw_evidence=RawEvidence(RawEvidenceKind.ANSWER, answer="Internal raw answer"),
    citations_captured=True,
)
STRATUM = SOURCE.stratum_key()
DEFAULT_DESTINATIONS = CampaignDestinationState(
    selected_destination_ids=frozenset({DESTINATION_ID}),
    qualified_destination_ids=frozenset({DESTINATION_ID}),
    verified_destination_ids=frozenset(),
)


@pytest.mark.parametrize(
    ("valid_count", "expected_status", "expected_missing"),
    (
        (0, "insufficient_evidence", 3),
        (1, "insufficient_evidence", 2),
        (2, "insufficient_evidence", 1),
        (3, "complete", 0),
    ),
)
def test_minimum_three_valid_repeats_is_enforced_per_query(
    valid_count: int, expected_status: str, expected_missing: int
) -> None:
    protocol = _protocol(sample_size=3, minimum_valid_repeats=3)
    query = _query(protocol, cluster="recommendation")
    observations = tuple(
        _observation(protocol, query, sample_index=index) for index in range(1, valid_count + 1)
    )

    metric = _snapshot(protocol, (query,), "recommendation", observations)

    assert metric.status == expected_status
    assert metric.eligible_sample_count == valid_count
    assert metric.sampled_sample_count == valid_count
    assert metric.invalid_sample_count == 0
    assert metric.missing_sample_count == expected_missing
    assert metric.invalid_reason_counts == ()
    assert metric.sufficient_query_count == int(valid_count == 3)
    assert metric.query_results[0].meets_threshold is (valid_count == 3)
    assert metric.observation_membership_version == OBSERVATION_MEMBERSHIP_VERSION
    assert metric.observation_membership_count == valid_count
    assert metric.observation_membership_hash is not None
    if valid_count == 0:
        assert metric.recommendation_share == Decimal("0.000000")
        assert metric.recommendation_ci_low == Decimal("0")
        assert metric.recommendation_ci_high == Decimal("1")
        assert metric.observation_membership_hash == hashlib.sha256(b"").hexdigest()


def test_metric_denominator_is_frozen_and_ineligible_or_unverified_samples_are_excluded() -> None:
    protocol = _protocol(sample_size=5, minimum_valid_repeats=4)
    query = _query(protocol, cluster="category")
    included = tuple(_observation(protocol, query, sample_index=index) for index in range(1, 4))
    unverified = _observation(
        protocol,
        query,
        sample_index=4,
        verified=False,
        destination_id=DESTINATION_ID,
    )
    ineligible = _observation(
        protocol,
        query,
        sample_index=5,
        eligible=False,
        ineligible_reasons=("manual_exclusion",),
    )
    other_campaign = replace(
        _observation(protocol, query, sample_index=1),
        id=uuid4(),
        campaign_id=uuid4(),
    )
    destination_state = CampaignDestinationState(
        selected_destination_ids=frozenset({DESTINATION_ID, uuid4()}),
        qualified_destination_ids=frozenset({DESTINATION_ID}),
        verified_destination_ids=frozenset({DESTINATION_ID}),
    )

    metric = _snapshot(
        protocol,
        (query,),
        "category",
        included + (unverified, ineligible, other_campaign),
        destinations=destination_state,
    )

    assert metric.expected_sample_count == 5
    assert metric.sampled_sample_count == 5
    assert metric.eligible_sample_count == 4
    assert metric.invalid_sample_count == 1
    assert metric.recommendation_share == Decimal("1.000000")
    assert metric.product_mention_share == Decimal("1.000000")
    assert metric.placement_citation_share == Decimal("0.000000")
    assert metric.qualified_destination_coverage == Decimal("0.500000")
    assert metric.verified_placement_coverage == Decimal("1.000000")
    assert metric.competitive_delta == Decimal("1.000000")
    assert metric.status == "complete"
    assert metric.confounded_reasons == ()


def test_five_repeat_protocol_requires_four_valid_results() -> None:
    protocol = _protocol(sample_size=5, minimum_valid_repeats=4)
    query = _query(protocol, cluster="category")
    three_valid = tuple(_observation(protocol, query, sample_index=index) for index in range(1, 4))
    four_valid = three_valid + (_observation(protocol, query, sample_index=4),)

    assert _snapshot(protocol, (query,), "category", three_valid).status == (
        "insufficient_evidence"
    )
    assert _snapshot(protocol, (query,), "category", four_valid).status == "complete"


def test_one_under_sampled_query_makes_the_entire_cluster_insufficient() -> None:
    protocol = _protocol(sample_size=3, minimum_valid_repeats=3)
    first = _query(protocol, cluster="category", ordinal=1, text="Best option?")
    second = _query(protocol, cluster="category", ordinal=2, text="Recommended option?")
    observations = tuple(
        _observation(protocol, first, sample_index=index) for index in range(1, 4)
    ) + tuple(_observation(protocol, second, sample_index=index) for index in range(1, 3))

    metric = _snapshot(protocol, (first, second), "category", observations)

    assert metric.status == "insufficient_evidence"
    assert metric.query_count == 2
    assert metric.sufficient_query_count == 1
    assert metric.expected_sample_count == 6
    assert metric.sampled_sample_count == 5
    assert metric.missing_sample_count == 1
    thresholds = {item.monitoring_query_id: item.meets_threshold for item in metric.query_results}
    assert thresholds == {
        first.monitoring_query_id: True,
        second.monitoring_query_id: False,
    }


def test_query_clusters_are_separate_analysis_strata() -> None:
    protocol = _protocol(sample_size=3, minimum_valid_repeats=3)
    category = _query(protocol, cluster="category", ordinal=1)
    comparison = _query(protocol, cluster="comparison", ordinal=2)
    category_observations = tuple(
        _observation(protocol, category, sample_index=index) for index in range(1, 4)
    )
    comparison_observations = tuple(
        _observation(protocol, comparison, sample_index=index) for index in range(1, 4)
    )

    category_metric = _snapshot(
        protocol,
        (category, comparison),
        "category",
        category_observations + comparison_observations,
    )
    comparison_metric = _snapshot(
        protocol,
        (category, comparison),
        "comparison",
        category_observations + comparison_observations,
    )

    assert category_metric.query_count == comparison_metric.query_count == 1
    assert category_metric.expected_sample_count == comparison_metric.expected_sample_count == 3
    assert category_metric.analysis_stratum_hash != comparison_metric.analysis_stratum_hash
    assert category_metric.input_hash != comparison_metric.input_hash


def test_missing_and_invalid_samples_are_not_conflated() -> None:
    protocol = _protocol(sample_size=5, minimum_valid_repeats=4)
    query = _query(protocol, cluster="category")
    valid = tuple(_observation(protocol, query, sample_index=index) for index in range(1, 4))
    invalid = _observation(
        protocol,
        query,
        sample_index=4,
        eligible=False,
        ineligible_reasons=("manual_exclusion", "uncontrolled_locale"),
    )

    metric = _snapshot(protocol, (query,), "category", valid + (invalid,))

    assert metric.status == "insufficient_evidence"
    assert metric.sampled_sample_count == 4
    assert metric.eligible_sample_count == 3
    assert metric.invalid_sample_count == 1
    assert metric.missing_sample_count == 1
    assert dict(metric.invalid_reason_counts) == {
        "manual_exclusion": 1,
        "uncontrolled_locale": 1,
    }
    assert sum(dict(metric.invalid_reason_counts).values()) > metric.invalid_sample_count


def test_wilson_interval_uses_exact_unrounded_proportion() -> None:
    protocol = _protocol(sample_size=3, minimum_valid_repeats=3)
    query = _query(protocol, cluster="category")
    observations = (
        _observation(protocol, query, sample_index=1, recommendation=True),
        _observation(protocol, query, sample_index=2, recommendation=False),
        _observation(protocol, query, sample_index=3, recommendation=False),
    )

    metric = _snapshot(protocol, (query,), "category", observations)

    assert metric.recommendation_share == Decimal("0.333333")
    assert metric.recommendation_ci_low == Decimal("0.061492")
    assert metric.recommendation_ci_high == Decimal("0.792340")


def test_same_frozen_input_has_reproducible_input_and_result_hashes() -> None:
    protocol = _protocol(sample_size=3, minimum_valid_repeats=3)
    query = _query(protocol, cluster="category")
    observations = tuple(_observation(protocol, query, sample_index=index) for index in range(1, 4))

    first = _snapshot(protocol, (query,), "category", observations)
    second = _snapshot(
        protocol,
        (query,),
        "category",
        tuple(reversed(observations)),
        snapshot_id=uuid4(),
        computed_at=NOW + timedelta(days=1),
    )
    changed_protocol = replace(protocol, protocol_hash="f" * 64)
    changed = _snapshot(changed_protocol, (query,), "category", observations)

    assert first.id != second.id
    assert first.computed_at != second.computed_at
    assert first.input_hash == second.input_hash
    assert first.result_hash == second.result_hash
    assert first.result_hash == canonical_hash(first.result_value())
    assert changed.input_hash != first.input_hash
    assert changed.result_hash != first.result_hash


def test_membership_manifest_is_ordered_and_observation_identity_is_frozen() -> None:
    protocol = _protocol(sample_size=3, minimum_valid_repeats=3)
    query = _query(protocol, cluster="category")
    observations = tuple(_observation(protocol, query, sample_index=index) for index in (3, 1, 2))
    snapshot_id = uuid4()

    membership = metric_observation_membership(snapshot_id, observations)
    manifest = "".join(
        f"{item.ordinal}:{item.observation_id}:{item.payload_hash}\n" for item in membership
    ).encode("ascii")
    original = _snapshot(protocol, (query,), "category", observations)
    replacement = replace(observations[0], id=uuid4())
    changed = _snapshot(protocol, (query,), "category", (replacement, *observations[1:]))

    assert [item.ordinal for item in membership] == [1, 2, 3]
    assert [
        next(obs.draft.sample_index for obs in observations if obs.id == item.observation_id)
        for item in membership
    ] == [1, 2, 3]
    assert observation_membership_hash(membership) == hashlib.sha256(manifest).hexdigest()
    assert replacement.payload_hash == observations[0].payload_hash
    assert changed.observation_membership_hash != original.observation_membership_hash
    assert changed.input_hash != original.input_hash
    assert changed.result_hash != original.result_hash


def test_threshold_is_part_of_the_reproducible_contract() -> None:
    protocol = _protocol(sample_size=5, minimum_valid_repeats=4, protocol_hash="a" * 64)
    strict = replace(protocol, minimum_valid_repeats=5, protocol_hash="b" * 64)
    query = _query(protocol, cluster="category")
    observations = tuple(_observation(protocol, query, sample_index=index) for index in range(1, 5))

    normal = _snapshot(protocol, (query,), "category", observations)
    strict_result = _snapshot(strict, (query,), "category", observations)

    assert normal.status == "complete"
    assert strict_result.status == "insufficient_evidence"
    assert normal.input_hash != strict_result.input_hash
    assert normal.result_hash != strict_result.result_hash


def test_historical_v2_result_hash_does_not_fabricate_membership_headers() -> None:
    protocol = _protocol(sample_size=3, minimum_valid_repeats=3)
    query = _query(protocol, cluster="category")
    current = _snapshot(protocol, (query,), "category", ())
    historical_draft = replace(
        current,
        result_hash=None,
        observation_membership_version=None,
        observation_membership_hash=None,
        observation_membership_count=None,
    )
    historical_hash = canonical_hash(historical_draft.result_value())

    historical = replace(historical_draft, result_hash=historical_hash)

    assert historical.result_hash == historical_hash
    assert "observation_membership_version" not in historical.result_value()
    assert "observation_membership_hash" not in historical.result_value()
    assert "observation_membership_count" not in historical.result_value()


def test_insufficient_report_refuses_directional_language() -> None:
    protocol = _protocol(sample_size=3, minimum_valid_repeats=3)
    query = _query(protocol, cluster="category")
    metric = _snapshot(
        protocol,
        (query,),
        "category",
        (_observation(protocol, query, sample_index=1),),
    )

    body, report_hash = render_report(metric, "Sparse result")

    lowered = body.lower()
    assert "insufficient evidence" in lowered
    assert "no directional conclusion" in lowered
    assert "improvement" not in lowered
    assert "decline" not in lowered
    assert "stable" not in lowered
    assert REPORT_METHODOLOGY in body
    assert len(report_hash) == 64


def test_complete_report_is_explicitly_observational_and_non_causal() -> None:
    protocol = _protocol(sample_size=3, minimum_valid_repeats=3)
    query = _query(protocol, cluster="category")
    observations = tuple(_observation(protocol, query, sample_index=index) for index in range(1, 4))
    metric = _snapshot(protocol, (query,), "category", observations)

    body, report_hash = render_report(metric, "T28 result")

    assert REPORT_METHODOLOGY in body
    assert "non-causal" in body
    assert len(report_hash) == 64


def test_unverified_or_unlinked_citations_are_not_counted() -> None:
    protocol = _protocol(sample_size=3, minimum_valid_repeats=3)
    query = _query(protocol, cluster="category")
    observations = (
        _observation(
            protocol,
            query,
            sample_index=1,
            destination_id=DESTINATION_ID,
            verified=False,
        ),
        _observation(
            protocol,
            query,
            sample_index=2,
            destination_id=DESTINATION_ID,
            verified_lineage=False,
        ),
        _observation(protocol, query, sample_index=3),
    )
    destination_state = replace(
        DEFAULT_DESTINATIONS, verified_destination_ids=frozenset({DESTINATION_ID})
    )

    metric = _snapshot(protocol, (query,), "category", observations, destinations=destination_state)

    assert metric.placement_citation_share == Decimal("0.000000")


def test_failed_samples_are_confounded_and_source_strata_are_isolated() -> None:
    other_source = replace(
        SOURCE,
        configured_model=ModelIdentity(ModelIdentityState.DISCLOSED, "other-model"),
        reported_model=ModelIdentity(ModelIdentityState.DISCLOSED, "other-model"),
    )
    protocol = _protocol(sample_size=5, minimum_valid_repeats=4, sources=(SOURCE, other_source))
    query = _query(protocol, cluster="category")
    valid = tuple(_observation(protocol, query, sample_index=index) for index in range(1, 5))
    failed = _observation(
        protocol,
        query,
        sample_index=5,
        eligible=False,
        result_status=ResultStatus.FAILED,
        ineligible_reasons=("provider_failure",),
    )
    other_stratum = _observation(protocol, query, sample_index=5, source=other_source)

    metric = _snapshot(
        protocol,
        (query,),
        "category",
        valid + (failed, other_stratum),
    )

    assert metric.status == "confounded"
    assert metric.eligible_sample_count == 4
    assert metric.invalid_sample_count == 1
    assert "failed_samples" in metric.confounded_reasons
    assert dict(metric.invalid_reason_counts) == {
        "capture_failed": 1,
        "provider_failure": 1,
    }


def test_other_source_details_create_independent_metric_denominators() -> None:
    first_source = replace(
        SOURCE,
        platform=ObservationPlatform.OTHER,
        surface=ObservationSurface.OTHER,
        surface_kind=SurfaceKind.CONSUMER_UI,
        platform_detail="answer-engine-a",
        surface_detail="consumer-surface-a",
    )
    second_source = replace(
        first_source,
        platform_detail="answer-engine-b",
        surface_detail="consumer-surface-b",
    )
    protocol = _protocol(
        sample_size=3,
        minimum_valid_repeats=3,
        sources=(first_source, second_source),
    )
    query = _query(protocol, cluster="category")
    first_observation = _observation(
        protocol, query, sample_index=1, source=first_source
    )
    second_observation = _observation(
        protocol, query, sample_index=1, source=second_source
    )

    first_metric = calculate_metric_snapshot(
        snapshot_id=uuid4(),
        protocol=protocol,
        queries=(query,),
        query_cluster_key="category",
        window=MeasurementWindow.BASELINE,
        source_stratum=first_source.stratum_key(),
        observations=(first_observation, second_observation),
        destination_state=DEFAULT_DESTINATIONS,
        computed_at=NOW,
    )
    second_metric = calculate_metric_snapshot(
        snapshot_id=uuid4(),
        protocol=protocol,
        queries=(query,),
        query_cluster_key="category",
        window=MeasurementWindow.BASELINE,
        source_stratum=second_source.stratum_key(),
        observations=(first_observation, second_observation),
        destination_state=DEFAULT_DESTINATIONS,
        computed_at=NOW,
    )

    assert first_metric.source_stratum_hash != second_metric.source_stratum_hash
    assert first_metric.sampled_sample_count == second_metric.sampled_sample_count == 1
    assert first_metric.observation_membership_count == 1
    assert second_metric.observation_membership_count == 1
    assert first_metric.observation_membership_hash != second_metric.observation_membership_hash


def test_legacy_v2_source_strata_cannot_create_new_statistics_snapshot() -> None:
    legacy = replace(
        STRATUM,
        source_contract_version=LEGACY_SOURCE_STRATUM_CONTRACT_VERSION,
    )
    protocol = replace(
        _protocol(sample_size=3, minimum_valid_repeats=3),
        source_strata=(legacy,),
        source_strata_hash=source_strata_inventory_hash((legacy,)),
    )
    query = _query(protocol, cluster="category")

    with pytest.raises(MonitoringRuleViolation, match="source stratum contract v3"):
        calculate_metric_snapshot(
            snapshot_id=uuid4(),
            protocol=protocol,
            queries=(query,),
            query_cluster_key="category",
            window=MeasurementWindow.BASELINE,
            source_stratum=legacy,
            observations=(),
            destination_state=DEFAULT_DESTINATIONS,
            computed_at=NOW,
        )


def _protocol(
    *,
    sample_size: int,
    minimum_valid_repeats: int,
    sources: tuple[ObservationSource, ...] = (SOURCE,),
    protocol_hash: str = "a" * 64,
) -> MonitoringProtocol:
    strata = tuple(source.stratum_key() for source in sources)
    return MonitoringProtocol(
        id=uuid4(),
        project_id=uuid4(),
        campaign_id=uuid4(),
        market_profile_id=uuid4(),
        name="Recommendation protocol",
        platform=Platform.CHATGPT_SEARCH,
        locale="en-AU",
        device=Device.DESKTOP,
        sample_size=sample_size,
        window_days=28,
        status=ProtocolStatus.FROZEN,
        protocol_hash=protocol_hash,
        created_at=NOW,
        approved_at=NOW,
        frozen_at=NOW,
        source_strata=strata,
        source_strata_hash=source_strata_inventory_hash(strata),
        minimum_valid_repeats=minimum_valid_repeats,
        statistics_method_version=METRIC_METHOD_VERSION,
        statistics_contract_version=STATISTICS_CONTRACT_VERSION,
    )


def _query(
    protocol: MonitoringProtocol,
    *,
    cluster: str,
    ordinal: int = 1,
    text: str = "Which product?",
) -> ProtocolQuery:
    return ProtocolQuery(
        id=uuid4(),
        project_id=protocol.project_id,
        protocol_id=protocol.id,
        monitoring_query_id=uuid4(),
        query_text=text,
        query_kind="recommendation",
        locale=protocol.locale,
        ordinal=ordinal,
        query_cluster_key=cluster,
    )


def _snapshot(
    protocol: MonitoringProtocol,
    queries: tuple[ProtocolQuery, ...],
    cluster: str,
    observations: tuple[MonitoringObservation, ...],
    *,
    destinations: CampaignDestinationState = DEFAULT_DESTINATIONS,
    snapshot_id: UUID | None = None,
    computed_at: datetime = NOW,
):
    return calculate_metric_snapshot(
        snapshot_id=snapshot_id or uuid4(),
        protocol=protocol,
        queries=queries,
        query_cluster_key=cluster,
        window=MeasurementWindow.BASELINE,
        source_stratum=STRATUM,
        observations=observations,
        destination_state=destinations,
        computed_at=computed_at,
    )


def _observation(
    protocol: MonitoringProtocol,
    query: ProtocolQuery,
    *,
    sample_index: int,
    eligible: bool = True,
    result_status: ResultStatus = ResultStatus.SUCCEEDED,
    ineligible_reasons: tuple[str, ...] = (),
    recommendation: bool = True,
    product_mentioned: bool = True,
    competitor_mentioned: bool = False,
    verified: bool = True,
    destination_id: UUID | None = None,
    submission_id: UUID = SUBMISSION_ID,
    verified_lineage: bool = True,
    confounding_factors: tuple[str, ...] = (),
    source: ObservationSource = SOURCE,
) -> MonitoringObservation:
    verification = VerificationStatus.PASSED if verified else VerificationStatus.FAILED
    citation_drafts: tuple[CitationDraft, ...] = ()
    citations: tuple[ObservationCitation, ...] = ()
    if destination_id is not None:
        citation_drafts = (
            CitationDraft(
                url="https://example.com/verified",
                title="Verified",
                verification_status=VerificationStatus.PASSED,
                verified_at=NOW,
                destination_id=destination_id,
                submission_id=submission_id,
            ),
        )
        citations = (
            ObservationCitation(
                id=uuid4(),
                citation_index=0,
                url="https://example.com/verified",
                title="Verified",
                verification_status=VerificationStatus.PASSED,
                destination_id=destination_id,
                submission_id=submission_id,
                verified_placement=verified_lineage,
            ),
        )
    draft = ObservationDraft(
        monitoring_query_id=query.monitoring_query_id,
        measurement_window=MeasurementWindow.BASELINE,
        sample_index=sample_index,
        result_status=result_status,
        requested_eligible=eligible,
        eligible=eligible,
        ineligible_reasons=ineligible_reasons,
        url_verification_status=verification,
        recommendation_present=recommendation,
        primary_product_mentioned=product_mentioned,
        competitor_mentioned=competitor_mentioned,
        raw_answer=source.raw_evidence.answer,
        raw_result=dict(source.raw_evidence.inline_response or {}),
        citations=citation_drafts,
        artifact_uri=None,
        artifact_hash=None,
        configured_model=source.configured_model.value,
        provider_reported_model=source.reported_model.value,
        ui_surface=source.surface.value,
        ui_metadata={},
        confounding_factors=confounding_factors,
        observed_at=NOW,
        source=source,
        query_cluster_key=query.query_cluster_key,
    )
    return MonitoringObservation(
        id=uuid4(),
        project_id=protocol.project_id,
        protocol_id=protocol.id,
        campaign_id=protocol.campaign_id,
        draft=draft,
        payload_hash=draft.payload_hash(),
        citations=citations,
        captured_by=uuid4(),
        created_at=NOW,
    )
