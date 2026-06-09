from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from uuid import uuid5, NAMESPACE_URL

from geno_core.audit import build_audit_event, hash_payload
from geno_core.models import (
    AuditEvent,
    CitationGraphResult,
    RawEvidenceRecord,
    ReportExport,
    ScoreContribution,
    VisibilityScoreSnapshot,
)


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geno", kind, *(str(part) for part in parts)))))


@dataclass(frozen=True)
class EvidenceReport:
    report_export: ReportExport
    markdown: str
    csv_content: str
    audit_event: AuditEvent
    report_evidence_answer_run_ids: tuple[str, ...]


class MarkdownCsvReportExporter:
    exporter_id = "markdown_csv_report_exporter_v1"

    def export(
        self,
        *,
        project_id: str,
        market_code: str,
        report_version: str,
        report_type: str,
        prompt_version: str,
        snapshot: VisibilityScoreSnapshot,
        contributions: tuple[ScoreContribution, ...],
        records: tuple[RawEvidenceRecord, ...],
        graph: CitationGraphResult,
        platform_weights_snapshot: dict[str, float],
        exported_by: str = "system",
    ) -> EvidenceReport:
        if not records:
            raise ValueError("Evidence report requires at least one raw evidence record")
        window_start = min(record.answer_run.collected_at for record in records)
        window_end = max(record.answer_run.collected_at for record in records)
        answer_run_ids = tuple(record.answer_run.id for record in records)
        methodology = {
            "market_code": market_code,
            "report_type": report_type,
            "prompt_version": prompt_version,
            "scoring_formula_version": snapshot.formula_version,
            "sample_size": len(records),
            "platform_weights_snapshot": platform_weights_snapshot,
            "google_coverage": "limited unless spike gate passes on real collection",
            "access_methods": sorted({record.answer_run.access_method for record in records}),
        }
        methodology_hash = hash_payload(methodology)
        report_id = _stable_id("report-export", project_id, report_version, methodology_hash)
        markdown_url = f"s3://geno-reports/{project_id}/{report_version}.md"
        csv_url = f"s3://geno-reports/{project_id}/{report_version}.csv"
        report_export = ReportExport(
            id=report_id,
            project_id=project_id,
            market_code=market_code,
            report_version=report_version,
            report_type=report_type,
            score_snapshot_ids=(snapshot.id,),
            answer_run_ids=answer_run_ids,
            prompt_version=prompt_version,
            scoring_formula_version=snapshot.formula_version,
            platform_weights_snapshot=platform_weights_snapshot,
            sample_size=len(records),
            window_start=window_start,
            window_end=window_end,
            methodology_hash=methodology_hash,
            markdown_url=markdown_url,
            pdf_url=None,
            csv_url=csv_url,
            exported_by=exported_by,
            exported_at=datetime.now(UTC),
        )
        markdown = _build_markdown_report(
            report_export=report_export,
            snapshot=snapshot,
            contributions=contributions,
            graph=graph,
            methodology=methodology,
        )
        csv_content = _build_csv_evidence(records)
        audit_event = build_audit_event(
            event_type="report_export_created",
            project_id=project_id,
            actor_type="system",
            actor_id=self.exporter_id,
            target_type="report_export",
            target_id=report_id,
            before=None,
            after={
                "report_export_id": report_id,
                "report_version": report_version,
                "score_snapshot_ids": list(report_export.score_snapshot_ids),
                "answer_run_ids": list(answer_run_ids),
                "methodology_hash": methodology_hash,
                "markdown_hash": hash_payload(markdown),
                "csv_hash": hash_payload(csv_content),
            },
            input_refs={
                "score_snapshot_ids": list(report_export.score_snapshot_ids),
                "answer_run_ids": list(answer_run_ids),
            },
            output_refs={"report_export_ids": [report_id]},
            method_version=self.exporter_id,
            reason="M5 evidence report export snapshot",
        )
        return EvidenceReport(
            report_export=report_export,
            markdown=markdown,
            csv_content=csv_content,
            audit_event=audit_event,
            report_evidence_answer_run_ids=answer_run_ids,
        )


def _build_markdown_report(
    *,
    report_export: ReportExport,
    snapshot: VisibilityScoreSnapshot,
    contributions: tuple[ScoreContribution, ...],
    graph: CitationGraphResult,
    methodology: dict[str, object],
) -> str:
    lines = [
        "# GENO AU Evidence Report",
        "",
        f"- Report version: {report_export.report_version}",
        f"- Market: {report_export.market_code}",
        f"- Sample size: {report_export.sample_size}",
        f"- Formula: {snapshot.formula_version}",
        f"- Final score: {snapshot.final_score}",
        f"- Trigger rate: {snapshot.trigger_rate}",
        f"- Mention rate: {snapshot.mention_rate}",
        f"- Recommendation rate: {snapshot.recommendation_rate}",
        f"- Dispersion: {snapshot.dispersion}",
        "",
        "## Methodology",
        "",
        f"- Methodology hash: {report_export.methodology_hash}",
        f"- Access methods: {', '.join(methodology['access_methods'])}",
        f"- Google coverage: {methodology['google_coverage']}",
        "",
        "## Score Contributions",
        "",
    ]
    for contribution in contributions:
        lines.append(
            f"- {contribution.component_name}: score={contribution.component_score}, "
            f"weight={contribution.weight}, contribution={contribution.weighted_contribution}, "
            f"denominator={contribution.denominator}"
        )
    lines.extend(["", "## Citation Graph", ""])
    lines.append(f"- Source nodes: {len(graph.nodes)}")
    lines.append(f"- Source gaps: {len(graph.source_gaps)}")
    lines.append(f"- Competitor benchmarks: {len(graph.competitor_benchmarks)}")
    lines.extend(["", "## Source Gaps", ""])
    for gap in graph.source_gaps:
        lines.append(f"- {gap.source_type}: {gap.gap_type}; {gap.recommendation}")
    lines.extend(["", "## Competitor Benchmarks", ""])
    for benchmark in graph.competitor_benchmarks:
        lines.append(
            f"- {benchmark.competitor_name}: mention_rate={benchmark.mention_rate}, "
            f"citation_overlap={benchmark.citation_overlap_count}, "
            f"answer_runs={len(benchmark.answer_run_ids)}"
        )
    lines.extend(["", "## Traceability", ""])
    lines.append(
        "Every score and graph metric in this report can be traced through "
        "ReportExport -> VisibilityScoreSnapshot -> ScoreContribution -> "
        "AnswerAnalysis -> AnswerRun -> RawAnswer/AnswerCitation/EvidenceAsset."
    )
    return "\n".join(lines) + "\n"


def _build_csv_evidence(records: tuple[RawEvidenceRecord, ...]) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "answer_run_id",
            "prompt_question_id",
            "platform",
            "surface",
            "access_method",
            "city",
            "sample_index",
            "sample_size",
            "answer_present",
            "surface_triggered",
            "citation_count",
            "evidence_asset_count",
            "raw_payload_hash",
        ],
    )
    writer.writeheader()
    for record in records:
        writer.writerow(
            {
                "answer_run_id": record.answer_run.id,
                "prompt_question_id": record.answer_run.prompt_question_id,
                "platform": record.answer_run.platform,
                "surface": record.answer_run.surface,
                "access_method": record.answer_run.access_method,
                "city": record.answer_run.city,
                "sample_index": record.answer_run.sample_index,
                "sample_size": record.answer_run.sample_size,
                "answer_present": record.answer_run.answer_present,
                "surface_triggered": record.answer_run.surface_triggered,
                "citation_count": len(record.citations),
                "evidence_asset_count": len(record.evidence_assets),
                "raw_payload_hash": record.raw_answer.raw_payload_hash,
            }
        )
    return output.getvalue()
