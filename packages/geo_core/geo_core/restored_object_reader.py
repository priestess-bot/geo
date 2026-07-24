"""Read-only access to verified object-store files during isolated restore probes."""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.parse import urlsplit


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_MAX_OBJECT_BYTES = 512 * 1024 * 1024


class RestoredObjectReadError(RuntimeError):
    """A restored object cannot be read under the frozen recovery policy."""


class VerifiedRestoredObjectReader:
    """Resolve an S3 URI into a verified regular file below one fixed root."""

    def __init__(self, *, root: Path, bucket: str) -> None:
        if _BUCKET.fullmatch(bucket) is None:
            raise RestoredObjectReadError("restored object bucket is invalid")
        try:
            metadata = root.lstat()
        except OSError:
            raise RestoredObjectReadError("restored object root is unavailable") from None
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise RestoredObjectReadError("restored object root security is invalid")
        self._root = root
        self._bucket = bucket

    def __call__(self, uri: str, expected_hash: str) -> bytes:
        if _SHA256.fullmatch(expected_hash) is None:
            raise RestoredObjectReadError("restored object checksum is invalid")
        parts = self._uri_parts(uri)
        root_descriptor = _open_directory(self._root)
        try:
            parent_descriptor = root_descriptor
            opened_directories: list[int] = []
            try:
                for part in parts[:-1]:
                    child = _open_directory(part, directory_fd=parent_descriptor)
                    opened_directories.append(child)
                    parent_descriptor = child
                payload = _read_regular_file(parts[-1], directory_fd=parent_descriptor)
            finally:
                for descriptor in reversed(opened_directories):
                    os.close(descriptor)
        finally:
            os.close(root_descriptor)
        actual_hash = hashlib.sha256(payload).hexdigest()
        if not hmac.compare_digest(actual_hash, expected_hash):
            raise RestoredObjectReadError("restored object content hash changed")
        return payload

    def _uri_parts(self, uri: str) -> tuple[str, ...]:
        try:
            parsed = urlsplit(uri)
        except ValueError:
            raise RestoredObjectReadError("restored object URI is invalid") from None
        if (
            parsed.scheme != "s3"
            or parsed.netloc != self._bucket
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
        ):
            raise RestoredObjectReadError("restored object URI is outside the backup bucket")
        key = parsed.path.removeprefix("/")
        candidate = PurePosixPath(key)
        raw_parts = key.split("/")
        if (
            not key
            or candidate.is_absolute()
            or any(part in {"", ".", ".."} for part in raw_parts)
            or "%" in key
            or any(
                character == "\\" or ord(character) < 32
                for character in key
            )
        ):
            raise RestoredObjectReadError("restored object key is unsafe")
        return candidate.parts


class VerifiedRestoredObjectReaders:
    """Route verified S3 reads to a fixed set of independently restored buckets."""

    def __init__(self, readers: dict[str, VerifiedRestoredObjectReader]) -> None:
        if not readers:
            raise RestoredObjectReadError("restored object reader set is empty")
        if any(not bucket or reader is None for bucket, reader in readers.items()):
            raise RestoredObjectReadError("restored object reader set is invalid")
        self._readers = dict(readers)

    def __call__(self, uri: str, expected_hash: str) -> bytes:
        try:
            bucket = urlsplit(uri).netloc
        except ValueError:
            raise RestoredObjectReadError("restored object URI is invalid") from None
        reader = self._readers.get(bucket)
        if reader is None:
            raise RestoredObjectReadError("restored object URI is outside the backup buckets")
        return reader(uri, expected_hash)


def _open_directory(
    path: str | Path,
    *,
    directory_fd: int | None = None,
) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, dir_fd=directory_fd)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            os.close(descriptor)
            raise RestoredObjectReadError("restored object path is not a directory")
        return descriptor
    except OSError:
        raise RestoredObjectReadError("restored object directory cannot be opened") from None


def _read_regular_file(name: str, *, directory_fd: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError:
        raise RestoredObjectReadError("restored object cannot be opened") from None
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or not 1 <= before.st_size <= _MAX_OBJECT_BYTES
        ):
            raise RestoredObjectReadError("restored object file is invalid")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise RestoredObjectReadError("restored object was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise RestoredObjectReadError("restored object grew while being read")
        after = os.fstat(descriptor)
        if (
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
            raise RestoredObjectReadError("restored object changed while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


__all__ = [
    "RestoredObjectReadError",
    "VerifiedRestoredObjectReader",
    "VerifiedRestoredObjectReaders",
]
