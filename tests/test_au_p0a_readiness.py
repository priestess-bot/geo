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
            "DATABASE_URL": "postgresql://geo:test@localhost:5432/geo",
        }

    def _write_env_file(self, temp_dir: str) -> Path:
        env_file = Path(temp_dir) / ".env.au-p0a"
        env_file.write_text(
            "\n".join(
                [
                    "PERPLEXITY_API_KEY=env-file-perplexity",
                    "OPENAI_API_KEY=env-file-openai",
                    "DATABASE_URL=postgresql://env-file.example/db",
                ]
            ),
            encoding="utf-8",
        )
        env_file.chmod(0o600)
        return env_file

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

    def _db_connection(self) -> object:
        class Cursor:
            def __enter__(self) -> "Cursor":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def execute(self, sql: str) -> None:
                if sql != "SELECT 1":
                    raise AssertionError(f"unexpected SQL: {sql}")

            def fetchone(self) -> tuple[int]:
                return (1,)

        class Connection:
            def __init__(self) -> None:
                self.closed = False

            def cursor(self) -> Cursor:
                return Cursor()

            def close(self) -> None:
                self.closed = True

        return Connection()

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
        self.assertEqual(result["database"]["status"], "skipped")

    def test_preflight_phase_passes_with_required_env_and_valid_runbook(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            result = verify_au_p0a_readiness(
                phase="preflight",
                runbook_path=runbook_path,
                env=self._env(),
                env_file_path=Path(temp_dir) / "missing.env",
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["ready_to_run_phase"])
        self.assertEqual(result["recommended_next_action"], "run_make_api_preflight")
        self.assertEqual(result["environment"]["missing_required"], [])
        self.assertEqual(result["database"]["status"], "skipped")
        self.assertIn("recommended_env_missing:OBJECT_STORE_ENDPOINT", result["warnings"])

    def test_preflight_phase_loads_env_file_without_leaking_secret_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            env_file = self._write_env_file(temp_dir)
            result = verify_au_p0a_readiness(
                phase="preflight",
                runbook_path=runbook_path,
                env={},
                env_file_path=env_file,
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["environment"]["status"], "pass")
        self.assertEqual(result["environment"]["env_file"]["path"], str(env_file))
        self.assertTrue(result["environment"]["env_file"]["hygiene"]["hygiene_ready"])
        checks = {check["name"]: check for check in result["environment"]["required"]}
        self.assertEqual(checks["PERPLEXITY_API_KEY"]["source"], "env_file")
        self.assertEqual(len(checks["PERPLEXITY_API_KEY"]["sha256_prefix"]), 12)
        self.assertNotIn("env-file-perplexity", json.dumps(result))
        self.assertNotIn("env-file-openai", json.dumps(result))

    def test_preflight_phase_fails_world_readable_env_file_with_secrets(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            env_file = self._write_env_file(temp_dir)
            env_file.chmod(0o644)
            result = verify_au_p0a_readiness(
                phase="preflight",
                runbook_path=runbook_path,
                env={},
                env_file_path=env_file,
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["environment"]["status"], "fail")
        self.assertIn("env_file:env_file_permissions_not_0600", result["environment"]["errors"])

    def test_preflight_phase_process_env_overrides_env_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            result = verify_au_p0a_readiness(
                phase="preflight",
                runbook_path=runbook_path,
                env={
                    "PERPLEXITY_API_KEY": "process-perplexity",
                    "OPENAI_API_KEY": "process-openai",
                    "DATABASE_URL": "postgresql://process.example/db",
                },
                env_file_path=self._write_env_file(temp_dir),
                generated_at="2026-06-11T00:00:00Z",
            )

        checks = {check["name"]: check for check in result["environment"]["required"]}
        self.assertEqual(checks["PERPLEXITY_API_KEY"]["source"], "process")
        self.assertEqual(checks["OPENAI_API_KEY"]["source"], "process")
        self.assertEqual(checks["DATABASE_URL"]["source"], "process")

    def test_preflight_phase_can_require_database_connection_check(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            result = verify_au_p0a_readiness(
                phase="preflight",
                runbook_path=runbook_path,
                env=self._env(),
                require_db_check=True,
                db_connector=lambda _database_url: self._db_connection(),
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["database"]["status"], "pass")
        self.assertEqual(result["database"]["connection_check"], "pass")

    def test_preflight_phase_fails_when_required_database_check_fails(self) -> None:
        def broken_connector(_database_url: str) -> object:
            raise RuntimeError("cannot connect")

        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            result = verify_au_p0a_readiness(
                phase="preflight",
                runbook_path=runbook_path,
                env=self._env(),
                require_db_check=True,
                db_connector=broken_connector,
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["database"]["status"], "fail")
        self.assertEqual(result["database"]["error_type"], "RuntimeError")
        self.assertIn("database:database_connection_check_failed", result["errors"])
        self.assertEqual(result["recommended_next_action"], "fix_database_readiness")

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
                    "--env-file",
                    str(Path(temp_dir) / "missing.env"),
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

    def test_cli_can_read_env_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            output_path = Path(temp_dir) / "readiness.json"
            env_file = self._write_env_file(temp_dir)
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0a_readiness.py",
                    "--phase",
                    "preflight",
                    "--runbook-path",
                    str(runbook_path),
                    "--env-file",
                    str(env_file),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-11T00:00:00Z",
                ],
                capture_output=True,
                env={},
                text=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["environment"]["required"][0]["source"], "env_file")
        self.assertNotIn("env-file-perplexity", json.dumps(payload))

    def test_cli_can_require_database_check_from_environment(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = self._write_runbook(temp_dir)
            output_path = Path(temp_dir) / "readiness.json"
            env = self._env()
            env["GEO_AU_P0A_REQUIRE_DB_CHECK"] = "1"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0a_readiness.py",
                    "--phase",
                    "preflight",
                    "--runbook-path",
                    str(runbook_path),
                    "--env-file",
                    str(Path(temp_dir) / "missing.env"),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-11T00:00:00Z",
                ],
                capture_output=True,
                env=env,
                text=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["database"]["status"], "fail")
        self.assertIn("database:database_connection_check_failed", payload["errors"])


if __name__ == "__main__":
    unittest.main()
