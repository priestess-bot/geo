from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from geo_core.model_gateway import (
    SecretStoreCredentialResolver,
    build_secret_store_credential_resolver,
)
from geo_core.model_gateway.provider_adapters import credentials
from geo_core.secrets import (
    ActivateSecretVersionCommand,
    CreateSecretCommand,
    EnvelopeCipher,
    MasterKeyring,
    MemorySecretDatabase,
    MemorySecretUnitOfWorkFactory,
    RevokeSecretVersionCommand,
    ResolveSecretCommand,
    SecretActorRole,
    SecretApplicationService,
    SecretConfigurationError,
    SecretNotFound,
    SecretPrincipal,
    SecretRequestHasher,
    SecretScopeViolation,
    SecretSurface,
    SecretValue,
    SecretVersionHandle,
    SecretVersionUnavailable,
    StageSecretRotationCommand,
    VerifySecretCommand,
)


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
PURPOSE = "model_provider.openai"


def test_public_builder_is_fail_closed_and_uses_public_runtime_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        credentials,
        "build_secret_store_postgres_runtime",
        lambda **_values: None,
    )
    with pytest.raises(SecretConfigurationError, match="not configured"):
        build_secret_store_credential_resolver(
            database_url="postgresql://example.invalid/geo",
            worker_actor_id=uuid4(),
        )

    application = object()
    uow_factory = object()
    monkeypatch.setattr(
        credentials,
        "build_secret_store_postgres_runtime",
        lambda **_values: SimpleNamespace(
            application=application,
            uow_factory=uow_factory,
        ),
    )
    resolver = build_secret_store_credential_resolver(
        database_url="postgresql://example.invalid/geo",
        worker_actor_id=uuid4(),
    )

    assert isinstance(resolver, SecretStoreCredentialResolver)
    assert not hasattr(resolver, "credentials")
    assert "REDACTED" in repr(resolver)


class _PausingResolveApplication:
    def __init__(self, delegate: SecretApplicationService) -> None:
        self._delegate = delegate
        self.started = Event()
        self.proceed = Event()

    def resolve(self, command: ResolveSecretCommand) -> SecretValue:
        self.started.set()
        if not self.proceed.wait(timeout=5):
            raise TimeoutError("fixture resolve was not released")
        return self._delegate.resolve(command)


def _principal(
    project_id: UUID,
    *,
    role: SecretActorRole,
    surface: SecretSurface,
) -> SecretPrincipal:
    return SecretPrincipal(
        actor_id=uuid4(),
        project_id=project_id,
        role=role,
        surface=surface,
    )


def test_resolver_uses_exact_frozen_version_across_rotation_and_revocation() -> None:
    project_id = uuid4()
    reference_id = uuid4()
    factory = MemorySecretUnitOfWorkFactory(MemorySecretDatabase())
    service = SecretApplicationService(
        uow_factory=factory,
        cipher=EnvelopeCipher(MasterKeyring(keys={1: b"K" * 32}, active_version=1)),
        request_hasher=SecretRequestHasher(b"H" * 32),
        clock=lambda: NOW,
    )
    creator = _principal(
        project_id,
        role=SecretActorRole.OWNER,
        surface=SecretSurface.ADMIN,
    )
    approver = _principal(
        project_id,
        role=SecretActorRole.ADMIN,
        surface=SecretSurface.ADMIN,
    )
    created = service.create(
        CreateSecretCommand(
            principal=creator,
            reference_id=reference_id,
            purpose=PURPOSE,
            value=SecretValue("provider-secret-v1"),
            idempotency_key="create-provider-secret-v1",
        )
    )
    service.verify(
        VerifySecretCommand(
            principal=creator,
            handle=created.handle,
            idempotency_key="verify-provider-secret-v1",
            expected_version=1,
        )
    )
    service.activate(
        ActivateSecretVersionCommand(
            principal=approver,
            handle=created.handle,
            idempotency_key="activate-provider-secret-v1",
            expected_version=2,
        )
    )
    resolver = SecretStoreCredentialResolver(
        application=service,
        uow_factory=factory,
        worker_actor_id=uuid4(),
    )

    first = resolver.resolve(created.handle)
    assert first.matches("provider-secret-v1")
    staged = service.stage_rotation(
        StageSecretRotationCommand(
            principal=creator,
            reference_id=reference_id,
            purpose=PURPOSE,
            value=SecretValue("provider-secret-v2"),
            idempotency_key="stage-provider-secret-v2",
            expected_version=3,
        )
    )
    service.verify(
        VerifySecretCommand(
            principal=creator,
            handle=staged.handle,
            idempotency_key="verify-provider-secret-v2",
            expected_version=4,
        )
    )
    service.activate(
        ActivateSecretVersionCommand(
            principal=approver,
            handle=staged.handle,
            idempotency_key="activate-provider-secret-v2",
            expected_version=5,
        )
    )

    frozen_first = resolver.resolve(created.handle)
    second = resolver.resolve(staged.handle)
    assert frozen_first.matches("provider-secret-v1")
    assert second.matches("provider-secret-v2")
    assert not second.matches("provider-secret-v1")
    service.revoke(
        RevokeSecretVersionCommand(
            principal=approver,
            handle=created.handle,
            idempotency_key="revoke-provider-secret-v1",
            expected_version=6,
        )
    )
    with pytest.raises(SecretVersionUnavailable, match="not available"):
        resolver.resolve(created.handle)
    assert resolver.resolve(staged.handle).matches("provider-secret-v2")
    assert "provider-secret" not in repr((resolver, first, frozen_first, second))


def test_resolver_rejects_project_or_purpose_scope_before_decryption() -> None:
    project_id = uuid4()
    other_project = uuid4()
    reference_id = uuid4()
    factory = MemorySecretUnitOfWorkFactory(MemorySecretDatabase())
    service = SecretApplicationService(
        uow_factory=factory,
        cipher=EnvelopeCipher(MasterKeyring(keys={1: b"K" * 32}, active_version=1)),
        request_hasher=SecretRequestHasher(b"H" * 32),
        clock=lambda: NOW,
    )
    creator = _principal(
        project_id,
        role=SecretActorRole.OWNER,
        surface=SecretSurface.ADMIN,
    )
    service.create(
        CreateSecretCommand(
            principal=creator,
            reference_id=reference_id,
            purpose=PURPOSE,
            value=SecretValue("scoped-provider-secret"),
            idempotency_key="create-scoped-provider-secret",
        )
    )
    resolver = SecretStoreCredentialResolver(
        application=service,
        uow_factory=factory,
        worker_actor_id=uuid4(),
    )

    with pytest.raises(SecretScopeViolation, match="scope"):
        resolver.resolve(
            SecretVersionHandle(
                reference_id=reference_id,
                project_id=project_id,
                purpose="model_provider.kimi",
                version=1,
            )
        )
    with pytest.raises(SecretNotFound, match="not found"):
        resolver.resolve(
            SecretVersionHandle(
                reference_id=reference_id,
                project_id=other_project,
                purpose=PURPOSE,
                version=1,
            )
        )


def test_inflight_frozen_handle_survives_rotation_but_not_concurrent_revocation() -> None:
    project_id = uuid4()
    reference_id = uuid4()
    factory = MemorySecretUnitOfWorkFactory(MemorySecretDatabase())
    service = SecretApplicationService(
        uow_factory=factory,
        cipher=EnvelopeCipher(MasterKeyring(keys={1: b"K" * 32}, active_version=1)),
        request_hasher=SecretRequestHasher(b"H" * 32),
        clock=lambda: NOW,
    )
    creator = _principal(
        project_id,
        role=SecretActorRole.OWNER,
        surface=SecretSurface.ADMIN,
    )
    approver = _principal(
        project_id,
        role=SecretActorRole.ADMIN,
        surface=SecretSurface.ADMIN,
    )
    created = service.create(
        CreateSecretCommand(
            principal=creator,
            reference_id=reference_id,
            purpose=PURPOSE,
            value=SecretValue("provider-secret-v1"),
            idempotency_key="concurrent-create-v1",
        )
    )
    service.verify(
        VerifySecretCommand(
            principal=creator,
            handle=created.handle,
            idempotency_key="concurrent-verify-v1",
            expected_version=1,
        )
    )
    service.activate(
        ActivateSecretVersionCommand(
            principal=approver,
            handle=created.handle,
            idempotency_key="concurrent-activate-v1",
            expected_version=2,
        )
    )
    staged = service.stage_rotation(
        StageSecretRotationCommand(
            principal=creator,
            reference_id=reference_id,
            purpose=PURPOSE,
            value=SecretValue("provider-secret-v2"),
            idempotency_key="concurrent-stage-v2",
            expected_version=3,
        )
    )
    service.verify(
        VerifySecretCommand(
            principal=creator,
            handle=staged.handle,
            idempotency_key="concurrent-verify-v2",
            expected_version=4,
        )
    )

    rotating_app = _PausingResolveApplication(service)
    rotating_resolver = SecretStoreCredentialResolver(
        application=rotating_app,
        uow_factory=factory,
        worker_actor_id=uuid4(),
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        old_version = pool.submit(rotating_resolver.resolve, created.handle)
        assert rotating_app.started.wait(timeout=5)
        service.activate(
            ActivateSecretVersionCommand(
                principal=approver,
                handle=staged.handle,
                idempotency_key="concurrent-activate-v2",
                expected_version=5,
            )
        )
        rotating_app.proceed.set()
        assert old_version.result(timeout=5).matches("provider-secret-v1")

        revoking_app = _PausingResolveApplication(service)
        revoking_resolver = SecretStoreCredentialResolver(
            application=revoking_app,
            uow_factory=factory,
            worker_actor_id=uuid4(),
        )
        revoked_version = pool.submit(revoking_resolver.resolve, created.handle)
        assert revoking_app.started.wait(timeout=5)
        service.revoke(
            RevokeSecretVersionCommand(
                principal=approver,
                handle=created.handle,
                idempotency_key="concurrent-revoke-v1",
                expected_version=6,
            )
        )
        revoking_app.proceed.set()
        with pytest.raises(SecretVersionUnavailable, match="not available"):
            revoked_version.result(timeout=5)
