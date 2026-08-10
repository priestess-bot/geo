from __future__ import annotations

import os

from alembic import command
import psycopg
import pytest

from tests.integration.test_batch2_migrations_postgres import _temporary_database


ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_URL,
        reason="GEO_ACCESS_TEST_ADMIN_DATABASE_URL is required",
    ),
]


def test_lokiproxy_pool_contract_round_trip() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0130_serpapi_secret_purpose")
        command.upgrade(configuration, "0131_lokiproxy_pool")
        _assert_upgraded(database_url)

        command.downgrade(configuration, "0130_serpapi_secret_purpose")
        _assert_downgraded(database_url)

        command.upgrade(configuration, "0131_lokiproxy_pool")
        _assert_upgraded(database_url)


def _assert_upgraded(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            "SELECT geo_model_gateway_provider_secret_purpose('openai')"
        ).fetchone() == ("model_provider.openai",)
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            connection.execute(
                "SELECT geo_model_gateway_provider_secret_purpose('serpapi')"
            ).fetchone()
        connection.rollback()
        columns = {
            str(row[0])
            for row in connection.execute(
                """SELECT column_name FROM information_schema.columns
                     WHERE table_schema = 'public'
                       AND table_name = 'browser_egress_endpoints'"""
            ).fetchall()
        }
        assert {
            "provider",
            "pool_product",
            "session_ttl_seconds",
            "max_concurrency",
            "health_status",
            "consecutive_failures",
            "last_checked_at",
            "cooldown_until",
            "last_error_class",
        } <= columns
        assert connection.execute(
            """SELECT count(*) FROM pg_trigger
                 WHERE tgname = 'browser_egress_pool_health_projection'
                   AND NOT tgisinternal"""
        ).fetchone() == (1,)
        egress_admission = connection.execute(
            """SELECT pg_get_functiondef(
                'public.geo_enqueue_browser_egress_test(uuid,uuid,uuid,uuid,timestamptz)'::regprocedure
            )"""
        ).fetchone()[0]
        assert "endpoint.provider <> 'lokiproxy'" in egress_admission
        assert "endpoint.cooldown_until > p_requested_at" in egress_admission
        assert "'session_ttl_seconds', endpoint.session_ttl_seconds" in egress_admission
        capture_admission = connection.execute(
            """SELECT pg_get_functiondef(
                'public.geo_enqueue_browser_capture_attempt(uuid,uuid,uuid,uuid,integer,uuid,uuid,uuid,text,text,timestamptz,timestamptz)'::regprocedure
            )"""
        ).fetchone()[0]
        assert "endpoint.provider <> 'lokiproxy'" in capture_admission
        assert "endpoint.health_status <> 'healthy'" in capture_admission
        capture_start = connection.execute(
            """SELECT pg_get_functiondef(
                'public.geo_start_browser_capture_execution(uuid,uuid,uuid,integer,text,text,timestamptz,timestamptz,text)'::regprocedure
            )"""
        ).fetchone()[0]
        assert "lokiproxy-pool:" in capture_start
        assert "endpoint.provider = 'lokiproxy'" in capture_start
        assert "active_session.status = 'running'" in capture_start
        assert "endpoint.max_concurrency" in capture_start


def _assert_downgraded(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            "SELECT geo_model_gateway_provider_secret_purpose('serpapi')"
        ).fetchone() == ("search.serpapi",)
        assert connection.execute(
            """SELECT count(*) FROM information_schema.columns
                 WHERE table_schema = 'public'
                   AND table_name = 'browser_egress_endpoints'
                   AND column_name = 'provider'"""
        ).fetchone() == (0,)
        egress_admission = connection.execute(
            """SELECT pg_get_functiondef(
                'public.geo_enqueue_browser_egress_test(uuid,uuid,uuid,uuid,timestamptz)'::regprocedure
            )"""
        ).fetchone()[0]
        assert "endpoint.provider" not in egress_admission
        assert "session_ttl_seconds" not in egress_admission
        capture_start = connection.execute(
            """SELECT pg_get_functiondef(
                'public.geo_start_browser_capture_execution(uuid,uuid,uuid,integer,text,text,timestamptz,timestamptz,text)'::regprocedure
            )"""
        ).fetchone()[0]
        assert "lokiproxy-pool:" not in capture_start
        assert "endpoint.max_concurrency" not in capture_start
