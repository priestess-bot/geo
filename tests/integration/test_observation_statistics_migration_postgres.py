from __future__ import annotations

import json
import os
from uuid import uuid4

from alembic import command
import psycopg
from psycopg.types.json import Jsonb
import pytest

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


def test_populated_0014_statistics_contract_round_trips_without_inventing_results() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0011_runtime_health")
        with psycopg.connect(database_url) as connection:
            fixture = _seed_legacy_fixture(connection)

        command.upgrade(configuration, "0014_observation_source_contract")
        with psycopg.connect(database_url) as connection:
            legacy_metric = connection.execute(
                """SELECT expected_sample_count, eligible_sample_count,
                          recommendation_share, product_mention_share,
                          placement_citation_share, qualified_destination_coverage,
                          verified_placement_coverage, competitive_delta, status,
                          confounded_reasons, input_hash, method_version,
                          source_contract_version, capture_method, source_stratum_hash
                   FROM monitoring_metric_snapshots WHERE id = %s""",
                (fixture["metric"],),
            ).fetchone()

        command.upgrade(configuration, "0015_observation_statistics_v2")
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                """SELECT statistics_contract_version, minimum_valid_repeats,
                          statistics_method_version
                   FROM monitoring_protocols WHERE id = %s""",
                (fixture["protocol"],),
            ).fetchone() == ("legacy-v1", None, None)
            migrated_metric = connection.execute(
                """SELECT expected_sample_count, eligible_sample_count,
                          recommendation_share, product_mention_share,
                          placement_citation_share, qualified_destination_coverage,
                          verified_placement_coverage, competitive_delta, status,
                          confounded_reasons, input_hash, method_version,
                          source_contract_version, capture_method, source_stratum_hash
                   FROM monitoring_metric_snapshots WHERE id = %s""",
                (fixture["metric"],),
            ).fetchone()
            assert migrated_metric == legacy_metric
            statistics_shape = connection.execute(
                """SELECT statistics_contract_version, query_cluster_key,
                          analysis_stratum_hash, minimum_valid_repeats,
                          sampled_sample_count, invalid_sample_count,
                          missing_sample_count, sampling_completion_ratio,
                          valid_completion_ratio, query_count,
                          sufficient_query_count, invalid_reason_counts,
                          declared_confounding_factors, query_results_snapshot,
                          recommendation_ci_low, recommendation_ci_high,
                          product_mention_ci_low, product_mention_ci_high,
                          placement_citation_ci_low, placement_citation_ci_high,
                          recommendation_query_min, recommendation_query_max,
                          product_mention_query_min, product_mention_query_max,
                          placement_citation_query_min, placement_citation_query_max,
                          worst_query_id, selected_destination_ids,
                          qualified_destination_ids, verified_destination_ids,
                          result_hash
                   FROM monitoring_metric_snapshots WHERE id = %s""",
                (fixture["metric"],),
            ).fetchone()
            assert statistics_shape[0] == "legacy-v1"
            assert statistics_shape[1:] == (None,) * (len(statistics_shape) - 1)

            canonical = json.dumps(
                {
                    "query_cluster_key": 'cluster-\u6d4b\u8bd5"\\\n',
                    "source_stratum_hash": "a" * 64,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            database_hash = connection.execute(
                "SELECT geo_analysis_stratum_hash(%s, %s)",
                ('cluster-\u6d4b\u8bd5"\\\n', "a" * 64),
            ).fetchone()[0]
            assert database_hash == _sha256(canonical)

        command.downgrade(configuration, "0014_observation_source_contract")
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                """SELECT count(*) FROM information_schema.columns
                   WHERE table_name = 'monitoring_metric_snapshots'
                     AND column_name = 'statistics_contract_version'"""
            ).fetchone()[0] == 0
            assert connection.execute(
                """SELECT expected_sample_count, eligible_sample_count,
                          recommendation_share, product_mention_share,
                          placement_citation_share, qualified_destination_coverage,
                          verified_placement_coverage, competitive_delta, status,
                          confounded_reasons, input_hash, method_version,
                          source_contract_version, capture_method, source_stratum_hash
                   FROM monitoring_metric_snapshots WHERE id = %s""",
                (fixture["metric"],),
            ).fetchone() == legacy_metric

        command.upgrade(configuration, "0015_observation_statistics_v2")
        source_stratum = {
            "capture_method": "manual_ui",
            "platform": "openai",
            "surface": "chatgpt_search",
            "surface_kind": "consumer_ui",
            "engine": "chatgpt",
            "configured_model": {"state": "disclosed", "value": "test-model"},
            "reported_model": {"state": "not_disclosed", "value": None},
            "locale": "en-AU",
            "region": "AU",
            "language": "en",
            "device": "desktop",
            "client_kind": "browser",
            "search_enabled": True,
            "search_mode": "live_web",
        }
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                "SELECT count(*) FROM alembic_sql_checksum_ledger"
            ).fetchone()[0] == 15
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute(
                        """INSERT INTO monitoring_protocols
                             (project_id, campaign_id, market_profile_id, name,
                              platform, locale, device, sample_size, window_days,
                              created_by, source_strata_snapshot, source_strata_hash,
                              statistics_contract_version)
                           VALUES (%s, %s, %s, 'Forbidden legacy protocol',
                                   'chatgpt_search', 'en-AU', 'desktop', 3, 28,
                                   %s, %s,
                                   geo_source_strata_inventory_hash(%s), 'legacy-v1')""",
                        (
                            fixture["project"],
                            fixture["campaign"],
                            fixture["market"],
                            fixture["owner"],
                            Jsonb([source_stratum]),
                            Jsonb([source_stratum]),
                        ),
                    )
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute(
                        """INSERT INTO monitoring_protocols
                             (project_id, campaign_id, market_profile_id, name,
                              platform, locale, device, sample_size, window_days,
                              created_by, source_strata_snapshot, source_strata_hash,
                              minimum_valid_repeats, statistics_method_version)
                           VALUES (%s, %s, %s, 'Too small v2 protocol',
                                   'chatgpt_search', 'en-AU', 'desktop', 2, 28,
                                   %s, %s, geo_source_strata_inventory_hash(%s),
                                   2, 'geo-observation-statistics-v2')""",
                        (
                            fixture["project"],
                            fixture["campaign"],
                            fixture["market"],
                            fixture["owner"],
                            Jsonb([source_stratum]),
                            Jsonb([source_stratum]),
                        ),
                    )
            protocol_id = connection.execute(
                """INSERT INTO monitoring_protocols
                     (project_id, campaign_id, market_profile_id, name,
                      platform, locale, device, sample_size, window_days,
                      created_by, source_strata_snapshot, source_strata_hash,
                      minimum_valid_repeats, statistics_method_version)
                   VALUES (%s, %s, %s, 'Valid v2 protocol',
                           'chatgpt_search', 'en-AU', 'desktop', 3, 28,
                           %s, %s, geo_source_strata_inventory_hash(%s),
                           3, 'geo-observation-statistics-v2')
                   RETURNING id""",
                (
                    fixture["project"],
                    fixture["campaign"],
                    fixture["market"],
                    fixture["owner"],
                    Jsonb([source_stratum]),
                    Jsonb([source_stratum]),
                ),
            ).fetchone()[0]
            cluster_key = "recommendation-core"
            suggestion_id = uuid4()
            connection.execute(
                """INSERT INTO monitoring_query_suggestions
                     (id, project_id, protocol_id, query_text, query_kind,
                      rationale, status, suggested_by, decided_by, decided_at,
                      query_cluster_key)
                   VALUES (%s, %s, %s, 'Which product is recommended?',
                           'recommendation', 'Statistics migration fixture',
                           'approved', %s, %s, clock_timestamp(), %s)""",
                (
                    suggestion_id,
                    fixture["project"],
                    protocol_id,
                    fixture["owner"],
                    fixture["owner"],
                    cluster_key,
                ),
            )
            connection.execute(
                """INSERT INTO monitoring_protocol_queries
                     (project_id, protocol_id, monitoring_query_id, suggestion_id,
                      ordinal, query_text_snapshot, query_kind_snapshot,
                      locale_snapshot, approved_by, query_cluster_key)
                   VALUES (%s, %s, %s, %s, 1,
                           'Which product is recommended?', 'recommendation',
                           'en-AU', %s, %s)""",
                (
                    fixture["project"],
                    protocol_id,
                    fixture["query"],
                    suggestion_id,
                    fixture["owner"],
                    cluster_key,
                ),
            )
            connection.execute(
                """UPDATE monitoring_protocols
                   SET status = 'approved', approved_by = %s,
                       approved_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s""",
                (fixture["owner"], protocol_id, fixture["project"]),
            )
            connection.execute(
                """UPDATE monitoring_protocols
                   SET status = 'frozen', frozen_by = %s,
                       frozen_at = clock_timestamp(), protocol_hash = %s
                   WHERE id = %s AND project_id = %s""",
                (
                    fixture["owner"],
                    _sha256("statistics-v2-protocol"),
                    protocol_id,
                    fixture["project"],
                ),
            )
            source_hash = connection.execute(
                "SELECT geo_source_stratum_hash_from_json(%s)",
                (Jsonb(source_stratum),),
            ).fetchone()[0]
            analysis_hash = connection.execute(
                "SELECT geo_analysis_stratum_hash(%s, %s)",
                (cluster_key, source_hash),
            ).fetchone()[0]
            empty_estimate = {
                "numerator": 0,
                "denominator": 0,
                "share": 0.0,
                "ci_low": 0.0,
                "ci_high": 1.0,
            }
            query_result = {
                "monitoring_query_id": str(fixture["query"]),
                "query_text_snapshot": "Which product is recommended?",
                "query_cluster_key": cluster_key,
                "expected_sample_count": 3,
                "sampled_sample_count": 0,
                "valid_sample_count": 0,
                "invalid_sample_count": 0,
                "missing_sample_count": 3,
                "meets_threshold": False,
                "invalid_reason_counts": {},
                "confounding_factors": [],
                "recommendation": empty_estimate,
                "product_mention": empty_estimate,
                "placement_citation": empty_estimate,
                "competitor": empty_estimate,
                "competitive_delta": 0.0,
            }
            metric_sql = """INSERT INTO monitoring_metric_snapshots
                 (project_id, protocol_id, campaign_id, measurement_window,
                  expected_sample_count, eligible_sample_count,
                  recommendation_share, product_mention_share,
                  placement_citation_share, qualified_destination_coverage,
                  verified_placement_coverage, competitive_delta, status,
                  confounded_reasons, input_hash, method_version, computed_by,
                  source_stratum, source_stratum_hash, capture_method,
                  source_contract_version, statistics_contract_version,
                  query_cluster_key, analysis_stratum_hash,
                  minimum_valid_repeats, sampled_sample_count,
                  invalid_sample_count, missing_sample_count,
                  sampling_completion_ratio, valid_completion_ratio,
                  query_count, sufficient_query_count, invalid_reason_counts,
                  declared_confounding_factors, query_results_snapshot,
                  recommendation_ci_low, recommendation_ci_high,
                  product_mention_ci_low, product_mention_ci_high,
                  placement_citation_ci_low, placement_citation_ci_high,
                  recommendation_query_min, recommendation_query_max,
                  product_mention_query_min, product_mention_query_max,
                  placement_citation_query_min, placement_citation_query_max,
                  worst_query_id, selected_destination_ids,
                  qualified_destination_ids, verified_destination_ids, result_hash)
               VALUES
                 (%(project_id)s, %(protocol_id)s, %(campaign_id)s, %(window)s,
                  3, %(eligible_sample_count)s, %(recommendation_share)s,
                  %(product_mention_share)s, %(placement_citation_share)s,
                  0, 0, %(competitive_delta)s, 'insufficient_evidence',
                  ARRAY['insufficient_query_samples'], %(input_hash)s,
                  'geo-observation-statistics-v2', %(computed_by)s,
                  %(source_stratum)s, %(source_hash)s, 'manual_ui',
                  'geo-observation-source-v2', 'geo-observation-statistics-v2',
                  %(cluster_key)s, %(analysis_hash)s, 3,
                  %(sampled_sample_count)s, %(invalid_sample_count)s,
                  %(missing_sample_count)s,
                  %(sampling_completion_ratio)s, %(valid_completion_ratio)s, 1, 0,
                  %(invalid_reason_counts)s, ARRAY[]::text[], %(query_results)s,
                  0, 1, 0, 1, 0, 1,
                  %(recommendation_query_min)s, %(recommendation_query_max)s,
                  %(product_mention_query_min)s, %(product_mention_query_max)s,
                  %(placement_citation_query_min)s, %(placement_citation_query_max)s,
                  %(worst_query_id)s, ARRAY[]::uuid[], ARRAY[]::uuid[],
                  ARRAY[]::uuid[], %(result_hash)s)
               RETURNING id"""
            metric_parameters = {
                "project_id": fixture["project"],
                "protocol_id": protocol_id,
                "campaign_id": fixture["campaign"],
                "window": "baseline",
                "input_hash": _sha256("statistics-v2-input"),
                "computed_by": fixture["owner"],
                "source_stratum": Jsonb(source_stratum),
                "source_hash": source_hash,
                "cluster_key": cluster_key,
                "analysis_hash": analysis_hash,
                "sampled_sample_count": 0,
                "eligible_sample_count": 0,
                "invalid_sample_count": 0,
                "missing_sample_count": 3,
                "sampling_completion_ratio": 0,
                "valid_completion_ratio": 0,
                "recommendation_share": 0,
                "product_mention_share": 0,
                "placement_citation_share": 0,
                "competitive_delta": 0,
                "recommendation_query_min": 0,
                "recommendation_query_max": 0,
                "product_mention_query_min": 0,
                "product_mention_query_max": 0,
                "placement_citation_query_min": 0,
                "placement_citation_query_max": 0,
                "invalid_reason_counts": Jsonb({}),
                "query_results": Jsonb([query_result]),
                "worst_query_id": fixture["query"],
                "result_hash": _sha256("statistics-v2-result"),
            }
            metric_id = connection.execute(metric_sql, metric_parameters).fetchone()[0]
            connection.commit()
            assert connection.execute(
                """SELECT status, sampled_sample_count, missing_sample_count,
                          sufficient_query_count
                   FROM monitoring_metric_snapshots WHERE id = %s""",
                (metric_id,),
            ).fetchone() == ("insufficient_evidence", 0, 3, 0)
            partial_estimate = {
                "numerator": 0,
                "denominator": 1,
                "share": 0.0,
                "ci_low": 0.0,
                "ci_high": 1.0,
            }
            partial_recommendation = {
                **partial_estimate,
                "numerator": 1,
                "share": 1.0,
            }
            partial_result = {
                **query_result,
                "sampled_sample_count": 1,
                "valid_sample_count": 1,
                "missing_sample_count": 2,
                "recommendation": partial_recommendation,
                "product_mention": partial_estimate,
                "placement_citation": partial_estimate,
                "competitor": partial_estimate,
            }
            partial_parameters = {
                **metric_parameters,
                "window": "t28",
                "input_hash": _sha256("statistics-v2-partial-input"),
                "sampled_sample_count": 1,
                "eligible_sample_count": 1,
                "missing_sample_count": 2,
                "sampling_completion_ratio": 0.333333,
                "valid_completion_ratio": 0.333333,
                "recommendation_share": 1,
                "recommendation_query_min": 1,
                "recommendation_query_max": 1,
                "query_results": Jsonb([partial_result]),
                "result_hash": _sha256("statistics-v2-partial-result"),
            }
            partial_metric_id = connection.execute(
                metric_sql, partial_parameters
            ).fetchone()[0]
            connection.commit()
            assert connection.execute(
                """SELECT status, sampled_sample_count, eligible_sample_count,
                          invalid_sample_count, missing_sample_count,
                          invalid_reason_counts
                   FROM monitoring_metric_snapshots WHERE id = %s""",
                (partial_metric_id,),
            ).fetchone() == ("insufficient_evidence", 1, 1, 0, 2, {})
            invalid_observation_result = {
                **query_result,
                "sampled_sample_count": 1,
                "invalid_sample_count": 1,
                "missing_sample_count": 2,
                "invalid_reason_counts": {"provider_failure": 1},
            }
            invalid_observation_parameters = {
                **metric_parameters,
                "window": "t56",
                "input_hash": _sha256("statistics-v2-invalid-observation-input"),
                "sampled_sample_count": 1,
                "invalid_sample_count": 1,
                "missing_sample_count": 2,
                "sampling_completion_ratio": 0.333333,
                "invalid_reason_counts": Jsonb({"provider_failure": 1}),
                "query_results": Jsonb([invalid_observation_result]),
                "result_hash": _sha256("statistics-v2-invalid-observation-result"),
            }
            invalid_observation_metric_id = connection.execute(
                metric_sql, invalid_observation_parameters
            ).fetchone()[0]
            connection.commit()
            assert connection.execute(
                """SELECT invalid_sample_count, missing_sample_count,
                          invalid_reason_counts
                   FROM monitoring_metric_snapshots WHERE id = %s""",
                (invalid_observation_metric_id,),
            ).fetchone() == (1, 2, {"provider_failure": 1})
            mismatched_reasons_parameters = {
                **invalid_observation_parameters,
                "window": "t84",
                "input_hash": _sha256("statistics-v2-mismatched-reasons-input"),
                "invalid_reason_counts": Jsonb({"wrong_reason": 1}),
                "result_hash": _sha256("statistics-v2-mismatched-reasons-result"),
            }
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute(metric_sql, mismatched_reasons_parameters)
            invalid_parameters = {
                **metric_parameters,
                "input_hash": _sha256("statistics-v2-invalid-input"),
                "sampled_sample_count": 1,
                "result_hash": _sha256("statistics-v2-invalid-result"),
            }
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute(metric_sql, invalid_parameters)

        with pytest.raises(Exception, match="observation statistics v2 data exists"):
            command.downgrade(configuration, "0014_observation_source_contract")
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0] == "0015_observation_statistics_v2"
