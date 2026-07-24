from __future__ import annotations

from datetime import UTC, datetime, timedelta
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4, uuid5

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyDecisionRequest,
    AdmissionPolicySubmitRequest,
    CreateAdmissionPolicyRequest,
    StartSamplingRunRequest,
)
from geo_api.workflow_c_sampling_postgres_policy import (
    PostgresWorkflowCSamplingPolicyControl,
)
from geo_api.workflow_c_sampling_postgres_run import PostgresWorkflowCSamplingRunControl
from geo_core.object_store import S3CompatibleObjectStore, StoredObject, parse_s3_uri
from geo_core.project_scope import set_project_scope
from geo_core.sampling import SamplingRuleViolation
from geo_core.sampling import (
    CaptureMethod,
    LocationControl,
    PersistentSamplingSuiteInput,
    PostgresSamplingRunRepository,
    PostgresSamplingSuiteRepository,
    SamplingQuestion,
    SamplingSourceStratum,
    SamplingSuite,
)
from geo_core.sampling.postgres_admission import PostgresSamplingAdmissionRepository
from geo_core.sampling.manual_artifact_governance import AUTOMATIC_POLICY_KEY
from geo_core.sampling.manual_artifact_storage import (
    IndependentWorkflowCArtifactEncryptor,
    MinioWorkflowCManualArtifactWriter,
)
from geo_core.sampling.postgres_suites import SAMPLING_SUITE_INPUT_NAMESPACE
from geo_core.secrets import EnvelopeCipher, MasterKeyring
from geo_core.workflow_c_artifacts.postgres import (
    PostgresWorkflowCArtifactKeyVault,
    PostgresWorkflowCManualArtifactRepository,
    synchronize_workflow_c_artifact_master_keys,
)
from geo_core.workflow_c_artifacts.lifecycle import WorkflowCArtifactMaintenanceService
from geo_core.workflow_c_artifacts.postgres_lifecycle import (
    PostgresWorkflowCArtifactLifecycleRepository,
)
from geo_core.workflow_c_artifacts.reader import (
    PostgresWorkflowCManualArtifactReader,
    WorkflowCManualArtifactReadRequest,
)
from geo_core.workflow_c_artifacts.postgres_scheduler import (
    PostgresWorkflowCArtifactMaintenanceSchedulerRepository,
)
from geo_core.workflow_c_artifacts.scheduler import WorkflowCArtifactMaintenanceScheduler
from tests.integration.monitoring_postgres_support import isolated_minio_store
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


@dataclass
class _FailFirstDelete:
    store: S3CompatibleObjectStore
    failures_remaining: int = 1

    def delete_s3_uri(self, *, uri: str) -> bool:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("temporary object-store delete failure")
        return self.store.delete_s3_uri(uri=uri)


class _ObjectReadsForbidden:
    """Make the terminal Reader check prove that it never reaches MinIO."""

    def get_s3_uri(self, **_values):
        raise AssertionError("an invalid manual artifact must not reach MinIO")


@pytest.mark.parametrize("fail_first_delete", (False, True))
def test_workflow_c_maintenance_is_project_scoped_and_deletes_real_minio_objects(
    fail_first_delete: bool,
) -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_workflow_c_artifact_maintenance_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    worker_login, worker_password = f"geo_workflow_c_maint_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(worker_password)
                )
            )
            created_role = True
            first = seed_project(admin, suffix=f"workflow-c-maintenance-{suffix}-a")
            second = seed_project(admin, suffix=f"workflow-c-maintenance-{suffix}-b")

        worker_url = login_url(database_url, user=worker_login, password=worker_password)
        now = datetime.now(UTC).replace(microsecond=0)
        with isolated_minio_store() as objects:
            with psycopg.connect(database_url) as admin:
                first_expired = _seed_active_artifact(
                    admin,
                    objects=objects,
                    project_id=first["project"],
                    now=now,
                    marker="first-expired",
                    legal_hold=False,
                )
                first_held = _seed_active_artifact(
                    admin,
                    objects=objects,
                    project_id=first["project"],
                    now=now,
                    marker="first-held",
                    legal_hold=True,
                )
                second_expired = _seed_active_artifact(
                    admin,
                    objects=objects,
                    project_id=second["project"],
                    now=now,
                    marker="second-expired",
                    legal_hold=False,
                )

            scheduler = WorkflowCArtifactMaintenanceScheduler(
                repository=PostgresWorkflowCArtifactMaintenanceSchedulerRepository(
                    connect=lambda: psycopg.connect(worker_url, row_factory=dict_row)
                ),
                clock=lambda: now,
            )
            scheduled = scheduler.run_once()
            assert scheduled.scheduled_project_count == 2
            assert scheduled.inserted_job_count == 2
            _assert_scheduled_projects(database_url, {first["project"], second["project"]})

            current_time = [now]
            maintenance_store = _FailFirstDelete(objects) if fail_first_delete else objects
            service = WorkflowCArtifactMaintenanceService(
                repository=PostgresWorkflowCArtifactLifecycleRepository(
                    connect=lambda: psycopg.connect(worker_url, row_factory=dict_row)
                ),
                object_store=maintenance_store,
                worker_id="workflow-c-maintenance-integration",
                clock=lambda: current_time[0],
            )
            result = service.run_once(project_id=first["project"])

            assert result.claimed_count == 1
            assert result.crypto_erased_count == 1
            assert result.completed_count == (0 if fail_first_delete else 1)
            assert result.retry_count == (1 if fail_first_delete else 0)
            if fail_first_delete:
                _assert_artifact_state(
                    database_url,
                    artifact_id=first_expired["artifact_id"],
                    expected=("crypto_erased", "destroyed", "retry_wait"),
                )
                current_time[0] = now + timedelta(seconds=61)
                retry = service.run_once(project_id=first["project"])
                assert retry.claimed_count == 1
                assert retry.crypto_erased_count == 0
                assert retry.completed_count == 1
                assert retry.retry_count == 0
            assert not objects.head_object(key=first_expired["payload"].key)
            assert not objects.head_object(key=first_expired["manifest"].key)
            assert objects.head_object(key=first_held["payload"].key)
            assert objects.head_object(key=first_held["manifest"].key)
            assert objects.head_object(key=second_expired["payload"].key)
            assert objects.head_object(key=second_expired["manifest"].key)
            _assert_artifact_state(
                database_url,
                artifact_id=first_expired["artifact_id"],
                expected=("tombstoned", "destroyed", "completed"),
            )
            _assert_artifact_state(
                database_url,
                artifact_id=first_held["artifact_id"],
                expected=("active", "active", None),
            )
            _assert_artifact_state(
                database_url,
                artifact_id=second_expired["artifact_id"],
                expected=("delete_pending", "active", "pending"),
            )
        alembic_command.downgrade(migration, "0036_recommendation_locks")
        # The pre-0064 model has only an unbounded boolean hold. The new
        # migration intentionally rejects that ambiguous state until an
        # operator releases it and obtains a bounded reapproval, so remove the
        # direct fixture before exercising the compatible upgrade replay.
        with psycopg.connect(database_url) as admin:
            admin.execute(
                """UPDATE workflow_c_manual_artifacts
                     SET legal_hold = false
                   WHERE artifact_id = %s""",
                (first_held["artifact_id"],),
            )
        alembic_command.upgrade(migration, "head")
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
                server.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login))
                )


def test_manual_artifact_reader_recovers_then_fails_closed_after_real_tombstone() -> None:
    """Exercise governed encryption, PostgreSQL lineage, MinIO, and invalidation together."""

    suffix = uuid4().hex[:10]
    database_name = f"geo_workflow_c_artifact_reader_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_workflow_c_writer_{suffix}", uuid4().hex
    worker_login, worker_password = f"geo_workflow_c_reader_{suffix}", uuid4().hex
    created_database = False
    created_logins = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        alembic_command.upgrade(migration, "head")
        alembic_command.downgrade(migration, "0045_sampling_terminal_reconcile")
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(worker_password)
                )
            )
            created_logins = True
            project = seed_project(admin, suffix=f"workflow-c-reader-{suffix}")["project"]
            _seed_manual_runtime_option(admin, project_id=project)

        app_url = login_url(database_url, user=app_login, password=app_password)
        worker_url = login_url(database_url, user=worker_login, password=worker_password)
        now = datetime.now(UTC).replace(microsecond=0)
        cipher = EnvelopeCipher(MasterKeyring(keys={1: b"W" * 32}, active_version=1))
        with psycopg.connect(database_url, row_factory=dict_row) as admin:
            assert synchronize_workflow_c_artifact_master_keys(admin, cipher) == (1,)

        with isolated_minio_store() as objects:

            def app_connect():
                return psycopg.connect(app_url, row_factory=dict_row)

            artifact_id = uuid4()
            run_id, task_id = _create_manual_sampling_lineage(
                app_connect=app_connect,
                project_id=project,
                now=now,
            )
            writer = MinioWorkflowCManualArtifactWriter(
                object_store=objects,
                encryptor=IndependentWorkflowCArtifactEncryptor(
                    PostgresWorkflowCArtifactKeyVault(
                        connect=app_connect, cipher=cipher, synchronize=False
                    )
                ),
                repository=PostgresWorkflowCManualArtifactRepository(connect=app_connect),
                retention_days=1,
                clock=lambda: now,
            )
            receipt = writer.write(
                project_id=project,
                run_id=run_id,
                task_id=task_id,
                artifact_manifest_id=artifact_id,
                capture_session_id=uuid4(),
                evidence_kind="transcript_export",
                content_type="application/json",
                content=bytearray(
                    b'{"answer":"Australian consumer result","email":"owner@example.com",'
                    b'"token":"must-not-persist"}'
                ),
                governance_policy_key=AUTOMATIC_POLICY_KEY,
                pre_redacted_attestation=False,
            )
            with app_connect() as application_connection:
                set_project_scope(application_connection, project)
                privileges = application_connection.execute(
                    """SELECT has_table_privilege(
                           current_user,
                           'workflow_c_manual_artifacts',
                           'UPDATE'
                       ) AS can_update"""
                ).fetchone()
            assert privileges is not None
            assert not bool(privileges["can_update"])
            reader = PostgresWorkflowCManualArtifactReader(
                connect=app_connect,
                cipher=cipher,
                object_store=objects,
                clock=lambda: now,
            )
            recovered = reader.load(
                WorkflowCManualArtifactReadRequest(
                    project_id=project,
                    artifact_id=artifact_id,
                    expected_manifest_hash=receipt.artifact_manifest_hash,
                    expected_content_hash=receipt.artifact_content_hash,
                )
            )
            try:
                assert b"Australian consumer result" in recovered.payload
                assert b"owner@example.com" not in recovered.payload
                assert b"must-not-persist" not in recovered.payload
            finally:
                recovered.wipe()

            with psycopg.connect(database_url, row_factory=dict_row) as admin:
                row = admin.execute(
                    """SELECT object_uri, manifest_uri
                         FROM workflow_c_manual_artifacts
                        WHERE project_id = %s AND artifact_id = %s""",
                    (project, artifact_id),
                ).fetchone()
            assert row is not None
            _payload_bucket, payload_key = parse_s3_uri(str(row["object_uri"]))
            _manifest_bucket, manifest_key = parse_s3_uri(str(row["manifest_uri"]))

            expired_at = now + timedelta(days=1, seconds=1)
            scheduler = WorkflowCArtifactMaintenanceScheduler(
                repository=PostgresWorkflowCArtifactMaintenanceSchedulerRepository(
                    connect=lambda: psycopg.connect(worker_url, row_factory=dict_row)
                ),
                clock=lambda: expired_at,
            )
            assert scheduler.run_once().inserted_job_count == 1
            service = WorkflowCArtifactMaintenanceService(
                repository=PostgresWorkflowCArtifactLifecycleRepository(
                    connect=lambda: psycopg.connect(worker_url, row_factory=dict_row)
                ),
                object_store=objects,
                worker_id="workflow-c-reader-integration",
                clock=lambda: expired_at,
            )
            outcome = service.run_once(project_id=project)
            assert (
                outcome.claimed_count,
                outcome.crypto_erased_count,
                outcome.completed_count,
            ) == (
                1,
                1,
                1,
            )
            assert not objects.head_object(key=payload_key)
            assert not objects.head_object(key=manifest_key)

            terminal_reader = PostgresWorkflowCManualArtifactReader(
                connect=app_connect,
                cipher=cipher,
                object_store=_ObjectReadsForbidden(),
                clock=lambda: expired_at,
            )
            with pytest.raises(SamplingRuleViolation, match="does not exist"):
                terminal_reader.load(
                    WorkflowCManualArtifactReadRequest(
                        project_id=project,
                        artifact_id=artifact_id,
                        expected_manifest_hash=receipt.artifact_manifest_hash,
                        expected_content_hash=receipt.artifact_content_hash,
                    )
                )
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        if created_logins:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))
                server.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login))
                )


def _seed_manual_runtime_option(connection, *, project_id: UUID) -> None:
    connection.execute(
        """INSERT INTO workflow_c_sampling_runtime_options(
               project_id, option_key, option_hash, display_name, platform,
               capture_method, adapter_release, location_control,
               location_evidence_hash, authorization_reference, allowed_purposes,
               status, frozen_at
           ) VALUES (
               %s, 'manual-au-v1', %s, 'Manual AU', 'consumer_ai', 'manual_ui',
               'manual-ui-au-v1', 'country', %s, 'authorization:manual-au',
               %s::jsonb, 'approved', clock_timestamp()
           )""",
        (
            project_id,
            _hash("manual-runtime-option"),
            _hash("manual-location:au"),
            Jsonb(["geo_measurement"]),
        ),
    )


def _create_manual_sampling_lineage(
    *, app_connect, project_id: UUID, now: datetime
) -> tuple[UUID, UUID]:
    policies = PostgresWorkflowCSamplingPolicyControl(
        repository=PostgresSamplingAdmissionRepository(connect=app_connect, clock=lambda: now),
        clock=lambda: now,
    )
    created_policy = policies.create(
        project_id=project_id,
        actor_id="manual-writer-maker",
        idempotency_key="manual-writer:policy",
        payload=CreateAdmissionPolicyRequest(
            runtime_authorization_option_key="manual-au-v1",
            purpose="geo_measurement",
            valid_until=now + timedelta(days=7),
            quota_remaining=3,
            daily_task_limit=3,
            minimum_request_interval_seconds=0,
            max_concurrency=1,
        ),
    ).record
    submitted_policy = policies.submit(
        project_id=project_id,
        policy_id=created_policy.id,
        actor_id="manual-writer-maker",
        idempotency_key="manual-writer:policy:submit",
        payload=AdmissionPolicySubmitRequest(expected_version=created_policy.aggregate_version),
    ).record
    approved_policy = policies.decide(
        project_id=project_id,
        policy_id=created_policy.id,
        actor_id="manual-writer-checker",
        idempotency_key="manual-writer:policy:approve",
        payload=AdmissionPolicyDecisionRequest(
            expected_version=submitted_policy.aggregate_version,
            reason="manual capture is authorized",
        ),
        approved=True,
    ).record
    source = SamplingSourceStratum(
        platform="consumer_ai",
        surface="manual_consumer_ui",
        configured_model="not_disclosed",
        reported_model="not_disclosed",
        capture_method=CaptureMethod.MANUAL_UI,
        adapter_release="manual-ui-au-v1",
        locale="en-AU",
        region="AU",
        language="en",
        search_mode="consumer_ui",
        account_cohort="approved_operator",
        egress_policy_category="operator_verified",
        location_control=LocationControl.COUNTRY,
        location_evidence_hash=_hash("manual-location:au"),
        requested_country="AU",
        requested_region=None,
        requested_locale="en-AU",
        requested_language="en",
        effective_country="AU",
        effective_region=None,
        effective_locale=None,
        effective_language=None,
    )
    option_key = "manual-artifact-lineage-v1"
    input_option = PersistentSamplingSuiteInput(
        id=uuid5(SAMPLING_SUITE_INPUT_NAMESPACE, f"{project_id}:{option_key}"),
        project_id=project_id,
        option_key=option_key,
        display_name="Manual artifact lineage",
        question_set_id=uuid4(),
        question_set_version="manual-question-set-v1",
        question_set_hash=_hash("manual-question-set"),
        questions=(SamplingQuestion("manual-q-1", "v1", _hash("manual question")),),
        adapter_release_id=uuid4(),
        adapter_release_hash=_hash("manual-adapter-release"),
        model_release_id=uuid4(),
        model_release_hash=_hash("manual-model-release"),
        route_policy_id=uuid4(),
        route_policy_hash=_hash("manual-route-policy"),
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash=_hash("manual-runtime-manifest"),
        runtime_option_id=uuid4(),
        runtime_option_hash=_hash("manual-runtime-option"),
        admission_policy_id=approved_policy.id,
        admission_policy_hash=approved_policy.definition_hash,
        source_stratum=source,
        frozen_at=now,
    )
    suites = PostgresSamplingSuiteRepository(connect=app_connect)
    suites.register_input(input_option, idempotency_key="manual-writer:input")
    suite = SamplingSuite(
        id=uuid4(),
        project_id=project_id,
        question_set_id=input_option.question_set_id,
        question_set_version=input_option.question_set_version,
        question_set_hash=input_option.question_set_hash,
        adapter_release_id=input_option.adapter_release_id,
        adapter_release_hash=input_option.adapter_release_hash,
        model_release_id=input_option.model_release_id,
        model_release_hash=input_option.model_release_hash,
        route_policy_id=input_option.route_policy_id,
        route_policy_hash=input_option.route_policy_hash,
        runtime_manifest_id=input_option.runtime_manifest_id,
        runtime_manifest_hash=input_option.runtime_manifest_hash,
        runtime_option_id=input_option.runtime_option_id,
        runtime_option_hash=input_option.runtime_option_hash,
        admission_policy_id=input_option.admission_policy_id,
        admission_policy_hash=input_option.admission_policy_hash,
        questions=input_option.questions,
        source_stratum=source,
        repetitions=3,
        statistics_method_version="manual-sampling-statistics-v1",
        max_planned_tasks=3,
        max_daily_tasks=3,
        minimum_request_interval_seconds=0,
        max_concurrency=1,
        frozen_by="manual-writer",
        frozen_at=now,
    )
    suites.create_suite(suite, input_option=input_option, idempotency_key="manual-writer:suite")
    run, tasks = PostgresWorkflowCSamplingRunControl(
        runs=PostgresSamplingRunRepository(connect=app_connect),
        suites=suites,
        policies=policies,
        clock=lambda: now,
    ).start_run(
        project_id=project_id,
        suite_id=suite.id,
        idempotency_key="manual-writer:run",
        payload=StartSamplingRunRequest(purpose="geo_measurement", requested_not_before=now),
    )
    assert len(tasks) == 3
    return run.id, tasks[0].id


def _seed_active_artifact(
    connection,
    *,
    objects: S3CompatibleObjectStore,
    project_id: UUID,
    now: datetime,
    marker: str,
    legal_hold: bool,
    run_id: UUID | None = None,
    task_id: UUID | None = None,
) -> dict[str, UUID | StoredObject]:
    artifact_id = uuid4()
    payload = objects.put_object(
        key=f"workflow-c-maintenance/{artifact_id}/payload.bin",
        content=f"encrypted fixture payload:{marker}".encode("utf-8"),
        content_type="application/octet-stream",
    )
    manifest = objects.put_object(
        key=f"workflow-c-maintenance/{artifact_id}/manifest.json",
        content=f'{{"artifact":"{artifact_id}","marker":"{marker}"}}'.encode("utf-8"),
        content_type="application/json",
    )
    created_at = now - timedelta(days=2)
    run_id = run_id or uuid4()
    task_id = task_id or uuid4()
    connection.execute("SET LOCAL session_replication_role = replica")
    connection.execute(
        """INSERT INTO workflow_c_artifact_master_key_versions(
               master_key_version, status, algorithm, canary_nonce,
               canary_ciphertext, created_at
           ) VALUES (1, 'encrypt_decrypt', 'AES-256-GCM', %s, %s, %s)
           ON CONFLICT (master_key_version) DO NOTHING""",
        (b"n" * 12, b"c" * 17, created_at),
    )
    connection.execute(
        """INSERT INTO workflow_c_artifact_deks(
               key_ref, project_id, artifact_id, ciphertext, data_nonce,
               wrapped_data_key, wrap_nonce, master_key_version, algorithm,
               status, created_at
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 'AES-256-GCM', 'active', %s)""",
        (
            artifact_id,
            project_id,
            artifact_id,
            b"c" * 17,
            b"n" * 12,
            b"w" * 48,
            b"r" * 12,
            created_at,
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
               legal_hold_until, status, key_ref, encryption_algorithm, stored_byte_size, created_at,
               activated_at
           ) VALUES (
               %s, %s, %s, %s, %s, 'screenshot', 'image/png',
               'application/octet-stream', %s, %s, %s, %s, %s, %s, %s, %s, %s,
               0, 0, 'automated_pass', 'restricted_manual_evidence', 'admin_only',
               false, false, 1, %s, %s, %s, 'active', %s, 'AES-256-GCM', %s, %s, %s
           )""",
        (
            artifact_id,
            project_id,
            run_id,
            task_id,
            uuid4(),
            _hash(f"source:{marker}"),
            _hash(f"redacted:{marker}"),
            payload.uri,
            payload.content_hash,
            manifest.uri,
            manifest.content_hash,
            _hash(f"policy:{marker}"),
            _hash(f"redactor:{marker}"),
            _hash(f"scanner:{marker}"),
            created_at + timedelta(days=1),
            legal_hold,
            (now + timedelta(days=1) if legal_hold else None),
            artifact_id,
            len(f"encrypted fixture payload:{marker}".encode("utf-8")),
            created_at,
            created_at,
        ),
    )
    return {"artifact_id": artifact_id, "payload": payload, "manifest": manifest}


def _assert_scheduled_projects(database_url: str, project_ids: set[UUID]) -> None:
    with psycopg.connect(database_url) as admin:
        rows = admin.execute(
            """SELECT project_id
                 FROM durable_jobs
                WHERE kind = 'workflow_c.artifact_maintenance'
                  AND status = 'queued'"""
        ).fetchall()
        outbox_count = admin.execute(
            """SELECT count(*)
                 FROM broker_outbox
                WHERE topic = 'workflow_c.artifact_maintenance'
                  AND published_at IS NULL"""
        ).fetchone()[0]
    assert {row[0] for row in rows} == project_ids
    assert outbox_count == len(project_ids)


def _assert_artifact_state(
    database_url: str,
    *,
    artifact_id: UUID,
    expected: tuple[str, str, str | None],
) -> None:
    with psycopg.connect(database_url) as admin:
        row = admin.execute(
            """SELECT artifact.status, dek.status, queue.status
                 FROM workflow_c_manual_artifacts AS artifact
                 JOIN workflow_c_artifact_deks AS dek
                   ON dek.project_id = artifact.project_id
                  AND dek.artifact_id = artifact.artifact_id
                 LEFT JOIN workflow_c_artifact_deletion_queue AS queue
                   ON queue.project_id = artifact.project_id
                  AND queue.artifact_id = artifact.artifact_id
                WHERE artifact.artifact_id = %s""",
            (artifact_id,),
        ).fetchone()
    assert row == expected


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit(parsed._replace(path=f"/{database_name}"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
