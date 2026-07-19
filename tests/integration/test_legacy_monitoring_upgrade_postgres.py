from __future__ import annotations

import os
from uuid import uuid4

from alembic import command
import psycopg
from psycopg import sql
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.domain import (
    Device,
    MeasurementWindow,
    MonitoringRuleViolation,
    Platform,
)
from geo_core.monitoring.postgres import PsycopgMonitoringUnitOfWorkFactory
from geo_core.monitoring.source_contract import CaptureMethod
from geo_core.placements.application import PlacementApplication
from geo_core.placements.postgres_uow import placement_uow_factory
from tests.integration.monitoring_postgres_support import draft, source
from tests.integration.placement_worker_support import login_url
from tests.integration.test_batch2_migrations_postgres import (
    _seed_legacy_fixture,
    _temporary_database,
)


ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_URL,
        reason="GEO_ACCESS_TEST_ADMIN_DATABASE_URL is required",
    ),
]


def test_legacy_monitoring_history_survives_and_current_contract_continues() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0010_campaign_destinations")
        with psycopg.connect(database_url) as connection:
            fixture = _seed_legacy_fixture(connection)

        command.upgrade(configuration, "head")
        suffix = uuid4().hex[:10]
        app_login = f"geo_legacy_monitor_{suffix}"
        app_password = uuid4().hex
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            admin.execute(
                """INSERT INTO project_memberships
                     (tenant_id, project_id, identity_id, role)
                   VALUES (%s, %s, %s, 'owner')""",
                (fixture["tenant"], fixture["project"], fixture["owner"]),
            )
            admin.commit()

        principal = AccessPrincipal(
            fixture["owner"],
            f"legacy-monitor-{suffix}",
            fixture["tenant"],
            (MembershipRecord(fixture["project"], fixture["tenant"], "owner"),),
            "development",
        )
        app_url = login_url(database_url, user=app_login, password=app_password)
        service = MonitoringApplication(PsycopgMonitoringUnitOfWorkFactory(app_url))
        placement = PlacementApplication(placement_uow_factory(lambda: psycopg.connect(app_url)))
        try:
            protocols = service.list_protocols(
                principal,
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
            )
            legacy_protocol = next(item for item in protocols if item.id == fixture["protocol"])
            assert legacy_protocol.statistics_contract_version == "legacy-v1"
            assert legacy_protocol.source_strata == ()

            observations = service.list_observations(
                principal,
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                protocol_id=legacy_protocol.id,
            )
            legacy_observation = next(
                item for item in observations if item.id == fixture["observation"]
            )
            assert legacy_observation.draft.eligible is False
            assert "legacy_unknown_capture_method" in (legacy_observation.draft.ineligible_reasons)
            assert legacy_observation.draft.source.capture_method == CaptureMethod.UNKNOWN
            assert legacy_observation.included_in_metrics is False

            legacy_metric = next(
                item
                for item in service.list_metrics(
                    principal,
                    project_id=fixture["project"],
                    campaign_id=fixture["campaign"],
                )
                if item.id == fixture["metric"]
            )
            assert legacy_metric.statistics_contract_version == "legacy-v1"
            with pytest.raises(
                MonitoringRuleViolation,
                match="legacy metrics with unknown sources",
            ):
                service.generate_report(
                    principal,
                    project_id=fixture["project"],
                    campaign_id=fixture["campaign"],
                    metric_snapshot_id=legacy_metric.id,
                    title="Legacy result must remain historical",
                )

            placement.review_destination_policy(
                project_id=fixture["project"],
                destination_id=fixture["destination"],
                status="approved",
                rules={"brand_participation": "disclosed"},
                identity_requirements={"brand_identity": "required"},
                disclosure_requirements={"commercial_relationship": "required"},
                allowed_hosts=("example.test",),
                reviewed_by=fixture["owner"],
            )
            opportunity = placement.transition_opportunity(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                opportunity_id=fixture["opportunity"],
                command="qualify",
                reason="Migrate the legacy destination to the current policy contract",
            )
            assert opportunity.status == "qualified"

            current_source = source(CaptureMethod.MANUAL_UI)
            protocol = service.create_protocol(
                principal,
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                market_profile_id=fixture["market"],
                name=f"Current monitoring {suffix}",
                platform=Platform.CHATGPT_SEARCH,
                locale="en-AU",
                device=Device.DESKTOP,
                sample_size=3,
                minimum_valid_repeats=3,
                window_days=28,
                source_strata=(current_source.stratum_key(),),
            )
            suggestion = service.suggest_query(
                principal,
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                protocol_id=protocol.id,
                query_text=f"Which product is recommended now? {suffix}",
                query_kind="recommendation",
                rationale="Continue monitoring under the current source contract",
                query_cluster_key="legacy-upgrade-recommendation",
            )
            query = service.approve_suggestion(
                principal,
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                protocol_id=protocol.id,
                suggestion_id=suggestion.id,
            )
            service.approve_protocol(
                principal,
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                protocol_id=protocol.id,
            )
            frozen = service.freeze_protocol(
                principal,
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                protocol_id=protocol.id,
            )
            assert frozen.statistics_contract_version == "geo-observation-statistics-v2"
            assert frozen.source_strata[0].source_contract_version == "geo-observation-source-v3"

            for sample_index in range(1, 4):
                imported = service.import_observation(
                    principal,
                    project_id=fixture["project"],
                    campaign_id=fixture["campaign"],
                    protocol_id=frozen.id,
                    draft=draft(
                        query.monitoring_query_id,
                        sample_index,
                        eligible=True,
                        verified=False,
                        source=current_source,
                    ),
                    idempotency_key=f"legacy-upgrade-{suffix}-{sample_index}",
                )
                assert imported.included_in_metrics

            metric = service.compute_metrics(
                principal,
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                protocol_id=frozen.id,
                window=MeasurementWindow.T28,
                source_stratum_hash=current_source.stratum_key().canonical_hash(),
                query_cluster_key="legacy-upgrade-recommendation",
            )
            assert metric.statistics_contract_version == "geo-observation-statistics-v2"
            assert metric.status == "complete"
            assert metric.sampled_sample_count == 3
            assert metric.eligible_sample_count == 3
            assert metric.observation_membership_count == 3
            assert metric.result_hash is not None
        finally:
            with psycopg.connect(database_url, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))
