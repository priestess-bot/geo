from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_handoff_dossier import (
    DOSSIER_VERSION,
    build_au_handoff_dossier,
    compute_handoff_dossier_hash,
    render_au_handoff_markdown,
)
from scripts.build_au_p0a_environment_checklist import build_au_p0a_environment_checklist
from scripts.build_au_p0a_execution_checklist import build_au_p0a_execution_checklist
from scripts.build_au_launch_remediation_plan import build_au_launch_remediation_plan
from scripts.build_au_p0b_google_execution_checklist import build_au_p0b_google_execution_checklist
from scripts.verify_au_handoff_dossier import verify_au_handoff_dossier
from tests.test_au_p0a_environment_checklist import AuP0aEnvironmentChecklistTest
from tests.test_au_p0a_execution_checklist import AuP0aExecutionChecklistTest
from tests.test_au_launch_status import AuLaunchStatusTest


class AuHandoffDossierTest(unittest.TestCase):
    def setUp(self) -> None:
        self._launch_helper = AuLaunchStatusTest()
        self._launch_helper.setUp()
        self._environment_helper = AuP0aEnvironmentChecklistTest()
        self._execution_helper = AuP0aExecutionChecklistTest()

    def _write_launch_status_and_plan(self, temp_dir: str, *, ready: bool) -> tuple[Path, Path]:
        p0a_status_path = self._launch_helper._write_p0a_status(temp_dir, ready=ready)
        p0c_package_path = self._launch_helper._write_p0c_package(temp_dir)
        runbook_path, execution_path, p0b_status_path, p0b_package_path = self._launch_helper._write_p0b_status_and_package(
            temp_dir,
            google_ready=ready,
        )
        from scripts.build_au_launch_status import build_au_launch_status

        launch_status = build_au_launch_status(
            p0a_status_path=p0a_status_path,
            p0b_google_status_path=p0b_status_path,
            p0b_google_package_path=p0b_package_path,
            p0b_google_runbook_path=runbook_path,
            p0b_google_execution_path=execution_path,
            p0c_report_package_path=p0c_package_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        launch_status_path = Path(temp_dir) / "launch-status.json"
        launch_status_path.write_text(json.dumps(launch_status), encoding="utf-8")
        remediation_plan = build_au_launch_remediation_plan(
            launch_status=launch_status,
            launch_status_path=launch_status_path,
            output_path=Path(temp_dir) / "remediation-plan.json",
            generated_at="2026-06-12T00:00:00Z",
        )
        remediation_plan_path = Path(temp_dir) / "remediation-plan.json"
        remediation_plan_path.write_text(json.dumps(remediation_plan), encoding="utf-8")
        return launch_status_path, remediation_plan_path

    def _write_p0b_google_execution_checklist(self, temp_dir: str, *, ready: bool = False) -> Path:
        runbook_path, execution_path, p0b_status_path, p0b_package_path = self._launch_helper._write_p0b_status_and_package(
            temp_dir,
            google_ready=ready,
        )
        checklist_path = Path(temp_dir) / "p0b-google-execution-checklist.json"
        checklist = build_au_p0b_google_execution_checklist(
            runbook_path=runbook_path,
            execution_path=execution_path,
            playwright_env_path=Path(temp_dir) / "runtime" / "au-p0b-google-playwright-env-latest.json",
            status_report_path=p0b_status_path,
            package_path=p0b_package_path,
            env_file_path=Path(temp_dir) / "missing-google.env",
            output_path=checklist_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        checklist_path.write_text(json.dumps(checklist), encoding="utf-8")
        return checklist_path

    def _write_p0a_environment_checklist(self, temp_dir: str, *, ready: bool = False) -> Path:
        runbook_path = self._environment_helper._write_runbook(temp_dir)
        env_path = self._environment_helper._write_env_report(temp_dir, runbook_path, ready=ready)
        checklist_path = Path(temp_dir) / "p0a-environment-checklist.json"
        checklist = build_au_p0a_environment_checklist(
            runbook_path=runbook_path,
            environment_path=env_path,
            status_path=Path(temp_dir) / "missing-p0a-status.json",
            env_file_path=Path(temp_dir) / "missing.env",
            output_path=checklist_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        checklist_path.write_text(json.dumps(checklist), encoding="utf-8")
        return checklist_path

    def _write_p0a_execution_checklist(self, temp_dir: str, *, ready: bool = False) -> Path:
        runbook_path, runbook = self._execution_helper._write_runbook(temp_dir)
        environment_path = Path(temp_dir) / "p0a-execution-env.json"
        execution_path = Path(temp_dir) / "p0a-runbook-execution.json"
        readiness_path = Path(temp_dir) / "p0a-readiness.json"
        package_path = Path(temp_dir) / "p0a-package.json"
        status_path = Path(temp_dir) / "p0a-status.json"
        self._execution_helper._write_env_report(environment_path, runbook_path, ready=ready)
        self._execution_helper._write_runbook_execution(execution_path, runbook_path, ready=ready)
        self._execution_helper._write_readiness(readiness_path, ready=ready)
        if ready:
            artifact_paths = runbook["artifact_paths"]  # type: ignore[index]
            self._execution_helper._write_payload_and_manifest(
                Path(artifact_paths["preflight_json"]),  # type: ignore[index]
                Path(artifact_paths["preflight_manifest"]),  # type: ignore[index]
                planned_runs=6,
                record_count=6,
                prompt_limit=1,
                cities=["Sydney"],
            )
            self._execution_helper._write_payload_and_manifest(
                Path(artifact_paths["small_batch_json"]),  # type: ignore[index]
                Path(artifact_paths["small_batch_manifest"]),  # type: ignore[index]
                planned_runs=30,
                record_count=30,
                prompt_limit=5,
                cities=["Sydney"],
            )
            self._execution_helper._write_payload_and_manifest(
                Path(artifact_paths["full_batch_json"]),  # type: ignore[index]
                Path(artifact_paths["full_batch_manifest"]),  # type: ignore[index]
                planned_runs=2400,
                record_count=2400,
                prompt_limit=100,
                cities=["Australia", "Sydney", "Melbourne", "Brisbane"],
            )
        self._execution_helper._write_package_and_status(
            runbook_path=runbook_path,
            environment_path=environment_path,
            execution_path=execution_path,
            readiness_path=readiness_path,
            package_path=package_path,
            status_path=status_path,
            ready=ready,
        )
        checklist_path = Path(temp_dir) / "p0a-execution-checklist.json"
        checklist = build_au_p0a_execution_checklist(
            runbook_path=runbook_path,
            environment_path=environment_path,
            runbook_execution_path=execution_path,
            readiness_path=readiness_path,
            package_path=package_path,
            status_path=status_path,
            output_path=checklist_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        checklist_path.write_text(json.dumps(checklist), encoding="utf-8")
        return checklist_path

    def test_dossier_records_blocked_handoff_with_mapped_work_items(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = self._write_launch_status_and_plan(temp_dir, ready=False)
            checklist_path = self._write_p0a_environment_checklist(temp_dir)
            p0a_execution_checklist_path = self._write_p0a_execution_checklist(temp_dir)
            p0b_checklist_path = self._write_p0b_google_execution_checklist(temp_dir)
            markdown_path = Path(temp_dir) / "dossier.md"
            dossier = build_au_handoff_dossier(
                launch_status_path=launch_status_path,
                remediation_plan_path=remediation_plan_path,
                p0a_environment_checklist_path=checklist_path,
                p0a_execution_checklist_path=p0a_execution_checklist_path,
                p0b_google_execution_checklist_path=p0b_checklist_path,
                output_path=Path(temp_dir) / "dossier.json",
                markdown_output_path=markdown_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_handoff_dossier(dossier)
            hard_gate = verify_au_handoff_dossier(dossier, require_customer_ready=True)

        self.assertEqual(dossier["handoff_dossier_version"], DOSSIER_VERSION)
        self.assertEqual(dossier["status"], "pass")
        self.assertTrue(dossier["handoff_dossier_ready"])
        self.assertFalse(dossier["ready_for_customer_report_handoff"])
        self.assertEqual(dossier["summary"]["handoff_posture"], "blocked_external_dependencies")
        self.assertEqual(dossier["summary"]["remaining_blocker_count"], 29)
        self.assertEqual(dossier["summary"]["unmapped_blocker_count"], 0)
        self.assertEqual(dossier["summary"]["work_item_count"], len(dossier["work_items"]))
        self.assertGreaterEqual(dossier["summary"]["work_item_count"], 8)
        self.assertEqual(dossier["summary"]["next_work_item_id"], "p0a_environment")
        self.assertEqual(dossier["next_work_item"]["id"], "p0a_environment")
        self.assertEqual(dossier["runtime_endpoints"]["launch_status"], "GET /v1/launch-status/au")
        self.assertEqual(
            dossier["runtime_endpoints"]["p0a_environment_checklist"],
            "GET /v1/p0a-environment-checklist/au",
        )
        self.assertEqual(
            dossier["runtime_endpoints"]["p0b_google_execution_checklist"],
            "GET /v1/p0b-google-execution-checklist/au",
        )
        self.assertEqual(
            dossier["runtime_endpoints"]["au_retest_scheduler_plan"],
            "GET /v1/au-retest-scheduler-plan",
        )
        self.assertEqual(
            dossier["runtime_endpoints"]["au_retest_execution_status"],
            "GET /v1/au-retest-execution-status",
        )
        self.assertFalse(dossier["p0a_environment_checklist"]["environment_checklist_ready"])
        self.assertEqual(dossier["p0a_environment_checklist"]["missing_required_count"], 3)
        self.assertEqual(dossier["summary"]["p0a_missing_required_environment_count"], 3)
        self.assertFalse(dossier["p0a_execution_checklist"]["p0a_execution_checklist_ready"])
        self.assertEqual(dossier["summary"]["p0a_execution_remaining_blocker_count"], 22)
        self.assertFalse(dossier["p0b_google_execution_checklist"]["google_execution_checklist_ready"])
        self.assertEqual(dossier["summary"]["p0b_google_remaining_blocker_count"], 7)
        markdown = render_au_handoff_markdown(dossier)
        self.assertIn("AU 客户交付总包", markdown)
        self.assertIn("P0a 环境清单", markdown)
        self.assertIn("P0a 执行清单", markdown)
        self.assertIn("P0b Google 执行清单", markdown)
        self.assertIn("PERPLEXITY_API_KEY", markdown)
        self.assertEqual(dossier["handoff_dossier_hash"], compute_handoff_dossier_hash(dossier))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("customer_handoff_not_ready", hard_gate["errors"])

    def test_dossier_passes_customer_ready_when_launch_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = self._write_launch_status_and_plan(temp_dir, ready=True)
            checklist_path = self._write_p0a_environment_checklist(temp_dir, ready=True)
            p0a_execution_checklist_path = self._write_p0a_execution_checklist(temp_dir, ready=True)
            p0b_checklist_path = self._write_p0b_google_execution_checklist(temp_dir, ready=True)
            dossier = build_au_handoff_dossier(
                launch_status_path=launch_status_path,
                remediation_plan_path=remediation_plan_path,
                p0a_environment_checklist_path=checklist_path,
                p0a_execution_checklist_path=p0a_execution_checklist_path,
                p0b_google_execution_checklist_path=p0b_checklist_path,
                output_path=Path(temp_dir) / "dossier.json",
                markdown_output_path=Path(temp_dir) / "dossier.md",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_handoff_dossier(dossier, require_customer_ready=True)

        self.assertEqual(dossier["status"], "pass")
        self.assertTrue(dossier["ready_for_customer_report_handoff"])
        self.assertEqual(dossier["summary"]["handoff_posture"], "ready_for_customer_report_handoff")
        self.assertEqual(dossier["summary"]["remaining_blocker_count"], 0)
        self.assertEqual(dossier["summary"]["next_work_item_id"], "none")
        self.assertEqual(verification["status"], "pass")

    def test_verifier_detects_hash_and_markdown_tampering(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = self._write_launch_status_and_plan(temp_dir, ready=False)
            checklist_path = self._write_p0a_environment_checklist(temp_dir)
            p0a_execution_checklist_path = self._write_p0a_execution_checklist(temp_dir)
            p0b_checklist_path = self._write_p0b_google_execution_checklist(temp_dir)
            dossier = build_au_handoff_dossier(
                launch_status_path=launch_status_path,
                remediation_plan_path=remediation_plan_path,
                p0a_environment_checklist_path=checklist_path,
                p0a_execution_checklist_path=p0a_execution_checklist_path,
                p0b_google_execution_checklist_path=p0b_checklist_path,
                output_path=Path(temp_dir) / "dossier.json",
                markdown_output_path=Path(temp_dir) / "dossier.md",
                generated_at="2026-06-12T00:00:00Z",
            )
            dossier["markdown_report"]["content_sha256"] = "tampered"  # type: ignore[index]
            verification = verify_au_handoff_dossier(dossier)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("handoff_dossier_hash_mismatch", verification["errors"])
        self.assertIn("markdown_content_sha256_mismatch", verification["errors"])

    def test_verifier_accepts_covered_count_when_unmapped_blockers_exist(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = self._write_launch_status_and_plan(temp_dir, ready=False)
            checklist_path = self._write_p0a_environment_checklist(temp_dir)
            p0a_execution_checklist_path = self._write_p0a_execution_checklist(temp_dir)
            p0b_checklist_path = self._write_p0b_google_execution_checklist(temp_dir)
            dossier = build_au_handoff_dossier(
                launch_status_path=launch_status_path,
                remediation_plan_path=remediation_plan_path,
                p0a_environment_checklist_path=checklist_path,
                p0a_execution_checklist_path=p0a_execution_checklist_path,
                p0b_google_execution_checklist_path=p0b_checklist_path,
                output_path=Path(temp_dir) / "dossier.json",
                markdown_output_path=Path(temp_dir) / "dossier.md",
                generated_at="2026-06-12T00:00:00Z",
            )
            dossier["summary"]["covered_blocker_count"] = 28  # type: ignore[index]
            dossier["summary"]["unmapped_blocker_count"] = 1  # type: ignore[index]
            dossier["remediation_plan_verifier"]["unmapped_blocker_count"] = 1  # type: ignore[index]
            dossier["handoff_dossier_hash"] = compute_handoff_dossier_hash(dossier)
            verification = verify_au_handoff_dossier(dossier)

        self.assertEqual(verification["status"], "fail")
        self.assertNotIn("summary_covered_blocker_count_mismatch", verification["errors"])
        self.assertIn("handoff_dossier_ready_mismatch", verification["errors"])

    def test_cli_writes_json_and_markdown(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = self._write_launch_status_and_plan(temp_dir, ready=False)
            checklist_path = self._write_p0a_environment_checklist(temp_dir)
            p0a_execution_checklist_path = self._write_p0a_execution_checklist(temp_dir)
            p0b_checklist_path = self._write_p0b_google_execution_checklist(temp_dir)
            output_path = Path(temp_dir) / "dossier.json"
            markdown_path = Path(temp_dir) / "dossier.md"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_handoff_dossier.py",
                    "--launch-status-path",
                    str(launch_status_path),
                    "--remediation-plan-path",
                    str(remediation_plan_path),
                    "--p0a-environment-checklist-path",
                    str(checklist_path),
                    "--p0a-execution-checklist-path",
                    str(p0a_execution_checklist_path),
                    "--p0b-google-execution-checklist-path",
                    str(p0b_checklist_path),
                    "--output-path",
                    str(output_path),
                    "--markdown-output-path",
                    str(markdown_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            verifier = subprocess.run(
                [sys.executable, "scripts/verify_au_handoff_dossier.py", str(output_path)],
                capture_output=True,
                check=True,
                text=True,
            )
            output_exists = output_path.exists()
            markdown_exists = markdown_path.exists()
            markdown_text = markdown_path.read_text(encoding="utf-8")

        payload = json.loads(result.stdout)
        verifier_payload = json.loads(verifier.stdout)
        self.assertTrue(output_exists)
        self.assertTrue(markdown_exists)
        self.assertEqual(payload["handoff_dossier_hash"], compute_handoff_dossier_hash(payload))
        self.assertEqual(verifier_payload["status"], "pass")
        self.assertIn("AU 客户交付总包", markdown_text)


if __name__ == "__main__":
    unittest.main()
