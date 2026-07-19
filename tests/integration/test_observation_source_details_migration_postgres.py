from __future__ import annotations

import hashlib
import json
import os
from uuid import UUID, uuid4

from alembic import command
import psycopg
from psycopg.types.json import Jsonb
import pytest
from sqlalchemy.exc import DBAPIError

from geo_core.project_scope import set_project_scope
from tests.integration.test_batch2_migrations_postgres import (
    _seed_legacy_fixture,
    _sha256,
    _temporary_database,
)
from tests.integration.test_metric_observation_membership_migration_postgres import (
    _insert_metric_snapshot,
)


ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_URL,
        reason="GEO_ACCESS_TEST_ADMIN_DATABASE_URL is required",
    ),
]


def _stratum(
    *,
    platform: str = "openai",
    platform_detail: str | None = None,
    surface: str = "chatgpt_search",
    surface_detail: str | None = None,
) -> dict[str, object]:
    return {
        "capture_method": "manual_ui",
        "platform": platform,
        "platform_detail": platform_detail,
        "surface": surface,
        "surface_kind": "consumer_ui",
        "surface_detail": surface_detail,
        "engine": "chatgpt",
        "configured_model": {"state": "disclosed", "value": "model-v1"},
        "reported_model": {"state": "not_disclosed", "value": None},
        "locale": "en-AU",
        "region": "AU",
        "language": "en",
        "device": "desktop",
        "client_kind": "browser",
        "search_enabled": True,
        "search_mode": "live_web",
    }


def _v2_stratum() -> dict[str, object]:
    value = _stratum()
    del value["platform_detail"]
    del value["surface_detail"]
    return value


def _insert_protocol(
    connection: psycopg.Connection[object],
    fixture: dict[str, object],
    *,
    snapshot: list[dict[str, object]],
    inventory_hash: str,
    name: str,
) -> UUID:
    return connection.execute(
        """INSERT INTO monitoring_protocols
             (project_id, campaign_id, market_profile_id, name, platform,
              locale, device, sample_size, minimum_valid_repeats, window_days,
              statistics_method_version, statistics_contract_version,
              source_strata_snapshot, source_strata_hash, created_by)
           VALUES (%s, %s, %s, %s, 'chatgpt_search', 'en-AU', 'desktop',
                   3, 3, 28, 'geo-observation-statistics-v2',
                   'geo-observation-statistics-v2', %s, %s, %s)
           RETURNING id""",
        (
            fixture["project"],
            fixture["campaign"],
            fixture["market"],
            name,
            Jsonb(snapshot),
            inventory_hash,
            fixture["owner"],
        ),
    ).fetchone()[0]


def _v3_hash(connection: psycopg.Connection[object], value: dict[str, object]) -> str:
    return connection.execute(
        "SELECT geo_source_stratum_v3_hash_from_json(%s)", (Jsonb(value),)
    ).fetchone()[0]


def test_source_v3_functions_preserve_v2_hashes_and_empty_round_trip() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0020_project_exports")
        v2 = _v2_stratum()
        with psycopg.connect(database_url) as admin:
            before = admin.execute(
                """SELECT geo_observation_source_stratum_canonical(
                         %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s),
                          geo_source_stratum_hash_from_json(%s),
                          geo_source_strata_inventory_hash(%s)""",
                (
                    v2["capture_method"],
                    v2["platform"],
                    v2["surface"],
                    v2["surface_kind"],
                    v2["engine"],
                    v2["configured_model"]["state"],
                    v2["configured_model"]["value"],
                    v2["reported_model"]["state"],
                    v2["reported_model"]["value"],
                    v2["locale"],
                    v2["region"],
                    v2["language"],
                    v2["device"],
                    v2["client_kind"],
                    v2["search_enabled"],
                    v2["search_mode"],
                    Jsonb(v2),
                    Jsonb([v2]),
                ),
            ).fetchone()

        command.upgrade(configuration, "0021_observation_source_details")
        with psycopg.connect(database_url) as admin:
            after = admin.execute(
                """SELECT geo_observation_source_stratum_canonical(
                         %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s),
                          geo_source_stratum_hash_from_json(%s),
                          geo_source_strata_inventory_hash(%s)""",
                (
                    v2["capture_method"],
                    v2["platform"],
                    v2["surface"],
                    v2["surface_kind"],
                    v2["engine"],
                    v2["configured_model"]["state"],
                    v2["configured_model"]["value"],
                    v2["reported_model"]["state"],
                    v2["reported_model"]["value"],
                    v2["locale"],
                    v2["region"],
                    v2["language"],
                    v2["device"],
                    v2["client_kind"],
                    v2["search_enabled"],
                    v2["search_mode"],
                    Jsonb(v2),
                    Jsonb([v2]),
                ),
            ).fetchone()
            assert after == before

            known = _stratum()
            canonical = json.dumps(
                known, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
            assert admin.execute(
                "SELECT geo_observation_source_stratum_v3_canonical(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    known["capture_method"],
                    known["platform"],
                    known["platform_detail"],
                    known["surface"],
                    known["surface_kind"],
                    known["surface_detail"],
                    known["engine"],
                    known["configured_model"]["state"],
                    known["configured_model"]["value"],
                    known["reported_model"]["state"],
                    known["reported_model"]["value"],
                    known["locale"],
                    known["region"],
                    known["language"],
                    known["device"],
                    known["client_kind"],
                    known["search_enabled"],
                    known["search_mode"],
                ),
            ).fetchone()[0] == canonical
            assert _v3_hash(admin, known) == hashlib.sha256(canonical.encode()).hexdigest()

        command.downgrade(configuration, "0020_project_exports")
        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                "SELECT to_regprocedure('geo_source_stratum_v3_hash_from_json(jsonb)')"
            ).fetchone()[0] is None
            assert admin.execute(
                "SELECT geo_source_stratum_hash_from_json(%s)", (Jsonb(v2),)
            ).fetchone()[0] == before[1]
        command.upgrade(configuration, "0021_observation_source_details")


def test_source_v3_details_history_guards_rls_and_fail_closed_down() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0011_runtime_health")
        with psycopg.connect(database_url) as admin:
            fixture = _seed_legacy_fixture(admin)
        command.upgrade(configuration, "0020_project_exports")

        v2 = _v2_stratum()
        historical_observation = uuid4()
        historical_metric = uuid4()
        historical_payload_hash = _sha256(f"historical-v2:{historical_observation}")
        with psycopg.connect(database_url) as admin:
            v2_hash = admin.execute(
                "SELECT geo_source_stratum_hash_from_json(%s)", (Jsonb(v2),)
            ).fetchone()[0]
            v2_inventory = admin.execute(
                "SELECT geo_source_strata_inventory_hash(%s)", (Jsonb([v2]),)
            ).fetchone()[0]
            v2_protocol = _insert_protocol(
                admin,
                fixture,
                snapshot=[v2],
                inventory_hash=v2_inventory,
                name="Historical v2 protocol",
            )
            admin.execute("SET LOCAL session_replication_role = replica")
            admin.execute(
                """INSERT INTO monitoring_observations
                     (id, project_id, protocol_id, campaign_id,
                      monitoring_query_id, measurement_window, sample_index,
                      result_status, eligible, ineligible_reasons,
                      url_verification_status, raw_answer, raw_result,
                      raw_citations, configured_model, ui_surface, ui_metadata,
                      observed_at, imported_by, idempotency_key, payload_hash,
                      eligibility_requested, capture_method, platform, surface,
                      surface_kind, engine, configured_model_state,
                      provider_reported_model_state, locale, region, language,
                      observation_device, client_kind, search_enabled, search_mode,
                      prompt_text, follow_up_prompts, raw_evidence_kind,
                      citations_captured, source_contract_version,
                      source_stratum_hash, query_cluster_key, publication_eligible)
                   VALUES
                     (%s, %s, %s, %s, %s, 't84', 1, 'succeeded', true,
                      ARRAY[]::text[], 'unknown', 'Historical v2 answer',
                      '{}'::jsonb, '[]'::jsonb, 'model-v1', 'chatgpt_search',
                      '{}'::jsonb, clock_timestamp(), %s, %s, %s, true,
                      'manual_ui', 'openai', 'chatgpt_search', 'consumer_ui',
                      'chatgpt', 'disclosed', 'not_disclosed', 'en-AU', 'AU',
                      'en', 'desktop', 'browser', true, 'live_web',
                      'Historical prompt', '[]'::jsonb, 'answer', true,
                      'geo-observation-source-v2', %s, 'historical-v2-cluster', true)""",
                (
                    historical_observation,
                    fixture["project"],
                    fixture["protocol"],
                    fixture["campaign"],
                    fixture["query"],
                    fixture["owner"],
                    f"historical-v2:{historical_observation}",
                    historical_payload_hash,
                    v2_hash,
                ),
            )
            _insert_metric_snapshot(
                admin,
                snapshot_id=historical_metric,
                fixture=fixture,
                measurement_window="t84",
                source_hash=v2_hash,
                cluster_key="historical-v2-cluster",
                sampled_count=0,
                membership_hash=None,
            )
            admin.commit()

        command.upgrade(configuration, "0021_observation_source_details")
        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                "SELECT source_strata_hash FROM monitoring_protocols WHERE id = %s",
                (v2_protocol,),
            ).fetchone()[0] == v2_inventory
            assert admin.execute(
                "SELECT source_contract_version, source_stratum_hash FROM monitoring_observations WHERE id = %s",
                (historical_observation,),
            ).fetchone() == ("geo-observation-source-v2", v2_hash)
            assert admin.execute(
                "SELECT source_contract_version, source_stratum_hash FROM monitoring_metric_snapshots WHERE id = %s",
                (historical_metric,),
            ).fetchone() == ("geo-observation-source-v2", v2_hash)

            fake_v3_snapshot = uuid4()
            admin.execute("SET LOCAL session_replication_role = replica")
            _insert_metric_snapshot(
                admin,
                snapshot_id=fake_v3_snapshot,
                fixture=fixture,
                measurement_window="t84",
                source_hash=v2_hash,
                cluster_key="historical-v2-cluster",
                sampled_count=0,
                membership_hash=_sha256(b""),
            )
            admin.execute(
                """UPDATE monitoring_metric_snapshots
                   SET source_contract_version = 'geo-observation-source-v3',
                       source_stratum = %s
                   WHERE id = %s""",
                (Jsonb(_stratum()), fake_v3_snapshot),
            )
            admin.commit()
            with pytest.raises(
                psycopg.errors.CheckViolation,
                match="metric observation member differs from its exact snapshot lineage",
            ):
                with admin.transaction():
                    admin.execute(
                        """INSERT INTO monitoring_metric_snapshot_observations
                             (snapshot_id, project_id, campaign_id, protocol_id,
                              observation_id, payload_hash, ordinal)
                           VALUES (%s, %s, %s, %s, %s, %s, 1)""",
                        (
                            fake_v3_snapshot,
                            fixture["project"],
                            fixture["campaign"],
                            fixture["protocol"],
                            historical_observation,
                            historical_payload_hash,
                        ),
                    )

            left = _stratum(
                platform="other",
                platform_detail="provider-a",
                surface="other",
                surface_detail="surface-a",
            )
            right = _stratum(
                platform="other",
                platform_detail="provider-b",
                surface="other",
                surface_detail="surface-b",
            )
            left_hash = _v3_hash(admin, left)
            right_hash = _v3_hash(admin, right)
            assert left_hash != right_hash
            assert admin.execute(
                "SELECT geo_source_stratum_v3_json_valid(%s), geo_source_stratum_v3_json_valid(%s)",
                (Jsonb(left), Jsonb(right)),
            ).fetchone() == (True, True)

            missing_detail = {**left, "platform_detail": None}
            known_with_detail = {**_stratum(), "surface_detail": "forged"}
            assert admin.execute(
                "SELECT geo_source_stratum_v3_json_valid(%s), geo_source_stratum_v3_json_valid(%s)",
                (Jsonb(missing_detail), Jsonb(known_with_detail)),
            ).fetchone() == (False, False)

            left_inventory = admin.execute(
                "SELECT geo_source_strata_v3_inventory_hash(%s)", (Jsonb([left]),)
            ).fetchone()[0]
            _insert_protocol(
                admin,
                fixture,
                snapshot=[left],
                inventory_hash=left_inventory,
                name="Valid v3 protocol",
            )
            admin.commit()

            with pytest.raises(psycopg.errors.CheckViolation):
                with admin.transaction():
                    _insert_protocol(
                        admin,
                        fixture,
                        snapshot=[right],
                        inventory_hash=v2_inventory,
                        name="Forged old hash",
                    )
            with pytest.raises(psycopg.errors.CheckViolation):
                with admin.transaction():
                    _insert_metric_snapshot(
                        admin,
                        snapshot_id=uuid4(),
                        fixture=fixture,
                        measurement_window="t84",
                        source_hash=v2_hash,
                        cluster_key="historical-v2-cluster",
                        sampled_count=0,
                        membership_hash=_sha256(b""),
                    )

        with psycopg.connect(database_url) as scoped:
            with scoped.transaction():
                scoped.execute("SET LOCAL ROLE geo_app")
                set_project_scope(scoped, fixture["project"])
                assert scoped.execute(
                    "SELECT count(*) FROM monitoring_protocols WHERE id = %s",
                    (v2_protocol,),
                ).fetchone()[0] == 1
            with scoped.transaction():
                scoped.execute("SET LOCAL ROLE geo_app")
                set_project_scope(scoped, uuid4())
                assert scoped.execute(
                    "SELECT count(*) FROM monitoring_protocols WHERE id = %s",
                    (v2_protocol,),
                ).fetchone()[0] == 0

        with pytest.raises(DBAPIError, match="observation source v3 data exists"):
            command.downgrade(configuration, "0020_project_exports")
