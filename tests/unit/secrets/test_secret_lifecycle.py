from datetime import UTC, datetime
import json
import pickle
from uuid import UUID, uuid4

import pytest

from geo_core.secrets import (
    EnvelopeCipher,
    InMemorySecretStore,
    MasterKeyring,
    SecretAuditAction,
    SecretRedactor,
    SecretScopeViolation,
    SecretSerializationRejected,
    SecretStateConflict,
    SecretValue,
    SecretVersionHandle,
    SecretVersionStatus,
    SecretVersionUnavailable,
    reject_secret_bearing_payload,
)


NOW = datetime(2026, 7, 23, 10, 15, tzinfo=UTC)
KEY = b"K" * 32
OLD_SECRET = "old-AU-egress-password-3029"
NEW_SECRET = "new-AU-egress-password-7812"


def test_rotation_verifies_then_atomically_switches_and_keeps_pinned_version() -> None:
    store = _store()
    project_id = uuid4()
    reference_id = uuid4()
    actor_id = uuid4()
    old_handle = store.create(
        reference_id=reference_id,
        project_id=project_id,
        purpose="egress.proxy",
        value=SecretValue(OLD_SECRET),
        actor_id=actor_id,
    )

    new_handle = store.rotate(
        reference_id=reference_id,
        project_id=project_id,
        purpose="egress.proxy",
        value=SecretValue(NEW_SECRET),
        actor_id=actor_id,
    )

    assert new_handle.version == 2
    assert store.current_handle(
        reference_id=reference_id,
        project_id=project_id,
        purpose="egress.proxy",
    ) == new_handle
    assert store.status_of(
        old_handle, project_id=project_id, purpose="egress.proxy"
    ) is SecretVersionStatus.SUPERSEDED
    assert store.status_of(
        new_handle, project_id=project_id, purpose="egress.proxy"
    ) is SecretVersionStatus.ACTIVE
    assert store.resolve(
        old_handle,
        project_id=project_id,
        purpose="egress.proxy",
        actor_id=actor_id,
    ).matches(OLD_SECRET)
    assert store.resolve(
        new_handle,
        project_id=project_id,
        purpose="egress.proxy",
        actor_id=actor_id,
    ).matches(NEW_SECRET)

    actions = [event.action for event in store.audit_events]
    assert actions.count(SecretAuditAction.VERSION_STAGED) == 2
    assert actions.count(SecretAuditAction.VERSION_VERIFIED) == 2
    assert actions.count(SecretAuditAction.VERSION_ACTIVATED) == 2
    assert all(event.project_id == project_id for event in store.audit_events)
    assert OLD_SECRET not in repr(store.audit_events)
    assert NEW_SECRET not in repr(store.audit_events)


def test_pending_version_requires_verification_before_activation_or_consumption() -> None:
    store, ids, current = _created_store()
    pending = store.stage_version(
        reference_id=current.reference_id,
        project_id=ids[0],
        purpose="provider.openai",
        value=SecretValue(NEW_SECRET),
        actor_id=ids[1],
    )

    with pytest.raises(SecretStateConflict, match="verified pending"):
        store.activate_version(
            pending,
            project_id=ids[0],
            purpose="provider.openai",
            actor_id=ids[1],
        )
    with pytest.raises(SecretVersionUnavailable, match="not available"):
        store.resolve(
            pending,
            project_id=ids[0],
            purpose="provider.openai",
            actor_id=ids[1],
        )

    result = store.verify_version(
        pending,
        project_id=ids[0],
        purpose="provider.openai",
        actor_id=ids[1],
    )
    store.activate_version(
        pending,
        project_id=ids[0],
        purpose="provider.openai",
        actor_id=ids[1],
    )

    assert result.valid is True
    assert result.handle == pending


def test_an_older_pending_version_cannot_replace_a_newer_active_version() -> None:
    store, ids, current = _created_store()
    older_pending = store.stage_version(
        reference_id=current.reference_id,
        project_id=ids[0],
        purpose="provider.openai",
        value=SecretValue("pending-version-two"),
        actor_id=ids[1],
    )
    newer_pending = store.stage_version(
        reference_id=current.reference_id,
        project_id=ids[0],
        purpose="provider.openai",
        value=SecretValue("pending-version-three"),
        actor_id=ids[1],
    )
    for handle in (older_pending, newer_pending):
        store.verify_version(
            handle,
            project_id=ids[0],
            purpose="provider.openai",
            actor_id=ids[1],
        )
    store.activate_version(
        newer_pending,
        project_id=ids[0],
        purpose="provider.openai",
        actor_id=ids[1],
    )

    with pytest.raises(SecretStateConflict, match="cannot roll back"):
        store.activate_version(
            older_pending,
            project_id=ids[0],
            purpose="provider.openai",
            actor_id=ids[1],
        )


def test_revocation_fails_closed_for_pinned_and_current_versions() -> None:
    store, ids, handle = _created_store()

    store.revoke_version(
        handle,
        project_id=ids[0],
        purpose="provider.openai",
        actor_id=ids[1],
    )

    with pytest.raises(SecretVersionUnavailable, match="not available"):
        store.resolve(
            handle,
            project_id=ids[0],
            purpose="provider.openai",
            actor_id=ids[1],
        )
    with pytest.raises(SecretVersionUnavailable, match="no active version"):
        store.current_handle(
            reference_id=handle.reference_id,
            project_id=ids[0],
            purpose="provider.openai",
        )
    assert store.status_of(
        handle, project_id=ids[0], purpose="provider.openai"
    ) is SecretVersionStatus.REVOKED


def test_project_and_purpose_scope_is_required_for_every_lookup() -> None:
    store, ids, handle = _created_store()

    for wrong_project, wrong_purpose in (
        (uuid4(), "provider.openai"),
        (ids[0], "provider.kimi"),
    ):
        with pytest.raises(SecretScopeViolation, match="scope"):
            store.resolve(
                handle,
                project_id=wrong_project,
                purpose=wrong_purpose,
                actor_id=ids[1],
            )


def test_job_payload_contains_only_immutable_reference_version() -> None:
    store, ids, handle = _created_store()
    payload = handle.as_job_payload()

    reject_secret_bearing_payload(payload)
    encoded = json.dumps(payload, sort_keys=True)

    assert OLD_SECRET not in encoded
    assert "ciphertext" not in encoded
    assert payload["secret_version"] == 1
    assert payload["secret_reference_id"] == str(handle.reference_id)
    with pytest.raises(SecretSerializationRejected, match="cannot enter"):
        reject_secret_bearing_payload(
            {"job": payload, "credential": store.resolve(
                handle,
                project_id=ids[0],
                purpose="provider.openai",
                actor_id=ids[1],
            )}
        )
    with pytest.raises(SecretSerializationRejected, match="cannot enter"):
        reject_secret_bearing_payload(
            store.encrypted_version(handle, project_id=ids[0], purpose="provider.openai")
        )


def test_plaintext_wrapper_and_external_exception_are_redacted() -> None:
    value = SecretValue(OLD_SECRET)
    redactor = SecretRedactor((value,))
    provider_error = RuntimeError(
        f"request failed Authorization: Bearer {OLD_SECRET} password={OLD_SECRET}"
    )
    payload = {
        "headers": {"Authorization": f"Bearer {OLD_SECRET}", "Accept": "json"},
        "query": f"https://example.test/search?token={OLD_SECRET}&q=vacuum",
        "form": {"password": OLD_SECRET, "locale": "en-AU"},
        "json": {"api_key": OLD_SECRET, "message": f"failed: {OLD_SECRET}"},
        "sdk_exception": provider_error,
    }

    cleaned = redactor.redact(payload)

    assert str(value) == "[REDACTED]"
    assert repr(value) == "SecretValue([REDACTED])"
    assert OLD_SECRET not in repr(cleaned)
    assert "en-AU" in repr(cleaned)
    assert "[REDACTED]" in repr(cleaned)
    redactor.assert_no_registered_plaintext(cleaned)
    with pytest.raises(SecretSerializationRejected, match="cannot be serialized"):
        pickle.dumps(value)
    with pytest.raises(TypeError):
        json.dumps(value)


def test_unregistered_common_credentials_are_redacted_by_context() -> None:
    redactor = SecretRedactor()
    source = (
        "Cookie: session=raw-cookie; Proxy-Authorization: Basic cHJveHk6cGFzcw==; "
        'body={"access_token":"raw-access"}; Bearer raw-standalone'
    )

    cleaned = redactor.redact_text(source)

    assert "raw-cookie" not in cleaned
    assert "cHJveHk6cGFzcw==" not in cleaned
    assert "raw-access" not in cleaned
    assert "raw-standalone" not in cleaned
    assert cleaned.count("[REDACTED]") == 4


def test_process_objects_with_keys_or_registered_values_deny_serialization() -> None:
    store = _store()
    redactor = SecretRedactor((OLD_SECRET,))

    for sensitive in (store, redactor):
        with pytest.raises(SecretSerializationRejected, match="cannot be serialized"):
            pickle.dumps(sensitive)
        with pytest.raises(SecretSerializationRejected, match="cannot enter"):
            reject_secret_bearing_payload(sensitive)


def test_redactor_detects_accidental_plaintext_payload_without_echoing_it() -> None:
    redactor = SecretRedactor((OLD_SECRET,))

    with pytest.raises(SecretSerializationRejected) as caught:
        redactor.assert_no_registered_plaintext({"debug": OLD_SECRET})

    assert OLD_SECRET not in str(caught.value)


def _store() -> InMemorySecretStore:
    return InMemorySecretStore(
        EnvelopeCipher(MasterKeyring(keys={1: KEY}, active_version=1)),
        clock=lambda: NOW,
    )


def _created_store() -> tuple[InMemorySecretStore, tuple[UUID, UUID], SecretVersionHandle]:
    store = _store()
    project_id = uuid4()
    actor_id = uuid4()
    handle = store.create(
        reference_id=uuid4(),
        project_id=project_id,
        purpose="provider.openai",
        value=SecretValue(OLD_SECRET),
        actor_id=actor_id,
    )
    return store, (project_id, actor_id), handle
