from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
from threading import Barrier
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.object_store import S3CompatibleObjectStore, parse_s3_uri
from geo_core.synthetic_lab.artifact_maintenance import SyntheticArtifactMaintenanceService
from geo_core.synthetic_lab.artifact_maintenance_contracts import (
    SYNTHETIC_ARTIFACT_MAINTENANCE_JOB_KIND,
)
from geo_core.synthetic_lab.postgres_artifact_maintenance import (
    PostgresSyntheticArtifactMaintenanceRepository,
)
from geo_core.synthetic_lab.raw_artifact_storage_contracts import RawArtifactStorageError
from geo_core.synthetic_lab.raw_artifact_storage import RawArtifactStores
from geo_worker.synthetic_artifact_maintenance import SyntheticArtifactMaintenanceOperation
from tests.integration.monitoring_postgres_support import isolated_minio_store
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


@dataclass(frozen=True)
class _Database:
    admin_url: str
    worker_url: str
    first: dict[str, UUID]
    second: dict[str, UUID]


@pytest.fixture
def database() -> _Database:
    suffix = uuid4().hex[:10]
    database_name = f"geo_synthetic_retention_{suffix}"
    target_url = _database_url(ADMIN_URL, database_name)
    worker_login, worker_password = f"geo_retention_worker_{suffix}", uuid4().hex
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(target_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(worker_password)
                )
            )
            first = seed_project(admin, suffix=f"synthetic-retention-{suffix}-a")
            second = seed_project(admin, suffix=f"synthetic-retention-{suffix}-b")
        yield _Database(
            admin_url=target_url,
            worker_url=login_url(target_url, user=worker_login, password=worker_password),
            first=first,
            second=second,
        )
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )
            server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login)))


@dataclass
class _RecordingStore:
    deleted: list[str]
    fail_payload_once: bool = False

    def delete_s3_uri(self, *, uri: str) -> bool:
        self.deleted.append(uri)
        if self.fail_payload_once and uri.endswith("payload.bin"):
            self.fail_payload_once = False
            raise RuntimeError("object deletion fixture failure")
        return True


@dataclass
class _FailPayloadDeleteOnce:
    """Fault injector around the real object-store client for retry coverage."""

    store: S3CompatibleObjectStore
    fail_payload_once: bool = True

    def delete_s3_uri(self, *, uri: str) -> bool:
        if self.fail_payload_once and uri.endswith("payload.bin"):
            self.fail_payload_once = False
            raise RuntimeError("object deletion fixture failure")
        return self.store.delete_s3_uri(uri=uri)


def test_synthetic_artifact_maintenance_is_project_scoped_and_fenced(
    database: _Database,
) -> None:
    now = datetime.now(UTC)
    first_artifact = _seed_deletion_pending_artifact(
        database.admin_url, project_id=database.first["project"], now=now
    )
    second_artifact = _seed_deletion_pending_artifact(
        database.admin_url, project_id=database.second["project"], now=now
    )

    scheduled = _schedule_maintenance(database.worker_url, now=now)
    assert {row["project_id"] for row in scheduled} == {
        database.first["project"],
        database.second["project"],
    }
    first_job_id = next(
        row["job_id"] for row in scheduled if row["project_id"] == database.first["project"]
    )

    def connect_worker():
        return psycopg.connect(database.worker_url, row_factory=dict_row)

    deletion_store = _RecordingStore([])
    service = SyntheticArtifactMaintenanceService(
        repository=PostgresSyntheticArtifactMaintenanceRepository(connect_worker),
        stores=RawArtifactStores(
            encrypted_raw=deletion_store,
            restricted_independent_dek=deletion_store,
            derived_project=deletion_store,
        ),
        worker_id="synthetic-retention-integration",
        clock=lambda: now,
    )
    durable_jobs = PostgresDurableJobStore(connect_worker)
    claim = durable_jobs.claim(
        job_id=first_job_id,
        project_id=database.first["project"],
        expected_kind=SYNTHETIC_ARTIFACT_MAINTENANCE_JOB_KIND,
        worker_id="synthetic-retention-integration",
        lease_for=timedelta(minutes=2),
    )
    assert claim.disposition == "claimed" and claim.lease is not None
    operation = SyntheticArtifactMaintenanceOperation(
        store=durable_jobs,
        service=service,
        lease_for=timedelta(minutes=2),
    )

    result = operation.execute(claim.lease)

    assert result == {
        "status": "succeeded",
        "job_id": str(first_job_id),
        "staged_expiry_count": 0,
        "claimed_count": 1,
        "crypto_erased_count": 1,
        "completed_count": 1,
        "retry_count": 0,
    }
    assert deletion_store.deleted == [
        first_artifact["manifest_uri"],
        first_artifact["payload_uri"],
    ]
    _assert_completed_artifact(database.admin_url, first_artifact)
    _assert_pending_artifact(database.admin_url, second_artifact)


def test_synthetic_artifact_maintenance_does_not_claim_an_active_legal_hold(
    database: _Database,
) -> None:
    now = datetime.now(UTC)
    artifact = _seed_deletion_pending_artifact(
        database.admin_url, project_id=database.first["project"], now=now
    )
    _place_active_legal_hold(
        database.admin_url,
        project=database.first,
        artifact=artifact,
        now=now,
    )
    deletion_store = _RecordingStore([])
    service = _maintenance_service(
        database.worker_url,
        deletion_store,
        clock=lambda: now,
    )

    result = service.run_once(project_id=database.first["project"])

    assert result.staged_expiry_count == 0
    assert result.claimed_count == 0
    assert result.crypto_erased_count == 0
    assert result.completed_count == 0
    assert result.retry_count == 0
    assert deletion_store.deleted == []
    _assert_pending_artifact(database.admin_url, artifact)


def test_synthetic_artifact_maintenance_concurrent_wakes_create_one_job_and_outbox(
    database: _Database,
) -> None:
    """A project lock makes concurrent scheduler wakes replay the same Job."""

    now = datetime.now(UTC)
    _seed_deletion_pending_artifact(
        database.admin_url, project_id=database.first["project"], now=now
    )
    with psycopg.connect(database.admin_url) as admin:
        admin.execute(
            """CREATE FUNCTION geo_test_pause_synthetic_maintenance_insert()
                   RETURNS trigger LANGUAGE plpgsql AS $$
                   BEGIN
                       IF NEW.kind = 'synthetic_lab.artifact_maintenance' THEN
                           PERFORM pg_sleep(0.25);
                       END IF;
                       RETURN NEW;
                   END;
                   $$"""
        )
        admin.execute(
            """CREATE TRIGGER geo_test_pause_synthetic_maintenance_insert
                   BEFORE INSERT ON durable_jobs
                   FOR EACH ROW EXECUTE FUNCTION geo_test_pause_synthetic_maintenance_insert()"""
        )

    barrier = Barrier(3)

    def schedule() -> tuple[dict[str, object], ...]:
        barrier.wait(timeout=5)
        return _schedule_maintenance(database.worker_url, now=now)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.submit(schedule), executor.submit(schedule)
        barrier.wait(timeout=5)
        rows = first.result(timeout=10) + second.result(timeout=10)

    assert len(rows) == 2
    assert {row["project_id"] for row in rows} == {database.first["project"]}
    assert len({row["job_id"] for row in rows}) == 1
    assert {row["replayed"] for row in rows} == {False, True}
    with psycopg.connect(database.admin_url) as admin:
        counts = admin.execute(
            """SELECT
                   (SELECT count(*) FROM durable_jobs
                     WHERE project_id = %s
                       AND kind = 'synthetic_lab.artifact_maintenance'
                       AND idempotency_key = 'synthetic-artifact-maintenance:v1'),
                   (SELECT count(*) FROM broker_outbox
                     WHERE project_id = %s
                       AND topic = 'synthetic_lab.artifact_maintenance')""",
            (database.first["project"], database.first["project"]),
        ).fetchone()
    assert counts == (1, 1)


def test_synthetic_artifact_maintenance_retries_partial_object_deletion_after_crypto_erasure(
    database: _Database,
) -> None:
    now = datetime.now(UTC)
    artifact = _seed_deletion_pending_artifact(
        database.admin_url, project_id=database.first["project"], now=now
    )
    current_time = [now]
    deletion_store = _RecordingStore([], fail_payload_once=True)
    service = _maintenance_service(
        database.worker_url,
        deletion_store,
        clock=lambda: current_time[0],
    )

    first = service.run_once(project_id=database.first["project"])

    assert first.staged_expiry_count == 0
    assert first.claimed_count == 1
    assert first.crypto_erased_count == 1
    assert first.completed_count == 0
    assert first.retry_count == 1
    _assert_object_deletion_retry(database.admin_url, artifact)

    current_time[0] = now + timedelta(seconds=61)
    second = service.run_once(project_id=database.first["project"])

    assert second.staged_expiry_count == 0
    assert second.claimed_count == 1
    assert second.crypto_erased_count == 0
    assert second.completed_count == 1
    assert second.retry_count == 0
    assert deletion_store.deleted == [
        artifact["manifest_uri"],
        artifact["payload_uri"],
        artifact["manifest_uri"],
        artifact["payload_uri"],
    ]
    _assert_completed_artifact(database.admin_url, artifact)


def test_synthetic_artifact_maintenance_deletes_real_minio_objects_after_crypto_erasure(
    database: _Database,
) -> None:
    """Exercise the irreversible PostgreSQL lifecycle against a real S3 endpoint."""

    now = datetime.now(UTC)
    with isolated_minio_store() as store:
        artifact = _seed_deletion_pending_artifact(
            database.admin_url,
            project_id=database.first["project"],
            now=now,
            bucket=store.bucket,
        )
        _put_minio_artifact_objects(store, artifact)

        service = _maintenance_service(
            database.worker_url,
            store,
            clock=lambda: now,
        )

        result = service.run_once(project_id=database.first["project"])

        assert result.staged_expiry_count == 0
        assert result.claimed_count == 1
        assert result.crypto_erased_count == 1
        assert result.completed_count == 1
        assert result.retry_count == 0
        for uri in (artifact["manifest_uri"], artifact["payload_uri"]):
            _, key = parse_s3_uri(str(uri))
            assert not store.head_object(key=key)
        _assert_completed_artifact(database.admin_url, artifact)


def test_synthetic_artifact_maintenance_retries_partial_real_minio_deletion_after_crypto_erasure(
    database: _Database,
) -> None:
    """Missing manifest deletes are idempotent after a partial real-MinIO failure."""

    now = datetime.now(UTC)
    current_time = [now]
    with isolated_minio_store() as store:
        artifact = _seed_deletion_pending_artifact(
            database.admin_url,
            project_id=database.first["project"],
            now=now,
            bucket=store.bucket,
        )
        _put_minio_artifact_objects(store, artifact)
        service = _maintenance_service(
            database.worker_url,
            _FailPayloadDeleteOnce(store),
            clock=lambda: current_time[0],
        )

        first = service.run_once(project_id=database.first["project"])

        assert first.crypto_erased_count == 1
        assert first.completed_count == 0
        assert first.retry_count == 1
        manifest_bucket, manifest_key = parse_s3_uri(str(artifact["manifest_uri"]))
        payload_bucket, payload_key = parse_s3_uri(str(artifact["payload_uri"]))
        assert manifest_bucket == payload_bucket == store.bucket
        assert not store.head_object(key=manifest_key)
        assert store.head_object(key=payload_key)
        _assert_object_deletion_retry(database.admin_url, artifact)

        current_time[0] = now + timedelta(seconds=61)
        second = service.run_once(project_id=database.first["project"])

        assert second.crypto_erased_count == 0
        assert second.completed_count == 1
        assert second.retry_count == 0
        assert not store.head_object(key=manifest_key)
        assert not store.head_object(key=payload_key)
        _assert_completed_artifact(database.admin_url, artifact)


def test_synthetic_artifact_deletion_lease_cannot_commit_after_expiry(
    database: _Database,
) -> None:
    now = datetime.now(UTC)
    artifact = _seed_deletion_pending_artifact(
        database.admin_url, project_id=database.first["project"], now=now
    )

    def connect_worker():
        return psycopg.connect(database.worker_url, row_factory=dict_row)

    repository = PostgresSyntheticArtifactMaintenanceRepository(connect_worker)
    (expired_lease,) = repository.claim_deletions(
        project_id=database.first["project"],
        worker_id="synthetic-retention-expired",
        now=now,
        batch_size=1,
        lease_seconds=5,
    )
    (current_lease,) = repository.claim_deletions(
        project_id=database.first["project"],
        worker_id="synthetic-retention-current",
        now=now + timedelta(seconds=6),
        batch_size=1,
        lease_seconds=120,
    )

    assert current_lease.outbox_id == expired_lease.outbox_id
    assert current_lease.lease_token != expired_lease.lease_token
    assert current_lease.deletion_fencing_generation > expired_lease.deletion_fencing_generation
    with pytest.raises(RawArtifactStorageError, match="PostgreSQL transition failed"):
        repository.crypto_erase_and_tombstone(
            expired_lease,
            erased_at=now + timedelta(seconds=7),
        )

    _assert_leased_artifact(database.admin_url, artifact)


def _seed_deletion_pending_artifact(
    database_url: str,
    *,
    project_id: UUID,
    now: datetime,
    bucket: str = "geo-synthetic-style-raw",
) -> dict[str, object]:
    artifact_id, job_id, outbox_id = uuid4(), uuid4(), uuid4()
    captured_at = now - timedelta(days=2)
    artifact_key_ref = f"synthetic-artifact-dek:{artifact_id}"
    values = {
        "artifact_id": artifact_id,
        "job_id": job_id,
        "outbox_id": outbox_id,
        "artifact_key_ref": artifact_key_ref,
        "content_hash": _hash(f"content:{artifact_id}"),
        "stored_hash": _hash(f"stored:{artifact_id}"),
        "manifest_hash": _hash(f"manifest:{artifact_id}"),
        "source_hash": _hash(f"source:{artifact_id}"),
        "manifest_uri": f"s3://{bucket}/synthetic/{artifact_id}/manifest.json",
        "payload_uri": f"s3://{bucket}/synthetic/{artifact_id}/payload.bin",
    }
    with psycopg.connect(database_url) as admin:
        try:
            admin.execute("SET session_replication_role = replica")
            admin.execute("SET CONSTRAINTS ALL DEFERRED")
            admin.execute(
                """INSERT INTO synthetic_lab_artifact_master_key_versions(
                       master_key_version, algorithm, status, canary_nonce,
                       canary_ciphertext, created_at, activated_at
                   ) VALUES ('1', 'AES-256-GCM', 'encrypt_decrypt', %s, %s, %s, %s)
                   ON CONFLICT (master_key_version) DO NOTHING""",
                (b"n" * 12, b"c" * 17, now, now),
            )
            admin.execute(
                """INSERT INTO durable_jobs(
                       id, project_id, kind, status, input_hash, idempotency_key,
                       max_attempts, next_run_at
                   ) VALUES (%s, %s, 'style.collect', 'succeeded', %s, %s, 3, %s)""",
                (job_id, project_id, _hash(f"job:{job_id}"), f"retention-seed:{job_id}", now),
            )
            admin.execute(
                """INSERT INTO synthetic_lab_job_metadata(
                       job_id, project_id, metadata_version, domain_job_kind,
                       payload, payload_hash
                   ) VALUES (%s, %s, 1, 'style_collection', %s, %s)""",
                (job_id, project_id, Jsonb({}), _hash(f"metadata:{job_id}")),
            )
            admin.execute(
                """INSERT INTO synthetic_lab_artifact_governance_decisions(
                       artifact_id, project_id, captured_at, classification,
                       persisted_content_hash, persistence_allowed, storage_tier,
                       independent_dek_required, allowed_audiences, ttl_days,
                       expires_at, destroy_temporary_payload
                   ) VALUES (
                       %s, %s, %s, 'restricted_authenticated_raw', %s, true,
                       'restricted_independent_dek', true, ARRAY['style_raw_reviewer'],
                       1, %s, true
                   )""",
                (
                    artifact_id,
                    project_id,
                    captured_at,
                    values["content_hash"],
                    captured_at + timedelta(days=1),
                ),
            )
            admin.execute(
                """INSERT INTO synthetic_lab_raw_artifacts(
                       project_id, artifact_id, job_id, generation_lease_token,
                       fencing_generation, artifact_form, classification, storage_tier,
                       persisted_content_hash, stored_object_hash, manifest_hash,
                       manifest_uri, payload_uri, media_type, byte_size, record_count,
                       source_identity_hash, producer_release, encryption_algorithm,
                       artifact_key_ref, captured_at, created_at, ttl_days, expires_at,
                       allowed_audiences, lifecycle_state, deletion_pending_at
                   ) VALUES (
                       %s, %s, %s, %s, 1, 'raw', 'restricted_authenticated_raw',
                       'restricted_independent_dek', %s, %s, %s, %s, %s,
                       'application/octet-stream', 1, 1, %s, 'retention-integration',
                       'AES-256-GCM/independent-DEK/v1', %s, %s, %s, 1, %s,
                       ARRAY['style_raw_reviewer'], 'deletion_pending', %s
                   )""",
                (
                    project_id,
                    artifact_id,
                    job_id,
                    uuid4(),
                    values["content_hash"],
                    values["stored_hash"],
                    values["manifest_hash"],
                    values["manifest_uri"],
                    values["payload_uri"],
                    values["source_hash"],
                    artifact_key_ref,
                    captured_at,
                    captured_at,
                    captured_at + timedelta(days=1),
                    now,
                ),
            )
            admin.execute(
                """INSERT INTO synthetic_lab_artifact_deks(
                       key_ref, project_id, artifact_id, fencing_generation,
                       wrapped_dek, wrap_nonce, master_key_version, algorithm,
                       status, created_at
                   ) VALUES (%s, %s, %s, 1, %s, %s, '1',
                             'AES-256-GCM/synthetic-artifact-KEK/v1', 'active', %s)""",
                (artifact_key_ref, project_id, artifact_id, b"d" * 48, b"w" * 12, captured_at),
            )
            admin.execute(
                """INSERT INTO synthetic_lab_artifact_deletion_outbox(
                       id, project_id, artifact_id, artifact_generation, manifest_hash,
                       reason, status, next_attempt_at
                   ) VALUES (%s, %s, %s, 1, %s, 'retention_expired', 'pending', %s)""",
                (
                    outbox_id,
                    project_id,
                    artifact_id,
                    values["manifest_hash"],
                    now - timedelta(seconds=1),
                ),
            )
        finally:
            admin.execute("SET session_replication_role = origin")
    return values


def _maintenance_service(
    worker_url: str,
    deletion_store,
    *,
    clock,
) -> SyntheticArtifactMaintenanceService:
    def connect_worker():
        return psycopg.connect(worker_url, row_factory=dict_row)

    return SyntheticArtifactMaintenanceService(
        repository=PostgresSyntheticArtifactMaintenanceRepository(connect_worker),
        stores=RawArtifactStores(
            encrypted_raw=deletion_store,
            restricted_independent_dek=deletion_store,
            derived_project=deletion_store,
        ),
        worker_id="synthetic-retention-integration",
        clock=clock,
    )


def _put_minio_artifact_objects(
    store: S3CompatibleObjectStore, artifact: dict[str, object]
) -> None:
    for uri, content in (
        (artifact["manifest_uri"], b'{"schema_version":1}'),
        (artifact["payload_uri"], b"encrypted-style-source"),
    ):
        bucket, key = parse_s3_uri(str(uri))
        assert bucket == store.bucket
        store.put_object(
            key=key,
            content=content,
            content_type="application/octet-stream",
        )
        assert store.head_object(key=key)


def _place_active_legal_hold(
    database_url: str,
    *,
    project: dict[str, UUID],
    artifact: dict[str, object],
    now: datetime,
) -> None:
    with psycopg.connect(database_url) as admin:
        admin.execute(
            """INSERT INTO synthetic_lab_artifact_legal_holds(
                   id, project_id, artifact_id, artifact_generation,
                   first_approver_id, second_approver_id, reason,
                   approved_at, expires_at, hold_hash
               ) VALUES (%s, %s, %s, 1, %s, %s, 'integration legal hold', %s, %s, %s)""",
            (
                uuid4(),
                project["project"],
                artifact["artifact_id"],
                project["owner"],
                project["reviewer"],
                now - timedelta(minutes=1),
                now + timedelta(days=1),
                _hash(f"hold:{artifact['artifact_id']}"),
            ),
        )


def _schedule_maintenance(worker_url: str, *, now: datetime) -> tuple[dict[str, object], ...]:
    with psycopg.connect(worker_url, row_factory=dict_row) as worker:
        return tuple(
            worker.execute(
                "SELECT * FROM geo_enqueue_synthetic_artifact_maintenance(%s)", (now,)
            ).fetchall()
        )


def _assert_completed_artifact(database_url: str, artifact: dict[str, object]) -> None:
    with psycopg.connect(database_url) as admin:
        row = admin.execute(
            """SELECT artifact.lifecycle_state, artifact.manifest_uri, artifact.payload_uri,
                      dek.status, outbox.status,
                      (SELECT count(*) FROM synthetic_lab_artifact_crypto_erasures AS erased
                       WHERE erased.project_id = artifact.project_id
                         AND erased.artifact_id = artifact.artifact_id),
                      (SELECT count(*) FROM synthetic_lab_artifact_tombstones AS tombstone
                       WHERE tombstone.project_id = artifact.project_id
                         AND tombstone.artifact_id = artifact.artifact_id)
               FROM synthetic_lab_raw_artifacts AS artifact
               JOIN synthetic_lab_artifact_deks AS dek
                 ON dek.project_id = artifact.project_id AND dek.artifact_id = artifact.artifact_id
               JOIN synthetic_lab_artifact_deletion_outbox AS outbox
                 ON outbox.project_id = artifact.project_id AND outbox.artifact_id = artifact.artifact_id
               WHERE artifact.artifact_id = %s""",
            (artifact["artifact_id"],),
        ).fetchone()
    assert row == ("deleted", None, None, "destroyed", "completed", 1, 1)


def _assert_pending_artifact(database_url: str, artifact: dict[str, object]) -> None:
    with psycopg.connect(database_url) as admin:
        row = admin.execute(
            """SELECT artifact.lifecycle_state, dek.status, outbox.status,
                      (SELECT count(*) FROM synthetic_lab_artifact_crypto_erasures AS erased
                       WHERE erased.project_id = artifact.project_id
                         AND erased.artifact_id = artifact.artifact_id)
               FROM synthetic_lab_raw_artifacts AS artifact
               JOIN synthetic_lab_artifact_deks AS dek
                 ON dek.project_id = artifact.project_id AND dek.artifact_id = artifact.artifact_id
               JOIN synthetic_lab_artifact_deletion_outbox AS outbox
                 ON outbox.project_id = artifact.project_id AND outbox.artifact_id = artifact.artifact_id
               WHERE artifact.artifact_id = %s""",
            (artifact["artifact_id"],),
        ).fetchone()
    assert row == ("deletion_pending", "active", "pending", 0)


def _assert_object_deletion_retry(database_url: str, artifact: dict[str, object]) -> None:
    with psycopg.connect(database_url) as admin:
        row = admin.execute(
            """SELECT artifact.lifecycle_state, dek.status, outbox.status,
                      outbox.last_error_code,
                      (SELECT count(*) FROM synthetic_lab_artifact_crypto_erasures AS erased
                       WHERE erased.project_id = artifact.project_id
                         AND erased.artifact_id = artifact.artifact_id),
                      (SELECT count(*) FROM synthetic_lab_artifact_tombstones AS tombstone
                       WHERE tombstone.project_id = artifact.project_id
                         AND tombstone.artifact_id = artifact.artifact_id)
               FROM synthetic_lab_raw_artifacts AS artifact
               JOIN synthetic_lab_artifact_deks AS dek
                 ON dek.project_id = artifact.project_id AND dek.artifact_id = artifact.artifact_id
               JOIN synthetic_lab_artifact_deletion_outbox AS outbox
                 ON outbox.project_id = artifact.project_id AND outbox.artifact_id = artifact.artifact_id
               WHERE artifact.artifact_id = %s""",
            (artifact["artifact_id"],),
        ).fetchone()
    assert row == ("object_delete_pending", "destroyed", "failed", "runtimeerror", 1, 0)


def _assert_leased_artifact(database_url: str, artifact: dict[str, object]) -> None:
    with psycopg.connect(database_url) as admin:
        row = admin.execute(
            """SELECT artifact.lifecycle_state, dek.status, outbox.status,
                      (SELECT count(*) FROM synthetic_lab_artifact_crypto_erasures AS erased
                       WHERE erased.project_id = artifact.project_id
                         AND erased.artifact_id = artifact.artifact_id)
               FROM synthetic_lab_raw_artifacts AS artifact
               JOIN synthetic_lab_artifact_deks AS dek
                 ON dek.project_id = artifact.project_id AND dek.artifact_id = artifact.artifact_id
               JOIN synthetic_lab_artifact_deletion_outbox AS outbox
                 ON outbox.project_id = artifact.project_id AND outbox.artifact_id = artifact.artifact_id
               WHERE artifact.artifact_id = %s""",
            (artifact["artifact_id"],),
        ).fetchone()
    assert row == ("deletion_pending", "active", "leased", 0)


def _database_url(database_url: str, database_name: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(parsed._replace(path=f"/{database_name}"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
