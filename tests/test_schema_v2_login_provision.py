from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.schema_v2_provision_login import (
    LoginProvisionError,
    build_parser,
    check_login,
    installer_config_from_env,
    main,
    read_api_login_secret,
)


ROOT = Path(__file__).resolve().parents[1]
STRONG_SECRET = "Correct-Horse_Battery-Staple-2026!"


class SchemaV2LoginSecretTest(unittest.TestCase):
    def _write_secret(self, directory: Path, value: str = STRONG_SECRET) -> Path:
        path = directory / "api-login-password"
        path.write_text(value, encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_secure_external_regular_file_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_secret(Path(temp_dir), STRONG_SECRET + "\n")
            self.assertEqual(
                read_api_login_secret(path, repository_root=ROOT),
                STRONG_SECRET,
            )
            path.chmod(0o400)
            self.assertEqual(
                read_api_login_secret(path, repository_root=ROOT),
                STRONG_SECRET,
            )

    def test_repository_path_symlink_and_insecure_modes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as repo_temp:
            path = self._write_secret(Path(repo_temp))
            with self.assertRaisesRegex(LoginProvisionError, "must_be_external"):
                read_api_login_secret(path, repository_root=ROOT)

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            target = self._write_secret(directory)
            link = directory / "api-login-link"
            link.symlink_to(target)
            with self.assertRaisesRegex(LoginProvisionError, "file_type_invalid"):
                read_api_login_secret(link, repository_root=ROOT)
            for mode in (0o644, 0o660, 0o200):
                with self.subTest(mode=oct(mode)):
                    target.chmod(mode)
                    with self.assertRaisesRegex(LoginProvisionError, "permissions_invalid"):
                        read_api_login_secret(target, repository_root=ROOT)

    def test_secret_content_policy_and_installer_reuse_are_rejected(self) -> None:
        rejected = (
            "short-A1!",
            "Password-Password-Password-123!",
            "Dev-Strong_But-Forbidden-Credential-2026!",
            "Correct-Horse_Battery-Staple-2026!\nsecond-line",
            " Correct-Horse_Battery-Staple-2026!",
            "Correct-Horse_Battery-Staple-2026!\x00",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            for value in rejected:
                with self.subTest(value=value[:12]):
                    path = self._write_secret(directory, value)
                    with self.assertRaises(LoginProvisionError):
                        read_api_login_secret(path, repository_root=ROOT)
            path = self._write_secret(directory)
            with self.assertRaisesRegex(LoginProvisionError, "reuses_installer"):
                read_api_login_secret(
                    path,
                    repository_root=ROOT,
                    installer_password=STRONG_SECRET,
                )
            unicode_secret = "Unicode-Reuse_真实凭据-2026!Alpha-Beta-Gamma"
            path = self._write_secret(directory, unicode_secret)
            with self.assertRaisesRegex(LoginProvisionError, "reuses_installer"):
                read_api_login_secret(
                    path,
                    repository_root=ROOT,
                    installer_password=unicode_secret,
                )

    def test_plaintext_api_environment_and_unstructured_connections_are_rejected(self) -> None:
        base = {
            "PGHOST": "localhost",
            "PGPORT": "5432",
            "PGDATABASE": "geno_v2",
            "PGUSER": "installer",
            "PGPASSWORD": "installer-secret",
        }
        for setting in (
            "GENO_SCHEMA_V2_API_LOGIN_PASSWORD",
            "SCHEMA_V2_API_LOGIN_PASSWORD",
            "GENO_V2_API_LOGIN_PASSWORD",
            "DATABASE_URL",
            "SCHEMA_V2_DATABASE_URL",
            "PGSERVICE",
            "PGSERVICEFILE",
            "PGHOSTADDR",
            "PGSSLMODE",
            "PGOPTIONS",
        ):
            with self.subTest(setting=setting):
                with self.assertRaises(LoginProvisionError):
                    installer_config_from_env({**base, setting: "forbidden"})
        with self.assertRaisesRegex(LoginProvisionError, "configuration_invalid"):
            installer_config_from_env({**base, "PGDATABASE": "postgres"})

    def test_cli_has_no_plaintext_password_argument_and_errors_do_not_echo_secret(self) -> None:
        parser = build_parser()
        option_names = {
            option
            for action in parser._actions
            for option in action.option_strings
        }
        self.assertNotIn("--password", option_names)
        with patch.dict(os.environ, {}, clear=True), patch("sys.stderr") as stderr:
            result = main(
                [
                    "provision",
                    "--credential-file",
                    "/does/not/exist",
                    "--credential-version",
                    "v1",
                ]
            )
        self.assertEqual(result, 2)
        rendered = " ".join(str(call) for call in stderr.write.call_args_list)
        self.assertNotIn(STRONG_SECRET, rendered)
        self.assertNotIn("Traceback", rendered)

    def test_startup_check_rejects_installer_identity_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_secret(Path(temp_dir))
            with self.assertRaisesRegex(LoginProvisionError, "installer_environment_forbidden"):
                check_login(
                    credential_file=path,
                    credential_version="login-v1",
                    repository_root=ROOT,
                    env={
                        "PGHOST": "localhost",
                        "PGPORT": "5432",
                        "PGDATABASE": "geno_v2",
                        "PGUSER": "installer",
                        "PGPASSWORD": "installer-secret",
                    },
                )


if __name__ == "__main__":
    unittest.main()
