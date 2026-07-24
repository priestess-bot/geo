"""Safely extract and verify the per-object inventory in a MinIO backup tar."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile


_SOURCE_BUCKETS = frozenset(
    {
        "geo-artifacts",
        "geo-restricted-recommendation-artifacts",
        "geo-restricted-workflow-c-artifacts",
        "geo-synthetic-style-derived",
        "geo-synthetic-style-raw",
    }
)
_INVENTORY_LINE = re.compile(
    r"^([0-9a-f]{64}) [ *](buckets/(?:geo-artifacts|"
    r"geo-restricted-recommendation-artifacts|"
    r"geo-restricted-workflow-c-artifacts|"
    r"geo-synthetic-style-derived|geo-synthetic-style-raw)/[ -~]+)$"
)
_CHUNK_SIZE = 1024 * 1024


class MinioBackupError(RuntimeError):
    pass


def verify_minio_tar(
    archive: Path,
    destination: Path,
    *,
    expected_object_count: int,
    expected_bucket_object_counts: Mapping[str, int],
) -> dict[str, object]:
    if expected_object_count < 0:
        raise MinioBackupError("expected object count is invalid")
    expected_buckets = _bucket_counts(expected_bucket_object_counts)
    if sum(expected_buckets.values()) != expected_object_count:
        raise MinioBackupError("expected MinIO bucket counts are inconsistent")
    _require_file(archive)
    _require_directory(destination)
    seen: set[str] = set()
    object_names: set[str] = set()
    try:
        with tarfile.open(archive, mode="r:") as bundle:
            for member in bundle:
                name = _safe_member_name(member.name)
                if name in seen:
                    raise MinioBackupError("MinIO archive contains duplicate entries")
                seen.add(name)
                if not _expected_archive_member(name):
                    raise MinioBackupError("MinIO archive contains an unexpected entry")
                target = destination / name
                if member.isdir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    target.chmod(0o700)
                    continue
                if not member.isfile():
                    raise MinioBackupError("MinIO archive contains a non-regular entry")
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                target.parent.chmod(0o700)
                source = bundle.extractfile(member)
                if source is None:
                    raise MinioBackupError("MinIO archive entry cannot be read")
                descriptor = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                with source, os.fdopen(descriptor, "wb") as output:
                    shutil.copyfileobj(source, output, _CHUNK_SIZE)
                    output.flush()
                    os.fsync(output.fileno())
                if name.startswith("buckets/") and member.isfile():
                    object_names.add(name)
    except (OSError, tarfile.TarError) as error:
        raise MinioBackupError("MinIO archive cannot be verified") from error

    inventory_path = destination / "objects.sha256"
    if not inventory_path.is_file():
        raise MinioBackupError("MinIO object inventory is missing")
    inventory = _parse_inventory(inventory_path)
    if set(inventory) != object_names or len(object_names) != expected_object_count:
        raise MinioBackupError("MinIO object inventory count does not match")
    for name, expected_hash in inventory.items():
        if not _constant_time_equal(_sha256(destination / name), expected_hash):
            raise MinioBackupError("MinIO object checksum does not match")
    observed_buckets = {
        bucket: sum(
            name.startswith(f"buckets/{bucket}/") for name in object_names
        )
        for bucket in sorted(_SOURCE_BUCKETS)
    }
    if observed_buckets != expected_buckets:
        raise MinioBackupError("MinIO per-bucket object counts do not match")
    return {
        "bucket_object_counts": observed_buckets,
        "object_count": len(object_names),
        "per_object_sha256_verified": True,
    }


def _parse_inventory(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError):
        raise MinioBackupError("MinIO object inventory is invalid") from None
    result: dict[str, str] = {}
    for line in lines:
        match = _INVENTORY_LINE.fullmatch(line)
        if match is None:
            raise MinioBackupError("MinIO object inventory is invalid")
        digest, name = match.groups()
        _safe_member_name(name)
        if name in result:
            raise MinioBackupError("MinIO object inventory is duplicated")
        result[name] = digest
    return result


def _expected_archive_member(name: str) -> bool:
    if name in {"buckets", "objects.sha256"}:
        return True
    parts = PurePosixPath(name).parts
    return len(parts) >= 2 and parts[0] == "buckets" and parts[1] in _SOURCE_BUCKETS


def _bucket_counts(value: Mapping[str, int]) -> dict[str, int]:
    if set(value) != set(_SOURCE_BUCKETS):
        raise MinioBackupError("expected MinIO bucket identities are invalid")
    normalized: dict[str, int] = {}
    for bucket in sorted(_SOURCE_BUCKETS):
        count = value[bucket]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise MinioBackupError("expected MinIO bucket count is invalid")
        normalized[bucket] = count
    return normalized


def _bucket_counts_json(value: str) -> dict[str, int]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        raise MinioBackupError("expected MinIO bucket counts are invalid") from None
    if not isinstance(parsed, dict):
        raise MinioBackupError("expected MinIO bucket counts are invalid")
    return _bucket_counts(parsed)


def _safe_member_name(value: str) -> str:
    candidate = PurePosixPath(value.removeprefix("./"))
    if (
        not value
        or value.startswith("/")
        or candidate.is_absolute()
        or ".." in candidate.parts
        or any(part in {"", "."} for part in candidate.parts)
        or any(ord(character) < 32 or character == "\\" for character in value)
    ):
        raise MinioBackupError("MinIO archive path is unsafe")
    return candidate.as_posix()


def _require_file(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError:
        raise MinioBackupError("MinIO archive is unavailable") from None
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise MinioBackupError("MinIO archive permissions are invalid")


def _require_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError:
        raise MinioBackupError("MinIO restore directory is unavailable") from None
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise MinioBackupError("MinIO restore directory permissions are invalid")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _constant_time_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a decrypted MinIO backup tar.")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-object-count", type=int, required=True)
    parser.add_argument("--expected-bucket-object-counts-json", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_minio_tar(
            args.archive,
            args.destination,
            expected_object_count=args.expected_object_count,
            expected_bucket_object_counts=_bucket_counts_json(
                args.expected_bucket_object_counts_json
            ),
        )
    except (MinioBackupError, OSError):
        print("MinIO backup verification failed", file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
