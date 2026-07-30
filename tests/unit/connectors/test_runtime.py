from __future__ import annotations

from datetime import UTC, datetime
import json
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from geo_core.connectors.runtime import EncryptedConnectorArtifactWriter
from geo_core.object_store import StoredObject


class MemoryObjects:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def put_object(self, *, key, content, content_type, expected_hash=None):
        payload = content.encode() if isinstance(content, str) else content
        self.values[key] = payload
        return StoredObject(
            uri=f"s3://connector-test/{key}",
            bucket="connector-test",
            key=key,
            content_type=content_type,
            content_hash=expected_hash or "",
            etag=None,
        )


def test_writer_encrypts_deterministic_jsonl_and_manifest_carries_lineage() -> None:
    objects = MemoryObjects()
    project_id, run_id = uuid4(), uuid4()
    key = b"K" * 32
    writer = EncryptedConnectorArtifactWriter(
        objects=objects,
        data_key=key,
        key_reference="connector-test-key:v1",
        producer_commit="a" * 40,
        clock=lambda: datetime(2026, 7, 28, tzinfo=UTC),
    )
    artifact = writer.persist(
        project_id=project_id,
        run_id=run_id,
        records=({"clicks": 3, "query": "robot vacuum"},),
        schema_fingerprint="b" * 64,
    )
    prefix = f"connectors/{project_id}/{run_id}"
    manifest = json.loads(objects.values[f"{prefix}/manifest.json"])
    ciphertext = objects.values[f"{prefix}/records.jsonl.aesgcm"]
    aad = f"geo-connector:{project_id}:{run_id}:{'b' * 64}".encode()
    plaintext = AESGCM(key).decrypt(bytes.fromhex(manifest["encryption"]["nonce_hex"]), ciphertext, aad)

    assert plaintext == b'{"clicks":3,"query":"robot vacuum"}\n'
    assert b"robot vacuum" not in ciphertext
    assert artifact.manifest_uri.endswith("/manifest.json")
    assert artifact.record_count == 1
    assert manifest["payload_plaintext_sha256"] == artifact.content_hash
