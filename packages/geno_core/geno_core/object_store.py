from __future__ import annotations

import hashlib
import hmac
import html
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen

from geno_core.models import EvidenceAsset, RawEvidenceRecord, RuntimeReportArtifact


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
        requester: RequestFn | None = None,
    ) -> None:
        if not endpoint:
            raise ObjectStoreError("OBJECT_STORE_ENDPOINT is required")
        if not bucket:
            raise ObjectStoreError("OBJECT_STORE_BUCKET is required")
        if not access_key or not secret_key:
            raise ObjectStoreError("OBJECT_STORE_ACCESS_KEY and OBJECT_STORE_SECRET_KEY are required")
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self._requester = requester or _default_requester
        self._bucket_ready = False

    def ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        status, _headers, body = self._signed_request(
            method="PUT",
            bucket=self.bucket,
            key=None,
            body=b"",
            content_type="application/octet-stream",
        )
        if status not in {200, 201, 204, 409}:
            raise ObjectStoreError(f"Bucket create failed: status={status} body={body[:200]!r}")
        self._bucket_ready = True

    def put_s3_uri(self, *, uri: str, content: str | bytes, content_type: str) -> StoredObject:
        bucket, key = parse_s3_uri(uri)
        if bucket != self.bucket:
            raise ObjectStoreError(f"S3 URI bucket {bucket!r} does not match configured bucket {self.bucket!r}")
        return self.put_object(key=key, content=content, content_type=content_type)

    def put_object(self, *, key: str, content: str | bytes, content_type: str) -> StoredObject:
        self.ensure_bucket()
        payload = content.encode("utf-8") if isinstance(content, str) else content
        status, headers, body = self._signed_request(
            method="PUT",
            bucket=self.bucket,
            key=key,
            body=payload,
            content_type=content_type,
        )
        if status not in {200, 201, 204}:
            raise ObjectStoreError(f"Object upload failed: key={key} status={status} body={body[:200]!r}")
        etag = _header(headers, "etag")
        return StoredObject(
            uri=f"s3://{self.bucket}/{key}",
            bucket=self.bucket,
            key=key,
            content_type=content_type,
            content_hash=hashlib.sha256(payload).hexdigest(),
            etag=etag,
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
        canonical_headers = "".join(f"{name}:{headers[name].strip()}\n" for name in signed_header_names)
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
        signature = _signature_key(self.secret_key, date_stamp, self.region).hex_digest(string_to_sign)
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
    key_date = hmac.new(("AWS4" + secret_key).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
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


def archive_report_artifacts(report: Any, store: S3CompatibleObjectStore) -> tuple[StoredObject, ...]:
    report_export = report.report_export
    artifacts = [
        (report_export.markdown_url, report.markdown, "text/markdown; charset=utf-8"),
        (report_export.pdf_url, report.pdf_content, "application/pdf"),
        (report_export.csv_url, report.csv_content, "text/csv; charset=utf-8"),
    ]
    stored: list[StoredObject] = []
    for uri, content, content_type in artifacts:
        if uri:
            stored.append(store.put_s3_uri(uri=uri, content=content, content_type=content_type))
    return tuple(stored)


def archive_runtime_report_artifact(
    *,
    project_id: str,
    artifact: RuntimeReportArtifact,
    store: S3CompatibleObjectStore,
) -> StoredObject:
    if not project_id.strip():
        raise ObjectStoreError("project_id is required")
    report_export = artifact.report_export
    report_export_id = str(report_export.get("id") or "").strip()
    if not report_export_id:
        raise ObjectStoreError("report_export id is required")
    content_hash = artifact.content_hash or hashlib.sha256(
        artifact.content.encode("utf-8") if isinstance(artifact.content, str) else artifact.content
    ).hexdigest()
    key = "/".join(
        [
            "report-artifacts",
            project_id.strip(),
            report_export_id,
            artifact.template,
            artifact.filter_hash,
            artifact.sort,
            f"{content_hash[:12]}-{_safe_asset_filename(artifact.filename)}",
        ]
    )
    return store.put_object(key=key, content=artifact.content, content_type=artifact.media_type)


def archive_project_brand_logo(
    *,
    project_id: str,
    filename: str,
    content: bytes,
    content_type: str | None,
    store: S3CompatibleObjectStore,
) -> StoredObject:
    if not project_id.strip():
        raise ObjectStoreError("project_id is required")
    if not content:
        raise ObjectStoreError("Brand logo payload is empty")
    safe_filename = _safe_asset_filename(filename)
    normalized_content_type = _brand_logo_content_type(filename=safe_filename, content_type=content_type)
    content_hash = hashlib.sha256(content).hexdigest()
    key = f"brand-assets/{project_id.strip()}/logo-{content_hash[:12]}-{safe_filename}"
    return store.put_object(key=key, content=content, content_type=normalized_content_type)


def archive_api_snapshot_assets(
    *,
    records: tuple[RawEvidenceRecord, ...],
    store: S3CompatibleObjectStore,
) -> tuple[tuple[RawEvidenceRecord, ...], tuple[StoredObject, ...]]:
    archived_records: list[RawEvidenceRecord] = []
    stored_objects: list[StoredObject] = []
    for record in records:
        updated_assets: list[EvidenceAsset] = []
        for asset in record.evidence_assets:
            if asset.asset_type != "html_snapshot" or not asset.url.startswith("geno-api-snapshot://"):
                updated_assets.append(asset)
                continue
            content = _render_api_snapshot_html(record=record, asset=asset)
            key = f"evidence/{record.answer_run.project_id}/{record.answer_run.id}/{asset.id}.html"
            stored = store.put_object(key=key, content=content, content_type="text/html; charset=utf-8")
            stored_objects.append(stored)
            updated_assets.append(replace(asset, url=stored.uri, content_hash=stored.content_hash))
        archived_records.append(replace(record, evidence_assets=tuple(updated_assets)))
    return tuple(archived_records), tuple(stored_objects)


def archive_browser_capture_assets(
    *,
    records: tuple[RawEvidenceRecord, ...],
    store: S3CompatibleObjectStore,
) -> tuple[tuple[RawEvidenceRecord, ...], tuple[StoredObject, ...]]:
    archived_records: list[RawEvidenceRecord] = []
    stored_objects: list[StoredObject] = []
    for record in records:
        updated_assets: list[EvidenceAsset] = []
        for asset in record.evidence_assets:
            if not _is_archiveable_browser_asset(record=record, asset=asset):
                updated_assets.append(asset)
                continue
            content = _read_file_uri(asset.url)
            suffix = _browser_asset_suffix(asset)
            key = f"evidence/{record.answer_run.project_id}/{record.answer_run.id}/{asset.id}{suffix}"
            stored = store.put_object(
                key=key,
                content=content,
                content_type=_browser_asset_content_type(asset),
            )
            stored_objects.append(stored)
            updated_assets.append(replace(asset, url=stored.uri, content_hash=stored.content_hash))
        archived_records.append(replace(record, evidence_assets=tuple(updated_assets)))
    return tuple(archived_records), tuple(stored_objects)


def _is_archiveable_browser_asset(*, record: RawEvidenceRecord, asset: EvidenceAsset) -> bool:
    return (
        record.answer_run.access_method == "browser"
        and asset.asset_type in {"html_snapshot", "screenshot"}
        and asset.url.startswith("file://")
    )


def _read_file_uri(uri: str) -> bytes:
    parsed = urlsplit(uri)
    if parsed.scheme != "file":
        raise ObjectStoreError(f"Browser artifact URI is not a file URI: {uri}")
    if parsed.netloc not in {"", "localhost"}:
        raise ObjectStoreError(f"Unsupported browser artifact file host: {parsed.netloc}")
    path = Path(unquote(parsed.path))
    if not path.is_file():
        raise ObjectStoreError(f"Browser artifact file is missing: {path}")
    return path.read_bytes()


def _browser_asset_suffix(asset: EvidenceAsset) -> str:
    suffix = Path(unquote(urlsplit(asset.url).path)).suffix.lower()
    if asset.asset_type == "html_snapshot":
        return ".html"
    if asset.asset_type == "screenshot":
        return suffix if suffix in {".png", ".jpg", ".jpeg", ".webp"} else ".png"
    return suffix or ".bin"


def _browser_asset_content_type(asset: EvidenceAsset) -> str:
    if asset.asset_type == "html_snapshot":
        return "text/html; charset=utf-8"
    suffix = _browser_asset_suffix(asset)
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".png":
        return "image/png"
    return "application/octet-stream"


def _safe_asset_filename(filename: str) -> str:
    basename = Path(filename or "logo.bin").name.strip() or "logo.bin"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", basename).strip(".-")
    return safe or "logo.bin"


def _brand_logo_content_type(*, filename: str, content_type: str | None) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized in {"image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"}:
        return normalized
    suffix = Path(filename).suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".svg":
        return "image/svg+xml"
    if suffix == ".gif":
        return "image/gif"
    return "application/octet-stream"


def _render_api_snapshot_html(*, record: RawEvidenceRecord, asset: EvidenceAsset) -> str:
    snapshot = record.raw_answer.raw_payload.get("_geno_api_snapshot")
    snapshot_meta = snapshot if isinstance(snapshot, dict) else {}
    citations = "\n".join(
        f"<li><a href=\"{html.escape(citation.url, quote=True)}\">{html.escape(citation.url)}</a></li>"
        for citation in record.citations
    )
    payload_json = html.escape(_stable_json(record.raw_answer.raw_payload))
    return "\n".join(
        [
            "<!doctype html>",
            "<html lang=\"en\">",
            "<head>",
            "  <meta charset=\"utf-8\">",
            f"  <title>GENO API Snapshot {html.escape(record.answer_run.id)}</title>",
            "</head>",
            "<body>",
            "  <h1>GENO Official API Response Snapshot</h1>",
            "  <dl>",
            f"    <dt>Answer run</dt><dd>{html.escape(record.answer_run.id)}</dd>",
            f"    <dt>Collector</dt><dd>{html.escape(record.answer_run.collector_backend_id)}</dd>",
            f"    <dt>Platform</dt><dd>{html.escape(record.answer_run.platform)}</dd>",
            f"    <dt>Surface</dt><dd>{html.escape(record.answer_run.surface)}</dd>",
            f"    <dt>Access method</dt><dd>{html.escape(record.answer_run.access_method)}</dd>",
            f"    <dt>City</dt><dd>{html.escape(record.answer_run.city)}</dd>",
            f"    <dt>Raw payload hash</dt><dd>{html.escape(record.raw_answer.raw_payload_hash)}</dd>",
            f"    <dt>Snapshot payload hash</dt><dd>{html.escape(str(snapshot_meta.get('payload_hash', '')))}</dd>",
            f"    <dt>Source URI before archive</dt><dd>{html.escape(asset.url)}</dd>",
            "  </dl>",
            "  <h2>Answer</h2>",
            f"  <pre>{html.escape(record.raw_answer.answer_text)}</pre>",
            "  <h2>Citations</h2>",
            f"  <ol>{citations}</ol>",
            "  <h2>Raw API Payload</h2>",
            f"  <pre>{payload_json}</pre>",
            "</body>",
            "</html>",
        ]
    )


def _stable_json(payload: Any) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str)
