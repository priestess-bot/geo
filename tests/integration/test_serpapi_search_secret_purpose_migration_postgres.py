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


def test_serpapi_secret_purpose_and_paid_call_contract_round_trip() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0129_question_repair")
        command.upgrade(configuration, "0130_serpapi_secret_purpose")
        _assert_upgraded(database_url)

        command.downgrade(configuration, "0129_question_repair")
        _assert_downgraded(database_url)

        command.upgrade(configuration, "0130_serpapi_secret_purpose")
        _assert_upgraded(database_url)


def _assert_upgraded(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            "SELECT geo_model_gateway_provider_secret_purpose('serpapi')"
        ).fetchone() == ("search.serpapi",)
        assert connection.execute(
            "SELECT geo_model_gateway_provider_secret_purpose('openai')"
        ).fetchone() == ("model_provider.openai",)
        constraints = dict(
            connection.execute(
                """SELECT conname, pg_get_constraintdef(oid)
                   FROM pg_constraint
                   WHERE conrelid = 'model_gateway_terminal_events'::regclass
                     AND conname IN (
                       'model_gateway_terminal_events_paid_call_count_check',
                       'model_gateway_terminal_events_status_shape',
                       'model_gateway_terminal_events_failed_artifact_shape'
                     )"""
            ).fetchall()
        )
        assert ">= 0" in constraints[
            "model_gateway_terminal_events_paid_call_count_check"
        ]
        assert "paid_call_count >= 1" in constraints[
            "model_gateway_terminal_events_status_shape"
        ]
        assert "paid_call_count >= 1" in constraints[
            "model_gateway_terminal_events_failed_artifact_shape"
        ]
        functions = {
            name: connection.execute(
                "SELECT pg_get_functiondef(%s::regprocedure)", (signature,)
            ).fetchone()[0]
            for name, signature in {
                "runtime_option": (
                    "public.geo_add_model_gateway_runtime_option(uuid,uuid,uuid,text,text,text,text,text,uuid,text,text,text,text,text,text,text[],jsonb,text,timestamptz)"
                ),
                "job_admission": (
                    "public.geo_assert_model_gateway_job_admission_insert()"
                ),
                "attempt": "public.geo_assert_model_gateway_attempt_insert()",
                "terminal_shape": "public.geo_assert_model_gateway_terminal_shape()",
            }.items()
        }
        assert "geo_model_gateway_provider_secret_purpose(p_provider)" in functions[
            "runtime_option"
        ]
        assert "geo_model_gateway_provider_secret_purpose(NEW.provider)" in functions[
            "job_admission"
        ]
        assert "geo_model_gateway_provider_secret_purpose(NEW.provider)" in functions[
            "attempt"
        ]
        assert "paid_call_count >= 1" in functions["terminal_shape"]


def _assert_downgraded(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            "SELECT to_regprocedure('public.geo_model_gateway_provider_secret_purpose(text)')"
        ).fetchone() == (None,)
        constraints = dict(
            connection.execute(
                """SELECT conname, pg_get_constraintdef(oid)
                   FROM pg_constraint
                   WHERE conrelid = 'model_gateway_terminal_events'::regclass
                     AND conname IN (
                       'model_gateway_terminal_events_paid_call_count_check',
                       'model_gateway_terminal_events_status_shape',
                       'model_gateway_terminal_events_failed_artifact_shape'
                     )"""
            ).fetchall()
        )
        assert "ARRAY[0, 1]" in constraints[
            "model_gateway_terminal_events_paid_call_count_check"
        ]
        assert "paid_call_count = 1" in constraints[
            "model_gateway_terminal_events_status_shape"
        ]
        assert "paid_call_count = 1" in constraints[
            "model_gateway_terminal_events_failed_artifact_shape"
        ]
        definition = connection.execute(
            "SELECT pg_get_functiondef('public.geo_assert_model_gateway_terminal_shape()'::regprocedure)"
        ).fetchone()[0]
        assert "paid_call_count = 1" in definition
