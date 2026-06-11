from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.verify_preflight_payload import compute_preflight_payload_hash, verify_preflight_payload


class PreflightPayloadVerifierTest(unittest.TestCase):
    def _payload(self, *, ready: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": "api",
            "record_count": 12 if ready else 0,
            "planned_runs": 12,
            "preflight_summary": {
                "summary_version": "provider_preflight_v1",
                "phase": "collection_completed" if ready else "collector_health",
                "exit_code": 0 if ready else 3,
                "ready_for_design_partner": ready,
                "recommended_next_action": "promote_to_small_real_au_batch"
                if ready
                else "configure_missing_provider_credentials_or_collectors",
            },
            "preflight_audit_checklist": {
                "checklist_version": "provider_preflight_audit_checklist_v1",
                "overall_status": "pass" if ready else "fail",
                "ready_for_design_partner": ready,
                "worker_args": ["--mode", "api"],
                "evidence_refs": {"preflight_summary": "preflight_summary"},
                "checks": [],
                "run_totals": {"planned_runs": 12, "record_count": 12 if ready else 0},
                "blocking_reasons": [] if ready else ["openai.web_search.api:not_configured"],
            },
        }
        payload["preflight_payload_hash"] = compute_preflight_payload_hash(payload)
        return payload

    def test_valid_preflight_payload_hash_passes(self) -> None:
        payload = self._payload()
        result = verify_preflight_payload(payload)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertTrue(result["ready_for_design_partner"])
        self.assertEqual(result["preflight_payload_hash"], result["computed_payload_hash"])

    def test_failed_provider_preflight_can_still_be_auditable(self) -> None:
        payload = self._payload(ready=False)
        result = verify_preflight_payload(payload)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertFalse(result["ready_for_design_partner"])
        self.assertEqual(result["recommended_next_action"], "configure_missing_provider_credentials_or_collectors")

    def test_require_design_partner_ready_fails_failed_preflight(self) -> None:
        payload = self._payload(ready=False)
        result = verify_preflight_payload(payload, require_design_partner_ready=True)
        self.assertEqual(result["status"], "fail")
        self.assertIn("design_partner_not_ready", result["errors"])

    def test_hash_mismatch_fails(self) -> None:
        payload = self._payload()
        payload["record_count"] = 13
        result = verify_preflight_payload(payload)
        self.assertEqual(result["status"], "fail")
        self.assertIn("preflight_payload_hash_mismatch", result["errors"])

    def test_cli_reads_file_and_reports_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "api-preflight.json"
            payload = self._payload(ready=False)
            payload["preflight_output_path"] = str(path)
            payload["preflight_payload_hash"] = compute_preflight_payload_hash(payload)
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, "scripts/verify_preflight_payload.py", str(path)],
                capture_output=True,
                check=True,
                text=True,
            )

        verifier_payload = json.loads(result.stdout)
        self.assertEqual(verifier_payload["status"], "pass")
        self.assertTrue(verifier_payload["hash_valid"])
        self.assertTrue(verifier_payload["output_path_matches_file"])


if __name__ == "__main__":
    unittest.main()
