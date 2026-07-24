"""Read-only empty-environment restore verification for Secret Store."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .crypto import EnvelopeCipher
from .docker_secret import load_master_keyring_from_docker_secret
from .errors import SecretConfigurationError
from .models import MasterKeyCanary
from .postgres_rows import VERSION_COLUMNS, version_from_row


@dataclass(frozen=True)
class SecretStoreRestoreVerification:
    verified_key_versions: tuple[int, ...]
    representative_secret_count: int


def verify_secret_store_restore(
    *, database_url: str, keyring_path: str | Path
) -> SecretStoreRestoreVerification:
    """Verify canaries and decrypt one stored envelope per referenced key version."""

    keyring = load_master_keyring_from_docker_secret(keyring_path)
    cipher = EnvelopeCipher(keyring)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        key_rows = tuple(
            connection.execute(
                """SELECT master_key_version, algorithm, status,
                          canary_nonce, canary_ciphertext
                   FROM secret_master_key_versions
                   ORDER BY master_key_version"""
            ).fetchall()
        )
        if not key_rows:
            raise SecretConfigurationError(
                "Secret Store restore has no persisted master key canaries"
            )
        nonretired = {
            int(row["master_key_version"])
            for row in key_rows
            if str(row["status"]) != "retired"
        }
        if nonretired != set(keyring.versions):
            raise SecretConfigurationError(
                "Secret Store restored keyring does not cover active key history"
            )
        active = {
            int(row["master_key_version"])
            for row in key_rows
            if str(row["status"]) == "encrypt_decrypt"
        }
        if active != {keyring.active_version}:
            raise SecretConfigurationError(
                "Secret Store restored active key does not match storage"
            )
        for row in key_rows:
            version = int(row["master_key_version"])
            if version not in nonretired:
                continue
            cipher.verify_canary(
                MasterKeyCanary(
                    master_key_version=version,
                    algorithm=str(row["algorithm"]),
                    nonce=bytes(row["canary_nonce"]),
                    ciphertext=bytes(row["canary_ciphertext"]),
                )
            )
        representatives = tuple(
            connection.execute(
                f"""SELECT DISTINCT ON (master_key_version) {VERSION_COLUMNS}
                    FROM secret_versions
                    ORDER BY master_key_version, reference_id, version"""
            ).fetchall()
        )
        referenced_versions = {
            int(row["master_key_version"]) for row in representatives
        }
        if not referenced_versions <= nonretired:
            raise SecretConfigurationError(
                "Secret Store ciphertext references a retired or unavailable key"
            )
        for row in representatives:
            cipher.decrypt(version_from_row(row).envelope)
    return SecretStoreRestoreVerification(
        verified_key_versions=tuple(sorted(nonretired)),
        representative_secret_count=len(representatives),
    )


__all__ = ["SecretStoreRestoreVerification", "verify_secret_store_restore"]
