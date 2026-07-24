from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
import json
import pickle
from uuid import UUID, uuid4

import pytest

from geo_core.secrets import (
    ActivateSecretVersionCommand,
    CreateSecretCommand,
    EnvelopeCipher,
    MasterKeyring,
    MemorySecretDatabase,
    MemorySecretUnitOfWorkFactory,
    ResolveSecretCommand,
    RevokeSecretVersionCommand,
    SecretActorRole,
    SecretApplicationService,
    SecretAuditAction,
    SecretAuthorizationError,
    SecretConcurrencyConflict,
    SecretCommandOutcome,
    SecretIdempotencyConflict,
    SecretLifecycleError,
    SecretNotFound,
    SecretOperation,
    SecretPrincipal,
    SecretRequestHasher,
    SecretScopeViolation,
    SecretSerializationRejected,
    SecretSurface,
    SecretValue,
    SecretVersionHandle,
    SecretVersionStatus,
    StageSecretRotationCommand,
    VerifySecretCommand,
    reject_secret_bearing_payload,
)


NOW = datetime(2026, 7, 23, 16, 30, tzinfo=UTC)
MASTER_KEY = b"M" * 32
REQUEST_HASH_KEY = b"H" * 32
OLD_SECRET = "provider-secret-old-SENSITIVE-1842"
NEW_SECRET = "provider-secret-new-SENSITIVE-9351"


@dataclass(frozen=True)
class Harness:
    service: SecretApplicationService
    factory: MemorySecretUnitOfWorkFactory
    database: MemorySecretDatabase
    project_id: UUID
    creator: SecretPrincipal
    approver: SecretPrincipal
    internal: SecretPrincipal


def test_rewrap_operation_has_a_stable_persistence_value() -> None:
    assert SecretOperation.REWRAP.value == "rewrap"
    assert SecretOperation("rewrap") is SecretOperation.REWRAP


def test_full_two_person_lifecycle_preserves_pinned_old_version_until_revoke() -> None:
    harness = _harness()
    created = _create(harness)
    assert created.status is SecretVersionStatus.PENDING
    assert created.aggregate_version == 1

    verified = harness.service.verify(
        VerifySecretCommand(
            principal=harness.creator,
            handle=created.handle,
            idempotency_key="verify-version-one",
            expected_version=1,
        )
    )
    assert verified.aggregate_version == 2

    with pytest.raises(SecretAuthorizationError, match="creator cannot activate"):
        harness.service.activate(
            ActivateSecretVersionCommand(
                principal=harness.creator,
                handle=created.handle,
                idempotency_key="self-activate-one",
                expected_version=2,
            )
        )
    assert len(harness.database.audit_events(harness.project_id)) == 3

    activated = harness.service.activate(
        ActivateSecretVersionCommand(
            principal=harness.approver,
            handle=created.handle,
            idempotency_key="activate-version-one",
            expected_version=2,
        )
    )
    assert activated.status is SecretVersionStatus.ACTIVE
    assert harness.service.resolve(
        ResolveSecretCommand(
            principal=harness.internal,
            handle=created.handle,
            idempotency_key="resolve-version-one",
        )
    ).matches(OLD_SECRET)

    staged = harness.service.stage_rotation(
        StageSecretRotationCommand(
            principal=harness.creator,
            reference_id=created.handle.reference_id,
            purpose=created.handle.purpose,
            value=SecretValue(NEW_SECRET),
            idempotency_key="stage-version-two",
            expected_version=3,
        )
    )
    assert staged.handle.version == 2
    harness.service.verify(
        VerifySecretCommand(
            principal=harness.creator,
            handle=staged.handle,
            idempotency_key="verify-version-two",
            expected_version=4,
        )
    )
    rotated = harness.service.activate(
        ActivateSecretVersionCommand(
            principal=harness.approver,
            handle=staged.handle,
            idempotency_key="activate-version-two",
            expected_version=5,
        )
    )
    assert rotated.aggregate_version == 6
    aggregate = harness.database.reference(
        harness.project_id, created.handle.reference_id
    )
    assert aggregate is not None
    assert aggregate.current_version == 2
    assert aggregate.require_version(1).status is SecretVersionStatus.SUPERSEDED
    assert harness.service.resolve(
        ResolveSecretCommand(
            principal=harness.internal,
            handle=created.handle,
            idempotency_key="resolve-pinned-old-after-rotation",
        )
    ).matches(OLD_SECRET)
    assert harness.service.resolve(
        ResolveSecretCommand(
            principal=harness.internal,
            handle=staged.handle,
            idempotency_key="resolve-current-version-two",
        )
    ).matches(NEW_SECRET)

    revoked = harness.service.revoke(
        RevokeSecretVersionCommand(
            principal=harness.approver,
            handle=created.handle,
            idempotency_key="revoke-version-one",
            expected_version=6,
        )
    )
    assert revoked.status is SecretVersionStatus.REVOKED
    with pytest.raises(SecretLifecycleError, match="unavailable"):
        harness.service.resolve(
            ResolveSecretCommand(
                principal=harness.internal,
                handle=created.handle,
                idempotency_key="resolve-revoked-old",
            )
        )


def test_create_replay_is_stable_and_does_not_duplicate_state_or_audit() -> None:
    harness = _harness()
    command = _create_command(harness, idempotency_key="create-replay-key")

    first = harness.service.create(command)
    second = harness.service.create(command)

    assert first.replayed is False
    assert second.replayed is True
    assert second.handle == first.handle
    assert second.aggregate_version == first.aggregate_version
    assert len(harness.database.audit_events(harness.project_id)) == 2
    assert len(harness.database.command_records(harness.project_id)) == 1
    assert harness.database.transaction_version(harness.project_id) == 1


def test_state_change_replay_does_not_repeat_transition_or_audit() -> None:
    harness = _harness()
    created = _create(harness)
    command = VerifySecretCommand(
        principal=harness.creator,
        handle=created.handle,
        idempotency_key="verify-replay-key",
        expected_version=1,
    )

    first = harness.service.verify(command)
    second = harness.service.verify(command)

    assert first.replayed is False
    assert second.replayed is True
    assert second.aggregate_version == 2
    assert len(harness.database.audit_events(harness.project_id)) == 3
    aggregate = harness.database.reference(harness.project_id, created.handle.reference_id)
    assert aggregate is not None
    assert aggregate.aggregate_version == 2


def test_idempotency_key_reuse_with_different_secret_fails_without_leakage() -> None:
    harness = _harness()
    first = _create_command(harness, idempotency_key="same-idempotency-key")
    harness.service.create(first)
    conflicting = replace(first, value=SecretValue(NEW_SECRET))

    with pytest.raises(SecretIdempotencyConflict) as caught:
        harness.service.create(conflicting)

    assert OLD_SECRET not in str(caught.value)
    assert NEW_SECRET not in str(caught.value)
    records = harness.database.command_records(harness.project_id)
    assert len(records) == 1
    rendered = repr(records)
    assert OLD_SECRET not in rendered
    assert NEW_SECRET not in rendered
    assert "same-idempotency-key" not in rendered


def test_idempotency_replay_is_bound_to_the_original_actor() -> None:
    harness = _harness()
    command = _create_command(harness, idempotency_key="actor-bound-idempotency")
    harness.service.create(command)

    with pytest.raises(SecretIdempotencyConflict, match="request hash"):
        harness.service.create(replace(command, principal=harness.approver))


def test_stale_expected_version_rejects_without_partial_audit_or_state() -> None:
    harness = _harness()
    created = _create(harness)
    before = harness.database.audit_events(harness.project_id)

    with pytest.raises(SecretConcurrencyConflict, match="stale"):
        harness.service.verify(
            VerifySecretCommand(
                principal=harness.creator,
                handle=created.handle,
                idempotency_key="verify-stale-version",
                expected_version=99,
            )
        )

    aggregate = harness.database.reference(harness.project_id, created.handle.reference_id)
    assert aggregate is not None
    assert aggregate.aggregate_version == 1
    assert aggregate.require_version(1).verified_at is None
    assert harness.database.audit_events(harness.project_id) == before


def test_boolean_is_not_accepted_as_an_expected_version() -> None:
    harness = _harness()
    created = _create(harness)

    with pytest.raises(SecretConcurrencyConflict, match="stale"):
        harness.service.verify(
            VerifySecretCommand(
                principal=harness.creator,
                handle=created.handle,
                idempotency_key="verify-boolean-version",
                expected_version=True,
            )
        )


@pytest.mark.parametrize(
    ("role", "surface"),
    [
        (SecretActorRole.VIEWER, SecretSurface.ADMIN),
        (SecretActorRole.SERVICE, SecretSurface.INTERNAL_API),
        (SecretActorRole.CUSTOMER, SecretSurface.CUSTOMER),
    ],
)
def test_mutations_require_owner_or_admin_on_admin_surface(
    role: SecretActorRole,
    surface: SecretSurface,
) -> None:
    harness = _harness()
    unauthorized = SecretPrincipal(
        actor_id=uuid4(),
        project_id=harness.project_id,
        role=role,
        surface=surface,
    )

    with pytest.raises(SecretAuthorizationError, match="owner or admin"):
        harness.service.create(
            replace(_create_command(harness), principal=unauthorized)
        )


def test_plaintext_resolution_is_internal_only() -> None:
    harness = _harness()
    handle = _activate_initial(harness)
    customer = SecretPrincipal(
        actor_id=uuid4(),
        project_id=harness.project_id,
        role=SecretActorRole.CUSTOMER,
        surface=SecretSurface.CUSTOMER,
    )
    admin_surface = replace(harness.approver, surface=SecretSurface.ADMIN)

    for principal in (customer, admin_surface):
        with pytest.raises(SecretAuthorizationError, match="internal consumers"):
            harness.service.resolve(
                ResolveSecretCommand(
                    principal=principal,
                    handle=handle,
                    idempotency_key=f"resolve-denied-{principal.role.value}",
                )
            )


def test_reference_metadata_is_safe_and_customer_cannot_read_it() -> None:
    harness = _harness()
    created = _create(harness)

    metadata = harness.service.reference_metadata(
        principal=harness.creator,
        reference_id=created.handle.reference_id,
    )
    rendered = json.dumps(asdict(metadata), default=str, sort_keys=True)

    assert metadata.status == "pending"
    assert metadata.current_version is None
    assert OLD_SECRET not in rendered
    assert "ciphertext" not in rendered
    assert "nonce" not in rendered
    assert "master_key" not in rendered
    assert "created_by" not in rendered

    customer = SecretPrincipal(
        actor_id=uuid4(),
        project_id=harness.project_id,
        role=SecretActorRole.CUSTOMER,
        surface=SecretSurface.CUSTOMER,
    )
    with pytest.raises(SecretAuthorizationError):
        harness.service.reference_metadata(
            principal=customer,
            reference_id=created.handle.reference_id,
        )


def test_cross_project_handle_and_reference_access_fail_closed() -> None:
    harness = _harness()
    handle = _activate_initial(harness)
    another_project = uuid4()
    other_internal = replace(harness.internal, project_id=another_project)
    forged = replace(handle, project_id=another_project)

    with pytest.raises(SecretScopeViolation, match="another project"):
        harness.service.resolve(
            ResolveSecretCommand(
                principal=harness.internal,
                handle=forged,
                idempotency_key="cross-project-forged-handle",
            )
        )
    with pytest.raises(SecretNotFound):
        harness.service.resolve(
            ResolveSecretCommand(
                principal=other_internal,
                handle=forged,
                idempotency_key="cross-project-missing-reference",
            )
        )


def test_resolve_replay_returns_value_without_duplicate_audit() -> None:
    harness = _harness()
    handle = _activate_initial(harness)
    command = ResolveSecretCommand(
        principal=harness.internal,
        handle=handle,
        idempotency_key="resolve-replay-key",
    )

    first = harness.service.resolve(command)
    audit_count = len(harness.database.audit_events(harness.project_id))
    second = harness.service.resolve(command)

    assert first.matches(OLD_SECRET)
    assert second.matches(OLD_SECRET)
    assert len(harness.database.audit_events(harness.project_id)) == audit_count


def test_revoking_current_version_clears_pointer_and_blocks_resolution() -> None:
    harness = _harness()
    handle = _activate_initial(harness)

    harness.service.revoke(
        RevokeSecretVersionCommand(
            principal=harness.approver,
            handle=handle,
            idempotency_key="revoke-current-version",
            expected_version=3,
        )
    )

    aggregate = harness.database.reference(harness.project_id, handle.reference_id)
    assert aggregate is not None
    assert aggregate.current_version is None
    assert aggregate.require_version(1).status is SecretVersionStatus.REVOKED
    assert harness.service.reference_metadata(
        principal=harness.approver,
        reference_id=handle.reference_id,
    ).status == "revoked"
    with pytest.raises(SecretLifecycleError, match="unavailable"):
        harness.service.resolve(
            ResolveSecretCommand(
                principal=harness.internal,
                handle=handle,
                idempotency_key="resolve-revoked-current",
            )
        )


def test_secret_commands_and_repository_state_are_rejected_from_payloads() -> None:
    harness = _harness()
    command = _create_command(harness)
    handle = harness.service.create(command).handle

    aggregate = harness.database.reference(harness.project_id, handle.reference_id)
    assert aggregate is not None
    for sensitive in (
        command,
        SecretRequestHasher(REQUEST_HASH_KEY),
        harness.database,
        harness.service,
        aggregate,
    ):
        with pytest.raises(SecretSerializationRejected, match="cannot enter"):
            reject_secret_bearing_payload({"artifact": sensitive})
    with pytest.raises(SecretSerializationRejected, match="cannot be serialized"):
        pickle.dumps(command)

    safe_payload = handle.as_job_payload()
    reject_secret_bearing_payload(safe_payload)
    assert OLD_SECRET not in json.dumps(safe_payload)
    assert set(safe_payload) == {
        "secret_reference_id",
        "secret_project_id",
        "secret_purpose",
        "secret_version",
    }


def test_audit_and_idempotency_records_commit_with_state() -> None:
    harness = _harness()
    created = _create(harness)
    events = harness.database.audit_events(harness.project_id)
    records = harness.database.command_records(harness.project_id)

    assert [event.action for event in events] == [
        SecretAuditAction.REFERENCE_CREATED,
        SecretAuditAction.VERSION_STAGED,
    ]
    assert all(event.reference_id == created.handle.reference_id for event in events)
    assert len(records) == 1
    assert records[0].outcome.handle == created.handle
    assert records[0].idempotency_key_hash != "create-initial-secret"


def _harness() -> Harness:
    project_id = uuid4()
    database = MemorySecretDatabase()
    factory = MemorySecretUnitOfWorkFactory(database)
    service = SecretApplicationService(
        uow_factory=factory,
        cipher=EnvelopeCipher(MasterKeyring(keys={1: MASTER_KEY}, active_version=1)),
        request_hasher=SecretRequestHasher(REQUEST_HASH_KEY),
        clock=lambda: NOW,
    )
    return Harness(
        service=service,
        factory=factory,
        database=database,
        project_id=project_id,
        creator=SecretPrincipal(
            actor_id=uuid4(),
            project_id=project_id,
            role=SecretActorRole.OWNER,
            surface=SecretSurface.ADMIN,
        ),
        approver=SecretPrincipal(
            actor_id=uuid4(),
            project_id=project_id,
            role=SecretActorRole.ADMIN,
            surface=SecretSurface.ADMIN,
        ),
        internal=SecretPrincipal(
            actor_id=uuid4(),
            project_id=project_id,
            role=SecretActorRole.SERVICE,
            surface=SecretSurface.WORKER,
        ),
    )


def _create_command(
    harness: Harness,
    *,
    idempotency_key: str = "create-initial-secret",
) -> CreateSecretCommand:
    return CreateSecretCommand(
        principal=harness.creator,
        reference_id=uuid4(),
        purpose="provider.openai",
        value=SecretValue(OLD_SECRET),
        idempotency_key=idempotency_key,
    )


def _create(harness: Harness) -> SecretCommandOutcome:
    return harness.service.create(_create_command(harness))


def _activate_initial(harness: Harness) -> SecretVersionHandle:
    created = _create(harness)
    harness.service.verify(
        VerifySecretCommand(
            principal=harness.creator,
            handle=created.handle,
            idempotency_key="verify-initial-secret",
            expected_version=1,
        )
    )
    harness.service.activate(
        ActivateSecretVersionCommand(
            principal=harness.approver,
            handle=created.handle,
            idempotency_key="activate-initial-secret",
            expected_version=2,
        )
    )
    return created.handle
