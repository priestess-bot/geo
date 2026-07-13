from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import schema_v2_provision_login as provisioner


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/schema-v2/baseline/0021_worker_login_provision.sql"
STRONG_SECRET = "Worker-Login-V2_Unit-Credential-2026!Alpha"


class SchemaV2WorkerLoginProvisionContractTest(unittest.TestCase):
    def _secret(self, directory: Path) -> Path:
        path = directory / "worker-login-password"
        path.write_text(STRONG_SECRET, encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_worker_profile_is_a_fixed_registry_entry(self) -> None:
        profile = provisioner.LOGIN_PROFILES["worker"]
        self.assertEqual(profile.login_role, "geno_v2_worker_login")
        self.assertEqual(profile.execution_role, "geno_v2_worker")
        self.assertEqual(
            profile.readiness_function,
            "geno_v2_worker_login_startup_ready",
        )
        self.assertEqual(
            profile.required_baseline_files,
            (
                "baseline/0014_auth_login_provision.sql",
                "baseline/0020_collection_geo_scoring.sql",
                "baseline/0021_worker_login_provision.sql",
            ),
        )
        self.assertEqual(
            profile.provision_lock_name,
            provisioner.LOGIN_PROFILES["api"].provision_lock_name,
        )
        with self.assertRaisesRegex(provisioner.LoginProvisionError, "login_kind_invalid"):
            provisioner._login_profile("arbitrary-role-name")

    def test_migration_seals_worker_and_exposes_only_narrow_readiness(self) -> None:
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("geno_v2_worker_login_startup_ready", sql)
        self.assertIn("WHERE attempt.login_kind = 'worker'", sql)
        self.assertIn("session_user = 'geno_v2_worker_login'", sql)
        self.assertIn("current_setting('role', true) = 'geno_v2_worker'", sql)
        self.assertIn("SECURITY DEFINER", sql)
        self.assertIn("SET search_path = pg_catalog", sql)
        self.assertIn("OWNER TO geno_v2_authz_owner", sql)
        self.assertIn("TO geno_v2_worker;", sql)
        self.assertIn("FROM PUBLIC, geno_v2_runtime, geno_v2_worker_login", sql)
        self.assertIn("NOLOGIN NOSUPERUSER", sql)
        self.assertIn("NOBYPASSRLS PASSWORD NULL", sql)
        self.assertIn("worker_login_provision_catalog_verification_failed", sql)

    def test_worker_cli_requires_only_a_secret_file_and_static_kind(self) -> None:
        parser = provisioner.build_parser()
        args = parser.parse_args(
            [
                "--login-kind",
                "worker",
                "check",
                "--credential-file",
                "/run/secrets/worker",
                "--credential-version",
                "worker-v1",
            ]
        )
        self.assertEqual(args.login_kind, "worker")
        self.assertEqual(args.command, "check")
        with self.assertRaises(SystemExit):
            parser.parse_args(["--login-kind", "geno_v2_job_owner", "disable"])

    def test_worker_plaintext_environment_is_rejected(self) -> None:
        base = {
            "PGHOST": "localhost",
            "PGPORT": "5432",
            "PGDATABASE": "geno_v2",
            "PGUSER": "installer",
            "PGPASSWORD": "installer-secret",
        }
        for variable in (
            "GENO_SCHEMA_V2_WORKER_LOGIN_PASSWORD",
            "SCHEMA_V2_WORKER_LOGIN_PASSWORD",
            "GENO_V2_WORKER_LOGIN_PASSWORD",
        ):
            with self.subTest(variable=variable):
                with self.assertRaisesRegex(
                    provisioner.LoginProvisionError,
                    "plaintext_environment_forbidden",
                ):
                    provisioner.installer_config_from_env(
                        {**base, variable: STRONG_SECRET}
                    )

    def test_worker_check_rejects_installer_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._secret(Path(temp_dir))
            with self.assertRaisesRegex(
                provisioner.LoginProvisionError,
                "worker_login_installer_environment_forbidden",
            ):
                provisioner.check_login(
                    credential_file=path,
                    credential_version="worker-v1",
                    repository_root=ROOT,
                    login_kind="worker",
                    env={
                        "PGHOST": "localhost",
                        "PGPORT": "5432",
                        "PGDATABASE": "geno_v2",
                        "PGUSER": "installer",
                        "PGPASSWORD": "installer-secret",
                    },
                )

    def test_worker_cli_error_does_not_echo_secret(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("sys.stderr") as stderr:
            result = provisioner.main(
                [
                    "--login-kind",
                    "worker",
                    "provision",
                    "--credential-file",
                    "/does/not/exist",
                    "--credential-version",
                    "worker-v1",
                ]
            )
        self.assertEqual(result, 2)
        rendered = " ".join(str(call) for call in stderr.write.call_args_list)
        self.assertNotIn(STRONG_SECRET, rendered)
        self.assertNotIn("Traceback", rendered)


if __name__ == "__main__":
    unittest.main()
