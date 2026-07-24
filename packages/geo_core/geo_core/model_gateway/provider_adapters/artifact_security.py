"""Encryption and sensitive-field governance for Provider artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import os
from typing import Protocol
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_ENVELOPE_PREFIX = b"GEO-PROVIDER-AESGCM-V1\x00"
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)


class ProviderArtifactError(RuntimeError):
    """A response could not be governed and durably persisted."""


@dataclass(frozen=True, repr=False)
class ProviderArtifactEncryptionEnvelope:
    payload: bytes = field(repr=False)
    key_reference: str
    algorithm: str

    def __post_init__(self) -> None:
        if not self.payload or not self.key_reference.strip() or not self.algorithm.strip():
            raise ProviderArtifactError("provider artifact encryption envelope is incomplete")


class ProviderArtifactKeyVault(Protocol):
    def store_wrapped_key(
        self, *, project_id: UUID, artifact_id: UUID, key_material: bytearray
    ) -> str: ...

    def destroy_wrapped_key(
        self, *, project_id: UUID, key_reference: str
    ) -> None: ...


class ProviderArtifactEncryptor(Protocol):
    def encrypt(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        plaintext: bytearray,
        associated_data: bytes,
    ) -> ProviderArtifactEncryptionEnvelope: ...

    def destroy_key(self, *, project_id: UUID, key_reference: str) -> None: ...


class IndependentProviderArtifactEncryptor:
    """Encrypt every artifact with a fresh DEK held by an external key vault."""

    def __init__(self, vault: ProviderArtifactKeyVault) -> None:
        self._vault = vault

    def encrypt(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        plaintext: bytearray,
        associated_data: bytes,
    ) -> ProviderArtifactEncryptionEnvelope:
        data_key = bytearray(os.urandom(32))
        key_reference: str | None = None
        try:
            nonce = os.urandom(12)
            ciphertext = AESGCM(bytes(data_key)).encrypt(
                nonce, bytes(plaintext), associated_data
            )
            key_reference = self._vault.store_wrapped_key(
                project_id=project_id,
                artifact_id=artifact_id,
                key_material=data_key,
            )
            return ProviderArtifactEncryptionEnvelope(
                payload=_ENVELOPE_PREFIX + nonce + ciphertext,
                key_reference=key_reference,
                algorithm="AES-256-GCM/independent-DEK/v1",
            )
        except BaseException:
            if key_reference is not None:
                self._vault.destroy_wrapped_key(
                    project_id=project_id, key_reference=key_reference
                )
            raise
        finally:
            wipe_bytearray(data_key)

    def destroy_key(self, *, project_id: UUID, key_reference: str) -> None:
        self._vault.destroy_wrapped_key(
            project_id=project_id, key_reference=key_reference
        )


@dataclass(frozen=True)
class GovernedProviderPayload:
    classification: str
    payload: bytearray = field(repr=False)


class ProviderArtifactGovernance(Protocol):
    def govern(self, payload: Mapping[str, object]) -> GovernedProviderPayload: ...


class StrictProviderArtifactGovernance:
    """Remove credential-like fields and classify all Provider bodies as restricted."""

    def govern(self, payload: Mapping[str, object]) -> GovernedProviderPayload:
        redacted = _redact_value(payload)
        if not isinstance(redacted, Mapping):
            raise ProviderArtifactError("provider response governance requires a JSON object")
        return GovernedProviderPayload(
            classification="restricted_provider_response",
            payload=bytearray(canonical_provider_json_bytes(redacted)),
        )


def canonical_provider_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProviderArtifactError("provider artifact is not canonical JSON") from exc


def provider_artifact_associated_data(
    *,
    project_id: UUID,
    provider: str,
    kind: str,
    content_hash: str,
    adapter_release_hash: str,
) -> bytes:
    return canonical_provider_json_bytes(
        {
            "project_id": str(project_id),
            "provider": provider,
            "kind": kind,
            "content_hash": content_hash,
            "adapter_release_hash": adapter_release_hash,
        }
    )


def decrypt_provider_artifact_payload(
    *, encrypted_payload: bytes, key_material: bytearray, associated_data: bytes
) -> bytearray:
    prefix_size = len(_ENVELOPE_PREFIX)
    if (
        len(key_material) != 32
        or not encrypted_payload.startswith(_ENVELOPE_PREFIX)
        or len(encrypted_payload) < prefix_size + 12 + 17
    ):
        raise ProviderArtifactError("Provider artifact encryption envelope is invalid")
    nonce = encrypted_payload[prefix_size : prefix_size + 12]
    ciphertext = encrypted_payload[prefix_size + 12 :]
    try:
        return bytearray(
            AESGCM(bytes(key_material)).decrypt(nonce, ciphertext, associated_data)
        )
    except InvalidTag:
        raise ProviderArtifactError(
            "Provider artifact encryption authentication failed"
        ) from None


def wipe_bytearray(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


def _redact_value(value: object, *, key: str | None = None) -> object:
    if key is not None and any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        if not all(isinstance(item_key, str) for item_key in value):
            raise ProviderArtifactError("provider artifact JSON keys must be strings")
        return {
            item_key: _redact_value(item, key=item_key)
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str) and value.lower().startswith("bearer "):
        return "[REDACTED]"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ProviderArtifactError("provider artifact contains non-JSON content")


__all__ = [
    "GovernedProviderPayload",
    "IndependentProviderArtifactEncryptor",
    "ProviderArtifactEncryptionEnvelope",
    "ProviderArtifactEncryptor",
    "ProviderArtifactError",
    "ProviderArtifactGovernance",
    "ProviderArtifactKeyVault",
    "StrictProviderArtifactGovernance",
    "canonical_provider_json_bytes",
    "decrypt_provider_artifact_payload",
    "provider_artifact_associated_data",
    "wipe_bytearray",
]
