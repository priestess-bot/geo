"""Secret-file, keyring-format, and cross-domain isolation preflight checks."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping
import hashlib
import os
from pathlib import Path
import re
import stat

from scripts.production_preflight_common import has_symlink_component, strict_json_object
from scripts.production_preflight_contracts import (
    APPLICATION_SECRET_FILE_FIELDS,
    ISOLATED_RECOVERY_SECRET_FIELDS,
    PreflightIssue,
    STRICT_0600_SECRET_FILE_FIELDS,
)


_MAX_SECRET_BYTES = 65_536
_MASTER_KEYRING_FORMAT = "geo-master-keyring-v1"
_BACKUP_KEYRING_FORMAT = "geo-backup-keyring-v1"
_SYNTHETIC_KEY_VERSION = re.compile(r"^[1-9][0-9]{0,9}$")


def validate_secret_file(
    field: str,
    value: str,
    issues: list[PreflightIssue],
    *,
    application_owner: Callable[[], tuple[int, int]],
    current_euid: int,
) -> bytes | None:
    path = Path(value)
    if not path.is_absolute():
        issues.append(PreflightIssue("SECRET_PATH_NOT_ABSOLUTE", field))
        return None
    if has_symlink_component(path):
        issues.append(PreflightIssue("SECRET_FILE_NOT_REGULAR", field))
        return None
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        issues.append(PreflightIssue("SECRET_FILE_NOT_FOUND", field))
        return None
    except OSError:
        issues.append(PreflightIssue("SECRET_FILE_UNREADABLE", field))
        return None
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        issues.append(PreflightIssue("SECRET_FILE_NOT_REGULAR", field))
        return None
    if field == "GEO_BACKUP_KEYRING_FILE" and metadata.st_uid not in {0, current_euid}:
        issues.append(PreflightIssue("SECRET_FILE_OWNER", field))
    if field in APPLICATION_SECRET_FILE_FIELDS:
        expected_uid, expected_gid = application_owner()
        if metadata.st_uid != expected_uid or metadata.st_gid != expected_gid:
            issues.append(PreflightIssue("SECRET_FILE_OWNER", field))
    allowed_modes = {0o600} if field in STRICT_0600_SECRET_FILE_FIELDS else {0o400, 0o600}
    if stat.S_IMODE(metadata.st_mode) not in allowed_modes:
        issues.append(PreflightIssue("SECRET_FILE_PERMISSIONS", field))
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                opened.st_ino != metadata.st_ino
                or opened.st_dev != metadata.st_dev
                or opened.st_size != metadata.st_size
                or opened.st_uid != metadata.st_uid
                or opened.st_gid != metadata.st_gid
                or opened.st_mode != metadata.st_mode
            ):
                issues.append(PreflightIssue("SECRET_FILE_CHANGED", field))
                return None
            content = os.read(descriptor, _MAX_SECRET_BYTES + 1)
        finally:
            os.close(descriptor)
    except OSError:
        issues.append(PreflightIssue("SECRET_FILE_UNREADABLE", field))
        return None
    if len(content) > _MAX_SECRET_BYTES:
        issues.append(PreflightIssue("SECRET_FILE_TOO_LARGE", field))
        return None
    if not content.strip():
        issues.append(PreflightIssue("SECRET_FILE_EMPTY", field))
        return None
    return content


def validate_key_material(
    values: dict[str, str],
    contents: dict[str, bytes],
    issues: list[PreflightIssue],
) -> None:
    domain_material: dict[str, frozenset[bytes]] = {}
    backup_field = "GEO_BACKUP_KEYRING_FILE"
    backup_path = values.get(backup_field, "").strip()
    if backup_path and backup_field in contents:
        try:
            from scripts.backup_envelope import BackupSecurityError, load_backup_keyring

            load_backup_keyring(Path(backup_path))
            domain_material[backup_field] = _backup_key_material(contents[backup_field])
        except (BackupSecurityError, OSError, ValueError):
            issues.append(PreflightIssue("SECRET_CONTENT_INVALID", backup_field))

    for field in (
        "GEO_SECRET_STORE_MASTER_KEYRING_FILE",
        "GEO_PROVIDER_ARTIFACT_KEYRING_FILE",
        "GEO_RECOMMENDATION_ARTIFACT_KEYRING_FILE",
        "GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE",
    ):
        content = contents.get(field)
        if content is None:
            continue
        try:
            domain_material[field] = _master_key_material(content)
        except ValueError:
            issues.append(PreflightIssue("SECRET_CONTENT_INVALID", field))

    synthetic_field = "GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE"
    if synthetic_field in contents:
        try:
            domain_material[synthetic_field] = _synthetic_key_material(
                contents[synthetic_field]
            )
        except ValueError:
            issues.append(PreflightIssue("SECRET_CONTENT_INVALID", synthetic_field))

    hash_field = "GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE"
    if hash_field in contents:
        try:
            hash_key = base64.b64decode(contents[hash_field].strip(), validate=True)
            if len(hash_key) != 32:
                raise ValueError
            domain_material[hash_field] = frozenset({hash_key})
        except (binascii.Error, ValueError):
            issues.append(PreflightIssue("SECRET_CONTENT_INVALID", hash_field))

    restore_password_field = "GEO_RESTORE_SMOKE_PASSWORD_FILE"
    restore_password = contents.get(restore_password_field)
    if restore_password is not None:
        password_material = {restore_password.strip()}
        try:
            decoded_password = base64.b64decode(restore_password.strip(), validate=True)
        except (binascii.Error, ValueError):
            decoded_password = b""
        if len(decoded_password) == 32:
            password_material.add(decoded_password)
        domain_material[restore_password_field] = frozenset(password_material)

    fields = sorted(domain_material)
    for index, field in enumerate(fields):
        for other in fields[index + 1 :]:
            if domain_material[field].isdisjoint(domain_material[other]):
                continue
            issues.append(PreflightIssue("SECRET_KEY_MATERIAL_REUSED", field))
            issues.append(PreflightIssue("SECRET_KEY_MATERIAL_REUSED", other))


def validate_key_domain_isolation(
    values: dict[str, str],
    contents: dict[str, bytes],
    issues: list[PreflightIssue],
) -> None:
    configured = {
        field: Path(values[field]).resolve(strict=False)
        for field in ISOLATED_RECOVERY_SECRET_FIELDS
        if values.get(field, "").strip()
    }
    _report_duplicate_values(configured, "SECRET_PATH_COLLISION", issues)

    inodes: dict[str, tuple[int, int]] = {}
    for field, path in configured.items():
        try:
            metadata = path.lstat()
        except OSError:
            continue
        if stat.S_ISREG(metadata.st_mode) and not path.is_symlink():
            inodes[field] = (metadata.st_dev, metadata.st_ino)
    _report_duplicate_values(inodes, "SECRET_INODE_COLLISION", issues)

    content_fingerprints = {
        field: hashlib.sha256(content).digest()
        for field, content in contents.items()
        if field in ISOLATED_RECOVERY_SECRET_FIELDS
    }
    _report_duplicate_values(content_fingerprints, "SECRET_CONTENT_REUSED", issues)
    root_value = values.get("GEO_BACKUP_ROOT", "").strip()
    if not root_value:
        return
    root = Path(root_value).resolve(strict=False)
    for field, path in configured.items():
        if path == root or path.is_relative_to(root):
            issues.append(PreflightIssue("SECRET_INSIDE_BACKUP_ROOT", field))
    restore_value = values.get("GEO_RESTORE_TMPFS_ROOT", "").strip()
    if not restore_value:
        return
    restore_root = Path(restore_value).resolve(strict=False)
    if (
        restore_root == root
        or restore_root.is_relative_to(root)
        or root.is_relative_to(restore_root)
    ):
        issues.append(PreflightIssue("DIRECTORY_PATH_COLLISION", "GEO_RESTORE_TMPFS_ROOT"))
    for field, path in configured.items():
        if path == restore_root or path.is_relative_to(restore_root):
            issues.append(PreflightIssue("SECRET_INSIDE_RESTORE_TMPFS_ROOT", field))


def _master_key_material(raw: bytes) -> frozenset[bytes]:
    payload = strict_json_object(raw)
    if set(payload) != {"format", "active_version", "keys"}:
        raise ValueError
    active_version = payload["active_version"]
    encoded_keys = payload["keys"]
    if (
        payload["format"] != _MASTER_KEYRING_FORMAT
        or not isinstance(active_version, int)
        or isinstance(active_version, bool)
        or not isinstance(encoded_keys, dict)
        or not encoded_keys
    ):
        raise ValueError
    decoded: dict[int, bytes] = {}
    for version_text, encoded_key in encoded_keys.items():
        if (
            not isinstance(version_text, str)
            or not version_text.isdigit()
            or str(int(version_text)) != version_text
            or int(version_text) < 1
            or not isinstance(encoded_key, str)
        ):
            raise ValueError
        try:
            material = base64.b64decode(encoded_key, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError from None
        if len(material) != 32:
            raise ValueError
        decoded[int(version_text)] = material
    if active_version not in decoded or len(set(decoded.values())) != len(decoded):
        raise ValueError
    return frozenset(decoded.values())


def _backup_key_material(raw: bytes) -> frozenset[bytes]:
    payload = strict_json_object(raw)
    entries = payload.get("keys")
    if (
        set(payload) != {"format", "active_version", "keys"}
        or payload["format"] != _BACKUP_KEYRING_FORMAT
        or not isinstance(entries, list)
    ):
        raise ValueError
    materials: list[bytes] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
            raise ValueError
        try:
            material = base64.b64decode(entry["key"], validate=True)
        except (binascii.Error, ValueError):
            raise ValueError from None
        if len(material) != 32:
            raise ValueError
        materials.append(material)
    if not materials or len(set(materials)) != len(materials):
        raise ValueError
    return frozenset(materials)


def _synthetic_key_material(raw: bytes) -> frozenset[bytes]:
    payload = strict_json_object(raw)
    active_version = payload.get("active_version")
    encoded_keys = payload.get("keys")
    if (
        set(payload) != {"schema_version", "active_version", "keys"}
        or payload["schema_version"] != 1
        or not isinstance(active_version, str)
        or _SYNTHETIC_KEY_VERSION.fullmatch(active_version) is None
        or not isinstance(encoded_keys, dict)
        or not encoded_keys
        or active_version not in encoded_keys
    ):
        raise ValueError
    materials: list[bytes] = []
    for version, encoded_key in encoded_keys.items():
        if (
            not isinstance(version, str)
            or _SYNTHETIC_KEY_VERSION.fullmatch(version) is None
            or not isinstance(encoded_key, str)
        ):
            raise ValueError
        try:
            material = base64.b64decode(encoded_key, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError from None
        if len(material) != 32:
            raise ValueError
        materials.append(material)
    if len(set(materials)) != len(materials):
        raise ValueError
    return frozenset(materials)


def _report_duplicate_values(
    values: Mapping[str, object],
    code: str,
    issues: list[PreflightIssue],
) -> None:
    fields = sorted(values)
    for index, field in enumerate(fields):
        if any(values[field] == values[other] for other in fields[index + 1 :]):
            issues.append(PreflightIssue(code, field))
        if any(values[field] == values[other] for other in fields[:index]):
            issues.append(PreflightIssue(code, field))


__all__ = [
    "validate_key_domain_isolation",
    "validate_key_material",
    "validate_secret_file",
]
