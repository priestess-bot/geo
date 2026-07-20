from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
import os
from uuid import uuid4

import psycopg
import pytest

from tests.integration.monitoring_customer_projection_support import (
    assert_exact_customer_url_projection,
)
from tests.integration.monitoring_postgres_support import (
    cleanup as _cleanup,
    draft as _draft,
    isolated_minio_store as _isolated_minio_store,
    seed as _seed,
    seed_campaign_destinations as _seed_campaign_destinations,
    source as _source,
    synthetic_source as _synthetic_source,
)

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.artifact_evidence import S3RawArtifactVerifier
from geo_core.monitoring.domain import (
    Device,
    MeasurementWindow,
    MonitoringConflict,
    MonitoringNotFound,
    MonitoringPersistenceUnavailable,
    MonitoringRuleViolation,
    CitationDraft,
    Platform,
    VerificationStatus,
    calculate_metric_snapshot,
)
from geo_core.monitoring.postgres import PsycopgMonitoringUnitOfWorkFactory
from geo_core.monitoring.official_reports import (
    OfficialReportImportDraft,
    OfficialReportRowDraft,
)
from geo_core.monitoring.source_contract import (
    CaptureMethod,
    ObservationPlatform,
    ObservationSurface,
    RawEvidence,
    RawEvidenceKind,
)


APP_URL = os.getenv("GEO_ACCESS_TEST_DATABASE_URL", "").strip()
ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()
MINIO_IMAGE = "minio/minio:RELEASE.2025-01-20T14-49-07Z"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not APP_URL or not ADMIN_URL,
        reason="GEO_ACCESS_TEST_DATABASE_URL and GEO_ACCESS_TEST_ADMIN_DATABASE_URL are required",
    ),
]


def test_monitoring_rls_idempotency_immutability_and_frozen_metrics() -> None:
    tenant_id, identity_id, project_id, foreign_project_id = (uuid4(), uuid4(), uuid4(), uuid4())
    market_id, foreign_market_id = uuid4(), uuid4()
    campaign_id, other_campaign_id, product_id = uuid4(), uuid4(), uuid4()
    marker = uuid4().hex[:10]
    _seed(
        tenant_id=tenant_id,
        identity_id=identity_id,
        project_id=project_id,
        foreign_project_id=foreign_project_id,
        market_id=market_id,
        foreign_market_id=foreign_market_id,
        campaign_id=campaign_id,
        other_campaign_id=other_campaign_id,
        product_id=product_id,
        marker=marker,
    )
    principal = AccessPrincipal(
        identity_id,
        f"monitor-{marker}",
        tenant_id,
        (MembershipRecord(project_id, tenant_id, "owner"),),
        "development",
    )
    factory = PsycopgMonitoringUnitOfWorkFactory(APP_URL)
    service = MonitoringApplication(factory)
    manual_source = _source(CaptureMethod.MANUAL_UI)
    provider_source = _source(CaptureMethod.PROVIDER_API)
    proxy_source = _source(CaptureMethod.PROXY_GROUNDED_API)
    try:
        with psycopg.connect(APP_URL) as connection:
            bypass, superuser = connection.execute(
                "SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user"
            ).fetchone()
            assert not bypass and not superuser
            for statement in (
                "SELECT * FROM alembic_sql_checksum_ledger",
                "INSERT INTO alembic_sql_checksum_ledger "
                "(revision, upgrade_sha256, downgrade_sha256) "
                "VALUES ('attack', repeat('a', 64), repeat('b', 64))",
                "UPDATE alembic_sql_checksum_ledger SET upgrade_sha256 = repeat('a', 64)",
                "DELETE FROM alembic_sql_checksum_ledger",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(statement)
                connection.rollback()

        protocol = service.create_protocol(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            market_profile_id=market_id,
            name=f"Protocol {marker}",
            platform=Platform.CHATGPT_SEARCH,
            locale="en-AU",
            device=Device.DESKTOP,
            sample_size=3,
            minimum_valid_repeats=3,
            window_days=28,
            source_strata=(
                manual_source.stratum_key(),
                provider_source.stratum_key(),
                proxy_source.stratum_key(),
            ),
        )
        suggestion = service.suggest_query(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=protocol.id,
            query_text=f"best robot vacuum {marker}",
            query_kind="recommendation",
            rationale="captures commercial recommendation intent",
            query_cluster_key="robot-vacuum-recommendation",
        )
        query = service.approve_suggestion(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=protocol.id,
            suggestion_id=suggestion.id,
        )
        empty_suggestion = service.suggest_query(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=protocol.id,
            query_text=f"robot vacuum comparison {marker}",
            query_kind="comparison",
            rationale="proves a zero-member frozen metric manifest",
            query_cluster_key="robot-vacuum-empty",
        )
        empty_query = service.approve_suggestion(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=protocol.id,
            suggestion_id=empty_suggestion.id,
        )
        with psycopg.connect(ADMIN_URL) as admin:
            assert (
                admin.execute(
                    """SELECT count(*) FROM campaign_monitoring_queries
                   WHERE project_id = %s AND campaign_id = %s AND monitoring_query_id = %s""",
                    (project_id, campaign_id, query.monitoring_query_id),
                ).fetchone()[0]
                == 1
            )
        service.approve_protocol(
            principal, project_id=project_id, campaign_id=campaign_id, protocol_id=protocol.id
        )
        frozen = service.freeze_protocol(
            principal, project_id=project_id, campaign_id=campaign_id, protocol_id=protocol.id
        )
        (
            verified_url,
            verified_submission_id,
            verified_destination_id,
            unapproved_url,
        ) = _seed_campaign_destinations(
            project_id=project_id,
            campaign_id=campaign_id,
            identity_id=identity_id,
            marker=marker,
        )

        protocol_queries = service.list_protocol_queries(
            principal, project_id=project_id, campaign_id=campaign_id, protocol_id=frozen.id
        )
        citation_targets = service.list_citation_targets(
            principal, project_id=project_id, campaign_id=campaign_id, protocol_id=frozen.id
        )
        assert [item.monitoring_query_id for item in protocol_queries] == [
            query.monitoring_query_id,
            empty_query.monitoring_query_id,
        ]
        assert verified_submission_id in {item.submission_id for item in citation_targets}

        empty_metric = service.compute_metrics(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=frozen.id,
            window=MeasurementWindow.T28,
            source_stratum_hash=manual_source.stratum_key().canonical_hash(),
            query_cluster_key="robot-vacuum-empty",
        )
        assert empty_metric.status == "insufficient_evidence"
        assert empty_metric.sampled_sample_count == 0
        assert empty_metric.observation_membership_count == 0
        assert empty_metric.observation_membership_hash == (
            "e3b0c44298fc1c149afbf4c8996fb924" "27ae41e4649b934ca495991b7852b855"
        )
        with factory(principal) as unit_of_work:
            assert (
                unit_of_work.monitoring.list_metric_observation_memberships(
                    project_id=project_id,
                    campaign_id=campaign_id,
                    snapshot_ids=(empty_metric.id,),
                )
                == ()
            )
            assert unit_of_work.monitoring.list_metric_snapshot_observations(
                project_id=project_id,
                campaign_id=campaign_id,
                snapshot_ids=(empty_metric.id,),
            ) == {empty_metric.id: ()}

        included = _draft(
            query.monitoring_query_id,
            1,
            eligible=True,
            verified=True,
            source=manual_source,
            citation=CitationDraft(
                url=verified_url,
                title="Verified placement",
                verification_status=VerificationStatus.UNKNOWN,
                verified_at=None,
                submission_id=verified_submission_id,
            ),
        )
        unverified = _draft(
            query.monitoring_query_id,
            2,
            eligible=True,
            verified=False,
            source=manual_source,
        )
        ineligible = _draft(
            query.monitoring_query_id,
            3,
            eligible=False,
            verified=True,
            source=manual_source,
        )
        provider = _draft(
            query.monitoring_query_id,
            1,
            eligible=True,
            verified=False,
            source=provider_source,
        )
        proxy = _draft(
            query.monitoring_query_id,
            1,
            eligible=True,
            verified=False,
            source=proxy_source,
        )
        first = service.import_observation(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=frozen.id,
            draft=included,
            idempotency_key=f"{marker}-1",
        )
        assert first.citations[0].verified_placement
        assert first.citations[0].destination_id == verified_destination_id
        assert first.citations[0].verification_status == VerificationStatus.PASSED
        with pytest.raises(MonitoringRuleViolation, match="does not match"):
            service.import_observation(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=frozen.id,
                draft=_draft(
                    query.monitoring_query_id,
                    1,
                    eligible=True,
                    verified=True,
                    source=manual_source,
                    citation=CitationDraft(
                        url=f"{verified_url}/forged",
                        title=None,
                        verification_status=VerificationStatus.UNKNOWN,
                        verified_at=None,
                        submission_id=verified_submission_id,
                    ),
                ),
                idempotency_key=f"{marker}-forged",
            )
        replay = service.import_observation(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=frozen.id,
            draft=included,
            idempotency_key=f"{marker}-1",
        )
        second = service.import_observation(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=frozen.id,
            draft=unverified,
            idempotency_key=f"{marker}-2",
        )
        initial_metric = service.compute_metrics(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=frozen.id,
            window=MeasurementWindow.T28,
            source_stratum_hash=manual_source.stratum_key().canonical_hash(),
            query_cluster_key="robot-vacuum-recommendation",
        )
        assert initial_metric.status == "insufficient_evidence"
        assert initial_metric.sampled_sample_count == 2
        assert initial_metric.missing_sample_count == 1
        assert initial_metric.observation_membership_count == 2
        assert initial_metric.observation_membership_hash is not None
        initial_replay = service.compute_metrics(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=frozen.id,
            window=MeasurementWindow.T28,
            source_stratum_hash=manual_source.stratum_key().canonical_hash(),
            query_cluster_key="robot-vacuum-recommendation",
        )
        assert initial_replay.id == initial_metric.id
        assert initial_replay.result_hash == initial_metric.result_hash
        service.import_observation(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=frozen.id,
            draft=ineligible,
            idempotency_key=f"{marker}-3",
        )
        service.import_observation(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=frozen.id,
            draft=provider,
            idempotency_key=f"{marker}-provider-1",
        )
        service.import_observation(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=frozen.id,
            draft=proxy,
            idempotency_key=f"{marker}-proxy-1",
        )
        synthetic_source = _synthetic_source(project_id)
        synthetic_draft = _draft(
            query.monitoring_query_id,
            2,
            eligible=False,
            verified=False,
            source=synthetic_source,
        )
        with pytest.raises(MonitoringRuleViolation, match="public observation command"):
            service.import_observation(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=frozen.id,
                draft=synthetic_draft,
                idempotency_key=f"{marker}-synthetic-public",
            )
        with factory(principal) as unit_of_work:
            worker_only_draft = replace(synthetic_draft, query_cluster_key=query.query_cluster_key)
            with pytest.raises(MonitoringPersistenceUnavailable):
                unit_of_work.monitoring.import_observation(
                    project_id=project_id,
                    campaign_id=campaign_id,
                    protocol_id=frozen.id,
                    draft=worker_only_draft,
                    actor_id=identity_id,
                    idempotency_key=f"{marker}-synthetic-app-role",
                    payload_hash=worker_only_draft.payload_hash(),
                )
        assert replay.id == first.id and replay.replayed
        with pytest.raises(MonitoringConflict):
            service.import_observation(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=frozen.id,
                draft=_draft(
                    query.monitoring_query_id,
                    1,
                    eligible=True,
                    verified=False,
                    source=manual_source,
                ),
                idempotency_key=f"{marker}-1",
            )

        metric = service.compute_metrics(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=frozen.id,
            window=MeasurementWindow.T28,
            source_stratum_hash=manual_source.stratum_key().canonical_hash(),
            query_cluster_key="robot-vacuum-recommendation",
        )
        assert metric.expected_sample_count == 3
        assert metric.sampled_sample_count == 3
        assert metric.eligible_sample_count == 2
        assert metric.invalid_sample_count == 1
        assert metric.missing_sample_count == 0
        assert metric.status == "insufficient_evidence"
        assert metric.query_cluster_key == "robot-vacuum-recommendation"
        assert metric.query_count == 1
        assert metric.sufficient_query_count == 0
        assert metric.query_results[0].monitoring_query_id == query.monitoring_query_id
        assert not metric.query_results[0].meets_threshold
        assert metric.result_hash is not None
        assert metric.recommendation_share == 1
        assert metric.placement_citation_share == pytest.approx(0.5)
        assert metric.qualified_destination_coverage == pytest.approx(0.5)
        assert metric.verified_placement_coverage == 1
        assert metric.confounded_reasons == ()
        assert dict(metric.invalid_reason_counts) == {"manual_exclusion": 1}
        assert metric.observation_membership_count == 3
        assert metric.observation_membership_hash != initial_metric.observation_membership_hash

        with factory(principal) as unit_of_work:
            frozen_members = unit_of_work.monitoring.list_metric_observation_memberships(
                project_id=project_id,
                campaign_id=campaign_id,
                snapshot_ids=(initial_metric.id,),
            )
            frozen_inputs = unit_of_work.monitoring.list_metric_snapshot_observations(
                project_id=project_id,
                campaign_id=campaign_id,
                snapshot_ids=(initial_metric.id,),
            )[initial_metric.id]
            destination_state = unit_of_work.monitoring.campaign_destination_state(
                project_id=project_id, campaign_id=campaign_id
            )
        recomputed = calculate_metric_snapshot(
            snapshot_id=uuid4(),
            protocol=frozen,
            queries=protocol_queries,
            query_cluster_key="robot-vacuum-recommendation",
            window=MeasurementWindow.T28,
            source_stratum=manual_source.stratum_key(),
            observations=frozen_inputs,
            destination_state=destination_state,
            computed_at=datetime.now(UTC),
        )
        assert [item.observation_id for item in frozen_members] == [first.id, second.id]
        assert [item.id for item in frozen_inputs] == [first.id, second.id]
        assert recomputed.input_hash == initial_metric.input_hash
        assert recomputed.result_hash == initial_metric.result_hash
        assert recomputed.missing_sample_count == 1

        provider_metric = service.compute_metrics(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=frozen.id,
            window=MeasurementWindow.T28,
            source_stratum_hash=provider_source.stratum_key().canonical_hash(),
            query_cluster_key="robot-vacuum-recommendation",
        )
        proxy_metric = service.compute_metrics(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=frozen.id,
            window=MeasurementWindow.T28,
            source_stratum_hash=proxy_source.stratum_key().canonical_hash(),
            query_cluster_key="robot-vacuum-recommendation",
        )
        assert provider_metric.eligible_sample_count == 1
        assert proxy_metric.eligible_sample_count == 1
        assert provider_metric.status == proxy_metric.status == "insufficient_evidence"
        assert provider_metric.missing_sample_count == proxy_metric.missing_sample_count == 2
        assert (
            len(
                {
                    metric.source_stratum_hash,
                    provider_metric.source_stratum_hash,
                    proxy_metric.source_stratum_hash,
                }
            )
            == 3
        )

        report = service.generate_report(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            metric_snapshot_id=metric.id,
            title="Observational baseline",
        )
        approved = service.approve_report(
            principal, project_id=project_id, campaign_id=campaign_id, report_id=report.id
        )
        assert approved.status == "approved"
        assert "non-causal" in approved.methodology_statement
        assert "No directional conclusion" in approved.body
        for index, stratum_metric in enumerate((provider_metric, proxy_metric), start=1):
            stratum_report = service.generate_report(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                metric_snapshot_id=stratum_metric.id,
                title=f"Observational stratum {index}",
            )
            service.approve_report(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                report_id=stratum_report.id,
            )
        newest_manual_report = service.generate_report(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            metric_snapshot_id=metric.id,
            title="Observational baseline latest",
        )
        newest_manual = service.approve_report(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            report_id=newest_manual_report.id,
        )
        urls = service.list_verified_urls(principal, project_id=project_id, campaign_id=campaign_id)
        assert {item.url for item in urls} == {verified_url, unapproved_url}
        approved_projections = service.list_customer_approved_report_snapshots(
            principal, project_id=project_id, campaign_id=campaign_id
        )
        assert len(approved_projections) == 3
        assert {item.snapshot.id for item in approved_projections} == {
            metric.id,
            provider_metric.id,
            proxy_metric.id,
        }
        manual_projection = next(
            item for item in approved_projections if item.snapshot.id == metric.id
        )
        assert manual_projection.report.id == newest_manual.id
        assert manual_projection.report.id != approved.id
        assert approved_projections[0].report.id == newest_manual.id
        customer_campaign = service.get_customer_campaign(
            principal, project_id=project_id, campaign_id=campaign_id
        )
        assert customer_campaign.approved_report_count == 4
        assert_exact_customer_url_projection(
            admin_url=ADMIN_URL,
            service=service,
            principal=principal,
            project_id=project_id,
            campaign_id=campaign_id,
            other_campaign_id=other_campaign_id,
            marker=marker,
            verified_url=verified_url,
            verified_submission_id=verified_submission_id,
            verified_destination_id=verified_destination_id,
            member_observation=first,
            approved_snapshot=metric,
            latest_report=newest_manual,
        )

        with _isolated_minio_store() as store:
            stored = store.put_object(
                key=f"observation-artifacts/{project_id}/official-{marker}.csv",
                content=b"query,clicks\nrobot vacuum,7\n",
                content_type="text/csv",
            )
            artifact_service = MonitoringApplication(
                factory, artifact_verifier=S3RawArtifactVerifier(store)
            )
            verified_artifact = artifact_service.verify_raw_evidence(
                project_id=project_id,
                capture_method=CaptureMethod.OFFICIAL_REPORT_IMPORT,
                evidence=RawEvidence(
                    RawEvidenceKind.ARTIFACT,
                    artifact_uri=stored.uri,
                    artifact_hash=stored.content_hash,
                ),
            )
            assert verified_artifact.artifact_verified
            with pytest.raises(MonitoringRuleViolation, match="verification failed"):
                artifact_service.verify_raw_evidence(
                    project_id=project_id,
                    capture_method=CaptureMethod.OFFICIAL_REPORT_IMPORT,
                    evidence=RawEvidence(
                        RawEvidenceKind.ARTIFACT,
                        artifact_uri=stored.uri,
                        artifact_hash="0" * 64,
                    ),
                )
            official_draft = OfficialReportImportDraft(
                campaign_id=campaign_id,
                platform=ObservationPlatform.GOOGLE,
                surface=ObservationSurface.GOOGLE_GENERATIVE_AI_PERFORMANCE_REPORT,
                platform_detail=None,
                surface_detail=None,
                artifact=verified_artifact,
                parser_name="google-ai-performance-csv",
                parser_version="1.0.0",
                report_period_start=date(2026, 6, 1),
                report_period_end=date(2026, 6, 30),
                account_ref=f"account-{marker}",
            )
            official_rows = (
                OfficialReportRowDraft(0, {"query": "robot vacuum", "clicks": 7}),
                OfficialReportRowDraft(
                    1,
                    {"query": "unknown"},
                    eligible=False,
                    ineligible_reasons=("unsupported_row",),
                ),
            )
            official = artifact_service.import_official_report(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                draft=official_draft,
                rows=official_rows,
                idempotency_key=f"official-{marker}",
            )
            official_replay = artifact_service.import_official_report(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                draft=official_draft,
                rows=official_rows,
                idempotency_key=f"official-{marker}",
            )
            with pytest.raises(MonitoringConflict):
                artifact_service.import_official_report(
                    principal,
                    project_id=project_id,
                    campaign_id=campaign_id,
                    draft=official_draft,
                    rows=(OfficialReportRowDraft(0, {"query": "changed"}),),
                    idempotency_key=f"official-{marker}",
                )
        assert official_replay.id == official.id and official_replay.replayed
        assert [row.draft.row_index for row in official.rows] == [0, 1]
        assert service.list_official_reports(
            principal, project_id=project_id, campaign_id=campaign_id
        ) == (official,)

        with factory(principal) as unit_of_work:
            assert (
                unit_of_work.monitoring.list_protocols(
                    project_id=foreign_project_id, campaign_id=campaign_id
                )
                == ()
            )
        with pytest.raises(MonitoringNotFound):
            service.list_protocols(
                principal, project_id=foreign_project_id, campaign_id=campaign_id
            )

        with psycopg.connect(ADMIN_URL) as admin:
            with pytest.raises(psycopg.Error):
                admin.execute(
                    """
                    INSERT INTO monitoring_observation_citations
                      (project_id, observation_id, citation_index, url,
                       destination_id, submission_id, verification_status, verified_at)
                    SELECT %s, %s, 1, %s, %s, id, 'passed', verified_at
                    FROM publication_submissions WHERE id = %s
                    """,
                    (
                        project_id,
                        first.id,
                        f"{verified_url}/forged",
                        verified_destination_id,
                        verified_submission_id,
                    ),
                )
            admin.rollback()
            with pytest.raises(psycopg.Error):
                admin.execute(
                    """
                    INSERT INTO monitoring_official_report_imports
                      (project_id, campaign_id, capture_method, platform, surface,
                       artifact_uri, artifact_hash, parser_name, parser_version,
                       report_period_start, report_period_end, account_ref, row_count,
                       idempotency_key, payload_hash, imported_by)
                    VALUES (%s, %s, 'manual_ui', 'google',
                            'google_generative_ai_performance_report', %s, %s,
                            'forged', '1', DATE '2026-06-01', DATE '2026-06-30',
                            'forged', 1, %s, %s, %s)
                    """,
                    (
                        project_id,
                        campaign_id,
                        f"s3://geo-artifacts/observation-artifacts/{project_id}/forged.csv",
                        "f" * 64,
                        f"forged-official-{marker}",
                        "e" * 64,
                        identity_id,
                    ),
                )
            admin.rollback()
            with pytest.raises(psycopg.Error):
                admin.execute(
                    "UPDATE monitoring_official_report_rows SET eligible = false "
                    "WHERE import_id = %s",
                    (official.id,),
                )
            admin.rollback()
            with pytest.raises(psycopg.Error):
                admin.execute(
                    """
                    INSERT INTO monitoring_observations
                      (project_id, protocol_id, campaign_id, monitoring_query_id,
                       measurement_window, sample_index, result_status, eligible,
                       url_verification_status, configured_model, ui_surface,
                       observed_at, imported_by, idempotency_key, payload_hash)
                    VALUES (%s, %s, %s, %s, 'ad_hoc', 1, 'succeeded', true,
                            'unknown', 'test', 'test', clock_timestamp(), %s, %s, %s)
                    """,
                    (
                        project_id,
                        frozen.id,
                        other_campaign_id,
                        query.monitoring_query_id,
                        identity_id,
                        f"wrong-campaign-{marker}",
                        "e" * 64,
                    ),
                )
            admin.rollback()
            with pytest.raises(psycopg.Error):
                admin.execute(
                    "UPDATE monitoring_observations SET raw_answer = 'changed' WHERE id = %s",
                    (first.id,),
                )
            admin.rollback()
            with pytest.raises(psycopg.Error):
                admin.execute(
                    "UPDATE monitoring_protocols SET sample_size = 99 WHERE id = %s",
                    (frozen.id,),
                )
            admin.rollback()
            with pytest.raises(psycopg.Error):
                admin.execute(
                    """
                    INSERT INTO monitoring_protocols
                      (project_id, market_profile_id, name, platform, locale, device,
                       sample_size, window_days, created_by)
                    VALUES (%s, %s, %s, 'chatgpt_search', 'en-AU', 'desktop', 1, 28, %s)
                    """,
                    (project_id, foreign_market_id, f"Cross project {marker}", identity_id),
                )
    finally:
        _cleanup(tenant_id, identity_id)
