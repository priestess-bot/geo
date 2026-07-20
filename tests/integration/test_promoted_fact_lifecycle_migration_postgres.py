from __future__ import annotations

import os

from alembic import command
import psycopg
import pytest

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


def test_promoted_fact_allows_only_lifecycle_retirement_round_trip() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0011_runtime_health")
        with psycopg.connect(database_url) as connection:
            fixture = _seed_legacy_fixture(connection)
            connection.commit()
        command.upgrade(configuration, "0022_legacy_fact_hash_repair")

        with psycopg.connect(database_url) as connection:
            with pytest.raises(psycopg.DatabaseError, match="immutable"):
                connection.execute(
                    """UPDATE knowledge_fact_candidates
                       SET lifecycle_status = 'superseded'
                       WHERE id = %s""",
                    (fixture["fact"],),
                )
            connection.rollback()

        command.upgrade(configuration, "0023_promoted_fact_lifecycle")
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """UPDATE knowledge_fact_candidates
                   SET lifecycle_status = 'superseded', updated_at = clock_timestamp()
                   WHERE id = %s""",
                (fixture["fact"],),
            )
            connection.commit()
            assert (
                connection.execute(
                    "SELECT lifecycle_status FROM knowledge_fact_candidates WHERE id = %s",
                    (fixture["fact"],),
                ).fetchone()[0]
                == "superseded"
            )
            with pytest.raises(psycopg.DatabaseError, match="immutable"):
                connection.execute(
                    """UPDATE knowledge_fact_candidates
                       SET statement = statement || ' changed'
                       WHERE id = %s""",
                    (fixture["fact"],),
                )
            connection.rollback()
            connection.execute("SET LOCAL session_replication_role = replica")
            connection.execute(
                """UPDATE knowledge_fact_candidates SET lifecycle_status = 'active'
                   WHERE id = %s""",
                (fixture["fact"],),
            )
            connection.execute("SET LOCAL session_replication_role = origin")
            connection.commit()

        command.downgrade(configuration, "0022_legacy_fact_hash_repair")
        with psycopg.connect(database_url) as connection:
            with pytest.raises(psycopg.DatabaseError, match="immutable"):
                connection.execute(
                    """UPDATE knowledge_fact_candidates
                       SET lifecycle_status = 'withdrawn'
                       WHERE id = %s""",
                    (fixture["fact"],),
                )
