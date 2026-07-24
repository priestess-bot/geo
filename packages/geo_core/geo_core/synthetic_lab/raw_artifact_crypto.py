"""Per-artifact AES-256-GCM encryption with independently wrapped DEKs."""

from __future__ import annotations

import os
from typing import Protocol
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from geo_core.secrets.models import SecretValue
from geo_core.synthetic_lab.raw_artifact_governance import ArtifactStorageTier
from geo_core.synthetic_lab.raw_artifact_storage_contracts import (
    ArtifactDekVaultPort,
    ArtifactEncryptionEnvelope,
    TierEncryptionEnvelope,
)


_ENVELOPE_PREFIX = b"GEO-RAW-AESGCM-V1\x00"
_TIER_ENVELOPE_PREFIX = b"GEO-TIER-AESGCM-V1\x00"


class ArtifactTierKeyResolverPort(Protocol):
    def resolve(
        self,
        *,
        project_id: UUID,
        storage_tier: ArtifactStorageTier,
    ) -> tuple[str, SecretValue]: ...


class IndependentDekArtifactEncryptor:
    """Generate and erase one data key for each restricted artifact."""

    def __init__(self, vault: ArtifactDekVaultPort) -> None:
        self._vault = vault

    def encrypt(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        fencing_generation: int,
        plaintext: bytearray,
        associated_data: bytes,
    ) -> ArtifactEncryptionEnvelope:
        data_key = bytearray(os.urandom(32))
        key_ref: str | None = None
        try:
            nonce = os.urandom(12)
            ciphertext = AESGCM(bytes(data_key)).encrypt(
                nonce,
                bytes(plaintext),
                associated_data,
            )
            key_ref = self._vault.store_wrapped_key(
                project_id=project_id,
                artifact_id=artifact_id,
                fencing_generation=fencing_generation,
                key_material=data_key,
            )
            return ArtifactEncryptionEnvelope(
                payload=_ENVELOPE_PREFIX + nonce + ciphertext,
                key_ref=key_ref,
                algorithm="AES-256-GCM/independent-DEK/v1",
            )
        except BaseException:
            if key_ref is not None:
                self._vault.destroy_wrapped_key(key_ref)
            raise
        finally:
            _wipe(data_key)

    def destroy_key(self, key_ref: str) -> None:
        self._vault.destroy_wrapped_key(key_ref)


class ProjectTierArtifactEncryptor:
    """Encrypt non-restricted objects with a versioned Project/tier key."""

    def __init__(self, resolver: ArtifactTierKeyResolverPort) -> None:
        self._resolver = resolver

    def encrypt(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        storage_tier: ArtifactStorageTier,
        plaintext: bytearray,
        associated_data: bytes,
    ) -> TierEncryptionEnvelope:
        del artifact_id
        key_version, secret = self._resolver.resolve(
            project_id=project_id,
            storage_tier=storage_tier,
        )
        key = bytearray(secret.reveal_bytes())
        try:
            if len(key) != 32:
                raise ValueError("artifact tier key must contain exactly 32 bytes")
            nonce = os.urandom(12)
            ciphertext = AESGCM(bytes(key)).encrypt(
                nonce,
                bytes(plaintext),
                associated_data,
            )
            return TierEncryptionEnvelope(
                payload=_TIER_ENVELOPE_PREFIX + nonce + ciphertext,
                key_version=key_version,
                algorithm="AES-256-GCM/project-tier-key/v1",
            )
        finally:
            _wipe(key)


def decrypt_independent_dek_artifact(
    *,
    payload: bytes,
    data_key: bytes,
    associated_data: bytes,
) -> bytes:
    return _decrypt_envelope(
        payload=payload,
        prefix=_ENVELOPE_PREFIX,
        key=data_key,
        associated_data=associated_data,
    )


def decrypt_project_tier_artifact(
    *,
    payload: bytes,
    tier_key: bytes,
    associated_data: bytes,
) -> bytes:
    return _decrypt_envelope(
        payload=payload,
        prefix=_TIER_ENVELOPE_PREFIX,
        key=tier_key,
        associated_data=associated_data,
    )


def _decrypt_envelope(
    *,
    payload: bytes,
    prefix: bytes,
    key: bytes,
    associated_data: bytes,
) -> bytes:
    if len(key) != 32 or not payload.startswith(prefix) or len(payload) <= len(prefix) + 28:
        raise ValueError("encrypted artifact envelope is invalid")
    offset = len(prefix)
    nonce = payload[offset : offset + 12]
    return AESGCM(key).decrypt(nonce, payload[offset + 12 :], associated_data)


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = [
    "ArtifactTierKeyResolverPort",
    "decrypt_independent_dek_artifact",
    "decrypt_project_tier_artifact",
    "IndependentDekArtifactEncryptor",
    "ProjectTierArtifactEncryptor",
]
