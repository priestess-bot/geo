from __future__ import annotations

import hashlib
import os
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


def _insert_metric_snapshot(
    connection: psycopg.Connection[object],
    *,
    snapshot_id: UUID,
    fixture: dict[str, object],
    measurement_window: str,
    source_hash: str,
    cluster_key: str,
    sampled_count: int,
    membership_hash: str | None,
) -> None:
    connection.execute(
        """INSERT INTO monitoring_metric_snapshots
             (id, project_id, protocol_id, campaign_id, measurement_window,
              expected_sample_count, eligible_sample_count,
              recommendation_share, product_mention_share,
              placement_citation_share, qualified_destination_coverage,
              verified_placement_coverage, competitive_delta, status,
              confounded_reasons, input_hash, method_version, computed_by,
              source_stratum, source_stratum_hash, capture_method,
              source_contract_version, statistics_contract_version,
              query_cluster_key, analysis_stratum_hash, minimum_valid_repeats,
              sampled_sample_count, invalid_sample_count, missing_sample_count,
              sampling_completion_ratio, valid_completion_ratio, query_count,
              sufficient_query_count, invalid_reason_counts,
              declared_confounding_factors, query_results_snapshot,
              recommendation_ci_low, recommendation_ci_high,
              product_mention_ci_low, product_mention_ci_high,
              placement_citation_ci_low, placement_citation_ci_high,
              recommendation_query_min, recommendation_query_max,
              product_mention_query_min, product_mention_query_max,
              placement_citation_query_min, placement_citation_query_max,
              worst_query_id, selected_destination_ids,
              qualified_destination_ids, verified_destination_ids, result_hash,
              observation_membership_version, observation_membership_count,
              observation_membership_hash)
           VALUES
             (%s, %s, %s, %s, %s, 1, %s,
              0, 0, 0, 0, 0, 0, %s, ARRAY[]::text[], %s,
              'geo-observation-statistics-v2', %s, '{"test":true}'::jsonb,
              %s, 'manual_ui', 'geo-observation-source-v2',
              'geo-observation-statistics-v2', %s, %s, 3,
              %s, 0, %s, %s, %s, 1, %s, '{}'::jsonb,
              ARRAY[]::text[], '[]'::jsonb,
              0, 1, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0,
              %s, ARRAY[]::uuid[], ARRAY[]::uuid[], ARRAY[]::uuid[], %s,
              %s, %s, %s)""",
        (
            snapshot_id,
            fixture["project"],
            fixture["protocol"],
            fixture["campaign"],
            measurement_window,
            sampled_count,
            "insufficient_evidence" if sampled_count < 3 else "complete",
            _sha256(f"metric-input:{snapshot_id}"),
            fixture["owner"],
            source_hash,
            cluster_key,
            _sha256(f"analysis:{snapshot_id}"),
            sampled_count,
            1 - sampled_count,
            sampled_count,
            sampled_count,
            0,
            fixture["query"],
            _sha256(f"result:{snapshot_id}"),
            "metric-observation-membership-v1" if membership_hash is not None else None,
            sampled_count if membership_hash is not None else None,
            membership_hash,
        ),
    )


def test_metric_membership_preserves_legacy_snapshot_round_trip() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0011_runtime_health")
        with psycopg.connect(database_url) as admin:
            legacy = _seed_legacy_fixture(admin)
        command.upgrade(configuration, "0018_metric_membership")

        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                """SELECT observation_membership_version,
                          observation_membership_count,
                          observation_membership_hash, input_hash
                   FROM monitoring_metric_snapshots WHERE id = %s""",
                (legacy["metric"],),
            ).fetchone() == (None, None, None, _sha256("legacy-metric"))
            assert admin.execute(
                "SELECT count(*) FROM monitoring_metric_snapshot_observations"
            ).fetchone()[0] == 0

        command.downgrade(configuration, "0017_knowledge_rag_graph")
        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                "SELECT input_hash FROM monitoring_metric_snapshots WHERE id = %s",
                (legacy["metric"],),
            ).fetchone()[0] == _sha256("legacy-metric")
            assert admin.execute(
                "SELECT to_regclass('public.monitoring_metric_snapshot_observations')"
            ).fetchone()[0] is None
        command.upgrade(configuration, "0018_metric_membership")


def test_metric_membership_manifest_exact_lineage_rls_and_fail_closed_down() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0011_runtime_health")
        with psycopg.connect(database_url) as admin:
            fixture = _seed_legacy_fixture(admin)
        command.upgrade(configuration, "0018_metric_membership")

        observation_id = uuid4()
        snapshot_id = uuid4()
        empty_snapshot_id = uuid4()
        payload_hash = _sha256("membership-observation")
        source_hash = _sha256("membership-source-stratum")
        cluster_key = "membership-cluster"
        manifest_hash = _sha256(f"1:{observation_id}:{payload_hash}\n")

        with psycopg.connect(database_url) as admin:
            admin.execute("SET session_replication_role = replica")
            admin.execute(
                """INSERT INTO monitoring_observations
                     (id, project_id, protocol_id, campaign_id,
                      monitoring_query_id, measurement_window, sample_index,
                      result_status, eligible, ineligible_reasons,
                      url_verification_status, raw_answer, raw_result,
                      raw_citations, configured_model, provider_reported_model,
                      ui_surface, ui_metadata, observed_at, imported_by,
                      idempotency_key, payload_hash, eligibility_requested,
                      capture_method, platform, surface, surface_kind, engine,
                      configured_model_state, provider_reported_model_state,
                      locale, region, language, observation_device, client_kind,
                      search_enabled, search_mode, prompt_text, follow_up_prompts,
                      raw_evidence_kind, citations_captured,
                      source_contract_version, source_stratum_hash,
                      query_cluster_key, publication_eligible)
                   VALUES
                     (%s, %s, %s, %s, %s, 't84', 1, 'succeeded', true,
                      ARRAY[]::text[], 'unknown', 'Membership evidence',
                      '{}'::jsonb, '[]'::jsonb, 'fixture-model', NULL,
                      'chatgpt_search', '{}'::jsonb, clock_timestamp(), %s,
                      %s, %s, true, 'manual_ui', 'openai', 'chatgpt_search',
                      'consumer_ui', 'chatgpt', 'disclosed', 'not_disclosed',
                      'en-AU', 'AU', 'en', 'desktop', 'browser', true,
                      'live_web', 'Fixture prompt', '[]'::jsonb, 'answer', true,
                      'geo-observation-source-v2', %s, %s, true)""",
                (
                    observation_id,
                    fixture["project"],
                    fixture["protocol"],
                    fixture["campaign"],
                    fixture["query"],
                    fixture["owner"],
                    f"membership-observation:{observation_id}",
                    payload_hash,
                    source_hash,
                    cluster_key,
                ),
            )
            admin.execute("SET session_replication_role = origin")
            admin.commit()

            admin.execute(
                "ALTER TABLE monitoring_metric_snapshots "
                "DISABLE TRIGGER monitoring_metric_source_stratum_guard"
            )
            admin.execute(
                "ALTER TABLE monitoring_metric_snapshots "
                "DISABLE TRIGGER monitoring_metric_statistics_guard"
            )
            admin.commit()

            _insert_metric_snapshot(
                admin,
                snapshot_id=snapshot_id,
                fixture=fixture,
                measurement_window="t84",
                source_hash=source_hash,
                cluster_key=cluster_key,
                sampled_count=1,
                membership_hash=manifest_hash,
            )
            admin.execute(
                """INSERT INTO monitoring_metric_snapshot_observations
                     (snapshot_id, project_id, campaign_id, protocol_id,
                      observation_id, payload_hash, ordinal)
                   VALUES (%s, %s, %s, %s, %s, %s, 1)""",
                (
                    snapshot_id,
                    fixture["project"],
                    fixture["campaign"],
                    fixture["protocol"],
                    observation_id,
                    payload_hash,
                ),
            )
            _insert_metric_snapshot(
                admin,
                snapshot_id=empty_snapshot_id,
                fixture=fixture,
                measurement_window="ad_hoc",
                source_hash=source_hash,
                cluster_key=cluster_key,
                sampled_count=0,
                membership_hash=hashlib.sha256(b"").hexdigest(),
            )
            admin.commit()

            assert admin.execute(
                """SELECT campaign_id, protocol_id, observation_id, payload_hash,
                          ordinal
                   FROM monitoring_metric_snapshot_observations
                   WHERE snapshot_id = %s""",
                (snapshot_id,),
            ).fetchone() == (
                fixture["campaign"],
                fixture["protocol"],
                observation_id,
                payload_hash,
                1,
            )
            assert admin.execute(
                """SELECT observation_membership_count,
                          observation_membership_hash
                   FROM monitoring_metric_snapshots WHERE id = %s""",
                (empty_snapshot_id,),
            ).fetchone() == (0, hashlib.sha256(b"").hexdigest())

            with pytest.raises(psycopg.errors.CheckViolation):
                with admin.transaction():
                    _insert_metric_snapshot(
                        admin,
                        snapshot_id=uuid4(),
                        fixture=fixture,
                        measurement_window="t56",
                        source_hash=source_hash,
                        cluster_key=cluster_key,
                        sampled_count=0,
                        membership_hash=None,
                    )
            with pytest.raises(psycopg.errors.CheckViolation):
                with admin.transaction():
                    admin.execute(
                        """INSERT INTO monitoring_metric_snapshot_observations
                             (snapshot_id, project_id, campaign_id, protocol_id,
                              observation_id, payload_hash, ordinal)
                           VALUES (%s, %s, %s, %s, %s, %s, 2)""",
                        (
                            empty_snapshot_id,
                            fixture["project"],
                            fixture["campaign"],
                            fixture["protocol"],
                            observation_id,
                            payload_hash,
                        ),
                    )
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                with admin.transaction():
                    admin.execute(
                        """UPDATE monitoring_metric_snapshot_observations
                           SET ordinal = 2 WHERE snapshot_id = %s""",
                        (snapshot_id,),
                    )

            admin.execute(
                "ALTER TABLE monitoring_metric_snapshots "
                "ENABLE TRIGGER monitoring_metric_source_stratum_guard"
            )
            admin.execute(
                "ALTER TABLE monitoring_metric_snapshots "
                "ENABLE TRIGGER monitoring_metric_statistics_guard"
            )
            admin.commit()

            assert admin.execute(
                """SELECT relrowsecurity, relforcerowsecurity FROM pg_class
                   WHERE relname = 'monitoring_metric_snapshot_observations'"""
            ).fetchone() == (True, True)
            assert admin.execute(
                """SELECT
                    has_table_privilege(
                        'geo_app', 'monitoring_metric_snapshot_observations', 'INSERT'
                    ),
                    has_table_privilege(
                        'geo_worker', 'monitoring_metric_snapshot_observations', 'SELECT'
                    ),
                    has_table_privilege(
                        'geo_readonly', 'monitoring_metric_snapshot_observations', 'UPDATE'
                    )"""
            ).fetchone() == (True, True, False)

        with pytest.raises(DBAPIError, match="frozen metric observation membership exists"):
            command.downgrade(configuration, "0017_knowledge_rag_graph")
