from __future__ import annotations

import os
import threading
from unittest.mock import patch
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4
import unittest

from geno_core.durable_jobs import (
    KNOWLEDGE_JOB_TABLES,
    JobStateConflictError,
    LeaseClaim,
    LeaseFencedConnection,
    LostLeaseError,
    acknowledge_durable_cancel,
    claim_durable_job,
    complete_durable_job,
    durable_claim_candidate_sql,
    durable_job_spec,
    fail_durable_job,
    heartbeat_durable_job,
    next_fair_table_order,
    request_durable_cancel,
)


DATABASE_URL = os.getenv("GENO_DURABLE_JOB_TEST_DATABASE_URL", "").strip()


@unittest.skipUnless(DATABASE_URL, "GENO_DURABLE_JOB_TEST_DATABASE_URL is required")
class DurableJobLeasePostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import psycopg

        cls.psycopg = psycopg

    def setUp(self) -> None:
        self.connection = self.psycopg.connect(DATABASE_URL)
        self.tenant_id = uuid4()
        self.project_id = uuid4()
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)",
                (self.tenant_id, "Durable lease test", f"durable-{self.tenant_id}"),
            )
            cursor.execute(
                """
                INSERT INTO projects (
                  id, tenant_id, name, market_code, industry_code,
                  target_brand, category, prompt_version, status
                ) VALUES (%s, %s, 'Durable lease project', 'GLOBAL', 'test',
                          'LeaseTest', 'test', 'v1', 'active')
                """,
                (self.project_id, self.tenant_id),
            )
        self.connection.commit()

    def tearDown(self) -> None:
        self.connection.rollback()
        with self.connection.cursor() as cursor:
            cursor.execute("DELETE FROM tenants WHERE id = %s", (self.tenant_id,))
        self.connection.commit()
        self.connection.close()

    def _insert_import_job(
        self,
        *,
        status: str = "queued",
        worker_id: str | None = None,
        token: UUID | None = None,
        lease_expires_at: datetime | None = None,
        attempt_count: int = 0,
        max_attempts: int = 4,
    ) -> UUID:
        job_id = uuid4()
        active = status in {"running", "finalizing"}
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO knowledge_import_jobs (
                  id, project_id, source_mode, status, requested_by, source_config,
                  locked_by, locked_at, heartbeat_at, lease_token, lease_expires_at,
                  attempt_count, max_attempts, next_run_at, priority
                ) VALUES (%s, %s, 'pasted_text', %s, 'postgres-test', '{}'::jsonb,
                          %s, %s, %s, %s, %s, %s, %s, now() - interval '1 second', 10)
                """,
                (
                    job_id,
                    self.project_id,
                    status,
                    worker_id if active else None,
                    datetime.now(UTC) - timedelta(seconds=10) if active else None,
                    datetime.now(UTC) - timedelta(seconds=10) if active else None,
                    token if active else None,
                    lease_expires_at if active else None,
                    attempt_count,
                    max_attempts,
                ),
            )
        self.connection.commit()
        return job_id

    def test_fresh_claim_heartbeats_and_unexpired_active_is_not_claimed(self) -> None:
        job_id = self._insert_import_job()
        claim = claim_durable_job(
            self.connection,
            durable_job_spec("knowledge_import_jobs"),
            worker_id="fresh-owner",
            lease_seconds=30,
            mode="fresh",
        ).claim
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim.job_id, job_id)
        self.assertEqual(claim.attempt_count, 1)

        contender = self.psycopg.connect(DATABASE_URL)
        try:
            self.assertEqual(
                claim_durable_job(
                    contender,
                    durable_job_spec("knowledge_import_jobs"),
                    worker_id="fresh-contender",
                    lease_seconds=30,
                    mode="any",
                ).kind,
                "empty",
            )
        finally:
            contender.close()
        heartbeat = heartbeat_durable_job(self.connection, claim, lease_seconds=30)
        self.assertIsNone(heartbeat["cancel_requested_at"])
        completed = complete_durable_job(
            self.connection, claim, status="succeeded", result={"ok": True}
        )
        self.assertEqual(completed["status"], "succeeded")

    def test_runtime_app_maintenance_scope_can_claim_and_complete_under_force_rls(self) -> None:
        from geno_core.knowledge_pipeline import KnowledgePipelineRepository

        job_id = self._insert_import_job()
        runtime_url = DATABASE_URL.replace(
            "postgresql://geno:geno@", "postgresql://geno_runtime_app:geno_runtime_app@"
        )
        runtime_connection = self.psycopg.connect(runtime_url)
        runtime_repository = KnowledgePipelineRepository(runtime_connection)
        runtime_repository.set_maintenance_scope(worker_id="rls-worker")
        try:
            claim = runtime_repository.claim_job(
                "knowledge_import_jobs",
                worker_id="rls-worker",
                lease_seconds=30,
                mode="fresh",
            )
            self.assertIsNotNone(claim)
            assert claim is not None
            self.assertEqual(claim.job_id, job_id)
            completed = runtime_repository.complete_job(
                claim, status="succeeded", summary={"rls": "passed"}
            )
            self.assertEqual(completed["status"], "succeeded")
        finally:
            runtime_connection.close()

    def test_migration_rerun_preserves_new_protocol_active_owner(self) -> None:
        job_id = self._insert_import_job()
        claim = claim_durable_job(
            self.connection,
            durable_job_spec("knowledge_import_jobs"),
            worker_id="migration-rerun-owner",
            lease_seconds=30,
            mode="fresh",
        ).claim
        assert claim is not None
        migration = Path("infra/db/migrations/up/0029_durable_job_lease_recovery.sql").read_text(
            encoding="utf-8"
        )
        self.connection.execute(migration)
        self.connection.commit()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, locked_by, lease_token, attempt_count
                FROM knowledge_import_jobs WHERE id = %s
                """,
                (job_id,),
            )
            status, worker_id, token, attempt_count = cursor.fetchone()
        self.connection.commit()
        self.assertEqual(status, "running")
        self.assertEqual(worker_id, claim.worker_id)
        self.assertEqual(token, claim.lease_token)
        self.assertEqual(attempt_count, 1)
        complete_durable_job(self.connection, claim, status="succeeded")

    def test_two_connections_reclaim_one_expired_row_and_old_token_is_fenced(self) -> None:
        old_token = uuid4()
        old_expiry = datetime.now(UTC) - timedelta(seconds=5)
        job_id = self._insert_import_job(
            status="running",
            worker_id="old-owner",
            token=old_token,
            lease_expires_at=old_expiry,
            attempt_count=1,
        )
        old_claim = LeaseClaim(
            spec=durable_job_spec("knowledge_import_jobs"),
            job_id=job_id,
            project_id=self.project_id,
            worker_id="old-owner",
            lease_token=old_token,
            lease_expires_at=old_expiry,
            claimed_from="queued",
            attempt_count=1,
            reclaimed=False,
            record={"id": job_id, "project_id": self.project_id},
        )
        barrier = threading.Barrier(2)
        outcomes: list[object] = []
        errors: list[BaseException] = []

        def reclaim(worker_id: str) -> None:
            connection = self.psycopg.connect(DATABASE_URL)
            try:
                barrier.wait(timeout=5)
                outcomes.append(
                    claim_durable_job(
                        connection,
                        durable_job_spec("knowledge_import_jobs"),
                        worker_id=worker_id,
                        lease_seconds=30,
                        mode="recovery",
                    )
                )
            except BaseException as exc:
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=reclaim, args=(f"new-owner-{index}",)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(errors)
        claimed = [outcome.claim for outcome in outcomes if getattr(outcome, "claim", None)]
        self.assertEqual(len(claimed), 1)
        new_claim = claimed[0]
        self.assertNotEqual(new_claim.lease_token, old_token)
        self.assertEqual(new_claim.attempt_count, 2)
        self.assertTrue(new_claim.reclaimed)

        for stale_operation in (
            lambda: heartbeat_durable_job(self.connection, old_claim, lease_seconds=30),
            lambda: complete_durable_job(self.connection, old_claim, status="succeeded"),
            lambda: fail_durable_job(
                self.connection,
                old_claim,
                error_code="stale",
                error_message="stale",
                retryable=True,
            ),
        ):
            with self.assertRaises(LostLeaseError):
                stale_operation()
        complete_durable_job(self.connection, new_claim, status="succeeded")

    def test_stale_knowledge_owner_cannot_commit_business_write_after_reclaim(self) -> None:
        job_id = self._insert_import_job()
        owner_connection = self.psycopg.connect(DATABASE_URL)
        reclaimer_connection = self.psycopg.connect(DATABASE_URL)
        check_connection = self.psycopg.connect(DATABASE_URL)
        asset_id = uuid4()
        try:
            old_claim = claim_durable_job(
                owner_connection,
                durable_job_spec("knowledge_import_jobs"),
                worker_id="knowledge-old-owner",
                lease_seconds=30,
                mode="fresh",
            ).claim
            assert old_claim is not None
            fenced = LeaseFencedConnection(owner_connection, old_claim, lease_seconds=30)
            with fenced.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO knowledge_source_assets (
                      id, project_id, asset_type, status,
                      title, content_hash, created_by
                    ) VALUES (%s, %s, 'pasted_text', 'processed',
                              'stale result', 'stale-result', 'knowledge-old-owner')
                    """,
                    (asset_id, self.project_id),
                )

            with reclaimer_connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE knowledge_import_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
                    (job_id,),
                )
            reclaimer_connection.commit()
            new_claim = claim_durable_job(
                reclaimer_connection,
                durable_job_spec("knowledge_import_jobs"),
                worker_id="knowledge-new-owner",
                lease_seconds=30,
                mode="recovery",
            ).claim
            assert new_claim is not None

            with self.assertRaises(LostLeaseError):
                fenced.commit()
            with check_connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM knowledge_source_assets WHERE id = %s", (asset_id,))
                self.assertEqual(cursor.fetchone()[0], 0)
            check_connection.commit()
            complete_durable_job(reclaimer_connection, new_claim, status="succeeded")
        finally:
            owner_connection.close()
            reclaimer_connection.close()
            check_connection.close()

    def test_stale_collection_child_cannot_commit_business_write_after_reclaim(self) -> None:
        job_id = uuid4()
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO collection_jobs (id, project_id, requested_by) VALUES (%s, %s, 'postgres-test')",
                (job_id, self.project_id),
            )
        self.connection.commit()
        owner_connection = self.psycopg.connect(DATABASE_URL)
        reclaimer_connection = self.psycopg.connect(DATABASE_URL)
        check_connection = self.psycopg.connect(DATABASE_URL)
        summary_id = uuid4()
        try:
            old_claim = claim_durable_job(
                owner_connection,
                durable_job_spec("collection_jobs"),
                worker_id="collection-old-owner",
                lease_seconds=30,
                mode="fresh",
            ).claim
            assert old_claim is not None
            fenced = LeaseFencedConnection(owner_connection, old_claim, lease_seconds=30)
            with fenced.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO collection_run_summaries (
                      id, project_id, run_type, mode, started_at, completed_at
                    ) VALUES (%s, %s, 'durable-test', 'api', now(), now())
                    """,
                    (summary_id, self.project_id),
                )

            with reclaimer_connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE collection_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
                    (job_id,),
                )
            reclaimer_connection.commit()
            new_claim = claim_durable_job(
                reclaimer_connection,
                durable_job_spec("collection_jobs"),
                worker_id="collection-new-owner",
                lease_seconds=30,
                mode="recovery",
            ).claim
            assert new_claim is not None

            with self.assertRaises(LostLeaseError):
                fenced.commit()
            with check_connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM collection_run_summaries WHERE id = %s", (summary_id,))
                self.assertEqual(cursor.fetchone()[0], 0)
            check_connection.commit()
            complete_durable_job(reclaimer_connection, new_claim, status="succeeded")
        finally:
            owner_connection.close()
            reclaimer_connection.close()
            check_connection.close()

    def test_after_business_crash_rolls_back_and_recovery_commits_result_atomically(self) -> None:
        job_id = self._insert_import_job()
        asset_id = uuid4()
        crashed_connection = self.psycopg.connect(DATABASE_URL)
        old_claim = claim_durable_job(
            crashed_connection,
            durable_job_spec("knowledge_import_jobs"),
            worker_id="atomic-old-owner",
            lease_seconds=30,
            mode="fresh",
        ).claim
        assert old_claim is not None
        crashed = LeaseFencedConnection(crashed_connection, old_claim, lease_seconds=30)
        crashed.defer_commits_until_terminal()
        with crashed.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO knowledge_source_assets (
                  id, project_id, import_job_id, asset_type, status,
                  title, content_hash, created_by
                ) VALUES (%s, %s, %s, 'pasted_text', 'processed',
                          'atomic result', 'atomic-result', 'atomic-old-owner')
                """,
                (asset_id, self.project_id, job_id),
            )
        crashed.commit()
        observer = self.psycopg.connect(DATABASE_URL)
        try:
            with observer.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM knowledge_source_assets WHERE id = %s", (asset_id,))
                self.assertEqual(cursor.fetchone()[0], 0)
            observer.commit()
        finally:
            observer.close()

        # Closing the process-owned connection models a kill after handler
        # business code but before the terminal CAS/commit.
        crashed_connection.close()
        with self.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE knowledge_import_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
                (job_id,),
            )
        self.connection.commit()

        recovery_connection = self.psycopg.connect(DATABASE_URL)
        observer = self.psycopg.connect(DATABASE_URL)
        try:
            recovered = claim_durable_job(
                recovery_connection,
                durable_job_spec("knowledge_import_jobs"),
                worker_id="atomic-new-owner",
                lease_seconds=30,
                mode="recovery",
            ).claim
            assert recovered is not None
            fenced = LeaseFencedConnection(recovery_connection, recovered, lease_seconds=30)
            fenced.defer_commits_until_terminal()
            with fenced.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO knowledge_source_assets (
                      id, project_id, import_job_id, asset_type, status,
                      title, content_hash, created_by
                    ) VALUES (%s, %s, %s, 'pasted_text', 'processed',
                              'atomic result', 'atomic-result', 'atomic-new-owner')
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (asset_id, self.project_id, job_id),
                )
            completed = fenced.complete(
                status="succeeded", result={"asset_ids": [str(asset_id)]}
            )
            self.assertEqual(completed["status"], "succeeded")
            with observer.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT job.status, job.result_summary, count(asset.id)
                    FROM knowledge_import_jobs AS job
                    LEFT JOIN knowledge_source_assets AS asset ON asset.id = %s
                    WHERE job.id = %s
                    GROUP BY job.status, job.result_summary
                    """,
                    (asset_id, job_id),
                )
                status, result_summary, asset_count = cursor.fetchone()
            observer.commit()
            self.assertEqual(status, "succeeded")
            self.assertEqual(result_summary["asset_ids"], [str(asset_id)])
            self.assertEqual(asset_count, 1)
        finally:
            recovery_connection.close()
            observer.close()

    def test_repository_fence_context_does_not_fence_again_after_terminal_commit(self) -> None:
        from geno_core.knowledge_pipeline import KnowledgePipelineRepository

        job_id = self._insert_import_job()
        repository = KnowledgePipelineRepository(self.connection, database_url=DATABASE_URL)
        claim = repository.claim_job(
            "knowledge_import_jobs",
            worker_id="context-terminal-owner",
            lease_seconds=30,
            mode="fresh",
        )
        assert claim is not None
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(sum(metric_value), 0)
                FROM durable_job_metric_counters
                WHERE job_type = 'knowledge_import_jobs'
                  AND metric_name IN ('lease_lost', 'stale_completion')
                """
            )
            loss_count_before = cursor.fetchone()[0]
        self.connection.commit()
        with repository.fence_job_commits(claim, lease_seconds=30) as fenced:
            fenced.defer_commits_until_terminal()
            completed = fenced.complete(status="succeeded", result={"context": "atomic"})
            self.assertEqual(completed["status"], "succeeded")
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, result_summary FROM knowledge_import_jobs WHERE id = %s",
                (job_id,),
            )
            status, result = cursor.fetchone()
            cursor.execute(
                """
                SELECT COALESCE(sum(metric_value), 0)
                FROM durable_job_metric_counters
                WHERE job_type = 'knowledge_import_jobs'
                  AND metric_name IN ('lease_lost', 'stale_completion')
                """
            )
            false_loss_count = cursor.fetchone()[0]
        self.connection.commit()
        self.assertEqual(status, "succeeded")
        self.assertEqual(result, {"context": "atomic"})
        self.assertEqual(false_loss_count, loss_count_before)

    def test_collection_provider_advisory_slot_releases_with_owner_connection(self) -> None:
        from workers.task_queue.tasks import _collection_rate_limit_context

        environment = {
            "DATABASE_URL": DATABASE_URL,
            "GENO_COLLECTION_PROVIDER_CONCURRENCY": "1",
            "GENO_COLLECTION_TEST_BYPASS_RATE_LIMIT": "",
        }
        with patch.dict(os.environ, environment, clear=False):
            with _collection_rate_limit_context() as first:
                self.assertTrue(first)
                with _collection_rate_limit_context() as contender:
                    self.assertFalse(contender)
            with _collection_rate_limit_context() as after_release:
                self.assertTrue(after_release)

    def test_expired_finalizing_keeps_state_and_attempt_exhaustion_dead_letters(self) -> None:
        from geno_core.knowledge_pipeline import KnowledgePipelineRepository
        from workers.knowledge_worker.run_knowledge_pipeline import _process_claim

        finalizing_id = self._insert_import_job(max_attempts=1)
        original = claim_durable_job(
            self.connection,
            durable_job_spec("knowledge_import_jobs"),
            worker_id="finalizer-old",
            lease_seconds=30,
            mode="fresh",
        ).claim
        assert original is not None
        original_fenced = LeaseFencedConnection(self.connection, original, lease_seconds=30)
        original_fenced.defer_commits_until_terminal()
        descriptor = {
            "descriptor_version": "durable_artifact_finalize_v1",
            "terminal_status": "succeeded",
            "result": {"artifact_ids": ["stable-artifact"]},
        }
        promoted = original_fenced.begin_finalizing(descriptor=descriptor)
        self.assertEqual(promoted["status"], "finalizing")
        self.assertEqual(promoted["finalize_descriptor"], descriptor)
        with self.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE knowledge_import_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
                (finalizing_id,),
            )
        self.connection.commit()
        finalizing = claim_durable_job(
            self.connection,
            durable_job_spec("knowledge_import_jobs"),
            worker_id="finalizer-new",
            lease_seconds=30,
            mode="recovery",
        ).claim
        self.assertIsNotNone(finalizing)
        assert finalizing is not None
        self.assertEqual(finalizing.job_id, finalizing_id)
        self.assertEqual(finalizing.record["status"], "finalizing")
        self.assertEqual(finalizing.claimed_from, "finalizing")
        self.assertEqual(finalizing.record["finalize_descriptor"], descriptor)
        self.assertEqual(finalizing.attempt_count, 1)

        class HealthyGuard:
            cancel_requested = False

            def start(self):
                return self

            def stop(self) -> None:
                return None

            def raise_if_stopped(self) -> None:
                return None

        repository = KnowledgePipelineRepository(self.connection, database_url=DATABASE_URL)
        with patch(
            "workers.knowledge_worker.run_knowledge_pipeline._process_job",
            side_effect=AssertionError("descriptor recovery must not execute handler/provider"),
        ):
            recovered = _process_claim(
                repository,
                finalizing,
                lease_seconds=30,
                guard=HealthyGuard(),
            )
        self.assertEqual(recovered["status"], "succeeded")
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, attempt_count, result_summary FROM knowledge_import_jobs WHERE id = %s",
                (finalizing_id,),
            )
            status, attempt_count, result_summary = cursor.fetchone()
        self.connection.commit()
        self.assertEqual(status, "succeeded")
        self.assertEqual(attempt_count, 1)
        self.assertEqual(result_summary, descriptor["result"])

        invalid_finalizing_id = self._insert_import_job(
            status="finalizing",
            worker_id="invalid-finalizer",
            token=uuid4(),
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=2),
            attempt_count=1,
        )
        invalid = claim_durable_job(
            self.connection,
            durable_job_spec("knowledge_import_jobs"),
            worker_id="invalid-finalizer-reaper",
            lease_seconds=30,
            mode="recovery",
        )
        self.assertEqual(invalid.kind, "dead_lettered")
        self.assertEqual(invalid.job_id, invalid_finalizing_id)
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT last_error_code FROM knowledge_import_jobs WHERE id = %s",
                (invalid_finalizing_id,),
            )
            self.assertEqual(cursor.fetchone()[0], "invalid_finalize_descriptor")
        self.connection.commit()

        exhausted_id = self._insert_import_job(
            status="running",
            worker_id="exhausted-owner",
            token=uuid4(),
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=2),
            attempt_count=3,
            max_attempts=3,
        )
        exhausted = claim_durable_job(
            self.connection,
            durable_job_spec("knowledge_import_jobs"),
            worker_id="reaper",
            lease_seconds=30,
            mode="recovery",
        )
        self.assertEqual(exhausted.kind, "dead_lettered")
        self.assertEqual(exhausted.job_id, exhausted_id)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT metric_value FROM durable_job_metric_counters
                WHERE queue_name = 'knowledge'
                  AND job_type = 'knowledge_import_jobs'
                  AND metric_name = 'dead_lettered'
                """
            )
            self.assertGreaterEqual(cursor.fetchone()[0], 2)
        self.connection.commit()

    def test_cancel_and_complete_race_has_one_terminal_winner(self) -> None:
        job_id = self._insert_import_job()
        claim = claim_durable_job(
            self.connection,
            durable_job_spec("knowledge_import_jobs"),
            worker_id="race-owner",
            lease_seconds=30,
            mode="fresh",
        ).claim
        assert claim is not None
        barrier = threading.Barrier(2)
        results: list[str] = []

        def cancel() -> None:
            connection = self.psycopg.connect(DATABASE_URL)
            try:
                barrier.wait(timeout=5)
                request_durable_cancel(
                    connection,
                    durable_job_spec("knowledge_import_jobs"),
                    project_id=self.project_id,
                    job_id=job_id,
                )
                results.append("cancel_requested")
            except JobStateConflictError:
                results.append("cancel_conflict")
            finally:
                connection.close()

        def complete() -> None:
            connection = self.psycopg.connect(DATABASE_URL)
            try:
                barrier.wait(timeout=5)
                complete_durable_job(connection, claim, status="succeeded")
                results.append("completed")
            except LostLeaseError:
                results.append("completion_fenced")
            finally:
                connection.close()

        threads = [threading.Thread(target=cancel), threading.Thread(target=complete)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        if "cancel_requested" in results:
            acknowledge_durable_cancel(self.connection, claim)
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT status FROM knowledge_import_jobs WHERE id = %s", (job_id,))
            status = cursor.fetchone()[0]
        self.connection.commit()
        self.assertIn(status, {"succeeded", "cancelled"})
        self.assertNotEqual(results.count("completed"), results.count("cancel_requested"))

    def test_collection_heartbeat_returns_cancel_and_completion_is_fenced(self) -> None:
        collection_id = uuid4()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO collection_jobs (id, project_id, requested_by)
                VALUES (%s, %s, 'postgres-test')
                """,
                (collection_id, self.project_id),
            )
        self.connection.commit()
        claim = claim_durable_job(
            self.connection,
            durable_job_spec("collection_jobs"),
            worker_id="collection-owner",
            lease_seconds=30,
            mode="fresh",
        ).claim
        assert claim is not None
        cancelling = self.psycopg.connect(DATABASE_URL)
        try:
            requested = request_durable_cancel(
                cancelling,
                durable_job_spec("collection_jobs"),
                project_id=self.project_id,
                job_id=collection_id,
            )
            self.assertEqual(requested["status"], "running")
        finally:
            cancelling.close()
        heartbeat = heartbeat_durable_job(self.connection, claim, lease_seconds=30)
        self.assertIsNotNone(heartbeat["cancel_requested_at"])
        with self.assertRaises(LostLeaseError):
            complete_durable_job(self.connection, claim, status="succeeded", result={})
        cancelled = acknowledge_durable_cancel(self.connection, claim)
        self.assertEqual(cancelled["status"], "cancelled")

    def test_persisted_round_robin_cursor_rotates(self) -> None:
        tables = (
            "knowledge_import_jobs",
            "crawl_jobs",
            "knowledge_parser_runs",
        )
        first = next_fair_table_order(
            self.connection,
            queue_name="knowledge_fresh",
            tables=tables,
            worker_id="cursor-worker",
        )
        second = next_fair_table_order(
            self.connection,
            queue_name="knowledge_fresh",
            tables=tables,
            worker_id="cursor-worker",
        )
        self.assertEqual(second, first[1:] + first[:1])

    def test_later_table_expired_job_is_reclaimed_before_limited_fresh_backlog(self) -> None:
        for _ in range(5):
            self._insert_import_job()
        content_id = uuid4()
        old_token = uuid4()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO content_generation_jobs (
                  id, project_id, status, locked_by, locked_at, heartbeat_at,
                  lease_token, lease_expires_at, attempt_count, max_attempts
                ) VALUES (%s, %s, 'running', 'late-old-owner', now() - interval '10 seconds',
                          now() - interval '10 seconds', %s, now() - interval '2 seconds', 1, 4)
                """,
                (content_id, self.project_id, old_token),
            )
        self.connection.commit()

        recovered = []
        for table in next_fair_table_order(
            self.connection,
            queue_name="knowledge_recovery",
            tables=KNOWLEDGE_JOB_TABLES,
            worker_id="fair-worker",
        ):
            outcome = claim_durable_job(
                self.connection,
                durable_job_spec(table),
                worker_id="fair-worker",
                lease_seconds=30,
                mode="recovery",
            )
            if outcome.claim is not None:
                recovered.append(outcome.claim)
        self.assertEqual([claim.job_id for claim in recovered], [content_id])
        self.assertNotEqual(recovered[0].lease_token, old_token)

        fresh = None
        for table in next_fair_table_order(
            self.connection,
            queue_name="knowledge_fresh",
            tables=KNOWLEDGE_JOB_TABLES,
            worker_id="fair-worker",
        ):
            outcome = claim_durable_job(
                self.connection,
                durable_job_spec(table),
                worker_id="fair-worker",
                lease_seconds=30,
                mode="fresh",
            )
            if outcome.claim is not None:
                fresh = outcome.claim
                break
        self.assertIsNotNone(fresh)
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM knowledge_import_jobs WHERE project_id = %s AND status = 'queued'",
                (self.project_id,),
            )
            queued_backlog = cursor.fetchone()[0]
        self.connection.commit()
        self.assertEqual(queued_backlog, 4)
        complete_durable_job(self.connection, recovered[0], status="succeeded")
        assert fresh is not None
        complete_durable_job(self.connection, fresh, status="succeeded")

    def test_upgrade_normalizes_legacy_content_partial_only_with_persisted_draft(self) -> None:
        with_draft = uuid4()
        without_draft = uuid4()
        with self.connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE content_generation_jobs DROP CONSTRAINT content_generation_jobs_status_check"
            )
            cursor.execute(
                """
                INSERT INTO content_generation_jobs (id, project_id, status)
                VALUES (%s, %s, 'partial_succeeded'), (%s, %s, 'partial_succeeded')
                """,
                (with_draft, self.project_id, without_draft, self.project_id),
            )
            cursor.execute(
                """
                INSERT INTO content_drafts (
                  project_id, title, content_type, content_template_id, target_city,
                  target_platform, target_source_type, draft_markdown, review_status,
                  created_by, content_generation_job_id
                ) VALUES (%s, 'persisted', 'faq', 'test', 'Global', 'chatgpt',
                          'knowledge', '# persisted', 'pending_review', 'postgres-test', %s)
                """,
                (self.project_id, with_draft),
            )
        self.connection.commit()
        migration = Path("infra/db/migrations/up/0029_durable_job_lease_recovery.sql").read_text(
            encoding="utf-8"
        )
        self.connection.execute(migration)
        self.connection.commit()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, status, last_error_code
                FROM content_generation_jobs
                WHERE id IN (%s, %s)
                ORDER BY id
                """,
                (with_draft, without_draft),
            )
            rows = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
        self.connection.commit()
        self.assertEqual(rows[with_draft][0], "succeeded")
        self.assertEqual(rows[without_draft], ("failed", "legacy_partial_without_persisted_draft"))

    def test_claim_execution_plans_use_fresh_and_expired_partial_indexes(self) -> None:
        self._insert_import_job()
        self._insert_import_job(
            status="running",
            worker_id="expired-index-owner",
            token=uuid4(),
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=3),
            attempt_count=1,
        )
        spec = durable_job_spec("knowledge_import_jobs")
        queries = {
            "idx_knowledge_import_jobs_durable_fresh": durable_claim_candidate_sql(
                spec, mode="fresh"
            ),
            "idx_knowledge_import_jobs_durable_expired": durable_claim_candidate_sql(
                spec, mode="recovery"
            ),
        }
        with self.connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan = off")
            for index_name, query in queries.items():
                cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}")
                plan = cursor.fetchone()[0]
                self.assertIn(index_name, str(plan))
        self.connection.rollback()


if __name__ == "__main__":
    unittest.main()
