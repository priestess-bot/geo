from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_spike_runbook import build_au_p0b_google_spike_runbook
from scripts.build_au_p0b_google_spike_status_report import build_au_p0b_google_spike_status_report
from scripts.build_au_p0b_google_spike_status_report import compute_google_spike_status_hash
from scripts.build_au_p0b_google_playwright_env_report import build_google_playwright_env_report
from scripts.build_au_p0b_manual_backfill_template import build_manual_backfill_template
from scripts.build_preflight_manifest import build_preflight_manifest
from scripts.run_au_p0b_google_playwright_smoke import run_google_playwright_smoke, write_smoke_payload
from scripts.run_au_p0b_google_spike_runbook import run_au_p0b_google_spike_runbook
from scripts.verify_au_p0b_manual_backfill import verify_manual_backfill
from scripts.verify_preflight_payload import compute_preflight_payload_hash, verify_preflight_payload
from scripts.verify_au_p0b_google_spike_status_report import verify_au_p0b_google_spike_status_report
from tests.test_au_p0b_google_playwright_smoke import FakeReadyGoogleAIOCollector


class AuP0bGoogleSpikeStatusReportVerifierTest(unittest.TestCase):
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
                "phase": "collection_completed" if google_ready else "collector_health",
                "exit_code": 0,
                "ready_for_design_partner": False,
                "recommended_next_action": "inspect_preflight_output",
            },
            "preflight_audit_checklist": {
                "checklist_version": "provider_preflight_audit_checklist_v1",
                "overall_status": "fail",
                "ready_for_design_partner": False,
                "blocking_reasons": [],
                "worker_args": ["--mode", "google-spike"],
                "evidence_refs": {"preflight_summary": "preflight_summary"},
                "checks": [],
                "run_totals": {"planned_runs": 240, "record_count": 240 if google_ready else 0},
            },
            "collector_health_gate": {
                "gate_status": "pass" if google_ready else "fail",
                "failure_reasons": [] if google_ready else ["google_aio.playwright:not_configured"],
            },
            "google_spike_gate": {
                "gate_status": "pass" if google_ready else "fail",
                "limited_coverage": not google_ready,
            },
            "google_spike_readiness_gate": {
                "gate_status": "pass" if google_ready else "fail",
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

    def _write_manual_backfill_verification(self, path: Path, temp_dir: str) -> None:
        lines, _manifest = build_manual_backfill_template(generated_at="2026-06-12T00:00:00Z")
        manual_path = Path(temp_dir) / "manual.jsonl"
        manual_path.write_text(
            "".join(
                json.dumps(
                    {
                        **line,
                        "answer_text": f"Manual Google AI Mode answer {index}.",
                        "citation_urls": [f"https://examplebrand.example/manual/{index}"],
                        "screenshot_url": f"s3://manual-google-ai-mode/{index}.png",
                        "html_snapshot_url": f"s3://manual-google-ai-mode/{index}.html",
                        "submitted_by": "analyst@example.com",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
                for index, line in enumerate(lines, start=1)
            ),
            encoding="utf-8",
        )
        result = verify_manual_backfill(manual_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result), encoding="utf-8")

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

    def _ready_report(self, temp_dir: str) -> dict[str, object]:
        runbook_path, execution_path, runbook = self._write_runbook_and_execution(temp_dir)
        artifacts = runbook["artifact_paths"]  # type: ignore[index]
        self._write_playwright_env(
            runbook_path=runbook_path,
            env_path=Path(artifacts["playwright_env_json"]),
            temp_dir=temp_dir,
        )
        self._write_smoke(Path(artifacts["playwright_smoke_json"]))
        self._write_manual_backfill_verification(Path(artifacts["manual_backfill_verification_json"]), temp_dir)
        self._write_manifest(Path(artifacts["health_json"]), Path(artifacts["health_manifest"]), google_ready=True)
        self._write_manifest(Path(artifacts["spike_json"]), Path(artifacts["spike_manifest"]), google_ready=True)

        return build_au_p0b_google_spike_status_report(
            runbook_path=runbook_path,
            execution_path=execution_path,
            generated_at="2026-06-12T00:00:00Z",
        )

    def test_valid_ready_status_report_passes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._ready_report(temp_dir)
            result = verify_au_p0b_google_spike_status_report(report)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertTrue(result["google_main_scoring_allowed"])
        self.assertFalse(result["limited_coverage"])
        self.assertEqual(result["remaining_blocker_count"], 0)

    def test_require_google_main_scoring_fails_when_not_allowed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, _ = self._write_runbook_and_execution(temp_dir)

            report = build_au_p0b_google_spike_status_report(
                runbook_path=runbook_path,
                execution_path=execution_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            result = verify_au_p0b_google_spike_status_report(report, require_google_main_scoring_allowed=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("google_main_scoring_not_allowed", result["errors"])

    def test_hash_mismatch_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._ready_report(temp_dir)
            report["next_action"] = "tampered"
            result = verify_au_p0b_google_spike_status_report(report)

        self.assertEqual(result["status"], "fail")
        self.assertIn("status_report_hash_mismatch", result["errors"])

    def test_cli_reads_status_report_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "status.json"
            report = self._ready_report(temp_dir)
            path.write_text(json.dumps(report), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/verify_au_p0b_google_spike_status_report.py", str(path)],
                capture_output=True,
                check=True,
                text=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["computed_status_report_hash"], compute_google_spike_status_hash(report))


if __name__ == "__main__":
    unittest.main()
