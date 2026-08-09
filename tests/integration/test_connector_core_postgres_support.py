from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from geo_core.connectors import (
    ConnectorSyncCommit,
    ConnectorSyncMode,
    ConnectorSyncPlan,
    FreshnessStatus,
    RawArtifactDescriptor,
    SchemaCompatibility,
    canonical_hash,
)


def _seed_connector(connection, *, seeded, now):
    definition_id, secret_id, connection_id, scope_id = (uuid4() for _ in range(4))
    connection.execute(
        """INSERT INTO secret_master_key_versions(
               master_key_version, algorithm, status, canary_nonce, canary_ciphertext,
               created_at, activated_at
           ) VALUES (1, 'AES-256-GCM', 'encrypt_decrypt', %s, %s, %s, %s)""",
        (b"n" * 12, b"c" * 17, now, now),
    )
    connection.execute(
        """INSERT INTO secret_references(
               id, project_id, purpose, aggregate_version, current_version,
               created_by, created_at, updated_at
           ) VALUES (%s, %s, 'connector.gsc', 1, NULL, %s, %s, %s)""",
        (secret_id, seeded["project"], seeded["owner"], now, now),
    )
    connection.execute(
        """INSERT INTO secret_versions(
               reference_id, project_id, purpose, version, ciphertext, data_nonce,
               wrapped_data_key, wrap_nonce, master_key_version, algorithm,
               created_at, status, created_by
           ) VALUES (%s, %s, 'connector.gsc', 1, %s, %s, %s, %s, 1,
                     'AES-256-GCM', %s, 'pending', %s)""",
        (
            secret_id,
            seeded["project"],
            b"x" * 17,
            b"d" * 12,
            b"w" * 48,
            b"q" * 12,
            now,
            seeded["owner"],
        ),
    )
    schema = {"type": "object"}
    connection.execute(
        """INSERT INTO connector_definitions(
               id, project_id, kind, adapter_release, runtime_release, capability,
               config_schema, config_schema_hash, release_hash, status,
               created_by, created_at, approved_by, approved_at
           ) VALUES (%s, %s, 'google_search_console',
                     'source-google-search-console:2.1.5', 'pyairbyte:0.53.2',
                     %s, %s, %s, %s, 'approved', %s, %s, %s, %s)""",
        (
            definition_id,
            seeded["project"],
            Jsonb({"incremental": True}),
            Jsonb(schema),
            canonical_hash(schema),
            "a" * 64,
            seeded["owner"],
            now,
            seeded["reviewer"],
            now,
        ),
    )
    connection.execute(
        """INSERT INTO connector_connections(
               id, project_id, definition_id, name, secret_reference_id,
               secret_purpose, secret_version, auth_summary, status,
               created_by, created_at, updated_at
           ) VALUES (%s, %s, %s, 'GSC integration', %s, 'connector.gsc', 1,
                     %s, 'active', %s, %s, %s)""",
        (
            connection_id,
            seeded["project"],
            definition_id,
            secret_id,
            Jsonb({"credential_type": "service_account"}),
            seeded["owner"],
            now,
            now,
        ),
    )
    scope = {"locator": "sc-domain:example.test", "streams": ["search_analytics_by_date"]}
    connection.execute(
        """INSERT INTO connector_scopes(
               id, project_id, connection_id, source_locator, streams, report_spec,
               locale, date_policy, scope_hash, status, created_by, created_at
           ) VALUES (%s, %s, %s, 'sc-domain:example.test', %s, %s,
                     'en-AU', %s, %s, 'active', %s, %s)""",
        (
            scope_id,
            seeded["project"],
            connection_id,
            Jsonb(["search_analytics_by_date"]),
            Jsonb({}),
            Jsonb({"lag_days": 2}),
            canonical_hash(scope),
            seeded["owner"],
            now,
        ),
    )
    return definition_id, connection_id, scope_id


def _seed_pending_secret(
    database_url: str,
    *,
    project_id,
    actor_id,
    purpose: str,
    now: datetime,
):
    reference_id = uuid4()
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """INSERT INTO secret_references(
                   id, project_id, purpose, aggregate_version, current_version,
                   created_by, created_at, updated_at
               ) VALUES (%s, %s, %s, 1, NULL, %s, %s, %s)""",
            (reference_id, project_id, purpose, actor_id, now, now),
        )
        connection.execute(
            """INSERT INTO secret_versions(
                   reference_id, project_id, purpose, version, ciphertext, data_nonce,
                   wrapped_data_key, wrap_nonce, master_key_version, algorithm,
                   created_at, status, created_by
               ) VALUES (%s, %s, %s, 1, %s, %s, %s, %s, 1,
                         'AES-256-GCM', %s, 'pending', %s)""",
            (
                reference_id,
                project_id,
                purpose,
                b"x" * 17,
                b"d" * 12,
                b"w" * 48,
                b"q" * 12,
                now,
                actor_id,
            ),
        )
    return reference_id


def _activate_secret(
    database_url: str,
    *,
    project_id,
    reference_id,
    purpose: str,
    reviewer_id,
    now: datetime,
):
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """UPDATE secret_versions
                  SET verified_by = %s, verified_at = %s
                WHERE reference_id = %s AND project_id = %s AND purpose = %s
                  AND version = 1 AND status = 'pending'""",
            (reviewer_id, now, reference_id, project_id, purpose),
        )
        connection.execute(
            """UPDATE secret_versions
                  SET status = 'active', activated_by = %s, activated_at = %s
                WHERE reference_id = %s AND project_id = %s AND purpose = %s
                  AND version = 1 AND status = 'pending' AND verified_at IS NOT NULL""",
            (reviewer_id, now, reference_id, project_id, purpose),
        )
        connection.execute(
            """UPDATE secret_references
                  SET current_version = 1, aggregate_version = aggregate_version + 1,
                      updated_at = %s
                WHERE id = %s AND project_id = %s AND purpose = %s""",
            (now, reference_id, project_id, purpose),
        )


def _plan(*, project_id, actor_id, definition_id, connection_id, scope_id, now):
    return ConnectorSyncPlan(
        project_id=project_id,
        definition_id=definition_id,
        connection_id=connection_id,
        scope_id=scope_id,
        mode=ConnectorSyncMode.INITIAL,
        adapter_release="source-google-search-console:2.1.5",
        input_checkpoint_id=None,
        input_checkpoint_hash="0" * 64,
        window_start=now - timedelta(days=2),
        window_end=now - timedelta(days=1),
        requested_by=actor_id,
        requested_at=now,
    )


def _commit(*, plan, run_id, run_version, now):
    schema = {"fields": [{"name": "date", "type": "date"}]}
    return ConnectorSyncCommit(
        project_id=plan.project_id,
        run_id=run_id,
        expected_run_version=run_version,
        expected_checkpoint_hash=plan.input_checkpoint_hash,
        artifact=RawArtifactDescriptor(
            manifest_uri=f"s3://connector-test/{run_id}/manifest.json",
            manifest_hash=canonical_hash({"run": str(run_id)}),
            content_hash="b" * 64,
            schema_fingerprint="c" * 64,
            record_count=1,
            byte_size=100,
            classification="internal_raw",
            retention_until=now + timedelta(days=90),
            encryption_key_reference="connector-key:v1",
            producer_commit="d" * 40,
        ),
        schema_document=schema,
        schema_hash=canonical_hash(schema),
        compatibility=SchemaCompatibility.INITIAL,
        schema_diff={},
        projection_kind="gsc.search_analytics.v1",
        projection_row_count=1,
        projection_dataset_hash="e" * 64,
        projection_lineage={"business_key": ["date", "query", "page"]},
        projection_records=(
            {
                "_geo_stream": "search_analytics_by_date",
                "date": now.date().isoformat(),
                "clicks": 3,
                "impressions": 20,
                "ctr": 0.15,
                "position": 2.4,
            },
        ),
        next_cursor_state={"date": now.date().isoformat()},
        next_watermark=now,
        expected_watermark=now,
        freshness_status=FreshnessStatus.FRESH,
        freshness_reason="fixture watermark is current",
    )


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
