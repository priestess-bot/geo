"""Versioned, file-backed key derivation for Synthetic artifact encryption."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from geo_core.secrets.models import SecretValue
from geo_core.synthetic_lab.raw_artifact_governance import ArtifactStorageTier


_VERSION = re.compile(r"^[1-9][0-9]{0,9}$")
_DERIVATION_SALT = b"geo-synthetic-artifact-keyring-v1\0"
_MAX_KEYRING_BYTES = 65_536


class ArtifactKeyringConfigurationError(RuntimeError):
    """The dedicated Synthetic artifact keyring is absent or malformed."""


@dataclass(frozen=True, kw_only=True, repr=False)
class SyntheticArtifactKeyring:
    active_version: str
    keys: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if _VERSION.fullmatch(self.active_version) is None:
            raise ArtifactKeyringConfigurationError("artifact active key version is invalid")
        copied = {version: bytes(key) for version, key in self.keys.items()}
        if not copied or self.active_version not in copied:
            raise ArtifactKeyringConfigurationError("artifact active key version is unavailable")
        if any(_VERSION.fullmatch(version) is None for version in copied):
            raise ArtifactKeyringConfigurationError("artifact key version is invalid")
        if any(len(key) != 32 for key in copied.values()):
            raise ArtifactKeyringConfigurationError("artifact root keys must be 256 bits")
        if len(set(copied.values())) != len(copied):
            raise ArtifactKeyringConfigurationError(
                "artifact key versions must not reuse key material"
            )
        object.__setattr__(self, "keys", MappingProxyType(copied))

    def __repr__(self) -> str:
        return "SyntheticArtifactKeyring([REDACTED])"

    def resolve(
        self,
        *,
        project_id: UUID,
        storage_tier: ArtifactStorageTier,
    ) -> tuple[str, SecretValue]:
        return self.resolve_version(
            project_id=project_id,
            storage_tier=storage_tier,
            version=self.active_version,
        )

    def resolve_version(
        self,
        *,
        project_id: UUID,
        storage_tier: ArtifactStorageTier,
        version: str,
    ) -> tuple[str, SecretValue]:
        try:
            root = self.keys[version]
        except KeyError as error:
            raise ArtifactKeyringConfigurationError(
                "requested artifact key version is unavailable"
            ) from error
        tier = ArtifactStorageTier(storage_tier)
        info = f"{project_id}:{tier.value}".encode("ascii")
        derived = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_DERIVATION_SALT,
            info=info,
        ).derive(root)
        return version, SecretValue(derived)


def load_synthetic_artifact_keyring(path: str | Path) -> SyntheticArtifactKeyring:
    source = Path(path)
    try:
        payload = json.loads(_read_secure_keyring(source).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactKeyringConfigurationError(
            "Synthetic artifact keyring cannot be read"
        ) from error
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "active_version",
        "keys",
    }:
        raise ArtifactKeyringConfigurationError("Synthetic artifact keyring schema is invalid")
    if payload["schema_version"] != 1 or not isinstance(payload["active_version"], str):
        raise ArtifactKeyringConfigurationError("Synthetic artifact keyring version is invalid")
    encoded_keys = payload["keys"]
    if not isinstance(encoded_keys, dict) or any(
        not isinstance(version, str) or not isinstance(value, str)
        for version, value in encoded_keys.items()
    ):
        raise ArtifactKeyringConfigurationError("Synthetic artifact key map is invalid")
    try:
        keys = {
            version: base64.b64decode(value, validate=True)
            for version, value in encoded_keys.items()
        }
    except (binascii.Error, ValueError) as error:
        raise ArtifactKeyringConfigurationError(
            "Synthetic artifact key material is invalid"
        ) from error
    return SyntheticArtifactKeyring(
        active_version=payload["active_version"],
        keys=keys,
    )


def _read_secure_keyring(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ArtifactKeyringConfigurationError(
            "Synthetic artifact keyring cannot be read"
        ) from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
            or before.st_uid not in {0, os.geteuid()}
            or not 1 <= before.st_size <= _MAX_KEYRING_BYTES
        ):
            raise ArtifactKeyringConfigurationError(
                "Synthetic artifact keyring file security is invalid"
            )
        value = os.read(descriptor, _MAX_KEYRING_BYTES + 1)
        after = os.fstat(descriptor)
        if len(value) > _MAX_KEYRING_BYTES or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ArtifactKeyringConfigurationError(
                "Synthetic artifact keyring changed while reading"
            )
        return value
    finally:
        os.close(descriptor)


__all__ = [
    "ArtifactKeyringConfigurationError",
    "SyntheticArtifactKeyring",
    "load_synthetic_artifact_keyring",
]
