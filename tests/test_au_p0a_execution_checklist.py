from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_env_report import build_au_p0a_env_report
from scripts.build_au_p0a_evidence_package import build_au_p0a_evidence_package
from scripts.build_au_p0a_execution_checklist import (
    CHECKLIST_VERSION,
    build_au_p0a_execution_checklist,
    compute_p0a_execution_checklist_hash,
)
from scripts.build_au_p0a_runbook import build_au_p0a_runbook
from scripts.build_au_p0a_status_report import build_au_p0a_status_report
from scripts.build_preflight_manifest import build_preflight_manifest
from scripts.run_au_p0a_runbook import run_au_p0a_runbook
from scripts.verify_au_p0a_execution_checklist import verify_au_p0a_execution_checklist
from scripts.verify_preflight_payload import compute_preflight_payload_hash, verify_preflight_payload


class AuP0aExecutionChecklistTest(unittest.TestCase):
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
        runbook = build_au_p0a_runbook(artifact_dir=artifact_dir, generated_at="2026-06-12T00:00:00Z")
        path = Path(temp_dir) / "runbook.json"
        path.write_text(json.dumps(runbook), encoding="utf-8")
        return path, runbook

    def _write_readiness(self, path: Path, *, ready: bool) -> None:
        payload = {
            "readiness_version": "au_p0a_readiness_v1",
            "generated_at": "2026-06-12T00:00:00Z",
            "phase": "full_batch",
            "status": "pass" if ready else "fail",
            "ready_to_run_phase": ready,
            "errors": [] if ready else ["required_env_missing:DATABASE_URL"],
            "warnings": [],
            "recommended_next_action": "run_full_au_p0a_batch" if ready else "configure_required_environment",
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _write_env_report(self, path: Path, runbook_path: Path, *, ready: bool) -> None:
        env = (
            {
                "PERPLEXITY_API_KEY": "perplexity-key",
                "OPENAI_API_KEY": "openai-key",
                "DATABASE_URL": "postgresql://user:pass@example.test/db",
            }
            if ready
            else {}
        )
        report = build_au_p0a_env_report(
            runbook_path=runbook_path,
            env_file_path=Path(path.parent) / "missing.env",
            output_path=path,
            env=env,
            generated_at="2026-06-12T00:00:00Z",
        )
        path.write_text(json.dumps(report), encoding="utf-8")

    def _write_runbook_execution(self, path: Path, runbook_path: Path, *, ready: bool) -> None:
        env = (
            {
                "PERPLEXITY_API_KEY": "perplexity-key",
                "OPENAI_API_KEY": "openai-key",
                "DATABASE_URL": "postgresql://user:pass@example.test/db",
            }
            if ready
            else {}
        )
        execution = run_au_p0a_runbook(
            runbook_path=runbook_path,
            output_path=path,
            env=env,
            generated_at="2026-06-12T00:00:00Z",
        )
        path.write_text(json.dumps(execution), encoding="utf-8")

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
            generated_at="2026-06-12T00:00:00Z",
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _write_package_and_status(
        self,
        *,
        runbook_path: Path,
        environment_path: Path,
        execution_path: Path,
        readiness_path: Path,
        package_path: Path,
        status_path: Path,
        ready: bool,
    ) -> None:
        package = build_au_p0a_evidence_package(
            runbook_path=runbook_path,
            environment_path=environment_path,
            readiness_path=readiness_path,
            runbook_execution_path=execution_path,
            output_path=package_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        package_path.write_text(json.dumps(package), encoding="utf-8")
        env = (
            {
                "PERPLEXITY_API_KEY": "perplexity-key",
                "OPENAI_API_KEY": "openai-key",
                "DATABASE_URL": "postgresql://user:pass@example.test/db",
            }
            if ready
            else {}
        )
        status = build_au_p0a_status_report(
            runbook_path=runbook_path,
            environment_path=environment_path,
            readiness_path=readiness_path,
            runbook_execution_path=execution_path,
            package_path=package_path,
            output_path=status_path,
            env=env,
            env_file_path=Path(status_path.parent) / "missing.env",
            generated_at="2026-06-12T00:00:00Z",
        )
        status_path.write_text(json.dumps(status), encoding="utf-8")

    def test_checklist_records_current_missing_artifacts_without_secret_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            environment_path = Path(temp_dir) / "environment.json"
            execution_path = Path(temp_dir) / "execution.json"
            readiness_path = Path(temp_dir) / "readiness.json"
            package_path = Path(temp_dir) / "package.json"
            status_path = Path(temp_dir) / "status.json"
            self._write_env_report(environment_path, runbook_path, ready=False)
            self._write_runbook_execution(execution_path, runbook_path, ready=False)
            self._write_readiness(readiness_path, ready=False)
            self._write_package_and_status(
                runbook_path=runbook_path,
                environment_path=environment_path,
                execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                ready=False,
            )
            checklist = build_au_p0a_execution_checklist(
                runbook_path=runbook_path,
                environment_path=environment_path,
                runbook_execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                env_file_path=Path(temp_dir) / "missing.env",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0a_execution_checklist(checklist)

        self.assertEqual(checklist["execution_checklist_version"], CHECKLIST_VERSION)
        self.assertEqual(checklist["status"], "fail")
        self.assertFalse(checklist["p0a_execution_checklist_ready"])
        self.assertFalse(checklist["ready_for_design_partner"])
        self.assertEqual(checklist["next_action"], "configure_required_environment")
        self.assertIn("preflight_json", checklist["summary"]["missing_artifacts"])
        self.assertIn("verify_env_template", {command["id"] for command in checklist["setup_commands"]})
        self.assertIn("chmod_env_file", {command["id"] for command in checklist["setup_commands"]})
        self.assertIn("hard_status_gate", {command["id"] for command in checklist["verification_commands"]})
        self.assertFalse(checklist["credential_handoff"]["ready"])
        self.assertEqual(checklist["credential_handoff"]["missing_required_count"], 3)
        self.assertEqual(
            sorted(checklist["credential_handoff"]["missing_required"]),
            ["DATABASE_URL", "OPENAI_API_KEY", "PERPLEXITY_API_KEY"],
        )
        self.assertIn("chmod 600 .env.au-p0a", checklist["credential_handoff"]["setup_commands"])
        self.assertFalse(checklist["credential_handoff"]["redaction_policy"]["raw_secret_values_allowed"])
        self.assertEqual(checklist["credential_handoff"]["redaction_policy"]["forbidden_exact_secret_field_count"], 2)
        self.assertTrue(checklist["credential_handoff"]["redaction_policy"]["forbidden_exact_secret_fields_redacted"])
        self.assertNotIn("raw_value", json.dumps(checklist["credential_handoff"]))
        self.assertEqual(checklist["p0a_execution_checklist_hash"], compute_p0a_execution_checklist_hash(checklist))
        self.assertEqual(verification["status"], "pass")
        serialized = json.dumps(checklist)
        self.assertNotIn("perplexity-key", serialized)
        self.assertNotIn("postgresql://user", serialized)

    def test_checklist_passes_when_all_p0a_artifacts_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, runbook = self._write_runbook(temp_dir)
            environment_path = Path(temp_dir) / "environment.json"
            execution_path = Path(temp_dir) / "execution.json"
            readiness_path = Path(temp_dir) / "readiness.json"
            package_path = Path(temp_dir) / "package.json"
            status_path = Path(temp_dir) / "status.json"
            self._write_env_report(environment_path, runbook_path, ready=True)
            self._write_runbook_execution(execution_path, runbook_path, ready=True)
            self._write_readiness(readiness_path, ready=True)
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
            self._write_package_and_status(
                runbook_path=runbook_path,
                environment_path=environment_path,
                execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                ready=True,
            )
            checklist = build_au_p0a_execution_checklist(
                runbook_path=runbook_path,
                environment_path=environment_path,
                runbook_execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                env_file_path=Path(temp_dir) / "missing.env",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0a_execution_checklist(checklist, require_design_partner_ready=True)

        self.assertEqual(checklist["status"], "pass")
        self.assertTrue(checklist["p0a_execution_checklist_ready"])
        self.assertTrue(checklist["ready_for_design_partner"])
        self.assertEqual(checklist["summary"]["missing_artifact_count"], 0)
        self.assertEqual(checklist["summary"]["remaining_blocker_count"], 0)
        self.assertTrue(checklist["credential_handoff"]["ready"])
        self.assertEqual(checklist["credential_handoff"]["missing_required_count"], 0)
        self.assertEqual(checklist["next_action"], "ready_for_design_partner_handoff")
        self.assertEqual(verification["status"], "pass")

    def test_verifier_detects_hash_and_summary_tampering(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            environment_path = Path(temp_dir) / "environment.json"
            execution_path = Path(temp_dir) / "execution.json"
            readiness_path = Path(temp_dir) / "readiness.json"
            package_path = Path(temp_dir) / "package.json"
            status_path = Path(temp_dir) / "status.json"
            self._write_env_report(environment_path, runbook_path, ready=False)
            self._write_runbook_execution(execution_path, runbook_path, ready=False)
            self._write_readiness(readiness_path, ready=False)
            self._write_package_and_status(
                runbook_path=runbook_path,
                environment_path=environment_path,
                execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                ready=False,
            )
            checklist = build_au_p0a_execution_checklist(
                runbook_path=runbook_path,
                environment_path=environment_path,
                runbook_execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            checklist["summary"]["missing_artifact_count"] = 0  # type: ignore[index]
            verification = verify_au_p0a_execution_checklist(checklist)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("p0a_execution_checklist_hash_mismatch", verification["errors"])
        self.assertIn("summary_missing_artifact_count_mismatch", verification["errors"])

    def test_verifier_requires_credential_handoff_to_match_missing_required_env(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            environment_path = Path(temp_dir) / "environment.json"
            execution_path = Path(temp_dir) / "execution.json"
            readiness_path = Path(temp_dir) / "readiness.json"
            package_path = Path(temp_dir) / "package.json"
            status_path = Path(temp_dir) / "status.json"
            self._write_env_report(environment_path, runbook_path, ready=False)
            self._write_runbook_execution(execution_path, runbook_path, ready=False)
            self._write_readiness(readiness_path, ready=False)
            self._write_package_and_status(
                runbook_path=runbook_path,
                environment_path=environment_path,
                execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                ready=False,
            )
            checklist = build_au_p0a_execution_checklist(
                runbook_path=runbook_path,
                environment_path=environment_path,
                runbook_execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            checklist["credential_handoff"]["missing_required"] = ["DATABASE_URL"]  # type: ignore[index]
            checklist["credential_handoff"]["setup_commands"] = ["make verify-au-p0a-env-template"]  # type: ignore[index]
            checklist["p0a_execution_checklist_hash"] = compute_p0a_execution_checklist_hash(checklist)
            verification = verify_au_p0a_execution_checklist(checklist)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("credential_handoff_missing_required_mismatch", verification["errors"])
        self.assertIn("credential_handoff_setup_command_missing:chmod 600 .env.au-p0a", verification["errors"])

    def test_verifier_rejects_forbidden_secret_fields_anywhere(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            environment_path = Path(temp_dir) / "environment.json"
            execution_path = Path(temp_dir) / "execution.json"
            readiness_path = Path(temp_dir) / "readiness.json"
            package_path = Path(temp_dir) / "package.json"
            status_path = Path(temp_dir) / "status.json"
            self._write_env_report(environment_path, runbook_path, ready=False)
            self._write_runbook_execution(execution_path, runbook_path, ready=False)
            self._write_readiness(readiness_path, ready=False)
            self._write_package_and_status(
                runbook_path=runbook_path,
                environment_path=environment_path,
                execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                ready=False,
            )
            checklist = build_au_p0a_execution_checklist(
                runbook_path=runbook_path,
                environment_path=environment_path,
                runbook_execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            checklist["status_report"]["raw_value"] = "secret"  # type: ignore[index]
            checklist["p0a_execution_checklist_hash"] = compute_p0a_execution_checklist_hash(checklist)
            verification = verify_au_p0a_execution_checklist(checklist)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("forbidden_secret_field:$.status_report.raw_value", verification["errors"])

    def test_cli_writes_and_verifies_checklist(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            environment_path = Path(temp_dir) / "environment.json"
            execution_path = Path(temp_dir) / "execution.json"
            readiness_path = Path(temp_dir) / "readiness.json"
            package_path = Path(temp_dir) / "package.json"
            status_path = Path(temp_dir) / "status.json"
            output_path = Path(temp_dir) / "execution-checklist.json"
            self._write_env_report(environment_path, runbook_path, ready=False)
            self._write_runbook_execution(execution_path, runbook_path, ready=False)
            self._write_readiness(readiness_path, ready=False)
            self._write_package_and_status(
                runbook_path=runbook_path,
                environment_path=environment_path,
                execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                ready=False,
            )
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_execution_checklist.py",
                    "--runbook-path",
                    str(runbook_path),
                    "--environment-path",
                    str(environment_path),
                    "--runbook-execution-path",
                    str(execution_path),
                    "--readiness-path",
                    str(readiness_path),
                    "--package-path",
                    str(package_path),
                    "--status-path",
                    str(status_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            verify_result = subprocess.run(
                [sys.executable, "scripts/verify_au_p0a_execution_checklist.py", str(output_path)],
                capture_output=True,
                check=True,
                text=True,
            )

        payload = json.loads(build_result.stdout)
        verifier_payload = json.loads(verify_result.stdout)
        self.assertEqual(payload["p0a_execution_checklist_hash"], compute_p0a_execution_checklist_hash(payload))
        self.assertEqual(verifier_payload["status"], "pass")
        self.assertEqual(verifier_payload["next_action"], "configure_required_environment")


if __name__ == "__main__":
    unittest.main()
