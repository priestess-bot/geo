"""Persistence-neutral parent/child contracts for Recommendation generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from uuid import UUID

from geo_core.model_gateway.contracts import ModelGatewayResult
from geo_core.recommendations.generation_contracts import (
    RecommendationGenerationSpec,
    ResolvedGenerationPrompt,
)


RECOMMENDATION_PARENT_JOB_KIND = "recommendation.generate"
RECOMMENDATION_PRIMARY_MODEL_JOB_KIND = "recommendation.model.primary"
RECOMMENDATION_ARBITER_MODEL_JOB_KIND = "recommendation.model.arbiter"
RECOMMENDATION_REQUIRED_JOB_KINDS = frozenset(
    {
        RECOMMENDATION_PARENT_JOB_KIND,
        RECOMMENDATION_PRIMARY_MODEL_JOB_KIND,
        RECOMMENDATION_ARBITER_MODEL_JOB_KIND,
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RecommendationModelRole(StrEnum):
    PRIMARY = "primary"
    ARBITER = "arbiter"

    @property
    def job_kind(self) -> str:
        return {
            RecommendationModelRole.PRIMARY: RECOMMENDATION_PRIMARY_MODEL_JOB_KIND,
            RecommendationModelRole.ARBITER: RECOMMENDATION_ARBITER_MODEL_JOB_KIND,
        }[self]


class RecommendationChildStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {
            RecommendationChildStatus.SUCCEEDED,
            RecommendationChildStatus.FAILED,
            RecommendationChildStatus.DEAD_LETTERED,
            RecommendationChildStatus.CANCELLED,
        }


@dataclass(frozen=True)
class RecommendationModelResultRef:
    model_attempt_id: UUID
    model_call_log_id: UUID
    response_hash: str
    output_hash: str
    artifact_uri: str
    artifact_manifest_hash: str
    artifact_content_hash: str

    def __post_init__(self) -> None:
        if self.model_attempt_id.int == 0 or self.model_call_log_id.int == 0:
            raise ValueError("Recommendation model result identities cannot be zero")
        for digest in (
            self.response_hash,
            self.output_hash,
            self.artifact_manifest_hash,
            self.artifact_content_hash,
        ):
            if _SHA256.fullmatch(digest) is None:
                raise ValueError("Recommendation model result lineage must be SHA-256")
        if not self.artifact_uri.startswith("s3://"):
            raise ValueError("Recommendation model result needs a governed S3 artifact")


@dataclass(frozen=True)
class RecommendationModelTask:
    child_job_id: UUID
    parent_job_id: UUID
    project_id: UUID
    parent_input_hash: str
    role: RecommendationModelRole
    runtime_selection_id: UUID
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    prompt: ResolvedGenerationPrompt
    admitted_by: UUID
    artifact_expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", RecommendationModelRole(self.role))
        if (
            self.child_job_id.int == 0
            or self.parent_job_id.int == 0
            or self.runtime_selection_id.int == 0
            or self.runtime_manifest_id.int == 0
            or self.runtime_option_id.int == 0
        ):
            raise ValueError("Recommendation model Job identities cannot be zero")
        if self.project_id != self.prompt.binding.project_id:
            raise ValueError("Recommendation model task crosses Project scope")
        if (
            self.artifact_expires_at.tzinfo is None
            or self.artifact_expires_at.utcoffset() is None
        ):
            raise ValueError("Recommendation model task expiry must be timezone-aware")
        if _SHA256.fullmatch(self.parent_input_hash) is None:
            raise ValueError("Recommendation parent input hash must be SHA-256")
        if self.runtime_selection_id != self.runtime_option_id:
            raise ValueError("Recommendation runtime selection must identify the frozen option")
        for digest in (self.runtime_manifest_hash, self.runtime_option_hash):
            if _SHA256.fullmatch(digest) is None:
                raise ValueError("Recommendation runtime lineage must be SHA-256")
        expected_kind = (
            "recommendation"
            if self.role is RecommendationModelRole.PRIMARY
            else "arbiter"
        )
        expected_purpose = (
            "recommendations.recommendation"
            if self.role is RecommendationModelRole.PRIMARY
            else "synthetic_lab.arbiter"
        )
        if self.prompt.binding.program_kind.value != expected_kind:
            raise ValueError("Recommendation model role differs from Prompt kind")
        if self.prompt.binding.purpose != expected_purpose:
            raise ValueError("Recommendation model role differs from exact Prompt purpose")


@dataclass(frozen=True)
class RecommendationModelOutcome:
    child_job_id: UUID
    role: RecommendationModelRole
    status: RecommendationChildStatus
    result: ModelGatewayResult | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", RecommendationModelRole(self.role))
        object.__setattr__(self, "status", RecommendationChildStatus(self.status))
        if self.child_job_id.int == 0:
            raise ValueError("Recommendation child Job identity cannot be zero")
        if self.status is RecommendationChildStatus.SUCCEEDED:
            if self.result is None or self.error_code is not None:
                raise ValueError("successful Recommendation child needs only a model result")
        elif self.result is not None:
            raise ValueError("non-successful Recommendation child cannot expose model output")
        if self.status.terminal and self.status is not RecommendationChildStatus.SUCCEEDED:
            if not (self.error_code or "").strip():
                raise ValueError("failed Recommendation child needs an error code")


@dataclass(frozen=True)
class RecommendationParentClaim:
    spec: RecommendationGenerationSpec
    primary: RecommendationModelOutcome | None = None
    arbiter: RecommendationModelOutcome | None = None

    def __post_init__(self) -> None:
        if self.primary is not None and self.primary.role is not RecommendationModelRole.PRIMARY:
            raise ValueError("primary Recommendation outcome has the wrong role")
        if self.arbiter is not None and self.arbiter.role is not RecommendationModelRole.ARBITER:
            raise ValueError("arbiter Recommendation outcome has the wrong role")
        if self.spec.arbiter_binding is None and self.arbiter is not None:
            raise ValueError("Recommendation without arbiter cannot have an arbiter outcome")


__all__ = [
    "RECOMMENDATION_ARBITER_MODEL_JOB_KIND",
    "RECOMMENDATION_PARENT_JOB_KIND",
    "RECOMMENDATION_PRIMARY_MODEL_JOB_KIND",
    "RECOMMENDATION_REQUIRED_JOB_KINDS",
    "RecommendationChildStatus",
    "RecommendationModelOutcome",
    "RecommendationModelResultRef",
    "RecommendationModelRole",
    "RecommendationModelTask",
    "RecommendationParentClaim",
]
