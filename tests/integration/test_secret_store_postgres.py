from __future__ import annotations

import base64
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.model_gateway import build_secret_store_credential_resolver
from geo_core.project_scope import set_project_scope
from geo_core.secrets import (
    EnvelopeCipher,
    MasterKeyring,
    SecretActorRole,
    SecretAuthorizationError,
    SecretDecryptionError,
    SecretIdempotencyConflict,
    SecretPrincipal,
    SecretRequestHasher,
    SecretStateConflict,
    SecretSurface,
    SecretValue,
)
from geo_core.secrets.postgres import (
    PostgresSecretMaintenance,
    PostgresSecretUnitOfWorkFactory,
    build_secret_store_api,
    retire_master_key_version,
    verify_secret_store_restore,
)
from geo_core.secrets.models import SecretVersionHandle
from geo_core.synthetic_lab.postgres_style_secret_resolver import (
    STYLE_COLLECTION_WORKER_SERVICE_NAME,
    build_audited_style_secret_resolver,
)
from geo_worker.service_identity import (
    MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ENV,
    MODEL_GATEWAY_WORKER_SERVICE_NAME,
    require_model_gateway_worker_identity,
)
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
KEY_ONE = b"K" * 32
KEY_TWO = b"N" * 32
HASH_KEY = b"H" * 32
OLD_VALUE = "POSTGRES_SECRET_VALUE_OLD_1842"
NEW_VALUE = "POSTGRES_SECRET_VALUE_NEW_9351"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_secret_store_postgres_lifecycle_rotation_rewrap_and_rls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_secret_test_{suffix}"
    test_admin_url = _database_url(ADMIN_URL, database_name)
    app_login, password = f"geo_secret_store_{suffix}", uuid4().hex
    worker_login, worker_password = f"geo_style_worker_{suffix}", uuid4().hex
    keyring_one = _keyring_file(tmp_path / "keyring-v1", {1: KEY_ONE}, active=1)
    hash_file = _hash_file(tmp_path / "request-hash-key")
    reference_id = uuid4()
    app_role_created = False
    worker_role_created = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        migration_config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration_config.attributes["geo_database_url_override"] = test_admin_url
        command.upgrade(migration_config, "head")
        with psycopg.connect(test_admin_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(password)
                )
            )
            app_role_created = True
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(worker_password)
                )
            )
            worker_role_created = True
            first = seed_project(admin, suffix=f"secret-store-{suffix}-a")
            second = seed_project(admin, suffix=f"secret-store-{suffix}-b")
        app_url = login_url(test_admin_url, user=app_login, password=password)
        worker_url = login_url(
            test_admin_url,
            user=worker_login,
            password=worker_password,
        )
        owner = _principal(first, "owner")
        approver = _principal(first, "reviewer")
        api = build_secret_store_api(
            database_url=app_url,
            master_keyring_path=keyring_one,
            request_hash_key_path=hash_file,
        )
        assert api is not None
        empty_restore = verify_secret_store_restore(
            database_url=test_admin_url, keyring_path=keyring_one
        )
        assert empty_restore.verified_key_versions == (1,)
        assert empty_restore.representative_secret_count == 0
        wrong_keyring = _keyring_file(
            tmp_path / "keyring-wrong", {1: b"W" * 32}, active=1
        )
        with pytest.raises(SecretDecryptionError, match="canary authentication failed"):
            verify_secret_store_restore(
                database_url=test_admin_url, keyring_path=wrong_keyring
            )
        created = api.create(
            owner,
            project_id=first["project"],
            reference_id=reference_id,
            purpose="provider.openai",
            value=SecretValue(OLD_VALUE),
            expected_version=0,
            idempotency_key="create-provider-openai-v1",
        )
        replay = api.create(
            owner,
            project_id=first["project"],
            reference_id=reference_id,
            purpose="provider.openai",
            value=SecretValue(OLD_VALUE),
            expected_version=0,
            idempotency_key="create-provider-openai-v1",
        )
        assert created.status == "pending"
        assert replay.replayed is True
        _assert_direct_activation_and_actor_rewrite_are_rejected(
            app_url=app_url,
            project_id=first["project"],
            reference_id=reference_id,
            creator_id=first["owner"],
            approver_id=first["reviewer"],
            api=api,
            owner=owner,
        )

        with pytest.raises(SecretAuthorizationError, match="creator cannot activate"):
            api.activate(
                owner,
                project_id=first["project"],
                reference_id=reference_id,
                version=1,
                expected_version=2,
                idempotency_key="activate-v1-by-creator",
            )
        active_v1 = api.activate(
            approver,
            project_id=first["project"],
            reference_id=reference_id,
            version=1,
            expected_version=2,
            idempotency_key="activate-provider-openai-v1",
        )
        staged_v2 = api.stage_rotation(
            owner,
            project_id=first["project"],
            reference_id=reference_id,
            value=SecretValue(NEW_VALUE),
            expected_version=3,
            idempotency_key="stage-provider-openai-v2",
        )
        api.verify(
            owner,
            project_id=first["project"],
            reference_id=reference_id,
            version=2,
            expected_version=4,
            idempotency_key="verify-provider-openai-v2",
        )
        active_v2 = api.activate(
            approver,
            project_id=first["project"],
            reference_id=reference_id,
            version=2,
            expected_version=5,
            idempotency_key="activate-provider-openai-v2",
        )
        assert active_v1.status == "active"
        assert staged_v2.version == 2
        assert active_v2.aggregate_version == 6
        assert api.list_references(
            owner, project_id=first["project"], limit=20, offset=0
        ).total == 1
        assert api.list_audits(
            owner, project_id=first["project"], limit=50, offset=0
        ).total == 7
        _assert_no_plaintext_and_rls(
            app_url=app_url,
            first_project=first["project"],
            second_project=second["project"],
        )
        style_login_handle = _assert_style_collection_service_identity_resolution(
            api=api,
            owner=owner,
            approver=approver,
            project_id=first["project"],
            test_admin_url=test_admin_url,
            worker_url=worker_url,
            keyring_path=keyring_one,
            request_hash_path=hash_file,
            monkeypatch=monkeypatch,
        )
        _assert_model_gateway_service_identity_resolution(
            project_id=first["project"],
            reference_id=reference_id,
            test_admin_url=test_admin_url,
            worker_url=worker_url,
            keyring_path=keyring_one,
            request_hash_path=hash_file,
            monkeypatch=monkeypatch,
        )

        keyring_two = _keyring_file(
            tmp_path / "keyring-v2", {1: KEY_ONE, 2: KEY_TWO}, active=2
        )
        assert build_secret_store_api(
            database_url=app_url,
            master_keyring_path=keyring_two,
            request_hash_key_path=hash_file,
        ) is not None
        _assert_direct_rewrap_without_receipt_is_rejected(
            app_url=app_url,
            project_id=first["project"],
            reference_id=reference_id,
        )

        factory = PostgresSecretUnitOfWorkFactory(app_url)
        cipher = EnvelopeCipher(
            MasterKeyring(keys={1: KEY_ONE, 2: KEY_TWO}, active_version=2)
        )
        maintenance = PostgresSecretMaintenance(
            uow_factory=factory,
            cipher=cipher,
            request_hasher=SecretRequestHasher(HASH_KEY),
        )
        admin_principal = SecretPrincipal(
            actor_id=first["reviewer"],
            project_id=first["project"],
            role=SecretActorRole.ADMIN,
            surface=SecretSurface.ADMIN,
        )
        first_handle = _handle(factory, first["project"], reference_id, 1)
        second_handle = _handle(factory, first["project"], reference_id, 2)
        first_rewrap = maintenance.rewrap(
            admin_principal,
            handle=first_handle,
            idempotency_key="rewrap-provider-openai-v1",
        )
        replayed_rewrap = maintenance.rewrap(
            admin_principal,
            handle=first_handle,
            idempotency_key="rewrap-provider-openai-v1",
        )
        assert first_rewrap.replayed is False
        assert replayed_rewrap.replayed is True
        with pytest.raises(SecretIdempotencyConflict):
            maintenance.rewrap(
                admin_principal,
                handle=second_handle,
                idempotency_key="rewrap-provider-openai-v1",
            )
        with psycopg.connect(app_url) as connection:
            with pytest.raises(SecretStateConflict, match="could not be retired"):
                retire_master_key_version(
                    connection,
                    master_key_version=1,
                    retired_at=datetime.now(UTC),
                )
            connection.rollback()

        maintenance.rewrap(
            admin_principal,
            handle=second_handle,
            idempotency_key="rewrap-provider-openai-v2",
        )
        style_rewrap = maintenance.rewrap(
            admin_principal,
            handle=style_login_handle,
            idempotency_key="rewrap-style-login-v1",
        )
        assert style_rewrap.replayed is False
        with psycopg.connect(app_url) as connection:
            retire_master_key_version(
                connection,
                master_key_version=1,
                retired_at=datetime.now(UTC),
            )
            assert connection.execute(
                """SELECT status FROM secret_master_key_versions
                   WHERE master_key_version = 1"""
            ).fetchone()[0] == "retired"
            connection.commit()
        active_keyring = _keyring_file(
            tmp_path / "keyring-active-only", {2: KEY_TWO}, active=2
        )
        restored = verify_secret_store_restore(
            database_url=test_admin_url, keyring_path=active_keyring
        )
        assert restored.verified_key_versions == (2,)
        assert restored.representative_secret_count == 1
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )
            if worker_role_created:
                server.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login))
                )
            if app_role_created:
                server.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login))
                )


def _assert_style_collection_service_identity_resolution(
    *,
    api,
    owner: AccessPrincipal,
    approver: AccessPrincipal,
    project_id: UUID,
    test_admin_url: str,
    worker_url: str,
    keyring_path: Path,
    request_hash_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> SecretVersionHandle:
    reference_id = uuid4()
    purpose = "style_collection_login.reddit"
    api.create(
        owner,
        project_id=project_id,
        reference_id=reference_id,
        purpose=purpose,
        value=SecretValue("STYLE_COLLECTION_LOGIN_SECRET_7284"),
        expected_version=0,
        idempotency_key="create-style-login-v1",
    )
    api.verify(
        owner,
        project_id=project_id,
        reference_id=reference_id,
        version=1,
        expected_version=1,
        idempotency_key="verify-style-login-v1",
    )
    activated = api.activate(
        approver,
        project_id=project_id,
        reference_id=reference_id,
        version=1,
        expected_version=2,
        idempotency_key="activate-style-login-v1",
    )
    assert activated.status == "active"

    service_identity_id = uuid4()
    with psycopg.connect(test_admin_url) as connection:
        provisioned = connection.execute(
            "SELECT geo_provision_service_identity(%s, %s, clock_timestamp())",
            (service_identity_id, STYLE_COLLECTION_WORKER_SERVICE_NAME),
        ).fetchone()
    assert provisioned is not None and provisioned[0] == service_identity_id

    monkeypatch.setenv("GEO_SECRET_STORE_MASTER_KEYRING_FILE", str(keyring_path))
    monkeypatch.setenv("GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE", str(request_hash_path))
    with pytest.raises(RuntimeError, match="service identity is not active"):
        build_audited_style_secret_resolver(
            database_url=worker_url,
            service_identity_id=uuid4(),
        )

    resolver = build_audited_style_secret_resolver(
        database_url=worker_url,
        service_identity_id=service_identity_id,
    )
    resolved = resolver.resolve(
        SecretVersionHandle(
            reference_id=reference_id,
            project_id=project_id,
            purpose=purpose,
            version=1,
        )
    )
    assert resolved.matches("STYLE_COLLECTION_LOGIN_SECRET_7284")
    with psycopg.connect(worker_url) as connection:
        set_project_scope(connection, project_id)
        row = connection.execute(
            """SELECT actor_id FROM secret_audit_events
               WHERE project_id = %s AND reference_id = %s
                 AND action = 'version_resolved'
               ORDER BY occurred_at DESC LIMIT 1""",
            (project_id, reference_id),
        ).fetchone()
    assert row is not None and row[0] == service_identity_id
    return SecretVersionHandle(
        reference_id=reference_id,
        project_id=project_id,
        purpose=purpose,
        version=1,
    )


def _assert_model_gateway_service_identity_resolution(
    *,
    project_id: UUID,
    reference_id: UUID,
    test_admin_url: str,
    worker_url: str,
    keyring_path: Path,
    request_hash_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_identity_id = uuid4()
    name_mismatch_identity_id = uuid4()
    with psycopg.connect(test_admin_url) as connection:
        provisioned = connection.execute(
            "SELECT geo_provision_service_identity(%s, %s, clock_timestamp())",
            (service_identity_id, MODEL_GATEWAY_WORKER_SERVICE_NAME),
        ).fetchone()
        connection.execute(
            "SELECT geo_provision_service_identity(%s, %s, clock_timestamp())",
            (name_mismatch_identity_id, "different_model_worker"),
        )
    assert provisioned is not None and provisioned[0] == service_identity_id

    monkeypatch.setenv("GEO_SECRET_STORE_MASTER_KEYRING_FILE", str(keyring_path))
    monkeypatch.setenv("GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE", str(request_hash_path))
    monkeypatch.setenv(
        MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ENV, str(uuid4())
    )
    with pytest.raises(RuntimeError, match="service identity is not active"):
        require_model_gateway_worker_identity(database_url=worker_url)

    monkeypatch.setenv(
        MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ENV, str(name_mismatch_identity_id)
    )
    with pytest.raises(RuntimeError, match="service identity is not active"):
        require_model_gateway_worker_identity(database_url=worker_url)

    monkeypatch.setenv(
        MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ENV, str(service_identity_id)
    )
    assert require_model_gateway_worker_identity(database_url=worker_url) == service_identity_id
    resolver = build_secret_store_credential_resolver(
        database_url=worker_url,
        master_keyring_path=keyring_path,
        request_hash_key_path=request_hash_path,
        worker_actor_id=service_identity_id,
    )
    resolved = resolver.resolve(
        SecretVersionHandle(
            reference_id=reference_id,
            project_id=project_id,
            purpose="provider.openai",
            version=2,
        )
    )
    assert resolved.matches(NEW_VALUE)
    with psycopg.connect(worker_url) as connection:
        set_project_scope(connection, project_id)
        row = connection.execute(
            """SELECT actor_id FROM secret_audit_events
               WHERE project_id = %s AND reference_id = %s
                 AND version = 2 AND action = 'version_resolved'
               ORDER BY occurred_at DESC LIMIT 1""",
            (project_id, reference_id),
        ).fetchone()
    assert row is not None and row[0] == service_identity_id

    with psycopg.connect(test_admin_url) as connection:
        connection.execute(
            "UPDATE service_identities SET status = 'disabled' WHERE identity_id = %s",
            (service_identity_id,),
        )
    with pytest.raises(RuntimeError, match="service identity is not active"):
        require_model_gateway_worker_identity(database_url=worker_url)


def _assert_direct_activation_and_actor_rewrite_are_rejected(
    *,
    app_url: str,
    project_id: UUID,
    reference_id: UUID,
    creator_id: UUID,
    approver_id: UUID,
    api,
    owner: AccessPrincipal,
) -> None:
    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, project_id)
        with pytest.raises(psycopg.Error, match="lifecycle transition is invalid"):
            connection.execute(
                """UPDATE secret_versions
                   SET status = 'active', verified_by = %s,
                       verified_at = clock_timestamp(), activated_by = %s,
                       activated_at = clock_timestamp()
                   WHERE project_id = %s AND reference_id = %s AND version = 1""",
                (creator_id, approver_id, project_id, reference_id),
            )
        connection.rollback()
    api.verify(
        owner,
        project_id=project_id,
        reference_id=reference_id,
        version=1,
        expected_version=1,
        idempotency_key="verify-provider-openai-v1",
    )
    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, project_id)
        with pytest.raises(psycopg.Error, match="lifecycle transition is invalid"):
            connection.execute(
                """UPDATE secret_versions SET verified_by = %s
                   WHERE project_id = %s AND reference_id = %s AND version = 1""",
                (approver_id, project_id, reference_id),
            )
        connection.rollback()


def _assert_direct_rewrap_without_receipt_is_rejected(
    *, app_url: str, project_id: UUID, reference_id: UUID
) -> None:
    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, project_id)
        connection.execute(
            """UPDATE secret_versions
               SET wrapped_data_key = %s, wrap_nonce = %s, master_key_version = 2
               WHERE project_id = %s AND reference_id = %s AND version = 1""",
            (os.urandom(48), os.urandom(12), project_id, reference_id),
        )
        with pytest.raises(
            psycopg.Error, match="rewrap requires matching receipt and audit lineage"
        ):
            connection.commit()
        connection.rollback()


def _assert_no_plaintext_and_rls(
    *, app_url: str, first_project: UUID, second_project: UUID
) -> None:
    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, first_project)
        rows = connection.execute(
            "SELECT ciphertext FROM secret_versions ORDER BY version"
        ).fetchall()
        assert len(rows) == 2
        visible = b"".join(bytes(row[0]) for row in rows)
        assert OLD_VALUE.encode() not in visible
        assert NEW_VALUE.encode() not in visible
    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, second_project)
        assert connection.execute(
            "SELECT count(*) FROM secret_references"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM secret_command_receipts"
        ).fetchone()[0] == 0


def _handle(
    factory: PostgresSecretUnitOfWorkFactory,
    project_id: UUID,
    reference_id: UUID,
    version: int,
):
    with factory.create(project_id) as unit_of_work:
        aggregate = unit_of_work.secrets.get(reference_id)
    assert aggregate is not None
    return aggregate.require_version(version).handle


def _principal(ids: dict[str, UUID], identity: str) -> AccessPrincipal:
    identity_id = ids[identity]
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=ids["tenant"],
        memberships=(MembershipRecord(ids["project"], ids["tenant"], "admin"),),
        auth_method="integration",
    )


def _keyring_file(path: Path, keys: dict[int, bytes], *, active: int) -> Path:
    path.write_text(
        json.dumps(
            {
                "format": "geo-master-keyring-v1",
                "active_version": active,
                "keys": {
                    str(version): base64.b64encode(key).decode("ascii")
                    for version, key in keys.items()
                },
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _hash_file(path: Path) -> Path:
    path.write_text(base64.b64encode(HASH_KEY).decode("ascii"), encoding="ascii")
    path.chmod(0o600)
    return path


def _database_url(database_url: str, database_name: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(parsed._replace(path=f"/{database_name}"))
