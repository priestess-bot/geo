from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from unittest.mock import patch


class FakeWorkerRepository:
    def __init__(self) -> None:
        self.saved_score_snapshots = 0
        self.saved_reports = 0
        self.saved_raw_evidence_records = 0
        self.saved_collection_summaries = 0

    def save_project_bootstrap(self, bootstrap: object) -> None:
        self.bootstrap = bootstrap

    def save_raw_evidence_records(self, records: tuple[object, ...]) -> None:
        self.saved_raw_evidence_records += len(records)

    def save_collection_failure_records(self, records: tuple[object, ...]) -> None:
        self.saved_collection_failures = len(records)

    def save_collection_run_summary(self, summary: object, audit_event: object) -> None:
        self.saved_collection_summaries += 1

    def get_confirmed_entity_alias_terms(self, project_id: str) -> dict[str, tuple[str, ...]]:
        return {}

    def get_score_weights_snapshot(self, *, project_id: str, formula_version: str) -> None:
        return None

    def save_answer_analyses(self, analyses: tuple[object, ...]) -> None:
        self.saved_answer_analyses = len(analyses)

    def save_score_snapshot(self, snapshot: object, contributions: tuple[object, ...], audit_event: object) -> None:
        self.saved_score_snapshots += 1

    def save_citation_graph(self, project_id: str, graph: object) -> None:
        self.saved_citation_graph = graph

    def save_report_export(self, report_export: object, audit_event: object) -> None:
        self.saved_reports += 1

    def save_fidelity_check(self, fidelity_check: object, audit_event: object) -> None:
        self.saved_fidelity_check = fidelity_check

    def save_audit_events(self, events: tuple[object, ...]) -> None:
        self.saved_audit_events = len(events)

    def save_action_plan(
        self,
        *,
        actions: tuple[object, ...],
        schedule: object,
        comparison: object,
        audit_events: tuple[object, ...],
    ) -> None:
        self.saved_action_plan = len(actions)

    def save_content_engine(
        self,
        *,
        facts: tuple[object, ...],
        drafts: tuple[object, ...],
        connectors: tuple[object, ...],
        distribution_records: tuple[object, ...],
        audit_event: object,
    ) -> None:
        self.saved_content_engine = len(drafts)

    def save_traceability_bundle(self, bundle: object) -> None:
        self.saved_traceability_bundle = bundle


class WorkerCliTest(unittest.TestCase):
    def _run_worker_result(
        self,
        *args: str,
        unset_env: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for key in unset_env:
            env.pop(key, None)
        env["PYTHONPATH"] = "packages/geno_core:apps/api"
        return subprocess.run(
            [sys.executable, "workers/collector_worker/run_collection_slice.py", *args],
            capture_output=True,
            text=True,
            env=env,
        )

    def _run_worker(self, *args: str) -> dict[str, object]:
        result = self._run_worker_result(*args)
        result.check_returncode()
        return json.loads(result.stdout)

    def _run_worker_in_process(self, *args: str, repository: FakeWorkerRepository) -> dict[str, object]:
        stdout = StringIO()
        stderr = StringIO()
        old_argv = sys.argv[:]
        try:
            sys.argv = ["workers/collector_worker/run_collection_slice.py", *args]
            with patch("geno_core.runtime.build_repository_from_env", return_value=repository), patch(
                "workers.collector_worker.run_collection_slice.build_repository_from_env",
                return_value=repository,
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                runpy.run_path("workers/collector_worker/run_collection_slice.py", run_name="__main__")
        finally:
            sys.argv = old_argv
        self.assertEqual(stderr.getvalue(), "")
        return json.loads(stdout.getvalue())

    def test_fixture_worker_slice_succeeds(self) -> None:
        payload = self._run_worker("--mode", "fixture", "--prompt-limit", "1")
        self.assertEqual(payload["record_count"], 4)
        self.assertEqual(payload["success_count"], 4)
        self.assertEqual(payload["failure_count"], 0)
        gate = payload["p0a_readiness_gate"]
        self.assertEqual(gate["gate_status"], "fail")
        self.assertIn("below_required_sample_size=4", gate["failure_reasons"])
        self.assertEqual(payload["persistence"], {"enabled": False})

    def test_fixture_worker_k3_slice_passes_p0a_readiness_gate(self) -> None:
        payload = self._run_worker("--mode", "fixture", "--prompt-limit", "1", "--sample-size", "3")
        self.assertEqual(payload["record_count"], 12)
        gate = payload["p0a_readiness_gate"]
        self.assertEqual(gate["gate_status"], "pass")
        self.assertEqual(set(gate["observed_platforms"]), {"chatgpt", "perplexity"})
        self.assertEqual(gate["required_sample_size"], 3)
        self.assertEqual(gate["observed_sample_sizes"], [3])
        self.assertEqual(gate["failure_reasons"], [])

    def test_api_worker_slice_without_keys_is_audited_failure(self) -> None:
        payload = self._run_worker("--mode", "api", "--prompt-limit", "1", "--cities", "Australia")
        self.assertEqual(payload["record_count"], 2)
        self.assertEqual(payload["success_count"], 0)
        self.assertEqual(payload["failure_count"], 2)
        gate = payload["p0a_readiness_gate"]
        self.assertEqual(gate["gate_status"], "fail")
        self.assertIn("collection_failures=2", gate["failure_reasons"])
        failure_events = payload["failure_events"]
        self.assertIsInstance(failure_events, list)
        self.assertEqual(failure_events[0]["audit_events"][0]["event_type"], "answer_run_failed")

    def test_google_fixture_worker_slice_returns_gate(self) -> None:
        payload = self._run_worker("--mode", "google-fixture")
        self.assertEqual(payload["record_count"], 240)
        self.assertEqual(payload["success_count"], 240)
        gate = payload["google_spike_gate"]
        self.assertEqual(gate["gate_status"], "pass")
        self.assertFalse(gate["limited_coverage"])
        readiness_gate = payload["google_spike_readiness_gate"]
        self.assertEqual(readiness_gate["gate_status"], "fail")
        self.assertIn("insufficient_collection_paths=1/2", readiness_gate["failure_reasons"])

    def test_google_fixture_persist_analysis_skips_main_score_without_readiness_gate(self) -> None:
        repository = FakeWorkerRepository()
        payload = self._run_worker_in_process("--mode", "google-fixture", "--persist", "--persist-analysis", repository=repository)
        self.assertEqual(payload["record_count"], 240)
        self.assertEqual(payload["success_count"], 240)
        self.assertEqual(repository.saved_raw_evidence_records, 240)
        self.assertEqual(repository.saved_collection_summaries, 1)
        self.assertEqual(repository.saved_score_snapshots, 0)
        self.assertEqual(repository.saved_reports, 0)
        analysis = payload["persistence"]["analysis"]
        self.assertEqual(analysis["reason"], "no_score_input_records")
        self.assertEqual(analysis["score_input_record_count"], 0)
        self.assertEqual(analysis["score_input_policy"]["excluded_google_record_count"], 240)
        self.assertFalse(analysis["score_input_policy"]["google_main_scoring_allowed"])

    def test_fixture_persist_analysis_samples_browser_fidelity_without_scoring_browser_runs(self) -> None:
        repository = FakeWorkerRepository()
        payload = self._run_worker_in_process(
            "--mode",
            "fixture",
            "--prompt-limit",
            "1",
            "--cities",
            "Sydney",
            "--include-browser-fidelity-fixture",
            "--persist",
            "--persist-analysis",
            repository=repository,
        )
        self.assertEqual(payload["record_count"], 3)
        self.assertEqual(payload["success_count"], 3)
        self.assertEqual(repository.saved_raw_evidence_records, 3)
        self.assertEqual(repository.saved_score_snapshots, 1)
        self.assertEqual(repository.saved_reports, 1)
        analysis = payload["persistence"]["analysis"]
        self.assertEqual(analysis["analysis_count"], 3)
        self.assertEqual(analysis["score_input_record_count"], 2)
        self.assertEqual(analysis["score_input_policy"]["excluded_fidelity_sample_record_count"], 1)
        self.assertEqual(analysis["fidelity_check_status"], "sampled")
        self.assertEqual(analysis["fidelity_difference_rate"], 0.0)
        self.assertEqual(repository.saved_fidelity_check["status"], "sampled")
        self.assertEqual(repository.saved_fidelity_check["official_api_records"], 2)
        self.assertEqual(repository.saved_fidelity_check["browser_records"], 1)

    def test_persist_without_database_url_fails_loudly(self) -> None:
        result = self._run_worker_result(
            "--mode",
            "fixture",
            "--prompt-limit",
            "1",
            "--persist",
            unset_env=("DATABASE_URL",),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("DATABASE_URL", result.stderr)

    def test_persist_analysis_requires_persist(self) -> None:
        result = self._run_worker_result(
            "--mode",
            "fixture",
            "--prompt-limit",
            "1",
            "--persist-analysis",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--persist-analysis requires --persist", result.stderr)


if __name__ == "__main__":
    unittest.main()
