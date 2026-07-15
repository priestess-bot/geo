from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import psycopg

from scripts import schema_v2_provision_login as provisioner


BEHAVIOR_TEST_ENABLED = os.getenv("SCHEMA_V2_BEHAVIOR_TEST") == "1"
ROOT = Path(__file__).resolve().parents[1]
SECRET_ONE = "Login-V2_First-Credential-2026!Alpha"
SECRET_TWO = "Login-V2_Second-Credential-2026!Beta"
SECRET_THREE = "Login-V2_Third-Credential-2026!Gamma"
SECRET_FOUR = "Login-V2_Fourth-Credential-2026!Delta"


@unittest.skipUnless(BEHAVIOR_TEST_ENABLED, "SCHEMA_V2_BEHAVIOR_TEST=1 is required")
class SchemaV2LoginProvisionPostgresTest(unittest.TestCase):
    def _secret(self, directory: Path, name: str, value: str) -> Path:
        path = directory / name
        path.write_text(value, encoding="utf-8")
        path.chmod(0o600)
        return path

    def _installer(self) -> psycopg.Connection[object]:
        return psycopg.connect(autocommit=True)

    def _api_connect_fails(self, secret: str) -> None:
        config = provisioner.installer_config_from_env()
        with self.assertRaises(psycopg.Error):
            psycopg.connect(
                **provisioner._connect_kwargs(config.endpoint),
                user=provisioner.API_LOGIN_ROLE,
                password=secret,
            )

    def _api_env(self) -> dict[str, str]:
        config = provisioner.installer_config_from_env()
        return {
            "PGHOST": config.endpoint.host,
            "PGPORT": str(config.endpoint.port),
            "PGDATABASE": config.endpoint.database,
        }

    def _check_login(self, path: Path, version: str) -> None:
        with patch.dict(os.environ, self._api_env(), clear=True):
            provisioner.check_login(
                credential_file=path,
                credential_version=version,
                repository_root=ROOT,
            )

    def test_complete_login_provision_rotation_compensation_and_disable_lifecycle(self) -> None:
        with self._installer() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT rolcanlogin, rolpassword IS NULL FROM pg_authid "
                    "WHERE rolname = 'geo_v2_api_login'"
                )
                self.assertEqual(cursor.fetchone(), (False, True))
                cursor.execute("SELECT count(*) FROM auth_login_provision_attempts")
                self.assertEqual(cursor.fetchone(), (0,))

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            first = self._secret(directory, "first", SECRET_ONE)
            second = self._secret(directory, "second", SECRET_TWO)
            third = self._secret(directory, "third", SECRET_THREE)
            fourth = self._secret(directory, "fourth", SECRET_FOUR)

            with self._installer() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "ALTER ROLE geo_v2_api_login LOGIN PASSWORD "
                        "'Untracked-Test-Credential-Only-2026!'"
                    )
            with self.assertRaisesRegex(
                provisioner.LoginProvisionError,
                "api_login_untracked_credential_sealed",
            ):
                provisioner.provision_or_rotate(
                    "provision",
                    credential_file=first,
                    credential_version="untracked-probe-v1",
                    initiated_by="postgres-gate",
                    repository_root=ROOT,
                    lock_timeout_seconds=2,
                    drain_confirmed=False,
                )
            with self._installer() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT rolcanlogin, rolpassword IS NULL FROM pg_authid "
                        "WHERE rolname = 'geo_v2_api_login'"
                    )
                    self.assertEqual(cursor.fetchone(), (False, True))
                    cursor.execute("SELECT count(*) FROM auth_login_provision_attempts")
                    self.assertEqual(cursor.fetchone(), (0,))

            provisioner.provision_or_rotate(
                "provision",
                credential_file=first,
                credential_version="login-v1",
                initiated_by="postgres-gate",
                repository_root=ROOT,
                lock_timeout_seconds=2,
                drain_confirmed=False,
            )
            self._check_login(first, "login-v1")
            with self._installer() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "GRANT SELECT ON auth_login_provision_attempts "
                        "TO geo_v2_api_login"
                    )
            try:
                with self.assertRaisesRegex(
                    provisioner.LoginProvisionError,
                    "direct_privilege_smoke_failed",
                ):
                    self._check_login(first, "login-v1")
            finally:
                with self._installer() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "REVOKE SELECT ON auth_login_provision_attempts "
                            "FROM geo_v2_api_login"
                        )
            with self._installer() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO auth_login_provision_attempts ("
                        "login_kind, operation, credential_version, "
                        "previous_credential_version, initiated_by) "
                        "VALUES ('worker', 'provision', 'worker-login-v1', "
                        "NULL, 'postgres-gate')"
                    )
            self._check_login(first, "login-v1")

            with self.assertRaisesRegex(
                provisioner.LoginProvisionError,
                "rotation_requires_drain_confirmation",
            ):
                provisioner.provision_or_rotate(
                    "rotate",
                    credential_file=second,
                    credential_version="login-v2",
                    initiated_by="postgres-gate",
                    repository_root=ROOT,
                    lock_timeout_seconds=2,
                    drain_confirmed=False,
                )

            provisioner.provision_or_rotate(
                "rotate",
                credential_file=second,
                credential_version="login-v2",
                initiated_by="postgres-gate",
                repository_root=ROOT,
                lock_timeout_seconds=2,
                drain_confirmed=True,
            )
            self._api_connect_fails(SECRET_ONE)
            self._check_login(second, "login-v2")

            with patch.object(
                provisioner,
                "_smoke_login",
                side_effect=provisioner.LoginProvisionError("injected_smoke_failure"),
            ):
                with self.assertRaisesRegex(
                    provisioner.LoginProvisionError,
                    "api_login_smoke_failed",
                ):
                    provisioner.provision_or_rotate(
                        "rotate",
                        credential_file=third,
                        credential_version="login-v3",
                        initiated_by="postgres-gate",
                        repository_root=ROOT,
                        lock_timeout_seconds=2,
                        drain_confirmed=True,
                    )
            with self._installer() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT rolcanlogin, rolpassword IS NULL FROM pg_authid "
                        "WHERE rolname = 'geo_v2_api_login'"
                    )
                    self.assertEqual(cursor.fetchone(), (False, True))
                    cursor.execute(
                        "SELECT status, failure_code FROM auth_login_provision_attempts "
                        "ORDER BY attempt_sequence DESC LIMIT 1"
                    )
                    self.assertEqual(
                        cursor.fetchone(),
                        ("failed", "new_credential_smoke_failed"),
                    )
            self._api_connect_fails(SECRET_TWO)
            self._api_connect_fails(SECRET_THREE)

            provisioner.provision_or_rotate(
                "provision",
                credential_file=fourth,
                credential_version="login-v4",
                initiated_by="postgres-gate",
                repository_root=ROOT,
                lock_timeout_seconds=2,
                drain_confirmed=False,
            )

            config = provisioner.installer_config_from_env()
            with psycopg.connect(
                **provisioner._connect_kwargs(config.endpoint),
                user=provisioner.API_LOGIN_ROLE,
                password=SECRET_FOUR,
            ) as pooled:
                with pooled.transaction():
                    with pooled.cursor() as cursor:
                        cursor.execute("SET LOCAL ROLE geo_v2_runtime")
                        cursor.execute(
                            "SET LOCAL app.session_token_hash = "
                            "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'"
                        )
                with pooled.cursor() as cursor:
                    cursor.execute(
                        "SELECT current_user, session_user, "
                        "current_setting('app.session_token_hash', true)"
                    )
                    current_user, session_user, session_hash = cursor.fetchone()
                pooled.rollback()
                self.assertEqual(current_user, provisioner.API_LOGIN_ROLE)
                self.assertEqual(session_user, provisioner.API_LOGIN_ROLE)
                self.assertIn(session_hash, (None, ""))

            with self._installer() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO auth_login_provision_attempts ("
                        "login_kind, operation, credential_version, "
                        "previous_credential_version, initiated_by) "
                        "VALUES ('api', 'rotate', 'interrupted-v5', "
                        "'login-v4', 'postgres-gate')"
                    )
            with self.assertRaisesRegex(
                provisioner.LoginProvisionError,
                "startup_readiness_failed",
            ):
                self._check_login(fourth, "login-v4")

            provisioner.disable_login(
                initiated_by="postgres-gate",
                lock_timeout_seconds=2,
            )
            self._api_connect_fails(SECRET_FOUR)

            with self._installer() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT operation, status FROM auth_login_provision_attempts "
                        "ORDER BY attempt_sequence DESC LIMIT 1"
                    )
                    self.assertEqual(cursor.fetchone(), ("disable", "succeeded"))
                    cursor.execute(
                        "SELECT status, failure_code FROM auth_login_provision_attempts "
                        "ORDER BY attempt_sequence DESC OFFSET 1 LIMIT 1"
                    )
                    self.assertEqual(
                        cursor.fetchone(),
                        ("failed", "interrupted_attempt_recovered"),
                    )
                    cursor.execute(
                        "SELECT status FROM auth_login_provision_attempts "
                        "WHERE login_kind = 'worker'"
                    )
                    self.assertEqual(cursor.fetchone(), ("preparing",))
                    cursor.execute(
                        "SELECT outcome, login_enabled, smoke_verified "
                        "FROM auth_login_provision_receipts "
                        "ORDER BY created_at DESC, id DESC LIMIT 1"
                    )
                    self.assertEqual(cursor.fetchone(), ("disabled", False, False))
                    cursor.execute(
                        "SELECT string_agg(row_payload, '') FROM ("
                        "SELECT row_to_json(attempt)::text AS row_payload "
                        "FROM auth_login_provision_attempts AS attempt "
                        "UNION ALL SELECT row_to_json(receipt)::text "
                        "FROM auth_login_provision_receipts AS receipt "
                        "UNION ALL SELECT row_to_json(audit)::text "
                        "FROM audit_events AS audit "
                        "WHERE event_type LIKE 'auth.api_login.%') AS rows"
                    )
                    persisted = cursor.fetchone()[0]
                    for secret in (SECRET_ONE, SECRET_TWO, SECRET_THREE, SECRET_FOUR):
                        self.assertNotIn(secret, persisted)

    def test_advisory_lock_timeout_does_not_create_an_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            secret_path = self._secret(Path(temp_dir), "lock", SECRET_ONE)
            with self._installer() as holder:
                with holder.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
                        (provisioner.INSTALL_LOCK_NAME,),
                    )
                with self._installer() as observer:
                    with observer.cursor() as cursor:
                        cursor.execute("SELECT count(*) FROM auth_login_provision_attempts")
                        before = cursor.fetchone()[0]
                with self.assertRaisesRegex(
                    provisioner.LoginProvisionError,
                    "provision_advisory_lock_timeout",
                ):
                    provisioner.provision_or_rotate(
                        "provision",
                        credential_file=secret_path,
                        credential_version="lock-timeout-v1",
                        initiated_by="postgres-gate",
                        repository_root=ROOT,
                        lock_timeout_seconds=0.1,
                        drain_confirmed=False,
                    )
                with self._installer() as observer:
                    with observer.cursor() as cursor:
                        cursor.execute("SELECT count(*) FROM auth_login_provision_attempts")
                        self.assertEqual(cursor.fetchone()[0], before)


if __name__ == "__main__":
    unittest.main()
