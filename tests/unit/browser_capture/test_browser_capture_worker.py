from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from uuid import uuid4

import pytest

from geo_core.browser_capture.artifacts import EncryptedBrowserArtifactWriter
from geo_core.browser_capture.domain import BrowserCaptureError, NetworkType
from geo_core.browser_capture.worker import build_proxy_lease
from geo_core.object_store import StoredObject


NOW = datetime(2026, 7, 29, 2, 0, tzinfo=UTC)


def _endpoint(sticky_mode: str = "credential_session") -> dict[str, object]:
    return {
        "protocol": "https",
        "endpoint_host": "au.proxy.example",
        "endpoint_port": 443,
        "sticky_mode": sticky_mode,
        "network_type": "residential",
        "expected_region": "NSW",
    }


def test_credential_session_injects_one_non_secret_sticky_lease() -> None:
    lease = build_proxy_lease(
        endpoint=_endpoint(),
        credential={
            "username": "account",
            "password": "secret",
            "username_template": "{username}-session-{session_id}",
            "lease_id": "capture-123",
            "lease_ttl_seconds": 600,
        },
        now=NOW,
    )
    assert lease.username == "account-session-capture-123"
    assert lease.password == "secret"
    assert lease.server == "https://au.proxy.example:443"
    assert lease.network_type is NetworkType.RESIDENTIAL
    assert lease.lease_hash == hashlib.sha256(b"capture-123").hexdigest()
    assert "secret" not in repr(lease)


def test_provider_lease_and_trusted_log_modes_fail_closed() -> None:
    with pytest.raises(BrowserCaptureError, match="provider lease_id"):
        build_proxy_lease(
            endpoint=_endpoint("provider_lease"),
            credential={"username": "account", "password": "secret"},
            now=NOW,
        )
    with pytest.raises(BrowserCaptureError, match="trusted log"):
        build_proxy_lease(
            endpoint=_endpoint("trusted_connection_log"),
            credential={"lease_id": "lease-1"},
            now=NOW,
        )


class _Objects:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObject:
        payload = content.encode() if isinstance(content, str) else content
        assert expected_hash == hashlib.sha256(payload).hexdigest()
        self.values[key] = payload
        return StoredObject(
            uri=f"s3://browser-test/{key}",
            bucket="browser-test",
            key=key,
            content_type=content_type,
            content_hash=expected_hash,
            etag=None,
        )


def test_page_bundle_is_encrypted_and_namespaced_by_capture_session() -> None:
    objects = _Objects()
    writer = EncryptedBrowserArtifactWriter(
        objects=objects,
        data_key=b"k" * 32,
        key_reference="browser-artifact:v1",
        producer_commit="a" * 40,
        clock=lambda: NOW,
    )
    project_id, attempt_id, session_id = (uuid4() for _ in range(3))
    bundle = writer.persist(
        project_id=project_id,
        attempt_id=attempt_id,
        capture_session_id=session_id,
        screenshot=b"png-sensitive",
        dom=b"html-sensitive",
        har=b"har-sensitive",
    )
    prefix = f"browser-captures/{project_id}/{attempt_id}/{session_id}"
    assert f"{prefix}/manifest.json" in objects.values
    assert all(
        plaintext not in objects.values[f"{prefix}/{name}.aesgcm"]
        for name, plaintext in (
            ("screenshot.png", b"png-sensitive"),
            ("page.html", b"html-sensitive"),
            ("page.har", b"har-sensitive"),
        )
    )
    manifest = json.loads(objects.values[f"{prefix}/manifest.json"])
    assert manifest["capture_session_id"] == str(session_id)
    assert manifest["governance"]["classification"] == "restricted_raw_consumer_surface"
    assert bundle.manifest_uri == f"s3://browser-test/{prefix}/manifest.json"
