from __future__ import annotations

import hashlib
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from geno_core.auth_delivery import AuthDeliveryKeyring
from geno_core.schema_v2 import (
    SchemaV2AnonymousAuthCommandError,
    SchemaV2AnonymousAuthResultError,
    SchemaV2AnonymousAuthUnitOfWork,
    SchemaV2ApiSessionUnitOfWork,
    SchemaV2InvitationSurface,
    SchemaV2PreflightResultCode,
    SchemaV2RedeemResultCode,
    build_redemption_material,
    build_source_identity_hmac_key,
    hash_raw_idempotency_key,
    hash_raw_invitation_token,
    hash_raw_session_token,
    hmac_source_identity,
)


BEHAVIOR_TEST_ENABLED = os.getenv("SCHEMA_V2_BEHAVIOR_TEST") == "1"
SENSITIVE_TABLES = (
    "project_member_invitations",
    "auth_invitation_redemption_attempts",
    "runtime_sessions",
    "auth_preflight_rate_limits",
    "runtime_session_reauth_queue",
    "auth_runtime_write_controls",
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@unittest.skipUnless(BEHAVIOR_TEST_ENABLED, "SCHEMA_V2_BEHAVIOR_TEST=1 is required")
class SchemaV2AnonymousAuthUowPostgresTest(unittest.TestCase):
    tenant_id: UUID
    project_ids: tuple[UUID, UUID, UUID]
    keyring: AuthDeliveryKeyring

    @classmethod
    def setUpClass(cls) -> None:
        marker = uuid4().hex
        cls.tenant_id = uuid4()
        cls.project_ids = tuple(sorted((uuid4(), uuid4(), uuid4()), key=str))
        cls.keyring = AuthDeliveryKeyring(
            active_key_id="schema-v2-pg-aes-v1",
            keys={"schema-v2-pg-aes-v1": hashlib.sha256(b"schema-v2-real-pg-key").digest()},
        )
        market_code = f"ANON-{marker}"
        industry_code = f"anonymous_{marker}"
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO market_profiles (market_code, payload) VALUES (%s, %s)",
                    (market_code, Jsonb({"fixture": "anonymous-auth-uow"})),
                )
                cursor.execute(
                    "INSERT INTO industry_profiles "
                    "(market_code, industry_code, payload) VALUES (%s, %s, %s)",
                    (
                        market_code,
                        industry_code,
                        Jsonb({"fixture": "anonymous-auth-uow"}),
                    ),
                )
                cursor.execute(
                    "INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)",
                    (
                        cls.tenant_id,
                        f"Anonymous Auth UoW {marker}",
                        f"anonymous-auth-uow-{marker}",
                    ),
                )
                for project_id in cls.project_ids:
                    cursor.execute(
                        "INSERT INTO projects ("
                        "id, tenant_id, name, market_code, industry_code, target_brand, "
                        "category, prompt_version, status) VALUES ("
                        "%s, %s, %s, %s, %s, 'Anonymous Brand', "
                        "'Anonymous', 'v1', 'active')",
                        (
                            project_id,
                            cls.tenant_id,
                            f"Anonymous Project {project_id}",
                            market_code,
                            industry_code,
                        ),
                    )

    @classmethod
    def _insert_pending_invitation(
        cls,
        *,
        actor_id: str,
        role: str,
        raw_invitation_token: str,
        project_id: UUID | None = None,
        expires_at: datetime | None = None,
    ) -> UUID:
        invitation_id = uuid4()
        project_id = project_id or cls.project_ids[0]
        audience = "customer" if role == "client_viewer" else "admin"
        now = datetime.now(UTC)
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO project_member_invitations ("
                    "id, tenant_id, project_id, email, role, invite_token_hash, "
                    "audience, allowed_surfaces, invited_by, expires_at, "
                    "created_at, updated_at) VALUES ("
                    "%s, %s, %s, %s, %s, %s, %s, ARRAY[%s]::text[], "
                    "'anonymous-auth-uow-test', %s, %s, %s)",
                    (
                        invitation_id,
                        cls.tenant_id,
                        project_id,
                        actor_id,
                        role,
                        _digest(raw_invitation_token),
                        audience,
                        audience,
                        expires_at or now + timedelta(days=1),
                        now,
                        now,
                    ),
                )
        return invitation_id

    @classmethod
    def _insert_member(
        cls,
        *,
        actor_id: str,
        project_id: UUID,
        role: str,
    ) -> None:
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO project_members "
                    "(tenant_id, project_id, user_id, role, invited_by) "
                    "VALUES (%s, %s, %s, %s, 'anonymous-auth-uow-test')",
                    (cls.tenant_id, project_id, actor_id, role),
                )

    @classmethod
    def _material(
        cls,
        *,
        attempt_id: UUID,
        raw_session_token: str,
        raw_csrf_token: str,
        session_expires_at: datetime | None = None,
    ):
        return build_redemption_material(
            raw_session_token,
            raw_csrf_token,
            session_cookie_name="geno-session",
            csrf_cookie_name="geno-csrf",
            session_expires_at=session_expires_at or datetime.now(UTC) + timedelta(days=1),
            secure=True,
            attempt_id=attempt_id,
            keyring=cls.keyring,
        )

    @classmethod
    def _redeem(
        cls,
        connection: psycopg.Connection[object],
        *,
        invitation_id: UUID,
        raw_invitation_token: str,
        raw_idempotency_key: str,
        requested_surface: SchemaV2InvitationSurface,
        attempt_id: UUID | None = None,
        session_id: UUID | None = None,
        raw_session_token: str | None = None,
        raw_csrf_token: str | None = None,
        delivery_expires_at: datetime | None = None,
        unit_of_work: SchemaV2AnonymousAuthUnitOfWork | None = None,
    ):
        attempt_id = attempt_id or uuid4()
        material = cls._material(
            attempt_id=attempt_id,
            raw_session_token=raw_session_token or f"session-{uuid4().hex}",
            raw_csrf_token=raw_csrf_token or f"csrf-{uuid4().hex}",
        )
        return (unit_of_work or SchemaV2AnonymousAuthUnitOfWork(connection)).redeem(
            attempt_id=attempt_id,
            session_id=session_id or uuid4(),
            invitation_id=invitation_id,
            invitation_token_hash=hash_raw_invitation_token(raw_invitation_token),
            requested_surface=requested_surface,
            idempotency_key_hash=hash_raw_idempotency_key(raw_idempotency_key),
            redemption_material=material,
            delivery_expires_at=delivery_expires_at or datetime.now(UTC) + timedelta(minutes=30),
        )

    @staticmethod
    def _set_writes_enabled(enabled: bool) -> None:
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE auth_runtime_write_controls SET writes_enabled = %s, "
                    "reason = %s, updated_by = 'anonymous-auth-uow-test', "
                    "updated_at = greatest(clock_timestamp(), "
                    "updated_at + interval '1 microsecond') WHERE singleton",
                    (enabled, "test-enabled" if enabled else "test-disabled"),
                )

    def test_01_preflight_shape_and_fixed_rate_limit_use_real_transactions(self) -> None:
        actor = f"preflight-{uuid4().hex}@example.test"
        raw_token = f"preflight-invitation-token-{uuid4().hex}"
        invitation_id = self._insert_pending_invitation(
            actor_id=actor,
            role="reviewer",
            raw_invitation_token=raw_token,
        )
        source_key = build_source_identity_hmac_key(
            hashlib.sha256(f"source-key-{uuid4()}".encode()).digest()
        )
        source_hmac = hmac_source_identity(
            f"198.51.100.{int(uuid4().hex[:2], 16)}",
            server_key=source_key,
        )
        invitation_hash = hash_raw_invitation_token(raw_token)

        with psycopg.connect() as connection:
            for expected_count in range(1, 21):
                uow = SchemaV2AnonymousAuthUnitOfWork(connection)
                result = uow.preflight(
                    invitation_id=invitation_id,
                    invitation_token_hash=invitation_hash,
                    requested_surface=SchemaV2InvitationSurface.ADMIN,
                    source_fingerprint_hmac=source_hmac,
                )
                self.assertEqual(result.result_code, SchemaV2PreflightResultCode.COMPATIBLE)
                self.assertEqual(result.compatibility, SchemaV2PreflightResultCode.COMPATIBLE)
                self.assertEqual(result.invitation_role, "reviewer")
                self.assertEqual(result.recommended_surface, SchemaV2InvitationSurface.ADMIN)
                self.assertEqual(result.policy_version, "auth_surface_policy_v1")
                self.assertEqual(result.invitation_request_count, expected_count)
                self.assertEqual(result.source_request_count, expected_count)
                self.assertIsNone(result.retry_after_seconds)
                self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)
                self.assertTrue(uow.connection_reusable)

            limited = SchemaV2AnonymousAuthUnitOfWork(connection).preflight(
                invitation_id=invitation_id,
                invitation_token_hash=invitation_hash,
                requested_surface=SchemaV2InvitationSurface.ADMIN,
                source_fingerprint_hmac=source_hmac,
            )
            self.assertEqual(limited.result_code, SchemaV2PreflightResultCode.RATE_LIMITED)
            self.assertEqual(limited.compatibility, SchemaV2PreflightResultCode.INVALID)
            self.assertEqual(limited.invitation_request_count, 21)
            self.assertGreater(limited.retry_after_seconds or 0, 0)
            self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)

    def test_02_wrong_surface_has_no_auth_side_effects(self) -> None:
        actor = f"wrong-surface-{uuid4().hex}@example.test"
        raw_token = f"wrong-surface-invitation-{uuid4().hex}"
        invitation_id = self._insert_pending_invitation(
            actor_id=actor,
            role="client_viewer",
            raw_invitation_token=raw_token,
        )
        with psycopg.connect() as connection:
            result = self._redeem(
                connection,
                invitation_id=invitation_id,
                raw_invitation_token=raw_token,
                raw_idempotency_key=f"wrong-surface-idempotency-{uuid4().hex}",
                requested_surface=SchemaV2InvitationSurface.ADMIN,
            )
            self.assertEqual(result.result_code, SchemaV2RedeemResultCode.SURFACE_MISMATCH)
            self.assertEqual(result.recommended_surface, SchemaV2InvitationSurface.CUSTOMER)
            self.assertIsNone(result.attempt_id)
            self.assertIsNone(result.session)
            self.assertIsNone(result.encrypted_delivery)
            self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)

        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT "
                    "(SELECT count(*) FROM auth_invitation_redemption_attempts "
                    " WHERE invitation_id = %s), "
                    "(SELECT count(*) FROM runtime_sessions WHERE actor_id = %s), "
                    "(SELECT count(*) FROM project_members WHERE tenant_id = %s "
                    " AND project_id = %s AND user_id = %s)",
                    (
                        invitation_id,
                        actor,
                        self.tenant_id,
                        self.project_ids[0],
                        actor,
                    ),
                )
                self.assertEqual(cursor.fetchone(), (0, 0, 0))

    def test_03_success_decrypts_and_same_connection_enters_session_uow(self) -> None:
        actor = f"success-{uuid4().hex}@example.test"
        raw_token = f"success-invitation-{uuid4().hex}"
        raw_session_token = f"success-session-{uuid4().hex}"
        raw_csrf_token = f"success-csrf-{uuid4().hex}"
        self._insert_member(
            actor_id=actor,
            project_id=self.project_ids[1],
            role="analyst",
        )
        invitation_id = self._insert_pending_invitation(
            actor_id=actor,
            role="reviewer",
            raw_invitation_token=raw_token,
            project_id=self.project_ids[0],
        )

        with psycopg.connect() as connection:
            anonymous_uow = SchemaV2AnonymousAuthUnitOfWork(connection)
            attempt_id = uuid4()
            material = self._material(
                attempt_id=attempt_id,
                raw_session_token=raw_session_token,
                raw_csrf_token=raw_csrf_token,
            )
            result = anonymous_uow.redeem(
                attempt_id=attempt_id,
                session_id=uuid4(),
                invitation_id=invitation_id,
                invitation_token_hash=hash_raw_invitation_token(raw_token),
                requested_surface=SchemaV2InvitationSurface.ADMIN,
                idempotency_key_hash=hash_raw_idempotency_key(f"success-idempotency-{uuid4().hex}"),
                redemption_material=material,
                delivery_expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
            self.assertEqual(result.result_code, SchemaV2RedeemResultCode.SUCCEEDED)
            self.assertEqual(result.attempt_id, attempt_id)
            session = result.session
            self.assertIsNotNone(session)
            self.assertEqual(session.actor_id, actor)  # type: ignore[union-attr]
            self.assertEqual(session.tenant_id, self.tenant_id)  # type: ignore[union-attr]
            self.assertEqual(
                session.project_ids,  # type: ignore[union-attr]
                tuple(sorted(self.project_ids[:2], key=str)),
            )
            self.assertEqual(session.tenant_roles, ())  # type: ignore[union-attr]
            scopes = {
                scope.project_id: scope
                for scope in session.project_scopes  # type: ignore[union-attr]
            }
            self.assertEqual(scopes[self.project_ids[0]].roles, ("reviewer",))
            self.assertIn("content.review", scopes[self.project_ids[0]].permissions)
            self.assertEqual(
                scopes[self.project_ids[0]].portal_capabilities,
                ("portal.admin.access",),
            )
            self.assertEqual(scopes[self.project_ids[0]].scope_sources, ("direct_member",))
            self.assertEqual(scopes[self.project_ids[1]].roles, ("analyst",))
            self.assertIn("analysis.read", scopes[self.project_ids[1]].permissions)
            delivery = result.encrypted_delivery.decrypt()  # type: ignore[union-attr]
            self.assertIn(f"geno-session={raw_session_token}", delivery.cookie_headers[0])
            self.assertIn(f"geno-csrf={raw_csrf_token}", delivery.cookie_headers[1])
            self.assertNotIn(raw_session_token, repr(result))
            self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)
            self.assertTrue(anonymous_uow.connection_reusable)

            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT session_user, current_user, current_role, "
                    "current_setting('app.session_token_hash', true)"
                )
                session_user, current_user, current_role, token_guc = cursor.fetchone()
            connection.rollback()
            self.assertEqual(current_user, session_user)
            self.assertEqual(current_role, session_user)
            self.assertNotEqual(current_role, "geno_v2_runtime")
            self.assertIn(token_guc, (None, ""))

            with SchemaV2ApiSessionUnitOfWork(
                connection,
                session_token_hash=hash_raw_session_token(raw_session_token),
            ) as session_uow:
                context = session_uow.session_context
                self.assertEqual(context.session_id, session.session_id)  # type: ignore[union-attr]
                self.assertEqual(context.actor_id, actor)
                self.assertEqual(context.project_ids, session.project_ids)  # type: ignore[union-attr]
                with session_uow.cursor() as cursor:
                    cursor.execute("SELECT id FROM projects ORDER BY id")
                    self.assertEqual(
                        tuple(row[0] for row in cursor.fetchall()),
                        context.project_ids,
                    )
            self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)
            self.assertTrue(session_uow.connection_reusable)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT session_user, current_user, current_role, "
                    "current_setting('app.session_token_hash', true)"
                )
                session_user, current_user, current_role, token_guc = cursor.fetchone()
            connection.rollback()
            self.assertEqual(current_user, session_user)
            self.assertEqual(current_role, session_user)
            self.assertNotEqual(current_role, "geno_v2_runtime")
            self.assertIn(token_guc, (None, ""))
            self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)

    def test_04_concurrent_uows_return_one_original_encrypted_delivery(self) -> None:
        actor = f"concurrent-{uuid4().hex}@example.test"
        raw_token = f"concurrent-invitation-{uuid4().hex}"
        raw_idempotency = f"concurrent-idempotency-{uuid4().hex}"
        self._insert_member(
            actor_id=actor,
            project_id=self.project_ids[1],
            role="analyst",
        )
        invitation_id = self._insert_pending_invitation(
            actor_id=actor,
            role="reviewer",
            raw_invitation_token=raw_token,
        )
        barrier = Barrier(2)

        def redeem_once(marker: str):
            attempt_id = uuid4()
            raw_session = f"concurrent-session-{marker}-{uuid4().hex}"
            raw_csrf = f"concurrent-csrf-{marker}-{uuid4().hex}"
            material = self._material(
                attempt_id=attempt_id,
                raw_session_token=raw_session,
                raw_csrf_token=raw_csrf,
            )
            with psycopg.connect() as connection:
                uow = SchemaV2AnonymousAuthUnitOfWork(connection)
                barrier.wait(timeout=5)
                result = uow.redeem(
                    attempt_id=attempt_id,
                    session_id=uuid4(),
                    invitation_id=invitation_id,
                    invitation_token_hash=hash_raw_invitation_token(raw_token),
                    requested_surface=SchemaV2InvitationSurface.ADMIN,
                    idempotency_key_hash=hash_raw_idempotency_key(raw_idempotency),
                    redemption_material=material,
                    delivery_expires_at=datetime.now(UTC) + timedelta(minutes=30),
                )
                return (
                    result,
                    (raw_session, raw_csrf),
                    connection.info.transaction_status,
                    uow.connection_reusable,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            rows = list(executor.map(redeem_once, ("one", "two")))
        results = [row[0] for row in rows]
        self.assertEqual(
            {result.result_code for result in results},
            {SchemaV2RedeemResultCode.SUCCEEDED, SchemaV2RedeemResultCode.REPLAYED},
        )
        self.assertEqual(results[0].attempt_id, results[1].attempt_id)
        self.assertEqual(results[0].session.session_id, results[1].session.session_id)  # type: ignore[union-attr]
        deliveries = [result.encrypted_delivery.decrypt() for result in results]  # type: ignore[union-attr]
        self.assertEqual(deliveries[0], deliveries[1])
        self.assertTrue(
            any(
                f"geno-session={raw_session}" in deliveries[0].cookie_headers[0]
                and f"geno-csrf={raw_csrf}" in deliveries[0].cookie_headers[1]
                for raw_session, raw_csrf in (rows[0][1], rows[1][1])
            )
        )
        self.assertEqual({result.replay_count for result in results}, {0, 1})
        self.assertTrue(all(row[2] == TransactionStatus.IDLE for row in rows))
        self.assertTrue(all(row[3] for row in rows))

        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT "
                    "(SELECT count(*) FROM auth_invitation_redemption_attempts "
                    " WHERE invitation_id = %s), "
                    "(SELECT count(*) FROM runtime_sessions WHERE actor_id = %s)",
                    (invitation_id, actor),
                )
                self.assertEqual(cursor.fetchone(), (1, 1))

    def test_05_disabled_switch_preserves_contraction_and_maps_valid_replay(self) -> None:
        expired_actor = f"expired-replay-{uuid4().hex}@example.test"
        expired_token = f"expired-replay-invitation-{uuid4().hex}"
        expired_idempotency = f"expired-replay-idempotency-{uuid4().hex}"
        expired_invitation = self._insert_pending_invitation(
            actor_id=expired_actor,
            role="reviewer",
            raw_invitation_token=expired_token,
        )
        with psycopg.connect() as connection:
            expired_success = self._redeem(
                connection,
                invitation_id=expired_invitation,
                raw_invitation_token=expired_token,
                raw_idempotency_key=expired_idempotency,
                requested_surface=SchemaV2InvitationSurface.ADMIN,
                delivery_expires_at=datetime.now(UTC) + timedelta(milliseconds=700),
            )
            self.assertEqual(expired_success.result_code, SchemaV2RedeemResultCode.SUCCEEDED)

        blocked_actor = f"blocked-replay-{uuid4().hex}@example.test"
        blocked_token = f"blocked-replay-invitation-{uuid4().hex}"
        blocked_idempotency = f"blocked-replay-idempotency-{uuid4().hex}"
        blocked_invitation = self._insert_pending_invitation(
            actor_id=blocked_actor,
            role="reviewer",
            raw_invitation_token=blocked_token,
        )
        with psycopg.connect() as connection:
            blocked_success = self._redeem(
                connection,
                invitation_id=blocked_invitation,
                raw_invitation_token=blocked_token,
                raw_idempotency_key=blocked_idempotency,
                requested_surface=SchemaV2InvitationSurface.ADMIN,
            )
            self.assertEqual(blocked_success.result_code, SchemaV2RedeemResultCode.SUCCEEDED)

        time.sleep(0.9)
        self._set_writes_enabled(False)
        try:
            with psycopg.connect() as contraction_connection:
                contracted = self._redeem(
                    contraction_connection,
                    invitation_id=expired_invitation,
                    raw_invitation_token=expired_token,
                    raw_idempotency_key=expired_idempotency,
                    requested_surface=SchemaV2InvitationSurface.ADMIN,
                )
                self.assertEqual(
                    contracted.result_code,
                    SchemaV2RedeemResultCode.RECOVERY_EXPIRED,
                )
                self.assertIsNone(contracted.encrypted_delivery)
                self.assertEqual(
                    contraction_connection.info.transaction_status,
                    TransactionStatus.IDLE,
                )

            with psycopg.connect() as blocked_connection:
                blocked_uow = SchemaV2AnonymousAuthUnitOfWork(blocked_connection)
                with self.assertRaises(SchemaV2AnonymousAuthCommandError) as blocked:
                    self._redeem(
                        blocked_connection,
                        invitation_id=blocked_invitation,
                        raw_invitation_token=blocked_token,
                        raw_idempotency_key=blocked_idempotency,
                        requested_surface=SchemaV2InvitationSurface.ADMIN,
                        unit_of_work=blocked_uow,
                    )
                self.assertEqual(blocked.exception.code, "auth_writes_temporarily_disabled")
                self.assertEqual(
                    blocked_connection.info.transaction_status,
                    TransactionStatus.IDLE,
                )
                self.assertTrue(blocked_uow.connection_reusable)
                self.assertEqual(blocked_uow.transaction_outcome, "rolled_back")
                self.assertEqual(blocked_uow.cleanup_telemetry.status, "succeeded")
        finally:
            self._set_writes_enabled(True)

        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT delivery_ciphertext, secret_erased_at FROM "
                    "auth_invitation_redemption_attempts WHERE id = %s",
                    (expired_success.attempt_id,),
                )
                ciphertext, erased_at = cursor.fetchone()
                self.assertIsNone(ciphertext)
                self.assertIsNotNone(erased_at)
                cursor.execute(
                    "SELECT replay_count, delivery_ciphertext IS NOT NULL FROM "
                    "auth_invitation_redemption_attempts WHERE id = %s",
                    (blocked_success.attempt_id,),
                )
                self.assertEqual(cursor.fetchone(), (0, True))

    def test_06_parser_error_rolls_back_and_reuses_the_physical_connection(self) -> None:
        actor = f"parser-error-{uuid4().hex}@example.test"
        raw_token = f"parser-error-invitation-{uuid4().hex}"
        invitation_id = self._insert_pending_invitation(
            actor_id=actor,
            role="reviewer",
            raw_invitation_token=raw_token,
        )
        source_hmac = hmac_source_identity(
            f"parser-error-source-{uuid4().hex}",
            server_key=build_source_identity_hmac_key(
                hashlib.sha256(f"parser-key-{uuid4()}".encode()).digest()
            ),
        )
        invitation_hash = hash_raw_invitation_token(raw_token)

        with psycopg.connect() as connection:
            failed_uow = SchemaV2AnonymousAuthUnitOfWork(connection)
            with patch(
                "geno_core.schema_v2.anonymous_auth_uow._parse_preflight_rows",
                side_effect=SchemaV2AnonymousAuthResultError(),
            ):
                with self.assertRaises(SchemaV2AnonymousAuthResultError):
                    failed_uow.preflight(
                        invitation_id=invitation_id,
                        invitation_token_hash=invitation_hash,
                        requested_surface=SchemaV2InvitationSurface.ADMIN,
                        source_fingerprint_hmac=source_hmac,
                    )
            self.assertEqual(failed_uow.transaction_outcome, "rolled_back")
            self.assertTrue(failed_uow.connection_reusable)
            self.assertEqual(failed_uow.cleanup_telemetry.status, "succeeded")
            self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)

            recovered = SchemaV2AnonymousAuthUnitOfWork(connection).preflight(
                invitation_id=invitation_id,
                invitation_token_hash=invitation_hash,
                requested_surface=SchemaV2InvitationSurface.ADMIN,
                source_fingerprint_hmac=source_hmac,
            )
            self.assertEqual(recovered.result_code, SchemaV2PreflightResultCode.COMPATIBLE)
            self.assertEqual(recovered.invitation_request_count, 1)
            self.assertEqual(recovered.source_request_count, 1)
            self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)

    def test_07_runtime_cannot_enumerate_sensitive_tables_after_cleanup(self) -> None:
        with psycopg.connect() as connection:
            for table in SENSITIVE_TABLES:
                with self.subTest(table=table):
                    with connection.cursor() as cursor:
                        cursor.execute("BEGIN")
                        cursor.execute("SET LOCAL ROLE geno_v2_runtime")
                        cursor.execute("SELECT set_config('app.session_token_hash', '', true)")
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                            cursor.execute(f"SELECT * FROM {table} LIMIT 1")
                    connection.rollback()
                    self.assertEqual(
                        connection.info.transaction_status,
                        TransactionStatus.IDLE,
                    )


if __name__ == "__main__":
    unittest.main()
