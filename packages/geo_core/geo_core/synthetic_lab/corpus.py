"""Immutable Corpus versions and guarded freeze contracts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from geo_core.synthetic_lab.domain import (
    SyntheticLabContractError,
    SyntheticLabScopeError,
    SyntheticOnly,
    _as_enum,
    _canonical_hash,
    _require_channel,
    _require_hash,
    _require_text,
    _require_uuid,
    assert_same_project,
    assert_synthetic_boundary,
)
from geo_core.synthetic_lab.revision import CandidateResolution, ReviewRunStatus


class CorpusRole(StrEnum):
    NO_CORPUS_BASELINE = "no_corpus_baseline"
    CURRENT_APPROVED = "current_approved_corpus"
    NEW_CANDIDATE = "new_candidate_corpus"


@dataclass(frozen=True, kw_only=True)
class FinalizationGuard(SyntheticOnly):
    project_id: UUID
    resource_id: UUID
    expected_lease_id: UUID
    held_lease_id: UUID | None
    expected_fencing_token: int
    held_fencing_token: int | None
    fact_snapshot_id: UUID
    fact_snapshot_hash: str
    facts_current_approved: bool
    cancelled: bool = False

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.project_id, "finalization Project ID"),
            (self.resource_id, "finalization resource ID"),
            (self.expected_lease_id, "expected lease ID"),
            (self.fact_snapshot_id, "finalization Fact snapshot ID"),
        ):
            _require_uuid(uuid_value, label)
        if self.held_lease_id is not None:
            _require_uuid(self.held_lease_id, "held lease ID")
        if self.expected_fencing_token < 1:
            raise SyntheticLabContractError("expected fencing token must be positive")
        if self.held_fencing_token is not None and self.held_fencing_token < 1:
            raise SyntheticLabContractError("held fencing token must be positive")
        _require_hash(self.fact_snapshot_hash, "finalization Fact snapshot hash")

    @property
    def evidence_hash(self) -> str:
        return _canonical_hash(
            {
                "project_id": str(self.project_id),
                "resource_id": str(self.resource_id),
                "expected_lease_id": str(self.expected_lease_id),
                "held_lease_id": str(self.held_lease_id) if self.held_lease_id else None,
                "expected_fencing_token": self.expected_fencing_token,
                "held_fencing_token": self.held_fencing_token,
                "fact_snapshot_id": str(self.fact_snapshot_id),
                "fact_snapshot_hash": self.fact_snapshot_hash,
                "facts_current_approved": self.facts_current_approved,
                "cancelled": self.cancelled,
            }
        )


@dataclass(frozen=True, kw_only=True)
class CorpusCandidateEntry(SyntheticOnly):
    project_id: UUID
    resolution_id: UUID
    candidate_id: UUID
    candidate_output_hash: str
    status: ReviewRunStatus
    warning_codes: tuple[str, ...]
    channel: str
    scenario_mode: str
    competitor_scenario: bool
    model_key: str
    model_identity_hash: str
    question_cluster_key: str

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.project_id, "Corpus Candidate Project ID"),
            (self.resolution_id, "Corpus Candidate Resolution ID"),
            (self.candidate_id, "Corpus Candidate ID"),
        ):
            _require_uuid(uuid_value, label)
        _require_hash(self.candidate_output_hash, "Corpus Candidate output hash")
        status = _as_enum(self.status, ReviewRunStatus, "Corpus Candidate status")
        object.__setattr__(self, "status", status)
        if status not in {
            ReviewRunStatus.PASSED,
            ReviewRunStatus.COMPLETED_WITH_WARNING,
        }:
            raise SyntheticLabContractError("Corpus can contain only passed or warning Candidates")
        warnings = tuple(self.warning_codes)
        object.__setattr__(self, "warning_codes", warnings)
        if len(warnings) != len(set(warnings)) or any(not code.strip() for code in warnings):
            raise SyntheticLabContractError(
                "Corpus Candidate warning codes must be unique non-empty values"
            )
        if status == ReviewRunStatus.PASSED and warnings:
            raise SyntheticLabContractError("passed Corpus Candidate cannot carry warnings")
        if status == ReviewRunStatus.COMPLETED_WITH_WARNING and not warnings:
            raise SyntheticLabContractError("warning Corpus Candidate requires warning codes")
        _require_channel(self.channel)
        if self.scenario_mode not in {"autonomous_scenario", "guided_scenario"}:
            raise SyntheticLabContractError("unsupported Corpus Candidate scenario mode")
        for text_value, label in (
            (self.model_key, "Corpus Candidate model key"),
            (self.question_cluster_key, "Corpus Candidate Question cluster"),
        ):
            _require_text(text_value, label)
        _require_hash(self.model_identity_hash, "Corpus Candidate model identity hash")


@dataclass(frozen=True, kw_only=True)
class CorpusVersion(SyntheticOnly):
    id: UUID
    project_id: UUID
    corpus_id: UUID
    version_number: int
    role: CorpusRole
    approved_fact_snapshot_id: UUID
    approved_fact_snapshot_hash: str
    profile_version_id: UUID
    profile_hash: str
    prompt_release_id: UUID
    prompt_release_hash: str
    candidates: tuple[CorpusCandidateEntry, ...]
    candidate_set_hash: str
    guard_evidence_hash: str
    content_hash: str
    passed_count: int = field(init=False)
    warning_count: int = field(init=False)
    warning_ratio: float = field(init=False)
    warning_by_code: Mapping[str, int] = field(init=False)
    warning_by_channel: Mapping[str, int] = field(init=False)
    warning_by_scenario_mode: Mapping[str, int] = field(init=False)
    warning_by_competitor: Mapping[str, int] = field(init=False)
    warning_by_model: Mapping[str, int] = field(init=False)
    warning_by_question_cluster: Mapping[str, int] = field(init=False)

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.id, "Corpus Version ID"),
            (self.project_id, "Corpus Project ID"),
            (self.corpus_id, "Corpus identity"),
            (self.approved_fact_snapshot_id, "Corpus approved Fact snapshot ID"),
            (self.profile_version_id, "Corpus Style Profile version ID"),
            (self.prompt_release_id, "Corpus Prompt Release ID"),
        ):
            _require_uuid(uuid_value, label)
        if self.version_number < 1:
            raise SyntheticLabContractError("Corpus version number must be positive")
        role = _as_enum(self.role, CorpusRole, "Corpus role")
        object.__setattr__(self, "role", role)
        for hash_value, label in (
            (self.approved_fact_snapshot_hash, "Corpus approved Fact snapshot hash"),
            (self.profile_hash, "Corpus Style Profile hash"),
            (self.prompt_release_hash, "Corpus Prompt Release hash"),
            (self.candidate_set_hash, "Corpus Candidate set hash"),
            (self.guard_evidence_hash, "Corpus finalization guard hash"),
            (self.content_hash, "Corpus content hash"),
        ):
            _require_hash(hash_value, label)
        candidates = tuple(self.candidates)
        object.__setattr__(self, "candidates", candidates)
        if role == CorpusRole.NO_CORPUS_BASELINE and candidates:
            raise SyntheticLabContractError("no-corpus baseline cannot contain Candidates")
        if role != CorpusRole.NO_CORPUS_BASELINE and not candidates:
            raise SyntheticLabContractError("approved/candidate Corpus cannot be empty")
        assert_same_project(self, *candidates)
        assert_synthetic_boundary(self, *candidates)
        if len({item.candidate_id for item in candidates}) != len(candidates):
            raise SyntheticLabContractError("Corpus Candidate IDs must be unique")
        if len({item.candidate_output_hash for item in candidates}) != len(candidates):
            raise SyntheticLabContractError("Corpus Candidate outputs must be unique")
        expected_set_hash = corpus_candidate_set_hash(candidates)
        if self.candidate_set_hash != expected_set_hash:
            raise SyntheticLabContractError("Corpus Candidate set does not match its hash")
        expected_content_hash = corpus_version_content_hash(
            role=role,
            approved_fact_snapshot_id=self.approved_fact_snapshot_id,
            approved_fact_snapshot_hash=self.approved_fact_snapshot_hash,
            profile_version_id=self.profile_version_id,
            profile_hash=self.profile_hash,
            prompt_release_id=self.prompt_release_id,
            prompt_release_hash=self.prompt_release_hash,
            candidate_set_hash=self.candidate_set_hash,
        )
        if self.content_hash != expected_content_hash:
            raise SyntheticLabContractError("Corpus content does not match its frozen hash")
        warning_items = tuple(
            item for item in candidates if item.status == ReviewRunStatus.COMPLETED_WITH_WARNING
        )
        warning_count = len(warning_items)
        object.__setattr__(self, "passed_count", len(candidates) - warning_count)
        object.__setattr__(self, "warning_count", warning_count)
        object.__setattr__(
            self,
            "warning_ratio",
            warning_count / len(candidates) if candidates else 0.0,
        )
        strata = {
            "warning_by_code": _counts(
                code for item in warning_items for code in item.warning_codes
            ),
            "warning_by_channel": _counts(item.channel for item in warning_items),
            "warning_by_scenario_mode": _counts(item.scenario_mode for item in warning_items),
            "warning_by_competitor": _counts(
                "competitor" if item.competitor_scenario else "non_competitor"
                for item in warning_items
            ),
            "warning_by_model": _counts(item.model_key for item in warning_items),
            "warning_by_question_cluster": _counts(
                item.question_cluster_key for item in warning_items
            ),
        }
        for field_name, values in strata.items():
            object.__setattr__(self, field_name, MappingProxyType(values))


def candidate_entry_from_resolution(
    resolution: CandidateResolution,
    *,
    competitor_scenario: bool,
    model_key: str,
    model_identity_hash: str,
    question_cluster_key: str,
) -> CorpusCandidateEntry:
    if not resolution.offline_experiment_eligible:
        raise SyntheticLabContractError("failed Candidate cannot enter a Corpus")
    return CorpusCandidateEntry(
        project_id=resolution.project_id,
        resolution_id=resolution.id,
        candidate_id=resolution.candidate_id,
        candidate_output_hash=resolution.candidate_output_hash,
        status=resolution.status,
        warning_codes=resolution.warning_codes,
        channel=resolution.channel,
        scenario_mode=resolution.scenario_mode.value,
        competitor_scenario=competitor_scenario,
        model_key=model_key,
        model_identity_hash=model_identity_hash,
        question_cluster_key=question_cluster_key,
    )


def corpus_candidate_set_hash(candidates: tuple[CorpusCandidateEntry, ...]) -> str:
    return _canonical_hash(
        [
            {
                "candidate_id": str(item.candidate_id),
                "candidate_output_hash": item.candidate_output_hash,
                "status": item.status.value,
                "warning_codes": list(item.warning_codes),
                "channel": item.channel,
                "scenario_mode": item.scenario_mode,
                "competitor_scenario": item.competitor_scenario,
                "model_key": item.model_key,
                "model_identity_hash": item.model_identity_hash,
                "question_cluster_key": item.question_cluster_key,
            }
            for item in sorted(candidates, key=lambda value: str(value.candidate_id))
        ]
    )


def corpus_version_content_hash(
    *,
    role: CorpusRole,
    approved_fact_snapshot_id: UUID,
    approved_fact_snapshot_hash: str,
    profile_version_id: UUID,
    profile_hash: str,
    prompt_release_id: UUID,
    prompt_release_hash: str,
    candidate_set_hash: str,
) -> str:
    return _canonical_hash(
        {
            "role": role.value,
            "approved_fact_snapshot_id": str(approved_fact_snapshot_id),
            "approved_fact_snapshot_hash": approved_fact_snapshot_hash,
            "profile_version_id": str(profile_version_id),
            "profile_hash": profile_hash,
            "prompt_release_id": str(prompt_release_id),
            "prompt_release_hash": prompt_release_hash,
            "candidate_set_hash": candidate_set_hash,
        }
    )


def freeze_corpus_version(
    *,
    id: UUID,
    project_id: UUID,
    corpus_id: UUID,
    version_number: int,
    role: CorpusRole,
    approved_fact_snapshot_id: UUID,
    approved_fact_snapshot_hash: str,
    profile_version_id: UUID,
    profile_hash: str,
    prompt_release_id: UUID,
    prompt_release_hash: str,
    candidates: tuple[CorpusCandidateEntry, ...],
    guard: FinalizationGuard,
) -> CorpusVersion:
    assert_finalization_guard(
        project_id=project_id,
        resource_id=id,
        fact_snapshot_id=approved_fact_snapshot_id,
        fact_snapshot_hash=approved_fact_snapshot_hash,
        guard=guard,
    )
    candidate_set_hash = corpus_candidate_set_hash(candidates)
    content_hash = corpus_version_content_hash(
        role=role,
        approved_fact_snapshot_id=approved_fact_snapshot_id,
        approved_fact_snapshot_hash=approved_fact_snapshot_hash,
        profile_version_id=profile_version_id,
        profile_hash=profile_hash,
        prompt_release_id=prompt_release_id,
        prompt_release_hash=prompt_release_hash,
        candidate_set_hash=candidate_set_hash,
    )
    return CorpusVersion(
        id=id,
        project_id=project_id,
        corpus_id=corpus_id,
        version_number=version_number,
        role=role,
        approved_fact_snapshot_id=approved_fact_snapshot_id,
        approved_fact_snapshot_hash=approved_fact_snapshot_hash,
        profile_version_id=profile_version_id,
        profile_hash=profile_hash,
        prompt_release_id=prompt_release_id,
        prompt_release_hash=prompt_release_hash,
        candidates=candidates,
        candidate_set_hash=candidate_set_hash,
        guard_evidence_hash=guard.evidence_hash,
        content_hash=content_hash,
    )


def assert_finalization_guard(
    *,
    project_id: UUID,
    resource_id: UUID,
    fact_snapshot_id: UUID,
    fact_snapshot_hash: str,
    guard: FinalizationGuard,
) -> None:
    assert_synthetic_boundary(guard)
    if guard.cancelled:
        raise SyntheticLabContractError("cancelled synthetic work cannot finalize")
    if not guard.facts_current_approved:
        raise SyntheticLabContractError("retired Fact prevents synthetic finalization")
    if (
        guard.project_id != project_id
        or guard.resource_id != resource_id
        or guard.fact_snapshot_id != fact_snapshot_id
        or guard.fact_snapshot_hash != fact_snapshot_hash
    ):
        raise SyntheticLabScopeError("finalization guard does not match frozen scope/Fact")
    if (
        guard.held_lease_id != guard.expected_lease_id
        or guard.held_fencing_token != guard.expected_fencing_token
    ):
        raise SyntheticLabContractError(
            "lost lease or stale fencing token prevents synthetic finalization"
        )


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


__all__ = [
    "CorpusCandidateEntry",
    "CorpusRole",
    "CorpusVersion",
    "FinalizationGuard",
    "assert_finalization_guard",
    "candidate_entry_from_resolution",
    "corpus_candidate_set_hash",
    "corpus_version_content_hash",
    "freeze_corpus_version",
]
