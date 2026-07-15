from __future__ import annotations

import hashlib
from collections.abc import Mapping

import pytest

from geo_core.object_store import (
    ObjectStoreError,
    S3CompatibleObjectStore,
    parse_s3_uri,
)


class RecordingRequester:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Mapping[str, str], bytes]] = []
        self.responses: list[tuple[int, Mapping[str, str], bytes]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.calls.append((method, url, headers, body))
        return self.responses.pop(0)


def store(requester: RecordingRequester) -> S3CompatibleObjectStore:
    return S3CompatibleObjectStore(
        endpoint="https://objects.example.test",
        bucket="geo-artifacts",
        access_key="test-access",
        secret_key="test-secret",
        requester=requester,
    )


def test_put_creates_bucket_once_and_records_content_identity() -> None:
    requester = RecordingRequester()
    requester.responses = [
        (200, {}, b""),
        (200, {"ETag": '"object-etag"'}, b""),
        (200, {}, b""),
    ]
    object_store = store(requester)

    first = object_store.put_object(
        key="placements/project/package.json",
        content=b'{"content":"verified"}',
        content_type="application/json",
    )
    object_store.put_object(
        key="placements/project/manifest.json",
        content=b"{}",
        content_type="application/json",
    )

    assert [call[0] for call in requester.calls] == ["PUT", "PUT", "PUT"]
    assert requester.calls[0][1].endswith("/geo-artifacts")
    assert requester.calls[1][1].endswith(
        "/geo-artifacts/placements/project/package.json"
    )
    assert first.uri == "s3://geo-artifacts/placements/project/package.json"
    assert first.content_hash == hashlib.sha256(b'{"content":"verified"}').hexdigest()
    assert first.etag == '"object-etag"'
    assert "test-secret" not in requester.calls[1][2]["authorization"]


def test_download_rejects_content_that_does_not_match_manifest_hash() -> None:
    requester = RecordingRequester()
    requester.responses = [(200, {"Content-Type": "application/json"}, b"tampered")]

    with pytest.raises(ObjectStoreError, match="Downloaded object hash mismatch"):
        store(requester).get_s3_uri(
            uri="s3://geo-artifacts/placements/project/package.json",
            expected_hash=hashlib.sha256(b"expected").hexdigest(),
        )


@pytest.mark.parametrize(
    "uri",
    ("https://objects.example.test/file", "s3://geo-artifacts", "s3:///file"),
)
def test_s3_uri_requires_scheme_bucket_and_key(uri: str) -> None:
    with pytest.raises(ObjectStoreError, match="Invalid S3 URI"):
        parse_s3_uri(uri)
