"""Database canary synchronization and master-key retirement controls."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.rows import dict_row

from .crypto import EnvelopeCipher
from .errors import SecretConfigurationError, SecretStateConflict
from .models import MasterKeyCanary


def synchronize_master_key_canaries(connection: Any, cipher: EnvelopeCipher) -> None:
    rows = _rows(connection)
    configured = set(cipher.master_key_versions)
    stored = {int(row["master_key_version"]) for row in rows}
    required = {
        int(row["master_key_version"])
        for row in rows
        if str(row["status"]) != "retired"
    }
    if required - configured:
        raise SecretConfigurationError(
            "Secret Store database requires unavailable historical master keys"
        )
    _verify_rows(
        cipher,
        tuple(
            row for row in rows if int(row["master_key_version"]) in configured
        ),
    )

    active = cipher.active_master_key_version
    if not rows:
        for version in cipher.master_key_versions:
            _register(
                connection,
                cipher.create_canary(version),
                status=("encrypt_decrypt" if version == active else "decrypt_only"),
            )
    elif active not in stored:
        if configured - stored != {active} or active <= max(stored):
            raise SecretConfigurationError(
                "Secret Store keyring history cannot be registered out of order"
            )
        _register(
            connection,
            cipher.create_canary(active),
            status="encrypt_decrypt",
        )
    elif configured != required:
        raise SecretConfigurationError(
            "Secret Store keyring contains unregistered historical versions"
        )

    final_rows = _rows(connection)
    final_required = {
        int(row["master_key_version"])
        for row in final_rows
        if str(row["status"]) != "retired"
    }
    if final_required != configured:
        raise SecretConfigurationError("Secret Store master key canary set is incomplete")
    for row in final_rows:
        version = int(row["master_key_version"])
        if version not in configured:
            continue
        expected = "encrypt_decrypt" if version == active else "decrypt_only"
        if str(row["status"]) != expected:
            raise SecretConfigurationError(
                "Secret Store active master key status does not match the Docker Secret"
            )
    _verify_rows(
        cipher,
        tuple(
            row
            for row in final_rows
            if int(row["master_key_version"]) in configured
        ),
    )


def retire_master_key_version(
    connection: Any, *, master_key_version: int, retired_at: datetime
) -> None:
    try:
        connection.execute(
            "SELECT geo_retire_secret_master_key_version(%s, %s)",
            (master_key_version, retired_at),
        )
    except Exception as error:
        del error
        raise SecretStateConflict(
            "Secret Store master key could not be retired"
        ) from None


def _rows(connection: Any) -> tuple[dict[str, Any], ...]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """SELECT master_key_version, algorithm, status,
                      canary_nonce, canary_ciphertext
               FROM secret_master_key_versions
               ORDER BY master_key_version"""
        )
        return tuple(cursor.fetchall())


def _verify_rows(
    cipher: EnvelopeCipher, rows: tuple[dict[str, Any], ...]
) -> None:
    for row in rows:
        cipher.verify_canary(
            MasterKeyCanary(
                master_key_version=int(row["master_key_version"]),
                algorithm=str(row["algorithm"]),
                nonce=bytes(row["canary_nonce"]),
                ciphertext=bytes(row["canary_ciphertext"]),
            )
        )


def _register(
    connection: Any, canary: MasterKeyCanary, *, status: str
) -> None:
    connection.execute(
        """SELECT geo_sync_secret_master_key_version(
                 %s, %s, %s, %s, %s, clock_timestamp()
               )""",
        (
            canary.master_key_version,
            status,
            canary.algorithm,
            canary.nonce,
            canary.ciphertext,
        ),
    )


__all__ = ["retire_master_key_version", "synchronize_master_key_canaries"]
