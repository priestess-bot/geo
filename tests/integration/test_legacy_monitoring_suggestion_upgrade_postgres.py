from __future__ import annotations

import os
from uuid import uuid4

from alembic import command
import psycopg
from psycopg import sql
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.domain import MonitoringRuleViolation
from geo_core.monitoring.postgres import PsycopgMonitoringUnitOfWorkFactory
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


def test_legacy_suggested_query_fails_closed_before_upgrade_trigger_write() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0010_campaign_destinations")
        protocol_id = uuid4()
        suggestion_id = uuid4()
        with psycopg.connect(database_url) as connection:
            fixture = _seed_legacy_fixture(connection)
            connection.execute(
                """INSERT INTO monitoring_protocols
                     (id, project_id, campaign_id, market_profile_id, name, platform,
                      locale, device, sample_size, window_days, created_by)
                   VALUES (%s, %s, %s, %s, 'Legacy draft protocol',
                           'chatgpt_search', 'en-AU', 'desktop', 1, 28, %s)""",
                (
                    protocol_id,
                    fixture["project"],
                    fixture["campaign"],
                    fixture["market"],
                    fixture["owner"],
                ),
            )
            connection.execute(
                """INSERT INTO monitoring_query_suggestions
                     (id, project_id, protocol_id, query_text, query_kind, rationale,
                      status, suggested_by)
                   VALUES (%s, %s, %s, 'Which legacy product?', 'recommendation',
                           'Legacy suggestion without a cluster', 'suggested', %s)""",
                (suggestion_id, fixture["project"], protocol_id, fixture["owner"]),
            )
            connection.commit()

        command.upgrade(configuration, "head")
        suffix = uuid4().hex[:10]
        app_login = f"geo_legacy_suggestion_{suffix}"
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
            f"legacy-suggestion-{suffix}",
            fixture["tenant"],
            (MembershipRecord(fixture["project"], fixture["tenant"], "owner"),),
            "development",
        )
        app_url = login_url(database_url, user=app_login, password=app_password)
        unit_of_work_factory = PsycopgMonitoringUnitOfWorkFactory(app_url)
        service = MonitoringApplication(unit_of_work_factory)
        try:
            suggestions = service.list_suggestions(
                principal,
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                protocol_id=protocol_id,
            )
            assert len(suggestions) == 1
            assert suggestions[0].query_cluster_key is None

            with pytest.raises(MonitoringRuleViolation, match="explicit cluster key"):
                service.approve_suggestion(
                    principal,
                    project_id=fixture["project"],
                    campaign_id=fixture["campaign"],
                    protocol_id=protocol_id,
                    suggestion_id=suggestion_id,
                )

            with unit_of_work_factory(principal) as unit_of_work:
                protocol = unit_of_work.monitoring.get_protocol(
                    project_id=fixture["project"],
                    campaign_id=fixture["campaign"],
                    protocol_id=protocol_id,
                )
                assert protocol is not None
                with pytest.raises(MonitoringRuleViolation, match="explicit cluster key"):
                    unit_of_work.monitoring.approve_suggestion(
                        project_id=fixture["project"],
                        protocol=protocol,
                        suggestion_id=suggestion_id,
                        actor_id=principal.identity_id,
                    )

            with psycopg.connect(database_url) as admin:
                assert admin.execute(
                    """SELECT status, query_cluster_key
                       FROM monitoring_query_suggestions
                       WHERE id = %s AND project_id = %s""",
                    (suggestion_id, fixture["project"]),
                ).fetchone() == ("suggested", None)
                assert admin.execute(
                    """SELECT count(*) FROM monitoring_protocol_queries
                       WHERE suggestion_id = %s AND project_id = %s""",
                    (suggestion_id, fixture["project"]),
                ).fetchone() == (0,)
        finally:
            with psycopg.connect(database_url, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))
