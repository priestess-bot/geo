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
from scripts.build_au_launch_remediation_plan import build_au_launch_remediation_plan
from scripts.verify_au_handoff_dossier import verify_au_handoff_dossier
from tests.test_au_launch_status import AuLaunchStatusTest


class AuHandoffDossierTest(unittest.TestCase):
    def setUp(self) -> None:
        self._launch_helper = AuLaunchStatusTest()
        self._launch_helper.setUp()

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

    def test_dossier_records_blocked_handoff_with_mapped_work_items(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = self._write_launch_status_and_plan(temp_dir, ready=False)
            markdown_path = Path(temp_dir) / "dossier.md"
            dossier = build_au_handoff_dossier(
                launch_status_path=launch_status_path,
                remediation_plan_path=remediation_plan_path,
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
        self.assertIn("AU 客户交付总包", render_au_handoff_markdown(dossier))
        self.assertEqual(dossier["handoff_dossier_hash"], compute_handoff_dossier_hash(dossier))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("customer_handoff_not_ready", hard_gate["errors"])

    def test_dossier_passes_customer_ready_when_launch_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = self._write_launch_status_and_plan(temp_dir, ready=True)
            dossier = build_au_handoff_dossier(
                launch_status_path=launch_status_path,
                remediation_plan_path=remediation_plan_path,
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
            dossier = build_au_handoff_dossier(
                launch_status_path=launch_status_path,
                remediation_plan_path=remediation_plan_path,
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
            dossier = build_au_handoff_dossier(
                launch_status_path=launch_status_path,
                remediation_plan_path=remediation_plan_path,
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
