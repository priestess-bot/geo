"""Fail-closed Docker Secret configuration for PostgreSQL Secret Store."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import os
from pathlib import Path
import stat

from .crypto import MasterKeyring
from .docker_secret import load_master_keyring_from_docker_secret
from .errors import SecretConfigurationError, SecretSerializationRejected


MASTER_KEYRING_ENV = "GEO_SECRET_STORE_MASTER_KEYRING_FILE"
REQUEST_HASH_KEY_ENV = "GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE"
_MAX_HASH_KEY_FILE_BYTES = 1024


@dataclass(frozen=True, repr=False)
class SecretPostgresCryptoConfig:
    keyring: MasterKeyring
    request_hash_key: bytes

    def __repr__(self) -> str:
        return "SecretPostgresCryptoConfig([REDACTED])"

    def __reduce__(self):
        raise SecretSerializationRejected(
            "Secret Store PostgreSQL crypto configuration cannot be serialized"
        )


def load_postgres_crypto_config(
    *,
    master_keyring_path: str | os.PathLike[str] | None = None,
    request_hash_key_path: str | os.PathLike[str] | None = None,
) -> SecretPostgresCryptoConfig | None:
    keyring_path = _configured_path(master_keyring_path, MASTER_KEYRING_ENV)
    hash_path = _configured_path(request_hash_key_path, REQUEST_HASH_KEY_ENV)
    if keyring_path is None and hash_path is None:
        return None
    if keyring_path is None or hash_path is None:
        raise SecretConfigurationError(
            "Secret Store Docker Secret files must be configured together"
        )
    return SecretPostgresCryptoConfig(
        keyring=load_master_keyring_from_docker_secret(keyring_path),
        request_hash_key=_load_base64_key(hash_path),
    )


def _configured_path(
    explicit: str | os.PathLike[str] | None, environment_name: str
) -> Path | None:
    if explicit is not None:
        return Path(explicit)
    value = os.getenv(environment_name, "").strip()
    return Path(value) if value else None


def _load_base64_key(path: Path) -> bytes:
    raw = _read_secure_file(path)
    try:
        encoded = raw.decode("ascii").strip()
        if not encoded or any(character.isspace() for character in encoded):
            raise ValueError
        key = base64.b64decode(encoded, validate=True)
    except (UnicodeDecodeError, binascii.Error, ValueError):
        raise SecretConfigurationError(
            "Secret Store request hash key format is invalid"
        ) from None
    if len(key) != 32:
        raise SecretConfigurationError(
            "Secret Store request hash key must be 256 bits"
        )
    return key


def _read_secure_file(path: Path) -> bytes:
    try:
        before = path.lstat()
    except OSError:
        raise SecretConfigurationError(
            "Secret Store request hash key file is unavailable"
        ) from None
    if (
        not stat.S_ISREG(before.st_mode)
        or path.is_symlink()
        or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
        or before.st_uid not in {0, os.geteuid()}
        or not 1 <= before.st_size <= _MAX_HASH_KEY_FILE_BYTES
    ):
        raise SecretConfigurationError(
            "Secret Store request hash key file security policy failed"
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                opened.st_ino != before.st_ino
                or opened.st_dev != before.st_dev
                or opened.st_size != before.st_size
                or stat.S_IMODE(opened.st_mode) not in {0o400, 0o600}
            ):
                raise SecretConfigurationError(
                    "Secret Store request hash key file changed during validation"
                )
            raw = os.read(descriptor, _MAX_HASH_KEY_FILE_BYTES + 1)
            after = os.fstat(descriptor)
            if (
                len(raw) != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
                or after.st_ctime_ns != opened.st_ctime_ns
            ):
                raise SecretConfigurationError(
                    "Secret Store request hash key file changed during validation"
                )
        finally:
            os.close(descriptor)
    except SecretConfigurationError:
        raise
    except OSError:
        raise SecretConfigurationError(
            "Secret Store request hash key file cannot be read securely"
        ) from None
    return raw


__all__ = [
    "MASTER_KEYRING_ENV",
    "REQUEST_HASH_KEY_ENV",
    "SecretPostgresCryptoConfig",
    "load_postgres_crypto_config",
]
