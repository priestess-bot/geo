from __future__ import annotations

import hashlib
import os
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
from psycopg.pq import TransactionStatus

from geno_core.schema_v2.session_uow import (
    SchemaV2ApiSessionUnitOfWork,
    SchemaV2RawSessionTokenError,
    SchemaV2SessionAuthorizationError,
    hash_raw_session_token,
)


BEHAVIOR_TEST_ENABLED = os.getenv("SCHEMA_V2_BEHAVIOR_TEST") == "1"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@unittest.skipUnless(BEHAVIOR_TEST_ENABLED, "SCHEMA_V2_BEHAVIOR_TEST=1 is required")
class SchemaV2SessionUnitOfWorkPostgresBehaviorTest(unittest.TestCase):
    tenant_id: UUID
    project_ids: tuple[UUID, UUID]
    actor_id: str
    raw_tokens: dict[str, str]
    session_ids: dict[str, UUID]
    probe_schema: str

    @classmethod
    def setUpClass(cls) -> None:
        unique = uuid4().hex
        cls.tenant_id = uuid4()
        cls.project_ids = tuple(sorted((uuid4(), uuid4()), key=str))
        cls.actor_id = f"session-uow-{unique}@example.test"
        cls.raw_tokens = {
            state: f"schema-v2-session-uow-{state}-{unique}"
            for state in ("valid", "expired", "revoked")
        }
        cls.session_ids = {}
        cls.probe_schema = f"session_uow_probe_{unique}"
        market_code = f"UOW-{unique}"
        industry_code = f"uow_{unique}"

        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO market_profiles (market_code, payload) VALUES (%s, %s)",
                    (market_code, psycopg.types.json.Jsonb({"fixture": "session-uow"})),
                )
                cursor.execute(
                    "INSERT INTO industry_profiles "
                    "(market_code, industry_code, payload) VALUES (%s, %s, %s)",
                    (
                        market_code,
                        industry_code,
                        psycopg.types.json.Jsonb({"fixture": "session-uow"}),
                    ),
                )
                cursor.execute(
                    "INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)",
                    (cls.tenant_id, f"Session UoW {unique}", f"session-uow-{unique}"),
                )
                for project_id, role in zip(
                    cls.project_ids,
                    ("project_owner", "analyst"),
                    strict=True,
                ):
                    cursor.execute(
                        "INSERT INTO projects ("
                        "id, tenant_id, name, market_code, industry_code, target_brand, "
                        "category, prompt_version, status) "
                        "VALUES (%s, %s, %s, %s, %s, 'UoW Brand', 'UoW', 'v1', 'active')",
                        (
                            project_id,
                            cls.tenant_id,
                            f"Session UoW Project {project_id}",
                            market_code,
                            industry_code,
                        ),
                    )
                    cursor.execute(
                        "INSERT INTO project_members "
                        "(tenant_id, project_id, user_id, role) VALUES (%s, %s, %s, %s)",
                        (cls.tenant_id, project_id, cls.actor_id, role),
                    )

                project_scopes: list[dict[str, object]] = []
                aggregate_permissions: set[str] = set()
                for project_id, role in zip(
                    cls.project_ids,
                    ("project_owner", "analyst"),
                    strict=True,
                ):
                    cursor.execute(
                        "SELECT permission FROM unnest("
                        "geno_v2_permissions_for_role(%s)) AS item(permission) "
                        "ORDER BY permission",
                        (role,),
                    )
                    permissions = [row[0] for row in cursor.fetchall()]
                    aggregate_permissions.update(permissions)
                    project_scopes.append(
                        {
                            "project_id": str(project_id),
                            "roles": [role],
                            "permissions": permissions,
                            "portal_capabilities": ["portal.admin.access"],
                            "scope_sources": ["direct_member"],
                        }
                    )

                now = datetime.now(UTC)
                for state, issued_at, expires_at in (
                    ("valid", now - timedelta(minutes=1), now + timedelta(days=1)),
                    ("expired", now - timedelta(days=2), now - timedelta(days=1)),
                    ("revoked", now - timedelta(minutes=1), now + timedelta(days=1)),
                ):
                    cls.session_ids[state] = cls._insert_session_lineage(
                        cursor,
                        state=state,
                        issued_at=issued_at,
                        expires_at=expires_at,
                        project_scopes=project_scopes,
                        aggregate_permissions=sorted(aggregate_permissions),
                    )

                cursor.execute(
                    "UPDATE runtime_sessions SET status = 'revoked', "
                    "revoked_at = clock_timestamp(), "
                    "revoked_by = 'session-uow-behavior-test', "
                    "revoke_reason = 'fixture-revocation', "
                    "updated_at = clock_timestamp() "
                    "WHERE id = %s",
                    (cls.session_ids["revoked"],),
                )
                cursor.execute(f"CREATE SCHEMA {cls.probe_schema}")
                cursor.execute(
                    f"CREATE TABLE {cls.probe_schema}.transaction_probe "
                    "(marker text PRIMARY KEY)"
                )
                cursor.execute(f"GRANT USAGE ON SCHEMA {cls.probe_schema} TO geno_v2_runtime")
                cursor.execute(
                    f"GRANT SELECT, INSERT ON {cls.probe_schema}.transaction_probe "
                    "TO geno_v2_runtime"
                )

    @classmethod
    def tearDownClass(cls) -> None:
        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP SCHEMA IF EXISTS {cls.probe_schema} CASCADE")

    @classmethod
    def _insert_session_lineage(
        cls,
        cursor: psycopg.Cursor[object],
        *,
        state: str,
        issued_at: datetime,
        expires_at: datetime,
        project_scopes: list[dict[str, object]],
        aggregate_permissions: list[str],
    ) -> UUID:
        invitation_id = uuid4()
        attempt_id = uuid4()
        session_id = uuid4()
        invitation_created_at = issued_at - timedelta(seconds=3)
        attempt_created_at = issued_at - timedelta(seconds=2)
        accepted_at = issued_at - timedelta(seconds=1)
        invitation_expires_at = issued_at + timedelta(days=2)
        delivery_expires_at = min(expires_at, issued_at + timedelta(minutes=15))
        invitation_token_hash = _digest(f"session-uow-invitation-{state}-{invitation_id}")

        cursor.execute(
            "INSERT INTO project_member_invitations ("
            "id, tenant_id, project_id, email, role, status, invite_token_hash, "
            "audience, allowed_surfaces, invited_by, accepted_by_attempt_id, "
            "expires_at, accepted_at, created_at) "
            "VALUES (%s, %s, %s, %s, 'project_owner', 'accepted', %s, "
            "'admin', ARRAY['admin']::text[], 'session-uow-behavior-test', %s, %s, %s, %s)",
            (
                invitation_id,
                cls.tenant_id,
                cls.project_ids[0],
                cls.actor_id,
                invitation_token_hash,
                attempt_id,
                invitation_expires_at,
                accepted_at,
                invitation_created_at,
            ),
        )
        cursor.execute(
            "INSERT INTO auth_invitation_redemption_attempts ("
            "id, tenant_id, project_id, invitation_id, requested_surface, "
            "idempotency_key_hash, request_hash, token_fingerprint, session_id, "
            "status, created_at, delivery_ciphertext, delivery_key_id, "
            "delivery_nonce, delivery_expires_at) "
            "VALUES (%s, %s, %s, %s, 'admin', %s, %s, %s, %s, "
            "'succeeded', %s, %s, %s, %s, %s)",
            (
                attempt_id,
                cls.tenant_id,
                cls.project_ids[0],
                invitation_id,
                _digest(f"session-uow-idempotency-{state}-{attempt_id}"),
                _digest(f"session-uow-request-{state}-{attempt_id}"),
                invitation_token_hash,
                session_id,
                attempt_created_at,
                b"encrypted-session-token-fixture",
                "session-uow-behavior-key",
                b"session-uow-behavior-nonce",
                delivery_expires_at,
            ),
        )
        cursor.execute(
            "INSERT INTO runtime_sessions ("
            "id, session_token_hash, actor_id, tenant_id, project_ids, roles, "
            "permissions, tenant_roles, project_scopes, redemption_attempt_id, "
            "issued_by, issued_at, expires_at, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, '[]'::jsonb, %s, %s, "
            "'session-uow-behavior-test', %s, %s, %s)",
            (
                session_id,
                _digest(cls.raw_tokens[state]),
                cls.actor_id,
                cls.tenant_id,
                psycopg.types.json.Jsonb([str(value) for value in cls.project_ids]),
                psycopg.types.json.Jsonb(["analyst", "project_owner"]),
                psycopg.types.json.Jsonb(aggregate_permissions),
                psycopg.types.json.Jsonb(project_scopes),
                attempt_id,
                issued_at,
                expires_at,
                psycopg.types.json.Jsonb({"fixture": state}),
            ),
        )
        return session_id

    def _connect_as_api_placeholder(self) -> psycopg.Connection[object]:
        connection = psycopg.connect(autocommit=True)
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION AUTHORIZATION geno_v2_api_login")
        connection.autocommit = False
        self._assert_clean_connection(connection)
        return connection

    def _assert_clean_connection(self, connection: psycopg.Connection[object]) -> None:
        self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_user, session_user, "
                "current_setting('app.session_token_hash', true)"
            )
            current_user, session_user, token_setting = cursor.fetchone()
        connection.rollback()
        self.assertEqual(current_user, "geno_v2_api_login")
        self.assertEqual(session_user, "geno_v2_api_login")
        self.assertIn(token_setting, (None, ""))
        self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)

    def _new_uow(
        self,
        connection: psycopg.Connection[object],
        raw_token: str,
    ) -> SchemaV2ApiSessionUnitOfWork:
        return SchemaV2ApiSessionUnitOfWork(
            connection,
            session_token_hash=hash_raw_session_token(raw_token),
        )

    def test_valid_raw_token_resolves_complete_multi_project_context(self) -> None:
        with self._connect_as_api_placeholder() as connection:
            unit_of_work = self._new_uow(connection, self.raw_tokens["valid"])
            with unit_of_work:
                context = unit_of_work.session_context
                self.assertEqual(context.session_id, self.session_ids["valid"])
                self.assertEqual(context.actor_id, self.actor_id)
                self.assertEqual(context.tenant_id, self.tenant_id)
                self.assertEqual(context.project_ids, self.project_ids)
                self.assertEqual(context.tenant_roles, ())
                self.assertEqual(
                    tuple(scope.project_id for scope in context.project_scopes),
                    self.project_ids,
                )
                self.assertEqual(
                    tuple(scope.roles for scope in context.project_scopes),
                    (("project_owner",), ("analyst",)),
                )
                with unit_of_work.cursor() as cursor:
                    cursor.execute("SELECT id FROM projects ORDER BY id")
                    self.assertEqual(tuple(row[0] for row in cursor.fetchall()), self.project_ids)

            self.assertEqual(unit_of_work.transaction_outcome, "committed")
            self.assertTrue(unit_of_work.connection_reusable)
            self.assertEqual(unit_of_work.cleanup_telemetry.status, "succeeded")
            self._assert_clean_connection(connection)

    def test_invalid_unknown_expired_and_revoked_tokens_fail_closed_without_leaks(self) -> None:
        with self.assertRaises(SchemaV2RawSessionTokenError):
            hash_raw_session_token("")

        with self._connect_as_api_placeholder() as connection:
            with self._new_uow(connection, self.raw_tokens["valid"]) as unit_of_work:
                self.assertEqual(unit_of_work.session_context.actor_id, self.actor_id)
            self._assert_clean_connection(connection)

            for label, raw_token in (
                ("unknown", f"unknown-{uuid4()}"),
                ("expired", self.raw_tokens["expired"]),
                ("revoked", self.raw_tokens["revoked"]),
            ):
                with self.subTest(label=label):
                    unit_of_work = self._new_uow(connection, raw_token)
                    with self.assertRaises(SchemaV2SessionAuthorizationError) as raised:
                        with unit_of_work:
                            self.fail("an unusable session must not enter the business block")
                    self.assertNotIn(raw_token, str(raised.exception))
                    self.assertNotIn(_digest(raw_token), str(raised.exception))
                    self.assertEqual(unit_of_work.transaction_outcome, "rolled_back")
                    self.assertTrue(unit_of_work.connection_reusable)
                    self.assertEqual(unit_of_work.cleanup_telemetry.status, "succeeded")
                    self._assert_clean_connection(connection)

            with self._new_uow(connection, self.raw_tokens["valid"]) as unit_of_work:
                self.assertEqual(unit_of_work.session_context.actor_id, self.actor_id)
            self._assert_clean_connection(connection)

    def test_business_commit_and_rollback_are_transactional(self) -> None:
        committed_marker = f"committed-{uuid4()}"
        rolled_back_marker = f"rolled-back-{uuid4()}"
        with self._connect_as_api_placeholder() as connection:
            committed = self._new_uow(connection, self.raw_tokens["valid"])
            with committed:
                with committed.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO {self.probe_schema}.transaction_probe (marker) "
                        "VALUES (%s)",
                        (committed_marker,),
                    )
            self.assertEqual(committed.transaction_outcome, "committed")
            self._assert_clean_connection(connection)

            rolled_back = self._new_uow(connection, self.raw_tokens["valid"])
            with self.assertRaisesRegex(RuntimeError, "force business rollback"):
                with rolled_back:
                    with rolled_back.cursor() as cursor:
                        cursor.execute(
                            f"INSERT INTO {self.probe_schema}.transaction_probe (marker) "
                            "VALUES (%s)",
                            (rolled_back_marker,),
                        )
                    raise RuntimeError("force business rollback")
            self.assertEqual(rolled_back.transaction_outcome, "rolled_back")
            self._assert_clean_connection(connection)

        with psycopg.connect() as owner_connection:
            with owner_connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT marker FROM {self.probe_schema}.transaction_probe ORDER BY marker"
                )
                self.assertEqual(cursor.fetchall(), [(committed_marker,)])

    def test_runtime_cannot_enumerate_sensitive_auth_tables(self) -> None:
        with self._connect_as_api_placeholder() as connection:
            for table_name in (
                "project_member_invitations",
                "auth_invitation_redemption_attempts",
                "runtime_sessions",
                "runtime_session_reauth_queue",
                "auth_preflight_rate_limits",
                "auth_runtime_write_controls",
            ):
                with self.subTest(table_name=table_name):
                    unit_of_work = self._new_uow(connection, self.raw_tokens["valid"])
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        with unit_of_work:
                            with unit_of_work.cursor() as cursor:
                                cursor.execute(f"SELECT * FROM {table_name}")
                    self.assertEqual(unit_of_work.transaction_outcome, "rolled_back")
                    self.assertTrue(unit_of_work.connection_reusable)
                    self._assert_clean_connection(connection)


if __name__ == "__main__":
    unittest.main(verbosity=2)
