from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_serp_status_report import (
    build_au_p0b_google_serp_status_report,
    compute_google_serp_status_hash,
)
from scripts.build_preflight_manifest import build_preflight_manifest
from scripts.verify_au_p0b_google_serp_comparison import verify_au_p0b_google_serp_comparison
from scripts.verify_preflight_payload import compute_preflight_payload_hash


class GoogleSerpStatusReportFixtureMixin:
    def _payload(self, *, path: Path, mode: str = "google-serp-fixture", ready: bool = True) -> dict[str, object]:
        record_count = 120 if ready else 0
        success_count = 120 if ready else 0
        failure_count = 0
        payload: dict[str, object] = {
            "mode": mode,
            "planned_runs": 120,
            "record_count": record_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "preflight_output_path": str(path),
            "collector_health_gate": {
                "gate_status": "pass" if ready else "fail",
                "failure_reasons": [] if ready else ["google.third_party_serp:not_configured"],
            },
            "preflight_summary": {
                "summary_version": "provider_preflight_v1",
                "phase": "collection_completed" if ready else "collector_health",
                "exit_code": 0 if ready else 3,
                "ready_for_design_partner": False,
                "recommended_next_action": "inspect_preflight_output",
                "planned_runs": 120,
                "record_count": record_count,
                "success_count": success_count,
                "failure_count": failure_count,
                "cities": ["Australia", "Sydney"],
                "sample_size": 2,
                "prompt_limit": 30,
            },
            "preflight_audit_checklist": {
                "checklist_version": "provider_preflight_audit_checklist_v1",
                "overall_status": "pass" if ready else "fail",
                "ready_for_design_partner": False,
                "blocking_reasons": [] if ready else ["google.third_party_serp:not_configured"],
                "worker_args": ["--mode", mode],
                "evidence_refs": {"preflight_summary": "preflight_summary"},
                "checks": [],
                "run_totals": {
                    "planned_runs": 120,
                    "record_count": record_count,
                    "success_count": success_count,
                    "failure_count": failure_count,
                },
            },
            "google_spike_plan": {
                "planned_runs": 240,
                "prompt_count": 30,
                "geo_cities": ["Australia", "Sydney"],
                "sample_size": 2,
            },
            "google_serp_comparison_plan": {
                "comparison_version": "google_serp_comparison_plan_v1",
                "surface": "google_aio",
                "access_method": "third_party_api",
                "collector_backend_id": "google.third_party_serp",
                "prompt_count": 30,
                "geo_cities": ["Australia", "Sydney"],
                "sample_size": 2,
                "planned_runs": 120,
                "main_google_spike_planned_runs": 240,
                "score_input_policy": "comparison evidence only until merged with full GoogleSpikeGateResult and GoogleSpikeReadinessGate",
            },
        }
        if ready:
            payload["google_serp_comparison_summary"] = {
                "comparison_version": "google_serp_comparison_summary_v1",
                "planned_runs": 120,
                "attempted_runs": 120,
                "completed_runs": 120,
                "failure_count": 0,
                "success_rate": 1.0,
                "surface_trigger_rate": 1.0,
                "answer_present_rate": 1.0,
                "screenshot_or_html_runs": 120,
                "ready_for_comparison": True,
                "failure_summary": {},
                "score_input_policy": "comparison evidence only until merged with full GoogleSpikeGateResult and GoogleSpikeReadinessGate",
            }
        payload["preflight_payload_hash"] = compute_preflight_payload_hash(payload)
        return payload

    def _write_payload_and_manifest(
        self,
        *,
        payload_path: Path,
        manifest_path: Path,
        mode: str = "google-serp-fixture",
        ready: bool = True,
    ) -> None:
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._payload(path=payload_path, mode=mode, ready=ready)
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        verifier = verify_au_p0b_google_serp_comparison(payload, path=payload_path)
        manifest = build_preflight_manifest(
            preflight_path=payload_path,
            payload=payload,
            verifier=verifier,
            generated_at="2026-06-12T00:00:00Z",
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


class AuP0bGoogleSerpStatusReportTest(GoogleSerpStatusReportFixtureMixin, unittest.TestCase):
    def test_status_report_blocks_until_supplier_health_exists(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_path = root / "fixture.json"
            fixture_manifest = root / "fixture-manifest.json"
            self._write_payload_and_manifest(payload_path=fixture_path, manifest_path=fixture_manifest)

            report = build_au_p0b_google_serp_status_report(
                fixture_path=fixture_path,
                fixture_manifest_path=fixture_manifest,
                health_path=root / "health.json",
                health_manifest_path=root / "health-manifest.json",
                comparison_path=root / "comparison.json",
                comparison_manifest_path=root / "comparison-manifest.json",
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["comparison_evidence_ready"])
        self.assertFalse(report["google_main_scoring_allowed"])
        self.assertTrue(report["limited_coverage"])
        self.assertEqual(report["next_action"], "run_google_serp_health_check")
        self.assertIn("health:file_missing", report["remaining_blockers"])
        self.assertEqual(report["status_report_hash"], compute_google_serp_status_hash(report))

    def test_status_report_passes_when_all_comparison_artifacts_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_path = root / "fixture.json"
            fixture_manifest = root / "fixture-manifest.json"
            health_path = root / "health.json"
            health_manifest = root / "health-manifest.json"
            comparison_path = root / "comparison.json"
            comparison_manifest = root / "comparison-manifest.json"
            self._write_payload_and_manifest(payload_path=fixture_path, manifest_path=fixture_manifest)
            self._write_payload_and_manifest(
                payload_path=health_path,
                manifest_path=health_manifest,
                mode="google-serp-spike",
            )
            self._write_payload_and_manifest(
                payload_path=comparison_path,
                manifest_path=comparison_manifest,
                mode="google-serp-spike",
            )

            report = build_au_p0b_google_serp_status_report(
                fixture_path=fixture_path,
                fixture_manifest_path=fixture_manifest,
                health_path=health_path,
                health_manifest_path=health_manifest,
                comparison_path=comparison_path,
                comparison_manifest_path=comparison_manifest,
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["comparison_evidence_ready"])
        self.assertTrue(report["supplier_health_ready"])
        self.assertFalse(report["google_main_scoring_allowed"])
        self.assertEqual(report["next_action"], "handoff_google_serp_evidence_to_p0b_review")
        self.assertEqual(report["remaining_blockers"], [])
        self.assertEqual(report["status_report_hash"], compute_google_serp_status_hash(report))

    def test_status_report_marks_health_failure_as_supplier_configuration_next_action(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_path = root / "fixture.json"
            fixture_manifest = root / "fixture-manifest.json"
            health_path = root / "health.json"
            health_manifest = root / "health-manifest.json"
            self._write_payload_and_manifest(payload_path=fixture_path, manifest_path=fixture_manifest)
            self._write_payload_and_manifest(
                payload_path=health_path,
                manifest_path=health_manifest,
                mode="google-serp-spike",
                ready=False,
            )

            report = build_au_p0b_google_serp_status_report(
                fixture_path=fixture_path,
                fixture_manifest_path=fixture_manifest,
                health_path=health_path,
                health_manifest_path=health_manifest,
                comparison_path=root / "comparison.json",
                comparison_manifest_path=root / "comparison-manifest.json",
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["next_action"], "configure_google_serp_supplier")
        self.assertIn("health:collector_health_not_ready", report["remaining_blockers"])

    def test_cli_writes_status_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_path = root / "fixture.json"
            fixture_manifest = root / "fixture-manifest.json"
            output_path = root / "status.json"
            self._write_payload_and_manifest(payload_path=fixture_path, manifest_path=fixture_manifest)

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_serp_status_report.py",
                    "--fixture-path",
                    str(fixture_path),
                    "--fixture-manifest-path",
                    str(fixture_manifest),
                    "--health-path",
                    str(root / "health.json"),
                    "--health-manifest-path",
                    str(root / "health-manifest.json"),
                    "--comparison-path",
                    str(root / "comparison.json"),
                    "--comparison-manifest-path",
                    str(root / "comparison-manifest.json"),
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
        self.assertTrue(output_exists)
        self.assertEqual(payload["status_report_hash"], compute_google_serp_status_hash(payload))
if __name__ == "__main__":
    unittest.main()
