from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


RequestFn = Callable[[str, str, Mapping[str, str], bytes], tuple[int, Mapping[str, str], bytes]]


class ObjectStoreError(RuntimeError):
    """Raised when S3-compatible object storage cannot archive an artifact."""


@dataclass(frozen=True)
class StoredObject:
    uri: str
    bucket: str
    key: str
    content_type: str
    content_hash: str
    etag: str | None


@dataclass(frozen=True)
class RetrievedObject:
    content: bytes
    bucket: str
    key: str
    content_type: str
    content_hash: str
    etag: str | None


def parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlsplit(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ObjectStoreError(f"Invalid S3 URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


class S3CompatibleObjectStore:
    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        auto_create_bucket: bool = True,
        requester: RequestFn | None = None,
    ) -> None:
        if not endpoint:
            raise ObjectStoreError("OBJECT_STORE_ENDPOINT is required")
        if not bucket:
            raise ObjectStoreError("OBJECT_STORE_BUCKET is required")
        if not access_key or not secret_key:
            raise ObjectStoreError(
                "OBJECT_STORE_ACCESS_KEY and OBJECT_STORE_SECRET_KEY are required"
            )
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.auto_create_bucket = auto_create_bucket
        self._requester = requester or _default_requester
        self._bucket_ready = False

    def ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        method = "PUT" if self.auto_create_bucket else "HEAD"
        status, _headers, body = self._signed_request(
            method=method,
            bucket=self.bucket,
            key=None,
            body=b"",
            content_type="application/octet-stream" if self.auto_create_bucket else None,
        )
        accepted_statuses = {200, 201, 204, 409} if self.auto_create_bucket else {200, 204}
        if status not in accepted_statuses:
            action = "create" if self.auto_create_bucket else "readiness HEAD"
            raise ObjectStoreError(f"Bucket {action} failed: status={status} body={body[:200]!r}")
        self._bucket_ready = True

    def put_s3_uri(
        self,
        *,
        uri: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObject:
        bucket, key = parse_s3_uri(uri)
        if bucket != self.bucket:
            raise ObjectStoreError(
                f"S3 URI bucket {bucket!r} does not match configured bucket {self.bucket!r}"
            )
        return self.put_object(
            key=key, content=content, content_type=content_type, expected_hash=expected_hash
        )

    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObject:
        self.ensure_bucket()
        payload = content.encode("utf-8") if isinstance(content, str) else content
        content_hash = hashlib.sha256(payload).hexdigest()
        if expected_hash and not hmac.compare_digest(content_hash, expected_hash):
            raise ObjectStoreError(
                f"Object content hash mismatch: key={key} expected={expected_hash} actual={content_hash}"
            )
        status, headers, body = self._signed_request(
            method="PUT",
            bucket=self.bucket,
            key=key,
            body=payload,
            content_type=content_type,
        )
        if status not in {200, 201, 204}:
            raise ObjectStoreError(
                f"Object upload failed: key={key} status={status} body={body[:200]!r}"
            )
        etag = _header(headers, "etag")
        return StoredObject(
            uri=f"s3://{self.bucket}/{key}",
            bucket=self.bucket,
            key=key,
            content_type=content_type,
            content_hash=content_hash,
            etag=etag,
        )

    def get_s3_uri(self, *, uri: str, expected_hash: str | None = None) -> RetrievedObject:
        bucket, key = parse_s3_uri(uri)
        if bucket != self.bucket:
            raise ObjectStoreError(
                f"S3 URI bucket {bucket!r} does not match configured bucket {self.bucket!r}"
            )
        return self.get_object(key=key, expected_hash=expected_hash)

    def get_object(self, *, key: str, expected_hash: str | None = None) -> RetrievedObject:
        status, headers, body = self._signed_request(
            method="GET",
            bucket=self.bucket,
            key=key,
            body=b"",
            content_type=None,
        )
        if status != 200:
            raise ObjectStoreError(
                f"Object download failed: key={key} status={status} body={body[:200]!r}"
            )
        content_hash = hashlib.sha256(body).hexdigest()
        if expected_hash and not hmac.compare_digest(content_hash, expected_hash):
            raise ObjectStoreError(
                f"Downloaded object hash mismatch: key={key} expected={expected_hash} actual={content_hash}"
            )
        return RetrievedObject(
            content=body,
            bucket=self.bucket,
            key=key,
            content_type=_header(headers, "content-type") or "application/octet-stream",
            content_hash=content_hash,
            etag=_header(headers, "etag"),
        )

    def head_object(self, *, key: str) -> bool:
        status, _headers, _body = self._signed_request(
            method="HEAD",
            bucket=self.bucket,
            key=key,
            body=b"",
            content_type=None,
        )
        return status == 200

    def _signed_request(
        self,
        *,
        method: str,
        bucket: str,
        key: str | None,
        body: bytes,
        content_type: str | None,
    ) -> tuple[int, Mapping[str, str], bytes]:
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(body).hexdigest()
        canonical_uri = _canonical_uri(bucket=bucket, key=key)
        url = f"{self.endpoint}{canonical_uri}"
        host = urlsplit(url).netloc
        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if content_type is not None:
            headers["content-type"] = content_type
        signed_header_names = sorted(headers)
        canonical_headers = "".join(
            f"{name}:{headers[name].strip()}\n" for name in signed_header_names
        )
        signed_headers = ";".join(signed_header_names)
        canonical_request = "\n".join(
            [
                method,
                canonical_uri,
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signature = _signature_key(self.secret_key, date_stamp, self.region).hex_digest(
            string_to_sign
        )
        request_headers = {
            **headers,
            "authorization": (
                "AWS4-HMAC-SHA256 "
                f"Credential={self.access_key}/{credential_scope}, "
                f"SignedHeaders={signed_headers}, Signature={signature}"
            ),
        }
        return self._requester(method, url, request_headers, body)


class _SigningKey:
    def __init__(self, key: bytes) -> None:
        self.key = key

    def hex_digest(self, value: str) -> str:
        return hmac.new(self.key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _signature_key(secret_key: str, date_stamp: str, region: str) -> _SigningKey:
    key_date = hmac.new(
        ("AWS4" + secret_key).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256
    ).digest()
    key_region = hmac.new(key_date, region.encode("utf-8"), hashlib.sha256).digest()
    key_service = hmac.new(key_region, b"s3", hashlib.sha256).digest()
    key_signing = hmac.new(key_service, b"aws4_request", hashlib.sha256).digest()
    return _SigningKey(key_signing)


def _canonical_uri(*, bucket: str, key: str | None) -> str:
    parts = [bucket]
    if key:
        parts.extend(part for part in key.split("/") if part)
    return "/" + "/".join(quote(part, safe="-_.~") for part in parts)


def _default_requester(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes,
) -> tuple[int, Mapping[str, str], bytes]:
    data = None if method == "HEAD" else body
    request = Request(url, data=data, headers=dict(headers), method=method)
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()
    except URLError as exc:
        raise ObjectStoreError(f"Object store request failed: {exc}") from exc


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None
