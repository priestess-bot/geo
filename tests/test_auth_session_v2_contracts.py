from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from geo_api.auth_contracts import AuthInvitationPreflightRequest, AuthInvitationRedeemRequest
from geo_api.auth_routes import _consume_preflight_rate_limit
from geo_api.runtime_access_routes import register_runtime_access_routes
from geo_core.auth import (
    AuthContractError,
    InvitationSurface,
    InvitationSurfaceCompatibility,
    build_session_scope_v2,
    effective_invitation_surfaces,
    project_scope_for_surface,
    surface_for_role,
)
from geo_core.auth_delivery import (
    AuthDeliveryError,
    AuthDeliveryKeyring,
    FrozenAuthDelivery,
    auth_session_cookie_secure,
    build_frozen_auth_delivery,
)
from geo_core.models import RuntimeProject, RuntimeProjectPage


def _encoded_key(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def test_surface_policy_is_role_scoped_and_snapshot_cannot_expand() -> None:
    assert surface_for_role("analyst") is InvitationSurface.ADMIN
    assert surface_for_role("viewer") is InvitationSurface.CUSTOMER
    assert effective_invitation_surfaces(
        role="viewer",
        issued_surfaces=["admin", "customer"],
    ) == frozenset({InvitationSurface.CUSTOMER})
    assert effective_invitation_surfaces(
        role="analyst",
        issued_surfaces=["customer"],
    ) == frozenset()


def test_session_scope_keeps_owner_and_viewer_roles_on_their_projects() -> None:
    scope = build_session_scope_v2(
        actor_id="mixed@example.com",
        tenant_id="tenant-1",
        tenant_roles=(),
        direct_memberships=[
            {"project_id": "project-owner", "role": "owner"},
            {"project_id": "project-viewer", "role": "viewer"},
        ],
        grants=[],
    )

    owner = next(item for item in scope.project_scopes if item.project_id == "project-owner")
    viewer = next(item for item in scope.project_scopes if item.project_id == "project-viewer")
    assert owner.roles == ("project_owner",)
    assert owner.portal_capabilities == ("portal.admin.access",)
    assert viewer.roles == ("client_viewer",)
    assert viewer.portal_capabilities == ("portal.customer.access",)
    assert "project.update" not in viewer.permissions
    assert project_scope_for_surface(scope, InvitationSurface.ADMIN) == (owner,)
    assert project_scope_for_surface(scope, InvitationSurface.CUSTOMER) == (viewer,)


def test_delivery_is_authenticated_stable_and_supports_key_rotation() -> None:
    expires_at = datetime.now(UTC) + timedelta(days=7)
    delivery = build_frozen_auth_delivery(
        session_cookie_name="GEO_RUNTIME_SESSION",
        session_token="session-secret",
        csrf_cookie_name="GEO_CSRF_TOKEN",
        csrf_token="csrf-secret",
        session_expires_at=expires_at,
        secure=True,
    )
    old_key = b"o" * 32
    new_key = b"n" * 32
    old_ring = AuthDeliveryKeyring(active_key_id="old", keys={"old": old_key})
    encrypted = old_ring.encrypt(delivery, attempt_id="attempt-1")
    rotated = AuthDeliveryKeyring(active_key_id="new", keys={"new": new_key, "old": old_key})

    recovered = rotated.decrypt(
        ciphertext=encrypted.ciphertext,
        key_id=encrypted.key_id,
        nonce=encrypted.nonce,
        attempt_id="attempt-1",
    )
    assert recovered.serialize() == delivery.serialize()
    assert recovered.cookie_headers == delivery.cookie_headers
    assert "HttpOnly" in recovered.cookie_headers[0]
    assert "Secure" in recovered.cookie_headers[0]
    assert "HttpOnly" not in recovered.cookie_headers[1]

    with pytest.raises(ValueError, match="authentication failed"):
        rotated.decrypt(
            ciphertext=encrypted.ciphertext,
            key_id=encrypted.key_id,
            nonce=encrypted.nonce,
            attempt_id="attempt-2",
        )


def test_keyring_reads_active_and_previous_keys_from_environment() -> None:
    ring = AuthDeliveryKeyring.from_env(
        {
            "GEO_AUTH_DELIVERY_MASTER_KEY": _encoded_key(b"a" * 32),
            "GEO_AUTH_DELIVERY_KEY_ID": "active",
            "GEO_AUTH_DELIVERY_PREVIOUS_KEYS": '{"previous":"' + _encoded_key(b"p" * 32) + '"}',
        }
    )
    delivery = FrozenAuthDelivery(
        cookie_headers=("session=value; Path=/; HttpOnly; SameSite=lax",),
        absolute_session_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert ring.encrypt(delivery, attempt_id="attempt").key_id == "active"


def test_keyring_reads_compose_secret_file_and_rejects_ambiguous_config(tmp_path: Path) -> None:
    secret_path = tmp_path / "auth-delivery-key"
    secret_path.write_text(_encoded_key(b"s" * 32), encoding="utf-8")
    ring = AuthDeliveryKeyring.from_env(
        {
            "GEO_AUTH_DELIVERY_MASTER_KEY_FILE": str(secret_path),
            "GEO_AUTH_DELIVERY_KEY_ID": "file-key",
        }
    )
    delivery = FrozenAuthDelivery(
        cookie_headers=("session=value; Path=/; HttpOnly; SameSite=lax",),
        absolute_session_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert ring.encrypt(delivery, attempt_id="attempt").key_id == "file-key"

    with pytest.raises(AuthDeliveryError, match="cannot both be configured"):
        AuthDeliveryKeyring.from_env(
            {
                "GEO_AUTH_DELIVERY_MASTER_KEY": _encoded_key(b"r" * 32),
                "GEO_AUTH_DELIVERY_MASTER_KEY_FILE": str(secret_path),
                "GEO_AUTH_DELIVERY_KEY_ID": "ambiguous",
            }
        )


def test_cookie_secure_configuration_is_strict() -> None:
    assert auth_session_cookie_secure({}) is True
    assert auth_session_cookie_secure({"GEO_RUNTIME_SESSION_COOKIE_SECURE": "false"}) is False
    with pytest.raises(AuthDeliveryError, match="explicit boolean"):
        auth_session_cookie_secure({"GEO_RUNTIME_SESSION_COOKIE_SECURE": "sometimes"})


def test_redeem_contract_rejects_client_supplied_actor() -> None:
    with pytest.raises(ValidationError):
        AuthInvitationRedeemRequest.model_validate(
            {
                "invitation_id": "21a98a17-7930-5504-a6fa-cd08990fbf07",
                "invite_token": "secret",
                "requested_surface": "customer",
                "accepted_by": "attacker@example.com",
            }
        )


def test_preflight_rate_limit_bucket_does_not_change_with_candidate_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RateRepository:
        def __init__(self) -> None:
            self.keys: list[str] = []

        def consume_auth_preflight_rate_limit(self, **kwargs: object) -> int:
            self.keys.append(str(kwargs["bucket_key"]))
            return 1

    repository = RateRepository()
    request = SimpleNamespace(headers={})
    monkeypatch.delenv("GEO_AUTH_PREFLIGHT_TRUSTED_SOURCE_HEADER", raising=False)
    monkeypatch.delenv("GEO_AUTH_PREFLIGHT_SOURCE_RATE_LIMIT", raising=False)
    monkeypatch.setenv("GEO_AUTH_PREFLIGHT_RATE_LIMIT", "20")
    for token in ("wrong-token-one", "wrong-token-two"):
        _consume_preflight_rate_limit(
            repository,
            payload=AuthInvitationPreflightRequest(
                invitation_id="21a98a17-7930-5504-a6fa-cd08990fbf07",
                invite_token=token,
                requested_surface="customer",
            ),
            request=request,  # type: ignore[arg-type]
        )
    assert len(repository.keys) == 2
    assert repository.keys[0] == repository.keys[1]


def test_preflight_trusted_source_limit_above_one_thousand_still_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RateRepository:
        def __init__(self) -> None:
            self.calls = 0

        def consume_auth_preflight_rate_limit(self, **_kwargs: object) -> int:
            self.calls += 1
            return 1 if self.calls == 1 else 1002

    monkeypatch.setenv("GEO_AUTH_PREFLIGHT_RATE_LIMIT", "20")
    monkeypatch.setenv("GEO_AUTH_PREFLIGHT_TRUSTED_SOURCE_HEADER", "X-Trusted-Client-Fingerprint")
    monkeypatch.setenv("GEO_AUTH_PREFLIGHT_SOURCE_RATE_LIMIT", "1001")
    with pytest.raises(AuthContractError) as caught:
        _consume_preflight_rate_limit(
            RateRepository(),
            payload=AuthInvitationPreflightRequest(
                invitation_id="21a98a17-7930-5504-a6fa-cd08990fbf07",
                invite_token="candidate",
                requested_surface="customer",
            ),
            request=SimpleNamespace(headers={"X-Trusted-Client-Fingerprint": "client-1"}),  # type: ignore[arg-type]
        )
    assert getattr(caught.value, "code", None) == "auth_preflight_rate_limited"


class _ProjectionRepository:
    def __init__(self) -> None:
        self.list_calls = 0

    def list_runtime_projects(self, **_kwargs: object) -> RuntimeProjectPage:
        self.list_calls += 1
        return RuntimeProjectPage(total_count=0, limit=50, offset=0, records=())


def _projection_app(context: object, repository: _ProjectionRepository) -> tuple[TestClient, list[object]]:
    app = FastAPI()
    closed: list[object] = []
    register_runtime_access_routes(
        app,
        runtime_actor_header="X-GEO-Actor-Id",
        project_manage_roles=("project_owner",),
        require_runtime_actor_id=lambda _actor: "viewer@example.com",
        assert_runtime_project_access=lambda *_args, **_kwargs: None,
        runtime_project_access_control_enabled=lambda: True,
        resolve_auth_context=lambda _actor: context,
        apply_runtime_project_db_context=lambda *_args, **_kwargs: None,
        build_repository=lambda: repository,
        close_repository=closed.append,
    )
    return TestClient(app), closed


def test_explicit_surface_with_zero_matching_scopes_returns_empty_without_legacy_fallback() -> None:
    repository = _ProjectionRepository()
    context = SimpleNamespace(
        actor_id="viewer@example.com",
        tenant_id="tenant-1",
        scope_version="runtime_session_scope_v2",
        authz_policy_version="auth_surface_policy_v1",
        project_ids=("customer-project",),
        project_scopes=(
            {
                "project_id": "customer-project",
                "portal_capabilities": ["portal.customer.access"],
            },
        ),
    )
    client, closed = _projection_app(context, repository)

    response = client.get("/v1/projects/runtime?surface=admin")

    assert response.status_code == 200
    assert response.json() == {"total_count": 0, "limit": 50, "offset": 0, "records": []}
    assert repository.list_calls == 0
    assert closed == [repository]


def test_valid_scope_v2_session_with_no_projects_returns_empty_page() -> None:
    repository = _ProjectionRepository()
    context = SimpleNamespace(
        actor_id="empty@example.com",
        tenant_id="tenant-1",
        scope_version="runtime_session_scope_v2",
        authz_policy_version="auth_surface_policy_v1",
        project_ids=(),
        project_scopes=(),
    )
    client, _closed = _projection_app(context, repository)

    response = client.get("/v1/projects/runtime?surface=customer")

    assert response.status_code == 200
    assert response.json()["records"] == []
    assert response.json()["total_count"] == 0
    assert repository.list_calls == 0


def test_surface_projection_paginates_more_than_two_hundred_scopes_without_truncation() -> None:
    class PopulatedRepository(_ProjectionRepository):
        def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
            self.list_calls += 1
            project_id = str(kwargs["project_id"])
            record = RuntimeProject(
                project={"id": project_id, "created_at": project_id},
                tenant={"id": "tenant-1"},
                brand=None,
                competitors=(),
                prompt_count=0,
                audit_events=(),
            )
            return RuntimeProjectPage(total_count=1, limit=1, offset=0, records=(record,))

    repository = PopulatedRepository()
    scopes = tuple(
        {
            "project_id": f"project-{index:03d}",
            "portal_capabilities": ["portal.customer.access"],
        }
        for index in range(205)
    )
    context = SimpleNamespace(
        actor_id="many@example.com",
        tenant_id="tenant-1",
        scope_version="runtime_session_scope_v2",
        authz_policy_version="auth_surface_policy_v1",
        project_ids=tuple(scope["project_id"] for scope in scopes),
        project_scopes=scopes,
    )
    client, _closed = _projection_app(context, repository)

    response = client.get("/v1/projects/runtime?surface=customer&limit=10&offset=200")

    assert response.status_code == 200
    assert response.json()["total_count"] == 205
    assert len(response.json()["records"]) == 5
    assert repository.list_calls == 205


def test_main_registers_one_authoritative_runtime_projects_get_with_surface_openapi() -> None:
    from geo_api.main import _runtime_session_csrf_exempt_path, app

    routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/v1/projects/runtime" and "GET" in (getattr(route, "methods", set()) or set())
    ]
    assert len(routes) == 1
    parameters = app.openapi()["paths"]["/v1/projects/runtime"]["get"]["parameters"]
    assert any(parameter.get("name") == "surface" and parameter.get("in") == "query" for parameter in parameters)
    assert _runtime_session_csrf_exempt_path("/v1/auth/invitations/preflight")
    assert _runtime_session_csrf_exempt_path("/v1/auth/invitations/redeem")


def test_customer_portal_access_rejects_legacy_invitation_mutation_fields() -> None:
    repository = _ProjectionRepository()
    context = SimpleNamespace(
        actor_id=None,
        tenant_id=None,
        scope_version=None,
        authz_policy_version=None,
        project_ids=(),
        project_scopes=(),
    )
    client, _closed = _projection_app(context, repository)

    response = client.post(
        "/v1/customer-portal/access",
        json={
            "invitation_id": "21a98a17-7930-5504-a6fa-cd08990fbf07",
            "invite_token": "secret",
            "accepted_by": "attacker@example.com",
        },
    )

    assert response.status_code == 422
    assert repository.list_calls == 0


def test_compatibility_enum_matches_frozen_wire_values() -> None:
    assert {item.value for item in InvitationSurfaceCompatibility} == {
        "compatible",
        "surface_mismatch",
        "policy_stale",
        "invalid",
    }
