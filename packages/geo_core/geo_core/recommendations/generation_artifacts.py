"""Encrypted MinIO artifacts for Recommendation model-child Prompt tasks."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
from uuid import UUID

from geo_core.object_store import StoredObject
from geo_core.recommendations.generation_artifact_contracts import (
    ARTIFACT_SECRET_PURPOSE,
    MANIFEST_CONTENT_TYPE,
    SHA256_PATTERN,
    RecommendationTaskArtifactDeletionTarget,
    RecommendationTaskArtifactError,
    RecommendationTaskArtifactPlan,
    RecommendationTaskArtifactRef,
    RecommendationTaskArtifactStore,
    RecommendationTaskObjectStore,
)
from geo_core.recommendations.generation_artifact_serialization import (
    assert_manifest_lineage,
    assert_plan,
    canonical_bytes,
    deletion_receipt,
    deletion_target,
    datetime_from_text,
    envelope_from_manifest,
    manifest,
    manifest_document,
    task_bytes,
    task_from_bytes,
    wipe,
)
from geo_core.recommendations.generation_worker_contracts import (
    RecommendationExecutionBackend,
    RecommendationModelTask,
)
from geo_core.secrets import (
    EnvelopeCipher,
    SecretReference,
    SecretValue,
)


class EncryptedRecommendationTaskArtifactStore:
    """Persist Prompt messages outside PostgreSQL using Secret Store envelope keys."""

    def __init__(
        self,
        *,
        object_store: RecommendationTaskObjectStore,
        cipher: EnvelopeCipher,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._objects = object_store
        self._cipher = cipher
        self._clock = clock

    def plan(self, task: RecommendationModelTask) -> RecommendationTaskArtifactPlan:
        plaintext = bytearray(task_bytes(task))
        try:
            content_hash = hashlib.sha256(plaintext).hexdigest()
            byte_size = len(plaintext)
        finally:
            wipe(plaintext)
        base = (
            f"recommendations/model-tasks/{task.project_id}/"
            f"{task.child_job_id}/{content_hash}"
        )
        manifest_key = f"{base}/manifest.json"
        payload_key = f"{base}/payload.bin"
        return RecommendationTaskArtifactPlan(
            project_id=task.project_id,
            parent_job_id=task.parent_job_id,
            child_job_id=task.child_job_id,
            parent_input_hash=task.parent_input_hash,
            content_hash=content_hash,
            byte_size=byte_size,
            manifest_key=manifest_key,
            manifest_uri=self._objects.uri_for_key(manifest_key),
            payload_key=payload_key,
            payload_uri=self._objects.uri_for_key(payload_key),
            expires_at=task.artifact_expires_at,
        )

    def put(
        self,
        task: RecommendationModelTask,
        *,
        plan: RecommendationTaskArtifactPlan | None = None,
    ) -> RecommendationTaskArtifactRef:
        planned = plan or self.plan(task)
        assert_plan(planned, task)
        created_at = self._clock()
        if created_at >= task.artifact_expires_at:
            raise RecommendationTaskArtifactError(
                "Recommendation task artifact expiry has elapsed"
            )
        plaintext = bytearray(task_bytes(task))
        content_byte_size = len(plaintext)
        content_hash = hashlib.sha256(plaintext).hexdigest()
        if (
            content_hash != planned.content_hash
            or content_byte_size != planned.byte_size
        ):
            wipe(plaintext)
            raise RecommendationTaskArtifactError(
                "Recommendation task changed after artifact planning"
            )
        try:
            envelope = self._cipher.encrypt(
                reference=SecretReference(
                    id=task.child_job_id,
                    project_id=task.project_id,
                    purpose=ARTIFACT_SECRET_PURPOSE,
                    created_at=created_at,
                ),
                version=1,
                value=SecretValue(plaintext),
                created_at=created_at,
            )
        finally:
            wipe(plaintext)
        payload_hash = hashlib.sha256(envelope.ciphertext).hexdigest()
        artifact_manifest = manifest(
            task=task,
            envelope=envelope,
            content_hash=content_hash,
            content_byte_size=content_byte_size,
            payload_uri=planned.payload_uri,
            payload_hash=payload_hash,
        )
        manifest_content = canonical_bytes(artifact_manifest)
        manifest_hash = hashlib.sha256(manifest_content).hexdigest()
        stored_payload: StoredObject | None = None
        stored_manifest: StoredObject | None = None
        try:
            stored_payload = self._objects.put_object(
                key=planned.payload_key,
                content=envelope.ciphertext,
                content_type="application/octet-stream",
                expected_hash=payload_hash,
            )
            if stored_payload.uri != planned.payload_uri:
                raise RecommendationTaskArtifactError(
                    "Recommendation task payload URI changed during persistence"
                )
            self._objects.get_s3_uri(
                uri=planned.payload_uri,
                expected_hash=payload_hash,
            )
            stored_manifest = self._objects.put_object(
                key=planned.manifest_key,
                content=manifest_content,
                content_type=MANIFEST_CONTENT_TYPE,
                expected_hash=manifest_hash,
            )
            if stored_manifest.uri != planned.manifest_uri:
                raise RecommendationTaskArtifactError(
                    "Recommendation task manifest URI changed during persistence"
                )
            self._objects.get_s3_uri(
                uri=stored_manifest.uri,
                expected_hash=manifest_hash,
            )
        except BaseException:
            for stored in (stored_manifest, stored_payload):
                if stored is not None:
                    self._objects.delete_s3_uri(uri=stored.uri)
            raise
        assert stored_manifest is not None
        return RecommendationTaskArtifactRef(
            uri=planned.manifest_uri,
            manifest_hash=manifest_hash,
            payload_uri=planned.payload_uri,
            payload_hash=payload_hash,
            content_hash=content_hash,
            byte_size=content_byte_size,
        )

    def inspect_for_deletion(
        self,
        reference: RecommendationTaskArtifactRef,
        *,
        project_id: UUID,
        child_job_id: UUID,
        expected_parent_input_hash: str,
    ) -> RecommendationTaskArtifactDeletionTarget:
        manifest_object = self._objects.get_s3_uri(
            uri=reference.uri,
            expected_hash=reference.manifest_hash,
        )
        artifact_manifest = manifest_document(manifest_object.content)
        assert_manifest_lineage(
            artifact_manifest,
            reference=reference,
            project_id=project_id,
            child_job_id=child_job_id,
            expected_parent_input_hash=expected_parent_input_hash,
        )
        return deletion_target(
            reference=reference,
            manifest_document=artifact_manifest,
            project_id=project_id,
            child_job_id=child_job_id,
        )

    def crypto_erase(
        self, target: RecommendationTaskArtifactDeletionTarget
    ) -> str:
        """Delete the manifest containing the wrapped DEK before ciphertext cleanup."""

        if not self._objects.delete_s3_uri(uri=target.reference.uri):
            raise RecommendationTaskArtifactError(
                "Recommendation task manifest could not be crypto-erased"
            )
        return deletion_receipt(target, phase="crypto_erased")

    def delete_ciphertext(
        self, target: RecommendationTaskArtifactDeletionTarget
    ) -> str:
        if not self._objects.delete_s3_uri(uri=target.payload_uri):
            raise RecommendationTaskArtifactError(
                "Recommendation task ciphertext could not be deleted"
            )
        return deletion_receipt(target, phase="deleted")

    def load(
        self,
        reference: RecommendationTaskArtifactRef,
        *,
        project_id: UUID,
        child_job_id: UUID,
        expected_parent_input_hash: str,
    ) -> RecommendationModelTask:
        if project_id.int == 0 or child_job_id.int == 0:
            raise RecommendationTaskArtifactError(
                "Recommendation task artifact scope is invalid"
            )
        if SHA256_PATTERN.fullmatch(expected_parent_input_hash) is None:
            raise RecommendationTaskArtifactError(
                "Recommendation task parent input hash is invalid"
            )
        manifest_object = self._objects.get_s3_uri(
            uri=reference.uri,
            expected_hash=reference.manifest_hash,
        )
        artifact_manifest = manifest_document(manifest_object.content)
        assert_manifest_lineage(
            artifact_manifest,
            reference=reference,
            project_id=project_id,
            child_job_id=child_job_id,
            expected_parent_input_hash=expected_parent_input_hash,
        )
        expires_at = datetime_from_text(artifact_manifest, "artifact_expires_at")
        if self._clock() >= expires_at:
            raise RecommendationTaskArtifactError(
                "Recommendation task artifact is expired"
            )
        payload = self._objects.get_s3_uri(
            uri=_manifest_text(artifact_manifest, "payload_uri"),
            expected_hash=_manifest_text(artifact_manifest, "payload_hash"),
        )
        envelope = envelope_from_manifest(artifact_manifest, payload.content)
        revealed = self._cipher.decrypt(envelope)
        plaintext = bytearray(revealed.reveal_bytes())
        try:
            if hashlib.sha256(plaintext).hexdigest() != reference.content_hash:
                raise RecommendationTaskArtifactError(
                    "Recommendation task plaintext hash changed"
                )
            task = task_from_bytes(bytes(plaintext))
        finally:
            wipe(plaintext)
        if (
            artifact_manifest.get("schema_version") == 1
            and task.execution_backend is not RecommendationExecutionBackend.MODEL_GATEWAY
        ):
            raise RecommendationTaskArtifactError(
                "legacy Recommendation task artifacts must remain on the native backend"
            )
        if (
            task.project_id != project_id
            or task.child_job_id != child_job_id
            or task.parent_input_hash != expected_parent_input_hash
            or task.artifact_expires_at != expires_at
        ):
            raise RecommendationTaskArtifactError(
                "Recommendation task artifact lineage changed"
            )
        return task


def _manifest_text(manifest_document: object, key: str) -> str:
    if not isinstance(manifest_document, dict):
        raise RecommendationTaskArtifactError("Recommendation task manifest is invalid")
    value = manifest_document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RecommendationTaskArtifactError(f"artifact {key} must be text")
    return value


__all__ = [
    "EncryptedRecommendationTaskArtifactStore",
    "RecommendationTaskArtifactDeletionTarget",
    "RecommendationTaskArtifactError",
    "RecommendationTaskArtifactPlan",
    "RecommendationTaskArtifactRef",
    "RecommendationTaskArtifactStore",
    "RecommendationTaskObjectStore",
]
