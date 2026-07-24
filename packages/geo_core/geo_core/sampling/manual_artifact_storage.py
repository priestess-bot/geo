"""Encrypted restricted storage for governed Workflow C manual evidence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from typing import Any, Protocol
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from geo_core.sampling.contracts import SamplingRuleViolation
from geo_core.sampling.manual_artifact_governance import (
    GovernedManualArtifact,
    StrictManualArtifactGovernance,
    wipe_bytearray,
)


_ENVELOPE_PREFIX = b"GEO-WORKFLOW-C-ARTIFACT-AESGCM-V1\x00"
_ALGORITHM = "AES-256-GCM/independent-DEK/v1"


@dataclass(frozen=True)
class WorkflowCManualArtifactReceipt:
    artifact_manifest_id: UUID
    artifact_manifest_hash: str
    artifact_content_hash: str
    governance_policy_hash: str
    capture_session_id: UUID


@dataclass(frozen=True, repr=False)
class WorkflowCArtifactEncryptionEnvelope:
    payload: bytes = field(repr=False)
    key_reference: UUID
    algorithm: str = _ALGORITHM


@dataclass(frozen=True, kw_only=True)
class WorkflowCManualArtifactRecord:
    artifact_id: UUID
    project_id: UUID
    run_id: UUID
    task_id: UUID
    capture_session_id: UUID
    evidence_kind: str
    source_content_type: str
    persisted_content_type: str
    source_content_hash: str
    redacted_content_hash: str
    object_uri: str
    object_hash: str
    manifest_uri: str
    manifest_hash: str
    governance_policy_hash: str
    redactor_version_hash: str
    scanner_version_hash: str
    pii_finding_count: int
    secret_finding_count: int
    redaction_assurance: str
    classification: str
    audience: str
    export_allowed: bool
    raw_retained: bool
    retention_days: int
    expires_at: datetime
    legal_hold: bool
    key_reference: UUID
    encryption_algorithm: str
    stored_byte_size: int
    created_at: datetime


class WorkflowCArtifactKeyVault(Protocol):
    def store_wrapped_key(
        self, *, project_id: UUID, artifact_id: UUID, key_material: bytearray
    ) -> UUID: ...

    def destroy_wrapped_key(
        self, *, project_id: UUID, key_reference: UUID
    ) -> None: ...


class WorkflowCManualArtifactRepository(Protocol):
    def stage(self, record: WorkflowCManualArtifactRecord) -> None: ...

    def activate(self, *, project_id: UUID, artifact_id: UUID) -> None: ...

    def queue_failed_stage_cleanup(
        self, *, project_id: UUID, artifact_id: UUID
    ) -> None: ...


class WorkflowCManualArtifactWriterObjectStore(Protocol):
    def uri_for_key(self, key: str) -> str: ...

    def put_object(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        expected_hash: str,
    ) -> Any: ...

    def get_s3_uri(self, *, uri: str, expected_hash: str) -> Any: ...


class WorkflowCManualArtifactObjectStore(WorkflowCManualArtifactWriterObjectStore, Protocol):
    """Maintenance-only extension; Writer credentials never delete objects."""

    def delete_s3_uri(self, *, uri: str) -> bool: ...


class IndependentWorkflowCArtifactEncryptor:
    def __init__(
        self,
        vault: WorkflowCArtifactKeyVault,
        *,
        random_bytes: Callable[[int], bytes] = os.urandom,
    ) -> None:
        self._vault = vault
        self._random_bytes = random_bytes

    def encrypt(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        plaintext: bytearray,
        associated_data: bytes,
    ) -> WorkflowCArtifactEncryptionEnvelope:
        data_key = bytearray(self._random_exact(32))
        key_reference: UUID | None = None
        try:
            nonce = self._random_exact(12)
            ciphertext = AESGCM(bytes(data_key)).encrypt(
                nonce, bytes(plaintext), associated_data
            )
            key_reference = self._vault.store_wrapped_key(
                project_id=project_id,
                artifact_id=artifact_id,
                key_material=data_key,
            )
            return WorkflowCArtifactEncryptionEnvelope(
                payload=_ENVELOPE_PREFIX + nonce + ciphertext,
                key_reference=key_reference,
            )
        except BaseException:
            if key_reference is not None:
                self._vault.destroy_wrapped_key(
                    project_id=project_id, key_reference=key_reference
                )
            raise
        finally:
            wipe_bytearray(data_key)

    def destroy_key(self, *, project_id: UUID, key_reference: UUID) -> None:
        self._vault.destroy_wrapped_key(
            project_id=project_id, key_reference=key_reference
        )

    def _random_exact(self, size: int) -> bytes:
        value = self._random_bytes(size)
        if len(value) != size:
            raise SamplingRuleViolation(
                "Workflow C artifact cryptographic random source failed"
            )
        return value


class MinioWorkflowCManualArtifactWriter:
    """Govern, encrypt, stage and verify one restricted manual evidence object."""

    def __init__(
        self,
        *,
        object_store: WorkflowCManualArtifactWriterObjectStore,
        encryptor: IndependentWorkflowCArtifactEncryptor,
        repository: WorkflowCManualArtifactRepository,
        governance: StrictManualArtifactGovernance | None = None,
        retention_days: int = 90,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not 1 <= retention_days <= 365:
            raise SamplingRuleViolation(
                "Workflow C manual artifact retention must be between 1 and 365 days"
            )
        self._store = object_store
        self._encryptor = encryptor
        self._repository = repository
        self._governance = governance or StrictManualArtifactGovernance()
        self._retention_days = retention_days
        self._clock = clock

    def __repr__(self) -> str:
        return "MinioWorkflowCManualArtifactWriter([REDACTED])"

    def write(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        artifact_manifest_id: UUID,
        capture_session_id: UUID,
        evidence_kind: str,
        content_type: str,
        content: bytearray,
        governance_policy_key: str,
        pre_redacted_attestation: bool,
        activate: bool = True,
    ) -> WorkflowCManualArtifactReceipt:
        governed: GovernedManualArtifact | None = None
        envelope: WorkflowCArtifactEncryptionEnvelope | None = None
        payload_uri: str | None = None
        manifest_uri: str | None = None
        staged = False
        try:
            governed = self._governance.govern(
                evidence_kind=evidence_kind,
                content_type=content_type,
                content=content,
                governance_policy_key=governance_policy_key,
                pre_redacted_attestation=pre_redacted_attestation,
            )
            created_at = self._clock()
            _require_aware(created_at)
            expires_at = created_at + timedelta(days=self._retention_days)
            aad = workflow_c_artifact_associated_data(
                project_id=project_id,
                artifact_id=artifact_manifest_id,
                persisted_content_hash=governed.persisted_content_hash,
                governance_policy_hash=governed.governance_policy_hash,
            )
            envelope = self._encryptor.encrypt(
                project_id=project_id,
                artifact_id=artifact_manifest_id,
                plaintext=governed.payload,
                associated_data=aad,
            )
            object_hash = hashlib.sha256(envelope.payload).hexdigest()
            base_key = (
                f"workflow-c/manual-evidence/{project_id}/{artifact_manifest_id}"
            )
            payload_key = f"{base_key}/payloads/{object_hash}.bin"
            payload_uri = self._store.uri_for_key(payload_key)
            manifest_without_hash = _manifest(
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                artifact_id=artifact_manifest_id,
                capture_session_id=capture_session_id,
                evidence_kind=evidence_kind,
                governed=governed,
                object_uri=payload_uri,
                object_hash=object_hash,
                envelope=envelope,
                retention_days=self._retention_days,
                created_at=created_at,
                expires_at=expires_at,
            )
            manifest_bytes = canonical_workflow_c_artifact_json(manifest_without_hash)
            manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
            manifest_key = f"{base_key}/manifests/{manifest_hash}.json"
            manifest_uri = self._store.uri_for_key(manifest_key)
            record = WorkflowCManualArtifactRecord(
                artifact_id=artifact_manifest_id,
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                capture_session_id=capture_session_id,
                evidence_kind=evidence_kind,
                source_content_type=governed.source_content_type,
                persisted_content_type=governed.persisted_content_type,
                source_content_hash=governed.source_content_hash,
                redacted_content_hash=governed.persisted_content_hash,
                object_uri=payload_uri,
                object_hash=object_hash,
                manifest_uri=manifest_uri,
                manifest_hash=manifest_hash,
                governance_policy_hash=governed.governance_policy_hash,
                redactor_version_hash=governed.redactor_version_hash,
                scanner_version_hash=governed.scanner_version_hash,
                pii_finding_count=governed.pii_finding_count,
                secret_finding_count=governed.secret_finding_count,
                redaction_assurance=governed.redaction_assurance,
                classification=governed.classification,
                audience=governed.audience,
                export_allowed=governed.export_allowed,
                raw_retained=governed.raw_retained,
                retention_days=self._retention_days,
                expires_at=expires_at,
                legal_hold=False,
                key_reference=envelope.key_reference,
                encryption_algorithm=envelope.algorithm,
                stored_byte_size=len(envelope.payload),
                created_at=created_at,
            )
            self._repository.stage(record)
            staged = True
            self._put_verified(
                key=payload_key,
                uri=payload_uri,
                content=envelope.payload,
                content_type="application/octet-stream",
                expected_hash=object_hash,
            )
            self._put_verified(
                key=manifest_key,
                uri=manifest_uri,
                content=manifest_bytes,
                content_type="application/json",
                expected_hash=manifest_hash,
            )
            if activate:
                self._repository.activate(
                    project_id=project_id, artifact_id=artifact_manifest_id
                )
            return WorkflowCManualArtifactReceipt(
                artifact_manifest_id=artifact_manifest_id,
                artifact_manifest_hash=manifest_hash,
                artifact_content_hash=governed.persisted_content_hash,
                governance_policy_hash=governed.governance_policy_hash,
                capture_session_id=capture_session_id,
            )
        except BaseException:
            self._rollback(
                project_id=project_id,
                artifact_id=artifact_manifest_id,
                envelope=envelope,
                staged=staged,
            )
            raise
        finally:
            wipe_bytearray(content)
            if governed is not None:
                wipe_bytearray(governed.payload)

    def cleanup_staged(self, *, project_id: UUID, artifact_manifest_id: UUID) -> None:
        """Queue a verified but unlinked stage for fenced crypto-erasure."""
        self._repository.queue_failed_stage_cleanup(
            project_id=project_id,
            artifact_id=artifact_manifest_id,
        )

    def _put_verified(
        self,
        *,
        key: str,
        uri: str,
        content: bytes,
        content_type: str,
        expected_hash: str,
    ) -> None:
        stored = self._store.put_object(
            key=key,
            content=content,
            content_type=content_type,
            expected_hash=expected_hash,
        )
        if getattr(stored, "uri", None) != uri:
            raise SamplingRuleViolation("Workflow C artifact object URI changed")
        retrieved = self._store.get_s3_uri(uri=uri, expected_hash=expected_hash)
        if getattr(retrieved, "content_hash", None) != expected_hash:
            raise SamplingRuleViolation("Workflow C artifact object verification failed")

    def _rollback(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        envelope: WorkflowCArtifactEncryptionEnvelope | None,
        staged: bool,
    ) -> None:
        if staged:
            try:
                self._repository.queue_failed_stage_cleanup(
                    project_id=project_id,
                    artifact_id=artifact_id,
                )
                # The restricted Writer cannot delete.  The durable maintenance
                # worker owns object deletion and DEK destruction under a fenced
                # lease so failed writes remain recoverable and auditable.
                return
            except BaseException:
                pass
        # Before the stage row exists, or if queueing itself is unavailable,
        # immediate crypto-erasure is the only safe local rollback.  Any object
        # from a staged-but-unqueued failure is subsequently discovered by the
        # staged-timeout sweeper; this process never has object-delete rights.
        if envelope is not None:
            try:
                self._encryptor.destroy_key(
                    project_id=project_id, key_reference=envelope.key_reference
                )
            except BaseException:
                pass


def decrypt_workflow_c_artifact_payload(
    *, encrypted_payload: bytes, key_material: bytearray, associated_data: bytes
) -> bytearray:
    prefix_size = len(_ENVELOPE_PREFIX)
    if (
        len(key_material) != 32
        or not encrypted_payload.startswith(_ENVELOPE_PREFIX)
        or len(encrypted_payload) < prefix_size + 12 + 17
    ):
        raise SamplingRuleViolation("Workflow C artifact envelope is invalid")
    try:
        return bytearray(
            AESGCM(bytes(key_material)).decrypt(
                encrypted_payload[prefix_size : prefix_size + 12],
                encrypted_payload[prefix_size + 12 :],
                associated_data,
            )
        )
    except InvalidTag:
        raise SamplingRuleViolation(
            "Workflow C artifact authentication failed"
        ) from None


def workflow_c_artifact_associated_data(
    *,
    project_id: UUID,
    artifact_id: UUID,
    persisted_content_hash: str,
    governance_policy_hash: str,
) -> bytes:
    return canonical_workflow_c_artifact_json(
        {
            "schema_version": 1,
            "project_id": str(project_id),
            "artifact_id": str(artifact_id),
            "persisted_content_hash": persisted_content_hash,
            "governance_policy_hash": governance_policy_hash,
        }
    )


def canonical_workflow_c_artifact_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _manifest(
    *,
    project_id: UUID,
    run_id: UUID,
    task_id: UUID,
    artifact_id: UUID,
    capture_session_id: UUID,
    evidence_kind: str,
    governed: GovernedManualArtifact,
    object_uri: str,
    object_hash: str,
    envelope: WorkflowCArtifactEncryptionEnvelope,
    retention_days: int,
    created_at: datetime,
    expires_at: datetime,
) -> dict[str, object]:
    return {
        "schema_version": "workflow-c-manual-evidence-manifest-v2",
        "project_id": str(project_id),
        "run_id": str(run_id),
        "task_id": str(task_id),
        "artifact_id": str(artifact_id),
        "capture_session_id": str(capture_session_id),
        "evidence_kind": evidence_kind,
        "source_content_type": governed.source_content_type,
        "persisted_content_type": governed.persisted_content_type,
        "source_content_hash": governed.source_content_hash,
        "persisted_content_hash": governed.persisted_content_hash,
        "stored_object_uri": object_uri,
        "stored_object_hash": object_hash,
        "stored_byte_size": len(envelope.payload),
        "encryption_algorithm": envelope.algorithm,
        "key_reference": str(envelope.key_reference),
        "governance_policy_hash": governed.governance_policy_hash,
        "redactor_version_hash": governed.redactor_version_hash,
        "scanner_version_hash": governed.scanner_version_hash,
        "pii_finding_count": governed.pii_finding_count,
        "secret_finding_count": governed.secret_finding_count,
        "redaction_assurance": governed.redaction_assurance,
        "classification": governed.classification,
        "audience": governed.audience,
        "export_allowed": governed.export_allowed,
        "raw_retained": governed.raw_retained,
        "retention_days": retention_days,
        "legal_hold": False,
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SamplingRuleViolation(
            "Workflow C artifact clock must be timezone-aware"
        )


__all__ = [
    "IndependentWorkflowCArtifactEncryptor",
    "MinioWorkflowCManualArtifactWriter",
    "WorkflowCArtifactEncryptionEnvelope",
    "WorkflowCArtifactKeyVault",
    "WorkflowCManualArtifactObjectStore",
    "WorkflowCManualArtifactWriterObjectStore",
    "WorkflowCManualArtifactReceipt",
    "WorkflowCManualArtifactRecord",
    "WorkflowCManualArtifactRepository",
    "canonical_workflow_c_artifact_json",
    "decrypt_workflow_c_artifact_payload",
    "workflow_c_artifact_associated_data",
]
