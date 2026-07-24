"""Dependency-light typed values for Workflow C metric model children."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from geo_core.semantic_metrics import MetricJudgePlan, MetricObservation


class WorkflowCMetricJudgeWorkerContractError(RuntimeError):
    """A metric model child or encrypted task is not frozen and valid."""


@dataclass(frozen=True)
class MetricChild:
    project_id: UUID
    parent_job_id: UUID
    child_job_id: UUID
    batch_id: UUID
    role: str
    evaluator_id: str
    candidate_id: UUID
    parent_input_hash: str
    runtime_selection_id: UUID
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    prompt_binding_id: UUID
    prompt_binding_version: int
    prompt_frozen_state_id: UUID
    prompt_state_version: int
    prompt_release_id: UUID
    prompt_release_version: int
    prompt_release_hash: str
    prompt_purpose: str
    prompt_bundle_hash: str
    portable_output_schema_hash: str
    application_output_schema_hash: str
    task_ciphertext: bytes
    task_data_nonce: bytes
    task_wrapped_data_key: bytes
    task_wrap_nonce: bytes
    task_master_key_version: int
    task_algorithm: str
    task_hash: str
    task_created_at: datetime


@dataclass(frozen=True)
class MetricChildReference:
    child_job_id: UUID
    parent_job_id: UUID
    batch_id: UUID
    role: str
    parent_input_hash: str
    task_hash: str


@dataclass(frozen=True)
class ModelRequestTask:
    messages: tuple[dict[str, str], ...]
    configured_model: str
    temperature: float
    max_output_tokens: int
    output_schema: Mapping[str, object]
    application_output_schema: Mapping[str, object]
    seed: int | None
    tool_mode: str | None
    search_mode: str | None
    deadline_at: datetime | None


@dataclass(frozen=True)
class MetricJudgeTask:
    subject_id: str
    output_locale: str
    schema_version: str
    observation: MetricObservation
    plans: tuple[MetricJudgePlan, ...]


@dataclass(frozen=True)
class MetricArbiterTask:
    subject_id: str
    output_locale: str
    candidate_ids: tuple[str, ...]
    evaluator_ids: tuple[str, ...]
    allowed_evidence_refs: frozenset[str]
    allowed_citation_refs: frozenset[str]


@dataclass(frozen=True)
class MetricTask:
    role: str
    admitted_by: UUID
    admitted_at: datetime
    request: ModelRequestTask
    judge: MetricJudgeTask | None
    arbiter: MetricArbiterTask | None


__all__ = [
    "MetricArbiterTask",
    "MetricChild",
    "MetricChildReference",
    "MetricJudgeTask",
    "MetricTask",
    "ModelRequestTask",
    "WorkflowCMetricJudgeWorkerContractError",
]
