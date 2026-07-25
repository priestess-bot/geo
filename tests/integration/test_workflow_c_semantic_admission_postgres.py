from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from geo_core.project_scope import set_project_scope
from geo_core.workflow_c_analysis_admission import MetricProtocolStatus, new_metric_protocol
from geo_core.workflow_c_analysis_protocols import (
    PostgresWorkflowCMetricProtocolRepository,
)
from geo_core.workflow_c_semantic_admission import (
    PostgresWorkflowCSemanticAdmissionRepository,
)
from tests.integration.placement_worker_support import login_url, seed_project
from tests.workflow_c_analysis_test_support import metric_protocol_definition_fixture


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_completed_manual_run_atomically_freezes_manifest_and_enqueues_v2_job() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_semantic_admission_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_semantic_admission_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        alembic_command.upgrade(migration, "head")
        now = datetime(2026, 7, 24, 10, 0, tzinfo=UTC)
        with psycopg.connect(database_url, row_factory=dict_row) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            created_role = True
            project = seed_project(admin, suffix=f"semantic-admission-{suffix}")
            run_id = _seed_completed_manual_run(
                admin, project_id=project["project"], now=now
            )

        app_url = login_url(database_url, user=app_login, password=app_password)

        def connect():
            return psycopg.connect(app_url, row_factory=dict_row)

        protocol_repository = PostgresWorkflowCMetricProtocolRepository(
            connect=connect, clock=lambda: now
        )
        protocol = new_metric_protocol(
            project_id=project["project"],
            definition=metric_protocol_definition_fixture(),
            actor_id="metric-maker",
            idempotency_key="semantic-protocol-v1",
            occurred_at=now,
        )
        created = protocol_repository.create(
            protocol, idempotency_key="semantic-protocol-v1"
        )
        submitted = protocol_repository.transition(
            project_id=project["project"],
            protocol_id=created.id,
            expected_aggregate_version=created.aggregate_version,
            target_status=MetricProtocolStatus.IN_REVIEW,
            actor_id="metric-maker",
            idempotency_key="semantic-protocol-v1:submit",
            occurred_at=now,
        )
        approved = protocol_repository.transition(
            project_id=project["project"],
            protocol_id=created.id,
            expected_aggregate_version=submitted.aggregate_version,
            target_status=MetricProtocolStatus.APPROVED,
            actor_id="metric-checker",
            reason="fixed semantic contract checked",
            idempotency_key="semantic-protocol-v1:approve",
            occurred_at=now,
        )

        admission = PostgresWorkflowCSemanticAdmissionRepository(
            connect=connect, clock=lambda: now + timedelta(minutes=1)
        )
        result = admission.enqueue(
            project_id=project["project"],
            sampling_run_id=run_id,
            metric_protocol_id=approved.id,
            actor_id="analysis-operator",
            idempotency_key="semantic-run-one",
        )
        replayed = admission.enqueue(
            project_id=project["project"],
            sampling_run_id=run_id,
            metric_protocol_id=approved.id,
            actor_id="analysis-operator",
            idempotency_key="semantic-run-one",
        )

        assert result.manifest == replayed.manifest
        assert result.job.job_id == replayed.job.job_id
        assert result.job.replayed is False
        assert replayed.job.replayed is True
        assert result.manifest.observation_count == 3
        assert len(result.manifest.items) == 3
        _assert_atomic_state(
            database_url,
            app_url,
            project_id=project["project"],
            manifest_id=result.manifest.id,
            job_id=result.job.job_id,
        )
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        if created_role:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))


def _seed_completed_manual_run(
    connection: psycopg.Connection, *, project_id: UUID, now: datetime
) -> UUID:
    policy_id, suite_id, run_id = uuid4(), uuid4(), uuid4()
    policy_hash = _hash("manual-policy")
    suite_hash = _hash("manual-suite")
    source_hash = _hash("manual-source-stratum")
    source = {
        "platform": "consumer-search",
        "surface": "manual-answer",
        "configured_model": "not-disclosed",
        "reported_model": "not-disclosed",
        "capture_method": "manual_ui",
        "adapter_release": "manual-import-v1",
        "locale": "en-AU",
        "region": "AU",
        "language": "en",
        "search_mode": "consumer-ui",
        "account_cohort": "approved-test-account",
        "egress_policy_category": "manual-verified-au",
        "location_control": "country",
        "location_evidence_hash": _hash("manual-location"),
        "requested_country": "AU",
        "requested_region": None,
        "requested_locale": "en-AU",
        "requested_language": "en",
        "effective_country": "AU",
        "effective_region": None,
        "effective_locale": None,
        "effective_language": None,
    }
    suite_payload = {
        "schema_version": 1,
        "suite": {"source_stratum": source},
        "frozen_by": "fixture",
        "frozen_at": now.isoformat(),
    }
    connection.execute("SET LOCAL session_replication_role = replica")
    connection.execute(
        """INSERT INTO workflow_c_sampling_suites(
               id, project_id, suite_hash, admission_policy_id,
               admission_policy_hash, source_stratum_hash, capture_method,
               planned_task_count, minimum_valid_repeats, payload, frozen_at
           ) VALUES (%s, %s, %s, %s, %s, %s, 'manual_ui', 3, 3, %s::jsonb, %s)""",
        (
            suite_id,
            project_id,
            suite_hash,
            policy_id,
            policy_hash,
            source_hash,
            Jsonb(suite_payload),
            now,
        ),
    )
    connection.execute(
        """INSERT INTO workflow_c_sampling_runs(
               id, project_id, suite_id, suite_hash, admission_policy_id,
               admission_policy_hash, admission_grant_hash, purpose, status,
               reserved_task_count, admitted_not_before, authorization_valid_until,
               version, payload, created_at, consumed_task_count
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'geo_measurement', 'completed',
                     3, %s, %s, 7, '{}'::jsonb, %s, 3)""",
        (
            run_id,
            project_id,
            suite_id,
            suite_hash,
            policy_id,
            policy_hash,
            _hash("manual-grant"),
            now - timedelta(minutes=5),
            now + timedelta(days=1),
            now,
        ),
    )
    for repetition in range(1, 4):
        _seed_manual_member(
            connection,
            project_id=project_id,
            suite_id=suite_id,
            run_id=run_id,
            source_hash=source_hash,
            repetition=repetition,
            now=now,
        )
    connection.execute("SET LOCAL session_replication_role = origin")
    return run_id


def _seed_manual_member(
    connection: psycopg.Connection,
    *,
    project_id: UUID,
    suite_id: UUID,
    run_id: UUID,
    source_hash: str,
    repetition: int,
    now: datetime,
) -> None:
    task_id, attempt_id, source_job_id = uuid4(), uuid4(), uuid4()
    observation_id, import_id = uuid4(), uuid4()
    artifact_id, capture_session_id, key_ref = uuid4(), uuid4(), uuid4()
    task_key = _hash(f"manual-task:{repetition}")
    manifest_hash = _hash(f"manual-manifest:{repetition}")
    content_hash = _hash(f"manual-content:{repetition}")
    governance_hash = _hash("manual-governance")
    location_hash = _hash(f"manual-actual-location:{repetition}")
    actual_location = {
        "location_control": "country",
        "location_evidence_hash": _hash("manual-location"),
        "requested_country": "AU",
        "requested_region": None,
        "requested_locale": "en-AU",
        "requested_language": "en",
        "effective_country": "AU",
        "effective_region": None,
        "effective_locale": None,
        "effective_language": None,
    }
    connection.execute(
        """INSERT INTO workflow_c_sampling_tasks(
               id, project_id, run_id, suite_id, task_key, source_stratum_hash,
               capture_method, question_id, question_version, repetition, status,
               version, payload, created_at, updated_at
           ) VALUES (%s, %s, %s, %s, %s, %s, 'manual_ui', 'question-1', 'v1',
                     %s, 'succeeded', 4, '{}'::jsonb, %s, %s)""",
        (
            task_id,
            project_id,
            run_id,
            suite_id,
            task_key,
            source_hash,
            repetition,
            now,
            now,
        ),
    )
    connection.execute(
        """INSERT INTO durable_jobs(
               id, project_id, kind, status, input_hash, idempotency_key,
               next_run_at, completed_at
           ) VALUES (%s, %s, 'sampling.manual_import', 'succeeded', %s, %s, %s, %s)""",
        (
            source_job_id,
            project_id,
            _hash(f"manual-source-job:{repetition}"),
            f"manual-source-job:{repetition}",
            now,
            now,
        ),
    )
    connection.execute(
        """INSERT INTO workflow_c_sampling_attempts(
               id, project_id, run_id, task_id, task_key, durable_job_id, ordinal,
               status, authorization_checked_at, actual_location_json,
               actual_location_hash, version, payload, created_at, updated_at
           ) VALUES (%s, %s, %s, %s, %s, %s, 1, 'succeeded', %s, %s::jsonb,
                     %s, 3, '{}'::jsonb, %s, %s)""",
        (
            attempt_id,
            project_id,
            run_id,
            task_id,
            task_key,
            source_job_id,
            now,
            Jsonb(actual_location),
            location_hash,
            now,
            now,
        ),
    )
    evidence = {
        "schema_version": 1,
        "kind": "manual_import",
        "derived_artifact": {
            "kind": "derived",
            "manifest_reference": f"s3://geo/manual/{artifact_id}/manifest.json",
            "manifest_hash": manifest_hash,
            "content_hash": content_hash,
            "governance_policy_hash": governance_hash,
        },
    }
    connection.execute(
        """INSERT INTO workflow_c_sampling_observations(
               id, project_id, run_id, task_id, attempt_id, task_key,
               source_stratum_hash, status, observation_hash,
               actual_location_json, evidence_json, payload, observed_at
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'complete', %s,
                     %s::jsonb, %s::jsonb, '{}'::jsonb, %s)""",
        (
            observation_id,
            project_id,
            run_id,
            task_id,
            attempt_id,
            task_key,
            source_hash,
            _hash(f"manual-observation:{repetition}"),
            Jsonb(actual_location),
            Jsonb(evidence),
            now,
        ),
    )
    connection.execute(
        """INSERT INTO workflow_c_manual_artifacts(
               artifact_id, project_id, run_id, task_id, capture_session_id,
               evidence_kind, source_content_type, persisted_content_type,
               source_content_hash, redacted_content_hash, object_uri, object_hash,
               manifest_uri, manifest_hash, governance_policy_hash,
               redactor_version_hash, scanner_version_hash, pii_finding_count,
               secret_finding_count, redaction_assurance, classification, audience,
               export_allowed, raw_retained, retention_days, expires_at, legal_hold,
               status, key_ref, encryption_algorithm, stored_byte_size, created_at,
               activated_at
           ) VALUES (
               %s, %s, %s, %s, %s, 'json', 'application/json', 'application/json',
               %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 0,
               'human_verified', 'restricted_manual_evidence', 'admin_only', false,
               false, 90, %s, false, 'active', %s,
               'AES-256-GCM/independent-DEK/v1', 128, %s, %s
           )""",
        (
            artifact_id,
            project_id,
            run_id,
            task_id,
            capture_session_id,
            _hash(f"manual-source:{repetition}"),
            content_hash,
            f"s3://geo/manual/{artifact_id}/payload.bin",
            _hash(f"manual-object:{repetition}"),
            f"s3://geo/manual/{artifact_id}/manifest.json",
            manifest_hash,
            governance_hash,
            _hash("redactor-v1"),
            _hash("scanner-v1"),
            now + timedelta(days=90),
            key_ref,
            now,
            now,
        ),
    )
    connection.execute(
        """INSERT INTO workflow_c_sampling_manual_imports(
               id, project_id, run_id, task_id, attempt_id, artifact_manifest_id,
               artifact_manifest_hash, artifact_content_hash, governance_policy_hash,
               capture_session_id, status, submitted_by, reviewed_by,
               aggregate_version, payload, submitted_at, reviewed_at, committed_at,
               review_reason
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'committed',
                     'manual-maker', 'manual-checker', 3, '{}'::jsonb, %s, %s, %s,
                     'approved redacted evidence')""",
        (
            import_id,
            project_id,
            run_id,
            task_id,
            attempt_id,
            artifact_id,
            manifest_hash,
            content_hash,
            governance_hash,
            capture_session_id,
            now,
            now,
            now,
        ),
    )


def _assert_atomic_state(
    database_url: str,
    app_url: str,
    *,
    project_id: UUID,
    manifest_id: UUID,
    job_id: UUID,
) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        set_project_scope(connection, project_id)
        manifest = connection.execute(
            """SELECT planned_slot_count, observation_count, payload
                 FROM workflow_c_analysis_input_manifests
                WHERE project_id = %s AND id = %s""",
            (project_id, manifest_id),
        ).fetchone()
        spec = connection.execute(
            """SELECT spec_payload FROM workflow_c_job_specs
                WHERE project_id = %s AND job_id = %s""",
            (project_id, job_id),
        ).fetchone()
        outbox_count = connection.execute(
            "SELECT count(*) AS count FROM broker_outbox WHERE project_id = %s AND job_id = %s",
            (project_id, job_id),
        ).fetchone()["count"]
        assert manifest["planned_slot_count"] == manifest["observation_count"] == 3
        assert len(manifest["payload"]["items"]) == 3
        assert spec["spec_payload"] == {
            "schema_version": 2,
            "kind": "workflow_c.analysis.semantic_metrics",
            "semantic_metrics": {
                "manifest_id": str(manifest_id),
                "manifest_hash": _canonical_hash(manifest["payload"]),
            },
        }
        assert "answer_text" not in str(spec["spec_payload"])
        assert outbox_count == 1
    with psycopg.connect(app_url, row_factory=dict_row) as connection:
        set_project_scope(connection, project_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """INSERT INTO workflow_c_analysis_input_manifests(
                       id, project_id, manifest_hash, sampling_run_id,
                       sampling_run_version, sampling_suite_hash, metric_protocol_id,
                       metric_protocol_hash, fact_snapshot_id, fact_snapshot_hash,
                       prompt_release_id, prompt_release_hash, corpus_version_id,
                       corpus_version_hash, source_stratum_hash, capture_method,
                       planned_slot_count, observation_count, payload, frozen_by, frozen_at
                   ) SELECT gen_random_uuid(), project_id, manifest_hash, sampling_run_id,
                       sampling_run_version, sampling_suite_hash, metric_protocol_id,
                       metric_protocol_hash, fact_snapshot_id, fact_snapshot_hash,
                       prompt_release_id, prompt_release_hash, corpus_version_id,
                       corpus_version_hash, source_stratum_hash, capture_method,
                       planned_slot_count, observation_count, payload, frozen_by, frozen_at
                     FROM workflow_c_analysis_input_manifests WHERE id = %s""",
                (manifest_id,),
            )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_hash(value: object) -> str:
    from geo_core.workflow_c_analysis_admission import canonical_hash

    return canonical_hash(value)


def _database_url(base: str, database_name: str) -> str:
    parts = urlsplit(base)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database_name}", parts.query, ""))
