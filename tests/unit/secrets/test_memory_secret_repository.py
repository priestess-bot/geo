from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from geo_core.secrets import (
    CreateSecretCommand,
    EnvelopeCipher,
    MasterKeyring,
    MemorySecretDatabase,
    MemorySecretUnitOfWorkFactory,
    SecretApplicationService,
    SecretConcurrencyConflict,
    SecretPrincipal,
    SecretRequestHasher,
    SecretScopeViolation,
    SecretActorRole,
    SecretSurface,
    SecretValue,
)


NOW = datetime(2026, 7, 23, 17, 0, tzinfo=UTC)


def test_concurrent_project_uow_commit_uses_optimistic_cas() -> None:
    database, factory, service, principal = _setup()
    outcome = service.create(_create_command(principal))
    first = factory.create(principal.project_id)
    second = factory.create(principal.project_id)
    first_aggregate = first.secrets.get(outcome.handle.reference_id)
    second_aggregate = second.secrets.get(outcome.handle.reference_id)
    assert first_aggregate is not None
    assert second_aggregate is not None
    first.secrets.save(
        replace(first_aggregate, aggregate_version=2),
        expected_version=1,
    )
    second.secrets.save(
        replace(second_aggregate, aggregate_version=2),
        expected_version=1,
    )

    first.commit()
    with pytest.raises(SecretConcurrencyConflict, match="transaction is stale"):
        second.commit()

    persisted = database.reference(principal.project_id, outcome.handle.reference_id)
    assert persisted is not None
    assert persisted.aggregate_version == 2


def test_uncommitted_uow_changes_are_rolled_back() -> None:
    database, factory, service, principal = _setup()
    outcome = service.create(_create_command(principal))
    with factory.create(principal.project_id) as uow:
        aggregate = uow.secrets.get(outcome.handle.reference_id)
        assert aggregate is not None
        uow.secrets.save(
            replace(aggregate, aggregate_version=2),
            expected_version=1,
        )

    persisted = database.reference(principal.project_id, outcome.handle.reference_id)
    assert persisted is not None
    assert persisted.aggregate_version == 1


def test_repository_rejects_aggregate_from_another_project() -> None:
    _, factory, service, principal = _setup()
    outcome = service.create(_create_command(principal))
    source = factory.database.reference(principal.project_id, outcome.handle.reference_id)
    assert source is not None

    with factory.create(uuid4()) as uow:
        with pytest.raises(SecretScopeViolation, match="another project"):
            uow.secrets.add(source)


def test_repository_expected_version_must_advance_exactly_once() -> None:
    _, factory, service, principal = _setup()
    outcome = service.create(_create_command(principal))
    with factory.create(principal.project_id) as uow:
        aggregate = uow.secrets.get(outcome.handle.reference_id)
        assert aggregate is not None
        with pytest.raises(SecretConcurrencyConflict, match="advance exactly once"):
            uow.secrets.save(
                replace(aggregate, aggregate_version=3),
                expected_version=1,
            )


def test_projects_have_independent_transaction_streams() -> None:
    database = MemorySecretDatabase()
    factory = MemorySecretUnitOfWorkFactory(database)
    first_project = uuid4()
    second_project = uuid4()

    first = factory.create(first_project)
    second = factory.create(second_project)
    first.commit()
    second.commit()

    assert database.transaction_version(first_project) == 1
    assert database.transaction_version(second_project) == 1


def _setup() -> tuple[
    MemorySecretDatabase,
    MemorySecretUnitOfWorkFactory,
    SecretApplicationService,
    SecretPrincipal,
]:
    database = MemorySecretDatabase()
    factory = MemorySecretUnitOfWorkFactory(database)
    principal = SecretPrincipal(
        actor_id=uuid4(),
        project_id=uuid4(),
        role=SecretActorRole.OWNER,
        surface=SecretSurface.ADMIN,
    )
    service = SecretApplicationService(
        uow_factory=factory,
        cipher=EnvelopeCipher(MasterKeyring(keys={1: b"M" * 32}, active_version=1)),
        request_hasher=SecretRequestHasher(b"H" * 32),
        clock=lambda: NOW,
    )
    return database, factory, service, principal


def _create_command(principal: SecretPrincipal) -> CreateSecretCommand:
    return CreateSecretCommand(
        principal=principal,
        reference_id=uuid4(),
        purpose="provider.openai",
        value=SecretValue("memory-repository-sensitive-value"),
        idempotency_key="memory-create-secret",
    )
