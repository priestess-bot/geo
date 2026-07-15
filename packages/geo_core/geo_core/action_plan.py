from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid5, NAMESPACE_URL

from geo_core.audit import build_audit_event
from geo_core.models import (
    ActionRecommendation,
    AuditEvent,
    CitationGraphResult,
    ScoreContribution,
    RetestComparison,
    RetestSchedule,
    VisibilityScoreSnapshot,
)

ACTION_TYPE_MISSING_WEAK_CITATION_SOURCE = "missing_or_weak_citation_source"
ACTION_TYPE_BRAND_NOT_MENTIONED = "brand_not_mentioned"
ACTION_TYPE_COMPETITOR_OUTRANKS_BRAND = "competitor_outranks_brand"
ACTION_PLAN_P0_ACTION_TYPES = (
    ACTION_TYPE_BRAND_NOT_MENTIONED,
    ACTION_TYPE_COMPETITOR_OUTRANKS_BRAND,
    ACTION_TYPE_MISSING_WEAK_CITATION_SOURCE,
)


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geo", kind, *(str(part) for part in parts)))))


def build_action_recommendations(
    *,
    project_id: str,
    graph: CitationGraphResult,
    snapshot: VisibilityScoreSnapshot,
    contributions: tuple[ScoreContribution, ...] = (),
    owner_id: str = "system",
    now: datetime | None = None,
) -> tuple[ActionRecommendation, ...]:
    created_at = now or datetime.now(UTC)
    actions: list[ActionRecommendation] = []
    contribution_ids = tuple(contribution.id for contribution in contributions) or (snapshot.id,)
    mention_contribution_ids = tuple(
        contribution.id for contribution in contributions if "mention" in contribution.component_name.lower()
    ) or contribution_ids
    recommendation_contribution_ids = tuple(
        contribution.id
        for contribution in contributions
        if "recommendation" in contribution.component_name.lower() or "position" in contribution.component_name.lower()
    ) or contribution_ids
    citation_contribution_ids = tuple(
        contribution.id for contribution in contributions if "citation" in contribution.component_name.lower()
    ) or contribution_ids
    for index, gap in enumerate(graph.source_gaps, start=1):
        priority = "high" if gap.expected_weight >= 0.9 else "medium"
        related_run_ids = tuple(
            answer_run_id
            for node in graph.nodes
            if node.source_type == gap.source_type
            for answer_run_id in node.answer_run_ids
        ) or tuple(snapshot.answer_run_ids)
        actions.append(
            ActionRecommendation(
                id=_stable_id("action", project_id, gap.source_type, gap.gap_type, index),
                project_id=project_id,
                title=f"Strengthen AU {gap.source_type} evidence",
                description=gap.recommendation,
                priority=priority,
                status="open",
                owner_id=owner_id,
                source_gap_type=gap.gap_type,
                evidence_answer_run_ids=related_run_ids,
                related_source_types=(gap.source_type,),
                next_check_date=created_at + timedelta(days=7),
                created_at=created_at,
                action_type=ACTION_TYPE_MISSING_WEAK_CITATION_SOURCE,
                customer_visible=False,
                score_contribution_ids=citation_contribution_ids,
                visibility_note="internal_only_until_reviewed",
            )
        )
    if snapshot.mention_rate < 0.5:
        actions.append(
            ActionRecommendation(
                id=_stable_id("action", project_id, "mention-rate", snapshot.id),
                project_id=project_id,
                title="Improve brand mention coverage",
                description="Create or update citation-ready pages for high-intent AU prompts where the brand is absent.",
                priority="high",
                status="open",
                owner_id=owner_id,
                source_gap_type="low_mention_rate",
                evidence_answer_run_ids=tuple(snapshot.answer_run_ids),
                related_source_types=(),
                next_check_date=created_at + timedelta(days=7),
                created_at=created_at,
                action_type=ACTION_TYPE_BRAND_NOT_MENTIONED,
                customer_visible=False,
                score_contribution_ids=mention_contribution_ids,
                visibility_note="internal_only_until_reviewed",
            )
        )
    competitor_pressure = max((benchmark.mention_rate for benchmark in graph.competitor_benchmarks), default=0.0)
    if snapshot.recommendation_rate < 0.35 or competitor_pressure > snapshot.mention_rate:
        actions.append(
            ActionRecommendation(
                id=_stable_id("action", project_id, "recommendation-rate", snapshot.id),
                project_id=project_id,
                title="Improve brand recommendation against competitor pressure",
                description="Add comparison, review, and proof content that gives AI systems clear reasons to recommend the brand.",
                priority="medium",
                status="open",
                owner_id=owner_id,
                source_gap_type="competitor_pressure",
                evidence_answer_run_ids=tuple(snapshot.answer_run_ids),
                related_source_types=("comparison_site", "review_site"),
                next_check_date=created_at + timedelta(days=14),
                created_at=created_at,
                action_type=ACTION_TYPE_COMPETITOR_OUTRANKS_BRAND,
                customer_visible=False,
                score_contribution_ids=recommendation_contribution_ids,
                visibility_note="internal_only_until_reviewed",
            )
        )
    return tuple(actions)


def build_retest_schedule(
    *,
    project_id: str,
    prompt_version: str,
    sample_size: int,
    answer_run_ids: tuple[str, ...],
    start_at: datetime | None = None,
    offsets_days: tuple[int, ...] = (0, 7, 14, 30),
) -> RetestSchedule:
    created_at = start_at or datetime.now(UTC)
    scheduled_dates = tuple(created_at + timedelta(days=offset) for offset in offsets_days)
    return RetestSchedule(
        id=_stable_id("retest-schedule", project_id, prompt_version, sample_size, ",".join(map(str, offsets_days))),
        project_id=project_id,
        prompt_version=prompt_version,
        sample_size=sample_size,
        offsets_days=offsets_days,
        scheduled_dates=scheduled_dates,
        answer_run_ids=answer_run_ids,
        created_at=created_at,
    )


def compare_retest_windows(
    *,
    project_id: str,
    baseline: VisibilityScoreSnapshot,
    retest: VisibilityScoreSnapshot,
    now: datetime | None = None,
) -> RetestComparison:
    created_at = now or datetime.now(UTC)
    delta = round(retest.final_score - baseline.final_score, 4)
    if delta > 1:
        trend = "improved"
    elif delta < -1:
        trend = "declined"
    else:
        trend = "flat"
    return RetestComparison(
        id=_stable_id("retest-comparison", project_id, baseline.id, retest.id),
        project_id=project_id,
        baseline_score=baseline.final_score,
        retest_score=retest.final_score,
        score_delta=delta,
        baseline_answer_run_ids=tuple(baseline.answer_run_ids),
        retest_answer_run_ids=tuple(retest.answer_run_ids),
        trend=trend,
        created_at=created_at,
    )


def build_action_plan_audit_event(
    *,
    project_id: str,
    actions: tuple[ActionRecommendation, ...],
    schedule: RetestSchedule,
) -> AuditEvent:
    return build_audit_event(
        event_type="action_plan_created",
        project_id=project_id,
        actor_type="system",
        actor_id="geo-core.action_plan",
        target_type="action_plan",
        target_id=schedule.id,
        before=None,
        after={
            "action_count": len(actions),
            "retest_schedule_id": schedule.id,
            "offsets_days": list(schedule.offsets_days),
        },
        input_refs={"answer_run_ids": list(schedule.answer_run_ids)},
        output_refs={
            "action_recommendation_ids": [action.id for action in actions],
            "retest_schedule_ids": [schedule.id],
        },
        method_version="action_plan_v1",
        reason="M6 source gap action plan and retest schedule",
    )


def build_retest_comparison_audit_event(
    *,
    project_id: str,
    comparison: RetestComparison,
) -> AuditEvent:
    return build_audit_event(
        event_type="retest_comparison_created",
        project_id=project_id,
        actor_type="system",
        actor_id="geo-core.action_plan",
        target_type="retest_comparison",
        target_id=comparison.id,
        before={"baseline_score": comparison.baseline_score},
        after={
            "retest_score": comparison.retest_score,
            "score_delta": comparison.score_delta,
            "trend": comparison.trend,
        },
        input_refs={
            "baseline_answer_run_ids": list(comparison.baseline_answer_run_ids),
            "retest_answer_run_ids": list(comparison.retest_answer_run_ids),
        },
        output_refs={"retest_comparison_ids": [comparison.id]},
        method_version="retest_comparison_v1",
        reason="M6 before/after retest comparison",
    )
