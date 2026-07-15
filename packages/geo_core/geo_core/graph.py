from __future__ import annotations

from collections import defaultdict
from uuid import uuid5, NAMESPACE_URL

from geo_core.models import (
    AnswerAnalysis,
    CitationGraphResult,
    CompetitorBenchmark,
    CompetitorEntity,
    IndustryProfile,
    RawEvidenceRecord,
    SourceGap,
    SourceGraphEvidence,
    SourceGraphNode,
)


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geo", kind, *(str(part) for part in parts)))))


def _topic_from_domain(domain: str) -> str:
    if "review" in domain:
        return "reviews"
    if "compare" in domain:
        return "comparison"
    if "examplebrand" in domain:
        return "brand_owned"
    return "general"


def build_citation_graph(
    *,
    project_id: str,
    records: tuple[RawEvidenceRecord, ...],
    analyses: tuple[AnswerAnalysis, ...],
    competitors: tuple[CompetitorEntity, ...],
    industry_profile: IndustryProfile,
) -> CitationGraphResult:
    nodes_by_domain_type: dict[tuple[str, str], dict[str, object]] = {}
    evidence_links: list[SourceGraphEvidence] = []

    for record in records:
        for citation in record.citations:
            key = (citation.domain, citation.source_type or "unknown")
            if key not in nodes_by_domain_type:
                source_graph_id = _stable_id("source-graph", project_id, citation.domain, citation.source_type)
                nodes_by_domain_type[key] = {
                    "id": source_graph_id,
                    "project_id": project_id,
                    "source_url": citation.url,
                    "source_domain": citation.domain,
                    "source_type": citation.source_type or "unknown",
                    "topic": _topic_from_domain(citation.domain),
                    "answer_run_ids": set(),
                    "citation_count": 0,
                }
            node = nodes_by_domain_type[key]
            answer_run_ids = node["answer_run_ids"]
            assert isinstance(answer_run_ids, set)
            answer_run_ids.add(record.answer_run.id)
            node["citation_count"] = int(node["citation_count"]) + 1
            evidence_links.append(
                SourceGraphEvidence(
                    id=_stable_id("source-graph-evidence", node["id"], record.answer_run.id, citation.id),
                    source_graph_id=str(node["id"]),
                    answer_run_id=record.answer_run.id,
                    answer_citation_id=citation.id,
                    relation_type="cited_by_answer",
                )
            )

    nodes = tuple(
        SourceGraphNode(
            id=str(node["id"]),
            project_id=str(node["project_id"]),
            source_url=str(node["source_url"]),
            source_domain=str(node["source_domain"]),
            source_type=str(node["source_type"]),
            topic=str(node["topic"]),
            source_gap_type=None,
            answer_run_ids=tuple(sorted(node["answer_run_ids"])),  # type: ignore[arg-type]
            citation_count=int(node["citation_count"]),
        )
        for node in nodes_by_domain_type.values()
    )
    source_gaps = _build_source_gaps(nodes=nodes, industry_profile=industry_profile)
    competitor_benchmarks = _build_competitor_benchmarks(
        project_id=project_id,
        analyses=analyses,
        competitors=competitors,
        nodes=nodes,
    )
    return CitationGraphResult(
        nodes=nodes,
        evidence_links=tuple(evidence_links),
        source_gaps=source_gaps,
        competitor_benchmarks=competitor_benchmarks,
    )


def _build_source_gaps(
    *,
    nodes: tuple[SourceGraphNode, ...],
    industry_profile: IndustryProfile,
) -> tuple[SourceGap, ...]:
    observed_by_type: dict[str, int] = defaultdict(int)
    for node in nodes:
        observed_by_type[node.source_type] += node.citation_count
    gaps: list[SourceGap] = []
    for source_type, expected_weight in industry_profile.source_type_weights.items():
        observed_count = observed_by_type.get(source_type, 0)
        if expected_weight >= 0.75 and observed_count == 0:
            gaps.append(
                SourceGap(
                    source_type=source_type,
                    gap_type="missing_high_weight_source_type",
                    observed_count=observed_count,
                    expected_weight=expected_weight,
                    recommendation=f"Add or strengthen AU evidence for {source_type}",
                )
            )
        elif expected_weight >= 0.90 and observed_count < 2:
            gaps.append(
                SourceGap(
                    source_type=source_type,
                    gap_type="thin_high_weight_source_type",
                    observed_count=observed_count,
                    expected_weight=expected_weight,
                    recommendation=f"Increase citation-ready AU evidence for {source_type}",
                )
            )
    return tuple(gaps)


def _build_competitor_benchmarks(
    *,
    project_id: str,
    analyses: tuple[AnswerAnalysis, ...],
    competitors: tuple[CompetitorEntity, ...],
    nodes: tuple[SourceGraphNode, ...],
) -> tuple[CompetitorBenchmark, ...]:
    total = len(analyses) or 1
    node_answer_runs = {answer_run_id for node in nodes for answer_run_id in node.answer_run_ids}
    benchmarks: list[CompetitorBenchmark] = []
    for competitor in competitors:
        mentioned_analyses = [
            analysis
            for analysis in analyses
            if competitor.canonical_name in analysis.competitors_mentioned
        ]
        answer_run_ids = tuple(analysis.answer_run_id for analysis in mentioned_analyses)
        citation_overlap_count = sum(1 for answer_run_id in answer_run_ids if answer_run_id in node_answer_runs)
        local_average = (
            sum(analysis.local_relevance_score for analysis in mentioned_analyses) / len(mentioned_analyses)
            if mentioned_analyses
            else 0.0
        )
        benchmarks.append(
            CompetitorBenchmark(
                id=_stable_id("competitor-benchmark", project_id, competitor.canonical_name),
                project_id=project_id,
                competitor_name=competitor.canonical_name,
                mention_count=len(mentioned_analyses),
                mention_rate=round(len(mentioned_analyses) / total, 4),
                recommendation_count=0,
                citation_overlap_count=citation_overlap_count,
                local_relevance_average=round(local_average, 4),
                answer_run_ids=answer_run_ids,
            )
        )
    return tuple(benchmarks)
