"""Shared value objects and warning summaries for Synthetic Lab API reads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from geo_core.synthetic_lab.corpus import CorpusVersion
from geo_core.synthetic_lab.offline_results import ArmMetricSummary
from geo_core.synthetic_lab.ports import SyntheticJob


@dataclass(frozen=True)
class SyntheticApiPage:
    items: tuple[object, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class SyntheticAggregateView:
    payload: object
    state_version: int


@dataclass(frozen=True)
class StyleProfileAggregateView:
    payload: object
    state_version: int
    build_verification_status: str | None
    rebuild_required: bool


@dataclass(frozen=True)
class SyntheticJobView:
    job: SyntheticJob
    warning_summary: Mapping[str, object] | None


@dataclass(frozen=True)
class SyntheticReviewResultView:
    job_id: UUID
    task: object
    result: object


def _corpus_warning_summary(corpus: CorpusVersion) -> Mapping[str, object]:
    return {
        "warning_count": corpus.warning_count,
        "candidate_count": len(corpus.candidates),
        "warning_ratio": corpus.warning_ratio,
        "by_code": dict(corpus.warning_by_code),
        "by_channel": dict(corpus.warning_by_channel),
        "by_scenario_mode": dict(corpus.warning_by_scenario_mode),
        "by_competitor": dict(corpus.warning_by_competitor),
        "by_model": dict(corpus.warning_by_model),
        "by_question_cluster": dict(corpus.warning_by_question_cluster),
    }


def _offline_warning_summary(
    summaries: tuple[ArmMetricSummary, ...],
) -> Mapping[str, object]:
    candidate_count = sum(item.corpus_candidate_count for item in summaries)
    warning_count = sum(item.corpus_warning_count for item in summaries)
    return {
        "warning_count": warning_count,
        "candidate_count": candidate_count,
        "warning_ratio": warning_count / candidate_count if candidate_count else 0.0,
        "by_code": _merge_warning_counts(summaries, "warning_by_code"),
        "by_channel": _merge_warning_counts(summaries, "warning_by_channel"),
        "by_scenario_mode": _merge_warning_counts(summaries, "warning_by_scenario_mode"),
        "by_competitor": _merge_warning_counts(summaries, "warning_by_competitor"),
        "by_model": _merge_warning_counts(summaries, "warning_by_model"),
        "by_question_cluster": _merge_warning_counts(
            summaries,
            "warning_by_question_cluster",
        ),
    }


def _merge_warning_counts(
    summaries: tuple[ArmMetricSummary, ...],
    field_name: str,
) -> dict[str, int]:
    merged: dict[str, int] = {}
    for summary in summaries:
        values = getattr(summary, field_name)
        if not isinstance(values, Mapping):
            raise ValueError("Offline Experiment warning summary shape changed")
        for key, value in values.items():
            if not isinstance(key, str) or not isinstance(value, int):
                raise ValueError("Offline Experiment warning summary value changed")
            merged[key] = merged.get(key, 0) + value
    return merged


for _view_type in (
    SyntheticApiPage,
    SyntheticAggregateView,
    StyleProfileAggregateView,
    SyntheticJobView,
    SyntheticReviewResultView,
):
    _view_type.__module__ = "geo_core.synthetic_lab.postgres_api_reads"


__all__ = [
    "StyleProfileAggregateView",
    "SyntheticAggregateView",
    "SyntheticApiPage",
    "SyntheticJobView",
    "SyntheticReviewResultView",
]
