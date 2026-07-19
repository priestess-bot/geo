from __future__ import annotations

import os
from uuid import uuid4

from alembic import command
import psycopg
import pytest
from sqlalchemy.exc import DBAPIError

from geo_core.project_scope import set_project_scope
from tests.integration.runtime_database_support import runtime_role_url
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


def test_knowledge_rag_graph_populated_round_trip_and_contract() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0011_runtime_health")
        with psycopg.connect(database_url) as admin:
            legacy = _seed_legacy_fixture(admin)

        command.upgrade(configuration, "0017_knowledge_rag_graph")
        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                """SELECT logical_source_id, supersedes_source_id, title,
                          content_hash
                   FROM knowledge_sources WHERE id = %s""",
                (legacy["source"],),
            ).fetchone() == (
                legacy["source"],
                None,
                "Legacy source",
                legacy["source_content_hash"],
            )
            assert admin.execute(
                """SELECT rag_revision_id, extractor_release, source_locator,
                          lifecycle_status, statement_hash, document_id, chunk_id
                   FROM knowledge_fact_candidates WHERE id = %s""",
                (legacy["fact"],),
            ).fetchone() == (
                None,
                "legacy-sentence-v1",
                None,
                "active",
                legacy["fact_statement_hash"],
                legacy["document"],
                legacy["chunk"],
            )
            for table in (
                "knowledge_rag_job_specs",
                "knowledge_rag_revisions",
                "knowledge_fact_candidate_sources",
                "knowledge_entity_candidates",
                "knowledge_entity_candidate_sources",
                "knowledge_relation_candidates",
                "knowledge_rag_validation_findings",
                "knowledge_graph_entities",
                "knowledge_graph_entity_sources",
                "knowledge_graph_relations",
                "knowledge_graph_relation_sources",
            ):
                assert admin.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0

        command.downgrade(configuration, "0016_publication_verification")
        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                "SELECT title, content_hash FROM knowledge_sources WHERE id = %s",
                (legacy["source"],),
            ).fetchone() == ("Legacy source", legacy["source_content_hash"])
            assert admin.execute(
                """SELECT statement_hash, document_id, chunk_id
                   FROM knowledge_fact_candidates WHERE id = %s""",
                (legacy["fact"],),
            ).fetchone() == (
                legacy["fact_statement_hash"],
                legacy["document"],
                legacy["chunk"],
            )
            assert admin.execute(
                """SELECT count(*) FROM information_schema.columns
                   WHERE table_name = 'knowledge_fact_candidates'
                     AND column_name IN (
                         'rag_revision_id', 'extractor_release',
                         'source_locator', 'lifecycle_status'
                     )"""
            ).fetchone()[0] == 0
        command.upgrade(configuration, "0017_knowledge_rag_graph")

        ids = {
            name: uuid4()
            for name in (
                "job",
                "revision",
                "rag_fact",
                "entity_candidate",
                "graph_entity",
                "project_two",
                "source_two",
                "invalid_source_revision",
            )
        }
        with psycopg.connect(database_url) as admin:
            admin.execute(
                """INSERT INTO durable_jobs
                     (id, project_id, kind, input_hash, idempotency_key)
                   VALUES (%s, %s, 'knowledge.rag.extract', %s, %s)""",
                (ids["job"], legacy["project"], _sha256("rag-job"), str(ids["job"])),
            )
            admin.execute(
                """INSERT INTO knowledge_rag_job_specs
                     (job_id, project_id, pipeline_run_id, source_id, document_id,
                      configured_model, model_call_budget, adapter_release,
                      selection_manifest_hash, requested_by)
                   VALUES (%s, %s, %s, %s, %s, 'fixture-model', 3,
                           'project-native-rag-v1', %s, %s)""",
                (
                    ids["job"],
                    legacy["project"],
                    legacy["run"],
                    legacy["source"],
                    legacy["document"],
                    _sha256("selection"),
                    legacy["owner"],
                ),
            )
            artifact_hash = _sha256("rag-artifact")
            admin.execute(
                """INSERT INTO knowledge_rag_revisions
                     (id, project_id, job_id, pipeline_run_id, source_id,
                      logical_source_id, document_id, adapter_release,
                      selection_manifest_hash, input_hash, output_hash,
                      artifact_uri, artifact_hash, lifecycle_status, created_by,
                      completed_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s,
                           'project-native-rag-v1', %s, %s, %s,
                           's3://knowledge-rag/fixture.json', %s, 'active', %s,
                           clock_timestamp())""",
                (
                    ids["revision"],
                    legacy["project"],
                    ids["job"],
                    legacy["run"],
                    legacy["source"],
                    legacy["source"],
                    legacy["document"],
                    _sha256("selection"),
                    _sha256("rag-input"),
                    artifact_hash,
                    artifact_hash,
                    legacy["owner"],
                ),
            )
            admin.execute(
                """INSERT INTO knowledge_fact_candidates
                     (id, project_id, pipeline_run_id, source_id, document_id,
                      chunk_id, statement, statement_hash, rag_revision_id,
                      extractor_release, source_locator)
                   SELECT %s, project_id, pipeline_run_id, source_id, document_id,
                          chunk_id, statement, statement_hash, %s,
                          'project-native-rag-v1', 'line:1'
                   FROM knowledge_fact_candidates WHERE id = %s""",
                (ids["rag_fact"], ids["revision"], legacy["fact"]),
            )
            admin.execute(
                """INSERT INTO knowledge_fact_candidate_sources
                     (project_id, fact_candidate_id, rag_revision_id,
                      pipeline_run_id, source_id, document_id, chunk_id,
                      source_locator)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'line:1')""",
                (
                    legacy["project"],
                    ids["rag_fact"],
                    ids["revision"],
                    legacy["run"],
                    legacy["source"],
                    legacy["document"],
                    legacy["chunk"],
                ),
            )
            entity_name = "Legacy Product"
            admin.execute(
                """INSERT INTO knowledge_entity_candidates
                     (id, project_id, rag_revision_id, pipeline_run_id, source_id,
                      document_id, adapter_candidate_id, entity_type, name,
                      name_hash, generated_by_job_id)
                   VALUES (%s, %s, %s, %s, %s, %s, 'entity-1', 'product',
                           %s, %s, %s)""",
                (
                    ids["entity_candidate"],
                    legacy["project"],
                    ids["revision"],
                    legacy["run"],
                    legacy["source"],
                    legacy["document"],
                    entity_name,
                    _sha256(entity_name),
                    ids["job"],
                ),
            )
            admin.execute(
                """INSERT INTO knowledge_entity_candidate_sources
                     (project_id, entity_candidate_id, rag_revision_id,
                      pipeline_run_id, source_id, document_id, chunk_id,
                      source_locator)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'line:1')""",
                (
                    legacy["project"],
                    ids["entity_candidate"],
                    ids["revision"],
                    legacy["run"],
                    legacy["source"],
                    legacy["document"],
                    legacy["chunk"],
                ),
            )
            admin.execute(
                """INSERT INTO knowledge_graph_entities
                     (id, project_id, entity_type, canonical_name, name_hash,
                      status, approved_by, approved_at)
                   VALUES (%s, %s, 'product', %s, %s, 'current', %s,
                           clock_timestamp())""",
                (
                    ids["graph_entity"],
                    legacy["project"],
                    entity_name,
                    _sha256(entity_name),
                    legacy["owner"],
                ),
            )
            admin.execute(
                """INSERT INTO knowledge_graph_entity_sources
                     (project_id, graph_entity_id, rag_revision_id,
                      entity_candidate_id, pipeline_run_id, source_id,
                      document_id, chunk_id, source_locator, approved_by,
                      lifecycle_status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'line:1', %s,
                           'active')""",
                (
                    legacy["project"],
                    ids["graph_entity"],
                    ids["revision"],
                    ids["entity_candidate"],
                    legacy["run"],
                    legacy["source"],
                    legacy["document"],
                    legacy["chunk"],
                    legacy["owner"],
                ),
            )
            admin.execute(
                """UPDATE knowledge_entity_candidates
                   SET workflow_status = 'approved', graph_entity_id = %s,
                       reviewed_by = %s, reviewed_at = clock_timestamp(),
                       updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s""",
                (
                    ids["graph_entity"],
                    legacy["owner"],
                    ids["entity_candidate"],
                    legacy["project"],
                ),
            )
            admin.commit()

            assert admin.execute(
                """SELECT count(*), count(*) FILTER (WHERE rag_revision_id IS NULL),
                          count(*) FILTER (WHERE rag_revision_id IS NOT NULL)
                   FROM knowledge_fact_candidates WHERE pipeline_run_id = %s
                     AND statement_hash = %s""",
                (legacy["run"], legacy["fact_statement_hash"]),
            ).fetchone() == (2, 1, 1)
            admin.execute(
                """UPDATE knowledge_graph_entities
                   SET catalog_entity_id = %s, updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s""",
                (legacy["product"], ids["graph_entity"], legacy["project"]),
            )
            admin.commit()

            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                with admin.transaction():
                    admin.execute(
                        "UPDATE knowledge_sources SET title = 'mutated' WHERE id = %s",
                        (legacy["source"],),
                    )
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                with admin.transaction():
                    admin.execute(
                        """UPDATE knowledge_graph_entities
                           SET catalog_entity_id = NULL WHERE id = %s""",
                        (ids["graph_entity"],),
                    )
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                with admin.transaction():
                    admin.execute(
                        """UPDATE knowledge_fact_candidates
                           SET rag_revision_id = %s,
                               extractor_release = 'project-native-rag-v1',
                               source_locator = 'line:1'
                           WHERE id = %s""",
                        (ids["revision"], legacy["fact"]),
                    )

            admin.execute(
                """INSERT INTO projects(id, tenant_id, name)
                   VALUES (%s, %s, 'F019 isolated project')""",
                (ids["project_two"], legacy["tenant"]),
            )
            admin.execute(
                """INSERT INTO knowledge_sources
                     (id, project_id, logical_source_id, source_kind, title,
                      media_type, raw_content, status, content_hash, created_by)
                   VALUES (%s, %s, %s, 'text', 'Other project source',
                           'text/plain', %s, 'ready', %s, %s)""",
                (
                    ids["source_two"],
                    ids["project_two"],
                    ids["source_two"],
                    b"other project",
                    _sha256("other project"),
                    legacy["owner"],
                ),
            )
            admin.commit()
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                with admin.transaction():
                    admin.execute(
                        """INSERT INTO knowledge_sources
                             (id, project_id, logical_source_id,
                              supersedes_source_id, source_kind, title,
                              media_type, raw_content, created_by)
                           VALUES (%s, %s, %s, %s, 'text', 'Cross project',
                                   'text/plain', %s, %s)""",
                        (
                            ids["invalid_source_revision"],
                            legacy["project"],
                            ids["source_two"],
                            legacy["source"],
                            b"invalid",
                            legacy["owner"],
                        ),
                    )

            protected_tables = (
                "knowledge_rag_job_specs",
                "knowledge_rag_revisions",
                "knowledge_fact_candidate_sources",
                "knowledge_entity_candidates",
                "knowledge_entity_candidate_sources",
                "knowledge_relation_candidates",
                "knowledge_rag_validation_findings",
                "knowledge_graph_entities",
                "knowledge_graph_entity_sources",
                "knowledge_graph_relations",
                "knowledge_graph_relation_sources",
            )
            rls = admin.execute(
                """SELECT relname, relrowsecurity, relforcerowsecurity
                   FROM pg_class WHERE relname = ANY(%s)""",
                (list(protected_tables),),
            ).fetchall()
            assert len(rls) == len(protected_tables)
            assert all(enabled and forced for _, enabled, forced in rls)
            assert admin.execute(
                """SELECT
                     has_table_privilege('geo_worker', 'knowledge_rag_job_specs', 'INSERT'),
                     has_table_privilege('geo_app', 'knowledge_rag_job_specs', 'INSERT'),
                     has_table_privilege('geo_app', 'knowledge_graph_entities', 'INSERT'),
                     has_table_privilege('geo_readonly', 'knowledge_graph_entities', 'UPDATE')"""
            ).fetchone() == (True, False, True, False)

        app_url = runtime_role_url(database_url, user="geo_app_dev")
        with psycopg.connect(app_url) as app:
            with app.transaction():
                set_project_scope(app, legacy["project"])
                assert app.execute(
                    "SELECT count(*) FROM knowledge_graph_entities"
                ).fetchone()[0] == 1
            with app.transaction():
                set_project_scope(app, ids["project_two"])
                assert app.execute(
                    "SELECT count(*) FROM knowledge_graph_entities"
                ).fetchone()[0] == 0

        with pytest.raises(DBAPIError, match="cannot downgrade"):
            command.downgrade(configuration, "0016_publication_verification")
