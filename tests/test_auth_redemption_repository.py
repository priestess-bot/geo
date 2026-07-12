from __future__ import annotations

from datetime import UTC, datetime, timedelta
import pytest

from geno_core.auth import (
    AuthContractError,
    AuthSessionV2Repository,
    InvitationSurface,
    InvitationSurfaceCompatibility,
)
from geno_core.repository import PostgresEvidenceRepository


class ScriptedCursor:
    def __init__(self, invitation: dict[str, object], attempt: dict[str, object] | None = None) -> None:
        self.invitation = invitation
        self.attempt = attempt
        self.last_sql = ""
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "ScriptedCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.last_sql = " ".join(sql.split())
        self.calls.append((self.last_sql, params))
        if "INSERT INTO auth_invitation_redemption_attempts" in self.last_sql and self.attempt is not None:
            self.attempt.update(
                {
                    "requested_surface": params[2],
                    "idempotency_key_hash": params[3],
                    "request_hash": params[4],
                    "token_fingerprint": params[5],
                }
            )

    def fetchone(self) -> dict[str, object] | None:
        if "FROM project_member_invitations" in self.last_sql:
            return dict(self.invitation)
        if "FROM auth_invitation_redemption_attempts" in self.last_sql:
            return dict(self.attempt) if self.attempt else None
        if "SELECT writes_enabled" in self.last_sql:
            return {"writes_enabled": True}
        return None

    def fetchall(self) -> list[dict[str, object]]:
        return []


class ScriptedConnection:
    def __init__(self, cursor: ScriptedCursor) -> None:
        self.scripted_cursor = cursor
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self) -> ScriptedCursor:
        return self.scripted_cursor

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


def _invitation(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "10000000-0000-4000-8000-000000000001",
        "project_id": "10000000-0000-4000-8000-000000000002",
        "tenant_id": "10000000-0000-4000-8000-000000000003",
        "email": "viewer@example.com",
        "role": "viewer",
        "status": "pending",
        "invite_token_hash": "unused-by-script",
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
        "audience": "customer",
        "allowed_surfaces": ["customer"],
        "policy_version": "auth_surface_policy_v1",
        "accepted_by_attempt_id": None,
    }
    value.update(overrides)
    return value


def _attempt(invitation_id: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "10000000-0000-4000-8000-000000000004",
        "invitation_id": invitation_id,
        "requested_surface": "customer",
        "idempotency_key_hash": "unused-by-script",
        "request_hash": "unused-by-script",
        "token_fingerprint": "unused-by-script",
        "session_id": None,
        "status": "preparing",
        "replay_count": 0,
        "delivery_ciphertext": None,
        "delivery_key_id": None,
        "delivery_nonce": None,
        "delivery_expires_at": None,
        "delivery_confirmed_at": None,
        "secret_erased_at": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    value.update(overrides)
    return value


def test_preflight_reports_stale_stored_policy_and_remains_read_only() -> None:
    cursor = ScriptedCursor(_invitation(policy_version="auth_surface_policy_v0"))
    connection = ScriptedConnection(cursor)
    repository = AuthSessionV2Repository(connection, keyring=None)

    result = repository.preflight(
        invitation_id=str(cursor.invitation["id"]),
        invite_token="invite-secret",
        requested_surface=InvitationSurface.CUSTOMER,
    )

    assert result.compatibility is InvitationSurfaceCompatibility.POLICY_STALE
    assert connection.commit_count == 1  # deny-all pooled-connection GUC baseline
    assert connection.rollback_count == 1
    assert not any("INSERT INTO" in sql or "UPDATE " in sql for sql, _params in cursor.calls)


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"policy_version": "auth_surface_policy_v0"}, "invitation_policy_stale"),
        ({"audience": "admin", "allowed_surfaces": ["admin", "customer"]}, "invitation_policy_stale"),
        ({"allowed_surfaces": ["admin"]}, "invitation_policy_stale"),
    ],
)
def test_redeem_rejects_stale_policy_without_member_or_session_side_effects(
    overrides: dict[str, object],
    expected_code: str,
) -> None:
    invitation = _invitation(**overrides)
    attempt = _attempt(str(invitation["id"]))
    cursor = ScriptedCursor(invitation, attempt)
    connection = ScriptedConnection(cursor)
    repository = AuthSessionV2Repository(connection, keyring=object())  # type: ignore[arg-type]

    with pytest.raises(AuthContractError) as caught:
        repository.redeem(
            invitation_id=str(invitation["id"]),
            invite_token="invite-secret",
            requested_surface=InvitationSurface.CUSTOMER,
            idempotency_key="stable-idempotency-key",
        )

    assert caught.value.code == expected_code
    assert connection.commit_count == 1  # deny-all pooled-connection GUC baseline
    assert connection.rollback_count == 1
    executed = "\n".join(sql for sql, _params in cursor.calls)
    assert "INSERT INTO project_members" not in executed
    assert "INSERT INTO runtime_sessions" not in executed


class ScopeCursor:
    def __init__(self) -> None:
        self.query_index = -1

    def __enter__(self) -> "ScopeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _sql: str, _params: tuple[object, ...] = ()) -> None:
        self.query_index += 1

    def fetchall(self) -> list[dict[str, object]]:
        if self.query_index == 0:
            return [{"tenant_id": "tenant-a", "role": "tenant_admin"}]
        return [
            {
                "project_id": "project-a",
                "role": "viewer",
                "tenant_id": "tenant-a",
                "permissions": [],
                "scope_source": "direct_member",
            },
            {
                "project_id": "project-b",
                "role": "viewer",
                "tenant_id": "tenant-b",
                "permissions": [],
                "scope_source": "direct_member",
            },
        ]


class ScopeConnection:
    def __init__(self) -> None:
        self.scope_cursor = ScopeCursor()

    def cursor(self) -> ScopeCursor:
        return self.scope_cursor


def test_membership_scope_requires_explicit_tenant_for_multi_tenant_actor() -> None:
    repository = PostgresEvidenceRepository(ScopeConnection())  # type: ignore[arg-type]

    with pytest.raises(PermissionError, match="tenant_id is required"):
        repository.get_runtime_membership_scope(actor_id="multi@example.com")
