from __future__ import annotations

import csv
import hashlib
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from io import StringIO
from typing import Any, Mapping

import httpx
from uuid import uuid5, NAMESPACE_URL

from geo_core.audit import build_audit_event, hash_payload
from geo_core.models import (
    AuditEvent,
    CitationGraphResult,
    GoogleSpikeGateResult,
    RawEvidenceRecord,
    ReportExport,
    ScoreContribution,
    VisibilityScoreSnapshot,
)


SCORE_RATE_DENOMINATORS: dict[str, dict[str, str]] = {
    "trigger_rate": {
        "label": "Trigger rate",
        "numerator": "surface_triggered evidence records",
        "denominator": "all attempted evidence records in this report window",
        "formula": "surface_triggered_records / attempted_records",
        "note": "Measures how often the AI surface produced a surfaced answer event.",
    },
    "mention_rate": {
        "label": "Mention rate",
        "numerator": "brand_mentioned answer analyses",
        "denominator": "surface_triggered evidence records, not all attempted records",
        "formula": "brand_mentioned_records / surface_triggered_records",
        "note": "Measures brand visibility after an AI answer is surfaced.",
    },
    "recommendation_rate": {
        "label": "Recommendation rate",
        "numerator": "brand_recommended answer analyses",
        "denominator": "surface_triggered evidence records, not all attempted records",
        "formula": "brand_recommended_records / surface_triggered_records",
        "note": "Measures explicit recommendation share after an AI answer is surfaced.",
    },
}


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geo", kind, *(str(part) for part in parts)))))


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
        google_spike_gate: GoogleSpikeGateResult | Mapping[str, object] | None = None,
        score_input_policy: Mapping[str, object] | None = None,
        fidelity_records: tuple[RawEvidenceRecord, ...] | None = None,
        audit_events: tuple[AuditEvent | Mapping[str, object], ...] = (),
    ) -> EvidenceReport:
        if not records:
            raise ValueError("Evidence report requires at least one raw evidence record")
        window_start = min(record.answer_run.collected_at for record in records)
        window_end = max(record.answer_run.collected_at for record in records)
        answer_run_ids = tuple(record.answer_run.id for record in records)
        method_disclosure = build_report_methodology_disclosure(
            rows=_methodology_rows_from_records(records),
            fidelity_rows=_methodology_rows_from_records(fidelity_records or records),
            platform_weights_snapshot=platform_weights_snapshot,
            google_spike_gate=google_spike_gate,
            score_input_policy=score_input_policy,
            audit_events=audit_events,
        )
        methodology = {
            "market_code": market_code,
            "report_type": report_type,
            "prompt_version": prompt_version,
            "scoring_formula_version": snapshot.formula_version,
            "sample_size": len(records),
            "platform_weights_snapshot": platform_weights_snapshot,
            "google_coverage": method_disclosure["google_coverage"],
            "access_methods": sorted({record.answer_run.access_method for record in records}),
            "method_disclosure": method_disclosure,
        }
        methodology_hash = hash_payload(methodology)
        report_id = _stable_id("report-export", project_id, report_version, methodology_hash)
        markdown_url = f"s3://geo-reports/{project_id}/{report_version}.md"
        pdf_url = f"s3://geo-reports/{project_id}/{report_version}.pdf"
        csv_url = f"s3://geo-reports/{project_id}/{report_version}.csv"
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
            method_disclosure=method_disclosure,
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
        pdf_content = render_markdown_pdf(markdown, title="GEO Evidence Report")
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
            reason="Production evidence report export snapshot",
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
        "# GEO Evidence Report",
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
        "### Method Disclosure",
        "",
        *render_methodology_disclosure_lines(
            methodology.get("method_disclosure") if isinstance(methodology.get("method_disclosure"), dict) else {}
        ),
        "",
        "### Audit Summary",
        "",
        *render_audit_summary_lines(
            dict(methodology.get("method_disclosure") or {}).get("audit_summary")
            if isinstance(methodology.get("method_disclosure"), dict)
            else {}
        ),
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


def _methodology_rows_from_records(records: tuple[RawEvidenceRecord, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "id": record.answer_run.id,
            "prompt_question_id": record.answer_run.prompt_question_id,
            "platform": record.answer_run.platform,
            "surface": record.answer_run.surface,
            "access_method": record.answer_run.access_method,
            "city": record.answer_run.city,
            "answer_present": record.answer_run.answer_present,
            "surface_triggered": record.answer_run.surface_triggered,
            "screenshot_count": sum(1 for asset in record.evidence_assets if asset.asset_type == "screenshot"),
            "html_snapshot_count": sum(1 for asset in record.evidence_assets if asset.asset_type == "html_snapshot"),
        }
        for record in records
    )


def methodology_rows_from_runtime_answer_runs(answer_runs: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "id": str(row.get("id") or ""),
            "prompt_question_id": str(row.get("prompt_question_id") or ""),
            "platform": str(row.get("platform") or ""),
            "surface": str(row.get("surface") or ""),
            "access_method": str(row.get("access_method") or "unknown"),
            "city": str(row.get("city") or ""),
            "answer_present": bool(row.get("answer_present")) if row.get("answer_present") is not None else None,
            "surface_triggered": bool(row.get("surface_triggered")) if row.get("surface_triggered") is not None else None,
            "screenshot_count": int(row.get("screenshot_count") or 0),
            "html_snapshot_count": int(row.get("html_snapshot_count") or 0),
        }
        for row in answer_runs
    )


def build_score_rate_methodology(rows: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    attempted_records = len(rows)
    surface_triggered_records = sum(1 for row in rows if bool(row.get("surface_triggered")))
    return {
        "definitions": {name: dict(definition) for name, definition in SCORE_RATE_DENOMINATORS.items()},
        "evidence_denominators": {
            "attempted_records": attempted_records,
            "surface_triggered_records": surface_triggered_records,
        },
        "evidence_trigger_rate": round(surface_triggered_records / attempted_records, 4)
        if attempted_records
        else 0.0,
    }


def _gate_payload(gate: GoogleSpikeGateResult | Mapping[str, object] | None, rows: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    google_rows = [row for row in rows if row.get("platform") == "google"]
    if gate is None:
        observed = bool(google_rows)
        return {
            "gate_status": "observed_without_gate" if observed else "not_run",
            "planned_runs": 0,
            "completed_runs": len(google_rows),
            "google_aio_completed_runs": sum(1 for row in google_rows if row.get("surface") == "google_aio"),
            "success_rate": 0.0,
            "trigger_rate": round(
                sum(1 for row in google_rows if row.get("surface_triggered")) / len(google_rows), 4
            )
            if google_rows
            else 0.0,
            "best_backend_id": None,
            "limited_coverage": True,
            "failure_summary": {},
            "recommendation": (
                "Do not use Google records in the main scoring denominator until a stored Google AIO / AI Mode "
                "spike gate reaches the pass threshold."
            ),
        }
    raw = asdict(gate) if is_dataclass(gate) else dict(gate)
    return {
        "gate_status": str(raw.get("gate_status") or "unknown"),
        "planned_runs": int(raw.get("planned_runs") or 0),
        "completed_runs": int(raw.get("completed_runs") or 0),
        "google_aio_completed_runs": int(raw.get("google_aio_completed_runs") or 0),
        "success_rate": float(raw.get("success_rate") or 0.0),
        "trigger_rate": float(raw.get("trigger_rate") or 0.0),
        "best_backend_id": raw.get("best_backend_id"),
        "limited_coverage": bool(raw.get("limited_coverage", True)),
        "failure_summary": dict(raw.get("failure_summary") or {}),
        "recommendation": str(raw.get("recommendation") or "No Google spike recommendation recorded"),
    }


def build_api_browser_fidelity_payload(rows: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    official_rows = [row for row in rows if row.get("access_method") == "official_api"]
    browser_rows = [row for row in rows if row.get("access_method") == "browser"]
    official_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    browser_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in official_rows:
        official_by_key[(str(row.get("prompt_question_id") or ""), str(row.get("city") or ""))].append(row)
    for row in browser_rows:
        browser_by_key[(str(row.get("prompt_question_id") or ""), str(row.get("city") or ""))].append(row)
    overlap_keys = sorted(set(official_by_key) & set(browser_by_key))
    mismatch_count = 0
    for key in overlap_keys:
        official_answer_present = any(bool(row.get("answer_present")) for row in official_by_key[key])
        browser_answer_present = any(bool(row.get("answer_present")) for row in browser_by_key[key])
        official_triggered = any(bool(row.get("surface_triggered")) for row in official_by_key[key])
        browser_triggered = any(bool(row.get("surface_triggered")) for row in browser_by_key[key])
        if (official_answer_present, official_triggered) != (browser_answer_present, browser_triggered):
            mismatch_count += 1
    if not official_rows or not browser_rows:
        status = "not_run"
        summary = "API-vs-browser fidelity check not run for this artifact."
    elif not overlap_keys:
        status = "no_overlap"
        summary = "Official API and browser records exist, but no prompt/city overlap was available for comparison."
    else:
        status = "sampled"
        summary = "Official API and browser records were compared on overlapping prompt/city pairs."
    return {
        "status": status,
        "official_api_records": len(official_rows),
        "browser_records": len(browser_rows),
        "comparable_prompt_city_pairs": len(overlap_keys),
        "mismatch_count": mismatch_count,
        "difference_rate": round(mismatch_count / len(overlap_keys), 4) if overlap_keys else None,
        "summary": summary,
    }


def _event_payload(event: AuditEvent | Mapping[str, object]) -> dict[str, Any]:
    return asdict(event) if is_dataclass(event) else dict(event)


def build_report_audit_summary(events: tuple[AuditEvent | Mapping[str, object], ...]) -> dict[str, Any]:
    payloads = tuple(_event_payload(event) for event in events)
    if not payloads:
        return {
            "audit_event_count": 0,
            "event_type_distribution": {},
            "target_type_distribution": {},
            "method_version_distribution": {},
            "actor_type_distribution": {},
            "input_ref_keys": [],
            "output_ref_keys": [],
            "first_event_at": "",
            "last_event_at": "",
            "event_ids": [],
            "summary": "No upstream audit events were attached to this report export.",
        }

    def text_value(payload: dict[str, Any], key: str, default: str = "unknown") -> str:
        value = payload.get(key)
        return str(value) if value not in (None, "") else default

    created_values = sorted(
        str(payload.get("created_at"))
        for payload in payloads
        if payload.get("created_at") not in (None, "")
    )
    input_ref_keys = sorted(
        {
            str(key)
            for payload in payloads
            for key in (payload.get("input_refs") if isinstance(payload.get("input_refs"), dict) else {}).keys()
        }
    )
    output_ref_keys = sorted(
        {
            str(key)
            for payload in payloads
            for key in (payload.get("output_refs") if isinstance(payload.get("output_refs"), dict) else {}).keys()
        }
    )
    def distribution(key: str) -> dict[str, int]:
        return dict(sorted(Counter(text_value(payload, key) for payload in payloads).items()))

    return {
        "audit_event_count": len(payloads),
        "event_type_distribution": distribution("event_type"),
        "target_type_distribution": distribution("target_type"),
        "method_version_distribution": distribution("method_version"),
        "actor_type_distribution": distribution("actor_type"),
        "input_ref_keys": input_ref_keys,
        "output_ref_keys": output_ref_keys,
        "first_event_at": created_values[0] if created_values else "",
        "last_event_at": created_values[-1] if created_values else "",
        "event_ids": [str(payload.get("id")) for payload in payloads[:20] if payload.get("id")],
        "summary": f"{len(payloads)} upstream audit events attached to this report export.",
    }


def build_report_methodology_disclosure(
    *,
    rows: tuple[dict[str, Any], ...],
    fidelity_rows: tuple[dict[str, Any], ...] | None = None,
    platform_weights_snapshot: dict[str, float],
    google_spike_gate: GoogleSpikeGateResult | Mapping[str, object] | None = None,
    score_input_policy: Mapping[str, object] | None = None,
    audit_events: tuple[AuditEvent | Mapping[str, object], ...] = (),
) -> dict[str, Any]:
    access_distribution = dict(sorted(Counter(str(row.get("access_method") or "unknown") for row in rows).items()))
    platform_distribution = dict(sorted(Counter(str(row.get("platform") or "unknown") for row in rows).items()))
    gate_payload = _gate_payload(google_spike_gate, rows)
    score_policy = dict(score_input_policy or {})
    fidelity_payload = build_api_browser_fidelity_payload(fidelity_rows or rows)
    score_policy_allows_google = bool(score_policy.get("google_main_scoring_allowed", False))
    google_coverage = (
        "main_scoring_allowed"
        if gate_payload["gate_status"] == "pass" and not gate_payload["limited_coverage"]
        and score_policy_allows_google
        else "limited_coverage_appendix_only"
    )
    return {
        "google_coverage": google_coverage,
        "google_spike_gate": gate_payload,
        "api_browser_fidelity": fidelity_payload,
        "score_rate_denominators": build_score_rate_methodology(rows),
        "access_method_distribution": access_distribution,
        "platform_distribution": platform_distribution,
        "platform_weights_snapshot": dict(sorted(platform_weights_snapshot.items())),
        "score_input_policy": score_policy,
        "audit_summary": build_report_audit_summary(audit_events),
        "evidence_asset_coverage": {
            "screenshot_records": sum(1 for row in rows if int(row.get("screenshot_count") or 0) > 0),
            "html_snapshot_records": sum(1 for row in rows if int(row.get("html_snapshot_count") or 0) > 0),
        },
    }


def render_methodology_disclosure_lines(disclosure: Mapping[str, Any]) -> list[str]:
    gate = dict(disclosure.get("google_spike_gate") or {})
    fidelity = dict(disclosure.get("api_browser_fidelity") or {})
    score_rates = dict(disclosure.get("score_rate_denominators") or {})
    rate_definitions = dict(score_rates.get("definitions") or {})
    rate_denominators = dict(score_rates.get("evidence_denominators") or {})
    assets = dict(disclosure.get("evidence_asset_coverage") or {})
    access_distribution = dict(disclosure.get("access_method_distribution") or {})
    platform_distribution = dict(disclosure.get("platform_distribution") or {})
    score_input_policy = dict(disclosure.get("score_input_policy") or {})
    return [
        f"- Google spike gate: {gate.get('gate_status', 'unknown')}",
        f"- Google limited coverage: {'yes' if gate.get('limited_coverage', True) else 'no'}",
        f"- Google AIO completed runs: {gate.get('google_aio_completed_runs', 0)} / planned {gate.get('planned_runs', 0)}",
        f"- Google trigger rate: {gate.get('trigger_rate', 0.0)}",
        f"- Google recommendation: {gate.get('recommendation', 'No recommendation recorded')}",
        f"- Main scoring Google allowed: {score_input_policy.get('google_main_scoring_allowed', False)}",
        f"- Main scoring records: {score_input_policy.get('score_input_record_count', 'n/a')}",
        f"- Excluded Google records from main scoring: {score_input_policy.get('excluded_google_record_count', 0)}",
        f"- API-vs-browser fidelity: {fidelity.get('status', 'unknown')}",
        f"- Official API records: {fidelity.get('official_api_records', 0)}",
        f"- Browser records: {fidelity.get('browser_records', 0)}",
        f"- Comparable prompt/city pairs: {fidelity.get('comparable_prompt_city_pairs', 0)}",
        f"- API/browser difference rate: {fidelity.get('difference_rate') if fidelity.get('difference_rate') is not None else 'n/a'}",
        f"- Trigger rate denominator: {dict(rate_definitions.get('trigger_rate') or {}).get('denominator', SCORE_RATE_DENOMINATORS['trigger_rate']['denominator'])}",
        f"- Mention rate denominator: {dict(rate_definitions.get('mention_rate') or {}).get('denominator', SCORE_RATE_DENOMINATORS['mention_rate']['denominator'])}",
        f"- Recommendation rate denominator: {dict(rate_definitions.get('recommendation_rate') or {}).get('denominator', SCORE_RATE_DENOMINATORS['recommendation_rate']['denominator'])}",
        f"- Report evidence attempted records: {rate_denominators.get('attempted_records', 0)}",
        f"- Report evidence surface-triggered records: {rate_denominators.get('surface_triggered_records', 0)}",
        f"- Report evidence trigger rate: {score_rates.get('evidence_trigger_rate', 0.0)}",
        f"- Access method distribution: {access_distribution}",
        f"- Platform distribution: {platform_distribution}",
        f"- Screenshot records: {assets.get('screenshot_records', 0)}",
        f"- HTML snapshot records: {assets.get('html_snapshot_records', 0)}",
    ]


def render_audit_summary_lines(summary_value: object) -> list[str]:
    summary = dict(summary_value) if isinstance(summary_value, Mapping) else {}
    event_types = dict(summary.get("event_type_distribution") or {})
    target_types = dict(summary.get("target_type_distribution") or {})
    method_versions = dict(summary.get("method_version_distribution") or {})
    actor_types = dict(summary.get("actor_type_distribution") or {})
    input_ref_keys = summary.get("input_ref_keys") if isinstance(summary.get("input_ref_keys"), list) else []
    output_ref_keys = summary.get("output_ref_keys") if isinstance(summary.get("output_ref_keys"), list) else []
    event_ids = summary.get("event_ids") if isinstance(summary.get("event_ids"), list) else []
    return [
        f"- Audit events attached: {summary.get('audit_event_count', 0)}",
        f"- Audit event types: {event_types}",
        f"- Audit target types: {target_types}",
        f"- Audit method versions: {method_versions}",
        f"- Audit actor types: {actor_types}",
        f"- Audit input ref keys: {input_ref_keys}",
        f"- Audit output ref keys: {output_ref_keys}",
        f"- Audit event window: {summary.get('first_event_at') or 'n/a'} to {summary.get('last_event_at') or 'n/a'}",
        f"- Audit event ids: {event_ids}",
        f"- Audit summary: {summary.get('summary', 'No audit summary recorded')}",
    ]


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


def render_markdown_pdf(markdown: str, *, title: str = "GEO Evidence Report") -> bytes:
    renderer_url = os.getenv("GEO_PDF_RENDERER_URL", "").strip().rstrip("/")
    production_required = (
        os.getenv("GEO_REPORT_PDF_RENDERER_REQUIRED", "false").strip().lower() in {"1", "true", "yes"}
        or os.getenv("GEO_DEPLOYMENT_ENVIRONMENT", "development").strip().lower() == "production"
    )
    if renderer_url:
        try:
            response = httpx.post(
                f"{renderer_url}/v1/render",
                json={"markdown": markdown, "title": title},
                timeout=120,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Playwright PDF renderer is unavailable: {exc}") from exc
        if not response.content.startswith(b"%PDF-"):
            raise RuntimeError("Playwright PDF renderer returned non-PDF content")
        return response.content
    if production_required:
        raise RuntimeError("GEO_PDF_RENDERER_URL is required for production PDF generation")
    return _render_minimal_test_pdf(markdown)


def _render_minimal_test_pdf(markdown: str) -> bytes:
    text_lines: list[str] = []
    for line in markdown.splitlines():
        text_lines.extend(_wrap_pdf_line(line))
    if not text_lines:
        text_lines = ["GEO Evidence Report"]

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
