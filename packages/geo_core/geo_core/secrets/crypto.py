"""AES-256-GCM envelope encryption and master-key recovery canaries."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
import json
import os
import hmac
from typing import Never

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import (
    SecretConfigurationError,
    SecretDecryptionError,
    SecretKeyUnavailable,
    SecretSerializationRejected,
)
from .models import (
    ENVELOPE_ALGORITHM,
    EncryptedSecretVersion,
    MasterKeyCanary,
    SecretReference,
    SecretValue,
    SecretVersionHandle,
)


_KEY_BYTES = 32
_NONCE_BYTES = 12
_CANARY_PLAINTEXT = b"geo-secret-store-master-key-canary-v1"


class MasterKeyring:
    """An immutable in-memory keyring with one encryption key and historical keys."""

    __slots__ = ("__keys", "__active_version")

    def __init__(self, *, keys: Mapping[int, bytes], active_version: int) -> None:
        copied: dict[int, bytes] = {}
        for version, key in keys.items():
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                raise SecretConfigurationError("master key versions must be positive integers")
            material = bytes(key)
            if len(material) != _KEY_BYTES:
                raise SecretConfigurationError("master keys must be 256 bits")
            copied[version] = material
        if (
            not isinstance(active_version, int)
            or isinstance(active_version, bool)
            or not copied
            or active_version not in copied
        ):
            raise SecretConfigurationError("active master key version is unavailable")
        self.__keys = copied
        self.__active_version = active_version

    @property
    def active_version(self) -> int:
        return self.__active_version

    @property
    def versions(self) -> tuple[int, ...]:
        return tuple(sorted(self.__keys))

    def __repr__(self) -> str:
        return f"MasterKeyring(active_version={self.active_version}, versions={self.versions!r})"

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("master keyrings cannot be serialized")

    def with_new_active_key(self, *, version: int, key: bytes) -> "MasterKeyring":
        if version in self.__keys:
            raise SecretConfigurationError("master key versions are immutable")
        return MasterKeyring(keys={**self.__keys, version: bytes(key)}, active_version=version)

    def _key_for(self, version: int) -> bytes:
        try:
            return self.__keys[version]
        except KeyError:
            raise SecretKeyUnavailable("required master key version is unavailable") from None

    def _items_for_escrow(self) -> tuple[tuple[int, bytes], ...]:
        """Return transient copies exclusively for the authenticated escrow codec."""

        return tuple((version, bytes(self.__keys[version])) for version in self.versions)

    def _contains_material(self, candidate: bytes) -> bool:
        return any(hmac.compare_digest(key, candidate) for key in self.__keys.values())


class EnvelopeCipher:
    """Encrypt secret payloads with per-version DEKs wrapped by a master key."""

    def __init__(
        self,
        keyring: MasterKeyring,
        *,
        random_bytes: Callable[[int], bytes] = os.urandom,
    ) -> None:
        self._keyring = keyring
        self._random_bytes = random_bytes

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("secret ciphers cannot be serialized")

    @property
    def master_key_versions(self) -> tuple[int, ...]:
        return self._keyring.versions

    @property
    def active_master_key_version(self) -> int:
        return self._keyring.active_version

    def encrypt(
        self,
        *,
        reference: SecretReference,
        version: int,
        value: SecretValue,
        created_at: datetime,
    ) -> EncryptedSecretVersion:
        handle = SecretVersionHandle(
            reference_id=reference.id,
            project_id=reference.project_id,
            purpose=reference.purpose,
            version=version,
        )
        data_key = bytearray(self._random_exact(_KEY_BYTES))
        try:
            data_nonce = self._random_exact(_NONCE_BYTES)
            wrap_nonce = self._random_exact(_NONCE_BYTES)
            payload_aad = _aad(handle=handle, layer="payload", created_at=created_at)
            master_key_version = self._keyring.active_version
            wrapping_aad = _aad(
                handle=handle,
                layer="data-key",
                created_at=created_at,
                master_key_version=master_key_version,
            )
            ciphertext = AESGCM(data_key).encrypt(
                data_nonce,
                value.reveal_bytes(),
                payload_aad,
            )
            wrapped_data_key = AESGCM(self._keyring._key_for(master_key_version)).encrypt(
                wrap_nonce,
                bytes(data_key),
                wrapping_aad,
            )
        finally:
            for index in range(len(data_key)):
                data_key[index] = 0
        return EncryptedSecretVersion(
            handle=handle,
            ciphertext=ciphertext,
            data_nonce=data_nonce,
            wrapped_data_key=wrapped_data_key,
            wrap_nonce=wrap_nonce,
            master_key_version=master_key_version,
            created_at=created_at,
        )

    def decrypt(self, envelope: EncryptedSecretVersion) -> SecretValue:
        data_key = self._unwrap_data_key(envelope)
        try:
            plaintext = AESGCM(data_key).decrypt(
                envelope.data_nonce,
                envelope.ciphertext,
                _aad(
                    handle=envelope.handle,
                    layer="payload",
                    created_at=envelope.created_at,
                ),
            )
        except InvalidTag:
            raise SecretDecryptionError("secret envelope authentication failed") from None
        finally:
            for index in range(len(data_key)):
                data_key[index] = 0
        return SecretValue(plaintext)

    def rewrap(self, envelope: EncryptedSecretVersion) -> EncryptedSecretVersion:
        """Authenticate the full envelope and wrap its DEK with the active key."""

        data_key = self._unwrap_data_key(envelope)
        try:
            try:
                AESGCM(data_key).decrypt(
                    envelope.data_nonce,
                    envelope.ciphertext,
                    _aad(
                        handle=envelope.handle,
                        layer="payload",
                        created_at=envelope.created_at,
                    ),
                )
            except InvalidTag:
                raise SecretDecryptionError("secret envelope authentication failed") from None
            wrap_nonce = self._random_exact(_NONCE_BYTES)
            active_version = self._keyring.active_version
            wrapped_data_key = AESGCM(self._keyring._key_for(active_version)).encrypt(
                wrap_nonce,
                bytes(data_key),
                _aad(
                    handle=envelope.handle,
                    layer="data-key",
                    created_at=envelope.created_at,
                    master_key_version=active_version,
                ),
            )
        finally:
            for index in range(len(data_key)):
                data_key[index] = 0
        return replace(
            envelope,
            wrapped_data_key=wrapped_data_key,
            wrap_nonce=wrap_nonce,
            master_key_version=active_version,
        )

    def create_canary(self, master_key_version: int) -> MasterKeyCanary:
        nonce = self._random_exact(_NONCE_BYTES)
        ciphertext = AESGCM(self._keyring._key_for(master_key_version)).encrypt(
            nonce,
            _CANARY_PLAINTEXT,
            _canary_aad(master_key_version),
        )
        return MasterKeyCanary(
            master_key_version=master_key_version,
            nonce=nonce,
            ciphertext=ciphertext,
        )

    def create_all_canaries(self) -> tuple[MasterKeyCanary, ...]:
        return tuple(self.create_canary(version) for version in self._keyring.versions)

    def verify_canary(self, canary: MasterKeyCanary) -> None:
        try:
            plaintext = AESGCM(self._keyring._key_for(canary.master_key_version)).decrypt(
                canary.nonce,
                canary.ciphertext,
                _canary_aad(canary.master_key_version),
            )
        except InvalidTag:
            raise SecretDecryptionError("master key canary authentication failed") from None
        if plaintext != _CANARY_PLAINTEXT:
            raise SecretDecryptionError("master key canary verification failed")

    def verify_canary_set(
        self,
        canaries: Iterable[MasterKeyCanary],
        *,
        required_versions: Iterable[int] | None = None,
    ) -> None:
        canary_list = tuple(canaries)
        by_version = {canary.master_key_version: canary for canary in canary_list}
        required = set(self._keyring.versions if required_versions is None else required_versions)
        if len(by_version) != len(canary_list) or set(by_version) != required:
            raise SecretConfigurationError("master key canary set does not match required versions")
        for version in sorted(required):
            self.verify_canary(by_version[version])

    def _unwrap_data_key(self, envelope: EncryptedSecretVersion) -> bytearray:
        try:
            value = AESGCM(self._keyring._key_for(envelope.master_key_version)).decrypt(
                envelope.wrap_nonce,
                envelope.wrapped_data_key,
                _aad(
                    handle=envelope.handle,
                    layer="data-key",
                    created_at=envelope.created_at,
                    master_key_version=envelope.master_key_version,
                ),
            )
        except InvalidTag:
            raise SecretDecryptionError("secret envelope authentication failed") from None
        if len(value) != _KEY_BYTES:
            raise SecretDecryptionError("secret envelope data key is invalid")
        return bytearray(value)

    def _random_exact(self, length: int) -> bytes:
        value = self._random_bytes(length)
        if len(value) != length:
            raise SecretConfigurationError("secure random source returned an invalid length")
        return value


def _aad(
    *,
    handle: SecretVersionHandle,
    layer: str,
    created_at: datetime,
    master_key_version: int | None = None,
) -> bytes:
    payload: dict[str, str | int] = {
        "algorithm": ENVELOPE_ALGORITHM,
        "created_at": created_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "layer": layer,
        "project_id": str(handle.project_id),
        "purpose": handle.purpose,
        "reference_id": str(handle.reference_id),
        "schema": "geo-secret-envelope-aad-v1",
        "version": handle.version,
    }
    if master_key_version is not None:
        payload["master_key_version"] = master_key_version
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _canary_aad(master_key_version: int) -> bytes:
    return (
        f"geo-secret-store-master-key-canary-aad-v1:{ENVELOPE_ALGORITHM}:"
        f"{master_key_version}"
    ).encode("ascii")
