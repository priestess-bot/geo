from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from geno_core.models import (
    ActionRecommendation,
    AuditEvent,
    AnswerAnalysis,
    CitationGraphResult,
    ContentDraft,
    EvidenceLink,
    RawEvidenceRecord,
    ReportExport,
    ScoreContribution,
    TraceabilityBundle,
    VisibilityScoreSnapshot,
)


@dataclass(frozen=True)
class ReportTraceabilitySmokeResult:
    status: str
    report_export_id: str
    score_snapshot_id: str
    checked_answer_run_ids: tuple[str, ...]
    checked_score_contribution_ids: tuple[str, ...]
    checked_analysis_ids: tuple[str, ...]
    checked_raw_answer_ids: tuple[str, ...]
    checked_evidence_asset_ids: tuple[str, ...]
    broken_links: tuple[str, ...]


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geno", kind, *(str(part) for part in parts)))))


def build_traceability_bundle(
    *,
    project_id: str,
    report_export: ReportExport,
    snapshot: VisibilityScoreSnapshot,
    contributions: tuple[ScoreContribution, ...],
    records: tuple[RawEvidenceRecord, ...],
    graph: CitationGraphResult,
    audit_events: tuple[AuditEvent, ...],
    actions: tuple[ActionRecommendation, ...] = (),
    content_drafts: tuple[ContentDraft, ...] = (),
) -> TraceabilityBundle:
    record_by_answer_run_id = {record.answer_run.id: record for record in records}
    answer_run_ids = tuple(report_export.answer_run_ids)
    raw_answer_ids = tuple(
        record_by_answer_run_id[answer_run_id].raw_answer.id
        for answer_run_id in answer_run_ids
        if answer_run_id in record_by_answer_run_id
    )
    answer_citation_ids = tuple(
        citation.id
        for answer_run_id in answer_run_ids
        if answer_run_id in record_by_answer_run_id
        for citation in record_by_answer_run_id[answer_run_id].citations
    )
    evidence_asset_ids = tuple(
        asset.id
        for answer_run_id in answer_run_ids
        if answer_run_id in record_by_answer_run_id
        for asset in record_by_answer_run_id[answer_run_id].evidence_assets
    )
    source_graph_ids = tuple(node.id for node in graph.nodes)
    source_gap_types = tuple(
        f"{gap.source_type}:{gap.gap_type}"
        for gap in graph.source_gaps
    )
    score_contribution_ids = tuple(contribution.id for contribution in contributions)
    action_ids = tuple(action.id for action in actions)
    content_draft_ids = tuple(draft.id for draft in content_drafts)
    audit_event_ids = tuple(event.id for event in audit_events)
    evidence_links = _build_evidence_links(
        project_id=project_id,
        report_export=report_export,
        snapshot=snapshot,
        contributions=contributions,
        graph=graph,
        actions=actions,
        content_drafts=content_drafts,
    )
    explanation_summary = (
        f"Report {report_export.report_version} traces {len(answer_run_ids)} answer runs, "
        f"{len(score_contribution_ids)} score contributions, {len(source_graph_ids)} source graph nodes, "
        f"{len(action_ids)} action recommendations, and {len(content_draft_ids)} content drafts."
    )
    return TraceabilityBundle(
        id=_stable_id("traceability-bundle", project_id, report_export.id, snapshot.id),
        project_id=project_id,
        subject_type="report_export",
        subject_id=report_export.id,
        report_export_ids=(report_export.id,),
        score_snapshot_ids=(snapshot.id,),
        score_contribution_ids=score_contribution_ids,
        answer_run_ids=answer_run_ids,
        raw_answer_ids=raw_answer_ids,
        answer_citation_ids=answer_citation_ids,
        evidence_asset_ids=evidence_asset_ids,
        source_graph_ids=source_graph_ids,
        source_gap_types=source_gap_types,
        action_recommendation_ids=action_ids,
        content_draft_ids=content_draft_ids,
        audit_event_ids=audit_event_ids,
        evidence_links=evidence_links,
        explanation_summary=explanation_summary,
    )


def verify_report_traceability_smoke(
    *,
    report_export: ReportExport,
    snapshot: VisibilityScoreSnapshot,
    contributions: tuple[ScoreContribution, ...],
    analyses: tuple[AnswerAnalysis, ...],
    records: tuple[RawEvidenceRecord, ...],
) -> ReportTraceabilitySmokeResult:
    broken_links: list[str] = []
    record_by_answer_run_id = {record.answer_run.id: record for record in records}
    analysis_by_answer_run_id = {analysis.answer_run_id: analysis for analysis in analyses}
    contribution_ids: list[str] = []
    analysis_ids: list[str] = []
    raw_answer_ids: list[str] = []
    evidence_asset_ids: list[str] = []

    if snapshot.id not in set(report_export.score_snapshot_ids):
        broken_links.append(
            f"report_export:{report_export.id}:score_snapshot_id_missing:{snapshot.id}"
        )
    for answer_run_id in report_export.answer_run_ids:
        record = record_by_answer_run_id.get(answer_run_id)
        if record is None:
            broken_links.append(f"report_export:{report_export.id}:answer_run_missing:{answer_run_id}")
            continue
        raw_answer_ids.append(record.raw_answer.id)
        if not record.raw_answer.answer_run_id == answer_run_id:
            broken_links.append(f"raw_answer:{record.raw_answer.id}:answer_run_mismatch:{answer_run_id}")
        if not record.evidence_assets:
            broken_links.append(f"answer_run:{answer_run_id}:evidence_asset_missing")
        for asset in record.evidence_assets:
            evidence_asset_ids.append(asset.id)
            if asset.answer_run_id != answer_run_id:
                broken_links.append(f"evidence_asset:{asset.id}:answer_run_mismatch:{answer_run_id}")
            if not asset.content_hash:
                broken_links.append(f"evidence_asset:{asset.id}:content_hash_missing")
        analysis = analysis_by_answer_run_id.get(answer_run_id)
        if analysis is None:
            broken_links.append(f"answer_run:{answer_run_id}:analysis_missing")
        else:
            analysis_ids.append(analysis.id)

    snapshot_answer_run_ids = set(snapshot.answer_run_ids)
    for contribution in contributions:
        contribution_ids.append(contribution.id)
        if contribution.score_snapshot_id != snapshot.id:
            broken_links.append(f"score_contribution:{contribution.id}:snapshot_mismatch:{snapshot.id}")
        for answer_run_id in contribution.evidence_answer_run_ids:
            if answer_run_id not in snapshot_answer_run_ids:
                broken_links.append(f"score_contribution:{contribution.id}:answer_run_not_in_snapshot:{answer_run_id}")
            if answer_run_id not in record_by_answer_run_id:
                broken_links.append(f"score_contribution:{contribution.id}:answer_run_missing:{answer_run_id}")
            if answer_run_id not in analysis_by_answer_run_id:
                broken_links.append(f"score_contribution:{contribution.id}:analysis_missing:{answer_run_id}")

    return ReportTraceabilitySmokeResult(
        status="pass" if not broken_links else "fail",
        report_export_id=report_export.id,
        score_snapshot_id=snapshot.id,
        checked_answer_run_ids=tuple(report_export.answer_run_ids),
        checked_score_contribution_ids=tuple(dict.fromkeys(contribution_ids)),
        checked_analysis_ids=tuple(dict.fromkeys(analysis_ids)),
        checked_raw_answer_ids=tuple(dict.fromkeys(raw_answer_ids)),
        checked_evidence_asset_ids=tuple(dict.fromkeys(evidence_asset_ids)),
        broken_links=tuple(broken_links),
    )


def _build_evidence_links(
    *,
    project_id: str,
    report_export: ReportExport,
    snapshot: VisibilityScoreSnapshot,
    contributions: tuple[ScoreContribution, ...],
    graph: CitationGraphResult,
    actions: tuple[ActionRecommendation, ...],
    content_drafts: tuple[ContentDraft, ...],
) -> tuple[EvidenceLink, ...]:
    links: list[EvidenceLink] = [
        EvidenceLink(
            id=_stable_id("evidence-link", report_export.id, snapshot.id, "contains_score_snapshot"),
            project_id=project_id,
            source_type="report_export",
            source_id=report_export.id,
            target_type="visibility_score_snapshot",
            target_id=snapshot.id,
            relation_type="contains_score_snapshot",
            answer_run_ids=tuple(report_export.answer_run_ids),
        )
    ]
    for contribution in contributions:
        links.append(
            EvidenceLink(
                id=_stable_id("evidence-link", snapshot.id, contribution.id, "explained_by"),
                project_id=project_id,
                source_type="visibility_score_snapshot",
                source_id=snapshot.id,
                target_type="score_contribution",
                target_id=contribution.id,
                relation_type="explained_by",
                answer_run_ids=tuple(contribution.evidence_answer_run_ids),
            )
        )
    for node in graph.nodes:
        links.append(
            EvidenceLink(
                id=_stable_id("evidence-link", report_export.id, node.id, "uses_source_graph"),
                project_id=project_id,
                source_type="report_export",
                source_id=report_export.id,
                target_type="source_graph_node",
                target_id=node.id,
                relation_type="uses_source_graph",
                answer_run_ids=node.answer_run_ids,
            )
        )
    for action in actions:
        links.append(
            EvidenceLink(
                id=_stable_id("evidence-link", report_export.id, action.id, "recommends_action"),
                project_id=project_id,
                source_type="report_export",
                source_id=report_export.id,
                target_type="action_recommendation",
                target_id=action.id,
                relation_type="recommends_action",
                answer_run_ids=action.evidence_answer_run_ids,
            )
        )
    for draft in content_drafts:
        links.append(
            EvidenceLink(
                id=_stable_id("evidence-link", draft.source_action_id or report_export.id, draft.id, "supports_draft"),
                project_id=project_id,
                source_type="action_recommendation" if draft.source_action_id else "report_export",
                source_id=draft.source_action_id or report_export.id,
                target_type="content_draft",
                target_id=draft.id,
                relation_type="supports_draft",
                answer_run_ids=draft.evidence_answer_run_ids,
            )
        )
    return tuple(links)
