from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb
import pytest
from sqlalchemy.engine import URL


ROOT = Path(__file__).resolve().parents[2]
ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_URL,
        reason="GEO_ACCESS_TEST_ADMIN_DATABASE_URL is required",
    ),
]


@contextmanager
def _temporary_database() -> Iterator[tuple[str, Config]]:
    database_name = f"geo_batch2_{uuid4().hex[:12]}"
    admin_parameters = conninfo_to_dict(ADMIN_URL)
    maintenance_url = make_conninfo(**{**admin_parameters, "dbname": "postgres"})
    database_url = make_conninfo(**{**admin_parameters, "dbname": database_name})
    sqlalchemy_url = URL.create(
        "postgresql+psycopg",
        username=admin_parameters.get("user"),
        password=admin_parameters.get("password"),
        host=admin_parameters.get("host"),
        port=int(admin_parameters["port"]) if admin_parameters.get("port") else None,
        database=database_name,
    ).render_as_string(hide_password=False)
    with psycopg.connect(maintenance_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    configuration = Config(ROOT / "alembic.ini")
    configuration.attributes["geo_database_url_override"] = sqlalchemy_url
    try:
        yield database_url, configuration
    finally:
        with psycopg.connect(maintenance_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


def _sha256(value: bytes | str) -> str:
    payload = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _seed_legacy_fixture(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    ids = {
        name: uuid4()
        for name in (
            "tenant",
            "owner",
            "project",
            "product",
            "market",
            "query",
            "campaign",
            "destination",
            "opportunity",
            "skill",
            "skill_version",
            "release",
            "source",
            "run",
            "document",
            "chunk",
            "fact",
            "evidence",
            "protocol",
            "suggestion",
            "protocol_query",
            "observation",
            "metric",
        )
    }
    raw_source = b"Legacy source bytes"
    raw_text = "Legacy source bytes"
    cleaned_text = "A verified legacy fact."
    chunk_text = cleaned_text
    statement = cleaned_text
    hashes = {
        "source": _sha256(raw_source),
        "raw": _sha256(raw_text),
        "document": _sha256(cleaned_text),
        "chunk": _sha256(chunk_text),
        "fact": _sha256(statement),
    }
    payload_hash = _sha256("legacy-observation-payload")
    release_hash = _sha256("legacy-release")

    connection.execute(
        "INSERT INTO tenants(id, name) VALUES (%s, 'Batch2 legacy tenant')",
        (ids["tenant"],),
    )
    connection.execute(
        """INSERT INTO identities(id, issuer, subject, email)
           VALUES (%s, 'batch2-test', %s, 'batch2@example.invalid')""",
        (ids["owner"], str(ids["owner"])),
    )
    connection.execute(
        "INSERT INTO projects(id, tenant_id, name) VALUES (%s, %s, 'Batch2 legacy')",
        (ids["project"], ids["tenant"]),
    )
    connection.execute(
        """INSERT INTO product_entities
             (id, project_id, entity_type, canonical_name)
           VALUES (%s, %s, 'product', 'Legacy Product')""",
        (ids["product"], ids["project"]),
    )
    connection.execute(
        """INSERT INTO market_profiles
             (id, project_id, market_code, locale, timezone)
           VALUES (%s, %s, 'AU', 'en-AU', 'Australia/Sydney')""",
        (ids["market"], ids["project"]),
    )
    connection.execute(
        """INSERT INTO monitoring_queries
             (id, project_id, market_profile_id, query_text, query_kind, locale)
           VALUES (%s, %s, %s, 'Which product is recommended?', 'recommendation', 'en-AU')""",
        (ids["query"], ids["project"], ids["market"]),
    )
    connection.execute(
        """INSERT INTO geo_campaigns
             (id, project_id, market_profile_id, primary_product_entity_id,
              name, status, created_by)
           VALUES (%s, %s, %s, %s, 'Legacy campaign', 'active', %s)""",
        (
            ids["campaign"],
            ids["project"],
            ids["market"],
            ids["product"],
            ids["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO campaign_monitoring_queries
             (campaign_id, project_id, monitoring_query_id)
           VALUES (%s, %s, %s)""",
        (ids["campaign"], ids["project"], ids["query"]),
    )
    connection.execute(
        """INSERT INTO publication_destinations
             (id, project_id, publication_channel, destination_key,
              canonical_url, canonical_host, allowed_hosts)
           VALUES (%s, %s, 'owned_site', 'legacy-site',
                   'https://example.test/', 'example.test', ARRAY['example.test'])""",
        (ids["destination"], ids["project"]),
    )
    connection.execute(
        """INSERT INTO placement_opportunities
             (id, project_id, campaign_id, destination_id, opportunity_ref, rationale)
           VALUES (%s, %s, %s, %s, 'legacy-opportunity', 'Legacy fixture')""",
        (
            ids["opportunity"],
            ids["project"],
            ids["campaign"],
            ids["destination"],
        ),
    )
    connection.execute(
        "INSERT INTO prompt_skills(id, project_id, skill_key) VALUES (%s, %s, 'legacy')",
        (ids["skill"], ids["project"]),
    )
    connection.execute(
        """INSERT INTO prompt_skill_versions
             (id, project_id, skill_id, version_number, source_text, source_hash, created_by)
           VALUES (%s, %s, %s, 1, 'Legacy prompt', %s, %s)""",
        (
            ids["skill_version"],
            ids["project"],
            ids["skill"],
            _sha256("Legacy prompt"),
            ids["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO generation_template_releases
             (id, project_id, skill_version_id, release_number, system_template,
              user_template, variable_schema, output_schema, compiler_version, release_hash)
           VALUES (%s, %s, %s, 1, 'System', 'User', '{}'::jsonb, '{}'::jsonb,
                   'legacy-compiler', %s)""",
        (ids["release"], ids["project"], ids["skill_version"], release_hash),
    )

    connection.execute(
        """INSERT INTO knowledge_sources
             (id, project_id, source_kind, title, filename, media_type, status,
              raw_content, content_hash, created_by)
           VALUES (%s, %s, 'file', 'Legacy source', 'legacy.txt', 'text/plain',
                   'ready', %s, %s, %s)""",
        (ids["source"], ids["project"], raw_source, hashes["source"], ids["owner"]),
    )
    connection.execute(
        """INSERT INTO knowledge_pipeline_runs
             (id, project_id, source_id, status, input_hash, started_at,
              completed_at, created_by)
           VALUES (%s, %s, %s, 'succeeded', %s, clock_timestamp(),
                   clock_timestamp(), %s)""",
        (ids["run"], ids["project"], ids["source"], _sha256("input"), ids["owner"]),
    )
    connection.execute(
        """INSERT INTO knowledge_documents
             (id, project_id, pipeline_run_id, source_id, parser_version,
              raw_text, cleaned_text, raw_text_hash, cleaned_text_hash)
           VALUES (%s, %s, %s, %s, 'legacy-parser', %s, %s, %s, %s)""",
        (
            ids["document"],
            ids["project"],
            ids["run"],
            ids["source"],
            raw_text,
            cleaned_text,
            hashes["raw"],
            hashes["document"],
        ),
    )
    connection.execute(
        """INSERT INTO knowledge_chunks
             (id, project_id, pipeline_run_id, source_id, document_id, chunk_index,
              text, text_hash, char_count)
           VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s)""",
        (
            ids["chunk"],
            ids["project"],
            ids["run"],
            ids["source"],
            ids["document"],
            chunk_text,
            hashes["chunk"],
            len(chunk_text),
        ),
    )
    connection.execute(
        """INSERT INTO knowledge_fact_candidates
             (id, project_id, pipeline_run_id, source_id, chunk_id, statement,
              statement_hash, status, reviewed_by, reviewed_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 'approved', %s, clock_timestamp())""",
        (
            ids["fact"],
            ids["project"],
            ids["run"],
            ids["source"],
            ids["chunk"],
            statement,
            hashes["fact"],
            ids["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO evidence_items
             (id, project_id, item_type, source_id, subject_entity_id, subject_role,
              snapshot_text, snapshot_hash, source_revision_kind,
              source_revision_value, usage_rights, confidentiality,
              public_source_title)
           VALUES (%s, %s, 'approved_fact', %s, %s, 'product', %s, %s,
                   'content_hash', %s, 'owned', 'internal', 'Legacy source')""",
        (
            ids["evidence"],
            ids["project"],
            ids["source"],
            ids["product"],
            statement,
            hashes["fact"],
            hashes["source"],
        ),
    )

    connection.execute(
        """INSERT INTO monitoring_protocols
             (id, project_id, campaign_id, market_profile_id, name, platform,
              locale, device, sample_size, window_days, created_by)
           VALUES (%s, %s, %s, %s, 'Legacy protocol', 'chatgpt_search',
                   'en-AU', 'desktop', 1, 28, %s)""",
        (
            ids["protocol"],
            ids["project"],
            ids["campaign"],
            ids["market"],
            ids["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO monitoring_query_suggestions
             (id, project_id, protocol_id, query_text, query_kind, rationale,
              status, suggested_by, decided_by, decided_at)
           VALUES (%s, %s, %s, 'Which product is recommended?', 'recommendation',
                   'Legacy fixture', 'approved', %s, %s, clock_timestamp())""",
        (
            ids["suggestion"],
            ids["project"],
            ids["protocol"],
            ids["owner"],
            ids["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO monitoring_protocol_queries
             (id, project_id, protocol_id, monitoring_query_id, suggestion_id,
              ordinal, query_text_snapshot, query_kind_snapshot, locale_snapshot,
              approved_by)
           VALUES (%s, %s, %s, %s, %s, 1, 'Which product is recommended?',
                   'recommendation', 'en-AU', %s)""",
        (
            ids["protocol_query"],
            ids["project"],
            ids["protocol"],
            ids["query"],
            ids["suggestion"],
            ids["owner"],
        ),
    )
    connection.execute(
        """UPDATE monitoring_protocols
           SET status = 'approved', approved_by = %s, approved_at = clock_timestamp()
           WHERE id = %s AND project_id = %s""",
        (ids["owner"], ids["protocol"], ids["project"]),
    )
    connection.execute(
        """UPDATE monitoring_protocols
           SET status = 'frozen', frozen_by = %s, frozen_at = clock_timestamp(),
               protocol_hash = %s
           WHERE id = %s AND project_id = %s""",
        (
            ids["owner"],
            _sha256("legacy-protocol"),
            ids["protocol"],
            ids["project"],
        ),
    )
    connection.execute(
        """INSERT INTO monitoring_observations
             (id, project_id, protocol_id, campaign_id, monitoring_query_id,
              measurement_window, sample_index, result_status, eligible,
              url_verification_status, recommendation_present,
              primary_product_mentioned, raw_answer, raw_result, raw_citations,
              configured_model, provider_reported_model, ui_surface, ui_metadata,
              observed_at, imported_by, idempotency_key, payload_hash)
           VALUES (%s, %s, %s, %s, %s, 'baseline', 1, 'succeeded', true,
                   'unknown', true, true, 'Legacy raw answer', %s, %s,
                   'legacy-model', 'legacy-reported-model', 'legacy-ui', '{}'::jsonb,
                   clock_timestamp(), %s, 'legacy-observation', %s)""",
        (
            ids["observation"],
            ids["project"],
            ids["protocol"],
            ids["campaign"],
            ids["query"],
            Jsonb({"legacy": True}),
            Jsonb([]),
            ids["owner"],
            payload_hash,
        ),
    )
    connection.execute(
        """INSERT INTO monitoring_metric_snapshots
             (id, project_id, protocol_id, campaign_id, measurement_window,
              expected_sample_count, eligible_sample_count, recommendation_share,
              product_mention_share, placement_citation_share,
              qualified_destination_coverage, verified_placement_coverage,
              competitive_delta, status, input_hash, method_version, computed_by)
           VALUES (%s, %s, %s, %s, 'baseline', 1, 1, 1, 1, 0, 0, 0, 1,
                   'complete', %s, 'legacy-v1', %s)""",
        (
            ids["metric"],
            ids["project"],
            ids["protocol"],
            ids["campaign"],
            _sha256("legacy-metric"),
            ids["owner"],
        ),
    )
    connection.commit()
    return {
        **ids,
        "source_content_hash": hashes["source"],
        "fact_statement_hash": hashes["fact"],
        "payload_hash": payload_hash,
        "release_hash": release_hash,
    }


def test_populated_0011_fixture_round_trips_without_fabricating_truth() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0011_runtime_health")
        with psycopg.connect(database_url) as connection:
            fixture = _seed_legacy_fixture(connection)

        command.upgrade(configuration, "0014_observation_source_contract")
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0] == "0014_observation_source_contract"
            assert connection.execute(
                """SELECT status, is_legacy_backfill
                   FROM current_generation_template_release_states
                   WHERE template_release_id = %s""",
                (fixture["release"],),
            ).fetchone() == ("approved", True)
            assert connection.execute(
                """SELECT binding_state, is_legacy_backfill
                   FROM current_opportunity_prompt_release_bindings
                   WHERE opportunity_id = %s""",
                (fixture["opportunity"],),
            ).fetchone() == ("unbound", True)
            assert connection.execute(
                "SELECT document_id FROM knowledge_fact_candidates WHERE id = %s",
                (fixture["fact"],),
            ).fetchone()[0] == fixture["document"]
            assert connection.execute(
                """SELECT fact_lineage_status FROM evidence_items WHERE id = %s""",
                (fixture["evidence"],),
            ).fetchone()[0] == "legacy_unverified"
            assert connection.execute(
                """SELECT lineage_contract_version
                   FROM knowledge_fact_evidence_lineages
                   WHERE knowledge_fact_id = %s AND evidence_item_id = %s""",
                (fixture["fact"], fixture["evidence"]),
            ).fetchone()[0] == "legacy-relational-v1"
            observation = connection.execute(
                """SELECT eligible, eligibility_requested, capture_method, platform,
                          surface, surface_kind, raw_answer, raw_result, raw_citations,
                          artifact_uri, configured_model, provider_reported_model,
                          source_contract_version, source_stratum_hash,
                          publication_eligible, payload_hash
                   FROM monitoring_observations WHERE id = %s""",
                (fixture["observation"],),
            ).fetchone()
            assert observation == (
                False,
                False,
                "unknown",
                "other",
                "other",
                "other",
                "Legacy raw answer",
                {"legacy": True},
                [],
                None,
                "legacy-model",
                "legacy-reported-model",
                "legacy-v1",
                None,
                False,
                fixture["payload_hash"],
            )
            assert connection.execute(
                """SELECT eligible FROM monitoring_observation_legacy_migration_state
                   WHERE observation_id = %s""",
                (fixture["observation"],),
            ).fetchone()[0] is True
            assert connection.execute(
                """SELECT capture_method, source_contract_version, source_stratum_hash
                   FROM monitoring_metric_snapshots WHERE id = %s""",
                (fixture["metric"],),
            ).fetchone() == ("unknown", "legacy-v1", None)

            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute(
                        """INSERT INTO monitoring_observations
                             (project_id, protocol_id, campaign_id, monitoring_query_id,
                              measurement_window, sample_index, result_status,
                              eligibility_requested, eligible, ineligible_reasons,
                              url_verification_status, raw_result, raw_citations,
                              configured_model, configured_model_state,
                              provider_reported_model_state, ui_surface, ui_metadata,
                              observed_at, capture_method, platform, surface, surface_kind,
                              follow_up_prompts, raw_evidence_kind, citations_captured,
                              source_contract_version, test_only, publication_eligible,
                              imported_by, idempotency_key, payload_hash)
                           VALUES (%s, %s, %s, %s, 'baseline', 1, 'succeeded', false,
                                   false, ARRAY['official_not_allowed'], 'unknown',
                                   '{}'::jsonb, '[]'::jsonb, NULL, 'not_applicable',
                                   'not_applicable', 'other', '{}'::jsonb,
                                   clock_timestamp(), 'official_report_import', 'google',
                                   'other', 'official_report', '[]'::jsonb, 'artifact',
                                   false, 'geo-observation-source-v2', false, false,
                                   %s, 'forbidden-official', %s)""",
                        (
                            fixture["project"],
                            fixture["protocol"],
                            fixture["campaign"],
                            fixture["query"],
                            fixture["owner"],
                            _sha256("forbidden-official"),
                        ),
                    )
            assert connection.execute(
                """SELECT count(*) FROM monitoring_observations
                   WHERE idempotency_key = 'forbidden-official'"""
            ).fetchone()[0] == 0

        command.downgrade(configuration, "0011_runtime_health")
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                "SELECT eligible, raw_answer, payload_hash FROM monitoring_observations WHERE id = %s",
                (fixture["observation"],),
            ).fetchone() == (True, "Legacy raw answer", fixture["payload_hash"])
            assert connection.execute(
                """SELECT count(*) FROM information_schema.columns
                   WHERE table_name = 'knowledge_fact_candidates'
                     AND column_name = 'document_id'"""
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT count(*) FROM knowledge_fact_candidates WHERE id = %s",
                (fixture["fact"],),
            ).fetchone()[0] == 1

        command.upgrade(configuration, "0014_observation_source_contract")
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0] == "0014_observation_source_contract"
            assert connection.execute(
                "SELECT count(*) FROM alembic_sql_checksum_ledger"
            ).fetchone()[0] == 14


def _seed_official_parent(connection: psycopg.Connection[Any]) -> dict[str, UUID]:
    ids = {name: uuid4() for name in ("tenant", "owner", "project", "product", "market", "campaign")}
    connection.execute(
        "INSERT INTO tenants(id, name) VALUES (%s, 'Official import tenant')",
        (ids["tenant"],),
    )
    connection.execute(
        "INSERT INTO identities(id, issuer, subject) VALUES (%s, 'batch2-test', %s)",
        (ids["owner"], str(ids["owner"])),
    )
    connection.execute(
        "INSERT INTO projects(id, tenant_id, name) VALUES (%s, %s, 'Official import')",
        (ids["project"], ids["tenant"]),
    )
    connection.execute(
        """INSERT INTO product_entities
             (id, project_id, entity_type, canonical_name)
           VALUES (%s, %s, 'product', 'Official Product')""",
        (ids["product"], ids["project"]),
    )
    connection.execute(
        """INSERT INTO market_profiles
             (id, project_id, market_code, locale, timezone)
           VALUES (%s, %s, 'AU', 'en-AU', 'Australia/Sydney')""",
        (ids["market"], ids["project"]),
    )
    connection.execute(
        """INSERT INTO geo_campaigns
             (id, project_id, market_profile_id, primary_product_entity_id,
              name, created_by)
           VALUES (%s, %s, %s, %s, 'Official campaign', %s)""",
        (
            ids["campaign"], ids["project"], ids["market"], ids["product"], ids["owner"]
        ),
    )
    return ids


def test_official_projection_data_blocks_observation_contract_downgrade() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0014_observation_source_contract")
        with psycopg.connect(database_url) as connection:
            fixture = _seed_official_parent(connection)
            imported = connection.execute(
                """INSERT INTO monitoring_official_report_imports
                     (project_id, campaign_id, platform, surface, artifact_uri,
                      artifact_hash, parser_name, parser_version, report_period_start,
                      report_period_end, account_ref, row_count, idempotency_key,
                      payload_hash, imported_by)
                   VALUES (%s, %s, 'google',
                           'google_generative_ai_performance_report',
                           's3://official/report.json', %s, 'fixture-parser', '1',
                           DATE '2026-06-01', DATE '2026-06-30', 'account-1', 1,
                           'official-fixture', %s, %s)
                   RETURNING id""",
                (
                    fixture["project"],
                    fixture["campaign"],
                    _sha256("official-artifact"),
                    _sha256("official-payload"),
                    fixture["owner"],
                ),
            ).fetchone()[0]
            connection.execute(
                """INSERT INTO monitoring_official_report_rows
                     (project_id, campaign_id, import_id, row_index, row_data,
                      eligible, row_hash)
                   VALUES (%s, %s, %s, 0, '{"metric":1}'::jsonb, true, %s)""",
                (
                    fixture["project"],
                    fixture["campaign"],
                    imported,
                    _sha256("official-row"),
                ),
            )
            connection.commit()

        with pytest.raises(Exception, match="cannot downgrade: typed observation source data exists"):
            command.downgrade(configuration, "0013_fact_evidence_lineage")
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0] == "0014_observation_source_contract"
            assert connection.execute(
                "SELECT count(*) FROM monitoring_official_report_imports"
            ).fetchone()[0] == 1
