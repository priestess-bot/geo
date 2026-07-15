from __future__ import annotations

from datetime import UTC, datetime
import os
from uuid import UUID, uuid4

import psycopg
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.domain import (
    Device,
    MeasurementWindow,
    MonitoringConflict,
    MonitoringNotFound,
    MonitoringRuleViolation,
    CitationDraft,
    ObservationDraft,
    Platform,
    ResultStatus,
    VerificationStatus,
)
from geo_core.monitoring.postgres import PsycopgMonitoringUnitOfWorkFactory


APP_URL = os.getenv("GEO_ACCESS_TEST_DATABASE_URL", "").strip()
ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not APP_URL or not ADMIN_URL,
        reason="GEO_ACCESS_TEST_DATABASE_URL and GEO_ACCESS_TEST_ADMIN_DATABASE_URL are required",
    ),
]


def test_monitoring_rls_idempotency_immutability_and_frozen_metrics() -> None:
    tenant_id, identity_id, project_id, foreign_project_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
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
            window_days=28,
        )
        suggestion = service.suggest_query(
            principal,
            project_id=project_id,
            protocol_id=protocol.id,
            query_text=f"best robot vacuum {marker}",
            query_kind="recommendation",
            rationale="captures commercial recommendation intent",
        )
        query = service.approve_suggestion(
            principal,
            project_id=project_id,
            protocol_id=protocol.id,
            suggestion_id=suggestion.id,
        )
        with psycopg.connect(ADMIN_URL) as admin:
            assert admin.execute(
                """SELECT count(*) FROM campaign_monitoring_queries
                   WHERE project_id = %s AND campaign_id = %s AND monitoring_query_id = %s""",
                (project_id, campaign_id, query.monitoring_query_id),
            ).fetchone()[0] == 1
        service.approve_protocol(
            principal, project_id=project_id, protocol_id=protocol.id
        )
        frozen = service.freeze_protocol(
            principal, project_id=project_id, protocol_id=protocol.id
        )
        verified_url, verified_submission_id, verified_destination_id = _seed_campaign_destinations(
            project_id=project_id,
            campaign_id=campaign_id,
            identity_id=identity_id,
            marker=marker,
        )

        protocol_queries = service.list_protocol_queries(
            principal, project_id=project_id, protocol_id=frozen.id
        )
        citation_targets = service.list_citation_targets(
            principal, project_id=project_id, protocol_id=frozen.id
        )
        assert [item.monitoring_query_id for item in protocol_queries] == [
            query.monitoring_query_id
        ]
        assert [item.submission_id for item in citation_targets] == [
            verified_submission_id
        ]

        included = _draft(
            query.monitoring_query_id,
            1,
            eligible=True,
            verified=True,
            citation=CitationDraft(
                url=verified_url,
                title="Verified placement",
                verification_status=VerificationStatus.UNKNOWN,
                verified_at=None,
                submission_id=verified_submission_id,
            ),
        )
        unverified = _draft(query.monitoring_query_id, 2, eligible=True, verified=False)
        ineligible = _draft(query.monitoring_query_id, 3, eligible=False, verified=True)
        first = service.import_observation(
            principal,
            project_id=project_id,
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
                protocol_id=frozen.id,
                draft=_draft(
                    query.monitoring_query_id,
                    1,
                    eligible=True,
                    verified=True,
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
            protocol_id=frozen.id,
            draft=included,
            idempotency_key=f"{marker}-1",
        )
        service.import_observation(
            principal,
            project_id=project_id,
            protocol_id=frozen.id,
            draft=unverified,
            idempotency_key=f"{marker}-2",
        )
        service.import_observation(
            principal,
            project_id=project_id,
            protocol_id=frozen.id,
            draft=ineligible,
            idempotency_key=f"{marker}-3",
        )
        assert replay.id == first.id and replay.replayed
        with pytest.raises(MonitoringConflict):
            service.import_observation(
                principal,
                project_id=project_id,
                protocol_id=frozen.id,
                draft=_draft(query.monitoring_query_id, 1, eligible=True, verified=False),
                idempotency_key=f"{marker}-1",
            )

        metric = service.compute_metrics(
            principal,
            project_id=project_id,
            protocol_id=frozen.id,
            window=MeasurementWindow.T28,
        )
        assert metric.expected_sample_count == 3
        assert metric.eligible_sample_count == 2
        assert metric.status == "confounded"
        assert metric.recommendation_share == 1
        assert metric.placement_citation_share == pytest.approx(0.5)
        assert metric.qualified_destination_coverage == pytest.approx(0.5)
        assert metric.verified_placement_coverage == 1
        assert "incomplete_or_ineligible_sample_set" in metric.confounded_reasons

        report = service.generate_report(
            principal,
            project_id=project_id,
            metric_snapshot_id=metric.id,
            title="Observational baseline",
        )
        approved = service.approve_report(
            principal, project_id=project_id, report_id=report.id
        )
        assert approved.status == "approved"
        assert "non-causal" in approved.methodology_statement
        urls = service.list_verified_urls(principal, project_id=project_id)
        assert len(urls) == 1
        assert urls[0].url == verified_url
        assert urls[0].campaign_id == campaign_id
        assert urls[0].observation_count == 1

        with factory(principal) as unit_of_work:
            assert unit_of_work.monitoring.list_protocols(
                project_id=foreign_project_id
            ) == ()
        with pytest.raises(MonitoringNotFound):
            service.list_protocols(principal, project_id=foreign_project_id)

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
                        project_id, first.id, f"{verified_url}/forged",
                        verified_destination_id, verified_submission_id,
                    ),
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
                        project_id, frozen.id, other_campaign_id,
                        query.monitoring_query_id, identity_id,
                        f"wrong-campaign-{marker}", "e" * 64,
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


def _draft(
    query_id: UUID,
    sample_index: int,
    *,
    eligible: bool,
    verified: bool,
    citation: CitationDraft | None = None,
) -> ObservationDraft:
    return ObservationDraft(
        monitoring_query_id=query_id,
        measurement_window=MeasurementWindow.T28,
        sample_index=sample_index,
        result_status=ResultStatus.SUCCEEDED,
        eligible=eligible,
        ineligible_reasons=() if eligible else ("manual_exclusion",),
        url_verification_status=(
            VerificationStatus.PASSED if verified else VerificationStatus.FAILED
        ),
        recommendation_present=True,
        primary_product_mentioned=True,
        competitor_mentioned=False,
        raw_answer="internal raw answer",
        raw_result={"rank": 1},
        citations=(citation,) if citation else (),
        artifact_uri=None,
        artifact_hash=None,
        configured_model="deepseek-chat",
        provider_reported_model="deepseek-chat",
        ui_surface="web-search",
        ui_metadata={"locale": "en-AU"},
        confounding_factors=(),
        observed_at=datetime.now(UTC),
    )


def _seed(**values: object) -> None:
    with psycopg.connect(ADMIN_URL) as connection:
        connection.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s)",
            (values["tenant_id"], f"Monitoring {values['marker']}"),
        )
        connection.execute(
            "INSERT INTO identities (id, issuer, subject) VALUES (%s, 'test', %s)",
            (values["identity_id"], f"monitor-{values['marker']}"),
        )
        for project_id, name in (
            (values["project_id"], "Owned"),
            (values["foreign_project_id"], "Foreign"),
        ):
            connection.execute(
                "INSERT INTO projects (id, tenant_id, name) VALUES (%s, %s, %s)",
                (project_id, values["tenant_id"], f"{name} {values['marker']}"),
            )
        connection.execute(
            """INSERT INTO project_memberships (tenant_id, project_id, identity_id, role)
               VALUES (%s, %s, %s, 'owner')""",
            (values["tenant_id"], values["project_id"], values["identity_id"]),
        )
        for market_id, project_id, code in (
            (values["market_id"], values["project_id"], "AU"),
            (values["foreign_market_id"], values["foreign_project_id"], "NZ"),
        ):
            connection.execute(
                """INSERT INTO market_profiles
                     (id, project_id, market_code, locale, timezone)
                   VALUES (%s, %s, %s, 'en-AU', 'Australia/Sydney')""",
                (market_id, project_id, code),
            )
        connection.execute(
            """INSERT INTO product_entities
                 (id, project_id, entity_type, canonical_name)
               VALUES (%s, %s, 'product', %s)""",
            (values["product_id"], values["project_id"], f"Product {values['marker']}"),
        )
        for campaign_id, name in (
            (values["campaign_id"], "Campaign"),
            (values["other_campaign_id"], "Other campaign"),
        ):
            connection.execute(
                """INSERT INTO geo_campaigns
                     (id, project_id, market_profile_id, primary_product_entity_id,
                      name, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    campaign_id, values["project_id"], values["market_id"],
                    values["product_id"], f"{name} {values['marker']}",
                    values["identity_id"],
                ),
            )


def _seed_campaign_destinations(
    *, project_id: UUID, campaign_id: UUID, identity_id: UUID, marker: str
) -> tuple[str, UUID, UUID]:
    qualified_destination, selected_destination = uuid4(), uuid4()
    qualified_opportunity, selected_opportunity = uuid4(), uuid4()
    package_id, package_version_id = uuid4(), uuid4()
    request_id, submission_id = uuid4(), uuid4()
    url = f"https://example.com/{marker}/verified"
    with psycopg.connect(ADMIN_URL) as connection:
        for destination_id, key, policy in (
            (qualified_destination, f"qualified-{marker}", "approved"),
            (selected_destination, f"selected-{marker}", "unreviewed"),
        ):
            connection.execute(
                """INSERT INTO publication_destinations
                     (id, project_id, publication_channel, destination_key, policy_status,
                      canonical_url, canonical_host, allowed_hosts)
                   VALUES (%s, %s, 'owned_site', %s, %s,
                           'https://example.com/', 'example.com', ARRAY['example.com'])""",
                (destination_id, project_id, key, policy),
            )
        for opportunity_id, destination_id, status in (
            (qualified_opportunity, qualified_destination, "qualified"),
            (selected_opportunity, selected_destination, "identified"),
        ):
            connection.execute(
                """INSERT INTO placement_opportunities
                     (id, project_id, campaign_id, destination_id,
                      opportunity_ref, rationale, status)
                   VALUES (%s, %s, %s, %s, %s, 'test fixture', %s)""",
                (
                    opportunity_id, project_id, campaign_id, destination_id,
                    f"test:{opportunity_id}", status,
                ),
            )
        connection.execute(
            """INSERT INTO placement_packages (id, project_id, opportunity_id)
               VALUES (%s, %s, %s)""",
            (package_id, project_id, qualified_opportunity),
        )
        connection.execute("SET LOCAL session_replication_role = 'replica'")
        connection.execute(
            """INSERT INTO placement_package_versions
                 (id, project_id, package_id, prompt_bundle_id, version_number,
                  workflow_status, content_json, rendered_text, content_hash,
                  edited_by, edit_reason)
               VALUES (%s, %s, %s, %s, 1, 'approved', '{}'::jsonb,
                       'upstream verified fixture', %s, %s, 'monitoring integration fixture')""",
            (package_version_id, project_id, package_id, uuid4(), "d" * 64, identity_id),
        )
        connection.execute("SET LOCAL session_replication_role = 'origin'")
        connection.execute(
            """INSERT INTO publication_requests
                 (id, project_id, package_version_id, destination_id,
                  idempotency_key, requested_by, status)
               VALUES (%s, %s, %s, %s, %s, %s, 'published')""",
            (
                request_id, project_id, package_version_id, qualified_destination,
                f"request-{marker}", identity_id,
            ),
        )
        connection.execute(
            """INSERT INTO publication_submissions
                 (id, project_id, publication_request_id, submitted_url,
                  status, submitted_at, verified_at)
               VALUES (%s, %s, %s, %s, 'verified', clock_timestamp(), clock_timestamp())""",
            (submission_id, project_id, request_id, url),
        )
    return url, submission_id, qualified_destination


def _cleanup(tenant_id: UUID, identity_id: UUID) -> None:
    with psycopg.connect(ADMIN_URL) as connection:
        connection.execute("SET LOCAL session_replication_role = 'replica'")
        for table in (
            "monitoring_reports",
            "monitoring_metric_snapshots",
            "monitoring_observation_citations",
            "monitoring_observations",
            "monitoring_protocol_queries",
            "monitoring_query_suggestions",
            "monitoring_protocols",
            "publication_submissions",
            "publication_requests",
            "placement_package_versions",
            "placement_packages",
            "placement_opportunities",
            "publication_destinations",
            "campaign_monitoring_queries",
            "monitoring_queries",
            "geo_campaigns",
            "product_entities",
            "market_profiles",
            "project_memberships",
        ):
            connection.execute(
                f"""DELETE FROM {table}
                    WHERE project_id IN (SELECT id FROM projects WHERE tenant_id = %s)""",
                (tenant_id,),
            )
        connection.execute("DELETE FROM projects WHERE tenant_id = %s", (tenant_id,))
        connection.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        connection.execute("SET LOCAL session_replication_role = 'origin'")
        connection.execute("DELETE FROM identities WHERE id = %s", (identity_id,))
