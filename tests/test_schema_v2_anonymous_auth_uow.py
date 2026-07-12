from __future__ import annotations

import dataclasses
import hashlib
import hmac
import inspect
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from geno_core.auth_delivery import AuthDeliveryError, AuthDeliveryKeyring
from geno_core.runtime import RuntimePostgresConnectionPool
from geno_core.schema_v2.anonymous_auth_uow import (
    SchemaV2AnonymousAuthCommitOutcomeUnknownError,
    SchemaV2AnonymousAuthCommandError,
    SchemaV2AnonymousAuthInputError,
    SchemaV2AnonymousAuthLifecycleError,
    SchemaV2AnonymousAuthResultError,
    SchemaV2AnonymousAuthRollbackError,
    SchemaV2AnonymousAuthUnitOfWork,
    SchemaV2AnonymousAuthUnitOfWorkError,
    SchemaV2EncryptedAuthDelivery,
    SchemaV2IdempotencyKeyHash,
    SchemaV2InvitationSurface,
    SchemaV2InvitationTokenHash,
    SchemaV2PreflightResultCode,
    SchemaV2RedeemResultCode,
    SchemaV2RedemptionMaterial,
    SchemaV2SourceIdentityHmac,
    SchemaV2SourceIdentityHmacKey,
    build_redemption_material,
    build_source_identity_hmac_key,
    hash_raw_idempotency_key,
    hash_raw_invitation_token,
    hmac_source_identity,
)
from geno_core.schema_v2.session_uow import (
    SchemaV2ApiSessionUnitOfWork,
    SchemaV2SessionTokenHash,
    hash_raw_session_token,
)


INVITATION_ID = UUID("11111111-1111-4111-8111-111111111111")
ATTEMPT_ID = UUID("22222222-2222-4222-8222-222222222222")
SESSION_ID = UUID("33333333-3333-4333-8333-333333333333")
TENANT_ID = UUID("44444444-4444-4444-8444-444444444444")
PROJECT_ID = UUID("55555555-5555-4555-8555-555555555555")
CORRELATION_ID = UUID("66666666-6666-4666-8666-666666666666")
OLD_ATTEMPT_ID = UUID("77777777-7777-4777-8777-777777777777")
OLD_SESSION_ID = UUID("88888888-8888-4888-8888-888888888888")
RAW_INVITATION_TOKEN = "raw-invitation-token-with-32-bytes"
RAW_IDEMPOTENCY_KEY = "opaque-idempotency-key"
RAW_SESSION_TOKEN = "raw-session-token-for-cookie"
RAW_CSRF_TOKEN = "raw-csrf-token-for-cookie"
RAW_SOURCE_IDENTITY = "203.0.113.41"
RAW_SOURCE_KEY = b"source-fingerprint-key-material!"
DELIVERY_KEY = b"d" * 32
NOW = datetime(2026, 7, 13, 2, 0, tzinfo=UTC)
DELIVERY_EXPIRY = NOW + timedelta(minutes=10)
SESSION_EXPIRY = NOW + timedelta(hours=8)


def project_scope() -> list[dict[str, object]]:
    return [
        {
            "project_id": str(PROJECT_ID),
            "roles": ["analyst"],
            "permissions": ["project.read"],
            "portal_capabilities": ["portal.admin.access"],
            "scope_sources": ["direct_member"],
        }
    ]


def compatible_preflight_row() -> tuple[object, ...]:
    return (
        "compatible",
        "compatible",
        "admin",
        "admin",
        "analyst",
        "auth_surface_policy_v1",
        1,
        1,
        None,
        CORRELATION_ID,
    )


def successful_redeem_row(
    encrypted_delivery: SchemaV2EncryptedAuthDelivery,
    *,
    result_code: str = "succeeded",
    attempt_id: UUID = ATTEMPT_ID,
    session_id: UUID = SESSION_ID,
    replay_count: int = 0,
) -> tuple[object, ...]:
    return (
        result_code,
        attempt_id,
        session_id,
        "owner@example.test",
        TENANT_ID,
        [str(PROJECT_ID)],
        [],
        project_scope(),
        encrypted_delivery._ciphertext,
        encrypted_delivery._key_id,
        encrypted_delivery._nonce,
        DELIVERY_EXPIRY,
        replay_count,
        None,
        CORRELATION_ID,
    )


def resolved_session_row() -> tuple[object, ...]:
    return (
        SESSION_ID,
        "owner@example.test",
        TENANT_ID,
        [str(PROJECT_ID)],
        [],
        project_scope(),
    )


class NamedTransactionStatus:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeDatabaseError(RuntimeError):
    def __init__(self, sqlstate: str, primary_message: str) -> None:
        super().__init__(f"secret database detail {RAW_INVITATION_TOKEN}")
        self.sqlstate = sqlstate
        self.diag = SimpleNamespace(message_primary=primary_message)


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        return None

    def execute(self, statement: str, params: tuple[object, ...] = ()) -> None:
        normalized = " ".join(statement.split())
        if self.connection.info.transaction_status.name == "IDLE":
            self.connection.info.transaction_status.name = "INTRANS"
        self.connection.calls.append((normalized, params))
        self.connection.events.append(f"SQL:{normalized}")
        if self.connection.fail_reset and normalized == "RESET ALL":
            raise RuntimeError(f"reset error containing {RAW_INVITATION_TOKEN}")
        if self.connection.fail_on_sql and self.connection.fail_on_sql in normalized:
            if self.connection.database_error is not None:
                raise self.connection.database_error
            raise RuntimeError(
                f"database error containing {RAW_INVITATION_TOKEN} {RAW_SESSION_TOKEN}"
            )

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.connection.rows)


class FakeConnection:
    def __init__(
        self,
        rows: list[tuple[object, ...]],
        *,
        fail_on_sql: str | None = None,
        fail_commit_calls: set[int] | None = None,
        fail_rollback: bool = False,
        fail_reset: bool = False,
        database_error: BaseException | None = None,
        autocommit: bool = False,
        status: str = "IDLE",
    ) -> None:
        self.rows = rows
        self.fail_on_sql = fail_on_sql
        self.fail_commit_calls = fail_commit_calls or set()
        self.fail_rollback = fail_rollback
        self.fail_reset = fail_reset
        self.database_error = database_error
        self.autocommit = autocommit
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.events: list[str] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
        self.info = SimpleNamespace(transaction_status=NamedTransactionStatus(status))

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commit_count += 1
        self.events.append("COMMIT")
        if self.commit_count in self.fail_commit_calls:
            self.info.transaction_status.name = "UNKNOWN"
            raise RuntimeError(f"commit failed {RAW_INVITATION_TOKEN}")
        self.info.transaction_status.name = "IDLE"

    def rollback(self) -> None:
        self.rollback_count += 1
        self.events.append("ROLLBACK")
        if self.fail_rollback:
            self.info.transaction_status.name = "UNKNOWN"
            raise RuntimeError(f"rollback failed {RAW_INVITATION_TOKEN}")
        self.info.transaction_status.name = "IDLE"

    def close(self) -> None:
        self.close_count += 1
        self.events.append("CLOSE")


class SchemaV2AnonymousAuthUnitOfWorkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.invitation_hash = hash_raw_invitation_token(RAW_INVITATION_TOKEN)
        self.idempotency_hash = hash_raw_idempotency_key(RAW_IDEMPOTENCY_KEY)
        self.session_hash = hash_raw_session_token(RAW_SESSION_TOKEN)
        self.delivery_keyring = AuthDeliveryKeyring(
            active_key_id="delivery-key-v1",
            keys={"delivery-key-v1": DELIVERY_KEY},
        )
        self.redemption_material = build_redemption_material(
            RAW_SESSION_TOKEN,
            RAW_CSRF_TOKEN,
            session_cookie_name="geno-session",
            csrf_cookie_name="geno-csrf",
            session_expires_at=SESSION_EXPIRY,
            secure=True,
            attempt_id=ATTEMPT_ID,
            keyring=self.delivery_keyring,
        )
        self.old_redemption_material = build_redemption_material(
            "old-raw-session-token-for-cookie",
            "old-raw-csrf-token-for-cookie",
            session_cookie_name="geno-session",
            csrf_cookie_name="geno-csrf",
            session_expires_at=SESSION_EXPIRY,
            secure=True,
            attempt_id=OLD_ATTEMPT_ID,
            keyring=self.delivery_keyring,
        )
        self.source_key = build_source_identity_hmac_key(RAW_SOURCE_KEY)
        self.source_hmac = hmac_source_identity(
            RAW_SOURCE_IDENTITY,
            server_key=self.source_key,
        )

    def _preflight(
        self,
        connection: FakeConnection,
    ):
        return SchemaV2AnonymousAuthUnitOfWork(connection).preflight(
            invitation_id=INVITATION_ID,
            invitation_token_hash=self.invitation_hash,
            requested_surface=SchemaV2InvitationSurface.ADMIN,
            source_fingerprint_hmac=self.source_hmac,
        )

    def _redeem(
        self,
        connection: FakeConnection,
        *,
        unit_of_work: SchemaV2AnonymousAuthUnitOfWork | None = None,
        redemption_material: SchemaV2RedemptionMaterial | None = None,
    ):
        active_uow = unit_of_work or SchemaV2AnonymousAuthUnitOfWork(connection)
        return active_uow.redeem(
            attempt_id=ATTEMPT_ID,
            session_id=SESSION_ID,
            invitation_id=INVITATION_ID,
            invitation_token_hash=self.invitation_hash,
            requested_surface=SchemaV2InvitationSurface.ADMIN,
            idempotency_key_hash=self.idempotency_hash,
            redemption_material=redemption_material or self.redemption_material,
            delivery_expires_at=DELIVERY_EXPIRY,
        )

    def test_factories_are_typed_frozen_bounded_and_redacted(self) -> None:
        invitation_digest = hashlib.sha256(RAW_INVITATION_TOKEN.encode()).hexdigest()
        idempotency_digest = hashlib.sha256(RAW_IDEMPOTENCY_KEY.encode()).hexdigest()
        source_digest = hmac.new(
            RAW_SOURCE_KEY,
            RAW_SOURCE_IDENTITY.encode(),
            hashlib.sha256,
        ).hexdigest()

        for value, raw, digest in (
            (self.invitation_hash, RAW_INVITATION_TOKEN, invitation_digest),
            (self.idempotency_hash, RAW_IDEMPOTENCY_KEY, idempotency_digest),
            (self.source_hmac, RAW_SOURCE_IDENTITY, source_digest),
            (self.source_key, RAW_SOURCE_KEY.decode(), RAW_SOURCE_KEY.hex()),
            (self.redemption_material, RAW_SESSION_TOKEN, RAW_CSRF_TOKEN),
            (
                self.redemption_material._encrypted_delivery,
                RAW_SESSION_TOKEN,
                RAW_CSRF_TOKEN,
            ),
        ):
            with self.subTest(value_type=type(value).__name__):
                self.assertNotIn(raw, repr(value))
                self.assertNotIn(digest, repr(value))
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    value._value = b"changed"  # type: ignore[misc]

        self.assertIs(type(self.invitation_hash), SchemaV2InvitationTokenHash)
        self.assertIs(type(self.idempotency_hash), SchemaV2IdempotencyKeyHash)
        self.assertIs(type(self.source_hmac), SchemaV2SourceIdentityHmac)
        self.assertIs(type(self.source_key), SchemaV2SourceIdentityHmacKey)
        self.assertIs(type(self.redemption_material), SchemaV2RedemptionMaterial)
        self.assertIs(
            type(self.redemption_material._encrypted_delivery),
            SchemaV2EncryptedAuthDelivery,
        )
        self.assertIs(type(self.session_hash), SchemaV2SessionTokenHash)
        self.assertEqual(
            self.redemption_material._session_token_hash,
            self.session_hash,
        )
        decrypted = self.redemption_material._encrypted_delivery.decrypt()
        self.assertEqual(decrypted.absolute_session_expires_at, SESSION_EXPIRY)
        self.assertIn(f"geno-session={RAW_SESSION_TOKEN}", decrypted.cookie_headers[0])
        self.assertIn(f"geno-csrf={RAW_CSRF_TOKEN}", decrypted.cookie_headers[1])

        invalid_factories = (
            lambda: hash_raw_invitation_token(""),
            lambda: hash_raw_invitation_token("x" * 31),
            lambda: hash_raw_invitation_token("x" * 513),
            lambda: hash_raw_idempotency_key("short"),
            lambda: build_source_identity_hmac_key(b"too-short"),
            lambda: hmac_source_identity(" source", server_key=self.source_key),
            lambda: SchemaV2InvitationTokenHash(invitation_digest),
            lambda: SchemaV2RedemptionMaterial(
                session_token_hash=self.session_hash,
                encrypted_delivery=self.redemption_material._encrypted_delivery,
                session_expires_at=SESSION_EXPIRY,
            ),
            lambda: build_redemption_material(
                "",
                RAW_CSRF_TOKEN,
                session_cookie_name="geno-session",
                csrf_cookie_name="geno-csrf",
                session_expires_at=SESSION_EXPIRY,
                secure=True,
                attempt_id=ATTEMPT_ID,
                keyring=self.delivery_keyring,
            ),
        )
        for factory in invalid_factories:
            with self.subTest(factory=repr(factory)):
                with self.assertRaises(SchemaV2AnonymousAuthInputError) as raised:
                    factory()
                for secret in (
                    RAW_INVITATION_TOKEN,
                    RAW_IDEMPOTENCY_KEY,
                    RAW_SOURCE_IDENTITY,
                    RAW_SOURCE_KEY.decode(),
                ):
                    self.assertNotIn(secret, str(raised.exception))

    def test_redemption_material_binds_token_hash_cookie_expiry_and_attempt_aad(self) -> None:
        encrypted = self.redemption_material._encrypted_delivery
        self.assertEqual(
            self.redemption_material._session_token_hash,
            hash_raw_session_token(RAW_SESSION_TOKEN),
        )
        self.assertEqual(self.redemption_material._session_expires_at, SESSION_EXPIRY)
        delivery = encrypted.decrypt()
        self.assertEqual(delivery.absolute_session_expires_at, SESSION_EXPIRY)
        self.assertIn(f"geno-session={RAW_SESSION_TOKEN}", delivery.cookie_headers[0])
        with self.assertRaises(AuthDeliveryError):
            self.delivery_keyring.decrypt(
                ciphertext=encrypted._ciphertext,
                key_id=encrypted._key_id,
                nonce=encrypted._nonce,
                attempt_id=str(OLD_ATTEMPT_ID),
            )

        connection = FakeConnection(
            [successful_redeem_row(self.old_redemption_material._encrypted_delivery)]
        )
        with self.assertRaises(SchemaV2AnonymousAuthInputError):
            self._redeem(
                connection,
                redemption_material=self.old_redemption_material,
            )
        self.assertEqual(connection.calls, [])

    def test_preflight_uses_only_exact_function_and_cleans_transaction(self) -> None:
        connection = FakeConnection([compatible_preflight_row()])
        uow = SchemaV2AnonymousAuthUnitOfWork(connection)
        result = uow.preflight(
            invitation_id=INVITATION_ID,
            invitation_token_hash=self.invitation_hash,
            requested_surface=SchemaV2InvitationSurface.ADMIN,
            source_fingerprint_hmac=self.source_hmac,
        )

        self.assertEqual(result.result_code, SchemaV2PreflightResultCode.COMPATIBLE)
        self.assertEqual(result.recommended_surface, SchemaV2InvitationSurface.ADMIN)
        self.assertEqual(result.invitation_role, "analyst")
        self.assertEqual(result.correlation_id, CORRELATION_ID)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.invitation_role = "reviewer"  # type: ignore[misc]
        self.assertEqual(
            connection.events,
            [
                "SQL:BEGIN",
                "SQL:SET LOCAL ROLE geno_v2_runtime",
                "SQL:SELECT set_config('app.session_token_hash', '', true)",
                "SQL:SELECT result_code, compatibility, requested_surface, "
                "recommended_surface, invitation_role, policy_version, "
                "invitation_request_count, source_request_count, retry_after_seconds, "
                "correlation_id FROM public.geno_v2_preflight_auth_invitation(%s, %s, %s, %s)",
                "COMMIT",
                "SQL:RESET ALL",
                "SQL:RESET ROLE",
                "COMMIT",
            ],
        )
        call_params = connection.calls[3][1]
        self.assertEqual(call_params[0], INVITATION_ID)
        self.assertEqual(call_params[1], hashlib.sha256(RAW_INVITATION_TOKEN.encode()).hexdigest())
        self.assertEqual(call_params[2], "admin")
        self.assertEqual(
            call_params[3],
            hmac.new(RAW_SOURCE_KEY, RAW_SOURCE_IDENTITY.encode(), hashlib.sha256).hexdigest(),
        )
        sql = "\n".join(statement for statement, _params in connection.calls)
        self.assertEqual(sql.count("geno_v2_preflight_auth_invitation"), 1)
        for forbidden in (
            "geno_v2_resolve_session_context",
            "runtime_sessions",
            "app.actor_id",
            "app.tenant_id",
            "app.project_id",
            "app.roles",
            "app.invitation_token_hash",
        ):
            self.assertNotIn(forbidden, sql)
        self.assertFalse(hasattr(uow, "cursor"))
        self.assertEqual(uow.transaction_outcome, "committed")
        self.assertTrue(uow.connection_reusable)
        self.assertEqual(uow.cleanup_telemetry.status, "succeeded")
        self.assertEqual(connection.info.transaction_status.name, "IDLE")

    def test_preflight_result_branches_are_strict_and_fail_closed(self) -> None:
        rows = (
            (
                "surface_mismatch",
                "surface_mismatch",
                "admin",
                "customer",
                "client_viewer",
                "auth_surface_policy_v1",
                1,
                1,
                None,
                CORRELATION_ID,
            ),
            (
                "policy_stale",
                "policy_stale",
                "admin",
                None,
                None,
                None,
                2,
                2,
                None,
                CORRELATION_ID,
            ),
            (
                "invalid",
                "invalid",
                "admin",
                None,
                None,
                None,
                3,
                3,
                None,
                CORRELATION_ID,
            ),
            (
                "rate_limited",
                "invalid",
                "admin",
                None,
                None,
                None,
                4,
                4,
                60,
                CORRELATION_ID,
            ),
        )
        for row in rows:
            with self.subTest(result_code=row[0]):
                result = self._preflight(FakeConnection([row]))
                self.assertEqual(result.result_code.value, row[0])

        malformed_rows = (
            [],
            [compatible_preflight_row(), compatible_preflight_row()],
            [compatible_preflight_row()[:-1]],
            [{**dict(enumerate(compatible_preflight_row())), 3: None}],
            [(*compatible_preflight_row()[:6], 0, *compatible_preflight_row()[7:])],
        )
        for rows_value in malformed_rows:
            with self.subTest(rows=repr(rows_value)[:80]):
                connection = FakeConnection(rows_value)  # type: ignore[arg-type]
                with self.assertRaises(SchemaV2AnonymousAuthResultError):
                    self._preflight(connection)
                self.assertEqual(connection.rollback_count, 1)
                self.assertEqual(connection.commit_count, 1)
                self.assertEqual(connection.info.transaction_status.name, "IDLE")

    def test_redeem_uses_exact_function_and_redacts_delivery_result(self) -> None:
        input_delivery = self.redemption_material._encrypted_delivery
        connection = FakeConnection([successful_redeem_row(input_delivery)])
        uow = SchemaV2AnonymousAuthUnitOfWork(connection)
        result = self._redeem(connection, unit_of_work=uow)

        self.assertEqual(result.result_code, SchemaV2RedeemResultCode.SUCCEEDED)
        self.assertEqual(result.attempt_id, ATTEMPT_ID)
        self.assertIsNotNone(result.session)
        self.assertEqual(result.session.session_id, SESSION_ID)  # type: ignore[union-attr]
        self.assertEqual(result.session.project_ids, (PROJECT_ID,))  # type: ignore[union-attr]
        self.assertIsNotNone(result.encrypted_delivery)
        decrypted = result.encrypted_delivery.decrypt()  # type: ignore[union-attr]
        self.assertIn(f"geno-session={RAW_SESSION_TOKEN}", decrypted.cookie_headers[0])
        self.assertNotIn(RAW_SESSION_TOKEN, repr(result))
        self.assertNotIn(RAW_CSRF_TOKEN, repr(result))

        statement, params = connection.calls[3]
        self.assertIn("FROM public.geno_v2_redeem_auth_invitation(", statement)
        self.assertEqual(
            sum(
                "geno_v2_redeem_auth_invitation" in call_statement
                for call_statement, _params in connection.calls
            ),
            1,
        )
        self.assertEqual(len(params), 12)
        self.assertEqual(params[:3], (ATTEMPT_ID, SESSION_ID, INVITATION_ID))
        self.assertEqual(params[6], hashlib.sha256(RAW_SESSION_TOKEN.encode()).hexdigest())
        self.assertEqual(params[7], SESSION_EXPIRY)
        self.assertEqual(params[8], input_delivery._ciphertext)
        self.assertEqual(params[10], input_delivery._nonce)
        self.assertNotIn(RAW_INVITATION_TOKEN, repr(params))
        self.assertNotIn(RAW_IDEMPOTENCY_KEY, repr(params))
        self.assertNotIn(RAW_SESSION_TOKEN, repr(params))
        self.assertEqual(uow.transaction_outcome, "committed")
        self.assertEqual(connection.info.transaction_status.name, "IDLE")

    def test_redeem_replay_and_failure_rows_enforce_column_coherence(self) -> None:
        input_delivery = self.redemption_material._encrypted_delivery
        replay = successful_redeem_row(
            self.old_redemption_material._encrypted_delivery,
            result_code="replayed",
            attempt_id=OLD_ATTEMPT_ID,
            session_id=OLD_SESSION_ID,
            replay_count=2,
        )
        replayed = self._redeem(FakeConnection([replay]))
        self.assertEqual(replayed.result_code, SchemaV2RedeemResultCode.REPLAYED)
        self.assertEqual(replayed.attempt_id, OLD_ATTEMPT_ID)
        self.assertEqual(replayed.session.session_id, OLD_SESSION_ID)  # type: ignore[union-attr]

        surface_mismatch = (
            "surface_mismatch",
            *(None for _ in range(12)),
            "customer",
            CORRELATION_ID,
        )
        invalid = ("invalid", *(None for _ in range(13)), CORRELATION_ID)
        terminal_empty = (
            "recovery_expired",
            *(None for _ in range(13)),
            CORRELATION_ID,
        )
        session_unavailable = (
            "session_unavailable",
            *(None for _ in range(13)),
            CORRELATION_ID,
        )
        replay_limit = (
            "replay_limit_exceeded",
            *(None for _ in range(13)),
            CORRELATION_ID,
        )
        for row in (
            surface_mismatch,
            invalid,
            terminal_empty,
            replay_limit,
            session_unavailable,
        ):
            with self.subTest(result_code=row[0]):
                result = self._redeem(FakeConnection([row]))
                self.assertEqual(result.result_code.value, row[0])
                self.assertIsNone(result.encrypted_delivery)

        malformed = list(successful_redeem_row(input_delivery))
        malformed[10] = b"bad"
        malformed_replay = list(replay)
        malformed_replay[12] = 4
        wrong_aad_replay = list(replay)
        wrong_aad_replay[8] = input_delivery._ciphertext
        wrong_aad_replay[9] = input_delivery._key_id
        wrong_aad_replay[10] = input_delivery._nonce
        leaked_failure = list(invalid)
        leaked_failure[8] = input_delivery._ciphertext
        leaked_identity = list(session_unavailable)
        leaked_identity[1] = OLD_ATTEMPT_ID
        for row in (
            tuple(malformed),
            tuple(malformed_replay),
            tuple(wrong_aad_replay),
            tuple(leaked_failure),
            tuple(leaked_identity),
        ):
            with self.subTest(row=repr(row)[:80]):
                connection = FakeConnection([row])
                with self.assertRaises(SchemaV2AnonymousAuthResultError):
                    self._redeem(connection)
                self.assertEqual(connection.rollback_count, 1)
                self.assertEqual(connection.info.transaction_status.name, "IDLE")

    def test_database_commit_rollback_and_cleanup_failures_are_redacted(self) -> None:
        database_failure = FakeConnection(
            [compatible_preflight_row()],
            fail_on_sql="geno_v2_preflight_auth_invitation",
        )
        with self.assertRaises(SchemaV2AnonymousAuthUnitOfWorkError) as raised:
            self._preflight(database_failure)
        self.assertEqual(raised.exception.code, "anonymous_auth_transaction_failed")
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertNotIn(RAW_INVITATION_TOKEN, str(raised.exception))
        self.assertEqual(database_failure.rollback_count, 1)
        self.assertEqual(database_failure.commit_count, 1)

        malformed_result = list(compatible_preflight_row())
        malformed_result[3] = None
        rollback_failure = FakeConnection([tuple(malformed_result)], fail_rollback=True)
        with self.assertRaises(SchemaV2AnonymousAuthRollbackError) as raised:
            self._preflight(rollback_failure)
        self.assertEqual(raised.exception.transaction_outcome, "unknown")
        self.assertTrue(raised.exception.requires_idempotency_recovery)
        self.assertEqual(rollback_failure.close_count, 1)
        self.assertEqual(rollback_failure.commit_count, 0)
        self.assertFalse(
            any(
                event.startswith("SQL:RESET") or event == "COMMIT"
                for event in rollback_failure.events
            )
        )

        commit_failure = FakeConnection(
            [successful_redeem_row(self.redemption_material._encrypted_delivery)],
            fail_commit_calls={1},
        )
        uow = SchemaV2AnonymousAuthUnitOfWork(commit_failure)
        with self.assertRaises(SchemaV2AnonymousAuthCommitOutcomeUnknownError) as raised:
            uow.redeem(
                attempt_id=ATTEMPT_ID,
                session_id=SESSION_ID,
                invitation_id=INVITATION_ID,
                invitation_token_hash=self.invitation_hash,
                requested_surface=SchemaV2InvitationSurface.ADMIN,
                idempotency_key_hash=self.idempotency_hash,
                redemption_material=self.redemption_material,
                delivery_expires_at=DELIVERY_EXPIRY,
            )
        self.assertTrue(raised.exception.requires_idempotency_recovery)
        self.assertEqual(uow.transaction_outcome, "unknown")
        self.assertFalse(uow.connection_reusable)
        self.assertEqual(commit_failure.close_count, 1)

        unconfirmed_commit = FakeConnection(
            [successful_redeem_row(self.redemption_material._encrypted_delivery)],
            fail_commit_calls={1},
            fail_rollback=True,
        )
        with self.assertRaises(SchemaV2AnonymousAuthCommitOutcomeUnknownError):
            self._redeem(unconfirmed_commit)
        self.assertEqual(unconfirmed_commit.commit_count, 1)
        self.assertEqual(unconfirmed_commit.close_count, 1)
        self.assertFalse(any(event.startswith("SQL:RESET") for event in unconfirmed_commit.events))

        cleanup_failure = FakeConnection(
            [compatible_preflight_row()],
            fail_reset=True,
        )
        cleanup_uow = SchemaV2AnonymousAuthUnitOfWork(cleanup_failure)
        cleanup_uow.preflight(
            invitation_id=INVITATION_ID,
            invitation_token_hash=self.invitation_hash,
            requested_surface=SchemaV2InvitationSurface.ADMIN,
            source_fingerprint_hmac=self.source_hmac,
        )
        self.assertFalse(cleanup_uow.connection_reusable)
        self.assertTrue(cleanup_uow.cleanup_telemetry.connection_discarded)
        self.assertEqual(cleanup_failure.close_count, 1)

    def test_database_command_errors_require_exact_sqlstate_and_primary_message(self) -> None:
        stable_errors = {
            "42501": "auth_writes_temporarily_disabled",
            "GA001": "auth_command_invalid_argument",
            "GA003": "auth_command_not_authorized",
            "GA004": "auth_command_idempotency_conflict",
            "GA005": "auth_command_state_conflict",
            "GA006": "auth_command_invariant_violation",
        }
        for sqlstate, primary_message in stable_errors.items():
            with self.subTest(sqlstate=sqlstate):
                connection = FakeConnection(
                    [compatible_preflight_row()],
                    fail_on_sql="geno_v2_preflight_auth_invitation",
                    database_error=FakeDatabaseError(sqlstate, primary_message),
                )
                with self.assertRaises(SchemaV2AnonymousAuthCommandError) as raised:
                    self._preflight(connection)
                self.assertEqual(raised.exception.code, primary_message)
                self.assertNotIn(RAW_INVITATION_TOKEN, str(raised.exception))
                self.assertTrue(raised.exception.__suppress_context__)

        for error in (
            FakeDatabaseError("GA001", "wrong_message"),
            FakeDatabaseError("XX000", "auth_command_invalid_argument"),
        ):
            connection = FakeConnection(
                [compatible_preflight_row()],
                fail_on_sql="geno_v2_preflight_auth_invitation",
                database_error=error,
            )
            with self.assertRaises(SchemaV2AnonymousAuthUnitOfWorkError) as raised:
                self._preflight(connection)
            self.assertNotIsInstance(raised.exception, SchemaV2AnonymousAuthCommandError)
            self.assertEqual(raised.exception.code, "anonymous_auth_transaction_failed")

    def test_session_and_anonymous_uows_share_connection_reservation(self) -> None:
        connection = FakeConnection([resolved_session_row()])
        session_uow = SchemaV2ApiSessionUnitOfWork(
            connection,
            session_token_hash=self.session_hash,
        )
        session_uow.__enter__()
        calls_before_anonymous = list(connection.calls)
        try:
            anonymous_uow = SchemaV2AnonymousAuthUnitOfWork(connection)
            with self.assertRaises(SchemaV2AnonymousAuthLifecycleError):
                anonymous_uow.preflight(
                    invitation_id=INVITATION_ID,
                    invitation_token_hash=self.invitation_hash,
                    requested_surface=SchemaV2InvitationSurface.ADMIN,
                    source_fingerprint_hmac=self.source_hmac,
                )
            self.assertEqual(connection.calls, calls_before_anonymous)
        finally:
            session_uow.__exit__(None, None, None)
        self.assertEqual(connection.info.transaction_status.name, "IDLE")

    def test_pooled_cleanup_failure_invalidates_instead_of_returning_connection(self) -> None:
        connections: list[FakeConnection] = []

        def connector(_database_url: str) -> FakeConnection:
            connection = FakeConnection(
                [compatible_preflight_row()],
                fail_reset=not connections,
            )
            connections.append(connection)
            return connection

        pool = RuntimePostgresConnectionPool(
            database_url="configured",
            connector=connector,
            max_size=1,
            timeout_seconds=0,
        )
        borrowed = pool.acquire()
        uow = SchemaV2AnonymousAuthUnitOfWork(borrowed)  # type: ignore[arg-type]
        uow.preflight(
            invitation_id=INVITATION_ID,
            invitation_token_hash=self.invitation_hash,
            requested_surface=SchemaV2InvitationSurface.ADMIN,
            source_fingerprint_hmac=self.source_hmac,
        )
        self.assertFalse(uow.connection_reusable)
        self.assertTrue(uow.cleanup_telemetry.connection_discarded)
        self.assertEqual(connections[0].close_count, 1)

        replacement = pool.acquire()
        self.assertEqual(len(connections), 2)
        replacement.invalidate()

    def test_input_lifecycle_and_public_surface_do_not_open_arbitrary_sql(self) -> None:
        self.assertEqual(
            set(inspect.signature(SchemaV2AnonymousAuthUnitOfWork).parameters),
            {"connection"},
        )
        public_methods = {
            name
            for name, value in inspect.getmembers(
                SchemaV2AnonymousAuthUnitOfWork,
                predicate=inspect.isfunction,
            )
            if not name.startswith("_")
        }
        self.assertEqual(public_methods, {"preflight", "redeem"})

        autocommit = FakeConnection([compatible_preflight_row()], autocommit=True)
        with self.assertRaises(SchemaV2AnonymousAuthLifecycleError):
            SchemaV2AnonymousAuthUnitOfWork(autocommit)
        self.assertEqual(autocommit.calls, [])

        nonidle = FakeConnection([compatible_preflight_row()], status="INTRANS")
        with self.assertRaises(SchemaV2AnonymousAuthLifecycleError):
            self._preflight(nonidle)
        self.assertEqual(nonidle.calls, [])

        connection = FakeConnection([compatible_preflight_row()])
        uow = SchemaV2AnonymousAuthUnitOfWork(connection)
        uow.preflight(
            invitation_id=INVITATION_ID,
            invitation_token_hash=self.invitation_hash,
            requested_surface=SchemaV2InvitationSurface.ADMIN,
            source_fingerprint_hmac=self.source_hmac,
        )
        with self.assertRaises(SchemaV2AnonymousAuthLifecycleError):
            uow.preflight(
                invitation_id=INVITATION_ID,
                invitation_token_hash=self.invitation_hash,
                requested_surface=SchemaV2InvitationSurface.ADMIN,
                source_fingerprint_hmac=self.source_hmac,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
