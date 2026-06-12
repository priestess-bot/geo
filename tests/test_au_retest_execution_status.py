from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_retest_execution_status import build_au_retest_execution_status
from scripts.build_au_retest_scheduler_plan import build_au_retest_scheduler_plan
from scripts.build_preflight_manifest import build_preflight_manifest, compute_manifest_payload_hash
from scripts.verify_au_retest_execution_status import verify_au_retest_execution_status
from scripts.verify_preflight_payload import compute_preflight_payload_hash, verify_preflight_payload


class AuRetestExecutionStatusTest(unittest.TestCase):
    def _ready_payload(self, *, path: Path) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": "api",
            "planned_runs": 2400,
            "record_count": 2400,
            "success_count": 2400,
            "failure_count": 0,
            "preflight_output_path": str(path),
            "preflight_summary": {
                "summary_version": "provider_preflight_v1",
                "phase": "collection_completed",
                "exit_code": 0,
                "ready_for_design_partner": True,
                "planned_runs": 2400,
                "record_count": 2400,
                "success_count": 2400,
                "failure_count": 0,
                "cities": ["Australia", "Sydney", "Melbourne", "Brisbane"],
                "sample_size": 3,
                "prompt_limit": 100,
                "recommended_next_action": "promote_to_small_real_au_batch",
            },
            "preflight_audit_checklist": {
                "checklist_version": "provider_preflight_audit_checklist_v1",
                "overall_status": "pass",
                "ready_for_design_partner": True,
                "blocking_reasons": [],
                "worker_args": ["--mode", "api", "--sample-size", "3"],
                "evidence_refs": {"preflight_summary": "preflight_summary"},
                "checks": [],
                "run_totals": {"planned_runs": 2400, "record_count": 2400},
            },
        }
        payload["preflight_payload_hash"] = compute_preflight_payload_hash(payload)
        return payload

    def _write_ready_window(self, *, artifact_base: Path, payload_relpath: str, manifest_relpath: str) -> None:
        payload_path = artifact_base / payload_relpath
        manifest_path = artifact_base / manifest_relpath
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._ready_payload(path=payload_path)
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        verifier = verify_preflight_payload(payload, path=payload_path, require_design_partner_ready=True)
        manifest = build_preflight_manifest(
            preflight_path=payload_path,
            payload=payload,
            verifier=verifier,
            generated_at="2026-06-12T00:00:00Z",
        )
        manifest["preflight_payload"]["path"] = payload_relpath
        manifest["manifest_payload_hash"] = compute_manifest_payload_hash(manifest)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_missing_retest_artifacts_produce_fail_but_auditable_status(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            plan_path = base / "au-retest-scheduler-plan.json"
            output_path = base / "au-retest-execution-status.json"
            build_au_retest_scheduler_plan(output_path=plan_path, generated_at="2026-06-12T00:00:00Z")

            status = build_au_retest_execution_status(
                plan_path=plan_path,
                output_path=output_path,
                artifact_base_dir=base / "missing-artifacts",
                generated_at="2026-06-12T00:00:01Z",
            )
            result = verify_au_retest_execution_status(status, path=output_path)

        self.assertEqual(status["status"], "fail")
        self.assertTrue(status["execution_status_report_ready"])
        self.assertFalse(status["retest_execution_ready"])
        self.assertFalse(status["comparison_allowed"])
        self.assertEqual(status["next_action"], "run_retest_window:baseline")
        self.assertEqual(status["summary"]["window_count"], 4)
        self.assertEqual(status["summary"]["ready_window_count"], 0)
        self.assertEqual(status["summary"]["missing_artifact_count"], 8)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])

    def test_ready_baseline_advances_next_window_without_enabling_comparison(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            plan_path = base / "au-retest-scheduler-plan.json"
            build_au_retest_scheduler_plan(output_path=plan_path, generated_at="2026-06-12T00:00:00Z")
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            baseline_payload, baseline_manifest = plan["timeline"][0]["evidence_outputs"]
            self._write_ready_window(
                artifact_base=base,
                payload_relpath=baseline_payload,
                manifest_relpath=baseline_manifest,
            )

            status = build_au_retest_execution_status(
                plan_path=plan_path,
                artifact_base_dir=base,
                generated_at="2026-06-12T00:00:01Z",
            )
            result = verify_au_retest_execution_status(status)

        self.assertEqual(status["status"], "fail")
        self.assertEqual(status["summary"]["ready_window_count"], 1)
        self.assertEqual(status["summary"]["missing_artifact_count"], 6)
        self.assertTrue(status["summary"]["baseline_ready"])
        self.assertFalse(status["comparison_allowed"])
        self.assertEqual(status["next_action"], "run_retest_window:t_plus_7")
        self.assertEqual(status["windows"][0]["payload"]["status"], "pass")
        self.assertEqual(status["windows"][0]["manifest"]["status"], "pass")
        self.assertEqual(result["status"], "pass")

    def test_ready_baseline_and_one_retest_allow_comparison(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            plan_path = base / "au-retest-scheduler-plan.json"
            build_au_retest_scheduler_plan(output_path=plan_path, generated_at="2026-06-12T00:00:00Z")
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            for window in plan["timeline"][:2]:
                payload_path, manifest_path = window["evidence_outputs"]
                self._write_ready_window(
                    artifact_base=base,
                    payload_relpath=payload_path,
                    manifest_relpath=manifest_path,
                )

            status = build_au_retest_execution_status(
                plan_path=plan_path,
                artifact_base_dir=base,
                generated_at="2026-06-12T00:00:01Z",
            )
            result = verify_au_retest_execution_status(status)

        self.assertEqual(status["status"], "fail")
        self.assertEqual(status["summary"]["ready_window_count"], 2)
        self.assertTrue(status["comparison_allowed"])
        self.assertEqual(status["next_action"], "run_retest_window:t_plus_14")
        self.assertEqual(result["status"], "pass")

    def test_verifier_rejects_tampered_status_hash(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            plan_path = base / "au-retest-scheduler-plan.json"
            build_au_retest_scheduler_plan(output_path=plan_path, generated_at="2026-06-12T00:00:00Z")
            status = build_au_retest_execution_status(
                plan_path=plan_path,
                artifact_base_dir=base / "missing-artifacts",
                generated_at="2026-06-12T00:00:01Z",
            )
            status["summary"]["missing_artifact_count"] = 0
            result = verify_au_retest_execution_status(status)

        self.assertEqual(result["status"], "fail")
        self.assertIn("retest_execution_status_hash_mismatch", result["errors"])

    def test_cli_writes_and_verifies_current_missing_artifact_status(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            plan_path = base / "au-retest-scheduler-plan.json"
            output_path = base / "au-retest-execution-status.json"
            build_au_retest_scheduler_plan(output_path=plan_path, generated_at="2026-06-12T00:00:00Z")

            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_retest_execution_status.py",
                    "--plan-path",
                    str(plan_path),
                    "--output-path",
                    str(output_path),
                    "--artifact-base-dir",
                    str(base / "missing-artifacts"),
                    "--generated-at",
                    "2026-06-12T00:00:01Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            verify_result = subprocess.run(
                [sys.executable, "scripts/verify_au_retest_execution_status.py", str(output_path)],
                capture_output=True,
                check=True,
                text=True,
            )
            status = json.loads(build_result.stdout)
            verifier = json.loads(verify_result.stdout)

        self.assertEqual(status["status"], "fail")
        self.assertEqual(verifier["status"], "pass")
        self.assertEqual(verifier["missing_artifact_count"], 8)


if __name__ == "__main__":
    unittest.main()
