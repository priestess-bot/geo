"""Read-only restore verification for Provider artifact keyrings and ciphertext."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any
from uuid import UUID

from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.model_gateway.postgres_artifacts import decrypt_provider_artifact_dek
from geo_core.model_gateway.provider_adapters.artifacts import (
    ProviderArtifactError,
    ProviderArtifactObjectStore,
    decrypt_provider_artifact_payload,
    provider_artifact_associated_data,
)
from geo_core.secrets import EnvelopeCipher, MasterKeyCanary


@dataclass(frozen=True)
class ProviderArtifactRestoreVerification:
    verified_master_key_versions: tuple[int, ...]
    active_dek_count: int
    recoverable_artifact_count: int
    representative_artifact_verified: bool
    representative_artifact_id: UUID | None
    representative_manifest_hash: str | None
    verification_receipt_hash: str
    empty_artifact_domain: bool


def verify_provider_artifact_restore(
    *,
    connection: Any,
    cipher: EnvelopeCipher,
    object_store: ProviderArtifactObjectStore,
) -> ProviderArtifactRestoreVerification:
    canary_rows = tuple(
        connection.execute(
            """SELECT master_key_version, status, algorithm,
                      canary_nonce, canary_ciphertext
               FROM model_gateway_artifact_master_key_versions
               WHERE status <> 'retired' ORDER BY master_key_version"""
        ).fetchall()
    )
    versions = tuple(int(row["master_key_version"]) for row in canary_rows)
    if set(versions) != set(cipher.master_key_versions):
        raise ProviderArtifactError(
            "Provider artifact restore keyring does not match non-retired canaries"
        )
    active_versions = tuple(
        int(row["master_key_version"])
        for row in canary_rows
        if row["status"] == "encrypt_decrypt"
    )
    if active_versions != (cipher.active_master_key_version,):
        raise ProviderArtifactError(
            "Provider artifact restore active key does not match the keyring"
        )
    for row in canary_rows:
        cipher.verify_canary(
            MasterKeyCanary(
                master_key_version=int(row["master_key_version"]),
                algorithm=str(row["algorithm"]),
                nonce=bytes(row["canary_nonce"]),
                ciphertext=bytes(row["canary_ciphertext"]),
            )
        )
    counts = connection.execute(
        """SELECT
               (SELECT count(*) FROM model_gateway_artifact_deks
                WHERE status = 'active') AS active_dek_count,
               (SELECT count(*)
                FROM model_gateway_artifacts artifact
                JOIN model_gateway_artifact_deks dek
                  ON dek.key_ref = artifact.key_ref
                 AND dek.project_id = artifact.project_id
                 AND dek.artifact_id = artifact.artifact_id
                JOIN model_gateway_artifact_bundles bundle
                  ON bundle.id = artifact.bundle_id
                 AND bundle.project_id = artifact.project_id
                WHERE dek.status = 'active' AND bundle.status = 'committed'
               ) AS recoverable_artifact_count"""
    ).fetchone()
    active_deks = int(counts["active_dek_count"])
    recoverable = int(counts["recoverable_artifact_count"])
    if active_deks > 0 and recoverable == 0:
        raise ProviderArtifactError(
            "Provider artifact restore found active DEKs without committed artifacts"
        )
    representative = connection.execute(
        """SELECT artifact.*, bundle.provider, bundle.adapter_release_hash,
                  dek.ciphertext, dek.data_nonce, dek.wrapped_data_key,
                  dek.wrap_nonce, dek.master_key_version, dek.algorithm,
                  dek.created_at
           FROM model_gateway_artifacts artifact
           JOIN model_gateway_artifact_bundles bundle
             ON bundle.id = artifact.bundle_id
            AND bundle.project_id = artifact.project_id
           JOIN model_gateway_artifact_deks dek
             ON dek.key_ref = artifact.key_ref
            AND dek.project_id = artifact.project_id
            AND dek.artifact_id = artifact.artifact_id
           WHERE bundle.status = 'committed' AND dek.status = 'active'
           ORDER BY bundle.committed_at, artifact.kind, artifact.artifact_id
           LIMIT 1"""
    ).fetchone()
    artifact_id: UUID | None = None
    manifest_hash: str | None = None
    verified = False
    probe: dict[str, object] | None = None
    if representative is not None:
        artifact_id = representative["artifact_id"]
        if not isinstance(artifact_id, UUID):
            raise ProviderArtifactError(
                "Provider artifact restore representative identity is invalid"
            )
        manifest_hash = str(representative["manifest_hash"])
        manifest = object_store.get_s3_uri(
            uri=str(representative["manifest_uri"]), expected_hash=manifest_hash
        )
        payload_hash = str(representative["payload_hash"])
        payload = object_store.get_s3_uri(
            uri=str(representative["payload_uri"]), expected_hash=payload_hash
        )
        key_material = decrypt_provider_artifact_dek(cipher, representative)
        plaintext = bytearray()
        try:
            plaintext = decrypt_provider_artifact_payload(
                encrypted_payload=payload.content,
                key_material=key_material,
                associated_data=provider_artifact_associated_data(
                    project_id=representative["project_id"],
                    provider=str(representative["provider"]),
                    kind=str(representative["kind"]),
                    content_hash=str(representative["content_hash"]),
                    adapter_release_hash=str(representative["adapter_release_hash"]),
                ),
            )
            if hashlib.sha256(plaintext).hexdigest() != representative["content_hash"]:
                raise ProviderArtifactError(
                    "Provider artifact restore plaintext hash differs from metadata"
                )
            verified = True
            probe = {
                "artifact_id": artifact_id,
                "manifest_hash": manifest.content_hash,
                "payload_hash": payload.content_hash,
                "content_hash": representative["content_hash"],
            }
        finally:
            _wipe(key_material)
            _wipe(plaintext)
    if recoverable > 0 and not verified:
        raise ProviderArtifactError(
            "Provider artifact restore has no verified representative"
        )
    empty = active_deks == 0 and recoverable == 0
    receipt_hash = canonical_json_hash(
        {
            "schema_version": 1,
            "verified_master_key_versions": versions,
            "active_dek_count": active_deks,
            "recoverable_artifact_count": recoverable,
            "representative_artifact_verified": verified,
            "representative": probe,
            "empty_artifact_domain": empty,
        }
    )
    return ProviderArtifactRestoreVerification(
        verified_master_key_versions=versions,
        active_dek_count=active_deks,
        recoverable_artifact_count=recoverable,
        representative_artifact_verified=verified,
        representative_artifact_id=artifact_id,
        representative_manifest_hash=manifest_hash,
        verification_receipt_hash=receipt_hash,
        empty_artifact_domain=empty,
    )


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = [
    "ProviderArtifactRestoreVerification",
    "verify_provider_artifact_restore",
]
