"""Streaming authenticated encryption for GEO backup artifacts."""

from __future__ import annotations

import argparse
import base64
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import tempfile
from typing import BinaryIO, Never

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


KEYRING_FORMAT = "geo-backup-keyring-v1"
ENVELOPE_FORMAT = "geo-backup-envelope-v1"
ALGORITHM = "AES-256-GCM"
MAGIC = b"GEOBAK1\x00"
CHUNK_SIZE = 1024 * 1024
TAG_SIZE = 16
MAX_HEADER_SIZE = 16 * 1024
MAX_KEYRING_SIZE = 64 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class BackupSecurityError(RuntimeError):
    """A backup cannot be trusted without revealing key or payload material."""


class BackupKeyring:
    """Versioned backup keys with redacted representation."""

    __slots__ = ("__keys", "active_version")

    def __init__(self, *, keys: Mapping[int, bytes], active_version: int) -> None:
        copied = {version: bytes(value) for version, value in keys.items()}
        if not copied or any(version < 1 or len(value) != 32 for version, value in copied.items()):
            raise BackupSecurityError("backup keyring entries are invalid")
        if active_version not in copied:
            raise BackupSecurityError("backup keyring active version is unavailable")
        self.__keys = copied
        self.active_version = active_version

    @property
    def versions(self) -> tuple[int, ...]:
        return tuple(sorted(self.__keys))

    def key(self, version: int) -> bytes:
        try:
            return bytes(self.__keys[version])
        except KeyError:
            raise BackupSecurityError("backup key version is unavailable") from None

    def __repr__(self) -> str:
        return (
            f"BackupKeyring(active_version={self.active_version}, "
            f"versions={self.versions!r}, keys=[REDACTED])"
        )

    def __reduce__(self) -> Never:
        raise BackupSecurityError("backup keyrings cannot be serialized")


@dataclass(frozen=True, kw_only=True)
class EnvelopeMetadata:
    backup_id: str
    artifact: str
    key_version: int
    encrypted_sha256: str
    encrypted_size: int


def load_backup_keyring(path: Path) -> BackupKeyring:
    raw = _read_secure_file(path, maximum=MAX_KEYRING_SIZE, allowed_modes={0o400, 0o600})
    payload = _strict_json(raw, "backup keyring")
    if not isinstance(payload, dict) or set(payload) != {"format", "active_version", "keys"}:
        raise BackupSecurityError("backup keyring structure is invalid")
    if payload["format"] != KEYRING_FORMAT:
        raise BackupSecurityError("backup keyring format is unsupported")
    active_version = _positive_int(payload["active_version"], "backup active key version")
    entries = payload["keys"]
    if not isinstance(entries, list) or not entries:
        raise BackupSecurityError("backup keyring entries are invalid")
    keys: dict[int, bytes] = {}
    active_entries = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"version", "status", "key"}:
            raise BackupSecurityError("backup keyring entry is invalid")
        version = _positive_int(entry["version"], "backup key version")
        status_value = entry["status"]
        if status_value not in {"encrypt_decrypt", "decrypt_only"}:
            raise BackupSecurityError("backup keyring entry status is invalid")
        if version in keys:
            raise BackupSecurityError("backup keyring versions are duplicated")
        keys[version] = _base64(entry["key"], expected_size=32, label="backup key")
        if status_value == "encrypt_decrypt":
            active_entries += 1
            if version != active_version:
                raise BackupSecurityError("backup keyring active status is inconsistent")
    if active_entries != 1:
        raise BackupSecurityError("backup keyring must contain one active key")
    return BackupKeyring(keys=keys, active_version=active_version)


def encrypt_stream(
    source: BinaryIO,
    destination: Path,
    *,
    keyring: BackupKeyring,
    backup_id: str,
    artifact: str,
) -> EnvelopeMetadata:
    _require_identifier(backup_id, "backup ID")
    _require_identifier(artifact, "backup artifact")
    _require_secure_directory(destination.parent)
    version = keyring.active_version
    dek = os.urandom(32)
    data_nonce = os.urandom(12)
    wrap_nonce = os.urandom(12)
    wrap_aad = _wrap_aad(version=version, backup_id=backup_id, artifact=artifact)
    wrapped_dek = AESGCM(_derive(keyring.key(version), b"dek-wrap", version)).encrypt(
        wrap_nonce,
        dek,
        wrap_aad,
    )
    header = _canonical_json(
        {
            "algorithm": ALGORITHM,
            "artifact": artifact,
            "backup_id": backup_id,
            "data_nonce": _encode64(data_nonce),
            "format": ENVELOPE_FORMAT,
            "key_version": version,
            "wrap_nonce": _encode64(wrap_nonce),
            "wrapped_dek": _encode64(wrapped_dek),
        }
    )
    temporary = destination.parent / f".{destination.name}.{os.getpid()}.tmp"
    try:
        with _exclusive_writer(temporary) as output:
            output.write(MAGIC)
            output.write(struct.pack(">I", len(header)))
            output.write(header)
            encryptor = Cipher(algorithms.AES(dek), modes.GCM(data_nonce)).encryptor()
            encryptor.authenticate_additional_data(header)
            while chunk := source.read(CHUNK_SIZE):
                output.write(encryptor.update(chunk))
            output.write(encryptor.finalize())
            output.write(encryptor.tag)
            output.flush()
            os.fsync(output.fileno())
        _commit_new_file(temporary, destination)
        _fsync_directory(destination.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return inspect_envelope(destination)


def inspect_envelope(path: Path) -> EnvelopeMetadata:
    with _open_secure_reader(path, allowed_modes={0o600}) as source:
        encrypted_size = os.fstat(source.fileno()).st_size
        header, payload = _read_header(source)
        source.seek(0)
        encrypted_sha256 = _sha256_stream(source)
    return EnvelopeMetadata(
        backup_id=_identifier_value(payload.get("backup_id"), "backup ID"),
        artifact=_identifier_value(payload.get("artifact"), "backup artifact"),
        key_version=_positive_int(payload.get("key_version"), "backup key version"),
        encrypted_sha256=encrypted_sha256,
        encrypted_size=encrypted_size,
    )


def decrypt_authenticated_to_stream(
    source_path: Path,
    destination: BinaryIO,
    *,
    keyring: BackupKeyring,
    expected_backup_id: str,
    expected_artifact: str,
    staging_directory: Path,
    expected_encrypted_sha256: str | None = None,
    expected_encrypted_size: int | None = None,
) -> None:
    _require_secure_directory(staging_directory)
    temporary_name: str | None = None
    try:
        with _open_secure_reader(source_path, allowed_modes={0o600}) as source:
            opened_size = os.fstat(source.fileno()).st_size
            opened_hash = _sha256_stream(source)
            if (
                expected_encrypted_size is not None
                and opened_size != expected_encrypted_size
                or expected_encrypted_sha256 is not None
                and not hmac.compare_digest(opened_hash, expected_encrypted_sha256)
            ):
                raise BackupSecurityError("backup envelope does not match manifest")
            source.seek(0)
            header, payload = _read_header(source)
            backup_id = _identifier_value(payload.get("backup_id"), "backup ID")
            artifact = _identifier_value(payload.get("artifact"), "backup artifact")
            if backup_id != expected_backup_id or artifact != expected_artifact:
                raise BackupSecurityError("backup envelope scope does not match manifest")
            version = _positive_int(payload.get("key_version"), "backup key version")
            data_nonce = _base64(payload.get("data_nonce"), 12, "backup data nonce")
            wrap_nonce = _base64(payload.get("wrap_nonce"), 12, "backup wrap nonce")
            wrapped_dek = _base64(payload.get("wrapped_dek"), 48, "wrapped backup key")
            try:
                dek = AESGCM(_derive(keyring.key(version), b"dek-wrap", version)).decrypt(
                    wrap_nonce,
                    wrapped_dek,
                    _wrap_aad(version=version, backup_id=backup_id, artifact=artifact),
                )
            except Exception:
                raise BackupSecurityError("backup envelope authentication failed") from None
            payload_start = source.tell()
            source.seek(0, os.SEEK_END)
            end = source.tell()
            if end - payload_start < TAG_SIZE:
                raise BackupSecurityError("backup envelope is truncated")
            source.seek(end - TAG_SIZE)
            tag = source.read(TAG_SIZE)
            source.seek(payload_start)
            remaining = end - TAG_SIZE - payload_start
            with tempfile.NamedTemporaryFile(
                mode="w+b", dir=staging_directory, prefix=".plaintext-", delete=False
            ) as staged:
                temporary_name = staged.name
                os.chmod(temporary_name, 0o600)
                decryptor = Cipher(algorithms.AES(dek), modes.GCM(data_nonce, tag)).decryptor()
                decryptor.authenticate_additional_data(header)
                try:
                    while remaining:
                        chunk = source.read(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            raise BackupSecurityError("backup envelope is truncated")
                        remaining -= len(chunk)
                        staged.write(decryptor.update(chunk))
                    staged.write(decryptor.finalize())
                except (InvalidTag, ValueError):
                    raise BackupSecurityError("backup envelope authentication failed") from None
                staged.flush()
                os.fsync(staged.fileno())
                staged.seek(0)
                shutil.copyfileobj(staged, destination, CHUNK_SIZE)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def derive_manifest_signing_key(keyring: BackupKeyring, version: int) -> bytes:
    return _derive(keyring.key(version), b"manifest-signing", version)


def canonical_json(value: object) -> bytes:
    return _canonical_json(value)


def read_canonical_json(path: Path, *, label: str) -> dict[str, object]:
    raw = _read_secure_file(path, maximum=1024 * 1024, allowed_modes={0o600})
    value = _strict_json(raw, label)
    if not isinstance(value, dict) or raw != _canonical_json(value) + b"\n":
        raise BackupSecurityError(f"{label} is not canonical")
    return value


def atomic_write(path: Path, content: bytes) -> None:
    _require_secure_directory(path.parent)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        with _exclusive_writer(temporary) as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        _commit_new_file(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _read_header(source: BinaryIO) -> tuple[bytes, dict[str, object]]:
    if source.read(len(MAGIC)) != MAGIC:
        raise BackupSecurityError("backup envelope format is invalid")
    encoded_length = source.read(4)
    if len(encoded_length) != 4:
        raise BackupSecurityError("backup envelope is truncated")
    header_size = struct.unpack(">I", encoded_length)[0]
    if not 1 <= header_size <= MAX_HEADER_SIZE:
        raise BackupSecurityError("backup envelope header is invalid")
    header = source.read(header_size)
    if len(header) != header_size:
        raise BackupSecurityError("backup envelope is truncated")
    payload = _strict_json(header, "backup envelope header")
    expected = {
        "algorithm", "artifact", "backup_id", "data_nonce", "format",
        "key_version", "wrap_nonce", "wrapped_dek",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise BackupSecurityError("backup envelope header is invalid")
    if payload["format"] != ENVELOPE_FORMAT or payload["algorithm"] != ALGORITHM:
        raise BackupSecurityError("backup envelope format is unsupported")
    if header != _canonical_json(payload):
        raise BackupSecurityError("backup envelope header is not canonical")
    return header, payload


def _derive(master: bytes, purpose: bytes, version: int) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"geo-backup-hkdf-v1",
        info=b"geo-backup-v1\x00" + purpose + b"\x00" + str(version).encode("ascii"),
    ).derive(master)


def _wrap_aad(*, version: int, backup_id: str, artifact: str) -> bytes:
    return _canonical_json(
        {
            "artifact": artifact,
            "backup_id": backup_id,
            "format": "geo-backup-dek-wrap-aad-v1",
            "key_version": version,
        }
    )


def _strict_json(raw: bytes, label: str) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise BackupSecurityError(f"{label} contains duplicate fields")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=reject_duplicates)
    except BackupSecurityError:
        raise
    except (UnicodeError, json.JSONDecodeError):
        raise BackupSecurityError(f"{label} is invalid") from None


def _read_secure_file(path: Path, *, maximum: int, allowed_modes: set[int]) -> bytes:
    try:
        with _open_secure_reader(path, allowed_modes=allowed_modes) as source:
            raw = source.read(maximum + 1)
    except OSError:
        raise BackupSecurityError("secure file cannot be read") from None
    if not raw or len(raw) > maximum:
        raise BackupSecurityError("secure file size is invalid")
    return raw


def _require_secure_regular_file(path: Path, *, allowed_modes: set[int]) -> None:
    if _has_symlink_component(path):
        raise BackupSecurityError("secure file path contains a symbolic link")
    try:
        metadata = path.lstat()
    except OSError:
        raise BackupSecurityError("secure file is unavailable") from None
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) not in allowed_modes:
        raise BackupSecurityError("secure file type or permissions are invalid")
    if metadata.st_uid not in {0, os.geteuid()}:
        raise BackupSecurityError("secure file owner is invalid")


def _open_secure_reader(path: Path, *, allowed_modes: set[int]) -> BinaryIO:
    _require_secure_regular_file(path, allowed_modes=allowed_modes)
    before = path.lstat()
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if (
            opened.st_ino != before.st_ino
            or opened.st_dev != before.st_dev
            or opened.st_size != before.st_size
            or stat.S_IMODE(opened.st_mode) not in allowed_modes
        ):
            os.close(descriptor)
            raise BackupSecurityError("secure file changed during validation")
        return os.fdopen(descriptor, "rb")
    except BackupSecurityError:
        raise
    except OSError:
        raise BackupSecurityError("secure file cannot be opened safely") from None


def _require_secure_directory(path: Path) -> None:
    if _has_symlink_component(path):
        raise BackupSecurityError("secure directory path contains a symbolic link")
    try:
        metadata = path.lstat()
    except OSError:
        raise BackupSecurityError("secure directory is unavailable") from None
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise BackupSecurityError("secure directory permissions are invalid")
    if metadata.st_uid not in {0, os.geteuid()}:
        raise BackupSecurityError("secure directory owner is invalid")


def _exclusive_writer(path: Path) -> BinaryIO:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    return os.fdopen(descriptor, "wb")


def _commit_new_file(temporary: Path, destination: Path) -> None:
    try:
        os.link(temporary, destination, follow_symlinks=False)
    except FileExistsError:
        raise BackupSecurityError("backup output already exists") from None
    except OSError:
        raise BackupSecurityError("backup output cannot be committed atomically") from None
    temporary.unlink()


def _base64(value: object, expected_size: int, label: str) -> bytes:
    if not isinstance(value, str):
        raise BackupSecurityError(f"{label} is invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise BackupSecurityError(f"{label} is invalid") from None
    if len(decoded) != expected_size or _encode64(decoded) != value:
        raise BackupSecurityError(f"{label} is invalid")
    return decoded


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise BackupSecurityError(f"{label} is invalid")
    return value


def _identifier_value(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise BackupSecurityError(f"{label} is invalid")
    _require_identifier(value, label)
    return value


def _require_identifier(value: str, label: str) -> None:
    if _IDENTIFIER.fullmatch(value) is None:
        raise BackupSecurityError(f"{label} is invalid")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("ascii")


def _encode64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _sha256_stream(source: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := source.read(CHUNK_SIZE):
        digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _has_symlink_component(path: Path) -> bool:
    candidate = path.absolute()
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Encrypt or inspect a GEO backup envelope.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    encrypt = subparsers.add_parser("encrypt")
    encrypt.add_argument("--keyring", type=Path, required=True)
    encrypt.add_argument("--backup-id", required=True)
    encrypt.add_argument("--artifact", required=True)
    encrypt.add_argument("--output", type=Path, required=True)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "encrypt":
            metadata = encrypt_stream(
                sys.stdin.buffer,
                args.output,
                keyring=load_backup_keyring(args.keyring),
                backup_id=args.backup_id,
                artifact=args.artifact,
            )
        else:
            metadata = inspect_envelope(args.file)
        print(_canonical_json(metadata.__dict__).decode("ascii"))
        return 0
    except (BackupSecurityError, OSError):
        print("backup security error: operation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
