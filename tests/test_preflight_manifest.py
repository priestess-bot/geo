from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_preflight_manifest import (
    MANIFEST_VERSION,
    build_preflight_manifest,
    compute_manifest_payload_hash,
)
from scripts.verify_preflight_payload import compute_preflight_payload_hash, verify_preflight_payload


class PreflightManifestTest(unittest.TestCase):
    def _payload(self, *, ready: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": "api",
            "planned_runs": 6,
            "record_count": 0 if not ready else 6,
            "success_count": 0 if not ready else 6,
            "failure_count": 0,
            "preflight_summary": {
                "summary_version": "provider_preflight_v1",
                "phase": "collector_health" if not ready else "collection_completed",
                "exit_code": 3 if not ready else 0,
                "ready_for_design_partner": ready,
                "planned_runs": 6,
                "record_count": 0 if not ready else 6,
                "success_count": 0 if not ready else 6,
                "failure_count": 0,
                "cities": ["Sydney"],
                "sample_size": 3,
                "prompt_limit": 1,
                "recommended_next_action": "configure_missing_provider_credentials_or_collectors"
                if not ready
                else "promote_to_small_real_au_batch",
            },
            "preflight_audit_checklist": {
                "checklist_version": "provider_preflight_audit_checklist_v1",
                "overall_status": "fail" if not ready else "pass",
                "ready_for_design_partner": ready,
                "blocking_reasons": ["openai.web_search.api:not_configured"] if not ready else [],
                "worker_args": ["--mode", "api", "--sample-size", "3"],
                "evidence_refs": {"preflight_summary": "preflight_summary"},
                "checks": [],
                "run_totals": {"planned_runs": 6, "record_count": 0 if not ready else 6},
            },
        }
        payload["preflight_payload_hash"] = compute_preflight_payload_hash(payload)
        return payload

    def test_build_manifest_records_file_and_verifier_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "api-preflight.json"
            payload = self._payload()
            path.write_text(json.dumps(payload), encoding="utf-8")
            verifier = verify_preflight_payload(payload, path=path)

            manifest = build_preflight_manifest(
                preflight_path=path,
                payload=payload,
                verifier=verifier,
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(manifest["manifest_version"], MANIFEST_VERSION)
        self.assertEqual(manifest["generated_at"], "2026-06-11T00:00:00Z")
        self.assertEqual(manifest["preflight_payload"]["payload_hash"], payload["preflight_payload_hash"])
        self.assertEqual(
            manifest["preflight_payload"]["file_sha256"],
            hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest(),
        )
        self.assertEqual(manifest["verifier"]["status"], "pass")
        self.assertTrue(manifest["verifier"]["hash_valid"])
        self.assertFalse(manifest["run_summary"]["ready_for_design_partner"])
        self.assertEqual(manifest["audit_checklist"]["blocking_reasons"], ["openai.web_search.api:not_configured"])
        self.assertEqual(manifest["manifest_payload_hash"], compute_manifest_payload_hash(manifest))

    def test_cli_writes_manifest_for_failed_but_auditable_preflight(self) -> None:
        with TemporaryDirectory() as temp_dir:
            preflight_path = Path(temp_dir) / "api-preflight.json"
            manifest_path = Path(temp_dir) / "manifest.json"
            payload = self._payload()
            payload["preflight_output_path"] = str(preflight_path)
            payload["preflight_payload_hash"] = compute_preflight_payload_hash(payload)
            preflight_path.write_text(json.dumps(payload), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_preflight_manifest.py",
                    str(preflight_path),
                    "--manifest-path",
                    str(manifest_path),
                    "--generated-at",
                    "2026-06-11T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            stdout_manifest = json.loads(result.stdout)
            written_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(stdout_manifest, written_manifest)
        self.assertEqual(written_manifest["verifier"]["status"], "pass")
        self.assertTrue(written_manifest["verifier"]["output_path_matches_file"])
        self.assertFalse(written_manifest["run_summary"]["ready_for_design_partner"])

    def test_cli_require_design_partner_ready_fails_manifest_when_not_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            preflight_path = Path(temp_dir) / "api-preflight.json"
            manifest_path = Path(temp_dir) / "manifest.json"
            payload = self._payload()
            preflight_path.write_text(json.dumps(payload), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_preflight_manifest.py",
                    str(preflight_path),
                    "--manifest-path",
                    str(manifest_path),
                    "--require-design-partner-ready",
                    "--generated-at",
                    "2026-06-11T00:00:00Z",
                ],
                capture_output=True,
                text=True,
            )
            manifest_exists = manifest_path.exists()

        self.assertEqual(result.returncode, 2)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["verifier"]["status"], "fail")
        self.assertIn("design_partner_not_ready", manifest["verifier"]["errors"])
        self.assertTrue(manifest_exists)


if __name__ == "__main__":
    unittest.main()
