"""Internal Secret Store API lifecycle, isolation, and non-disclosure contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geo_api import secret_store_runtime
from geo_api.app_factory import create_api_app
from geo_api.secret_store_contracts import CreateSecretRequest
from geo_api.secret_store_runtime import MemorySecretStoreApi
from geo_core.access.models import AccessForbidden, AccessPrincipal, MembershipRecord
from geo_core.secrets import (
    EnvelopeCipher,
    MasterKeyring,
    MemorySecretDatabase,
    MemorySecretUnitOfWorkFactory,
    SecretApplicationService,
    SecretRequestHasher,
)


NOW = datetime(2026, 7, 23, 18, 0, tzinfo=UTC)
TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("20000000-0000-0000-0000-000000000002")
REFERENCE_ID = UUID("30000000-0000-0000-0000-000000000003")
OLD_CANARY = "API_SECRET_CANARY_MUST_NEVER_LEAK_1842"
NEW_CANARY = "API_ROTATION_CANARY_MUST_NEVER_LEAK_9351"
FORBIDDEN_RESPONSE_FIELDS = {
    "secret_value",
    "plaintext",
    "ciphertext",
    "data_nonce",
    "wrap_nonce",
    "wrapped_data_key",
}


class PrincipalServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self.principal = principal

    def require_project_role(
        self,
        authentication: object,
        *,
        project_id: UUID,
        allowed_roles: frozenset[str],
    ) -> AccessPrincipal:
        del authentication
        membership = next(
            (item for item in self.principal.memberships if item.project_id == project_id),
            None,
        )
        if membership is None or membership.role not in allowed_roles:
            raise AccessForbidden("project owner or admin membership is required")
        return self.principal


@dataclass(frozen=True)
class ApiHarness:
    app: FastAPI
    services: PrincipalServices
    database: MemorySecretDatabase
    creator: AccessPrincipal
    approver: AccessPrincipal


def test_full_lifecycle_returns_only_safe_metadata_and_audits() -> None:
    harness = _harness()
    base = f"/v1/projects/{PROJECT_ID}/secrets"

    with TestClient(harness.app) as client:
        created = client.post(
            base,
            headers=_idempotency("secret-create-0001"),
            json=_create_payload(),
        )
        _assert_safe_response(created, status_code=201)
        assert created.json()["status"] == "pending"
        assert created.json()["aggregate_version"] == 1
        assert created.json()["version"] == 1

        replay = client.post(
            base,
            headers=_idempotency("secret-create-0001"),
            json=_create_payload(),
        )
        _assert_safe_response(replay, status_code=201)
        assert replay.json()["replayed"] is True
        assert replay.json()["fingerprint"] == created.json()["fingerprint"]

        verified = client.post(
            f"{base}/{REFERENCE_ID}/versions/1/verify",
            headers=_idempotency("secret-verify-0001"),
            json={"expected_version": 1},
        )
        _assert_safe_response(verified)
        assert verified.json()["aggregate_version"] == 2
        assert verified.json()["verified_at"] is not None

        self_activation = client.post(
            f"{base}/{REFERENCE_ID}/versions/1/activate",
            headers=_idempotency("secret-activate-self-0001"),
            json={"expected_version": 2},
        )
        _assert_safe_response(self_activation, status_code=403)

        harness.services.principal = harness.approver
        activated = client.post(
            f"{base}/{REFERENCE_ID}/versions/1/activate",
            headers=_idempotency("secret-activate-0001"),
            json={"expected_version": 2},
        )
        _assert_safe_response(activated)
        assert activated.json()["status"] == "active"
        assert activated.json()["aggregate_version"] == 3

        reference = client.get(f"{base}/{REFERENCE_ID}")
        _assert_safe_response(reference)
        assert reference.json()["purpose"] == "provider.openai"
        assert reference.json()["current_version"] == 1

        page = client.get(base)
        _assert_safe_response(page)
        assert page.json()["total"] == 1
        assert page.json()["items"] == [reference.json()]

        harness.services.principal = harness.creator
        staged = client.post(
            f"{base}/{REFERENCE_ID}/versions",
            headers=_idempotency("secret-rotate-stage-0002"),
            json={"secret_value": NEW_CANARY, "expected_version": 3},
        )
        _assert_safe_response(staged, status_code=201)
        assert staged.json()["version"] == 2
        assert staged.json()["aggregate_version"] == 4
        assert staged.json()["fingerprint"] != created.json()["fingerprint"]

        verified_rotation = client.post(
            f"{base}/{REFERENCE_ID}/versions/2/verify",
            headers=_idempotency("secret-verify-0002"),
            json={"expected_version": 4},
        )
        _assert_safe_response(verified_rotation)
        assert verified_rotation.json()["aggregate_version"] == 5

        harness.services.principal = harness.approver
        activated_rotation = client.post(
            f"{base}/{REFERENCE_ID}/versions/2/activate",
            headers=_idempotency("secret-activate-0002"),
            json={"expected_version": 5},
        )
        _assert_safe_response(activated_rotation)
        assert activated_rotation.json()["aggregate_version"] == 6

        revoked_old = client.post(
            f"{base}/{REFERENCE_ID}/versions/1/revoke",
            headers=_idempotency("secret-revoke-0001"),
            json={"expected_version": 6},
        )
        _assert_safe_response(revoked_old)
        assert revoked_old.json()["status"] == "revoked"
        assert revoked_old.json()["aggregate_version"] == 7

        audits = client.get(f"{base}/audit-events")
        _assert_safe_response(audits)
        actions = [item["action"] for item in audits.json()["items"]]
        assert actions == [
            "reference_created",
            "version_staged",
            "version_verified",
            "version_activated",
            "version_staged",
            "version_verified",
            "version_activated",
            "version_revoked",
        ]
        assert audits.json()["total"] == 8


def test_secret_never_enters_validation_error_log_response_or_model_repr(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = _harness()
    caplog.set_level(logging.DEBUG)
    payload = CreateSecretRequest.model_validate(_create_payload())
    assert OLD_CANARY not in repr(payload)
    assert OLD_CANARY not in str(payload)

    with TestClient(harness.app) as client:
        response = client.post(
            f"/v1/projects/{PROJECT_ID}/secrets",
            headers=_idempotency("secret-invalid-0001"),
            json={
                "reference_id": str(REFERENCE_ID),
                "secret_value": OLD_CANARY,
                "expected_version": 0,
                "unexpected": "force-validation-error",
            },
        )

    assert response.status_code == 422
    _assert_no_canary(response.text)
    _assert_no_canary(caplog.text)


def test_idempotency_conflict_and_missing_header_do_not_echo_secret() -> None:
    harness = _harness()
    path = f"/v1/projects/{PROJECT_ID}/secrets"

    with TestClient(harness.app) as client:
        first = client.post(
            path,
            headers=_idempotency("secret-create-conflict"),
            json=_create_payload(),
        )
        conflict = client.post(
            path,
            headers=_idempotency("secret-create-conflict"),
            json={**_create_payload(), "secret_value": NEW_CANARY},
        )
        missing_header = client.post(path, json=_create_payload())

    _assert_safe_response(first, status_code=201)
    _assert_safe_response(conflict, status_code=409)
    _assert_safe_response(missing_header, status_code=422)


def test_server_generates_stable_opaque_reference_for_idempotent_create() -> None:
    harness = _harness()
    path = f"/v1/projects/{PROJECT_ID}/secrets"
    payload = {
        "purpose": "model_provider.openai",
        "secret_value": OLD_CANARY,
        "expected_version": 0,
    }

    with TestClient(harness.app) as client:
        first = client.post(
            path,
            headers=_idempotency("secret-server-id-0001"),
            json=payload,
        )
        replay = client.post(
            path,
            headers=_idempotency("secret-server-id-0001"),
            json=payload,
        )

    _assert_safe_response(first, status_code=201)
    _assert_safe_response(replay, status_code=201)
    reference_id = UUID(first.json()["reference_id"])
    assert reference_id.int != 0
    assert replay.json()["reference_id"] == str(reference_id)
    assert replay.json()["replayed"] is True


def test_owner_admin_authorization_runtime_unavailability_and_customer_isolation() -> None:
    viewer_harness = _harness(role="viewer")
    internal_missing = create_api_app(
        surface="internal",
        services=PrincipalServices(_principal("owner")),  # type: ignore[arg-type]
        secret_store_application=object(),
    )
    internal_missing.state.secret_store_application = None
    customer = create_api_app(
        surface="customer",
        services=PrincipalServices(_principal("owner")),  # type: ignore[arg-type]
        secret_store_application=viewer_harness.app,
    )
    path = f"/v1/projects/{PROJECT_ID}/secrets"

    with TestClient(viewer_harness.app) as client:
        forbidden = client.get(path)
    with TestClient(internal_missing) as client:
        unavailable = client.get(path)
    with TestClient(customer) as client:
        absent = client.get(path)

    assert forbidden.status_code == 403
    assert unavailable.status_code == 503
    assert unavailable.headers["Retry-After"] == "30"
    assert absent.status_code == 404
    assert customer.state.secret_store_application is None


def test_openapi_is_internal_write_only_and_has_no_plaintext_operation() -> None:
    internal = create_api_app(surface="internal", secret_store_application=object()).openapi()
    customer = create_api_app(surface="customer", secret_store_application=object()).openapi()
    prefix = "/v1/projects/{project_id}/secrets"
    expected = {
        prefix,
        f"{prefix}/audit-events",
        f"{prefix}/{{reference_id}}",
        f"{prefix}/{{reference_id}}/versions",
        f"{prefix}/{{reference_id}}/versions/{{version}}/verify",
        f"{prefix}/{{reference_id}}/versions/{{version}}/activate",
        f"{prefix}/{{reference_id}}/versions/{{version}}/revoke",
    }

    assert expected <= set(internal["paths"])
    assert expected.isdisjoint(customer["paths"])
    assert not any(
        term in path.lower()
        for path in internal["paths"]
        if path.startswith(prefix)
        for term in ("resolve", "decrypt", "plaintext")
    )
    assert not hasattr(MemorySecretStoreApi, "resolve")

    schemas = internal["components"]["schemas"]
    for schema_name in ("CreateSecretRequest", "StageSecretRotationRequest"):
        secret_field = schemas[schema_name]["properties"]["secret_value"]
        assert secret_field["writeOnly"] is True
        assert secret_field["format"] == "password"
        assert "example" not in secret_field
        assert "examples" not in secret_field
        encoded_schema = json.dumps(schemas[schema_name], sort_keys=True)
        assert '"example"' not in encoded_schema
        assert '"examples"' not in encoded_schema

    for name in (
        "SecretVersionResponse",
        "SecretReferenceResponse",
        "SecretAuditEventResponse",
    ):
        assert FORBIDDEN_RESPONSE_FIELDS.isdisjoint(schemas[name]["properties"])

    for path in expected:
        operation = internal["paths"][path].get("post")
        if operation is None:
            continue
        idempotency = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "Idempotency-Key"
        )
        assert idempotency["required"] is True
        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema = schemas[request_ref.rsplit("/", 1)[-1]]
        assert "expected_version" in request_schema["required"]

    encoded = json.dumps(internal, sort_keys=True)
    _assert_no_canary(encoded)
    assert not any(name.startswith("Secret") for name in customer["components"]["schemas"])


def test_runtime_builder_fails_closed_without_migration_backed_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEO_DATABASE_URL", raising=False)
    monkeypatch.delenv("GEO_DATABASE_URL_FILE", raising=False)
    assert secret_store_runtime.build_secret_store_application() is None

    monkeypatch.setenv("GEO_DATABASE_URL", "postgresql://secret.invalid/geo")
    monkeypatch.setattr(secret_store_runtime.importlib, "import_module", lambda name: object())
    assert secret_store_runtime.build_secret_store_application() is None


def test_runtime_builder_passes_database_url_to_postgres_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_url = "postgresql://secret.invalid/geo"
    built = object()
    received: dict[str, str] = {}

    class PostgresModule:
        @staticmethod
        def build_secret_store_api(*, database_url: str) -> object:
            received["database_url"] = database_url
            return built

    monkeypatch.setenv("GEO_DATABASE_URL", configured_url)
    monkeypatch.delenv("GEO_DATABASE_URL_FILE", raising=False)
    monkeypatch.setattr(
        secret_store_runtime.importlib,
        "import_module",
        lambda name: PostgresModule,
    )

    assert secret_store_runtime.build_secret_store_application() is built
    assert received == {"database_url": configured_url}


def _harness(*, role: str = "owner") -> ApiHarness:
    database = MemorySecretDatabase()
    application = SecretApplicationService(
        uow_factory=MemorySecretUnitOfWorkFactory(database),
        cipher=EnvelopeCipher(MasterKeyring(keys={1: b"M" * 32}, active_version=1)),
        request_hasher=SecretRequestHasher(b"H" * 32),
        clock=lambda: NOW,
    )
    creator = _principal(role)
    approver = _principal("admin")
    services = PrincipalServices(creator)
    app = create_api_app(
        surface="internal",
        services=services,  # type: ignore[arg-type]
        secret_store_application=MemorySecretStoreApi(
            application=application,
            database=database,
        ),
    )
    return ApiHarness(app, services, database, creator, approver)


def _principal(role: str) -> AccessPrincipal:
    identity_id = uuid4()
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=TENANT_ID,
        memberships=(MembershipRecord(PROJECT_ID, TENANT_ID, role),),
        auth_method="test",
    )


def _create_payload() -> dict[str, object]:
    return {
        "reference_id": str(REFERENCE_ID),
        "purpose": "provider.openai",
        "secret_value": OLD_CANARY,
        "expected_version": 0,
    }


def _idempotency(value: str) -> dict[str, str]:
    return {"Idempotency-Key": value}


def _assert_safe_response(response: object, *, status_code: int = 200) -> None:
    assert getattr(response, "status_code") == status_code
    body = getattr(response, "text")
    _assert_no_canary(body)
    if getattr(response, "headers").get("content-type", "").startswith("application/json"):
        assert FORBIDDEN_RESPONSE_FIELDS.isdisjoint(_nested_keys(getattr(response, "json")()))


def _assert_no_canary(value: str) -> None:
    assert OLD_CANARY not in value
    assert NEW_CANARY not in value


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested
            for item in value.values()
            for nested in _nested_keys(item)
        }
    if isinstance(value, list):
        return {nested for item in value for nested in _nested_keys(item)}
    return set()
