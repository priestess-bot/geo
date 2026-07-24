from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
import pickle
from typing import Any
from uuid import uuid4

import pytest

from geo_core.secrets import (
    EncryptedSecretVersion,
    EnvelopeCipher,
    MasterKeyring,
    SecretConfigurationError,
    SecretDecryptionError,
    SecretKeyUnavailable,
    SecretReference,
    SecretSerializationRejected,
    SecretValue,
)


NOW = datetime(2026, 7, 23, 9, 30, tzinfo=UTC)
KEY_V1 = bytes(range(32))
KEY_V2 = bytes(reversed(range(32)))
PLAINTEXT = "au-provider-token-VERY-SENSITIVE-9347"


def test_envelope_round_trip_uses_random_dek_and_redacted_representation() -> None:
    cipher = EnvelopeCipher(MasterKeyring(keys={1: KEY_V1}, active_version=1))
    reference = _reference()

    first = cipher.encrypt(
        reference=reference,
        version=1,
        value=SecretValue(PLAINTEXT),
        created_at=NOW,
    )
    second = cipher.encrypt(
        reference=reference,
        version=2,
        value=SecretValue(PLAINTEXT),
        created_at=NOW,
    )

    assert cipher.decrypt(first).matches(PLAINTEXT)
    assert first.ciphertext != second.ciphertext
    assert first.wrapped_data_key != second.wrapped_data_key
    assert PLAINTEXT.encode() not in first.ciphertext
    assert PLAINTEXT not in repr(first)
    assert "ciphertext" not in repr(first)
    with pytest.raises(FrozenInstanceError):
        first.master_key_version = 2  # type: ignore[misc]


@pytest.mark.parametrize("field", ["ciphertext", "wrapped_data_key", "data_nonce", "wrap_nonce"])
def test_tampered_envelope_fails_authenticated_decryption_without_plaintext(
    field: str,
) -> None:
    cipher = EnvelopeCipher(MasterKeyring(keys={1: KEY_V1}, active_version=1))
    envelope = _envelope(cipher)
    original = getattr(envelope, field)
    tampered = bytes([original[0] ^ 1]) + original[1:]

    with pytest.raises(SecretDecryptionError) as caught:
        cipher.decrypt(replace(envelope, **{field: tampered}))

    assert PLAINTEXT not in str(caught.value)
    assert "authentication failed" in str(caught.value)


def test_wrong_and_missing_master_keys_fail_closed() -> None:
    envelope = _envelope(EnvelopeCipher(MasterKeyring(keys={1: KEY_V1}, active_version=1)))

    wrong = EnvelopeCipher(MasterKeyring(keys={1: KEY_V2}, active_version=1))
    with pytest.raises(SecretDecryptionError, match="authentication failed"):
        wrong.decrypt(envelope)

    missing = EnvelopeCipher(MasterKeyring(keys={2: KEY_V2}, active_version=2))
    with pytest.raises(SecretKeyUnavailable, match="unavailable"):
        missing.decrypt(envelope)


def test_wrapped_key_aad_authenticates_master_key_version_metadata() -> None:
    shared_key_versions = MasterKeyring(keys={1: KEY_V1, 2: KEY_V1}, active_version=1)
    cipher = EnvelopeCipher(shared_key_versions)
    envelope = _envelope(cipher)

    with pytest.raises(SecretDecryptionError, match="authentication failed"):
        cipher.decrypt(replace(envelope, master_key_version=2))


def test_envelope_aad_authenticates_creation_time_metadata() -> None:
    cipher = EnvelopeCipher(MasterKeyring(keys={1: KEY_V1}, active_version=1))
    envelope = _envelope(cipher)

    with pytest.raises(SecretDecryptionError, match="authentication failed"):
        cipher.decrypt(replace(envelope, created_at=NOW + timedelta(seconds=1)))


@pytest.mark.parametrize(
    "handle_change",
    [
        {"project_id": uuid4()},
        {"reference_id": uuid4()},
        {"purpose": "provider.kimi"},
        {"version": 2},
    ],
)
def test_aad_rejects_cross_scope_and_identity_substitution(
    handle_change: dict[str, Any],
) -> None:
    cipher = EnvelopeCipher(MasterKeyring(keys={1: KEY_V1}, active_version=1))
    envelope = _envelope(cipher)
    forged_handle = replace(envelope.handle, **handle_change)

    with pytest.raises(SecretDecryptionError, match="authentication failed"):
        cipher.decrypt(replace(envelope, handle=forged_handle))


def test_master_key_rotation_preserves_history_until_authenticated_rewrap() -> None:
    initial_keyring = MasterKeyring(keys={1: KEY_V1}, active_version=1)
    initial_cipher = EnvelopeCipher(initial_keyring)
    envelope = _envelope(initial_cipher)
    canary_v1 = initial_cipher.create_canary(1)

    rotated_keyring = initial_keyring.with_new_active_key(version=2, key=KEY_V2)
    rotated_cipher = EnvelopeCipher(rotated_keyring)
    canary_v2 = rotated_cipher.create_canary(2)

    rotated_cipher.verify_canary_set((canary_v1, canary_v2))
    assert rotated_cipher.decrypt(envelope).matches(PLAINTEXT)

    rewrapped = rotated_cipher.rewrap(envelope)

    assert rewrapped.master_key_version == 2
    assert rewrapped.ciphertext == envelope.ciphertext
    assert rewrapped.wrapped_data_key != envelope.wrapped_data_key
    assert rotated_cipher.decrypt(rewrapped).matches(PLAINTEXT)
    with pytest.raises(SecretKeyUnavailable):
        initial_cipher.decrypt(rewrapped)


def test_canary_set_detects_wrong_key_tamper_and_missing_history() -> None:
    cipher = EnvelopeCipher(MasterKeyring(keys={1: KEY_V1}, active_version=1))
    canary = cipher.create_canary(1)

    wrong = EnvelopeCipher(MasterKeyring(keys={1: KEY_V2}, active_version=1))
    with pytest.raises(SecretDecryptionError, match="canary authentication failed"):
        wrong.verify_canary(canary)

    with pytest.raises(SecretDecryptionError, match="canary authentication failed"):
        cipher.verify_canary(
            replace(canary, ciphertext=bytes([canary.ciphertext[0] ^ 1]) + canary.ciphertext[1:])
        )

    with pytest.raises(SecretConfigurationError, match="does not match"):
        cipher.verify_canary_set(())
    with pytest.raises(SecretConfigurationError, match="does not match"):
        cipher.verify_canary_set((canary, canary))


def test_master_key_material_never_appears_in_keyring_repr() -> None:
    keyring = MasterKeyring(keys={1: KEY_V1}, active_version=1)

    assert KEY_V1.hex() not in repr(keyring)
    assert repr(keyring) == "MasterKeyring(active_version=1, versions=(1,))"
    with pytest.raises(SecretConfigurationError, match="immutable"):
        keyring.with_new_active_key(version=1, key=KEY_V2)


def test_keyring_cipher_and_envelope_deny_pickle_serialization() -> None:
    keyring = MasterKeyring(keys={1: KEY_V1}, active_version=1)
    cipher = EnvelopeCipher(keyring)
    envelope = _envelope(cipher)

    for sensitive in (keyring, cipher, envelope):
        with pytest.raises(SecretSerializationRejected, match="cannot be serialized"):
            pickle.dumps(sensitive)


def _reference() -> SecretReference:
    return SecretReference(
        id=uuid4(),
        project_id=uuid4(),
        purpose="provider.openai",
        created_at=NOW,
    )


def _envelope(cipher: EnvelopeCipher) -> EncryptedSecretVersion:
    return cipher.encrypt(
        reference=_reference(),
        version=1,
        value=SecretValue(PLAINTEXT),
        created_at=NOW,
    )
