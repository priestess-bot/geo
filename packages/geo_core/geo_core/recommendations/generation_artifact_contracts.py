"""Public contracts for governed Recommendation child-task artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from geo_core.object_store import RetrievedObject, StoredObject
from geo_core.recommendations.errors import RecommendationRuleViolation
from geo_core.recommendations.generation_worker_contracts import RecommendationModelTask


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_CONTENT_TYPE = "application/vnd.geo.recommendation-model-task-manifest+json"
ARTIFACT_SECRET_PURPOSE = "recommendation.child_task"


class RecommendationTaskArtifactError(RuntimeError):
    """A governed Recommendation task artifact failed integrity or decryption."""


class RecommendationTaskObjectStore(Protocol):
    def uri_for_key(self, key: str) -> str: ...

    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObject: ...

    def get_s3_uri(
        self, *, uri: str, expected_hash: str | None = None
    ) -> RetrievedObject: ...

    def delete_s3_uri(self, *, uri: str) -> bool: ...


@dataclass(frozen=True)
class RecommendationTaskArtifactRef:
    uri: str
    manifest_hash: str
    payload_uri: str
    payload_hash: str
    content_hash: str
    byte_size: int

    def __post_init__(self) -> None:
        if not self.uri.startswith("s3://") or not self.payload_uri.startswith("s3://"):
            raise RecommendationRuleViolation("Recommendation task artifact needs S3 URIs")
        for value in (self.manifest_hash, self.payload_hash, self.content_hash):
            if SHA256_PATTERN.fullmatch(value) is None:
                raise RecommendationRuleViolation(
                    "Recommendation task artifact hashes must be SHA-256"
                )
        if self.byte_size < 1:
            raise RecommendationRuleViolation(
                "Recommendation task artifact byte size must be positive"
            )


@dataclass(frozen=True)
class RecommendationTaskArtifactPlan:
    project_id: UUID
    parent_job_id: UUID
    child_job_id: UUID
    parent_input_hash: str
    content_hash: str
    byte_size: int
    manifest_key: str
    manifest_uri: str
    payload_key: str
    payload_uri: str
    expires_at: datetime


@dataclass(frozen=True)
class RecommendationTaskArtifactDeletionTarget:
    reference: RecommendationTaskArtifactRef
    payload_uri: str
    payload_hash: str
    expires_at: datetime
    tombstone_hash: str


class RecommendationTaskArtifactStore(Protocol):
    def put(self, task: RecommendationModelTask) -> RecommendationTaskArtifactRef: ...

    def load(
        self,
        reference: RecommendationTaskArtifactRef,
        *,
        project_id: UUID,
        child_job_id: UUID,
        expected_parent_input_hash: str,
    ) -> RecommendationModelTask: ...


__all__ = [
    "ARTIFACT_SECRET_PURPOSE",
    "MANIFEST_CONTENT_TYPE",
    "SHA256_PATTERN",
    "RecommendationTaskArtifactDeletionTarget",
    "RecommendationTaskArtifactError",
    "RecommendationTaskArtifactPlan",
    "RecommendationTaskArtifactRef",
    "RecommendationTaskArtifactStore",
    "RecommendationTaskObjectStore",
]
