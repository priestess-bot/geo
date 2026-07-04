from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProductionV1GateContractsTest(unittest.TestCase):
    def test_checklist_tracks_plan_sections_and_deferred_upgrades(self) -> None:
        checklist = (ROOT / "docs/GEO-Production-v1执行进度-checklist-2026-07-05.md").read_text(encoding="utf-8")

        self.assertIn("GEO-Production-v1完整规划-2026-07-05.md", checklist)
        for item in ("W10-I01", "W2-I01a", "W3-I00", "W4-I01d", "W6-I01f", "W8-I03", "W9-I02"):
            self.assertIn(item, checklist)
        for upgrade in ("额外平台", "自动发布", "高级图谱", "复杂 SSO"):
            self.assertIn(upgrade, checklist)
        self.assertIn("Deferred upgrade", checklist)

    def test_makefile_exposes_production_v1_gate_targets(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        for target in (
            "lint:",
            "typecheck:",
            "rls-smoke:",
            "security-smoke:",
            "production-v1-e2e:",
            "enablement-v1-e2e:",
            "no-fixture-production-smoke:",
            "no-secret-leak-smoke:",
            "report-traceability-smoke:",
            "customer-access-negative-smoke:",
            "connector-real-smoke:",
            "ops-smoke:",
            "backup-smoke:",
            "production-v1-final-gate:",
        ):
            self.assertIn(target, makefile)
        self.assertIn("scripts/verify_production_v1_gate.py", makefile)

    def test_gate_script_checklist_mode_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/verify_production_v1_gate.py", "checklist"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn('"gate": "checklist"', result.stdout)
        self.assertIn('"status": "passed"', result.stdout)

    def test_gate_script_strict_mode_reports_pending_as_nonzero(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/verify_production_v1_gate.py", "production-v1-e2e"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('"status": "pending"', result.stdout)
        self.assertIn("W2-I01a", result.stdout)

    def test_gate_script_allow_pending_mode_is_available_for_progress_view(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/verify_production_v1_gate.py",
                "production-v1-e2e",
                "--allow-pending",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn('"status": "pending"', result.stdout)


if __name__ == "__main__":
    unittest.main()
