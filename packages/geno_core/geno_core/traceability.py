from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from geno_core.models import (
    ActionRecommendation,
    AuditEvent,
    CitationGraphResult,
    ContentDraft,
    EvidenceLink,
    RawEvidenceRecord,
    ReportExport,
    ScoreContribution,
    TraceabilityBundle,
    VisibilityScoreSnapshot,
)


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
