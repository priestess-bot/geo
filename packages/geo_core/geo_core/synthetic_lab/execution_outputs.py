"""Immutable outputs produced by Synthetic Lab execution tasks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from uuid import UUID

from geo_core.prompts.bootstrap_limits import STYLE_PROFILE_SUMMARY_MAX_CHARACTERS
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.corpus import CorpusVersion
from geo_core.synthetic_lab.domain import (
    SyntheticLabContractError,
    _require_hash,
    _require_text,
    _require_uuid,
)
from geo_core.synthetic_lab.evaluation import CandidateEvaluation
from geo_core.synthetic_lab.generation import GenerationBatch
from geo_core.synthetic_lab.offline_experiment import OfflineSlotResult
from geo_core.synthetic_lab.offline_results import OfflineExperimentResult
from geo_core.synthetic_lab.revision import CandidateResolution, CandidateRevision


@dataclass(frozen=True, kw_only=True)
class StyleProfileBuildOutput:
    project_id: UUID
    profile_version_id: UUID
    profile_hash: str
    artifact_hash: str
    model_call_ids: tuple[UUID, ...]
    profile_summary: str | None = None
    workflow_attempt_ids: tuple[UUID, ...] = ()
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "Profile result Project")
        _require_uuid(self.profile_version_id, "Profile result version")
        _require_hash(self.profile_hash, "Profile result")
        _require_hash(self.artifact_hash, "Profile artifact")
        if self.profile_summary is not None:
            _require_text(self.profile_summary, "Profile result summary")
            if len(self.profile_summary) > STYLE_PROFILE_SUMMARY_MAX_CHARACTERS:
                raise SyntheticLabContractError("Profile result summary is too large")
        if len(self.model_call_ids) + len(self.workflow_attempt_ids) != 1:
            raise SyntheticLabContractError(
                "Profile build requires exactly one model or workflow call"
            )
        for value in (*self.model_call_ids, *self.workflow_attempt_ids):
            _require_uuid(value, "Profile execution call")
        hash_value: dict[str, object] = {
            "project_id": self.project_id,
            "profile_version_id": self.profile_version_id,
            "profile_hash": self.profile_hash,
            "artifact_hash": self.artifact_hash,
            "model_call_ids": self.model_call_ids,
            "profile_summary": self.profile_summary,
        }
        if self.workflow_attempt_ids:
            hash_value["workflow_attempt_ids"] = self.workflow_attempt_ids
        object.__setattr__(
            self,
            "result_hash",
            canonical_hash(hash_value),
        )


@dataclass(frozen=True, kw_only=True)
class ReviewCaseRunOutput:
    project_id: UUID
    review_run_id: UUID
    review_case_id: UUID
    batches: tuple[GenerationBatch, ...]
    revisions: tuple[CandidateRevision, ...]
    evaluations: tuple[CandidateEvaluation, ...]
    resolution: CandidateResolution
    model_call_ids: tuple[UUID, ...]
    resolved_candidate_text: str | None = None
    workflow_attempt_ids: tuple[UUID, ...] = ()
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.project_id, "Review result Project"),
            (self.review_run_id, "Review result Run"),
            (self.review_case_id, "Review result Case"),
        ):
            _require_uuid(value, label)
        if (
            not self.batches
            or not self.evaluations
            or not (self.model_call_ids or self.workflow_attempt_ids)
        ):
            raise SyntheticLabContractError("Review result is missing execution evidence")
        for value in (*self.model_call_ids, *self.workflow_attempt_ids):
            _require_uuid(value, "Review execution call")
        if self.resolution.review_case_id != self.review_case_id:
            raise SyntheticLabContractError("Review result resolution belongs to another Case")
        if self.resolved_candidate_text is not None:
            _require_text(self.resolved_candidate_text, "resolved Candidate text")
            if len(self.resolved_candidate_text) > 100_000:
                raise SyntheticLabContractError("resolved Candidate text is too large")
            if (
                canonical_hash(self.resolved_candidate_text)
                != self.resolution.candidate_output_hash
            ):
                raise SyntheticLabContractError("resolved Candidate text changed")
        hash_value: dict[str, object] = {
            "project_id": self.project_id,
            "review_run_id": self.review_run_id,
            "review_case_id": self.review_case_id,
            "batches": self.batches,
            "revisions": self.revisions,
            "evaluations": self.evaluations,
            "resolution": self.resolution,
            "model_call_ids": self.model_call_ids,
        }
        if self.resolved_candidate_text is not None:
            hash_value["resolved_candidate_text"] = self.resolved_candidate_text
        if self.workflow_attempt_ids:
            hash_value["workflow_attempt_ids"] = self.workflow_attempt_ids
        object.__setattr__(
            self,
            "result_hash",
            canonical_hash(hash_value),
        )


@dataclass(frozen=True, kw_only=True)
class CorpusFinalizeOutput:
    project_id: UUID
    corpus: CorpusVersion
    candidate_text: Mapping[UUID, str]
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "Corpus result Project")
        if self.corpus.project_id != self.project_id:
            raise SyntheticLabContractError("Corpus result crosses Project scope")
        texts = dict(self.candidate_text)
        object.__setattr__(self, "candidate_text", MappingProxyType(texts))
        candidates = {item.candidate_id: item for item in self.corpus.candidates}
        if set(texts) != set(candidates) or any(
            not text.strip()
            or canonical_hash(text) != candidates[candidate_id].candidate_output_hash
            for candidate_id, text in texts.items()
        ):
            raise SyntheticLabContractError("Corpus result text manifest changed")
        object.__setattr__(
            self,
            "result_hash",
            canonical_hash(
                {
                    "project_id": self.project_id,
                    "corpus": self.corpus,
                    "candidate_text_hashes": {
                        str(key): canonical_hash(value) for key, value in texts.items()
                    },
                }
            ),
        )


@dataclass(frozen=True, kw_only=True)
class OfflineExperimentRunOutput:
    project_id: UUID
    experiment_id: UUID
    result_id: UUID
    slot_results: tuple[OfflineSlotResult, ...]
    model_call_ids: tuple[UUID, ...]
    summary: OfflineExperimentResult | None = None
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.project_id, "Experiment result Project"),
            (self.experiment_id, "Experiment"),
            (self.result_id, "Experiment result"),
        ):
            _require_uuid(value, label)
        if not self.slot_results:
            raise SyntheticLabContractError("Offline Experiment produced no slot results")
        if self.summary is not None:
            if (
                self.summary.project_id != self.project_id
                or self.summary.experiment_id != self.experiment_id
                or self.summary.id != self.result_id
            ):
                raise SyntheticLabContractError(
                    "Offline Experiment summary crosses its frozen result identity"
                )
            if self.summary.slot_membership_hash != canonical_hash(
                [
                    {"slot_id": item.slot_id, "result_hash": item.result_hash}
                    for item in sorted(self.slot_results, key=lambda value: value.slot_id)
                ]
            ):
                raise SyntheticLabContractError(
                    "Offline Experiment summary changed the slot result membership"
                )
        hash_value: dict[str, object] = {
            "project_id": self.project_id,
            "experiment_id": self.experiment_id,
            "result_id": self.result_id,
            "slot_results": self.slot_results,
            "model_call_ids": self.model_call_ids,
        }
        if self.summary is not None:
            hash_value["summary"] = self.summary
        object.__setattr__(
            self,
            "result_hash",
            canonical_hash(hash_value),
        )


_PUBLIC_MODULE = "geo_core.synthetic_lab.execution_contracts"
for _output_type in (
    StyleProfileBuildOutput,
    ReviewCaseRunOutput,
    CorpusFinalizeOutput,
    OfflineExperimentRunOutput,
):
    _output_type.__module__ = _PUBLIC_MODULE


__all__ = [
    "CorpusFinalizeOutput",
    "OfflineExperimentRunOutput",
    "ReviewCaseRunOutput",
    "StyleProfileBuildOutput",
]
