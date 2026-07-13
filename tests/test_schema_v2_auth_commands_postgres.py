from __future__ import annotations

import hashlib
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb


BEHAVIOR_TEST_ENABLED = os.getenv("SCHEMA_V2_BEHAVIOR_TEST") == "1"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@unittest.skipUnless(BEHAVIOR_TEST_ENABLED, "SCHEMA_V2_BEHAVIOR_TEST=1 is required")
class SchemaV2AuthCommandsPostgresTest(unittest.TestCase):
    tenant_id: UUID
    project_ids: tuple[UUID, UUID, UUID]
    admin_actor: str
    admin_session_hash: str
    analyst_session_hash: str

    @classmethod
    def setUpClass(cls) -> None:
        marker = uuid4().hex
        cls.tenant_id = uuid4()
        cls.project_ids = tuple(sorted((uuid4(), uuid4(), uuid4()), key=str))
        cls.admin_actor = f"auth-command-owner-{marker}@example.test"
        cls.admin_session_hash = _digest(f"auth-command-admin-session-{marker}")
        cls.analyst_session_hash = _digest(f"auth-command-analyst-session-{marker}")
        market_code = f"AUTH-{marker}"
        industry_code = f"auth_{marker}"

        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO market_profiles (market_code, payload) VALUES (%s, %s)",
                    (market_code, Jsonb({"fixture": "auth-commands"})),
                )
                cursor.execute(
                    "INSERT INTO industry_profiles "
                    "(market_code, industry_code, payload) VALUES (%s, %s, %s)",
                    (market_code, industry_code, Jsonb({"fixture": "auth-commands"})),
                )
                cursor.execute(
                    "INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)",
                    (cls.tenant_id, f"Auth Commands {marker}", f"auth-commands-{marker}"),
                )
                for project_id in cls.project_ids:
                    cursor.execute(
                        "INSERT INTO projects ("
                        "id, tenant_id, name, market_code, industry_code, target_brand, "
                        "category, prompt_version, status) VALUES ("
                        "%s, %s, %s, %s, %s, 'Auth Brand', 'Auth', 'v1', 'active')",
                        (
                            project_id,
                            cls.tenant_id,
                            f"Auth Project {project_id}",
                            market_code,
                            industry_code,
                        ),
                    )
                    cursor.execute(
                        "INSERT INTO project_members "
                        "(tenant_id, project_id, user_id, role, invited_by) "
                        "VALUES (%s, %s, %s, 'project_owner', 'auth-command-fixture')",
                        (cls.tenant_id, project_id, cls.admin_actor),
                    )

                cls._insert_session_lineage(
                    cursor,
                    actor_id=cls.admin_actor,
                    invitation_project_id=cls.project_ids[0],
                    invitation_role="project_owner",
                    session_hash=cls.admin_session_hash,
                    marker=f"admin-{marker}",
                )

                analyst_actor = f"auth-command-analyst-{marker}@example.test"
                cursor.execute(
                    "INSERT INTO project_members "
                    "(tenant_id, project_id, user_id, role, invited_by) "
                    "VALUES (%s, %s, %s, 'analyst', 'auth-command-fixture')",
                    (cls.tenant_id, cls.project_ids[0], analyst_actor),
                )
                cls._insert_session_lineage(
                    cursor,
                    actor_id=analyst_actor,
                    invitation_project_id=cls.project_ids[0],
                    invitation_role="analyst",
                    session_hash=cls.analyst_session_hash,
                    marker=f"analyst-{marker}",
                )

    @classmethod
    def _insert_session_lineage(
        cls,
        cursor: psycopg.Cursor[object],
        *,
        actor_id: str,
        invitation_project_id: UUID,
        invitation_role: str,
        session_hash: str,
        marker: str,
    ) -> tuple[UUID, UUID]:
        invitation_id = uuid4()
        attempt_id = uuid4()
        session_id = uuid4()
        surface = "customer" if invitation_role == "client_viewer" else "admin"
        invite_hash = _digest(f"fixture-invite-{marker}")
        idempotency_hash = _digest(f"fixture-idempotency-{marker}")
        now = datetime.now(UTC)
        created_at = now - timedelta(seconds=2)
        issued_at = now
        delivery_expires_at = now + timedelta(minutes=30)

        cursor.execute(
            "INSERT INTO project_member_invitations ("
            "id, tenant_id, project_id, email, role, invite_token_hash, audience, "
            "allowed_surfaces, invited_by, expires_at, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, ARRAY[%s]::text[], "
            "'auth-command-fixture', %s, %s, %s)",
            (
                invitation_id,
                cls.tenant_id,
                invitation_project_id,
                actor_id,
                invitation_role,
                invite_hash,
                surface,
                surface,
                now + timedelta(days=1),
                created_at,
                created_at,
            ),
        )
        cursor.execute(
            "SELECT geno_v2_auth_redeem_request_hash(%s, %s, %s)",
            (invitation_id, invite_hash, surface),
        )
        request_hash = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO auth_invitation_redemption_attempts ("
            "id, tenant_id, project_id, invitation_id, requested_surface, "
            "idempotency_key_hash, request_hash, token_fingerprint, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                attempt_id,
                cls.tenant_id,
                invitation_project_id,
                invitation_id,
                surface,
                idempotency_hash,
                request_hash,
                invite_hash,
                now - timedelta(seconds=1),
                now - timedelta(seconds=1),
            ),
        )
        cursor.execute(
            "SELECT project_ids, tenant_roles, project_scopes, flat_roles, "
            "flat_permissions FROM geno_v2_build_locked_auth_scope(%s, %s)",
            (cls.tenant_id, actor_id),
        )
        project_ids, tenant_roles, project_scopes, roles, permissions = cursor.fetchone()
        cursor.execute(
            "INSERT INTO runtime_sessions ("
            "id, session_token_hash, actor_id, tenant_id, project_ids, roles, "
            "permissions, tenant_roles, project_scopes, redemption_attempt_id, "
            "issued_by, issued_at, expires_at, created_at, updated_at) VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "'auth-command-fixture', %s, %s, %s, %s)",
            (
                session_id,
                session_hash,
                actor_id,
                cls.tenant_id,
                Jsonb(project_ids),
                Jsonb(roles),
                Jsonb(permissions),
                Jsonb(tenant_roles),
                Jsonb(project_scopes),
                attempt_id,
                issued_at,
                now + timedelta(days=1),
                issued_at,
                issued_at,
            ),
        )
        cursor.execute(
            "UPDATE auth_invitation_redemption_attempts SET "
            "session_id = %s, status = 'succeeded', delivery_ciphertext = %s, "
            "delivery_key_id = 'fixture-key-v1', delivery_nonce = %s, "
            "delivery_expires_at = %s, updated_at = clock_timestamp() WHERE id = %s",
            (
                session_id,
                b"fixture-encrypted-session",
                b"0123456789ab",
                delivery_expires_at,
                attempt_id,
            ),
        )
        cursor.execute(
            "UPDATE project_member_invitations SET status = 'accepted', "
            "accepted_by_attempt_id = %s, accepted_at = %s, "
            "updated_at = clock_timestamp() WHERE id = %s",
            (attempt_id, now, invitation_id),
        )
        return session_id, attempt_id

    @staticmethod
    def _runtime_call(
        statement: str,
        parameters: tuple[object, ...] = (),
        *,
        session_hash: str = "",
        application_name: str | None = None,
    ) -> tuple[object, ...]:
        connect_parameters = {"application_name": application_name} if application_name else {}
        with psycopg.connect(**connect_parameters) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL ROLE geno_v2_runtime")
                cursor.execute(
                    "SELECT set_config('app.session_token_hash', %s, true)",
                    (session_hash,),
                )
                cursor.execute(statement, parameters)
                row = cursor.fetchone()
                if row is None:
                    raise AssertionError("auth command returned no row")
                return row

    @classmethod
    def _insert_pending_invitation(
        cls,
        *,
        actor_id: str,
        role: str,
        project_id: UUID | None = None,
        invitation_id: UUID | None = None,
        invite_hash: str | None = None,
        invited_by: str = "auth-command-fixture",
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> tuple[UUID, str]:
        invitation_id = invitation_id or uuid4()
        invite_hash = invite_hash or _digest(f"invite-{invitation_id}")
        project_id = project_id or cls.project_ids[0]
        created_at = created_at or datetime.now(UTC)
        expires_at = expires_at or created_at + timedelta(days=1)
        audience = "customer" if role == "client_viewer" else "admin"
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO project_member_invitations ("
                    "id, tenant_id, project_id, email, role, invite_token_hash, "
                    "audience, allowed_surfaces, invited_by, expires_at, created_at, "
                    "updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, "
                    "ARRAY[%s]::text[], %s, %s, %s, %s)",
                    (
                        invitation_id,
                        cls.tenant_id,
                        project_id,
                        actor_id,
                        role,
                        invite_hash,
                        audience,
                        audience,
                        invited_by,
                        expires_at,
                        created_at,
                        created_at,
                    ),
                )
        return invitation_id, invite_hash

    @classmethod
    def _create_invitation(
        cls,
        *,
        actor_id: str,
        role: str = "reviewer",
        session_hash: str | None = None,
        invitation_id: UUID | None = None,
        invite_hash: str | None = None,
        expires_at: datetime | None = None,
        project_id: UUID | None = None,
    ) -> tuple[tuple[object, ...], UUID, str, datetime]:
        invitation_id = invitation_id or uuid4()
        invite_hash = invite_hash or _digest(f"created-invite-{invitation_id}")
        expires_at = expires_at or datetime.now(UTC) + timedelta(days=1)
        project_id = project_id or cls.project_ids[0]
        row = cls._runtime_call(
            "SELECT * FROM geno_v2_create_project_member_invitation(" "%s, %s, %s, %s, %s, %s)",
            (invitation_id, project_id, actor_id, role, invite_hash, expires_at),
            session_hash=session_hash or cls.admin_session_hash,
        )
        return row, invitation_id, invite_hash, expires_at

    @classmethod
    def _redeem(
        cls,
        *,
        invitation_id: UUID,
        invite_hash: str,
        surface: str,
        idempotency_hash: str,
        attempt_id: UUID | None = None,
        session_id: UUID | None = None,
        session_hash: str | None = None,
        ciphertext: bytes | None = None,
        delivery_expires_at: datetime | None = None,
        application_name: str | None = None,
    ) -> tuple[object, ...]:
        return cls._runtime_call(
            "SELECT * FROM geno_v2_redeem_auth_invitation("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                attempt_id or uuid4(),
                session_id or uuid4(),
                invitation_id,
                invite_hash,
                surface,
                idempotency_hash,
                session_hash or _digest(f"redeem-session-{uuid4()}"),
                datetime.now(UTC) + timedelta(days=1),
                ciphertext or f"encrypted-delivery-{uuid4()}".encode(),
                "auth-command-test-key-v1",
                b"0123456789ab",
                delivery_expires_at or datetime.now(UTC) + timedelta(minutes=30),
            ),
            application_name=application_name,
        )

    @staticmethod
    def _set_writes_enabled(enabled: bool, *, application_name: str | None = None) -> None:
        connect_parameters = {"application_name": application_name} if application_name else {}
        with psycopg.connect(**connect_parameters) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE auth_runtime_write_controls SET writes_enabled = %s, "
                    "reason = %s, updated_by = 'auth-command-test', "
                    "updated_at = greatest(clock_timestamp(), "
                    "updated_at + interval '1 microsecond') WHERE singleton",
                    (enabled, "test-enabled" if enabled else "test-disabled"),
                )

    def test_01_preflight_rate_limits_and_invalid_tokens_fail_closed(self) -> None:
        actor = f"preflight-{uuid4().hex}@example.test"
        invitation_id, invite_hash = self._insert_pending_invitation(
            actor_id=actor, role="reviewer"
        )
        source = _digest(f"source-{uuid4()}")
        for expected_count in range(1, 21):
            row = self._runtime_call(
                "SELECT * FROM geno_v2_preflight_auth_invitation(%s, %s, %s, %s)",
                (invitation_id, invite_hash, "admin", source),
            )
            self.assertEqual(
                row[0:6],
                (
                    "compatible",
                    "compatible",
                    "admin",
                    "admin",
                    "reviewer",
                    "auth_surface_policy_v1",
                ),
            )
            self.assertEqual(row[6], expected_count)
            self.assertEqual(row[8], None)
        limited = self._runtime_call(
            "SELECT * FROM geno_v2_preflight_auth_invitation(%s, %s, %s, %s)",
            (invitation_id, invite_hash, "admin", source),
        )
        self.assertEqual(limited[0:6], ("rate_limited", "invalid", "admin", None, None, None))
        self.assertEqual(limited[6], 21)
        self.assertGreater(limited[8], 0)

        wrong_id, actual_hash = self._insert_pending_invitation(
            actor_id=f"wrong-{uuid4().hex}@example.test", role="reviewer"
        )
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status, updated_at FROM project_member_invitations WHERE id = %s",
                    (wrong_id,),
                )
                before = cursor.fetchone()
        wrong = self._runtime_call(
            "SELECT * FROM geno_v2_preflight_auth_invitation(%s, %s, %s, %s)",
            (wrong_id, _digest("wrong-token"), "admin", _digest(f"source-{uuid4()}")),
        )
        self.assertEqual(wrong[0:6], ("invalid", "invalid", "admin", None, None, None))
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status, updated_at FROM project_member_invitations WHERE id = %s",
                    (wrong_id,),
                )
                self.assertEqual(cursor.fetchone(), before)
                cursor.execute(
                    "SELECT invite_token_hash FROM project_member_invitations WHERE id = %s",
                    (wrong_id,),
                )
                self.assertEqual(cursor.fetchone()[0], actual_hash)

        expired_id, expired_hash = self._insert_pending_invitation(
            actor_id=f"expired-{uuid4().hex}@example.test",
            role="reviewer",
            created_at=datetime.now(UTC) - timedelta(hours=2),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        for _ in range(2):
            expired = self._runtime_call(
                "SELECT * FROM geno_v2_preflight_auth_invitation(%s, %s, %s, %s)",
                (expired_id, expired_hash, "admin", _digest(f"source-{uuid4()}")),
            )
            self.assertEqual(expired[0], "invalid")
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status, revoke_reason FROM project_member_invitations WHERE id = %s",
                    (expired_id,),
                )
                self.assertEqual(cursor.fetchone(), ("expired", "member_invitation_expired"))
                cursor.execute(
                    "SELECT count(*) FROM audit_events WHERE event_type = "
                    "'auth.invitation.expired' AND target_id = %s",
                    (str(expired_id),),
                )
                self.assertEqual(cursor.fetchone()[0], 1)

        race_id = uuid4()
        race_hash = _digest(f"preflight-create-race-{race_id}")
        race_actor = f"preflight-create-race-{uuid4().hex}@example.test"
        race_expiry = datetime.now(UTC) - timedelta(hours=1)
        self._insert_pending_invitation(
            actor_id=race_actor,
            role="reviewer",
            invitation_id=race_id,
            invite_hash=race_hash,
            invited_by=self.admin_actor,
            created_at=datetime.now(UTC) - timedelta(hours=2),
            expires_at=race_expiry,
        )
        race_barrier = Barrier(2)

        def expire_from_preflight() -> str:
            race_barrier.wait(timeout=5)
            return self._runtime_call(
                "SELECT * FROM geno_v2_preflight_auth_invitation(%s, %s, %s, %s)",
                (race_id, race_hash, "admin", _digest(f"source-{uuid4()}")),
            )[0]

        def expire_from_create() -> str:
            race_barrier.wait(timeout=5)
            return self._create_invitation(
                actor_id=race_actor,
                invitation_id=race_id,
                invite_hash=race_hash,
                expires_at=race_expiry,
            )[0][0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            preflight_future = executor.submit(expire_from_preflight)
            create_future = executor.submit(expire_from_create)
            self.assertEqual(preflight_future.result(timeout=10), "invalid")
            self.assertEqual(create_future.result(timeout=10), "expired")
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status FROM project_member_invitations WHERE id = %s",
                    (race_id,),
                )
                self.assertEqual(cursor.fetchone()[0], "expired")
                cursor.execute(
                    "SELECT count(*) FROM audit_events WHERE event_type = "
                    "'auth.invitation.expired' AND target_id = %s",
                    (str(race_id),),
                )
                self.assertEqual(cursor.fetchone()[0], 1)

    def test_02_invitation_commands_are_idempotent_and_require_member_manage(self) -> None:
        actor = f"create-{uuid4().hex}@example.test"
        created, invitation_id, invite_hash, expires_at = self._create_invitation(actor_id=actor)
        self.assertEqual(created[0], "created")
        replayed, *_ = self._create_invitation(
            actor_id=actor,
            invitation_id=invitation_id,
            invite_hash=invite_hash,
            expires_at=expires_at,
        )
        self.assertEqual(replayed[0], "replayed")
        with self.assertRaises(psycopg.Error) as conflict:
            self._create_invitation(
                actor_id=actor,
                invitation_id=invitation_id,
                invite_hash=_digest("immutable-conflict"),
                expires_at=expires_at,
            )
        self.assertEqual(conflict.exception.sqlstate, "GA004")
        self.assertEqual(
            conflict.exception.diag.message_primary, "auth_command_idempotency_conflict"
        )

        expired_id = uuid4()
        expired_actor = f"same-expired-{uuid4().hex}@example.test"
        expired_hash = _digest(f"expired-{expired_id}")
        created_at = datetime.now(UTC) - timedelta(hours=2)
        expired_at = datetime.now(UTC) - timedelta(hours=1)
        self._insert_pending_invitation(
            actor_id=expired_actor,
            role="reviewer",
            invitation_id=expired_id,
            invite_hash=expired_hash,
            invited_by=self.admin_actor,
            created_at=created_at,
            expires_at=expired_at,
        )
        first_expired, *_ = self._create_invitation(
            actor_id=expired_actor,
            invitation_id=expired_id,
            invite_hash=expired_hash,
            expires_at=expired_at,
        )
        second_expired, *_ = self._create_invitation(
            actor_id=expired_actor,
            invitation_id=expired_id,
            invite_hash=expired_hash,
            expires_at=expired_at,
        )
        self.assertEqual(first_expired[0], "expired")
        self.assertEqual(second_expired[0], "expired")

        replacement_actor = f"replacement-{uuid4().hex}@example.test"
        old_id, _ = self._insert_pending_invitation(
            actor_id=replacement_actor,
            role="reviewer",
            invited_by=self.admin_actor,
            created_at=datetime.now(UTC) - timedelta(hours=2),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        replacement, replacement_id, _, _ = self._create_invitation(actor_id=replacement_actor)
        self.assertEqual(replacement[0], "created")
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, status FROM project_member_invitations "
                    "WHERE id IN (%s, %s) ORDER BY id",
                    (old_id, replacement_id),
                )
                self.assertEqual(
                    {tuple(row) for row in cursor.fetchall()},
                    {(old_id, "expired"), (replacement_id, "pending")},
                )

        with self.assertRaises(psycopg.Error) as denied:
            self._create_invitation(
                actor_id=f"denied-{uuid4().hex}@example.test",
                session_hash=self.analyst_session_hash,
            )
        self.assertEqual(denied.exception.sqlstate, "GA003")
        self.assertEqual(denied.exception.diag.message_primary, "auth_command_not_authorized")

    def test_03_redeem_rejects_surface_mismatch_and_replays_exact_scope(self) -> None:
        mismatch_actor = f"mismatch-{uuid4().hex}@example.test"
        mismatch_id, mismatch_hash = self._insert_pending_invitation(
            actor_id=mismatch_actor, role="client_viewer"
        )
        mismatch = self._redeem(
            invitation_id=mismatch_id,
            invite_hash=mismatch_hash,
            surface="admin",
            idempotency_hash=_digest(f"idem-{uuid4()}"),
        )
        self.assertEqual(mismatch[0], "surface_mismatch")
        self.assertTrue(all(value is None for value in mismatch[1:13]))
        self.assertEqual(mismatch[13], "customer")
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM auth_invitation_redemption_attempts "
                    "WHERE invitation_id = %s",
                    (mismatch_id,),
                )
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "SELECT count(*) FROM project_members WHERE project_id = %s AND user_id = %s",
                    (self.project_ids[0], mismatch_actor),
                )
                self.assertEqual(cursor.fetchone()[0], 0)

        actor = f"multi-scope-{uuid4().hex}@example.test"
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO project_members "
                    "(tenant_id, project_id, user_id, role, invited_by) "
                    "VALUES (%s, %s, %s, 'analyst', 'auth-command-test')",
                    (self.tenant_id, self.project_ids[1], actor),
                )
        invitation_id, invite_hash = self._insert_pending_invitation(
            actor_id=actor, role="client_viewer", project_id=self.project_ids[0]
        )
        idempotency_hash = _digest(f"idem-{uuid4()}")
        attempt_id = uuid4()
        session_id = uuid4()
        session_hash = _digest(f"session-{uuid4()}")
        ciphertext = f"secret-delivery-{uuid4()}".encode()
        succeeded = self._redeem(
            invitation_id=invitation_id,
            invite_hash=invite_hash,
            surface="customer",
            idempotency_hash=idempotency_hash,
            attempt_id=attempt_id,
            session_id=session_id,
            session_hash=session_hash,
            ciphertext=ciphertext,
        )
        self.assertEqual(succeeded[0], "succeeded")
        self.assertEqual(succeeded[1:5], (attempt_id, session_id, actor, self.tenant_id))
        self.assertEqual(set(succeeded[5]), {str(self.project_ids[0]), str(self.project_ids[1])})
        self.assertEqual(succeeded[8], ciphertext)
        replayed = self._redeem(
            invitation_id=invitation_id,
            invite_hash=invite_hash,
            surface="customer",
            idempotency_hash=idempotency_hash,
            attempt_id=uuid4(),
            session_id=uuid4(),
            session_hash=_digest(f"ignored-session-{uuid4()}"),
            ciphertext=b"ignored-new-ciphertext",
        )
        self.assertEqual(replayed[0], "replayed")
        self.assertEqual(replayed[1:12], succeeded[1:12])
        self.assertEqual(replayed[12], 1)
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM audit_events WHERE event_type = "
                    "'auth.redemption.replayed' AND target_id = %s",
                    (str(attempt_id),),
                )
                self.assertEqual(cursor.fetchone()[0], 1)
                cursor.execute(
                    "SELECT count(*) FROM audit_events WHERE audit_events::text LIKE %s",
                    (f"%{ciphertext.decode()}%",),
                )
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "SELECT metadata::text FROM runtime_sessions WHERE id = %s",
                    (session_id,),
                )
                self.assertNotIn(ciphertext.decode(), cursor.fetchone()[0])

    def test_04_concurrent_same_invitation_has_one_success_and_one_replay(self) -> None:
        actor = f"concurrent-{uuid4().hex}@example.test"
        invitation_id, invite_hash = self._insert_pending_invitation(
            actor_id=actor, role="reviewer"
        )
        idempotency_hash = _digest(f"concurrent-idem-{uuid4()}")
        barrier = Barrier(2)

        def redeem_once(marker: str) -> tuple[object, ...]:
            barrier.wait(timeout=5)
            return self._redeem(
                invitation_id=invitation_id,
                invite_hash=invite_hash,
                surface="admin",
                idempotency_hash=idempotency_hash,
                ciphertext=f"concurrent-ciphertext-{marker}".encode(),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            rows = list(executor.map(redeem_once, ("one", "two")))
        self.assertEqual({row[0] for row in rows}, {"succeeded", "replayed"})
        self.assertEqual(rows[0][1:12], rows[1][1:12])
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM auth_invitation_redemption_attempts "
                    "WHERE invitation_id = %s",
                    (invitation_id,),
                )
                self.assertEqual(cursor.fetchone()[0], 1)
                cursor.execute(
                    "SELECT count(*) FROM runtime_sessions WHERE actor_id = %s",
                    (actor,),
                )
                self.assertEqual(cursor.fetchone()[0], 1)

        cross_actor = f"cross-project-{uuid4().hex}@example.test"
        first_id, first_hash = self._insert_pending_invitation(
            actor_id=cross_actor,
            role="reviewer",
            project_id=self.project_ids[0],
        )
        second_id, second_hash = self._insert_pending_invitation(
            actor_id=cross_actor,
            role="reviewer",
            project_id=self.project_ids[1],
        )
        cross_barrier = Barrier(2)

        def redeem_project(invitation: tuple[UUID, str]) -> tuple[object, ...]:
            cross_barrier.wait(timeout=5)
            return self._redeem(
                invitation_id=invitation[0],
                invite_hash=invitation[1],
                surface="admin",
                idempotency_hash=_digest(f"cross-project-idem-{invitation[0]}"),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            cross_rows = list(
                executor.map(
                    redeem_project,
                    ((first_id, first_hash), (second_id, second_hash)),
                )
            )
        self.assertEqual([row[0] for row in cross_rows], ["succeeded", "succeeded"])
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM project_members WHERE tenant_id = %s "
                    "AND user_id = %s AND project_id IN (%s, %s)",
                    (
                        self.tenant_id,
                        cross_actor,
                        self.project_ids[0],
                        self.project_ids[1],
                    ),
                )
                self.assertEqual(cursor.fetchone()[0], 2)

    def test_05_kill_switch_toggle_is_linear_with_in_flight_create(self) -> None:
        invitation_id = uuid4()
        actor = f"linear-create-{uuid4().hex}@example.test"
        invite_hash = _digest(f"linear-create-{invitation_id}")
        expires_at = datetime.now(UTC) + timedelta(days=1)
        create_app = f"auth-create-{uuid4().hex}"
        toggle_app = f"auth-toggle-{uuid4().hex}"
        redeem_app = f"auth-redeem-{uuid4().hex}"
        redeem_actor = f"linear-redeem-{uuid4().hex}@example.test"
        redeem_id, redeem_hash = self._insert_pending_invitation(
            actor_id=redeem_actor,
            role="reviewer",
            project_id=self.project_ids[1],
        )

        def wait_until_lock_wait(application_name: str) -> None:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with psycopg.connect() as observer:
                    with observer.cursor() as cursor:
                        cursor.execute(
                            "SELECT wait_event_type FROM pg_stat_activity "
                            "WHERE application_name = %s",
                            (application_name,),
                        )
                        row = cursor.fetchone()
                if row is not None and row[0] == "Lock":
                    return
                time.sleep(0.02)
            self.fail(f"{application_name} did not reach its expected lock wait")

        blocker = psycopg.connect()
        try:
            with blocker.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM projects WHERE tenant_id = %s " "ORDER BY id FOR UPDATE",
                    (self.tenant_id,),
                )
                cursor.fetchall()

            def create_invitation() -> tuple[object, ...]:
                return self._runtime_call(
                    "SELECT * FROM geno_v2_create_project_member_invitation("
                    "%s, %s, %s, %s, %s, %s)",
                    (
                        invitation_id,
                        self.project_ids[0],
                        actor,
                        "reviewer",
                        invite_hash,
                        expires_at,
                    ),
                    session_hash=self.admin_session_hash,
                    application_name=create_app,
                )

            with ThreadPoolExecutor(max_workers=3) as executor:
                create_future = executor.submit(create_invitation)
                wait_until_lock_wait(create_app)
                toggle_future = executor.submit(
                    self._set_writes_enabled,
                    False,
                    application_name=toggle_app,
                )
                wait_until_lock_wait(toggle_app)
                redeem_future = executor.submit(
                    self._redeem,
                    invitation_id=redeem_id,
                    invite_hash=redeem_hash,
                    surface="admin",
                    idempotency_hash=_digest(f"linear-redeem-{redeem_id}"),
                    application_name=redeem_app,
                )
                wait_until_lock_wait(redeem_app)
                self.assertFalse(create_future.done())
                self.assertFalse(toggle_future.done())
                self.assertFalse(redeem_future.done())
                blocker.commit()
                self.assertEqual(create_future.result(timeout=10)[0], "created")
                redeem_succeeded = False
                try:
                    redeem_succeeded = (
                        redeem_future.result(timeout=10)[0] == "succeeded"
                    )
                except psycopg.Error as redeem_error:
                    self.assertEqual(redeem_error.sqlstate, "42501")
                toggle_future.result(timeout=10)
        finally:
            blocker.close()

        try:
            with self.assertRaises(psycopg.Error) as disabled:
                self._create_invitation(actor_id=f"after-toggle-{uuid4().hex}@example.test")
            self.assertEqual(disabled.exception.sqlstate, "42501")
            self.assertEqual(
                disabled.exception.diag.message_primary,
                "auth_writes_temporarily_disabled",
            )
            with psycopg.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM auth_invitation_redemption_attempts "
                        "WHERE invitation_id = %s",
                        (redeem_id,),
                    )
                    self.assertEqual(
                        cursor.fetchone()[0], 1 if redeem_succeeded else 0
                    )
                    cursor.execute(
                        "SELECT count(*) FROM project_members "
                        "WHERE tenant_id = %s AND user_id = %s",
                        (self.tenant_id, redeem_actor),
                    )
                    self.assertEqual(
                        cursor.fetchone()[0], 1 if redeem_succeeded else 0
                    )
        finally:
            self._set_writes_enabled(True)

    def test_06_tenant_role_projection_and_auth_command_do_not_deadlock(self) -> None:
        actor = f"tenant-role-race-{uuid4().hex}@example.test"
        session_hash = _digest(f"tenant-role-race-session-{uuid4()}")
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO tenant_members "
                    "(tenant_id, user_id, role, invited_by) "
                    "VALUES (%s, %s, 'tenant_admin', 'auth-command-test') "
                    "RETURNING id",
                    (self.tenant_id, actor),
                )
                tenant_member_id = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO project_members "
                    "(tenant_id, project_id, user_id, role, invited_by) "
                    "VALUES (%s, %s, %s, 'project_owner', 'auth-command-test')",
                    (self.tenant_id, self.project_ids[0], actor),
                )
                self._insert_session_lineage(
                    cursor,
                    actor_id=actor,
                    invitation_project_id=self.project_ids[0],
                    invitation_role="project_owner",
                    session_hash=session_hash,
                    marker=f"tenant-role-race-{uuid4().hex}",
                )

        blocker = psycopg.connect()
        application_name = f"tenant-role-auth-command-{uuid4().hex}"
        try:
            with blocker.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM tenant_members WHERE id = %s FOR UPDATE",
                    (tenant_member_id,),
                )

            def create_invitation() -> tuple[object, ...]:
                return self._runtime_call(
                    "SELECT * FROM geno_v2_create_project_member_invitation("
                    "%s, %s, %s, 'reviewer', %s, %s)",
                    (
                        uuid4(),
                        self.project_ids[0],
                        f"tenant-role-invitee-{uuid4().hex}@example.test",
                        _digest(f"tenant-role-invite-{uuid4()}"),
                        datetime.now(UTC) + timedelta(days=1),
                    ),
                    session_hash=session_hash,
                    application_name=application_name,
                )

            with ThreadPoolExecutor(max_workers=1) as executor:
                command_future = executor.submit(create_invitation)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with psycopg.connect() as observer:
                        with observer.cursor() as cursor:
                            cursor.execute(
                                "SELECT wait_event_type FROM pg_stat_activity "
                                "WHERE application_name = %s",
                                (application_name,),
                            )
                            row = cursor.fetchone()
                    if row is not None and row[0] == "Lock":
                        break
                    time.sleep(0.02)
                else:
                    self.fail("auth command did not wait on the tenant member lock")

                with blocker.cursor() as cursor:
                    cursor.execute(
                        "UPDATE tenant_members SET role = 'super_admin', "
                        "updated_at = clock_timestamp() WHERE id = %s",
                        (tenant_member_id,),
                    )
                blocker.commit()
                with self.assertRaises(psycopg.Error) as stale_session:
                    command_future.result(timeout=10)
                self.assertEqual(stale_session.exception.sqlstate, "GA003")
        finally:
            blocker.close()

        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT role FROM tenant_members WHERE id = %s",
                    (tenant_member_id,),
                )
                self.assertEqual(cursor.fetchone()[0], "super_admin")
                cursor.execute(
                    "SELECT count(*) FROM runtime_project_access_grants "
                    "WHERE source_id = %s AND canonical_role = 'super_admin'",
                    (tenant_member_id,),
                )
                self.assertEqual(cursor.fetchone()[0], len(self.project_ids))

    def test_07_disabled_switch_allows_contraction_and_erases_recovery_secret(self) -> None:
        actor = f"expired-recovery-{uuid4().hex}@example.test"
        invitation_id, invite_hash = self._insert_pending_invitation(
            actor_id=actor, role="reviewer"
        )
        idem = _digest(f"expired-idem-{uuid4()}")
        delivery_expires_at = datetime.now(UTC) + timedelta(milliseconds=500)
        succeeded = self._redeem(
            invitation_id=invitation_id,
            invite_hash=invite_hash,
            surface="admin",
            idempotency_hash=idem,
            delivery_expires_at=delivery_expires_at,
        )
        self.assertEqual(succeeded[0], "succeeded")

        blocked_actor = f"blocked-replay-{uuid4().hex}@example.test"
        blocked_id, blocked_hash = self._insert_pending_invitation(
            actor_id=blocked_actor, role="reviewer"
        )
        blocked_idem = _digest(f"blocked-idem-{uuid4()}")
        self.assertEqual(
            self._redeem(
                invitation_id=blocked_id,
                invite_hash=blocked_hash,
                surface="admin",
                idempotency_hash=blocked_idem,
            )[0],
            "succeeded",
        )
        pending_id, _ = self._insert_pending_invitation(
            actor_id=f"revoke-{uuid4().hex}@example.test", role="reviewer"
        )
        expirable_id, _ = self._insert_pending_invitation(
            actor_id=f"expire-{uuid4().hex}@example.test",
            role="reviewer",
            created_at=datetime.now(UTC) - timedelta(hours=2),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        time.sleep(0.7)
        self._set_writes_enabled(False)
        try:
            expired = self._redeem(
                invitation_id=invitation_id,
                invite_hash=invite_hash,
                surface="admin",
                idempotency_hash=idem,
            )
            self.assertEqual(expired[0], "recovery_expired")
            self.assertTrue(all(value is None for value in expired[1:14]))

            with self.assertRaises(psycopg.Error) as blocked_replay:
                self._redeem(
                    invitation_id=blocked_id,
                    invite_hash=blocked_hash,
                    surface="admin",
                    idempotency_hash=blocked_idem,
                )
            self.assertEqual(blocked_replay.exception.sqlstate, "42501")
            self.assertEqual(
                blocked_replay.exception.diag.message_primary,
                "auth_writes_temporarily_disabled",
            )
            revoked = self._runtime_call(
                "SELECT * FROM geno_v2_revoke_project_member_invitation(%s, %s)",
                (pending_id, "member_invitation_security"),
                session_hash=self.admin_session_hash,
            )
            self.assertEqual(revoked[0:3], ("revoked", pending_id, "revoked"))
            expired_invitation = self._runtime_call(
                "SELECT * FROM geno_v2_expire_project_member_invitation(%s)",
                (expirable_id,),
                session_hash=self.admin_session_hash,
            )
            expired_again = self._runtime_call(
                "SELECT * FROM geno_v2_expire_project_member_invitation(%s)",
                (expirable_id,),
                session_hash=self.admin_session_hash,
            )
            self.assertEqual(
                expired_invitation[0:3],
                ("expired", expirable_id, "expired"),
            )
            self.assertEqual(
                expired_again[0:3],
                ("already_terminal", expirable_id, "expired"),
            )
        finally:
            self._set_writes_enabled(True)
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT delivery_ciphertext, delivery_key_id, delivery_nonce, "
                    "secret_erased_at FROM auth_invitation_redemption_attempts WHERE id = %s",
                    (succeeded[1],),
                )
                ciphertext, key_id, nonce, erased_at = cursor.fetchone()
                self.assertIsNone(ciphertext)
                self.assertIsNone(key_id)
                self.assertIsNone(nonce)
                self.assertIsNotNone(erased_at)

        limit_actor = f"replay-limit-{uuid4().hex}@example.test"
        limit_id, limit_hash = self._insert_pending_invitation(
            actor_id=limit_actor, role="reviewer"
        )
        limit_idem = _digest(f"limit-idem-{uuid4()}")
        limit_success = self._redeem(
            invitation_id=limit_id,
            invite_hash=limit_hash,
            surface="admin",
            idempotency_hash=limit_idem,
        )
        for expected_count in range(1, 4):
            replay = self._redeem(
                invitation_id=limit_id,
                invite_hash=limit_hash,
                surface="admin",
                idempotency_hash=limit_idem,
            )
            self.assertEqual((replay[0], replay[12]), ("replayed", expected_count))
        self._set_writes_enabled(False)
        try:
            exhausted = self._redeem(
                invitation_id=limit_id,
                invite_hash=limit_hash,
                surface="admin",
                idempotency_hash=limit_idem,
            )
            self.assertEqual(exhausted[0], "replay_limit_exceeded")
        finally:
            self._set_writes_enabled(True)
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT delivery_ciphertext, secret_erased_at FROM "
                    "auth_invitation_redemption_attempts WHERE id = %s",
                    (limit_success[1],),
                )
                ciphertext, erased_at = cursor.fetchone()
                self.assertIsNone(ciphertext)
                self.assertIsNotNone(erased_at)

    def test_08_delivery_logout_and_reauth_commands_are_idempotent(self) -> None:
        def create_session(label: str) -> tuple[tuple[object, ...], str]:
            actor = f"{label}-{uuid4().hex}@example.test"
            invitation_id, invite_hash = self._insert_pending_invitation(
                actor_id=actor, role="reviewer"
            )
            session_hash = _digest(f"{label}-session-{uuid4()}")
            result = self._redeem(
                invitation_id=invitation_id,
                invite_hash=invite_hash,
                surface="admin",
                idempotency_hash=_digest(f"{label}-idem-{uuid4()}"),
                session_hash=session_hash,
            )
            return result, session_hash

        def call_twice(
            statement: str, session_hash: str
        ) -> tuple[tuple[object, ...], tuple[object, ...]]:
            barrier = Barrier(2)

            def call() -> tuple[object, ...]:
                barrier.wait(timeout=5)
                return self._runtime_call(statement, session_hash=session_hash)

            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(call)
                second = executor.submit(call)
                return first.result(timeout=10), second.result(timeout=10)

        confirmed_session, confirmed_hash = create_session("confirm")
        confirmed_rows = call_twice(
            "SELECT * FROM geno_v2_confirm_current_auth_delivery()", confirmed_hash
        )
        self.assertEqual(
            {row[0] for row in confirmed_rows},
            {"confirmed", "already_confirmed"},
        )
        self.assertEqual(confirmed_rows[0][1:4], confirmed_rows[1][1:4])
        self.assertEqual(confirmed_rows[0][1], confirmed_session[1])

        erased_session, erased_hash = create_session("erase")
        erased_rows = call_twice(
            "SELECT * FROM geno_v2_erase_current_auth_delivery_secret()", erased_hash
        )
        self.assertEqual(
            {row[0] for row in erased_rows},
            {"erased", "already_erased"},
        )
        self.assertEqual(erased_rows[0][1:4], erased_rows[1][1:4])
        self.assertEqual(erased_rows[0][1], erased_session[1])

        logout_session, logout_hash = create_session("logout")
        logout_rows = call_twice("SELECT * FROM geno_v2_logout_current_session()", logout_hash)
        self.assertEqual(
            {row[0] for row in logout_rows},
            {"logged_out", "no_active_session"},
        )
        logged_out = next(row for row in logout_rows if row[0] == "logged_out")
        self.assertEqual(logged_out[1], logout_session[2])
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM runtime_session_reauth_queue WHERE session_id = %s",
                    (logout_session[2],),
                )
                self.assertEqual(cursor.fetchone()[0], 0)

                cursor.execute(
                    "SELECT id, actor_id FROM runtime_sessions WHERE session_token_hash = %s",
                    (self.admin_session_hash,),
                )
                admin_session_id, admin_actor = cursor.fetchone()
                cursor.execute(
                    "INSERT INTO runtime_session_reauth_queue "
                    "(session_id, tenant_id, actor_id, reason_code) VALUES (%s, %s, %s, %s)",
                    (admin_session_id, self.tenant_id, admin_actor, "test_reauthentication"),
                )
        resolved = self._runtime_call(
            "SELECT * FROM geno_v2_resolve_current_reauth_queue()",
            session_hash=self.admin_session_hash,
        )
        resolved_again = self._runtime_call(
            "SELECT * FROM geno_v2_resolve_current_reauth_queue()",
            session_hash=self.admin_session_hash,
        )
        self.assertEqual(resolved[0:3], ("resolved", admin_session_id, 1))
        self.assertEqual(resolved_again[0:3], ("no_pending", admin_session_id, 0))

    def test_09_runtime_acl_and_final_write_state_are_exact(self) -> None:
        public_functions = (
            "geno_v2_preflight_auth_invitation(uuid,text,text,text)",
            "geno_v2_create_project_member_invitation(uuid,uuid,text,text,text,timestamp with time zone)",
            "geno_v2_revoke_project_member_invitation(uuid,text)",
            "geno_v2_expire_project_member_invitation(uuid)",
            "geno_v2_redeem_auth_invitation(uuid,uuid,uuid,text,text,text,text,timestamp with time zone,bytea,text,bytea,timestamp with time zone)",
            "geno_v2_confirm_current_auth_delivery()",
            "geno_v2_erase_current_auth_delivery_secret()",
            "geno_v2_logout_current_session()",
            "geno_v2_resolve_current_reauth_queue()",
        )
        sensitive_tables = (
            "project_member_invitations",
            "auth_invitation_redemption_attempts",
            "runtime_sessions",
            "auth_preflight_rate_limits",
            "runtime_session_reauth_queue",
            "auth_runtime_write_controls",
        )
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                for signature in public_functions:
                    cursor.execute(
                        "SELECT has_function_privilege('geno_v2_runtime', %s, 'EXECUTE'), "
                        "has_function_privilege('public', %s, 'EXECUTE')",
                        (signature, signature),
                    )
                    self.assertEqual(cursor.fetchone(), (True, False), signature)
                for table in sensitive_tables:
                    cursor.execute(
                        "SELECT has_table_privilege('geno_v2_runtime', %s, 'INSERT'), "
                        "has_table_privilege('geno_v2_runtime', %s, 'UPDATE'), "
                        "has_table_privilege('geno_v2_runtime', %s, 'DELETE')",
                        (table, table, table),
                    )
                    self.assertEqual(cursor.fetchone(), (False, False, False), table)
                cursor.execute(
                    "SELECT rolcanlogin, rolpassword IS NULL FROM pg_authid "
                    "WHERE rolname = 'geno_v2_api_login'"
                )
                self.assertEqual(cursor.fetchone(), (False, True))
                cursor.execute(
                    "SELECT writes_enabled FROM auth_runtime_write_controls WHERE singleton"
                )
                self.assertEqual(cursor.fetchone()[0], True)
                cursor.execute(
                    "SELECT has_table_privilege('geno_v2_authz_owner', "
                    "'auth_runtime_write_controls', 'UPDATE'), "
                    "has_column_privilege('geno_v2_authz_owner', "
                    "'auth_runtime_write_controls', 'writes_enabled', 'UPDATE'), "
                    "has_column_privilege('geno_v2_authz_owner', "
                    "'auth_runtime_write_controls', 'reason', 'UPDATE')"
                )
                self.assertEqual(cursor.fetchone(), (False, True, False))


if __name__ == "__main__":
    unittest.main()
