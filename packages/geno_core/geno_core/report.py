from __future__ import annotations

import csv
import hashlib
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
    pdf_content: bytes
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
        pdf_url = f"s3://geno-reports/{project_id}/{report_version}.pdf"
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
            pdf_url=pdf_url,
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
        pdf_content = render_markdown_pdf(markdown)
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
                "markdown_url": markdown_url,
                "pdf_url": pdf_url,
                "csv_url": csv_url,
                "markdown_hash": hash_payload(markdown),
                "pdf_hash": _content_sha256(pdf_content),
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
            pdf_content=pdf_content,
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


def _content_sha256(content: str | bytes) -> str:
    payload = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(payload).hexdigest()


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_pdf_line(value: str, *, width: int = 92) -> list[str]:
    if not value:
        return [""]
    words = value.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
            continue
        if len(current) + len(word) + 1 <= width:
            current = f"{current} {word}"
            continue
        lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def render_markdown_pdf(markdown: str) -> bytes:
    text_lines: list[str] = []
    for line in markdown.splitlines():
        text_lines.extend(_wrap_pdf_line(line))
    if not text_lines:
        text_lines = ["GENO AU Evidence Report"]

    max_lines_per_page = 52
    pages = [
        text_lines[index : index + max_lines_per_page]
        for index in range(0, len(text_lines), max_lines_per_page)
    ]

    objects: list[tuple[int, bytes]] = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
    ]
    page_object_ids: list[int] = []
    next_object_id = 4
    for page_lines in pages:
        page_id = next_object_id
        content_id = next_object_id + 1
        next_object_id += 2
        page_object_ids.append(page_id)

        commands = ["BT", "/F1 10 Tf", "50 760 Td", "13 TL"]
        for line in page_lines:
            commands.append(f"({_pdf_escape(line)}) Tj")
            commands.append("T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1", errors="replace")
        content_body = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )
        page_body = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("ascii")
        objects.extend([(page_id, page_body), (content_id, content_body)])

    kids = " ".join(f"{page_id} 0 R" for page_id in page_object_ids)
    objects.append(
        (
            2,
            f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_ids)} >>".encode("ascii"),
        )
    )
    objects.sort(key=lambda item: item[0])

    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets: list[int] = [0]
    for object_id, body in objects:
        offsets.append(len(pdf))
        pdf += f"{object_id} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n".encode("ascii")
    pdf += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return pdf
