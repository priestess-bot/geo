from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_evidence_package import (
    build_au_p0a_evidence_package,
    compute_package_payload_hash,
)
from scripts.build_au_p0a_runbook import build_au_p0a_runbook
from scripts.build_preflight_manifest import build_preflight_manifest
from scripts.run_au_p0a_runbook import run_au_p0a_runbook
from scripts.verify_au_p0a_evidence_package import verify_au_p0a_evidence_package
from scripts.verify_preflight_payload import compute_preflight_payload_hash, verify_preflight_payload


class AuP0aEvidencePackageVerifierTest(unittest.TestCase):
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

    def _package(self, temp_dir: str, *, complete: bool) -> dict[str, object]:
        artifact_dir = str(Path(temp_dir) / "runtime")
        runbook = build_au_p0a_runbook(artifact_dir=artifact_dir, generated_at="2026-06-11T00:00:00Z")
        runbook_path = Path(temp_dir) / "runbook.json"
        runbook_path.write_text(json.dumps(runbook), encoding="utf-8")
        execution_path = Path(temp_dir) / "execution.json"
        execution_path.write_text(
            json.dumps(
                run_au_p0a_runbook(
                    runbook_path=runbook_path,
                    output_path=execution_path,
                    env={
                        "PERPLEXITY_API_KEY": "perplexity-key",
                        "OPENAI_API_KEY": "openai-key",
                        "DATABASE_URL": "postgresql://user:pass@example.test/db",
                    }
                    if complete
                    else {},
                    generated_at="2026-06-11T00:00:00Z",
                )
            ),
            encoding="utf-8",
        )
        readiness_path = Path(temp_dir) / "readiness.json"
        readiness_path.write_text(
            json.dumps(
                {
                    "readiness_version": "au_p0a_readiness_v1",
                    "generated_at": "2026-06-11T00:00:00Z",
                    "phase": "full_batch",
                    "status": "pass" if complete else "fail",
                    "ready_to_run_phase": complete,
                    "errors": [] if complete else ["small_batch_json:preflight_payload_file_missing"],
                    "warnings": [],
                    "recommended_next_action": "run_full_au_p0a_batch"
                    if complete
                    else "run_or_fix_small_batch_and_manifest",
                }
            ),
            encoding="utf-8",
        )
        if complete:
            artifact_paths = runbook["artifact_paths"]
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
        return build_au_p0a_evidence_package(
            runbook_path=runbook_path,
            readiness_path=readiness_path,
            runbook_execution_path=execution_path,
            generated_at="2026-06-11T00:00:00Z",
        )

    def test_ready_package_passes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            package = self._package(temp_dir, complete=True)
            result = verify_au_p0a_evidence_package(package, require_design_partner_ready=True)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertTrue(result["ready_for_design_partner"])
        self.assertEqual(result["artifact_count"], 9)

    def test_hash_mismatch_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            package = self._package(temp_dir, complete=True)
            package["summary"]["artifact_count"] = 7  # type: ignore[index]
            result = verify_au_p0a_evidence_package(package)

        self.assertEqual(result["status"], "fail")
        self.assertIn("package_payload_hash_mismatch", result["errors"])
        self.assertIn("summary_artifact_count_mismatch", result["errors"])

    def test_summary_missing_artifacts_mismatch_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            package = self._package(temp_dir, complete=False)
            package["summary"]["missing_artifacts"] = []  # type: ignore[index]
            package["package_payload_hash"] = compute_package_payload_hash(package)
            result = verify_au_p0a_evidence_package(package)

        self.assertEqual(result["status"], "fail")
        self.assertIn("summary_missing_artifacts_mismatch", result["errors"])

    def test_require_design_partner_ready_fails_incomplete_package(self) -> None:
        with TemporaryDirectory() as temp_dir:
            package = self._package(temp_dir, complete=False)
            result = verify_au_p0a_evidence_package(package, require_design_partner_ready=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("design_partner_not_ready", result["errors"])

    def test_cli_reads_package_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "package.json"
            path.write_text(json.dumps(self._package(temp_dir, complete=True)), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/verify_au_p0a_evidence_package.py", str(path)],
                capture_output=True,
                check=True,
                text=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["hash_valid"])


if __name__ == "__main__":
    unittest.main()
