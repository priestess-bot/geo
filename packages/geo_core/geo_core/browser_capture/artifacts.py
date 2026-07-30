"""Encrypted Browser Capture Page Bundle persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from typing import Protocol
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from geo_core.object_store import StoredObject


class BrowserArtifactError(RuntimeError):
    """A browser evidence bundle could not be encrypted or persisted."""


class BrowserArtifactObjectStore(Protocol):
    def put_object(
        self, *, key: str, content: str | bytes, content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObject: ...


@dataclass(frozen=True)
class BrowserArtifactBundle:
    manifest_uri: str
    manifest_hash: str
    screenshot_hash: str
    dom_hash: str
    har_hash: str
    encryption_key_reference: str
    retention_until: datetime


class EncryptedBrowserArtifactWriter:
    def __init__(
        self,
        *,
        objects: BrowserArtifactObjectStore,
        data_key: bytes,
        key_reference: str,
        producer_commit: str,
        retention_days: int = 30,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if len(data_key) != 32 or not key_reference.strip() or retention_days < 1:
            raise BrowserArtifactError("Browser artifact encryption settings are invalid")
        self._objects = objects
        self._data_key = data_key
        self._key_reference = key_reference
        self._producer_commit = producer_commit
        self._retention_days = retention_days
        self._clock = clock

    def persist(
        self,
        *,
        project_id: UUID,
        attempt_id: UUID,
        capture_session_id: UUID,
        screenshot: bytes,
        dom: bytes,
        har: bytes,
    ) -> BrowserArtifactBundle:
        if not screenshot or not dom or not har:
            raise BrowserArtifactError("Browser Page Bundle components must be non-empty")
        prefix = f"browser-captures/{project_id}/{attempt_id}/{capture_session_id}"
        items = {}
        for name, payload in (("screenshot.png", screenshot), ("page.html", dom), ("page.har", har)):
            plain_hash = hashlib.sha256(payload).hexdigest()
            nonce = os.urandom(12)
            aad = (
                f"geo-browser:{project_id}:{attempt_id}:{capture_session_id}:{name}"
            ).encode()
            ciphertext = AESGCM(self._data_key).encrypt(nonce, payload, aad)
            cipher_hash = hashlib.sha256(ciphertext).hexdigest()
            stored = self._objects.put_object(
                key=f"{prefix}/{name}.aesgcm", content=ciphertext,
                content_type="application/octet-stream", expected_hash=cipher_hash,
            )
            items[name] = {
                "uri": stored.uri, "plaintext_sha256": plain_hash,
                "ciphertext_sha256": cipher_hash, "nonce_hex": nonce.hex(),
                "aad_sha256": hashlib.sha256(aad).hexdigest(),
            }
        now = self._clock()
        retention_until = now + timedelta(days=self._retention_days)
        manifest_value = {
            "schema_version": "geo-browser-page-bundle-v1",
            "project_id": str(project_id), "sampling_attempt_id": str(attempt_id),
            "capture_session_id": str(capture_session_id),
            "items": items,
            "encryption": {"algorithm": "AES-256-GCM", "key_reference": self._key_reference},
            "governance": {
                "classification": "restricted_raw_consumer_surface",
                "access_scope": "admin_browser_capture_evidence",
                "deletion_policy": "delete_after_retention_unless_legal_hold",
            },
            "producer_commit": self._producer_commit,
            "created_at": now.isoformat(), "retention_until": retention_until.isoformat(),
        }
        manifest = json.dumps(
            manifest_value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode()
        manifest_hash = hashlib.sha256(manifest).hexdigest()
        stored_manifest = self._objects.put_object(
            key=f"{prefix}/manifest.json", content=manifest,
            content_type="application/json", expected_hash=manifest_hash,
        )
        return BrowserArtifactBundle(
            manifest_uri=stored_manifest.uri, manifest_hash=manifest_hash,
            screenshot_hash=items["screenshot.png"]["plaintext_sha256"],
            dom_hash=items["page.html"]["plaintext_sha256"],
            har_hash=items["page.har"]["plaintext_sha256"],
            encryption_key_reference=self._key_reference,
            retention_until=retention_until,
        )


__all__ = [
    "BrowserArtifactBundle", "BrowserArtifactError", "BrowserArtifactObjectStore",
    "EncryptedBrowserArtifactWriter",
]
