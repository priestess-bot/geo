from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_runbook import build_au_p0a_runbook
from scripts.build_preflight_manifest import build_preflight_manifest
from scripts.verify_au_p0a_readiness import verify_au_p0a_readiness
from scripts.verify_preflight_payload import compute_preflight_payload_hash, verify_preflight_payload


class AuP0aReadinessTest(unittest.TestCase):
    def _env(self) -> dict[str, str]:
        return {
            "PERPLEXITY_API_KEY": "test-perplexity",
            "OPENAI_API_KEY": "test-openai",
            "DATABASE_URL": "postgresql://geno:test@localhost:5432/geno",
        }

    def _payload(self, *, path: Path, ready: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": "api",
            "planned_runs": 6,
            "record_count": 6 if ready else 0,
            "success_count": 6 if ready else 0,
            "failure_count": 0,
            "preflight_output_path": str(path),
            "preflight_summary": {
                "summary_version": "provider_preflight_v1",
                "phase": "collection_completed" if ready else "collector_health",
                "exit_code": 0 if ready else 3,
                "ready_for_design_partner": ready,
                "planned_runs": 6,
                "record_count": 6 if ready else 0,
                "success_count": 6 if ready else 0,
                "failure_count": 0,
                "cities": ["Sydney"],
                "sample_size": 3,
                "prompt_limit": 1,
                "recommended_next_action": "promote_to_small_real_au_batch"
                if ready
                else "configure_missing_provider_credentials_or_collectors",
            },
            "preflight_audit_checklist": {
                "checklist_version": "provider_preflight_audit_checklist_v1",
                "overall_status": "pass" if ready else "fail",
                "ready_for_design_partner": ready,
                "blocking_reasons": [] if ready else ["openai.web_search.api:not_configured"],
                "worker_args": ["--mode", "api", "--sample-size", "3"],
                "evidence_refs": {"preflight_summary": "preflight_summary"},
                "checks": [],
                "run_totals": {"planned_runs": 6, "record_count": 6 if ready else 0},
            },
        }
        payload["preflight_payload_hash"] = compute_preflight_payload_hash(payload)
        return payload

    def _write_runbook(self, temp_dir: str) -> tuple[Path, dict[str, object]]:
        artifact_dir = str(Path(temp_dir) / "runtime")
        runbook = build_au_p0a_runbook(
            artifact_dir=artifact_dir,
            generated_at="2026-06-11T00:00:00Z",
        )
        path = Path(temp_dir) / "runbook.json"
        path.write_text(json.dumps(runbook), encoding="utf-8")
        return path, runbook

    def _write_payload_and_manifest(self, payload_path: Path, manifest_path: Path, *, ready: bool = True) -> None:
        payload = self._payload(path=payload_path, ready=ready)
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        verifier = verify_preflight_payload(
            payload,
            path=payload_path,
            require_design_partner_ready=ready,
        )
        manifest = build_preflight_manifest(
            preflight_path=payload_path,
            payload=payload,
            verifier=verifier,
            generated_at="2026-06-11T00:00:00Z",
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_preflight_phase_requires_provider_env_and_valid_runbook(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            result = verify_au_p0a_readiness(
                phase="preflight",
                runbook_path=runbook_path,
                env={},
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["ready_to_run_phase"])
        self.assertIn("required_env_missing:PERPLEXITY_API_KEY", result["errors"])
        self.assertEqual(result["runbook"]["status"], "pass")
        self.assertEqual(result["recommended_next_action"], "configure_required_environment")

    def test_preflight_phase_passes_with_required_env_and_valid_runbook(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            result = verify_au_p0a_readiness(
                phase="preflight",
                runbook_path=runbook_path,
                env=self._env(),
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["ready_to_run_phase"])
        self.assertEqual(result["recommended_next_action"], "run_make_api_preflight")
        self.assertEqual(result["environment"]["missing_required"], [])
        self.assertIn("recommended_env_missing:OBJECT_STORE_ENDPOINT", result["warnings"])

    def test_small_batch_phase_requires_ready_preflight_payload_and_manifest(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, runbook = self._write_runbook(temp_dir)
            artifact_paths = runbook["artifact_paths"]  # type: ignore[index]
            preflight_path = Path(artifact_paths["preflight_json"])  # type: ignore[index]
            manifest_path = Path(artifact_paths["preflight_manifest"])  # type: ignore[index]
            self._write_payload_and_manifest(preflight_path, manifest_path, ready=True)

            result = verify_au_p0a_readiness(
                phase="small_batch",
                runbook_path=runbook_path,
                env=self._env(),
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["gates"]["preflight_json"]["ready_for_design_partner"])
        self.assertTrue(result["gates"]["preflight_manifest"]["ready_for_design_partner"])
        self.assertEqual(result["recommended_next_action"], "run_small_au_p0a_batch")

    def test_full_batch_phase_fails_until_small_batch_manifest_is_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, runbook = self._write_runbook(temp_dir)
            artifact_paths = runbook["artifact_paths"]  # type: ignore[index]
            self._write_payload_and_manifest(
                Path(artifact_paths["preflight_json"]),  # type: ignore[index]
                Path(artifact_paths["preflight_manifest"]),  # type: ignore[index]
                ready=True,
            )

            result = verify_au_p0a_readiness(
                phase="full_batch",
                runbook_path=runbook_path,
                env=self._env(),
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(result["status"], "fail")
        self.assertIn("small_batch_json:preflight_payload_file_missing", result["errors"])
        self.assertIn("small_batch_manifest:preflight_manifest_file_missing", result["errors"])
        self.assertEqual(result["recommended_next_action"], "run_or_fix_small_batch_and_manifest")

    def test_cli_writes_readiness_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            output_path = Path(temp_dir) / "readiness.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0a_readiness.py",
                    "--phase",
                    "preflight",
                    "--runbook-path",
                    str(runbook_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-11T00:00:00Z",
                ],
                capture_output=True,
                env=self._env(),
                text=True,
            )
            stdout_payload = json.loads(result.stdout)
            written_payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0)
        self.assertEqual(stdout_payload, written_payload)
        self.assertEqual(written_payload["status"], "pass")


if __name__ == "__main__":
    unittest.main()
