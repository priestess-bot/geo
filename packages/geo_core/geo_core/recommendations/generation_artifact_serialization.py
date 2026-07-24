"""Manifest and encrypted-task serialization for Recommendation artifacts."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from datetime import datetime
import hashlib
import json
from typing import Any
from uuid import UUID

from geo_core.recommendations.generation_artifact_contracts import (
    RecommendationTaskArtifactDeletionTarget,
    RecommendationTaskArtifactError,
    RecommendationTaskArtifactPlan,
    RecommendationTaskArtifactRef,
    SHA256_PATTERN,
)
from geo_core.recommendations.errors import RecommendationRuleViolation
from geo_core.recommendations.generation_worker_contracts import RecommendationModelTask
from geo_core.recommendations.postgres.generation_worker_codec import (
    model_task_from_payload,
    model_task_payload,
)
from geo_core.secrets import EncryptedSecretVersion, SecretVersionHandle


def task_bytes(task: RecommendationModelTask) -> bytes:
    return canonical_bytes(model_task_payload(task))


def manifest(
    *,
    task: RecommendationModelTask,
    envelope: EncryptedSecretVersion,
    content_hash: str,
    content_byte_size: int,
    payload_uri: str,
    payload_hash: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "classification": "internal_confidential",
        "project_id": str(task.project_id),
        "child_job_id": str(task.child_job_id),
        "parent_job_id": str(task.parent_job_id),
        "parent_input_hash": task.parent_input_hash,
        "role": task.role.value,
        "artifact_expires_at": task.artifact_expires_at.isoformat(),
        "content_hash": content_hash,
        "content_byte_size": content_byte_size,
        "payload_uri": payload_uri,
        "payload_hash": payload_hash,
        "encryption": {
            "algorithm": envelope.algorithm,
            "secret_purpose": envelope.handle.purpose,
            "secret_version": envelope.handle.version,
            "master_key_version": envelope.master_key_version,
            "data_nonce": b64(envelope.data_nonce),
            "wrapped_data_key": b64(envelope.wrapped_data_key),
            "wrap_nonce": b64(envelope.wrap_nonce),
            "created_at": envelope.created_at.isoformat(),
        },
    }


def envelope_from_manifest(
    manifest_document: Mapping[str, Any], ciphertext: bytes
) -> EncryptedSecretVersion:
    project_id = UUID(text(manifest_document, "project_id"))
    child_job_id = UUID(text(manifest_document, "child_job_id"))
    encryption = mapping(manifest_document.get("encryption"), "artifact encryption")
    return EncryptedSecretVersion(
        handle=SecretVersionHandle(
            reference_id=child_job_id,
            project_id=project_id,
            purpose=text(encryption, "secret_purpose"),
            version=integer(encryption, "secret_version"),
        ),
        ciphertext=ciphertext,
        data_nonce=decode_b64(encryption, "data_nonce"),
        wrapped_data_key=decode_b64(encryption, "wrapped_data_key"),
        wrap_nonce=decode_b64(encryption, "wrap_nonce"),
        master_key_version=integer(encryption, "master_key_version"),
        created_at=datetime_from_text(encryption, "created_at"),
        algorithm=text(encryption, "algorithm"),
    )


def assert_manifest_lineage(
    manifest_document: Mapping[str, Any],
    *,
    reference: RecommendationTaskArtifactRef,
    project_id: UUID,
    child_job_id: UUID,
    expected_parent_input_hash: str,
) -> None:
    if manifest_document.get("schema_version") != 1:
        raise RecommendationTaskArtifactError(
            "Recommendation task artifact schema changed"
        )
    expected = (
        str(project_id),
        str(child_job_id),
        expected_parent_input_hash,
        reference.content_hash,
        reference.payload_uri,
        reference.payload_hash,
        reference.byte_size,
        "internal_confidential",
    )
    observed = (
        manifest_document.get("project_id"),
        manifest_document.get("child_job_id"),
        manifest_document.get("parent_input_hash"),
        manifest_document.get("content_hash"),
        manifest_document.get("payload_uri"),
        manifest_document.get("payload_hash"),
        manifest_document.get("content_byte_size"),
        manifest_document.get("classification"),
    )
    if observed != expected:
        raise RecommendationTaskArtifactError(
            "Recommendation task manifest lineage changed"
        )


def assert_plan(plan: RecommendationTaskArtifactPlan, task: RecommendationModelTask) -> None:
    expected = (
        task.project_id,
        task.parent_job_id,
        task.child_job_id,
        task.parent_input_hash,
        task.artifact_expires_at,
    )
    observed = (
        plan.project_id,
        plan.parent_job_id,
        plan.child_job_id,
        plan.parent_input_hash,
        plan.expires_at,
    )
    if observed != expected:
        raise RecommendationTaskArtifactError("Recommendation artifact plan lineage changed")
    if (
        SHA256_PATTERN.fullmatch(plan.content_hash) is None
        or plan.byte_size < 1
        or not plan.manifest_uri.startswith("s3://")
        or not plan.payload_uri.startswith("s3://")
        or not plan.manifest_key.endswith("/manifest.json")
        or not plan.payload_key.endswith("/payload.bin")
    ):
        raise RecommendationTaskArtifactError("Recommendation artifact plan shape is invalid")


def deletion_target(
    *,
    reference: RecommendationTaskArtifactRef,
    manifest_document: Mapping[str, Any],
    project_id: UUID,
    child_job_id: UUID,
) -> RecommendationTaskArtifactDeletionTarget:
    expires_at = datetime_from_text(manifest_document, "artifact_expires_at")
    payload_uri = text(manifest_document, "payload_uri")
    payload_hash = text(manifest_document, "payload_hash")
    if payload_uri != reference.payload_uri or payload_hash != reference.payload_hash:
        raise RecommendationTaskArtifactError(
            "Recommendation task payload lineage changed"
        )
    tombstone_hash = hashlib.sha256(
        canonical_bytes(
            {
                "schema_version": 1,
                "project_id": str(project_id),
                "child_job_id": str(child_job_id),
                "manifest_uri": reference.uri,
                "manifest_hash": reference.manifest_hash,
                "payload_uri": payload_uri,
                "payload_hash": payload_hash,
                "content_hash": reference.content_hash,
                "expires_at": expires_at.isoformat(),
            }
        )
    ).hexdigest()
    return RecommendationTaskArtifactDeletionTarget(
        reference=reference,
        payload_uri=payload_uri,
        payload_hash=payload_hash,
        expires_at=expires_at,
        tombstone_hash=tombstone_hash,
    )


def deletion_receipt(
    target: RecommendationTaskArtifactDeletionTarget, *, phase: str
) -> str:
    return hashlib.sha256(
        canonical_bytes(
            {
                "schema_version": 1,
                "phase": phase,
                "manifest_uri": target.reference.uri,
                "manifest_hash": target.reference.manifest_hash,
                "payload_uri": target.payload_uri,
                "payload_hash": target.payload_hash,
                "tombstone_hash": target.tombstone_hash,
            }
        )
    ).hexdigest()


def task_from_bytes(value: bytes) -> RecommendationModelTask:
    try:
        payload = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecommendationTaskArtifactError("Recommendation task artifact JSON is invalid") from error
    try:
        return model_task_from_payload(payload)
    except (TypeError, ValueError, RecommendationRuleViolation) as error:
        raise RecommendationTaskArtifactError(
            "Recommendation task artifact contract changed"
        ) from error


def manifest_document(value: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecommendationTaskArtifactError("Recommendation task manifest JSON is invalid") from error
    return mapping(payload, "Recommendation task manifest")


def canonical_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RecommendationTaskArtifactError(f"{label} must be an object")
    return value


def text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise RecommendationTaskArtifactError(f"artifact {key} must be text")
    return item


def integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise RecommendationTaskArtifactError(f"artifact {key} must be an integer")
    return item


def b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def decode_b64(value: Mapping[str, Any], key: str) -> bytes:
    try:
        return base64.b64decode(text(value, key), validate=True)
    except (binascii.Error, ValueError) as error:
        raise RecommendationTaskArtifactError(
            f"artifact {key} is not canonical base64"
        ) from error


def datetime_from_text(value: Mapping[str, Any], key: str) -> datetime:
    try:
        result = datetime.fromisoformat(text(value, key))
    except ValueError as error:
        raise RecommendationTaskArtifactError(f"artifact {key} is not ISO-8601") from error
    if result.tzinfo is None:
        raise RecommendationTaskArtifactError(f"artifact {key} must be timezone-aware")
    return result


def wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = [
    "assert_manifest_lineage",
    "assert_plan",
    "canonical_bytes",
    "datetime_from_text",
    "deletion_receipt",
    "deletion_target",
    "envelope_from_manifest",
    "manifest",
    "manifest_document",
    "task_bytes",
    "task_from_bytes",
    "wipe",
]
