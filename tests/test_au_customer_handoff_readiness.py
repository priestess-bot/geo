from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_customer_handoff_readiness import (
    READINESS_VERSION,
    build_au_customer_handoff_readiness,
    compute_customer_handoff_readiness_hash,
)
from scripts.build_au_handoff_dossier import build_au_handoff_dossier
from scripts.verify_au_customer_handoff_readiness import verify_au_customer_handoff_readiness
from tests.test_au_handoff_dossier import AuHandoffDossierTest


class AuCustomerHandoffReadinessTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = AuHandoffDossierTest()
        self._helper.setUp()

    def _build_handoff_dossier(self, temp_dir: str, *, ready: bool) -> tuple[Path, dict[str, object]]:
        launch_status_path, remediation_plan_path = self._helper._write_launch_status_and_plan(temp_dir, ready=ready)
        checklist_path = self._helper._write_p0a_environment_checklist(temp_dir, ready=ready)
        p0a_execution_checklist_path = self._helper._write_p0a_execution_checklist(temp_dir, ready=ready)
        p0b_checklist_path = self._helper._write_p0b_google_execution_checklist(temp_dir, ready=ready)
        dossier_path = Path(temp_dir) / "dossier.json"
        dossier = build_au_handoff_dossier(
            launch_status_path=launch_status_path,
            remediation_plan_path=remediation_plan_path,
            p0a_environment_checklist_path=checklist_path,
            p0a_execution_checklist_path=p0a_execution_checklist_path,
            p0b_google_execution_checklist_path=p0b_checklist_path,
            output_path=dossier_path,
            markdown_output_path=Path(temp_dir) / "dossier.md",
            generated_at="2026-06-12T00:00:00Z",
        )
        dossier_path.write_text(json.dumps(dossier), encoding="utf-8")
        return dossier_path, dossier

    def test_readiness_records_blocked_customer_handoff_with_auditable_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, dossier = self._build_handoff_dossier(temp_dir, ready=False)
            readiness = build_au_customer_handoff_readiness(
                handoff_dossier_path=dossier_path,
                handoff_dossier=dossier,
                output_path=Path(temp_dir) / "readiness.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_customer_handoff_readiness(readiness)
            hard_gate = verify_au_customer_handoff_readiness(readiness, require_customer_ready=True)

        self.assertEqual(readiness["customer_handoff_readiness_version"], READINESS_VERSION)
        self.assertEqual(readiness["status"], "pass")
        self.assertTrue(readiness["readiness_audit_ready"])
        self.assertFalse(readiness["ready_for_customer_report_handoff"])
        self.assertEqual(readiness["summary"]["customer_report_handoff_readiness_percent"], 10.0)
        self.assertEqual(readiness["summary"]["structural_auditability_percent"], 100.0)
        self.assertEqual(readiness["summary"]["customer_ready_gate_count"], 1)
        self.assertEqual(readiness["summary"]["customer_total_gate_count"], 10)
        self.assertEqual(readiness["summary"]["blocked_customer_gate_count"], 9)
        self.assertEqual(readiness["summary"]["next_work_item_id"], "p0a_environment")
        self.assertEqual(readiness["summary"]["remaining_blocker_count"], 29)
        self.assertEqual(readiness["summary"]["external_dependency_blocker_count"], 29)
        self.assertIn("customer_report_handoff_gate", readiness["summary"]["blocked_customer_gate_ids"])
        self.assertEqual(
            readiness["runtime_endpoints"]["customer_handoff_readiness"],
            "GET /v1/customer-handoff-readiness/au",
        )
        self.assertIn("make au-customer-handoff-readiness", readiness["hard_gate_commands"])
        self.assertIn("make verify-au-customer-handoff-readiness", readiness["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-customer-ready") for command in readiness["hard_gate_commands"]))
        self.assertEqual(readiness["customer_handoff_readiness_hash"], compute_customer_handoff_readiness_hash(readiness))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("customer_handoff_not_ready", hard_gate["errors"])

    def test_readiness_passes_customer_gate_when_source_dossier_is_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, dossier = self._build_handoff_dossier(temp_dir, ready=True)
            readiness = build_au_customer_handoff_readiness(
                handoff_dossier_path=dossier_path,
                handoff_dossier=dossier,
                output_path=Path(temp_dir) / "readiness.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            hard_gate = verify_au_customer_handoff_readiness(readiness, require_customer_ready=True)

        self.assertTrue(readiness["ready_for_customer_report_handoff"])
        self.assertEqual(readiness["summary"]["customer_report_handoff_readiness_percent"], 100.0)
        self.assertEqual(readiness["summary"]["blocked_customer_gate_count"], 0)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_rejects_tampered_summary_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, dossier = self._build_handoff_dossier(temp_dir, ready=False)
            readiness = build_au_customer_handoff_readiness(
                handoff_dossier_path=dossier_path,
                handoff_dossier=dossier,
                output_path=Path(temp_dir) / "readiness.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            readiness["summary"]["customer_report_handoff_readiness_percent"] = 77.0
            readiness["customer_handoff_readiness_hash"] = compute_customer_handoff_readiness_hash(readiness)
            verification = verify_au_customer_handoff_readiness(readiness)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_customer_readiness_percent_mismatch", verification["errors"])

    def test_cli_writes_readiness_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, _ = self._build_handoff_dossier(temp_dir, ready=False)
            output_path = Path(temp_dir) / "readiness.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_customer_handoff_readiness.py",
                    "--handoff-dossier-path",
                    str(dossier_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertIn("au_customer_handoff_readiness_v1", result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(verify_au_customer_handoff_readiness(payload)["status"], "pass")
