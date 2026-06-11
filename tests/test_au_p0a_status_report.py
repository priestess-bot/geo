from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_evidence_package import build_au_p0a_evidence_package
from scripts.build_au_p0a_runbook import build_au_p0a_runbook
from scripts.build_au_p0a_status_report import (
    build_au_p0a_status_report,
    compute_status_report_hash,
)
from scripts.build_preflight_manifest import build_preflight_manifest
from scripts.verify_preflight_payload import compute_preflight_payload_hash, verify_preflight_payload


class AuP0aStatusReportFixtureMixin:
    def _payload(self, *, path: Path, planned_runs: int) -> dict[str, object]:
        prompt_limit = 1 if planned_runs == 6 else 5 if planned_runs == 30 else 100
        cities = ["Sydney"] if planned_runs in (6, 30) else ["Australia", "Sydney", "Melbourne", "Brisbane"]
        payload: dict[str, object] = {
            "mode": "api",
            "planned_runs": planned_runs,
            "record_count": planned_runs,
            "success_count": planned_runs,
            "failure_count": 0,
            "preflight_output_path": str(path),
            "preflight_summary": {
                "summary_version": "provider_preflight_v1",
                "phase": "collection_completed",
                "exit_code": 0,
                "ready_for_design_partner": True,
                "planned_runs": planned_runs,
                "record_count": planned_runs,
                "success_count": planned_runs,
                "failure_count": 0,
                "cities": cities,
                "sample_size": 3,
                "prompt_limit": prompt_limit,
                "recommended_next_action": "promote_to_next_real_au_batch",
            },
            "preflight_audit_checklist": {
                "checklist_version": "provider_preflight_audit_checklist_v1",
                "overall_status": "pass",
                "ready_for_design_partner": True,
                "blocking_reasons": [],
                "worker_args": ["--mode", "api", "--sample-size", "3"],
                "evidence_refs": {"preflight_summary": "preflight_summary"},
                "checks": [],
                "run_totals": {"planned_runs": planned_runs, "record_count": planned_runs},
            },
        }
        payload["preflight_payload_hash"] = compute_preflight_payload_hash(payload)
        return payload

    def _write_payload_and_manifest(self, payload_path: Path, manifest_path: Path, *, planned_runs: int) -> None:
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._payload(path=payload_path, planned_runs=planned_runs)
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        verifier = verify_preflight_payload(payload, path=payload_path, require_design_partner_ready=True)
        manifest = build_preflight_manifest(
            preflight_path=payload_path,
            payload=payload,
            verifier=verifier,
            generated_at="2026-06-11T00:00:00Z",
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _write_runbook(self, temp_dir: str) -> tuple[Path, dict[str, object]]:
        artifact_dir = str(Path(temp_dir) / "runtime")
        runbook = build_au_p0a_runbook(artifact_dir=artifact_dir, generated_at="2026-06-11T00:00:00Z")
        runbook_path = Path(temp_dir) / "runbook.json"
        runbook_path.write_text(json.dumps(runbook), encoding="utf-8")
        return runbook_path, runbook

    def _write_ready_readiness(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "readiness_version": "au_p0a_readiness_v1",
                    "generated_at": "2026-06-11T00:00:00Z",
                    "phase": "full_batch",
                    "status": "pass",
                    "ready_to_run_phase": True,
                    "errors": [],
                    "warnings": [],
                    "recommended_next_action": "run_full_au_p0a_batch",
                }
            ),
            encoding="utf-8",
        )

    def _write_complete_package(self, temp_dir: str) -> tuple[Path, Path, Path]:
        runbook_path, runbook = self._write_runbook(temp_dir)
        readiness_path = Path(temp_dir) / "readiness.json"
        package_path = Path(temp_dir) / "package.json"
        self._write_ready_readiness(readiness_path)
        artifact_paths = runbook["artifact_paths"]  # type: ignore[index]
        self._write_payload_and_manifest(
            Path(artifact_paths["preflight_json"]),
            Path(artifact_paths["preflight_manifest"]),
            planned_runs=6,
        )
        self._write_payload_and_manifest(
            Path(artifact_paths["small_batch_json"]),
            Path(artifact_paths["small_batch_manifest"]),
            planned_runs=30,
        )
        self._write_payload_and_manifest(
            Path(artifact_paths["full_batch_json"]),
            Path(artifact_paths["full_batch_manifest"]),
            planned_runs=2400,
        )
        package = build_au_p0a_evidence_package(
            runbook_path=runbook_path,
            readiness_path=readiness_path,
            output_path=package_path,
            generated_at="2026-06-11T00:00:00Z",
        )
        package_path.write_text(json.dumps(package), encoding="utf-8")
        return runbook_path, readiness_path, package_path


class AuP0aStatusReportTest(AuP0aStatusReportFixtureMixin, unittest.TestCase):
    def test_status_report_records_remaining_blockers_for_incomplete_state(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _ = self._write_runbook(temp_dir)
            report = build_au_p0a_status_report(
                runbook_path=runbook_path,
                readiness_path=Path(temp_dir) / "missing-readiness.json",
                package_path=Path(temp_dir) / "missing-package.json",
                env={},
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["ready_for_design_partner"])
        self.assertEqual(report["next_action"], "configure_required_environment")
        self.assertEqual(report["package_source"]["source"], "generated_in_memory")
        self.assertEqual(report["package"]["status"], "fail")
        self.assertEqual(report["package"]["package_manifest_status"], "fail")
        self.assertEqual(report["package"]["verifier_status"], "pass")
        self.assertEqual(report["completion"]["non_failed_artifact_count"], 1)
        self.assertEqual(report["completion"]["ready_artifact_count"], 0)
        self.assertEqual(report["completion"]["design_ready_eligible_artifact_count"], 0)
        self.assertEqual(report["completion"]["completion_percent"], 12.5)
        self.assertEqual(report["completion"]["design_ready_artifact_percent"], 0.0)
        self.assertIn("required_env_missing:PERPLEXITY_API_KEY", report["readiness"]["preflight"]["errors"])
        self.assertIn("readiness:readiness_file_missing", report["remaining_blockers"])
        self.assertEqual(report["status_report_hash"], compute_status_report_hash(report))

    def test_status_report_passes_with_complete_package_and_env(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, readiness_path, package_path = self._write_complete_package(temp_dir)
            report = build_au_p0a_status_report(
                runbook_path=runbook_path,
                readiness_path=readiness_path,
                package_path=package_path,
                env={
                    "PERPLEXITY_API_KEY": "perplexity-key",
                    "OPENAI_API_KEY": "openai-key",
                    "DATABASE_URL": "postgresql://user:pass@example.test/db",
                },
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["ready_for_design_partner"])
        self.assertEqual(report["next_action"], "ready_for_design_partner_handoff")
        self.assertEqual(report["package"]["status"], "pass")
        self.assertEqual(report["package"]["package_manifest_status"], "pass")
        self.assertEqual(report["package"]["verifier_status"], "pass")
        self.assertEqual(report["completion"]["completion_percent"], 100.0)
        self.assertEqual(report["completion"]["design_ready_eligible_artifact_count"], 7)
        self.assertEqual(report["completion"]["design_ready_artifact_percent"], 100.0)
        self.assertEqual(report["remaining_blockers"], [])
        self.assertEqual(report["status_report_hash"], compute_status_report_hash(report))

    def test_cli_writes_status_report_without_hard_gate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _ = self._write_runbook(temp_dir)
            output_path = Path(temp_dir) / "status.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_status_report.py",
                    "--runbook-path",
                    str(runbook_path),
                    "--readiness-path",
                    str(Path(temp_dir) / "missing-readiness.json"),
                    "--package-path",
                    str(Path(temp_dir) / "missing-package.json"),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-11T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            output_exists = output_path.exists()

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "fail")
        self.assertTrue(output_exists)

    def test_cli_require_design_partner_ready_exits_nonzero(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _ = self._write_runbook(temp_dir)
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_status_report.py",
                    "--runbook-path",
                    str(runbook_path),
                    "--readiness-path",
                    str(Path(temp_dir) / "missing-readiness.json"),
                    "--package-path",
                    str(Path(temp_dir) / "missing-package.json"),
                    "--output-path",
                    str(Path(temp_dir) / "status.json"),
                    "--require-design-partner-ready",
                    "--generated-at",
                    "2026-06-11T00:00:00Z",
                ],
                capture_output=True,
                check=False,
                text=True,
            )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
