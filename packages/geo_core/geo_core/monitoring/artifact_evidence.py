"""Server-side verification for immutable monitoring evidence artifacts."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol
from uuid import UUID

from geo_core.monitoring.source_contract import CaptureMethod, RawEvidence, RawEvidenceKind
from geo_core.object_store import ObjectStoreError, S3CompatibleObjectStore, parse_s3_uri


class RawArtifactVerificationError(RuntimeError):
    """The referenced object is absent, out of scope, or hash-mismatched."""


class RawArtifactVerifier(Protocol):
    def verify(
        self,
        *,
        project_id: UUID,
        capture_method: CaptureMethod,
        evidence: RawEvidence,
    ) -> RawEvidence: ...


class S3RawArtifactVerifier:
    def __init__(self, object_store: S3CompatibleObjectStore) -> None:
        self._object_store = object_store

    def verify(
        self,
        *,
        project_id: UUID,
        capture_method: CaptureMethod,
        evidence: RawEvidence,
    ) -> RawEvidence:
        if evidence.kind != RawEvidenceKind.ARTIFACT:
            return evidence
        assert evidence.artifact_uri is not None
        assert evidence.artifact_hash is not None
        try:
            _bucket, key = parse_s3_uri(evidence.artifact_uri)
            if not _allowed_key(
                project_id=project_id, capture_method=capture_method, key=key
            ):
                raise RawArtifactVerificationError(
                    "raw artifact is outside the project-scoped monitoring prefixes"
                )
            retrieved = self._object_store.get_s3_uri(
                uri=evidence.artifact_uri, expected_hash=evidence.artifact_hash
            )
        except ObjectStoreError as error:
            raise RawArtifactVerificationError("raw artifact verification failed") from error
        if retrieved.content_hash != evidence.artifact_hash:
            raise RawArtifactVerificationError("raw artifact hash does not match")
        return replace(evidence, artifact_verified=True)


def _allowed_key(*, project_id: UUID, capture_method: CaptureMethod, key: str) -> bool:
    project = str(project_id)
    if capture_method == CaptureMethod.SYNTHETIC:
        return key.startswith(f"content-simulations/{project}/")
    return key.startswith(f"observation-artifacts/{project}/")
