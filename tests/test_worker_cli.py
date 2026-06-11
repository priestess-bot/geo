from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
import unittest
from dataclasses import asdict
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import collect_prompt_once
from geno_core.collectors import JsonHttpResponse, PerplexitySonarCollector, PlaywrightChatGPTSearchCollector
from geno_core.object_store import StoredObject


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
        self.raw_evidence_records = records

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
        self.audit_events = events

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
    def _preflight_payload_hash(self, payload: dict[str, object]) -> str:
        payload_for_hash = dict(payload)
        payload_for_hash.pop("preflight_payload_hash", None)
        return hashlib.sha256(
            json.dumps(
                payload_for_hash,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

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
        self.assertEqual(
            payload["collection_execution_policy"],
            {"max_retries": 0, "retry_backoff_seconds": 0.0, "rate_limit_delay_seconds": 0.0},
        )
        self.assertEqual(payload["collector_health_gate"]["gate_status"], "pass")
        self.assertEqual(
            {item["health"] for item in payload["collector_health"]},
            {"fixture_ready"},
        )
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
        summary = payload["preflight_summary"]
        self.assertEqual(summary["summary_version"], "provider_preflight_v1")
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["phase"], "collection_completed")
        self.assertTrue(summary["ready_for_design_partner"])
        self.assertEqual(summary["collector_health_status"], "pass")
        self.assertEqual(summary["p0a_readiness_status"], "pass")
        self.assertEqual(summary["recommended_next_action"], "promote_to_small_real_au_batch")
        checklist = payload["preflight_audit_checklist"]
        self.assertEqual(checklist["checklist_version"], "provider_preflight_audit_checklist_v1")
        self.assertEqual(checklist["overall_status"], "pass")
        self.assertTrue(checklist["ready_for_design_partner"])
        self.assertEqual(checklist["blocking_reasons"], [])
        self.assertIn("--sample-size", checklist["worker_args"])
        self.assertEqual(checklist["run_totals"]["planned_runs"], 12)
        self.assertEqual(
            {check["id"]: check["status"] for check in checklist["checks"]},
            {
                "collector_health": "pass",
                "p0a_readiness": "pass",
                "collection_failures": "pass",
                "preflight_output_path": "warn",
                "replay_context": "pass",
            },
        )
        self.assertRegex(payload["preflight_payload_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(payload["preflight_payload_hash"], self._preflight_payload_hash(payload))

    def test_api_worker_slice_without_keys_is_audited_failure(self) -> None:
        payload = self._run_worker("--mode", "api", "--prompt-limit", "1", "--cities", "Australia")
        self.assertEqual(payload["record_count"], 2)
        self.assertEqual(payload["success_count"], 0)
        self.assertEqual(payload["failure_count"], 2)
        self.assertEqual(payload["collector_health_gate"]["gate_status"], "fail")
        self.assertEqual(
            payload["collector_health_gate"]["failure_reasons"],
            ["perplexity.sonar.api:not_configured", "openai.web_search.api:not_configured"],
        )
        summary = payload["preflight_summary"]
        self.assertEqual(summary["summary_version"], "provider_preflight_v1")
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["phase"], "collection_completed")
        self.assertFalse(summary["ready_for_design_partner"])
        self.assertEqual(summary["collector_health_status"], "fail")
        self.assertEqual(
            summary["collector_health_failure_reasons"],
            ["perplexity.sonar.api:not_configured", "openai.web_search.api:not_configured"],
        )
        self.assertEqual(summary["recommended_next_action"], "configure_missing_provider_credentials_or_collectors")
        gate = payload["p0a_readiness_gate"]
        self.assertEqual(gate["gate_status"], "fail")
        self.assertIn("collection_failures=2", gate["failure_reasons"])
        failure_events = payload["failure_events"]
        self.assertIsInstance(failure_events, list)
        self.assertEqual(failure_events[0]["audit_events"][0]["event_type"], "answer_run_failed")

    def test_api_preflight_without_keys_fails_before_collection(self) -> None:
        with TemporaryDirectory() as output_dir:
            output_path = os.path.join(output_dir, "api-preflight.json")
            result = self._run_worker_result(
                "--mode",
                "api",
                "--prompt-limit",
                "1",
                "--cities",
                "Sydney",
                "--require-ready-collectors",
                "--preflight-output-path",
                output_path,
                unset_env=("PERPLEXITY_API_KEY", "OPENAI_API_KEY"),
            )
            with open(output_path, encoding="utf-8") as output_file:
                written_payload = json.loads(output_file.read())
        self.assertEqual(result.returncode, 3)
        self.assertIn("collector_preflight_failed", result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload, written_payload)
        self.assertEqual(payload["preflight_output_path"], output_path)
        self.assertEqual(payload["record_count"], 0)
        self.assertEqual(payload["planned_runs"], 2)
        self.assertEqual(payload["collector_health_gate"]["gate_status"], "fail")
        self.assertEqual(
            payload["collector_health_gate"]["failure_reasons"],
            ["perplexity.sonar.api:not_configured", "openai.web_search.api:not_configured"],
        )
        summary = payload["preflight_summary"]
        self.assertEqual(summary["summary_version"], "provider_preflight_v1")
        self.assertEqual(summary["exit_code"], 3)
        self.assertEqual(summary["phase"], "collector_health")
        self.assertFalse(summary["ready_for_design_partner"])
        self.assertEqual(summary["collector_health_status"], "fail")
        self.assertEqual(
            summary["collector_health_failure_reasons"],
            ["perplexity.sonar.api:not_configured", "openai.web_search.api:not_configured"],
        )
        self.assertEqual(summary["audit_output_path"], output_path)
        self.assertEqual(summary["recommended_next_action"], "configure_missing_provider_credentials_or_collectors")
        checklist = payload["preflight_audit_checklist"]
        self.assertEqual(checklist["overall_status"], "fail")
        self.assertEqual(checklist["phase"], "collector_health")
        self.assertEqual(checklist["exit_code"], 3)
        self.assertIn("perplexity.sonar.api:not_configured", checklist["blocking_reasons"])
        self.assertEqual(checklist["evidence_refs"]["preflight_output_path"], output_path)
        self.assertIn("--preflight-output-path", checklist["worker_args"])
        self.assertEqual(
            {check["id"]: check["status"] for check in checklist["checks"]},
            {
                "collector_health": "fail",
                "p0a_readiness": "not_run",
                "collection_failures": "pass",
                "preflight_output_path": "pass",
                "replay_context": "pass",
            },
        )
        self.assertRegex(payload["preflight_payload_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(payload["preflight_payload_hash"], self._preflight_payload_hash(payload))
        self.assertEqual(written_payload["preflight_payload_hash"], self._preflight_payload_hash(written_payload))

    def test_api_preflight_with_browser_fidelity_requires_browser_collector_ready(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PERPLEXITY_API_KEY": "test-perplexity-key",
                "OPENAI_API_KEY": "test-openai-key",
            },
            clear=False,
        ):
            result = self._run_worker_result(
                "--mode",
                "api",
                "--prompt-limit",
                "1",
                "--cities",
                "Sydney",
                "--sample-size",
                "3",
                "--include-browser-fidelity-playwright",
                "--require-ready-collectors",
                unset_env=(
                    "GENO_BROWSER_COLLECTOR_ENABLED",
                    "GENO_BROWSER_PROMPT_SELECTOR",
                    "GENO_BROWSER_ANSWER_SELECTOR",
                ),
            )
        self.assertEqual(result.returncode, 3)
        self.assertIn("collector_preflight_failed", result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["record_count"], 0)
        self.assertEqual(payload["planned_runs"], 9)
        self.assertEqual(payload["collector_health_gate"]["gate_status"], "fail")
        self.assertEqual(
            payload["collector_health_gate"]["failure_reasons"],
            ["chatgpt_search.browser.playwright:not_configured"],
        )
        summary = payload["preflight_summary"]
        self.assertEqual(summary["exit_code"], 3)
        self.assertEqual(summary["planned_runs"], 9)
        self.assertEqual(summary["phase"], "collector_health")
        self.assertFalse(summary["ready_for_design_partner"])
        self.assertEqual(summary["recommended_next_action"], "configure_missing_provider_credentials_or_collectors")

    def test_browser_fidelity_sampling_plan_outputs_replayable_worker_args(self) -> None:
        payload = self._run_worker(
            "--plan-browser-fidelity-sampling",
            "--fidelity-run-date",
            "2026-06-11",
            "--fidelity-prompt-count",
            "3",
            "--fidelity-city-count",
            "2",
            "--sample-size",
            "1",
            "--fidelity-selection-seed",
            "worker-fixed-seed",
        )
        plan = payload["browser_fidelity_sampling_plan"]
        self.assertEqual(payload["mode"], "browser_fidelity_sampling_plan")
        self.assertEqual(payload["record_count"], 0)
        self.assertEqual(plan["prompt_count"], 3)
        self.assertEqual(plan["city_count"], 2)
        self.assertEqual(plan["planned_runs"], 18)
        self.assertEqual(payload["planned_runs"], 18)
        self.assertEqual(payload["audit_event"]["event_type"], "browser_fidelity_sampling_planned")
        self.assertIn("--prompt-ids", payload["recommended_worker_args"])
        self.assertIn("--include-browser-fidelity-playwright", payload["recommended_worker_args"])
        self.assertRegex(payload["preflight_payload_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(payload["preflight_payload_hash"], self._preflight_payload_hash(payload))

    def test_prompt_ids_limit_collection_to_scheduled_sample(self) -> None:
        bootstrap = build_au_project_bootstrap()
        prompt_ids = ",".join(prompt.id for prompt in bootstrap.prompt_questions[:3])
        payload = self._run_worker(
            "--mode",
            "fixture",
            "--prompt-ids",
            prompt_ids,
            "--cities",
            "Sydney",
            "--sample-size",
            "1",
        )
        self.assertEqual(payload["record_count"], 6)
        self.assertEqual(payload["planned_runs"], 6)
        self.assertEqual(payload["success_count"], 6)
        self.assertEqual(payload["collector_health_gate"]["gate_status"], "pass")

    def test_require_p0a_readiness_fails_nonzero_when_gate_fails(self) -> None:
        result = self._run_worker_result(
            "--mode",
            "fixture",
            "--prompt-limit",
            "1",
            "--require-p0a-readiness",
        )
        self.assertEqual(result.returncode, 4)
        self.assertIn("p0a_readiness_failed", result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["p0a_readiness_gate"]["gate_status"], "fail")
        self.assertIn("below_required_sample_size=4", payload["p0a_readiness_gate"]["failure_reasons"])
        summary = payload["preflight_summary"]
        self.assertEqual(summary["exit_code"], 4)
        self.assertEqual(summary["phase"], "p0a_readiness")
        self.assertFalse(summary["ready_for_design_partner"])
        self.assertEqual(summary["p0a_readiness_status"], "fail")
        self.assertIn("below_required_sample_size=4", summary["p0a_readiness_failure_reasons"])
        self.assertEqual(
            summary["recommended_next_action"],
            "inspect_p0a_readiness_failure_reasons_before_design_partner",
        )
        checklist = payload["preflight_audit_checklist"]
        self.assertEqual(checklist["overall_status"], "fail")
        self.assertIn("below_required_sample_size=4", checklist["blocking_reasons"])
        self.assertEqual(checklist["run_totals"]["record_count"], 4)
        self.assertEqual(
            {check["id"]: check["status"] for check in checklist["checks"]},
            {
                "collector_health": "pass",
                "p0a_readiness": "fail",
                "collection_failures": "pass",
                "preflight_output_path": "warn",
                "replay_context": "pass",
            },
        )

    def test_require_no_collection_failures_fails_nonzero_after_collection(self) -> None:
        result = self._run_worker_result(
            "--mode",
            "api",
            "--prompt-limit",
            "1",
            "--cities",
            "Sydney",
            "--require-no-collection-failures",
            unset_env=("PERPLEXITY_API_KEY", "OPENAI_API_KEY"),
        )
        self.assertEqual(result.returncode, 5)
        self.assertIn("collection_failures_found: 2", result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["failure_count"], 2)
        self.assertEqual(payload["record_count"], 2)
        checklist = payload["preflight_audit_checklist"]
        self.assertEqual(checklist["overall_status"], "fail")
        self.assertIn("collection_failures=2", checklist["blocking_reasons"])
        self.assertEqual(checklist["run_totals"]["failure_count"], 2)
        self.assertEqual(
            {check["id"]: check["status"] for check in checklist["checks"]}["collection_failures"],
            "fail",
        )

    def test_collection_retry_cli_options_are_reported(self) -> None:
        payload = self._run_worker(
            "--mode",
            "fixture",
            "--prompt-limit",
            "1",
            "--cities",
            "Sydney",
            "--collection-max-retries",
            "1",
            "--collection-retry-backoff-seconds",
            "0",
            "--collection-rate-limit-delay-seconds",
            "0",
        )
        self.assertEqual(payload["record_count"], 2)
        self.assertEqual(
            payload["collection_execution_policy"],
            {"max_retries": 1, "retry_backoff_seconds": 0.0, "rate_limit_delay_seconds": 0.0},
        )

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
        self.assertEqual(analysis["judge_gateway"], "fixture")
        self.assertEqual(analysis["judge_model"], "local-fixture-judge")
        self.assertEqual(analysis["score_input_policy"]["excluded_fidelity_sample_record_count"], 1)
        self.assertEqual(analysis["fidelity_check_status"], "sampled")
        self.assertEqual(analysis["fidelity_difference_rate"], 0.0)
        self.assertEqual(repository.saved_fidelity_check["status"], "sampled")
        self.assertEqual(repository.saved_fidelity_check["official_api_records"], 2)
        self.assertEqual(repository.saved_fidelity_check["browser_records"], 1)

    def test_persist_records_archives_api_snapshot_assets_before_saving_evidence(self) -> None:
        class FakeApiHttpClient:
            def post_json(self, **kwargs: object) -> JsonHttpResponse:
                return JsonHttpResponse(
                    status_code=200,
                    payload={
                        "choices": [{"message": {"content": "Perplexity answer"}}],
                        "citations": ["https://source.example/a"],
                    },
                )

        class FakeObjectStore:
            def put_object(self, *, key: str, content: str | bytes, content_type: str) -> StoredObject:
                payload = content.encode("utf-8") if isinstance(content, str) else content
                return StoredObject(
                    uri=f"s3://geno-reports/{key}",
                    bucket="geno-reports",
                    key=key,
                    content_type=content_type,
                    content_hash=__import__("hashlib").sha256(payload).hexdigest(),
                    etag='"snapshot-etag"',
                )

        from workers.collector_worker import run_collection_slice as worker_module

        bootstrap = build_au_project_bootstrap()
        record = collect_prompt_once(
            project_id=bootstrap.project.id,
            prompt=bootstrap.prompt_questions[0],
            market_profile=bootstrap.market_profile,
            collector=PerplexitySonarCollector(api_key="test-key", http_client=FakeApiHttpClient()),
            city="Sydney",
            sample_index=1,
            sample_size=3,
        )
        repository = FakeWorkerRepository()
        env = {"OBJECT_STORE_ENDPOINT": "http://minio:9000"}
        with patch.dict(os.environ, env, clear=False), patch(
            "workers.collector_worker.run_collection_slice.build_repository_from_env",
            return_value=repository,
        ), patch(
            "workers.collector_worker.run_collection_slice.build_object_store_from_env",
            return_value=FakeObjectStore(),
        ):
            payload = worker_module._persist_records(
                bootstrap=bootstrap,
                mode="api",
                run_type="p0a_slice",
                planned_runs=1,
                records=(record,),
                successes=(record,),
                failures=(),
                persist_analysis=False,
                score_formula_version="au_visibility_v1",
                judge_gateway="fixture",
                judge_model="local-fixture-judge",
            )

        saved_asset = repository.raw_evidence_records[0].evidence_assets[0]
        self.assertTrue(saved_asset.url.startswith("s3://geno-reports/evidence/"))
        self.assertEqual(len(saved_asset.content_hash), 64)
        self.assertEqual(payload["api_snapshot_artifacts"]["enabled"], True)
        self.assertEqual(len(payload["api_snapshot_artifacts"]["stored_snapshot_assets"]), 1)
        self.assertEqual(repository.audit_events[0].event_type, "api_snapshot_assets_archived")
        self.assertEqual(asdict(repository.audit_events[0])["output_refs"]["artifact_uris"], [saved_asset.url])

    def test_persist_records_archives_browser_capture_assets_before_saving_evidence(self) -> None:
        class FakeLocator:
            @property
            def last(self) -> "FakeLocator":
                return self

            def inner_text(self, **kwargs: object) -> str:
                return "Browser answer for worker archive."

            def evaluate_all(self, script: str) -> list[str]:
                return ["https://source.example/browser-worker"]

        class FakeKeyboard:
            def press(self, key: str) -> None:
                self.key = key

        class FakePage:
            url = "https://chatgpt.com/c/worker-browser-archive"

            def __init__(self) -> None:
                self.keyboard = FakeKeyboard()

            def goto(self, *args: object, **kwargs: object) -> None:
                return None

            def fill(self, *args: object, **kwargs: object) -> None:
                return None

            def wait_for_selector(self, *args: object, **kwargs: object) -> None:
                return None

            def locator(self, selector: str) -> FakeLocator:
                return FakeLocator()

            def title(self) -> str:
                return "Fake Worker Browser"

            def content(self) -> str:
                return "<html><body>Worker browser HTML</body></html>"

            def screenshot(self, **kwargs: object) -> bytes:
                return b"worker-browser-png"

        class FakeContext:
            def new_page(self) -> FakePage:
                return FakePage()

            def close(self) -> None:
                return None

        class FakeBrowser:
            def launch(self, **kwargs: object) -> "FakeBrowser":
                return self

            def new_context(self, **kwargs: object) -> FakeContext:
                return FakeContext()

            def close(self) -> None:
                return None

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeBrowser()

        class FakePlaywrightManager:
            def __enter__(self) -> FakePlaywright:
                return FakePlaywright()

            def __exit__(self, *args: object) -> None:
                return None

        class FakeObjectStore:
            def put_object(self, *, key: str, content: str | bytes, content_type: str) -> StoredObject:
                payload = content.encode("utf-8") if isinstance(content, str) else content
                return StoredObject(
                    uri=f"s3://geno-reports/{key}",
                    bucket="geno-reports",
                    key=key,
                    content_type=content_type,
                    content_hash=__import__("hashlib").sha256(payload).hexdigest(),
                    etag='"browser-etag"',
                )

        from workers.collector_worker import run_collection_slice as worker_module

        bootstrap = build_au_project_bootstrap()
        with TemporaryDirectory() as artifact_dir:
            record = collect_prompt_once(
                project_id=bootstrap.project.id,
                prompt=bootstrap.prompt_questions[0],
                market_profile=bootstrap.market_profile,
                collector=PlaywrightChatGPTSearchCollector(
                    enabled=True,
                    prompt_selector="#prompt",
                    answer_selector=".answer",
                    citation_selector=".citation",
                    artifact_dir=artifact_dir,
                    playwright_factory=FakePlaywrightManager,
                ),
                city="Sydney",
                sample_index=1,
                sample_size=1,
            )
            repository = FakeWorkerRepository()
            env = {"OBJECT_STORE_ENDPOINT": "http://minio:9000"}
            with patch.dict(os.environ, env, clear=False), patch(
                "workers.collector_worker.run_collection_slice.build_repository_from_env",
                return_value=repository,
            ), patch(
                "workers.collector_worker.run_collection_slice.build_object_store_from_env",
                return_value=FakeObjectStore(),
            ):
                payload = worker_module._persist_records(
                    bootstrap=bootstrap,
                    mode="api",
                    run_type="browser_fidelity_slice",
                    planned_runs=1,
                    records=(record,),
                    successes=(record,),
                    failures=(),
                    persist_analysis=False,
                    score_formula_version="au_visibility_v1",
                    judge_gateway="fixture",
                    judge_model="local-fixture-judge",
                )

        saved_assets = repository.raw_evidence_records[0].evidence_assets
        self.assertEqual({asset.asset_type for asset in saved_assets}, {"html_snapshot", "screenshot"})
        self.assertTrue(all(asset.url.startswith("s3://geno-reports/evidence/") for asset in saved_assets))
        self.assertTrue(all(len(str(asset.content_hash)) == 64 for asset in saved_assets))
        self.assertEqual(payload["browser_capture_artifacts"]["enabled"], True)
        self.assertEqual(len(payload["browser_capture_artifacts"]["stored_browser_assets"]), 2)
        self.assertEqual(repository.audit_events[0].event_type, "browser_capture_assets_archived")
        self.assertEqual(
            sorted(asdict(repository.audit_events[0])["output_refs"]["artifact_uris"]),
            sorted(asset.url for asset in saved_assets),
        )

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
