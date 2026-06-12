from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_spike_runbook import build_au_p0b_google_spike_runbook
from scripts.build_au_p0b_google_spike_status_report import (
    build_au_p0b_google_spike_status_report,
    compute_google_spike_status_hash,
)
from scripts.build_au_p0b_google_playwright_env_report import build_google_playwright_env_report
from scripts.build_preflight_manifest import build_preflight_manifest
from scripts.run_au_p0b_google_playwright_smoke import run_google_playwright_smoke, write_smoke_payload
from scripts.run_au_p0b_google_spike_runbook import run_au_p0b_google_spike_runbook
from scripts.verify_preflight_payload import compute_preflight_payload_hash, verify_preflight_payload
from tests.test_au_p0b_google_playwright_smoke import FakeReadyGoogleAIOCollector


class AuP0bGoogleSpikeStatusReportTest(unittest.TestCase):
    def _payload(self, *, path: Path, google_ready: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": "google-spike",
            "planned_runs": 240,
            "record_count": 240 if google_ready else 0,
            "success_count": 240 if google_ready else 0,
            "failure_count": 0,
            "preflight_output_path": str(path),
            "preflight_summary": {
                "summary_version": "provider_preflight_v1",
                "mode": "google-spike",
                "phase": "collection_completed" if google_ready else "collector_health",
                "exit_code": 0,
                "ready_for_design_partner": False,
                "planned_runs": 240,
                "record_count": 240 if google_ready else 0,
                "success_count": 240 if google_ready else 0,
                "failure_count": 0,
                "cities": ["Australia", "Sydney"],
                "sample_size": 2,
                "prompt_limit": 30,
                "recommended_next_action": "inspect_preflight_output",
            },
            "preflight_audit_checklist": {
                "checklist_version": "provider_preflight_audit_checklist_v1",
                "overall_status": "fail",
                "ready_for_design_partner": False,
                "blocking_reasons": [],
                "worker_args": ["--mode", "google-spike", "--require-google-spike-gates"],
                "evidence_refs": {"preflight_summary": "preflight_summary"},
                "checks": [],
                "run_totals": {
                    "planned_runs": 240,
                    "record_count": 240 if google_ready else 0,
                    "success_count": 240 if google_ready else 0,
                    "failure_count": 0,
                },
            },
            "collector_health_gate": {
                "gate_status": "pass" if google_ready else "fail",
                "failure_reasons": [] if google_ready else ["google_aio.playwright:not_configured"],
            },
            "google_spike_gate": {
                "gate_status": "pass" if google_ready else "fail",
                "planned_runs": 240,
                "completed_runs": 240 if google_ready else 0,
                "google_aio_completed_runs": 120 if google_ready else 0,
                "success_rate": 1.0 if google_ready else 0.0,
                "trigger_rate": 1.0 if google_ready else 0.0,
                "limited_coverage": not google_ready,
            },
            "google_spike_readiness_gate": {
                "gate_status": "pass" if google_ready else "fail",
                "planned_runs": 240,
                "attempted_runs": 240 if google_ready else 0,
                "completed_runs": 240 if google_ready else 0,
                "observed_access_methods": ["browser", "manual"] if google_ready else [],
                "failure_reasons": [] if google_ready else ["no_records"],
            },
        }
        payload["preflight_payload_hash"] = compute_preflight_payload_hash(payload)
        return payload

    def _write_manifest(self, payload_path: Path, manifest_path: Path, *, google_ready: bool) -> None:
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._payload(path=payload_path, google_ready=google_ready)
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        verifier = verify_preflight_payload(payload, path=payload_path)
        manifest = build_preflight_manifest(
            preflight_path=payload_path,
            payload=payload,
            verifier=verifier,
            generated_at="2026-06-12T00:00:00Z",
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _write_smoke(self, smoke_path: Path) -> None:
        payload = run_google_playwright_smoke(
            collector=FakeReadyGoogleAIOCollector(),
            generated_at="2026-06-12T00:00:00Z",
        )
        write_smoke_payload(payload, smoke_path)

    def _write_playwright_env(self, *, runbook_path: Path, env_path: Path, temp_dir: str) -> None:
        manual_path = Path(temp_dir) / "manual.jsonl"
        manual_path.write_text(
            json.dumps(
                {
                    "prompt": "Best mattresses in Sydney?",
                    "city": "Sydney",
                    "answer_text": "Koala is visible.",
                    "citation_urls": ["https://koala.com/en-au"],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        report = build_google_playwright_env_report(
            runbook_path=runbook_path,
            env_file_path=Path(temp_dir) / "missing.env",
            output_path=env_path,
            env={
                "GOOGLE_PLAYWRIGHT_ENABLED": "1",
                "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR": "#prompt",
                "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR": ".answer",
                "MANUAL_BACKFILL_PATH": str(manual_path),
                "DATABASE_URL": "postgresql://user:pass@example.test/db",
            },
            playwright_available=True,
            generated_at="2026-06-12T00:00:00Z",
        )
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(json.dumps(report), encoding="utf-8")

    def _write_runbook_and_execution(self, temp_dir: str) -> tuple[Path, Path, dict[str, object]]:
        artifact_dir = str(Path(temp_dir) / "runtime")
        runbook = build_au_p0b_google_spike_runbook(
            artifact_dir=artifact_dir,
            generated_at="2026-06-12T00:00:00Z",
        )
        runbook_path = Path(temp_dir) / "runbook.json"
        runbook_path.write_text(json.dumps(runbook), encoding="utf-8")
        execution_path = Path(temp_dir) / "execution.json"
        execution = run_au_p0b_google_spike_runbook(
            runbook_path=runbook_path,
            output_path=execution_path,
            env={
                "GOOGLE_PLAYWRIGHT_ENABLED": "1",
                "MANUAL_BACKFILL_PATH": str(Path(temp_dir) / "manual.jsonl"),
                "DATABASE_URL": "postgresql://user:pass@example.test/db",
            },
            generated_at="2026-06-12T00:00:00Z",
        )
        execution_path.write_text(json.dumps(execution), encoding="utf-8")
        return runbook_path, execution_path, runbook

    def test_status_report_blocks_until_real_spike_payload_exists(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, _ = self._write_runbook_and_execution(temp_dir)
            report = build_au_p0b_google_spike_status_report(
                runbook_path=runbook_path,
                execution_path=execution_path,
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["google_main_scoring_allowed"])
        self.assertEqual(report["next_action"], "run_google_playwright_env_report")
        self.assertIn("playwright_env:file_missing", report["remaining_blockers"])
        self.assertIn("playwright_smoke:file_missing", report["remaining_blockers"])
        self.assertIn("health:file_missing", report["remaining_blockers"])
        self.assertEqual(report["status_report_hash"], compute_google_spike_status_hash(report))

    def test_status_report_passes_when_health_and_spike_gates_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, runbook = self._write_runbook_and_execution(temp_dir)
            artifacts = runbook["artifact_paths"]  # type: ignore[index]
            self._write_playwright_env(
                runbook_path=runbook_path,
                env_path=Path(artifacts["playwright_env_json"]),
                temp_dir=temp_dir,
            )
            self._write_smoke(Path(artifacts["playwright_smoke_json"]))
            self._write_manifest(Path(artifacts["health_json"]), Path(artifacts["health_manifest"]), google_ready=True)
            self._write_manifest(Path(artifacts["spike_json"]), Path(artifacts["spike_manifest"]), google_ready=True)
            report = build_au_p0b_google_spike_status_report(
                runbook_path=runbook_path,
                execution_path=execution_path,
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["google_main_scoring_allowed"])
        self.assertFalse(report["limited_coverage"])
        self.assertEqual(report["next_action"], "allow_google_into_main_scoring_denominator")
        self.assertEqual(report["remaining_blockers"], [])
        self.assertEqual(report["status_report_hash"], compute_google_spike_status_hash(report))
        self.assertTrue(report["artifacts"]["playwright_smoke"]["smoke_success"])  # type: ignore[index]

    def test_cli_writes_status_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, _ = self._write_runbook_and_execution(temp_dir)
            output_path = Path(temp_dir) / "status.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_spike_status_report.py",
                    "--runbook-path",
                    str(runbook_path),
                    "--execution-path",
                    str(execution_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            output_exists = output_path.exists()

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status_report_hash"], compute_google_spike_status_hash(payload))
        self.assertTrue(output_exists)


if __name__ == "__main__":
    unittest.main()
