from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from geo_core.restored_object_reader import (
    RestoredObjectReadError,
    VerifiedRestoredObjectReader,
    VerifiedRestoredObjectReaders,
)


def test_reader_returns_only_hash_verified_file_from_frozen_bucket(tmp_path: Path) -> None:
    root = _root(tmp_path)
    payload = b"authenticated encrypted artifact"
    target = root / "provider" / "attempt" / "payload.bin"
    target.parent.mkdir(parents=True, mode=0o700)
    target.write_bytes(payload)
    target.chmod(0o600)
    reader = VerifiedRestoredObjectReader(root=root, bucket="geo-artifacts")

    assert reader(
        "s3://geo-artifacts/provider/attempt/payload.bin",
        hashlib.sha256(payload).hexdigest(),
    ) == payload


@pytest.mark.parametrize(
    "uri",
    [
        "s3://other-bucket/provider/payload.bin",
        "s3://geo-artifacts/../outside.bin",
        "s3://geo-artifacts/provider/./payload.bin",
        "s3://geo-artifacts/provider/%2e%2e/payload.bin",
        "s3://geo-artifacts/provider/payload.bin?version=1",
        "https://geo-artifacts/provider/payload.bin",
        "s3://user@geo-artifacts/provider/payload.bin",
    ],
)
def test_reader_rejects_bucket_and_path_escape(tmp_path: Path, uri: str) -> None:
    reader = VerifiedRestoredObjectReader(root=_root(tmp_path), bucket="geo-artifacts")

    with pytest.raises(RestoredObjectReadError):
        reader(uri, "1" * 64)


def test_reader_rejects_symlinks_hash_mismatch_and_insecure_root(tmp_path: Path) -> None:
    root = _root(tmp_path)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"must not be read")
    (root / "linked.bin").symlink_to(outside)
    reader = VerifiedRestoredObjectReader(root=root, bucket="geo-artifacts")

    with pytest.raises(RestoredObjectReadError):
        reader("s3://geo-artifacts/linked.bin", hashlib.sha256(outside.read_bytes()).hexdigest())

    target = root / "payload.bin"
    target.write_bytes(b"payload")
    target.chmod(0o600)
    with pytest.raises(RestoredObjectReadError):
        reader("s3://geo-artifacts/payload.bin", "0" * 64)

    root.chmod(0o755)
    with pytest.raises(RestoredObjectReadError):
        VerifiedRestoredObjectReader(root=root, bucket="geo-artifacts")


def test_reader_rejects_empty_object(tmp_path: Path) -> None:
    root = _root(tmp_path)
    target = root / "empty.bin"
    target.touch(mode=0o600)
    reader = VerifiedRestoredObjectReader(root=root, bucket="geo-artifacts")

    with pytest.raises(RestoredObjectReadError):
        reader("s3://geo-artifacts/empty.bin", hashlib.sha256(b"").hexdigest())


def test_reader_set_routes_only_to_declared_restored_buckets(tmp_path: Path) -> None:
    raw_root = _root(tmp_path / "raw")
    derived_root = _root(tmp_path / "derived")
    raw_payload = b"encrypted-raw"
    derived_payload = b"derived-sample"
    (raw_root / "synthetic-raw").mkdir()
    (derived_root / "synthetic-raw").mkdir()
    (raw_root / "synthetic-raw" / "raw.bin").write_bytes(raw_payload)
    (derived_root / "synthetic-raw" / "derived.bin").write_bytes(derived_payload)
    reader = VerifiedRestoredObjectReaders(
        {
            "geo-synthetic-style-raw": VerifiedRestoredObjectReader(
                root=raw_root,
                bucket="geo-synthetic-style-raw",
            ),
            "geo-synthetic-style-derived": VerifiedRestoredObjectReader(
                root=derived_root,
                bucket="geo-synthetic-style-derived",
            ),
        }
    )

    assert reader(
        "s3://geo-synthetic-style-raw/synthetic-raw/raw.bin",
        hashlib.sha256(raw_payload).hexdigest(),
    ) == raw_payload
    assert reader(
        "s3://geo-synthetic-style-derived/synthetic-raw/derived.bin",
        hashlib.sha256(derived_payload).hexdigest(),
    ) == derived_payload
    with pytest.raises(RestoredObjectReadError, match="outside the backup buckets"):
        reader("s3://geo-artifacts/reports/nope", "a" * 64)


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "objects"
    root.mkdir(mode=0o700, parents=True)
    root.chmod(0o700)
    return root
