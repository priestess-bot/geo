from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_evidence_package import (
    PACKAGE_VERSION,
    build_au_p0a_evidence_package,
    compute_package_payload_hash,
)
from scripts.build_au_p0a_runbook import build_au_p0a_runbook
from scripts.build_preflight_manifest import build_preflight_manifest
from scripts.verify_preflight_payload import compute_preflight_payload_hash, verify_preflight_payload


class AuP0aEvidencePackageTest(unittest.TestCase):
    def _payload(
        self,
        *,
        path: Path,
        planned_runs: int,
        record_count: int,
        prompt_limit: int,
        cities: list[str],
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": "api",
            "planned_runs": planned_runs,
            "record_count": record_count,
            "success_count": record_count,
            "failure_count": 0,
            "preflight_output_path": str(path),
            "preflight_summary": {
                "summary_version": "provider_preflight_v1",
                "phase": "collection_completed",
                "exit_code": 0,
                "ready_for_design_partner": True,
                "planned_runs": planned_runs,
                "record_count": record_count,
                "success_count": record_count,
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
                "run_totals": {"planned_runs": planned_runs, "record_count": record_count},
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

    def _write_readiness(self, path: Path, *, status: str = "pass") -> None:
        payload = {
            "readiness_version": "au_p0a_readiness_v1",
            "generated_at": "2026-06-11T00:00:00Z",
            "phase": "full_batch",
            "status": status,
            "ready_to_run_phase": status == "pass",
            "errors": [] if status == "pass" else ["small_batch_json:preflight_payload_file_missing"],
            "warnings": [],
            "recommended_next_action": "run_full_au_p0a_batch" if status == "pass" else "run_or_fix_small_batch_and_manifest",
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _write_payload_and_manifest(
        self,
        payload_path: Path,
        manifest_path: Path,
        *,
        planned_runs: int,
        record_count: int,
        prompt_limit: int,
        cities: list[str],
    ) -> None:
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._payload(
            path=payload_path,
            planned_runs=planned_runs,
            record_count=record_count,
            prompt_limit=prompt_limit,
            cities=cities,
        )
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        verifier = verify_preflight_payload(payload, path=payload_path, require_design_partner_ready=True)
        manifest = build_preflight_manifest(
            preflight_path=payload_path,
            payload=payload,
            verifier=verifier,
            generated_at="2026-06-11T00:00:00Z",
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_package_records_missing_batch_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            readiness_path = Path(temp_dir) / "readiness.json"
            self._write_readiness(readiness_path, status="fail")

            package = build_au_p0a_evidence_package(
                runbook_path=runbook_path,
                readiness_path=readiness_path,
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(package["package_version"], PACKAGE_VERSION)
        self.assertEqual(package["status"], "fail")
        self.assertIn("preflight_json", package["summary"]["missing_artifacts"])
        self.assertIn("full_batch_manifest", package["summary"]["failed_artifacts"])
        self.assertFalse(package["ready_for_design_partner"])
        self.assertEqual(package["package_payload_hash"], compute_package_payload_hash(package))

    def test_package_passes_when_all_artifacts_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, runbook = self._write_runbook(temp_dir)
            readiness_path = Path(temp_dir) / "readiness.json"
            self._write_readiness(readiness_path)
            artifact_paths = runbook["artifact_paths"]  # type: ignore[index]
            self._write_payload_and_manifest(
                Path(artifact_paths["preflight_json"]),  # type: ignore[index]
                Path(artifact_paths["preflight_manifest"]),  # type: ignore[index]
                planned_runs=6,
                record_count=6,
                prompt_limit=1,
                cities=["Sydney"],
            )
            self._write_payload_and_manifest(
                Path(artifact_paths["small_batch_json"]),  # type: ignore[index]
                Path(artifact_paths["small_batch_manifest"]),  # type: ignore[index]
                planned_runs=30,
                record_count=30,
                prompt_limit=5,
                cities=["Sydney"],
            )
            self._write_payload_and_manifest(
                Path(artifact_paths["full_batch_json"]),  # type: ignore[index]
                Path(artifact_paths["full_batch_manifest"]),  # type: ignore[index]
                planned_runs=2400,
                record_count=2400,
                prompt_limit=100,
                cities=["Australia", "Sydney", "Melbourne", "Brisbane"],
            )

            package = build_au_p0a_evidence_package(
                runbook_path=runbook_path,
                readiness_path=readiness_path,
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(package["status"], "pass")
        self.assertTrue(package["ready_for_design_partner"])
        self.assertEqual(package["summary"]["missing_artifacts"], [])
        self.assertEqual(package["artifacts"]["full_batch_manifest"]["run_summary"]["planned_runs"], 2400)
        self.assertEqual(package["package_payload_hash"], compute_package_payload_hash(package))

    def test_cli_writes_fail_package_for_missing_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            readiness_path = Path(temp_dir) / "readiness.json"
            output_path = Path(temp_dir) / "package.json"
            self._write_readiness(readiness_path, status="fail")

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_evidence_package.py",
                    "--runbook-path",
                    str(runbook_path),
                    "--readiness-path",
                    str(readiness_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-11T00:00:00Z",
                ],
                capture_output=True,
                text=True,
            )
            stdout_payload = json.loads(result.stdout)
            written_payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 2)
        self.assertEqual(stdout_payload, written_payload)
        self.assertEqual(written_payload["status"], "fail")


if __name__ == "__main__":
    unittest.main()
