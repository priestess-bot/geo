"""Worker-only recovery of governed Workflow C manual evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import hmac
from typing import Any
from uuid import UUID

import psycopg

from geo_core.project_scope import set_project_scope
from geo_core.sampling.contracts import SamplingRuleViolation
from geo_core.sampling.manual_artifact_governance import wipe_bytearray
from geo_core.sampling.manual_artifact_storage import (
    WorkflowCManualArtifactObjectStore,
    decrypt_workflow_c_artifact_payload,
    workflow_c_artifact_associated_data,
)
from geo_core.secrets import EnvelopeCipher
from geo_core.workflow_c_artifacts.postgres import (
    decrypt_workflow_c_artifact_dek,
    validate_workflow_c_artifact_manifest,
)


@dataclass(frozen=True, kw_only=True)
class WorkflowCManualArtifactReadRequest:
    project_id: UUID
    artifact_id: UUID
    expected_manifest_hash: str
    expected_content_hash: str


@dataclass(frozen=True, kw_only=True, repr=False)
class RecoveredWorkflowCManualArtifact:
    artifact_id: UUID
    evidence_kind: str
    persisted_content_type: str
    manifest_hash: str
    content_hash: str
    payload: bytearray = field(repr=False)
    expires_at: datetime

    def wipe(self) -> None:
        wipe_bytearray(self.payload)


class PostgresWorkflowCManualArtifactReader:
    """Recover only an active, unexpired, Admin-governed redacted derivative."""

    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        cipher: EnvelopeCipher,
        object_store: WorkflowCManualArtifactObjectStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._cipher = cipher
        self._objects = object_store
        self._clock = clock

    def __repr__(self) -> str:
        return "PostgresWorkflowCManualArtifactReader([REDACTED])"

    def load(
        self, request: WorkflowCManualArtifactReadRequest
    ) -> RecoveredWorkflowCManualArtifact:
        now = self._clock()
        _require_aware(now)
        row = self._load_row(request)
        if (
            row["status"] != "active"
            or row["dek_status"] != "active"
            or row["expires_at"] <= now
            or row["classification"] != "restricted_manual_evidence"
            or row["audience"] != "admin_only"
            or bool(row["export_allowed"])
            or bool(row["raw_retained"])
        ):
            raise SamplingRuleViolation(
                "Workflow C manual artifact is not eligible for worker recovery"
            )
        if not hmac.compare_digest(
            str(row["manifest_hash"]), request.expected_manifest_hash
        ) or not hmac.compare_digest(
            str(row["redacted_content_hash"]), request.expected_content_hash
        ):
            raise SamplingRuleViolation(
                "Workflow C manual artifact expected lineage changed"
            )
        manifest = self._objects.get_s3_uri(
            uri=str(row["manifest_uri"]), expected_hash=str(row["manifest_hash"])
        )
        payload = self._objects.get_s3_uri(
            uri=str(row["object_uri"]), expected_hash=str(row["object_hash"])
        )
        validate_workflow_c_artifact_manifest(row, manifest.content)
        key_material = bytearray()
        plaintext = bytearray()
        try:
            key_material = decrypt_workflow_c_artifact_dek(self._cipher, row)
            plaintext = decrypt_workflow_c_artifact_payload(
                encrypted_payload=payload.content,
                key_material=key_material,
                associated_data=workflow_c_artifact_associated_data(
                    project_id=request.project_id,
                    artifact_id=request.artifact_id,
                    persisted_content_hash=request.expected_content_hash,
                    governance_policy_hash=str(row["governance_policy_hash"]),
                ),
            )
            if not hmac.compare_digest(
                hashlib.sha256(plaintext).hexdigest(), request.expected_content_hash
            ):
                raise SamplingRuleViolation(
                    "Workflow C recovered manual artifact hash changed"
                )
            recovered = RecoveredWorkflowCManualArtifact(
                artifact_id=request.artifact_id,
                evidence_kind=str(row["evidence_kind"]),
                persisted_content_type=str(row["persisted_content_type"]),
                manifest_hash=request.expected_manifest_hash,
                content_hash=request.expected_content_hash,
                payload=bytearray(plaintext),
                expires_at=row["expires_at"],
            )
            return recovered
        finally:
            wipe_bytearray(key_material)
            wipe_bytearray(plaintext)

    def _load_row(
        self, request: WorkflowCManualArtifactReadRequest
    ) -> Mapping[str, Any]:
        try:
            with self._connect() as connection:
                set_project_scope(connection, request.project_id)
                row = connection.execute(
                    """SELECT artifact.*,
                              dek.status AS dek_status, dek.ciphertext,
                              dek.data_nonce, dek.wrapped_data_key,
                              dek.wrap_nonce, dek.master_key_version,
                              dek.algorithm AS dek_algorithm,
                              dek.created_at AS dek_created_at
                         FROM workflow_c_manual_artifacts artifact
                         JOIN workflow_c_artifact_deks dek
                           ON dek.key_ref = artifact.key_ref
                          AND dek.project_id = artifact.project_id
                          AND dek.artifact_id = artifact.artifact_id
                        WHERE artifact.project_id = %s
                          AND artifact.artifact_id = %s""",
                    (request.project_id, request.artifact_id),
                ).fetchone()
        except psycopg.Error as exc:
            raise SamplingRuleViolation(
                "Workflow C manual artifact lineage is unavailable"
            ) from exc
        if row is None:
            raise SamplingRuleViolation(
                "Workflow C manual artifact does not exist"
            )
        return row


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SamplingRuleViolation(
            "Workflow C manual artifact reader clock must be timezone-aware"
        )


__all__ = [
    "PostgresWorkflowCManualArtifactReader",
    "RecoveredWorkflowCManualArtifact",
    "WorkflowCManualArtifactReadRequest",
]
