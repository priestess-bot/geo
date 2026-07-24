"""Guarded finalization and summaries for paired offline experiments."""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from geo_core.synthetic_lab.corpus import FinalizationGuard, assert_finalization_guard
from geo_core.synthetic_lab.domain import (
    SyntheticLabContractError,
    SyntheticLabScopeError,
    SyntheticOnly,
    _as_enum,
    _canonical_hash,
    _require_hash,
    _require_uuid,
    assert_same_project,
    assert_synthetic_boundary,
)
from geo_core.synthetic_lab.offline_experiment import (
    ARM_ROLE,
    ExperimentArm,
    OfflineExperimentPlan,
    OfflineSlotResult,
    planned_experiment_slots,
)


_WARNING_MAPPING_FIELDS = (
    "warning_by_code",
    "warning_by_channel",
    "warning_by_scenario_mode",
    "warning_by_competitor",
    "warning_by_model",
    "warning_by_question_cluster",
)


@dataclass(frozen=True, kw_only=True)
class ArmMetricSummary(SyntheticOnly):
    project_id: UUID
    arm: ExperimentArm
    corpus_version_id: UUID
    corpus_hash: str
    valid_slot_count: int
    invalid_slot_count: int
    overall_metric: float
    corpus_candidate_count: int
    corpus_passed_count: int
    corpus_warning_count: int
    corpus_warning_ratio: float
    warning_by_code: Mapping[str, int]
    warning_by_channel: Mapping[str, int]
    warning_by_scenario_mode: Mapping[str, int]
    warning_by_competitor: Mapping[str, int]
    warning_by_model: Mapping[str, int]
    warning_by_question_cluster: Mapping[str, int]

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "arm summary Project ID")
        _require_uuid(self.corpus_version_id, "arm summary Corpus Version ID")
        _require_hash(self.corpus_hash, "arm summary Corpus hash")
        object.__setattr__(self, "arm", _as_enum(self.arm, ExperimentArm, "summary arm"))
        if self.valid_slot_count < 1 or self.invalid_slot_count < 0:
            raise SyntheticLabContractError("arm summary requires valid non-negative counts")
        if not math.isfinite(self.overall_metric):
            raise SyntheticLabContractError("arm summary metric must be finite")
        if (
            min(
                self.corpus_candidate_count,
                self.corpus_passed_count,
                self.corpus_warning_count,
            )
            < 0
        ):
            raise SyntheticLabContractError("arm Corpus counts cannot be negative")
        if self.corpus_passed_count + self.corpus_warning_count != self.corpus_candidate_count:
            raise SyntheticLabContractError("arm Corpus passed/warning counts do not add up")
        expected_ratio = (
            self.corpus_warning_count / self.corpus_candidate_count
            if self.corpus_candidate_count
            else 0.0
        )
        if self.corpus_warning_ratio != expected_ratio:
            raise SyntheticLabContractError("arm Corpus warning ratio does not match counts")
        for field_name in _WARNING_MAPPING_FIELDS:
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(dict(getattr(self, field_name))),
            )


@dataclass(frozen=True, kw_only=True)
class OfflineExperimentResult(SyntheticOnly):
    id: UUID
    project_id: UUID
    experiment_id: UUID
    experiment_input_hash: str
    slot_membership_hash: str
    guard_evidence_hash: str
    planned_pair_count: int
    valid_pair_count: int
    invalid_pair_count: int
    completion_ratio: float
    arm_summaries: tuple[ArmMetricSummary, ...]
    result_hash: str

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.id, "Offline Experiment Result ID"),
            (self.project_id, "Offline Experiment Result Project ID"),
            (self.experiment_id, "Offline Experiment Result Experiment ID"),
        ):
            _require_uuid(uuid_value, label)
        for hash_value, label in (
            (self.experiment_input_hash, "result Experiment input hash"),
            (self.slot_membership_hash, "result slot membership hash"),
            (self.guard_evidence_hash, "result guard evidence hash"),
            (self.result_hash, "Offline Experiment result hash"),
        ):
            _require_hash(hash_value, label)
        summaries = tuple(self.arm_summaries)
        object.__setattr__(self, "arm_summaries", summaries)
        if len(summaries) != 3 or {item.arm for item in summaries} != set(ExperimentArm):
            raise SyntheticLabContractError("result requires exactly three arm summaries")
        assert_same_project(self, *summaries)
        assert_synthetic_boundary(self, *summaries)
        if (
            self.planned_pair_count < 1
            or min(
                self.valid_pair_count,
                self.invalid_pair_count,
            )
            < 0
        ):
            raise SyntheticLabContractError("result pair counts must be valid non-negative values")
        if self.valid_pair_count + self.invalid_pair_count != self.planned_pair_count:
            raise SyntheticLabContractError("result pair counts do not add up")
        if self.completion_ratio != self.valid_pair_count / self.planned_pair_count:
            raise SyntheticLabContractError("result completion ratio does not match pair counts")
        expected_hash = offline_experiment_result_hash(
            experiment_input_hash=self.experiment_input_hash,
            slot_membership_hash=self.slot_membership_hash,
            planned_pair_count=self.planned_pair_count,
            valid_pair_count=self.valid_pair_count,
            invalid_pair_count=self.invalid_pair_count,
            completion_ratio=self.completion_ratio,
            arm_summaries=summaries,
        )
        if self.result_hash != expected_hash:
            raise SyntheticLabContractError(
                "Offline Experiment result does not match its deterministic hash"
            )


def finalize_offline_experiment(
    *,
    result_id: UUID,
    plan: OfflineExperimentPlan,
    slot_results: tuple[OfflineSlotResult, ...],
    guard: FinalizationGuard,
) -> OfflineExperimentResult:
    assert_finalization_guard(
        project_id=plan.project_id,
        resource_id=plan.id,
        fact_snapshot_id=plan.approved_fact_snapshot_id,
        fact_snapshot_hash=plan.approved_fact_snapshot_hash,
        guard=guard,
    )
    slots = planned_experiment_slots(plan)
    expected = {slot.slot_id: slot for slot in slots}
    if len(slot_results) != len(expected) or len({item.slot_id for item in slot_results}) != len(
        slot_results
    ):
        raise SyntheticLabContractError(
            "Offline Experiment requires exactly one result for every planned slot"
        )
    assert_same_project(plan, *slot_results)
    assert_synthetic_boundary(plan, *slot_results)
    for result in slot_results:
        slot = expected.get(result.slot_id)
        if slot is None or (
            result.experiment_id != plan.id
            or result.pair_id != slot.pair_id
            or result.arm != slot.arm
            or result.input_hash != slot.input_hash
        ):
            raise SyntheticLabScopeError("slot result does not match the frozen Experiment plan")
    by_pair: dict[str, list[OfflineSlotResult]] = {}
    for result in slot_results:
        by_pair.setdefault(result.pair_id, []).append(result)
    for pair_results in by_pair.values():
        if len(pair_results) != 3 or {item.arm for item in pair_results} != set(ExperimentArm):
            raise SyntheticLabContractError("each paired slot requires all three arms")
        if len({item.valid for item in pair_results}) != 1:
            raise SyntheticLabContractError("paired slot arms cannot mix valid and invalid results")
    valid_pairs = sum(all(item.valid for item in values) for values in by_pair.values())
    planned_pairs = len(by_pair)
    completion_ratio = valid_pairs / planned_pairs
    if completion_ratio < plan.minimum_valid_pair_ratio:
        raise SyntheticLabContractError("valid paired completion is below the frozen minimum ratio")
    summaries = tuple(_summarize_arm(plan, arm, slot_results) for arm in ExperimentArm)
    membership_hash = _canonical_hash(
        [
            {"slot_id": item.slot_id, "result_hash": item.result_hash}
            for item in sorted(slot_results, key=lambda value: value.slot_id)
        ]
    )
    invalid_pairs = planned_pairs - valid_pairs
    result_hash = offline_experiment_result_hash(
        experiment_input_hash=plan.input_hash,
        slot_membership_hash=membership_hash,
        planned_pair_count=planned_pairs,
        valid_pair_count=valid_pairs,
        invalid_pair_count=invalid_pairs,
        completion_ratio=completion_ratio,
        arm_summaries=summaries,
    )
    return OfflineExperimentResult(
        id=result_id,
        project_id=plan.project_id,
        experiment_id=plan.id,
        experiment_input_hash=plan.input_hash,
        slot_membership_hash=membership_hash,
        guard_evidence_hash=guard.evidence_hash,
        planned_pair_count=planned_pairs,
        valid_pair_count=valid_pairs,
        invalid_pair_count=invalid_pairs,
        completion_ratio=completion_ratio,
        arm_summaries=summaries,
        result_hash=result_hash,
    )


def offline_experiment_result_hash(**values: object) -> str:
    payload = dict(values)
    summaries = payload.get("arm_summaries")
    if isinstance(summaries, tuple):
        payload["arm_summaries"] = [_summary_value(item) for item in summaries]
    return _canonical_hash(payload)


def _summarize_arm(
    plan: OfflineExperimentPlan,
    arm: ExperimentArm,
    results: tuple[OfflineSlotResult, ...],
) -> ArmMetricSummary:
    corpus = next(item for item in plan.corpora if item.role == ARM_ROLE[arm])
    arm_results = tuple(item for item in results if item.arm == arm)
    metric_values = [
        item.metric_value for item in arm_results if item.valid and item.metric_value is not None
    ]
    return ArmMetricSummary(
        project_id=plan.project_id,
        arm=arm,
        corpus_version_id=corpus.id,
        corpus_hash=corpus.content_hash,
        valid_slot_count=len(metric_values),
        invalid_slot_count=len(arm_results) - len(metric_values),
        overall_metric=sum(metric_values) / len(metric_values),
        corpus_candidate_count=len(corpus.candidates),
        corpus_passed_count=corpus.passed_count,
        corpus_warning_count=corpus.warning_count,
        corpus_warning_ratio=corpus.warning_ratio,
        warning_by_code=corpus.warning_by_code,
        warning_by_channel=corpus.warning_by_channel,
        warning_by_scenario_mode=corpus.warning_by_scenario_mode,
        warning_by_competitor=corpus.warning_by_competitor,
        warning_by_model=corpus.warning_by_model,
        warning_by_question_cluster=corpus.warning_by_question_cluster,
    )


def _summary_value(summary: ArmMetricSummary) -> dict[str, object]:
    return {
        "arm": summary.arm.value,
        "corpus_version_id": str(summary.corpus_version_id),
        "corpus_hash": summary.corpus_hash,
        "valid_slot_count": summary.valid_slot_count,
        "invalid_slot_count": summary.invalid_slot_count,
        "overall_metric": summary.overall_metric,
        "corpus_candidate_count": summary.corpus_candidate_count,
        "corpus_passed_count": summary.corpus_passed_count,
        "corpus_warning_count": summary.corpus_warning_count,
        "corpus_warning_ratio": summary.corpus_warning_ratio,
        **{name: dict(getattr(summary, name)) for name in _WARNING_MAPPING_FIELDS},
    }


__all__ = [
    "ArmMetricSummary",
    "OfflineExperimentResult",
    "finalize_offline_experiment",
    "offline_experiment_result_hash",
]
