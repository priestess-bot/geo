from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from geo_core.object_store import RetrievedObject, StoredObject, parse_s3_uri
from geo_core.sampling import SamplingRuleViolation
from geo_core.workflow_c_artifacts.composition import (
    WORKFLOW_C_RESTRICTED_BUCKET,
    build_workflow_c_artifact_object_store,
)
from geo_core.sampling.manual_artifact_governance import (
    AUTOMATIC_POLICY_KEY,
    StrictManualArtifactGovernance,
    wipe_bytearray,
)
from geo_core.sampling.manual_artifact_storage import (
    IndependentWorkflowCArtifactEncryptor,
    MinioWorkflowCManualArtifactWriter,
    WorkflowCManualArtifactRecord,
    decrypt_workflow_c_artifact_payload,
    workflow_c_artifact_associated_data,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
PROJECT_ID = UUID("ca000000-0000-0000-0000-000000000001")
RUN_ID = UUID("ca000000-0000-0000-0000-000000000002")
TASK_ID = UUID("ca000000-0000-0000-0000-000000000003")
ARTIFACT_ID = UUID("ca000000-0000-0000-0000-000000000004")
SESSION_ID = UUID("ca000000-0000-0000-0000-000000000005")


class _Vault:
    def __init__(self) -> None:
        self.keys: dict[UUID, bytes] = {}

    def store_wrapped_key(
        self, *, project_id: UUID, artifact_id: UUID, key_material: bytearray
    ) -> UUID:
        assert project_id == PROJECT_ID
        self.keys[artifact_id] = bytes(key_material)
        return artifact_id

    def destroy_wrapped_key(
        self, *, project_id: UUID, key_reference: UUID
    ) -> None:
        assert project_id == PROJECT_ID
        self.keys.pop(key_reference, None)


class _Repository:
    def __init__(self) -> None:
        self.record: WorkflowCManualArtifactRecord | None = None
        self.status: str | None = None

    def stage(self, record: WorkflowCManualArtifactRecord) -> None:
        self.record = record
        self.status = "staged"

    def activate(self, *, project_id: UUID, artifact_id: UUID) -> None:
        assert (project_id, artifact_id) == (PROJECT_ID, ARTIFACT_ID)
        self.status = "active"

    def queue_failed_stage_cleanup(
        self, *, project_id: UUID, artifact_id: UUID
    ) -> None:
        assert (project_id, artifact_id) == (
            PROJECT_ID,
            ARTIFACT_ID,
        )
        self.status = "delete_pending"


class _Store:
    bucket = WORKFLOW_C_RESTRICTED_BUCKET

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def uri_for_key(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def put_object(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        expected_hash: str,
    ) -> StoredObject:
        assert hashlib.sha256(content).hexdigest() == expected_hash
        self.objects[key] = (content, content_type)
        return StoredObject(
            uri=self.uri_for_key(key),
            bucket=self.bucket,
            key=key,
            content_type=content_type,
            content_hash=expected_hash,
            etag=None,
        )

    def get_s3_uri(self, *, uri: str, expected_hash: str) -> RetrievedObject:
        bucket, key = parse_s3_uri(uri)
        payload, content_type = self.objects[key]
        assert bucket == self.bucket
        assert hashlib.sha256(payload).hexdigest() == expected_hash
        return RetrievedObject(
            content=payload,
            bucket=bucket,
            key=key,
            content_type=content_type,
            content_hash=expected_hash,
            etag=None,
        )

    def delete_s3_uri(self, *, uri: str) -> bool:
        _bucket, key = parse_s3_uri(uri)
        return self.objects.pop(key, None) is not None


class _WriterDeleteDeniedStore(_Store):
    """The Writer principal must never call a delete-capable operation."""

    def __init__(self) -> None:
        super().__init__()
        self.put_calls = 0
        self.delete_attempts = 0

    def put_object(self, **values):
        self.put_calls += 1
        if self.put_calls == 2:
            raise RuntimeError("fixture manifest write failure")
        return super().put_object(**values)

    def delete_s3_uri(self, *, uri: str) -> bool:
        self.delete_attempts += 1
        raise AssertionError("Workflow C Writer must not delete restricted objects")


def test_structured_governance_removes_sensitive_values_and_raw_markup() -> None:
    source = bytearray(
        b"<html><script>token=script-secret</script><body>Contact "
        b"owner@example.com or 0412 345 678. Authorization: bearer abcdefghijk"
        b"</body></html>"
    )
    governed = StrictManualArtifactGovernance().govern(
        evidence_kind="html_export",
        content_type="text/html",
        content=source,
        governance_policy_key=AUTOMATIC_POLICY_KEY,
        pre_redacted_attestation=False,
    )
    try:
        persisted = bytes(governed.payload)
        assert b"owner@example.com" not in persisted
        assert b"0412 345 678" not in persisted
        assert b"abcdefghijk" not in persisted
        assert b"script-secret" not in persisted
        assert b"<html" not in persisted
        assert governed.pii_finding_count == 2
        assert governed.secret_finding_count == 1
        assert governed.raw_retained is governed.export_allowed is False
        assert governed.audience == "admin_only"
    finally:
        wipe_bytearray(source)
        wipe_bytearray(governed.payload)


def test_json_sensitive_keys_and_duplicate_keys_fail_closed() -> None:
    source = bytearray(
        b'{"answer":"safe","cookie":"session-secret","nested":{"email":"a@b.com"}}'
    )
    governed = StrictManualArtifactGovernance().govern(
        evidence_kind="transcript_export",
        content_type="application/json",
        content=source,
        governance_policy_key=AUTOMATIC_POLICY_KEY,
        pre_redacted_attestation=False,
    )
    assert b"session-secret" not in governed.payload
    assert b"a@b.com" not in governed.payload
    assert governed.secret_finding_count == governed.pii_finding_count == 1

    with pytest.raises(SamplingRuleViolation, match="JSON is invalid"):
        StrictManualArtifactGovernance().govern(
            evidence_kind="transcript_export",
            content_type="application/json",
            content=bytearray(b'{"answer":1,"answer":2}'),
            governance_policy_key=AUTOMATIC_POLICY_KEY,
            pre_redacted_attestation=False,
        )


def test_screenshot_requires_explicit_pre_redacted_attestation() -> None:
    content = bytearray(b"\x89PNG\r\n\x1a\nfixture")
    with pytest.raises(SamplingRuleViolation, match="explicit pre-redacted"):
        StrictManualArtifactGovernance().govern(
            evidence_kind="screenshot",
            content_type="image/png",
            content=content,
            governance_policy_key=AUTOMATIC_POLICY_KEY,
            pre_redacted_attestation=False,
        )


def test_writer_persists_only_encrypted_redacted_derivative_and_metadata() -> None:
    source = bytearray(b"Contact owner@example.com token=never-store-this")
    vault = _Vault()
    repository = _Repository()
    store = _Store()
    writer = MinioWorkflowCManualArtifactWriter(
        object_store=store,
        encryptor=IndependentWorkflowCArtifactEncryptor(vault),
        repository=repository,
        clock=lambda: NOW,
    )
    receipt = writer.write(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        task_id=TASK_ID,
        artifact_manifest_id=ARTIFACT_ID,
        capture_session_id=SESSION_ID,
        evidence_kind="transcript_export",
        content_type="text/plain",
        content=source,
        governance_policy_key=AUTOMATIC_POLICY_KEY,
        pre_redacted_attestation=False,
    )
    assert source == bytearray(len(source))
    assert repository.status == "active"
    assert repository.record is not None
    record = repository.record
    payload = next(value for key, value in store.objects.items() if "/payloads/" in key)[0]
    manifest = next(value for key, value in store.objects.items() if "/manifests/" in key)[0]
    for forbidden in (b"owner@example.com", b"never-store-this"):
        assert forbidden not in payload
        assert forbidden not in manifest
    manifest_value = json.loads(manifest)
    assert manifest_value["raw_retained"] is False
    assert manifest_value["export_allowed"] is False
    assert manifest_value["audience"] == "admin_only"
    key = bytearray(vault.keys[ARTIFACT_ID])
    plaintext = decrypt_workflow_c_artifact_payload(
        encrypted_payload=payload,
        key_material=key,
        associated_data=workflow_c_artifact_associated_data(
            project_id=PROJECT_ID,
            artifact_id=ARTIFACT_ID,
            persisted_content_hash=record.redacted_content_hash,
            governance_policy_hash=record.governance_policy_hash,
        ),
    )
    try:
        assert b"[REDACTED_EMAIL]" in plaintext
        assert b"[REDACTED_SECRET]" in plaintext
        assert hashlib.sha256(plaintext).hexdigest() == receipt.artifact_content_hash
    finally:
        wipe_bytearray(key)
        wipe_bytearray(plaintext)


def test_failed_staged_write_is_queued_for_deleter_without_writer_delete_access() -> None:
    source = bytearray(b"Safe derivative that fails while writing its manifest")
    vault = _Vault()
    repository = _Repository()
    store = _WriterDeleteDeniedStore()
    writer = MinioWorkflowCManualArtifactWriter(
        object_store=store,
        encryptor=IndependentWorkflowCArtifactEncryptor(vault),
        repository=repository,
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="manifest write failure"):
        writer.write(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            task_id=TASK_ID,
            artifact_manifest_id=ARTIFACT_ID,
            capture_session_id=SESSION_ID,
            evidence_kind="transcript_export",
            content_type="text/plain",
            content=source,
            governance_policy_key=AUTOMATIC_POLICY_KEY,
            pre_redacted_attestation=False,
        )

    assert source == bytearray(len(source))
    assert repository.status == "delete_pending"
    assert store.delete_attempts == 0
    # The deleter still owns crypto-erasure because the staged queue retains key_ref.
    assert ARTIFACT_ID in vault.keys


def test_object_store_composition_rejects_general_bucket_and_direct_credentials(
    tmp_path: Path,
) -> None:
    access = tmp_path / "access"
    secret = tmp_path / "secret"
    access.write_text("workflow-c-user", encoding="utf-8")
    secret.write_text("workflow-c-password", encoding="utf-8")
    values = {
        "GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_ENDPOINT": "http://minio:9000",
        "GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_BUCKET": WORKFLOW_C_RESTRICTED_BUCKET,
        "GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_ACCESS_KEY_FILE": str(access),
        "GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_SECRET_KEY_FILE": str(secret),
    }
    store = build_workflow_c_artifact_object_store(values)
    assert store.bucket == WORKFLOW_C_RESTRICTED_BUCKET
    assert store.auto_create_bucket is False
    with pytest.raises(RuntimeError, match="restricted bucket"):
        build_workflow_c_artifact_object_store(
            {**values, "GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_BUCKET": "geo-artifacts"}
        )
    with pytest.raises(RuntimeError, match="Docker Secret"):
        build_workflow_c_artifact_object_store(
            {**values, "GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_ACCESS_KEY": "raw"}
        )
