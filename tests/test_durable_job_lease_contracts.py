from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4
import unittest

from geno_core.durable_jobs import (
    DURABLE_JOB_SPECS,
    KNOWLEDGE_JOB_TABLES,
    LeaseClaim,
    durable_claim_candidate_sql,
    durable_job_spec,
    internal_lease_environment,
    lease_claim_from_internal_environment,
)
from workers.knowledge_worker.run_knowledge_pipeline import _knowledge_terminal_status
from workers.task_queue.tasks import _run_collection_subprocess


ROOT = Path(__file__).resolve().parents[1]


class DurableJobLeaseContractsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.migration = (ROOT / "infra/db/migrations/up/0029_durable_job_lease_recovery.sql").read_text(
            encoding="utf-8"
        )
        self.rollback = (
            ROOT / "infra/db/migrations/down/0029_durable_job_lease_recovery.down.sql"
        ).read_text(encoding="utf-8")

    def test_static_allowlist_covers_only_eight_knowledge_tables_and_collection(self) -> None:
        self.assertEqual(len(KNOWLEDGE_JOB_TABLES), 8)
        self.assertEqual(set(DURABLE_JOB_SPECS), {*KNOWLEDGE_JOB_TABLES, "collection_jobs"})
        self.assertNotIn("knowledge_pipeline_runs", DURABLE_JOB_SPECS)
        with self.assertRaisesRegex(ValueError, "unsupported durable job table"):
            durable_job_spec("jobs; DROP TABLE projects")

    def test_migration_preserves_per_table_states_and_content_is_single_asset(self) -> None:
        expected_status_fragments = {
            "knowledge_import_jobs": ("'draft'", "'ready'", "'partial_succeeded'"),
            "knowledge_parser_runs": ("'fallback_succeeded'", "'partial_succeeded'"),
            "collection_jobs": ("'partial_succeeded'", "'finalizing'"),
        }
        for table, statuses in expected_status_fragments.items():
            start = self.migration.index(f"ADD CONSTRAINT {table}_status_check")
            contract = self.migration[start : self.migration.index(";", start)]
            for status in statuses:
                self.assertIn(status, contract)
            self.assertIn("'retry_wait'", contract)
            self.assertIn("'dead_letter'", contract)

        content_start = self.migration.index(
            "ADD CONSTRAINT content_generation_jobs_status_check"
        )
        content_contract = self.migration[
            content_start : self.migration.index(";", content_start)
        ]
        self.assertNotIn("partial_succeeded", content_contract)
        self.assertEqual(
            _knowledge_terminal_status("content_generation_jobs", {"blocked": True}),
            "succeeded",
        )

    def test_legacy_content_partial_normalization_requires_a_persisted_draft(self) -> None:
        normalization_start = self.migration.index("UPDATE content_generation_jobs AS job")
        normalization = self.migration[
            normalization_start : self.migration.index("WHERE status = 'partial_succeeded';", normalization_start)
        ]
        self.assertIn("FROM content_drafts AS draft", normalization)
        self.assertIn("draft.content_generation_job_id = job.id", normalization)
        self.assertIn("THEN 'succeeded'", normalization)
        self.assertIn("ELSE 'failed'", normalization)
        self.assertIn("legacy_partial_without_persisted_draft", normalization)

    def test_rerun_normalizes_only_legacy_active_rows_without_tokens(self) -> None:
        self.assertEqual(
            self.migration.count(
                "WHERE status IN ('running', 'finalizing') AND lease_token IS NULL;"
            ),
            9,
        )
        self.assertIn("'stale_completion', 'cancelled', 'dead_lettered'", self.migration)
        self.assertIn(
            "DROP CONSTRAINT IF EXISTS durable_job_metric_counters_metric_name_check",
            self.migration,
        )
        self.assertIn("DROP TABLE IF EXISTS durable_job_metric_counters", self.rollback)

    def test_every_table_has_active_lease_check_and_matching_partial_indexes(self) -> None:
        for table, spec in DURABLE_JOB_SPECS.items():
            self.assertIn(f"{table}_active_lease_check", self.migration)
            self.assertIn(f"{table}_durable_fresh", self.migration)
            self.assertIn(f"{table}_durable_expired", self.migration)
            schedule = spec.schedule_column
            self.assertIn(f"ON {table}({schedule}", self.migration)
            fresh_line = next(
                line
                for line in self.migration.splitlines()
                if line.startswith("CREATE INDEX") and f"{table}_durable_fresh" in line
            )
            expired_line = next(
                line
                for line in self.migration.splitlines()
                if line.startswith("CREATE INDEX") and f"{table}_durable_expired" in line
            )
            self.assertIn("cancel_requested_at IS NULL", fresh_line)
            self.assertIn("cancel_requested_at IS NULL", expired_line)
            self.assertNotIn("now()", fresh_line)
            self.assertNotIn("now()", expired_line)

    def test_down_migration_rejects_active_token_owner_before_mapping_statuses(self) -> None:
        rejection = self.rollback.index("cannot roll back durable leases")
        mapping = self.rollback.index("UPDATE knowledge_import_jobs SET status")
        drop_columns = self.rollback.index("DROP COLUMN IF EXISTS lease_token")
        self.assertLess(rejection, mapping)
        self.assertLess(mapping, drop_columns)

    def test_claim_token_is_redacted_from_repr_and_handler_payload(self) -> None:
        token = uuid4()
        claim = LeaseClaim(
            spec=durable_job_spec("knowledge_import_jobs"),
            job_id=uuid4(),
            project_id=uuid4(),
            worker_id="worker-a",
            lease_token=token,
            lease_expires_at=datetime.now(UTC),
            claimed_from="queued",
            attempt_count=1,
            reclaimed=False,
            record={"id": uuid4(), "lease_token": token, "source_mode": "file"},
        )
        self.assertNotIn(str(token), repr(claim))
        self.assertNotIn("lease_token", claim.worker_payload())
        self.assertEqual(len(claim.token_fingerprint), 16)

    def test_collection_child_parses_then_removes_internal_token_environment(self) -> None:
        claim = LeaseClaim(
            spec=durable_job_spec("collection_jobs"),
            job_id=uuid4(),
            project_id=uuid4(),
            worker_id="parent-owner",
            lease_token=uuid4(),
            lease_expires_at=datetime.now(UTC),
            claimed_from="queued",
            attempt_count=2,
            reclaimed=True,
            record={},
        )
        environment = internal_lease_environment(claim, lease_seconds=30)
        with patch.dict(os.environ, environment, clear=False):
            parsed = lease_claim_from_internal_environment()
            self.assertIsNotNone(parsed)
            self.assertNotIn("GENO_INTERNAL_DURABLE_LEASE_TOKEN", os.environ)
            self.assertFalse(
                any(key.startswith("GENO_INTERNAL_DURABLE_") for key in os.environ)
            )
        assert parsed is not None
        self.assertEqual(parsed[0].lease_token, claim.lease_token)

    def test_worker_uses_expired_first_fair_pass_and_terminable_popen(self) -> None:
        knowledge_worker = (
            ROOT / "workers/knowledge_worker/run_knowledge_pipeline.py"
        ).read_text(encoding="utf-8")
        task_worker = (ROOT / "workers/task_queue/tasks.py").read_text(encoding="utf-8")
        repository = (
            ROOT / "packages/geno_core/geno_core/knowledge_pipeline.py"
        ).read_text(encoding="utf-8")
        self.assertLess(
            knowledge_worker.index('queue_name="knowledge_recovery"'),
            knowledge_worker.index('queue_name="knowledge_fresh"'),
        )
        self.assertIn('mode="recovery"', knowledge_worker)
        self.assertIn("for table in recovery_order", knowledge_worker)
        self.assertIn("FOR UPDATE SKIP LOCKED", (ROOT / "packages/geno_core/geno_core/durable_jobs.py").read_text(encoding="utf-8"))
        self.assertIn("status = 'queued'", repository[repository.index("def run_ready_pipeline_once") :])
        self.assertIn("subprocess.Popen", task_worker)
        self.assertIn("process.terminate()", task_worker)
        self.assertIn("process.kill()", task_worker)
        self.assertNotIn("ConcurrentRateLimiter", task_worker)
        self.assertNotIn("ttl=3_900_000", task_worker)
        collection_actor = task_worker[
            task_worker.index("def process_collection_queue") : task_worker.index("def process_knowledge_queue")
        ]
        self.assertNotIn("subprocess.run", collection_actor)
        self.assertLess(
            collection_actor.index("_collection_rate_limit_context()"),
            collection_actor.index("store.claim_next_outcome"),
        )
        self.assertIn('"status": "capacity_busy", "processed": False', collection_actor)
        self.assertLess(
            collection_actor.index("store.begin_finalizing"),
            collection_actor.rindex("store.complete"),
        )
        self.assertIn("descriptor_only_recovery", collection_actor)

    def test_production_claim_sql_matches_index_order(self) -> None:
        knowledge = durable_job_spec("knowledge_import_jobs")
        fresh = durable_claim_candidate_sql(knowledge, mode="fresh")
        recovery = durable_claim_candidate_sql(knowledge, mode="recovery")
        collection = durable_claim_candidate_sql(
            durable_job_spec("collection_jobs"), mode="fresh"
        )
        self.assertIn(
            "ORDER BY next_run_at ASC, priority DESC, created_at ASC", fresh
        )
        self.assertIn(
            "ORDER BY lease_expires_at ASC, priority DESC, created_at ASC", recovery
        )
        self.assertIn("ORDER BY next_attempt_at ASC, created_at ASC", collection)
        self.assertIn("cancel_requested_at IS NULL", fresh)
        self.assertIn("FOR UPDATE SKIP LOCKED", recovery)

    def test_lease_token_is_not_selected_by_collection_public_contract(self) -> None:
        collection = (
            ROOT / "packages/geno_core/geno_core/collection_jobs.py"
        ).read_text(encoding="utf-8")
        columns = collection[
            collection.index("COLLECTION_JOB_COLUMNS") : collection.index("def _row")
        ]
        self.assertNotIn('"lease_token"', columns)
        self.assertIn('public.pop("lease_token", None)', (
            ROOT / "packages/geno_core/geno_core/knowledge_pipeline.py"
        ).read_text(encoding="utf-8"))

    def test_verifier_classifies_configuration_only_runs_as_non_production_evidence(self) -> None:
        verifier = (ROOT / "scripts/verify_durable_job_lease_recovery.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"production_evidence" if args.run_actor_kill_tests', verifier)
        self.assertIn('"status": "failed" if failure else "passed" if args.run_actor_kill_tests else "configuration_only"', verifier)
        self.assertIn('"satisfied": bool(args.run_actor_kill_tests and failure is None)', verifier)
        self.assertGreaterEqual(verifier.count('"--no-deps"'), 3)
        self.assertIn('"name": "seed_cleanup"', verifier)

    @unittest.skipUnless(os.name == "posix", "process-group cleanup is POSIX-specific")
    def test_collection_timeout_kills_descendant_process_group(self) -> None:
        class HealthyGuard:
            def raise_if_stopped(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "descendant.pid"
            child_code = (
                "import signal,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(60)"
            )
            parent_code = (
                "import pathlib,subprocess,sys,time; "
                f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
                f"pathlib.Path({str(pid_path)!r}).write_text(str(child.pid)); "
                "time.sleep(60)"
            )
            with self.assertRaises(subprocess.TimeoutExpired):
                _run_collection_subprocess(
                    [sys.executable, "-c", parent_code],
                    guard=HealthyGuard(),
                    timeout_seconds=1,
                    terminate_grace_seconds=0.2,
                )
            descendant_pid = int(pid_path.read_text(encoding="utf-8"))

            def descendant_alive() -> bool:
                stat_path = Path(f"/proc/{descendant_pid}/stat")
                if not stat_path.exists():
                    return False
                try:
                    return stat_path.read_text(encoding="utf-8").split()[2] != "Z"
                except (FileNotFoundError, IndexError):
                    return False

            deadline = time.monotonic() + 5
            while descendant_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(descendant_alive())


if __name__ == "__main__":
    unittest.main()
