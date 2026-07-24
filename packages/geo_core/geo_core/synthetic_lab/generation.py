"""Frozen generation inputs and four-candidate batch contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from geo_core.synthetic_lab.domain import (
    SyntheticLabContractError,
    SyntheticLabScopeError,
    SyntheticOnly,
    _as_enum,
    _require_hash,
    _require_text,
    _require_uuid,
    assert_same_project,
    assert_synthetic_boundary,
)
from geo_core.synthetic_lab.review_cases import ReviewCase, ScenarioMode


DEFAULT_CANDIDATE_COUNT = 4
MAX_REGENERATION_BATCHES = 1
LAB_PROGRAM_KINDS = frozenset(
    {
        "generation",
        "claim_extraction",
        "conflict_check",
        "revision",
        "style_judge",
        "arbiter",
    }
)


class GenerationBatchKind(StrEnum):
    INITIAL = "initial"
    REGENERATED = "regenerated"


@dataclass(frozen=True, kw_only=True)
class FrozenCallLineage(SyntheticOnly):
    """Inputs and provider identity frozen for one completed model call."""

    project_id: UUID
    review_run_id: UUID
    review_suite_version_id: UUID
    review_suite_hash: str
    review_case_id: UUID
    review_case_hash: str
    program_kind: str
    prompt_release_id: UUID
    prompt_release_hash: str
    profile_version_id: UUID
    profile_hash: str
    fact_snapshot_id: UUID
    fact_snapshot_hash: str
    model_policy_hash: str
    model_call_id: UUID
    provider: str
    configured_model: str
    reported_model: str
    model_identity_hash: str
    request_hash: str
    response_hash: str

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.project_id, "call Project ID"),
            (self.review_run_id, "call Review Run ID"),
            (self.review_suite_version_id, "call Review Suite version ID"),
            (self.review_case_id, "call Review Case ID"),
            (self.prompt_release_id, "call Prompt Release ID"),
            (self.profile_version_id, "call Style Profile version ID"),
            (self.fact_snapshot_id, "call Fact snapshot ID"),
            (self.model_call_id, "model call ID"),
        ):
            _require_uuid(uuid_value, label)
        for hash_value, label in (
            (self.review_suite_hash, "Review Suite hash"),
            (self.review_case_hash, "Review Case hash"),
            (self.prompt_release_hash, "Prompt Release hash"),
            (self.profile_hash, "Style Profile hash"),
            (self.fact_snapshot_hash, "Fact snapshot hash"),
            (self.model_policy_hash, "model policy hash"),
            (self.model_identity_hash, "model identity hash"),
            (self.request_hash, "model request hash"),
            (self.response_hash, "model response hash"),
        ):
            _require_hash(hash_value, label)
        if self.program_kind not in LAB_PROGRAM_KINDS:
            raise SyntheticLabContractError(
                f"unsupported synthetic-lab Prompt program: {self.program_kind!r}"
            )
        for text_value, label in (
            (self.provider, "model provider"),
            (self.configured_model, "configured model"),
            (self.reported_model, "reported model"),
        ):
            _require_text(text_value, label)


@dataclass(frozen=True, kw_only=True)
class GeneratedCandidate(SyntheticOnly):
    id: UUID
    project_id: UUID
    review_run_id: UUID
    review_case_id: UUID
    generation_batch_id: UUID
    batch_number: int
    ordinal: int
    output_hash: str
    artifact_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "Candidate ID"),
            (self.project_id, "Candidate Project ID"),
            (self.review_run_id, "Candidate Review Run ID"),
            (self.review_case_id, "Candidate Review Case ID"),
            (self.generation_batch_id, "Candidate Generation Batch ID"),
        ):
            _require_uuid(value, label)
        if self.batch_number not in {1, 2}:
            raise SyntheticLabContractError("Candidate batch number must be 1 or 2")
        if not 1 <= self.ordinal <= DEFAULT_CANDIDATE_COUNT:
            raise SyntheticLabContractError("Candidate ordinal must be between 1 and 4")
        _require_hash(self.output_hash, "Candidate output hash")
        _require_hash(self.artifact_hash, "Candidate artifact hash")


@dataclass(frozen=True, kw_only=True)
class GenerationBatch(SyntheticOnly):
    id: UUID
    project_id: UUID
    review_run_id: UUID
    review_case_id: UUID
    batch_number: int
    kind: GenerationBatchKind
    scenario_mode: ScenarioMode
    creative_reference: str | None
    call_lineage: FrozenCallLineage
    candidates: tuple[GeneratedCandidate, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "Generation Batch ID"),
            (self.project_id, "Generation Batch Project ID"),
            (self.review_run_id, "Generation Batch Review Run ID"),
            (self.review_case_id, "Generation Batch Review Case ID"),
        ):
            _require_uuid(value, label)
        kind = _as_enum(self.kind, GenerationBatchKind, "Generation Batch kind")
        mode = _as_enum(self.scenario_mode, ScenarioMode, "scenario mode")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "scenario_mode", mode)
        expected_number = 1 if kind == GenerationBatchKind.INITIAL else 2
        if self.batch_number != expected_number:
            raise SyntheticLabContractError(
                f"{kind.value} Generation Batch must use number {expected_number}"
            )
        reference = (self.creative_reference or "").strip()
        if mode == ScenarioMode.GUIDED:
            if not reference:
                raise SyntheticLabContractError("guided generation accepts one creative reference")
            object.__setattr__(self, "creative_reference", reference)
        elif self.creative_reference is not None:
            raise SyntheticLabContractError(
                "autonomous generation cannot carry guided operator input"
            )
        candidates = tuple(self.candidates)
        object.__setattr__(self, "candidates", candidates)
        if len(candidates) != DEFAULT_CANDIDATE_COUNT:
            raise SyntheticLabContractError("each Generation Batch requires exactly 4 Candidates")
        if {candidate.ordinal for candidate in candidates} != set(
            range(1, DEFAULT_CANDIDATE_COUNT + 1)
        ):
            raise SyntheticLabContractError(
                "Generation Batch Candidate ordinals must be exactly 1 through 4"
            )
        if len({candidate.id for candidate in candidates}) != len(candidates):
            raise SyntheticLabContractError("Generation Batch Candidate IDs must be unique")
        if len({candidate.output_hash for candidate in candidates}) != len(candidates):
            raise SyntheticLabContractError("Generation Batch Candidate outputs must be unique")
        assert_same_project(self, self.call_lineage, *candidates)
        assert_synthetic_boundary(self, self.call_lineage, *candidates)
        if self.call_lineage.program_kind != "generation":
            raise SyntheticLabContractError("Generation Batch requires a generation Prompt call")
        if (
            self.call_lineage.review_run_id != self.review_run_id
            or self.call_lineage.review_case_id != self.review_case_id
        ):
            raise SyntheticLabScopeError(
                "Generation Batch and model call do not share Review Run/Case lineage"
            )
        if any(
            candidate.review_run_id != self.review_run_id
            or candidate.review_case_id != self.review_case_id
            or candidate.generation_batch_id != self.id
            or candidate.batch_number != self.batch_number
            for candidate in candidates
        ):
            raise SyntheticLabScopeError(
                "Candidate does not match its frozen Generation Batch lineage"
            )


_FROZEN_CONTEXT_FIELDS = (
    "project_id",
    "review_run_id",
    "review_suite_version_id",
    "review_suite_hash",
    "review_case_id",
    "review_case_hash",
    "profile_version_id",
    "profile_hash",
    "fact_snapshot_id",
    "fact_snapshot_hash",
    "model_policy_hash",
)


def assert_same_frozen_context(*lineages: FrozenCallLineage) -> FrozenCallLineage:
    if not lineages:
        raise SyntheticLabContractError("frozen context check requires model-call lineage")
    first = lineages[0]
    for lineage in lineages[1:]:
        if any(
            getattr(lineage, field) != getattr(first, field) for field in _FROZEN_CONTEXT_FIELDS
        ):
            raise SyntheticLabScopeError(
                "model calls do not share the same frozen Case/Profile/Fact context"
            )
    return first


def assert_call_lineage_for_case(case: ReviewCase, lineage: FrozenCallLineage) -> None:
    assert_same_project(case, lineage)
    assert_synthetic_boundary(case, lineage)
    if (
        lineage.review_case_id != case.id
        or lineage.review_case_hash != case.content_hash
        or lineage.review_suite_version_id != case.review_suite_version_id
        or lineage.profile_version_id != case.profile_version_id
        or lineage.profile_hash != case.profile_hash
        or lineage.fact_snapshot_id != case.fact_snapshot_id
        or lineage.fact_snapshot_hash != case.fact_snapshot_hash
    ):
        raise SyntheticLabScopeError(
            "model call does not bind the frozen Review Case/Profile/Fact lineage"
        )


def assert_generation_batch_for_case(case: ReviewCase, batch: GenerationBatch) -> None:
    assert_same_project(case, batch)
    assert_call_lineage_for_case(case, batch.call_lineage)
    if batch.review_case_id != case.id or batch.scenario_mode != case.mode:
        raise SyntheticLabScopeError("Generation Batch does not belong to the Review Case")
    if batch.creative_reference != case.creative_reference:
        raise SyntheticLabScopeError(
            "Generation Batch changed the Case creative-reference boundary"
        )


def assert_generation_history(
    case: ReviewCase,
    batches: tuple[GenerationBatch, ...],
) -> None:
    if not 1 <= len(batches) <= 1 + MAX_REGENERATION_BATCHES:
        raise SyntheticLabContractError(
            "generation history requires one initial and at most one regenerated Batch"
        )
    for batch in batches:
        assert_generation_batch_for_case(case, batch)
    ordered = tuple(sorted(batches, key=lambda batch: batch.batch_number))
    if ordered[0].kind != GenerationBatchKind.INITIAL:
        raise SyntheticLabContractError("generation history must start with the initial Batch")
    if len(ordered) == 2:
        if ordered[1].kind != GenerationBatchKind.REGENERATED:
            raise SyntheticLabContractError("second Generation Batch must be regenerated")
        assert_same_frozen_context(ordered[0].call_lineage, ordered[1].call_lineage)
        if ordered[0].id == ordered[1].id:
            raise SyntheticLabContractError("regenerated Batch requires a new identity")


def assert_fact_snapshot_current(
    lineage: FrozenCallLineage,
    *,
    current_snapshot_id: UUID,
    current_snapshot_hash: str,
    all_bound_facts_current_approved: bool,
) -> None:
    _require_uuid(current_snapshot_id, "current Fact snapshot ID")
    _require_hash(current_snapshot_hash, "current Fact snapshot hash")
    if (
        not all_bound_facts_current_approved
        or current_snapshot_id != lineage.fact_snapshot_id
        or current_snapshot_hash != lineage.fact_snapshot_hash
    ):
        raise SyntheticLabContractError(
            "frozen approved Fact lineage is stale; stop or bind a new Review Run"
        )


__all__ = [
    "DEFAULT_CANDIDATE_COUNT",
    "MAX_REGENERATION_BATCHES",
    "FrozenCallLineage",
    "GeneratedCandidate",
    "GenerationBatch",
    "GenerationBatchKind",
    "assert_call_lineage_for_case",
    "assert_fact_snapshot_current",
    "assert_generation_batch_for_case",
    "assert_generation_history",
    "assert_same_frozen_context",
]
