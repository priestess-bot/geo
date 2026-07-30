from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from geo_core.browser_capture.admin import BrowserCaptureAdminService
from geo_core.browser_capture.domain import BrowserCaptureError
from geo_core.connectors import (
    ConnectorKind,
    ConnectorPersistenceError,
    ConnectorSyncCommit,
    ConnectorSyncMode,
    ConnectorSyncPlan,
    FreshnessStatus,
    PostgresConnectorJobRepository,
    PostgresConnectorRepository,
    RawArtifactDescriptor,
    SchemaCompatibility,
    canonical_hash,
)
from geo_core.connectors.admin import ConnectorAdminError, ConnectorAdminService
from geo_core.connectors.connection_test import (
    CONNECTOR_CONNECTION_TEST_JOB_KIND,
    ConnectorConnectionTestOperation,
    PostgresConnectorConnectionTestRepository,
)
from geo_core.connectors.external_data import ExternalDataService
from geo_core.jobs.postgres import PostgresDurableJobStore
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_connector_commit_is_atomic_replayable_and_rejects_stale_checkpoint() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_connector_{suffix}"
    target_url = _database_url(ADMIN_URL, database_name)
    app_login, password = f"geo_connector_{suffix}", uuid4().hex
    database_created = role_created = False
    migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    migration.attributes["geo_database_url_override"] = target_url
    now = datetime(2026, 7, 28, 3, 0, tzinfo=UTC)
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        database_created = True
        command.upgrade(migration, "head")
        with psycopg.connect(target_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(password)
                )
            )
            role_created = True
            seeded = seed_project(admin, suffix=f"connector-{suffix}")
            seeded["campaign"] = uuid4()
            admin.execute(
                """INSERT INTO geo_campaigns(
                       id, project_id, market_profile_id, primary_product_entity_id,
                       name, created_by
                   ) VALUES (%s, %s, %s, %s, 'Connector evidence', %s)""",
                (
                    seeded["campaign"],
                    seeded["project"],
                    seeded["market"],
                    seeded["entity"],
                    seeded["owner"],
                ),
            )
            definition_id, connection_id, scope_id = _seed_connector(
                admin, seeded=seeded, now=now
            )

        app_url = login_url(target_url, user=app_login, password=password)

        def connect():
            return psycopg.connect(app_url, row_factory=dict_row)

        repository = PostgresConnectorRepository(connect=connect)
        jobs = PostgresConnectorJobRepository(connect=connect)
        plan = _plan(
            project_id=seeded["project"],
            actor_id=seeded["owner"],
            definition_id=definition_id,
            connection_id=connection_id,
            scope_id=scope_id,
            now=now,
        )
        run_id = uuid4()
        created = repository.create_sync_run(plan, run_id=run_id)
        assert created.status == "planned" and created.replayed is False
        assert repository.create_sync_run(plan, run_id=uuid4()).id == run_id
        enqueued = jobs.enqueue(plan=plan, run_id=run_id, expected_run_version=1)
        replayed_job = jobs.enqueue(plan=plan, run_id=run_id, expected_run_version=1)
        assert replayed_job.job_id == enqueued.job_id and replayed_job.replayed is True
        running = repository.mark_running(
            project_id=seeded["project"],
            run_id=run_id,
            expected_version=2,
            started_at=now + timedelta(minutes=1),
        )
        commit = _commit(plan=plan, run_id=run_id, run_version=running.version, now=now)
        result = repository.commit_success(commit, finished_at=now + timedelta(minutes=2))
        replay = repository.commit_success(commit, finished_at=now + timedelta(minutes=3))
        assert replay == result
        assert result.checkpoint_version == 1

        external_data = ExternalDataService(connect=connect, clock=lambda: now)
        draft = external_data.create_connector_report(
            project_id=seeded["project"],
            campaign_id=seeded["campaign"],
            projection_batch_id=result.projection_batch_id,
            actor_id=seeded["owner"],
            title="GSC search performance",
            summary="Approved search performance projection.",
        )
        submitted = external_data.submit(
            project_id=seeded["project"], report_id=draft["id"]
        )
        approved_report = external_data.decide(
            project_id=seeded["project"],
            report_id=draft["id"],
            snapshot_hash=draft["snapshot"]["snapshot_hash"],
            decision="approved",
            actor_id=seeded["reviewer"],
            reason="Projection and freshness reviewed",
            review_evidence={"checklist": "external-data-rubric-v1"},
            idempotency_key=f"approve:{draft['id']}",
        )
        replayed_approval = external_data.decide(
            project_id=seeded["project"],
            report_id=draft["id"],
            snapshot_hash=draft["snapshot"]["snapshot_hash"],
            decision="approved",
            actor_id=seeded["reviewer"],
            reason="Projection and freshness reviewed",
            review_evidence={"checklist": "external-data-rubric-v1"},
            idempotency_key=f"approve:{draft['id']}",
        )
        assert submitted["status"] == "in_review"
        assert approved_report["status"] == "approved"
        assert replayed_approval["id"] == approved_report["id"]
        latest = external_data.latest(
            project_id=seeded["project"], campaign_id=seeded["campaign"]
        )
        assert len(latest) == 1
        assert latest[0]["source_kind"] == "gsc_connector"
        assert latest[0]["customer_payload"]["rows"][0]["clicks"] == 3.0
        invalidated = external_data.invalidate(
            project_id=seeded["project"],
            report_id=draft["id"],
            snapshot_hash=draft["snapshot"]["snapshot_hash"],
            decision="stale",
            actor_id=seeded["reviewer"],
            reason="Source freshness window expired",
            evidence={"freshness_status": "stale"},
            idempotency_key=f"stale:{draft['id']}",
        )
        assert invalidated["status"] == "stale"
        assert external_data.latest(
            project_id=seeded["project"], campaign_id=seeded["campaign"]
        ) == ()

        # Change the window so this is a distinct initial Run while still
        # claiming the now-stale empty checkpoint.
        stale_plan = _plan(
            project_id=seeded["project"],
            actor_id=seeded["owner"],
            definition_id=definition_id,
            connection_id=connection_id,
            scope_id=scope_id,
            now=now + timedelta(days=1),
        )
        stale_run_id = uuid4()
        repository.create_sync_run(stale_plan, run_id=stale_run_id)
        jobs.enqueue(plan=stale_plan, run_id=stale_run_id, expected_run_version=1)
        stale_running = repository.mark_running(
            project_id=seeded["project"],
            run_id=stale_run_id,
            expected_version=2,
            started_at=now + timedelta(days=1, minutes=1),
        )
        with pytest.raises(ConnectorPersistenceError, match="empty checkpoint"):
            repository.commit_success(
                _commit(
                    plan=stale_plan,
                    run_id=stale_run_id,
                    run_version=stale_running.version,
                    now=now + timedelta(days=1),
                ),
                finished_at=now + timedelta(days=1, minutes=2),
            )
        with connect() as app:
            from geo_core.project_scope import set_project_scope

            set_project_scope(app, seeded["project"])
            counts = app.execute(
                """SELECT
                    (SELECT count(*) FROM connector_raw_artifacts) AS raw_count,
                    (SELECT count(*) FROM connector_projection_batches) AS batch_count,
                    (SELECT count(*) FROM connector_checkpoints) AS checkpoint_count,
                    (SELECT count(*) FROM connector_job_specs) AS spec_count,
                    (SELECT count(*) FROM broker_outbox
                      WHERE topic = 'connector.sync') AS outbox_count"""
            ).fetchone()
        assert counts == {
            "raw_count": 1,
            "batch_count": 1,
            "checkpoint_count": 1,
            "spec_count": 2,
            "outbox_count": 2,
        }

        # Exercise the operator path without placing credential values in the
        # Connector API: definition -> independent approval -> reference ->
        # scope -> durable sync admission.
        ga4_secret_id = _seed_pending_secret(
            target_url,
            project_id=seeded["project"],
            actor_id=seeded["owner"],
            purpose="connector.ga4",
            now=now,
        )
        admin_service = ConnectorAdminService(connect=connect, clock=lambda: now)
        definition = admin_service.install_definition(
            project_id=seeded["project"],
            actor_id=seeded["owner"],
            kind=ConnectorKind.GOOGLE_ANALYTICS_4,
        )
        approved = admin_service.approve_definition(
            project_id=seeded["project"],
            definition_id=definition["id"],
            reviewer_id=seeded["reviewer"],
        )
        assert approved["status"] == "approved"
        ga4_connection = admin_service.create_connection(
            project_id=seeded["project"],
            actor_id=seeded["owner"],
            definition_id=definition["id"],
            name="GA4 aggregate reconciliation",
            secret_reference_id=ga4_secret_id,
            secret_purpose="connector.ga4",
            secret_version=1,
        )
        ga4_scope = admin_service.create_scope(
            project_id=seeded["project"],
            actor_id=seeded["owner"],
            connection_id=ga4_connection["id"],
            source_locator="properties/123456789",
            streams=("reports",),
            locale="en-AU",
            report_spec={"dimensions": ["date"], "metrics": ["sessions"]},
            date_policy={"timezone": "Australia/Sydney"},
        )
        disabled = admin_service.set_connection_status(
            project_id=seeded["project"], connection_id=ga4_connection["id"],
            status="disabled", expected_version=1,
        )
        assert disabled["status"] == "disabled" and disabled["version"] == 2
        with pytest.raises(ConnectorAdminError, match="not active"):
            admin_service.test_connection(
                project_id=seeded["project"], actor_id=seeded["owner"],
                connection_id=ga4_connection["id"], expected_version=2,
                idempotency_key="disabled-ga4-connection-test",
            )
        with pytest.raises(ConnectorAdminError, match="active exact Secret"):
            admin_service.start_sync(
                project_id=seeded["project"], actor_id=seeded["owner"],
                scope_id=ga4_scope["id"], mode=ConnectorSyncMode.INITIAL,
                window_start=now - timedelta(days=7), window_end=now,
            )
        enabled = admin_service.set_connection_status(
            project_id=seeded["project"], connection_id=ga4_connection["id"],
            status="active", expected_version=2,
        )
        assert enabled["status"] == "active" and enabled["version"] == 3
        with pytest.raises(ConnectorAdminError, match="active exact Secret"):
            admin_service.start_sync(
                project_id=seeded["project"], actor_id=seeded["owner"],
                scope_id=ga4_scope["id"], mode=ConnectorSyncMode.INITIAL,
                window_start=now - timedelta(days=7), window_end=now,
            )
        _activate_secret(
            target_url,
            project_id=seeded["project"],
            reference_id=ga4_secret_id,
            purpose="connector.ga4",
            reviewer_id=seeded["reviewer"],
            now=now,
        )
        rotated = admin_service.rotate_connection_secret(
            project_id=seeded["project"], connection_id=ga4_connection["id"],
            secret_version=1, expected_version=3,
        )
        assert rotated["secret_version"] == 1 and rotated["version"] == 4
        connection_test = admin_service.test_connection(
            project_id=seeded["project"], actor_id=seeded["owner"],
            connection_id=ga4_connection["id"], expected_version=4,
            idempotency_key="ga4-connection-test-success",
        )
        replayed_test = admin_service.test_connection(
            project_id=seeded["project"], actor_id=seeded["owner"],
            connection_id=ga4_connection["id"], expected_version=4,
            idempotency_key="ga4-connection-test-success",
        )
        assert replayed_test["test_id"] == connection_test["test_id"]
        assert replayed_test["replayed"] is True

        def admin_connect():
            return psycopg.connect(target_url, row_factory=dict_row)

        test_store = PostgresDurableJobStore(admin_connect)
        test_claim = test_store.claim(
            job_id=connection_test["job_id"], project_id=seeded["project"],
            expected_kind=CONNECTOR_CONNECTION_TEST_JOB_KIND,
            worker_id="connector-test-worker", lease_for=timedelta(minutes=1),
        )
        assert test_claim.lease is not None

        class Credentials:
            def resolve(self, **_values):
                return {"credentials": "resolved-only-inside-worker"}

        class CheckedSource:
            def check_connection(self):
                return None

        test_operation = ConnectorConnectionTestOperation(
            store=test_store,
            repository=PostgresConnectorConnectionTestRepository(connect=admin_connect),
            credentials=Credentials(),
            sources=lambda **_values: CheckedSource(),
            lease_for=timedelta(minutes=1), clock=lambda: now,
        )
        assert test_operation.execute(test_claim.lease)["status"] == "succeeded"
        inventory_after_test = admin_service.inventory(project_id=seeded["project"])
        projected_test = next(
            item for item in inventory_after_test["connection_tests"]
            if item["id"] == connection_test["test_id"]
        )
        assert projected_test["status"] == "succeeded"
        assert projected_test["result_hash"] is not None
        failed_test = admin_service.test_connection(
            project_id=seeded["project"], actor_id=seeded["owner"],
            connection_id=ga4_connection["id"], expected_version=4,
            idempotency_key="ga4-connection-test-failure",
        )
        failed_test_claim = test_store.claim(
            job_id=failed_test["job_id"], project_id=seeded["project"],
            expected_kind=CONNECTOR_CONNECTION_TEST_JOB_KIND,
            worker_id="connector-test-worker", lease_for=timedelta(minutes=1),
        )
        assert failed_test_claim.lease is not None
        assert test_store.fail(
            failed_test_claim.lease,
            error_code="connector_connection_test_failed",
            details={"classification": "ConnectorRuntimeError"}, retry_delay=None,
        ) == "failed"
        failed_projection = next(
            item for item in admin_service.inventory(
                project_id=seeded["project"]
            )["connection_tests"]
            if item["id"] == failed_test["test_id"]
        )
        assert failed_projection["status"] == "failed"
        assert failed_projection["error_class"] == "ConnectorRuntimeError"
        accepted = admin_service.start_sync(
            project_id=seeded["project"],
            actor_id=seeded["owner"],
            scope_id=ga4_scope["id"],
            mode=ConnectorSyncMode.INITIAL,
            window_start=now - timedelta(days=7),
            window_end=now,
        )
        assert accepted["status"] == "queued" and accepted["replayed"] is False
        inventory = admin_service.inventory(project_id=seeded["project"])
        accepted_run = next(
            item for item in inventory["runs"] if item["id"] == accepted["run_id"]
        )
        assert accepted_run["version"] == 2
        cancelled = admin_service.cancel_sync(
            project_id=seeded["project"], run_id=accepted["run_id"], expected_version=2,
        )
        assert cancelled["status"] == "cancelled"
        inventory = admin_service.inventory(project_id=seeded["project"])
        assert next(
            item for item in inventory["runs"] if item["id"] == accepted["run_id"]
        )["status"] == "cancelled"

        browser_secret_id = _seed_pending_secret(
            target_url,
            project_id=seeded["project"],
            actor_id=seeded["owner"],
            purpose="browser_egress.au_proxy",
            now=now,
        )
        browser = BrowserCaptureAdminService(connect=connect, clock=lambda: now)
        release = browser.create_surface_release(
            project_id=seeded["project"], actor_id=seeded["owner"],
            platform="google", surface="google_ai_overviews", release_version="fixture-v1",
            entry_url_template="https://www.google.com/",
            allowed_hosts=("www.google.com",),
            selectors={
                "query_input": "textarea[name='q']",
                "page_complete": "#search",
                "surface_marker": "[data-aio]",
                "answer": "[data-answer]",
                "citations": "[data-citation]",
                "page_location": "[data-location]",
            },
            block_detectors={"captcha": "form[action*='sorry']"},
            parser_release="google-aio-parser-v1", browser_release="playwright:1.60.0",
            authorization_track="A", authorization_status="approved",
            authorization_reference="legal-review:2026-07-28",
            authorization_valid_until=now + timedelta(days=30), terms_version="2026-07",
        )
        assert browser.approve_surface_release(
            project_id=seeded["project"], release_id=release["id"],
            reviewer_id=seeded["reviewer"],
        )["status"] == "approved"
        endpoint = browser.create_egress_endpoint(
            project_id=seeded["project"], actor_id=seeded["owner"], name="AU proxy",
            protocol="https", endpoint_host="proxy.example.test", endpoint_port=443,
            secret_reference_id=browser_secret_id,
            secret_purpose="browser_egress.au_proxy", secret_version=1,
            expected_region="NSW", network_type="residential",
            sticky_mode="provider_lease", egress_policy_version="au-egress-v1",
            egress_cohort_key="au-residential-nsw-v1",
        )
        with pytest.raises(BrowserCaptureError, match="active exact Secret"):
            browser.approve_egress_endpoint(
                project_id=seeded["project"], endpoint_id=endpoint["id"],
                reviewer_id=seeded["reviewer"],
            )
        _activate_secret(
            target_url, project_id=seeded["project"], reference_id=browser_secret_id,
            purpose="browser_egress.au_proxy", reviewer_id=seeded["reviewer"], now=now,
        )
        assert browser.approve_egress_endpoint(
            project_id=seeded["project"], endpoint_id=endpoint["id"],
            reviewer_id=seeded["reviewer"],
        )["status"] == "approved"
        profile = browser.create_profile(
            project_id=seeded["project"], actor_id=seeded["owner"], version="au-desktop-v1",
            browser_release="playwright:1.60.0/chromium", device_class="desktop",
            viewport={"width": 1440, "height": 1000}, timezone="Australia/Sydney",
            geolocation={"latitude": -33.8688, "longitude": 151.2093, "accuracy": 25},
            location_permission=True, safe_search="moderate", account_cohort="clean_anonymous",
        )
        assert browser.approve_profile(
            project_id=seeded["project"], profile_id=profile["id"],
            reviewer_id=seeded["reviewer"],
        )["status"] == "approved"
        browser_inventory = browser.inventory(project_id=seeded["project"])
        assert len(browser_inventory["surface_releases"]) == 1
        assert len(browser_inventory["egress_endpoints"]) == 1
        browser_option = browser.register_sampling_runtime_option(
            project_id=seeded["project"], surface_release_id=release["id"],
            egress_endpoint_id=endpoint["id"], profile_version_id=profile["id"],
        )
        assert browser_option["capture_method"] == "automated_ui"
        assert browser_option["location_control"] == "country"
        assert browser_option["adapter_release"].startswith("browser:")

        # A dispatcher-owned terminal failure must not strand the Connector
        # aggregate in queued/running or omit its actionable error projection.
        failed_plan = _plan(
            project_id=seeded["project"], actor_id=seeded["owner"],
            definition_id=definition_id, connection_id=connection_id, scope_id=scope_id,
            now=now + timedelta(days=2),
        )
        failed_run_id = uuid4()
        repository.create_sync_run(failed_plan, run_id=failed_run_id)
        failed_job = jobs.enqueue(
            plan=failed_plan, run_id=failed_run_id, expected_run_version=1
        )
        admin_store = PostgresDurableJobStore(
            lambda: psycopg.connect(target_url, row_factory=dict_row)
        )
        claim = admin_store.claim(
            job_id=failed_job.job_id, project_id=seeded["project"],
            expected_kind="connector.sync", worker_id="connector-test",
            lease_for=timedelta(minutes=1),
        )
        assert claim.lease is not None
        assert admin_store.fail(
            claim.lease, error_code="connector_sync_failed",
            details={"classification": "CredentialRevoked"}, retry_delay=None,
        ) == "failed"
        with connect() as app:
            from geo_core.project_scope import set_project_scope

            set_project_scope(app, seeded["project"])
            terminal = app.execute(
                """SELECT status, error_class, finished_at
                     FROM connector_sync_runs WHERE project_id = %s AND id = %s""",
                (seeded["project"], failed_run_id),
            ).fetchone()
            failure = app.execute(
                """SELECT error_class, retryable, operator_action
                     FROM connector_errors WHERE project_id = %s AND sync_run_id = %s""",
                (seeded["project"], failed_run_id),
            ).fetchone()
        assert terminal["status"] == "failed"
        assert terminal["finished_at"] is not None
        assert failure["error_class"] == "revoked"
        assert failure["retryable"] is False
        assert "authorization" in failure["operator_action"].lower()
    finally:
        if database_created:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
                if role_created:
                    server.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login))
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
