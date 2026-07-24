"""Fail-closed loading of a versioned keyring from a Docker Secret file."""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
import stat
from typing import Any

from .crypto import MasterKeyring
from .errors import SecretConfigurationError
from .models import KEYRING_FORMAT


_MAX_KEYRING_BYTES = 64 * 1024


def load_master_keyring_from_docker_secret(path: str | os.PathLike[str]) -> MasterKeyring:
    """Load strict JSON without ever falling back to environment variables.

    Format::

        {"format":"geo-master-keyring-v1","active_version":2,
         "keys":{"1":"<base64 32 bytes>","2":"<base64 32 bytes>"}}
    """

    file_path = Path(path)
    try:
        file_stat = file_path.lstat()
    except OSError:
        raise SecretConfigurationError("Docker Secret keyring file is unavailable") from None
    if not stat.S_ISREG(file_stat.st_mode) or file_path.is_symlink():
        raise SecretConfigurationError("Docker Secret keyring must be a regular file")
    if stat.S_IMODE(file_stat.st_mode) not in {0o400, 0o600}:
        raise SecretConfigurationError("Docker Secret keyring permissions are too broad")
    if file_stat.st_uid not in {0, os.geteuid()}:
        raise SecretConfigurationError("Docker Secret keyring owner is not trusted")
    if file_stat.st_size < 2 or file_stat.st_size > _MAX_KEYRING_BYTES:
        raise SecretConfigurationError("Docker Secret keyring size is invalid")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(file_path, flags)
        try:
            opened_stat = os.fstat(descriptor)
            if (
                opened_stat.st_ino != file_stat.st_ino
                or opened_stat.st_dev != file_stat.st_dev
                or stat.S_IMODE(opened_stat.st_mode) not in {0o400, 0o600}
                or opened_stat.st_size != file_stat.st_size
            ):
                raise SecretConfigurationError("Docker Secret keyring changed during validation")
            chunks: list[bytes] = []
            remaining = _MAX_KEYRING_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            final_stat = os.fstat(descriptor)
            if (
                final_stat.st_size != opened_stat.st_size
                or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
                or final_stat.st_ctime_ns != opened_stat.st_ctime_ns
            ):
                raise SecretConfigurationError("Docker Secret keyring changed during validation")
        finally:
            os.close(descriptor)
    except SecretConfigurationError:
        raise
    except OSError:
        raise SecretConfigurationError("Docker Secret keyring cannot be read securely") from None
    if len(raw) != file_stat.st_size or len(raw) > _MAX_KEYRING_BYTES:
        raise SecretConfigurationError("Docker Secret keyring size is invalid")
    return _parse_keyring(raw)


def _parse_keyring(raw: bytes) -> MasterKeyring:
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, SecretConfigurationError):
        raise SecretConfigurationError("Docker Secret keyring format is invalid") from None
    if not isinstance(payload, dict) or set(payload) != {"format", "active_version", "keys"}:
        raise SecretConfigurationError("Docker Secret keyring format is invalid")
    if payload["format"] != KEYRING_FORMAT:
        raise SecretConfigurationError("Docker Secret keyring format is unsupported")
    active_version = payload["active_version"]
    encoded_keys = payload["keys"]
    if (
        not isinstance(active_version, int)
        or isinstance(active_version, bool)
        or not isinstance(encoded_keys, dict)
        or not encoded_keys
    ):
        raise SecretConfigurationError("Docker Secret keyring metadata is invalid")

    keys: dict[int, bytes] = {}
    for raw_version, encoded_key in encoded_keys.items():
        if not isinstance(raw_version, str) or not raw_version.isdigit() or not isinstance(encoded_key, str):
            raise SecretConfigurationError("Docker Secret keyring entry is invalid")
        version = int(raw_version)
        if version < 1 or str(version) != raw_version:
            raise SecretConfigurationError("Docker Secret keyring entry is invalid")
        try:
            key = base64.b64decode(encoded_key, validate=True)
        except (binascii.Error, ValueError):
            raise SecretConfigurationError("Docker Secret keyring entry is invalid") from None
        if len(key) != 32:
            raise SecretConfigurationError("Docker Secret keyring entry is invalid")
        keys[version] = key
    return MasterKeyring(keys=keys, active_version=active_version)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SecretConfigurationError("Docker Secret keyring contains duplicate fields")
        result[key] = value
    return result
