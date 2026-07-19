from __future__ import annotations

import os
from typing import Any
from uuid import UUID, uuid4

from alembic import command
import psycopg
import pytest
from sqlalchemy.exc import DBAPIError

from tests.integration.test_batch2_migrations_postgres import (
    _seed_legacy_fixture,
    _sha256,
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


def _insert_legacy_fact(
    connection: psycopg.Connection[Any],
    fixture: dict[str, Any],
    *,
    statement: str,
    statement_hash: str,
    approved: bool = False,
) -> UUID:
    fact_id = uuid4()
    status = "approved" if approved else "pending_review"
    connection.execute(
        """INSERT INTO knowledge_fact_candidates (
               id, project_id, pipeline_run_id, source_id, document_id, chunk_id,
               statement, statement_hash, status, reviewed_by, reviewed_at,
               extractor_release, lifecycle_status
           )
           SELECT %s, project_id, pipeline_run_id, source_id, document_id, chunk_id,
                  %s, %s, %s,
                  CASE WHEN %s THEN %s::uuid ELSE NULL END,
                  CASE WHEN %s THEN clock_timestamp() ELSE NULL END,
                  'legacy-sentence-v1', 'active'
           FROM knowledge_fact_candidates
           WHERE id = %s""",
        (
            fact_id,
            statement,
            statement_hash,
            status,
            approved,
            fixture["owner"],
            approved,
            fixture["fact"],
        ),
    )
    return fact_id


def _seed_through_0021(database_url: str, configuration: Any) -> dict[str, Any]:
    command.upgrade(configuration, "0011_runtime_health")
    with psycopg.connect(database_url) as connection:
        fixture = _seed_legacy_fixture(connection)
    command.upgrade(configuration, "0021_observation_source_details")
    return fixture


def test_legacy_fact_hash_repair_fresh_round_trip() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0022_legacy_fact_hash_repair")
        with psycopg.connect(database_url) as connection:
            assert (
                connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                == "0022_legacy_fact_hash_repair"
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM knowledge_legacy_fact_hash_repairs"
                ).fetchone()[0]
                == 0
            )

        command.downgrade(configuration, "0021_observation_source_details")
        command.upgrade(configuration, "0022_legacy_fact_hash_repair")


def test_legacy_fact_hash_repair_populated_round_trip() -> None:
    with _temporary_database() as (database_url, configuration):
        fixture = _seed_through_0021(database_url, configuration)
        statement = "ADVINSYS V600 Uses Exact Vision."
        previous_hash = _sha256(statement.lower())
        repaired_hash = _sha256(statement)
        with psycopg.connect(database_url) as connection:
            fact_id = _insert_legacy_fact(
                connection,
                fixture,
                statement=statement,
                statement_hash=previous_hash,
            )
            connection.commit()

        command.upgrade(configuration, "0022_legacy_fact_hash_repair")
        with psycopg.connect(database_url) as connection:
            assert (
                connection.execute(
                    "SELECT statement_hash FROM knowledge_fact_candidates WHERE id = %s",
                    (fact_id,),
                ).fetchone()[0]
                == repaired_hash
            )
            assert connection.execute(
                """SELECT previous_statement_hash, repaired_statement_hash,
                          repair_contract_version
                   FROM knowledge_legacy_fact_hash_repairs
                   WHERE fact_candidate_id = %s""",
                (fact_id,),
            ).fetchone() == (
                previous_hash,
                repaired_hash,
                "legacy-ascii-lower-sha256-to-exact-v1",
            )
            assert (
                connection.execute(
                    """SELECT statement_hash FROM knowledge_fact_candidates
                   WHERE id = %s""",
                    (fixture["fact"],),
                ).fetchone()[0]
                == fixture["fact_statement_hash"]
            )

        command.downgrade(configuration, "0021_observation_source_details")
        with psycopg.connect(database_url) as connection:
            assert (
                connection.execute(
                    "SELECT statement_hash FROM knowledge_fact_candidates WHERE id = %s",
                    (fact_id,),
                ).fetchone()[0]
                == previous_hash
            )
            assert (
                connection.execute(
                    "SELECT to_regclass('knowledge_legacy_fact_hash_repairs')"
                ).fetchone()[0]
                is None
            )

        command.upgrade(configuration, "0022_legacy_fact_hash_repair")
        with psycopg.connect(database_url) as connection:
            assert (
                connection.execute(
                    "SELECT statement_hash FROM knowledge_fact_candidates WHERE id = %s",
                    (fact_id,),
                ).fetchone()[0]
                == repaired_hash
            )


def test_legacy_fact_hash_repair_rejects_duplicate_target() -> None:
    with _temporary_database() as (database_url, configuration):
        fixture = _seed_through_0021(database_url, configuration)
        statement = "Mixed Case Duplicate Target."
        previous_hash = _sha256(statement.lower())
        repaired_hash = _sha256(statement)
        with psycopg.connect(database_url) as connection:
            target_id = _insert_legacy_fact(
                connection,
                fixture,
                statement=statement,
                statement_hash=previous_hash,
            )
            duplicate_id = _insert_legacy_fact(
                connection,
                fixture,
                statement=statement,
                statement_hash=repaired_hash,
            )
            connection.commit()

        with pytest.raises(DBAPIError) as error:
            command.upgrade(configuration, "0022_legacy_fact_hash_repair")
        assert "invalid_hash=0, referenced=0, duplicate_target=1" in str(error.value)

        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                """SELECT id, statement_hash FROM knowledge_fact_candidates
                   WHERE id IN (%s, %s) ORDER BY id""",
                (target_id, duplicate_id),
            ).fetchall() == sorted([(target_id, previous_hash), (duplicate_id, repaired_hash)])
            assert (
                connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                == "0021_observation_source_details"
            )
            assert (
                connection.execute(
                    "SELECT to_regclass('knowledge_legacy_fact_hash_repairs')"
                ).fetchone()[0]
                is None
            )


def test_legacy_fact_hash_repair_rejects_non_ascii_non_exact_hashes() -> None:
    with _temporary_database() as (database_url, configuration):
        fixture = _seed_through_0021(database_url, configuration)
        cases = (
            ("ΟΣ", _sha256("ΟΣ".lower())),
            ("İ", _sha256("İ".lower())),
            ("中文", _sha256("non-exact-Chinese-hash")),
            ("可验证中文", _sha256("可验证中文")),
        )
        inserted: list[tuple[UUID, str]] = []
        with psycopg.connect(database_url) as connection:
            for statement, statement_hash in cases:
                inserted.append(
                    (
                        _insert_legacy_fact(
                            connection,
                            fixture,
                            statement=statement,
                            statement_hash=statement_hash,
                        ),
                        statement_hash,
                    )
                )
            connection.commit()

        with pytest.raises(DBAPIError) as error:
            command.upgrade(configuration, "0022_legacy_fact_hash_repair")
        assert "invalid_hash=3, referenced=0, duplicate_target=0" in str(error.value)

        with psycopg.connect(database_url) as connection:
            for fact_id, statement_hash in inserted:
                assert (
                    connection.execute(
                        """SELECT statement_hash FROM knowledge_fact_candidates
                           WHERE id = %s""",
                        (fact_id,),
                    ).fetchone()[0]
                    == statement_hash
                )
            assert (
                connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                == "0021_observation_source_details"
            )
            assert (
                connection.execute(
                    "SELECT to_regclass('knowledge_legacy_fact_hash_repairs')"
                ).fetchone()[0]
                is None
            )


def test_legacy_fact_hash_repair_rejects_lineage_and_invalid_hash() -> None:
    with _temporary_database() as (database_url, configuration):
        fixture = _seed_through_0021(database_url, configuration)
        statement = "Referenced Mixed Case Fact."
        previous_hash = _sha256(statement.lower())
        evidence_id = uuid4()
        with psycopg.connect(database_url) as connection:
            fact_id = _insert_legacy_fact(
                connection,
                fixture,
                statement=statement,
                statement_hash=previous_hash,
                approved=True,
            )
            invalid_id = _insert_legacy_fact(
                connection,
                fixture,
                statement="Invalid Legacy Hash.",
                statement_hash="f" * 64,
            )
            connection.execute("SET LOCAL session_replication_role = replica")
            connection.execute(
                """INSERT INTO evidence_items (
                       id, project_id, item_type, source_id, subject_entity_id,
                       subject_role, snapshot_text, snapshot_hash,
                       source_revision_kind, source_revision_value, usage_rights,
                       confidentiality, public_source_title, fact_lineage_status
                   ) VALUES (
                       %s, %s, 'approved_fact', %s, %s, 'product', %s, %s,
                       'content_hash', %s, 'owned', 'internal',
                       'Legacy hash guard fixture', 'verified'
                   )""",
                (
                    evidence_id,
                    fixture["project"],
                    fact_id,
                    fixture["product"],
                    statement,
                    previous_hash,
                    previous_hash,
                ),
            )
            connection.execute(
                """INSERT INTO knowledge_fact_evidence_lineages (
                       project_id, pipeline_run_id, knowledge_source_id,
                       knowledge_document_id, knowledge_chunk_id, knowledge_fact_id,
                       evidence_item_id, evidence_title, promoted_by,
                       idempotency_key, promotion_request_hash, source_content_hash,
                       document_cleaned_text_hash, chunk_text_hash,
                       fact_statement_hash, evidence_snapshot_hash,
                       lineage_contract_version
                   )
                   SELECT fact.project_id, fact.pipeline_run_id, fact.source_id,
                          fact.document_id, fact.chunk_id, fact.id, %s,
                          'Legacy hash guard fixture', %s, %s, %s,
                          source.content_hash, document.cleaned_text_hash,
                          chunk.text_hash, fact.statement_hash, %s,
                          'knowledge-fact-evidence-v1'
                   FROM knowledge_fact_candidates AS fact
                   JOIN knowledge_sources AS source ON source.id = fact.source_id
                   JOIN knowledge_documents AS document ON document.id = fact.document_id
                   JOIN knowledge_chunks AS chunk ON chunk.id = fact.chunk_id
                   WHERE fact.id = %s""",
                (
                    evidence_id,
                    fixture["owner"],
                    f"legacy-hash-guard:{fact_id}",
                    _sha256(f"legacy-hash-guard:{fact_id}"),
                    previous_hash,
                    fact_id,
                ),
            )
            connection.commit()

        with pytest.raises(DBAPIError) as error:
            command.upgrade(configuration, "0022_legacy_fact_hash_repair")
        assert "invalid_hash=1, referenced=1, duplicate_target=0" in str(error.value)

        with psycopg.connect(database_url) as connection:
            assert (
                connection.execute(
                    "SELECT statement_hash FROM knowledge_fact_candidates WHERE id = %s",
                    (fact_id,),
                ).fetchone()[0]
                == previous_hash
            )
            assert (
                connection.execute(
                    "SELECT statement_hash FROM knowledge_fact_candidates WHERE id = %s",
                    (invalid_id,),
                ).fetchone()[0]
                == "f" * 64
            )
            assert (
                connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                == "0021_observation_source_details"
            )
