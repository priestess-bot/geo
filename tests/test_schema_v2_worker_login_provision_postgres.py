from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from scripts import schema_v2_provision_login as provisioner


BEHAVIOR_TEST_ENABLED = os.getenv("SCHEMA_V2_BEHAVIOR_TEST") == "1"
ROOT = Path(__file__).resolve().parents[1]
SECRET_ONE = "Worker-Login-V2_First-Credential-2026!Alpha"
SECRET_TWO = "Worker-Login-V2_Second-Credential-2026!Beta"
SECRET_THREE = "Worker-Login-V2_Third-Credential-2026!Gamma"
SECRET_FOUR = "Worker-Login-V2_Fourth-Credential-2026!Delta"


@unittest.skipUnless(BEHAVIOR_TEST_ENABLED, "SCHEMA_V2_BEHAVIOR_TEST=1 is required")
class SchemaV2WorkerLoginProvisionPostgresTest(unittest.TestCase):
    def _secret(self, directory: Path, name: str, value: str) -> Path:
        path = directory / name
        path.write_text(value, encoding="utf-8")
        path.chmod(0o600)
        return path

    def _installer(self) -> psycopg.Connection[object]:
        return psycopg.connect(autocommit=True)

    def _worker_env(self) -> dict[str, str]:
        config = provisioner.installer_config_from_env()
        return {
            "PGHOST": config.endpoint.host,
            "PGPORT": str(config.endpoint.port),
            "PGDATABASE": config.endpoint.database,
        }

    def _check_worker(self, path: Path, version: str) -> None:
        with patch.dict(os.environ, self._worker_env(), clear=True):
            provisioner.check_login(
                credential_file=path,
                credential_version=version,
                repository_root=ROOT,
                login_kind="worker",
            )

    def _worker_connect_fails(self, secret: str) -> None:
        config = provisioner.installer_config_from_env()
        with self.assertRaises(psycopg.Error):
            psycopg.connect(
                **provisioner._connect_kwargs(config.endpoint),
                user=provisioner.WORKER_LOGIN_ROLE,
                password=secret,
            )

    def _insert_dispatch_fixture(self) -> tuple[UUID, UUID]:
        marker = uuid4().hex
        tenant_id = uuid4()
        project_id = uuid4()
        query_id = uuid4()
        run_id = uuid4()
        job_id = uuid4()
        market_code = f"worker-{marker}"
        industry_code = f"geo-{marker}"
        query_hash = hashlib.sha256(marker.encode("utf-8")).hexdigest()
        with self._installer() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO market_profiles (market_code, payload) VALUES (%s, %s)",
                    (market_code, Jsonb({"fixture": "worker-login"})),
                )
                cursor.execute(
                    "INSERT INTO industry_profiles (market_code, industry_code, payload) "
                    "VALUES (%s, %s, %s)",
                    (
                        market_code,
                        industry_code,
                        Jsonb({"fixture": "worker-login"}),
                    ),
                )
                cursor.execute(
                    "INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)",
                    (tenant_id, f"Worker Login {marker}", f"worker-login-{marker}"),
                )
                cursor.execute(
                    "INSERT INTO projects ("
                    "id, tenant_id, name, market_code, industry_code, target_brand, "
                    "category, prompt_version, status) VALUES ("
                    "%s, %s, %s, %s, %s, 'Worker Brand', 'GEO', 'v1', 'active')",
                    (
                        project_id,
                        tenant_id,
                        f"Worker Login {marker}",
                        market_code,
                        industry_code,
                    ),
                )
                cursor.execute(
                    "INSERT INTO monitoring_queries ("
                    "id, tenant_id, project_id, query_text, query_hash, "
                    "observation_objective, intent_type, market_code, language_code, "
                    "device_class, created_by, updated_by) VALUES ("
                    "%s, %s, %s, %s, %s, 'discovery', 'informational', %s, "
                    "'en', 'desktop', 'worker-login-gate', 'worker-login-gate')",
                    (
                        query_id,
                        tenant_id,
                        project_id,
                        f"Worker dispatch fixture {marker}",
                        query_hash,
                        market_code,
                    ),
                )
                cursor.execute(
                    "INSERT INTO collection_runs ("
                    "id, tenant_id, project_id, status, idempotency_key, requested_by, "
                    "collection_method_version, expected_job_count) VALUES ("
                    "%s, %s, %s, 'queued', %s, 'worker-login-gate', 'v2', 1)",
                    (run_id, tenant_id, project_id, f"run-{marker}"),
                )
                cursor.execute(
                    "INSERT INTO collection_run_queries ("
                    "tenant_id, project_id, collection_run_id, monitoring_query_id, "
                    "ordinal, sample_size, query_text_snapshot, query_hash_snapshot, "
                    "market_code_snapshot, language_code_snapshot, "
                    "device_class_snapshot) SELECT %s, %s, %s, id, 0, 1, query_text, "
                    "query_hash, market_code, language_code, device_class "
                    "FROM monitoring_queries WHERE id = %s",
                    (tenant_id, project_id, run_id, query_id),
                )
                cursor.execute(
                    "INSERT INTO collection_jobs ("
                    "id, tenant_id, project_id, collection_run_id, monitoring_query_id, "
                    "platform, surface, access_method, sample_index, idempotency_key) "
                    "VALUES (%s, %s, %s, %s, %s, 'openai', 'responses', "
                    "'official_api', 1, %s)",
                    (
                        job_id,
                        tenant_id,
                        project_id,
                        run_id,
                        query_id,
                        f"job-{marker}",
                    ),
                )
                cursor.execute(
                    "SELECT id FROM durable_job_dispatch_outbox "
                    "WHERE collection_job_id = %s",
                    (job_id,),
                )
                dispatch_id = cursor.fetchone()[0]
        return project_id, dispatch_id

    def test_worker_provision_rotation_recovery_compensation_and_disable(self) -> None:
        with self._installer() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT rolcanlogin, rolpassword IS NULL FROM pg_authid "
                    "WHERE rolname = 'geo_v2_worker_login'"
                )
                self.assertEqual(cursor.fetchone(), (False, True))
                cursor.execute(
                    "SELECT rolcanlogin, rolpassword IS NULL FROM pg_authid "
                    "WHERE rolname = 'geo_v2_api_login'"
                )
                self.assertEqual(cursor.fetchone(), (False, True))
                cursor.execute(
                    "INSERT INTO auth_login_provision_attempts ("
                    "login_kind, operation, credential_version, initiated_by) "
                    "VALUES ('api', 'provision', 'api-isolation-pending-v1', "
                    "'worker-postgres-gate')"
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            first = self._secret(directory, "first", SECRET_ONE)
            second = self._secret(directory, "second", SECRET_TWO)
            third = self._secret(directory, "third", SECRET_THREE)
            fourth = self._secret(directory, "fourth", SECRET_FOUR)

            provisioner.provision_or_rotate(
                "provision",
                credential_file=first,
                credential_version="worker-login-v1",
                initiated_by="worker-postgres-gate",
                repository_root=ROOT,
                lock_timeout_seconds=2,
                drain_confirmed=False,
                login_kind="worker",
            )
            self._check_worker(first, "worker-login-v1")

            with self._installer() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("GRANT SELECT ON collection_jobs TO geo_v2_worker")
            try:
                with self.assertRaisesRegex(
                    provisioner.LoginProvisionError,
                    "worker_login_direct_data_acl_smoke_failed",
                ):
                    self._check_worker(first, "worker-login-v1")
            finally:
                with self._installer() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("REVOKE SELECT ON collection_jobs FROM geo_v2_worker")

            with self._installer() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "CREATE FUNCTION geo_v2_complete_durable_job_dispatch(text) "
                        "RETURNS integer LANGUAGE sql AS 'SELECT 1'"
                    )
                    cursor.execute(
                        "REVOKE ALL ON FUNCTION "
                        "geo_v2_complete_durable_job_dispatch(text) FROM PUBLIC"
                    )
                    cursor.execute(
                        "GRANT EXECUTE ON FUNCTION "
                        "geo_v2_complete_durable_job_dispatch(text) TO geo_v2_worker"
                    )
            try:
                with self.assertRaisesRegex(
                    provisioner.LoginProvisionError,
                    "worker_login_function_acl_smoke_failed",
                ):
                    self._check_worker(first, "worker-login-v1")
            finally:
                with self._installer() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "DROP FUNCTION geo_v2_complete_durable_job_dispatch(text)"
                        )

            with self._installer() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT status FROM auth_login_provision_attempts "
                        "WHERE login_kind = 'api' "
                        "AND credential_version = 'api-isolation-pending-v1'"
                    )
                    self.assertEqual(cursor.fetchone(), ("preparing",))
                    cursor.execute(
                        "SELECT rolcanlogin, rolpassword IS NULL FROM pg_authid "
                        "WHERE rolname = 'geo_v2_api_login'"
                    )
                    self.assertEqual(cursor.fetchone(), (False, True))
                    cursor.execute(
                        "SELECT parent.rolname, child.rolname, membership.admin_option, "
                        "membership.inherit_option, membership.set_option "
                        "FROM pg_auth_members AS membership "
                        "JOIN pg_roles AS parent ON parent.oid = membership.roleid "
                        "JOIN pg_roles AS child ON child.oid = membership.member "
                        "WHERE parent.rolname = 'geo_v2_worker_login' "
                        "OR child.rolname = 'geo_v2_worker_login'"
                    )
                    self.assertEqual(
                        cursor.fetchall(),
                        [("geo_v2_worker", "geo_v2_worker_login", False, False, True)],
                    )

            project_id, dispatch_id = self._insert_dispatch_fixture()
            config = provisioner.installer_config_from_env()
            with psycopg.connect(
                **provisioner._connect_kwargs(config.endpoint),
                user=provisioner.WORKER_LOGIN_ROLE,
                password=SECRET_ONE,
            ) as worker_connection:
                with worker_connection.cursor() as cursor:
                    with self.assertRaises(
                        (psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable)
                    ):
                        cursor.execute("SELECT count(*) FROM auth_login_provision_attempts")
                    worker_connection.rollback()
                    with self.assertRaises(
                        (psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable)
                    ):
                        cursor.execute(
                            "INSERT INTO auth_login_provision_attempts ("
                            "login_kind, operation, credential_version, initiated_by) "
                            "VALUES ('worker', 'provision', 'forbidden-v1', 'forbidden')"
                        )
                    worker_connection.rollback()
                    cursor.execute("SET LOCAL ROLE geo_v2_worker")
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        cursor.execute("SELECT count(*) FROM public.collection_jobs")
                    worker_connection.rollback()
                    cursor.execute("SET LOCAL ROLE geo_v2_worker")
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        cursor.execute("SET LOCAL ROLE geo_v2_runtime")
                    worker_connection.rollback()
                    cursor.execute(
                        "SELECT current_user, session_user, "
                        "current_setting('role', true), "
                        "current_setting('app.session_token_hash', true)"
                    )
                    current_user, session_user, active_role, session_hash = cursor.fetchone()
                    self.assertEqual(current_user, provisioner.WORKER_LOGIN_ROLE)
                    self.assertEqual(session_user, provisioner.WORKER_LOGIN_ROLE)
                    self.assertIn(active_role, (None, "none"))
                    self.assertIn(session_hash, (None, ""))
                    worker_connection.rollback()

                    worker_id = "worker-real-login-gate"
                    with worker_connection.transaction():
                        cursor.execute("SET LOCAL ROLE geo_v2_worker")
                        cursor.execute(
                            "SELECT id, lease_token, status "
                            "FROM geo_v2_claim_durable_job_dispatch(%s, %s, %s, %s)",
                            (worker_id, 30, project_id, dispatch_id),
                        )
                        claimed_id, lease_token, status = cursor.fetchone()
                        self.assertEqual(claimed_id, dispatch_id)
                        self.assertEqual(status, "dispatching")

                    with worker_connection.transaction():
                        cursor.execute("SET LOCAL ROLE geo_v2_worker")
                        cursor.execute(
                            "SELECT status FROM geo_v2_heartbeat_durable_job_dispatch("
                            "%s, %s, %s, %s)",
                            (dispatch_id, worker_id, lease_token, 30),
                        )
                        self.assertEqual(cursor.fetchone(), ("dispatching",))

                    with worker_connection.transaction():
                        cursor.execute("SET LOCAL ROLE geo_v2_worker")
                        cursor.execute(
                            "SELECT status FROM geo_v2_complete_durable_job_dispatch("
                            "%s, %s, %s)",
                            (dispatch_id, worker_id, lease_token),
                        )
                        self.assertEqual(cursor.fetchone(), ("dispatched",))

                    cursor.execute(
                        "SELECT current_user, session_user, "
                        "current_setting('role', true)"
                    )
                    self.assertEqual(
                        cursor.fetchone(),
                        (
                            provisioner.WORKER_LOGIN_ROLE,
                            provisioner.WORKER_LOGIN_ROLE,
                            "none",
                        ),
                    )
                    worker_connection.rollback()

            with self._installer() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT status, dispatched_by, lease_token IS NULL "
                        "FROM durable_job_dispatch_outbox WHERE id = %s",
                        (dispatch_id,),
                    )
                    self.assertEqual(
                        cursor.fetchone(),
                        ("dispatched", "worker-real-login-gate", True),
                    )

            with self.assertRaisesRegex(
                provisioner.LoginProvisionError,
                "rotation_requires_drain_confirmation",
            ):
                provisioner.provision_or_rotate(
                    "rotate",
                    credential_file=second,
                    credential_version="worker-login-v2",
                    initiated_by="worker-postgres-gate",
                    repository_root=ROOT,
                    lock_timeout_seconds=2,
                    drain_confirmed=False,
                    login_kind="worker",
                )

            provisioner.provision_or_rotate(
                "rotate",
                credential_file=second,
                credential_version="worker-login-v2",
                initiated_by="worker-postgres-gate",
                repository_root=ROOT,
                lock_timeout_seconds=2,
                drain_confirmed=True,
                login_kind="worker",
            )
            self._worker_connect_fails(SECRET_ONE)
            self._check_worker(second, "worker-login-v2")

            with patch.object(
                provisioner,
                "_smoke_login",
                side_effect=provisioner.LoginProvisionError("injected_smoke_failure"),
            ):
                with self.assertRaisesRegex(
                    provisioner.LoginProvisionError,
                    "worker_login_smoke_failed",
                ):
                    provisioner.provision_or_rotate(
                        "rotate",
                        credential_file=third,
                        credential_version="worker-login-v3",
                        initiated_by="worker-postgres-gate",
                        repository_root=ROOT,
                        lock_timeout_seconds=2,
                        drain_confirmed=True,
                        login_kind="worker",
                    )
            self._worker_connect_fails(SECRET_TWO)
            self._worker_connect_fails(SECRET_THREE)

            provisioner.provision_or_rotate(
                "provision",
                credential_file=third,
                credential_version="worker-login-v4",
                initiated_by="worker-postgres-gate",
                repository_root=ROOT,
                lock_timeout_seconds=2,
                drain_confirmed=False,
                login_kind="worker",
            )
            with self._installer() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO auth_login_provision_attempts ("
                        "login_kind, operation, credential_version, "
                        "previous_credential_version, initiated_by) "
                        "VALUES ('worker', 'rotate', 'worker-interrupted-v5', "
                        "'worker-login-v4', 'worker-postgres-gate')"
                    )
            with self.assertRaisesRegex(
                provisioner.LoginProvisionError,
                "worker_login_startup_readiness_failed",
            ):
                self._check_worker(third, "worker-login-v4")

            provisioner.provision_or_rotate(
                "provision",
                credential_file=fourth,
                credential_version="worker-login-v6",
                initiated_by="worker-postgres-gate",
                repository_root=ROOT,
                lock_timeout_seconds=2,
                drain_confirmed=False,
                login_kind="worker",
            )
            self._worker_connect_fails(SECRET_THREE)
            self._check_worker(fourth, "worker-login-v6")

            provisioner.disable_login(
                initiated_by="worker-postgres-gate",
                lock_timeout_seconds=2,
                login_kind="worker",
            )
            self._worker_connect_fails(SECRET_FOUR)

            with self._installer() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT operation, status FROM auth_login_provision_attempts "
                        "WHERE login_kind = 'worker' "
                        "ORDER BY attempt_sequence DESC LIMIT 1"
                    )
                    self.assertEqual(cursor.fetchone(), ("disable", "succeeded"))
                    cursor.execute(
                        "SELECT status, failure_code FROM auth_login_provision_attempts "
                        "WHERE credential_version = 'worker-interrupted-v5'"
                    )
                    self.assertEqual(
                        cursor.fetchone(),
                        ("failed", "interrupted_attempt_recovered"),
                    )
                    cursor.execute(
                        "SELECT auth.rolcanlogin, auth.rolpassword IS NULL, "
                        "role_row.rolconfig IS NULL FROM pg_authid AS auth "
                        "JOIN pg_roles AS role_row ON role_row.oid = auth.oid "
                        "WHERE auth.rolname = 'geo_v2_worker_login'"
                    )
                    self.assertEqual(cursor.fetchone(), (False, True, True))
                    cursor.execute(
                        "SELECT string_agg(row_payload, '') FROM ("
                        "SELECT row_to_json(attempt)::text AS row_payload "
                        "FROM auth_login_provision_attempts AS attempt "
                        "UNION ALL SELECT row_to_json(receipt)::text "
                        "FROM auth_login_provision_receipts AS receipt "
                        "UNION ALL SELECT row_to_json(event)::text "
                        "FROM audit_events AS event "
                        "WHERE event.event_type LIKE 'auth.worker_login.%') AS rows"
                    )
                    persisted = cursor.fetchone()[0]
                    for secret in (SECRET_ONE, SECRET_TWO, SECRET_THREE, SECRET_FOUR):
                        self.assertNotIn(secret, persisted)
                    self.assertNotIn("SCRAM-SHA-256$", persisted)


if __name__ == "__main__":
    unittest.main()
