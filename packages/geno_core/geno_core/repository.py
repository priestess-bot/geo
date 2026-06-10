from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from io import StringIO
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from geno_core.audit import build_audit_event
from geno_core.models import (
    ActionRecommendation,
    AnswerAnalysis,
    AuditEvent,
    CitationGraphResult,
    CollectionFailureRecord,
    CollectionRunSummary,
    ContentDraft,
    EntityAliasInput,
    IntegrationConnector,
    LocalizedKnowledgeFact,
    ManualDistributionRecord,
    ProjectBootstrap,
    RawEvidenceRecord,
    ReportExport,
    RetestComparison,
    RetestSchedule,
    RuntimeActionPlan,
    RuntimeActionPlanPage,
    RuntimeCitationGraph,
    RuntimeCitationGraphNode,
    RuntimeCitationGraphPage,
    RuntimeContentDraft,
    RuntimeContentEngine,
    RuntimeContentEnginePage,
    RuntimeCollectionRun,
    RuntimeCollectionRunPage,
    RuntimeEvidenceExport,
    RuntimeEvidencePage,
    RuntimeEvidenceRun,
    RuntimeEntityAlias,
    RuntimeEntityAliasCandidate,
    RuntimeEntityAliasCandidatePage,
    RuntimeEntityAliasPage,
    RuntimeHumanReviewInput,
    RuntimeHumanReviewPage,
    RuntimeHumanReviewRecord,
    RuntimeProjectBrandKit,
    RuntimeProjectBrandKitInput,
    RuntimeProject,
    RuntimeProjectPage,
    RuntimePromptImportInput,
    RuntimePromptImportResult,
    RuntimePromptPage,
    RuntimeReportArtifact,
    RuntimeReportExport,
    RuntimeReportExportPage,
    RuntimeSavedView,
    RuntimeSavedViewInput,
    RuntimeSavedViewPage,
    RuntimeScoreWeightConfig,
    RuntimeScoreWeightConfigInput,
    RuntimeScoreSnapshot,
    RuntimeScoreSnapshotPage,
    RuntimeScoreSnapshotRun,
    RuntimeTraceabilityDetail,
    ScoreContribution,
    TraceabilityBundle,
    VisibilityScoreSnapshot,
)
from geno_core.report import (
    build_report_methodology_disclosure,
    methodology_rows_from_runtime_answer_runs,
    render_markdown_pdf,
    render_methodology_disclosure_lines,
)
from geno_core.scoring import AU_VISIBILITY_V1, normalize_score_weights


class DbCursor(Protocol):
    def execute(self, sql: str, params: tuple[object, ...] = ()) -> Any: ...

    def fetchone(self) -> Any: ...

    def fetchall(self) -> Any: ...

    def __enter__(self) -> "DbCursor": ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...


class DbConnection(Protocol):
    def cursor(self) -> DbCursor: ...

    def commit(self) -> None: ...


def _json_compatible(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _json_payload(value: object) -> object:
    if is_dataclass(value):
        value = asdict(value)
    payload = _json_compatible(value)
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return payload
    return Jsonb(payload)


def _uuid_array(values: tuple[str, ...] | list[str]) -> list[object]:
    converted: list[object] = []
    for value in values:
        try:
            converted.append(UUID(str(value)))
        except (TypeError, ValueError):
            converted.append(str(value))
    return converted


def _uuid(value: str | None) -> object | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return str(value)


def _datetime(value: datetime | None) -> datetime | None:
    return value


def _llm_call_logs_from_analysis(analysis: AnswerAnalysis) -> tuple[dict[str, Any], ...]:
    comparison = analysis.parser_comparison or {}
    if not isinstance(comparison, dict):
        return ()
    candidates: list[object] = [comparison.get("llm_call_log")]
    secondary_result = comparison.get("secondary_result")
    if isinstance(secondary_result, dict):
        candidates.append(secondary_result.get("llm_call_log"))
    logs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for candidate in candidates:
        if is_dataclass(candidate):
            candidate = asdict(candidate)
        if not isinstance(candidate, dict):
            continue
        log_id = str(candidate.get("id") or "")
        if not log_id or log_id in seen_ids:
            continue
        seen_ids.add(log_id)
        logs.append(candidate)
    return tuple(logs)


def _row_dict(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return {key: _json_compatible(value) for key, value in row.items()}
    return {column: _json_compatible(row[index]) for index, column in enumerate(columns)}


def _rows_dict(rows: Any, columns: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(_row_dict(row, columns) for row in rows)


def _runtime_collection_run_row(row: dict[str, Any]) -> dict[str, Any]:
    int_fields = (
        "planned_runs",
        "attempted_runs",
        "success_count",
        "failure_count",
        "total_duration_ms",
        "average_duration_ms",
    )
    float_fields = (
        "success_rate",
        "trigger_rate",
        "answer_present_rate",
        "total_cost",
        "average_cost_per_run",
    )
    normalized = dict(row)
    for field in int_fields:
        normalized[field] = int(normalized.get(field) or 0)
    for field in float_fields:
        normalized[field] = float(normalized.get(field) or 0.0)
    return normalized


def _frozen_method_disclosure(report_export: dict[str, Any]) -> dict[str, Any] | None:
    disclosure = report_export.get("method_disclosure")
    return dict(disclosure) if isinstance(disclosure, dict) else None


RUNTIME_EVIDENCE_SORTS = {
    "collected_at_desc": "ar.collected_at DESC, ar.id DESC",
    "collected_at_asc": "ar.collected_at ASC, ar.id ASC",
    "cost_desc": "cc.total_cost DESC NULLS LAST, ar.collected_at DESC, ar.id DESC",
    "cost_asc": "cc.total_cost ASC NULLS LAST, ar.collected_at DESC, ar.id DESC",
    "citation_count_desc": "citation_counts.citation_count DESC NULLS LAST, ar.collected_at DESC, ar.id DESC",
    "audit_count_desc": "audit_counts.audit_event_count DESC NULLS LAST, ar.collected_at DESC, ar.id DESC",
}


def _runtime_evidence_sort(sort: str | None) -> tuple[str, str]:
    normalized = sort or "collected_at_desc"
    return normalized if normalized in RUNTIME_EVIDENCE_SORTS else "collected_at_desc", RUNTIME_EVIDENCE_SORTS.get(
        normalized, RUNTIME_EVIDENCE_SORTS["collected_at_desc"]
    )


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geno", kind, *(str(part) for part in parts)))))


def _alias_host(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.netloc or parsed.path).strip().lower().removeprefix("www.")


def _append_alias_candidate(
    candidates: list[dict[str, Any]],
    seen: set[str],
    *,
    entity: dict[str, Any],
    alias: str,
    alias_type: str,
    source: str,
    confidence: float,
) -> None:
    normalized_alias = alias.strip()
    key = normalized_alias.lower()
    if not normalized_alias or key in seen:
        return
    seen.add(key)
    candidates.append(
        {
            "id": _stable_id(
                "entity-alias-candidate",
                entity["entity_kind"],
                entity["id"],
                normalized_alias,
                alias_type,
                source,
            ),
            "entity_id": str(entity["id"]),
            "entity_kind": str(entity["entity_kind"]),
            "alias": normalized_alias,
            "alias_type": alias_type,
            "source": source,
            "confidence": confidence,
            "reason": f"candidate from {source}",
        }
    )


def _artifact_hash(content: str | bytes) -> str:
    payload = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(payload).hexdigest()


def _parse_prompt_import_csv(
    *,
    project_id: str,
    csv_content: str,
    max_rows: int,
) -> tuple[dict[str, Any], ...]:
    content = csv_content.strip()
    if not content:
        raise ValueError("csv_content is required")
    reader = csv.DictReader(StringIO(content))
    if not reader.fieldnames:
        raise ValueError("csv header is required")
    fieldnames = {field.strip() for field in reader.fieldnames if field}
    missing = sorted({"text", "intent_type"} - fieldnames)
    if missing:
        raise ValueError(f"csv missing required columns: {', '.join(missing)}")
    prompts: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    for row_index, row in enumerate(reader, start=1):
        if row_index > max_rows:
            raise ValueError(f"csv row count exceeds max_rows={max_rows}")
        prompt = {str(key).strip(): (value.strip() if isinstance(value, str) else value) for key, value in row.items() if key}
        text = str(prompt.get("text") or "").strip()
        intent_type = str(prompt.get("intent_type") or "").strip()
        if not text:
            raise ValueError(f"row {row_index} text is required")
        if not intent_type:
            raise ValueError(f"row {row_index} intent_type is required")
        normalized_key = text.lower()
        if normalized_key in seen_texts:
            raise ValueError(f"row {row_index} duplicates prompt text")
        seen_texts.add(normalized_key)
        prompt["project_id"] = project_id
        prompt["text"] = text
        prompt["intent_type"] = intent_type
        prompts.append(prompt)
    if not prompts:
        raise ValueError("csv must contain at least one prompt row")
    return tuple(prompts)


def _normalize_import_prompt(
    *,
    prompt: dict[str, Any],
    project: dict[str, Any],
    default_competitors: tuple[str, ...],
) -> dict[str, Any]:
    def text_value(key: str, default: str) -> str:
        value = str(prompt.get(key) or "").strip()
        return value or default

    def int_value(key: str, default: int) -> int:
        raw = str(prompt.get(key) or "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{key} must be an integer") from exc
        if value < 0:
            raise ValueError(f"{key} must be >= 0")
        return value

    def float_value(key: str, default: float) -> float:
        raw = str(prompt.get(key) or "").strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{key} must be a number") from exc
        if value < 0 or value > 1:
            raise ValueError(f"{key} must be between 0 and 1")
        return value

    competitors_raw = str(prompt.get("competitors") or "").strip()
    competitors = (
        tuple(item.strip() for item in competitors_raw.replace("|", ";").split(";") if item.strip())
        if competitors_raw
        else default_competitors
    )
    if len(competitors) > 5:
        raise ValueError("competitors must contain at most 5 items")
    return {
        "project_id": str(project["id"]),
        "market_code": text_value("market_code", str(project["market_code"])),
        "industry_code": text_value("industry_code", str(project["industry_code"])),
        "text": str(prompt["text"]),
        "intent_type": str(prompt["intent_type"]),
        "city": text_value("city", "Australia"),
        "language": text_value("language", "en-AU"),
        "target_brand": text_value("target_brand", str(project["target_brand"])),
        "competitors": competitors,
        "priority": int_value("priority", 0),
        "intent_weight": float_value("intent_weight", 1.0),
        "prompt_version": text_value("prompt_version", str(project["prompt_version"])),
        "status": text_value("status", "active"),
    }


def _render_runtime_report_markdown(report: RuntimeReportExport) -> str:
    report_export = report.report_export
    snapshot = report.score_snapshots[0] if report.score_snapshots else {}
    graph = report.citation_graph
    method_disclosure = _frozen_method_disclosure(report_export) or build_report_methodology_disclosure(
        rows=methodology_rows_from_runtime_answer_runs(report.answer_runs),
        platform_weights_snapshot=dict(report_export.get("platform_weights_snapshot") or {}),
    )
    lines = [
        "# GENO AU Evidence Report",
        "",
        f"- Report version: {report_export['report_version']}",
        f"- Market: {report_export['market_code']}",
        f"- Sample size: {report_export['sample_size']}",
        f"- Prompt version: {report_export['prompt_version']}",
        f"- Formula: {report_export['scoring_formula_version']}",
        f"- Methodology hash: {report_export['methodology_hash']}",
        f"- Window: {report_export['window_start']} to {report_export['window_end']}",
        "",
        "## Score Snapshot",
        "",
        f"- Final score: {snapshot.get('final_score', 'n/a')}",
        f"- Trigger rate: {snapshot.get('trigger_rate', 'n/a')}",
        f"- Mention rate: {snapshot.get('mention_rate', 'n/a')}",
        f"- Recommendation rate: {snapshot.get('recommendation_rate', 'n/a')}",
        f"- Dispersion: {snapshot.get('dispersion', 'n/a')}",
        "",
        "## Method Disclosure",
        "",
        *render_methodology_disclosure_lines(method_disclosure),
        "",
        "## Evidence Appendix",
        "",
    ]
    for answer_run in report.answer_runs:
        lines.append(
            f"- {answer_run['platform']} / {answer_run['surface']} / {answer_run['city']}: "
            f"{answer_run.get('prompt_text') or answer_run['prompt_question_id']} "
            f"(answer_run_id={answer_run['id']})"
        )
    lines.extend(["", "## Citation Graph", ""])
    if graph:
        lines.append(f"- Source nodes: {len(graph.nodes)}")
        lines.append(f"- Evidence links: {len(graph.evidence_links)}")
        lines.append(f"- Source gaps: {len(graph.source_gaps)}")
        lines.append(f"- Competitor benchmarks: {len(graph.competitor_benchmarks)}")
        lines.extend(["", "### Source Gaps", ""])
        for gap in graph.source_gaps:
            lines.append(f"- {gap['source_type']}: {gap['gap_type']}; {gap['recommendation']}")
    else:
        lines.append("- No citation graph stored for this report.")
    lines.extend(["", "## Audit Summary", ""])
    for event in report.audit_events:
        lines.append(
            f"- {event['event_type']} target={event['target_type']} "
            f"method={event.get('method_version') or 'n/a'}"
        )
    lines.extend(["", "## Traceability", ""])
    lines.append(
        "This artifact is regenerated from frozen runtime data: "
        "ReportExport -> VisibilityScoreSnapshot -> ReportEvidence/AnswerRun -> CitationGraph -> AuditEvent."
    )
    return "\n".join(lines) + "\n"


def _render_white_label_report_markdown(
    report: RuntimeReportExport,
    *,
    client_name: str,
    prepared_by: str,
    logo_url: str | None = None,
    primary_color: str | None = None,
    secondary_color: str | None = None,
    footer_text: str | None = None,
) -> str:
    report_export = report.report_export
    snapshot = report.score_snapshots[0] if report.score_snapshots else {}
    graph = report.citation_graph
    method_disclosure = _frozen_method_disclosure(report_export) or build_report_methodology_disclosure(
        rows=methodology_rows_from_runtime_answer_runs(report.answer_runs),
        platform_weights_snapshot=dict(report_export.get("platform_weights_snapshot") or {}),
    )
    platform_values = sorted(
        {
            str(answer_run.get("platform"))
            for answer_run in report.answer_runs
            if answer_run.get("platform")
        }
    )
    city_values = sorted(
        {
            str(answer_run.get("city"))
            for answer_run in report.answer_runs
            if answer_run.get("city")
        }
    )
    lines = [
        f"# {client_name} GEO Evidence Report",
        "",
        f"Prepared by: {prepared_by}",
        f"Market: {report_export.get('market_code', 'unknown')}",
        f"Report version: {report_export.get('report_version', 'unknown')}",
        f"Exported at: {report_export.get('exported_at', 'unknown')}",
        f"Methodology hash: {report_export.get('methodology_hash', 'unknown')}",
        f"Logo URL: {logo_url or 'not configured'}",
        f"Theme colors: {primary_color or 'default'} / {secondary_color or 'default'}",
        "",
        "## Executive Snapshot",
        "",
        f"- Final score: {snapshot.get('final_score', 'n/a')}",
        f"- Trigger rate: {snapshot.get('trigger_rate', 'n/a')}",
        f"- Mention rate: {snapshot.get('mention_rate', 'n/a')}",
        f"- Recommendation rate: {snapshot.get('recommendation_rate', 'n/a')}",
        f"- Evidence rows in this artifact: {len(report.answer_runs)}",
        f"- Platforms: {', '.join(platform_values) if platform_values else 'unknown'}",
        f"- Cities: {', '.join(city_values) if city_values else 'unknown'}",
        "",
        "## Client-Ready Method Notes",
        "",
        "- This white-label PDF is regenerated from the frozen runtime ReportExport snapshot.",
        "- Active appendix filters affect only this downloadable artifact, not stored score snapshots or evidence ids.",
        "- Every displayed score remains traceable to answer runs, citations, score contributions, and audit events.",
        f"- Google coverage: {method_disclosure['google_coverage']}",
        f"- API-vs-browser fidelity: {method_disclosure['api_browser_fidelity']['status']}",
        "",
        "## Evidence Highlights",
        "",
    ]
    for answer_run in report.answer_runs[:12]:
        lines.append(
            f"- {answer_run.get('platform', 'platform')} / {answer_run.get('city', 'city')}: "
            f"{answer_run.get('prompt_text') or answer_run.get('prompt_question_id') or answer_run.get('id')} "
            f"(run={answer_run.get('id')})"
        )
    if not report.answer_runs:
        lines.append("- No evidence rows match the selected filters.")
    lines.extend(["", "## Source & Audit Summary", ""])
    if graph:
        lines.append(f"- Source nodes: {len(graph.nodes)}")
        lines.append(f"- Evidence links: {len(graph.evidence_links)}")
        lines.append(f"- Source gaps: {len(graph.source_gaps)}")
        lines.append(f"- Competitor benchmarks: {len(graph.competitor_benchmarks)}")
    else:
        lines.append("- No citation graph stored for this report.")
    lines.append(f"- Report audit events: {len(report.audit_events)}")
    for event in report.audit_events[:5]:
        lines.append(
            f"- Audit: {event.get('event_type', 'audit_event')} "
            f"target={event.get('target_type', 'target')} "
            f"method={event.get('method_version') or 'n/a'}"
        )
    lines.extend(["", "## Footer", ""])
    if footer_text:
        lines.append(footer_text)
        lines.append("")
    lines.append(
        f"{prepared_by} white-label template `white_label_v1`; "
        f"ReportExport {report_export.get('id', 'unknown')} remains the source of truth."
    )
    return "\n".join(lines) + "\n"


def _render_runtime_report_csv(report: RuntimeReportExport) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "report_export_id",
            "report_version",
            "answer_run_id",
            "prompt_question_id",
            "prompt_text",
            "prompt_intent_type",
            "platform",
            "surface",
            "city",
            "access_method",
            "sample_index",
            "sample_size",
            "answer_present",
            "surface_triggered",
            "status",
            "total_cost",
            "citation_count",
            "audit_event_count",
        ],
    )
    writer.writeheader()
    for answer_run in report.answer_runs:
        writer.writerow(
            {
                "report_export_id": report.report_export["id"],
                "report_version": report.report_export["report_version"],
                "answer_run_id": answer_run["id"],
                "prompt_question_id": answer_run["prompt_question_id"],
                "prompt_text": answer_run.get("prompt_text") or "",
                "prompt_intent_type": answer_run.get("prompt_intent_type") or "",
                "platform": answer_run["platform"],
                "surface": answer_run["surface"],
                "city": answer_run["city"],
                "access_method": answer_run["access_method"],
                "sample_index": answer_run["sample_index"],
                "sample_size": answer_run["sample_size"],
                "answer_present": answer_run["answer_present"],
                "surface_triggered": answer_run["surface_triggered"],
                "status": answer_run["status"],
                "total_cost": answer_run.get("total_cost") or "",
                "citation_count": answer_run.get("citation_count") or "",
                "audit_event_count": answer_run.get("audit_event_count") or "",
            }
        )
    return output.getvalue()


def _filter_runtime_report_answer_runs(
    answer_runs: tuple[dict[str, Any], ...],
    *,
    platform: str | None = None,
    city: str | None = None,
    intent_type: str | None = None,
    status: str | None = None,
    sort: str | None = None,
) -> tuple[tuple[dict[str, Any], ...], str]:
    filtered = [
        answer_run
        for answer_run in answer_runs
        if (not platform or answer_run.get("platform") == platform)
        and (not city or answer_run.get("city") == city)
        and (not intent_type or answer_run.get("prompt_intent_type") == intent_type)
        and (not status or answer_run.get("status") == status)
    ]
    if sort is None:
        return tuple(filtered), "report_evidence_order"
    sort_key, _ = _runtime_evidence_sort(sort)

    def sort_value(answer_run: dict[str, Any]) -> tuple[object, ...]:
        if sort_key == "collected_at_asc":
            return (answer_run.get("collected_at") or "", answer_run.get("id") or "")
        if sort_key == "cost_desc":
            return (-(float(answer_run.get("total_cost") or 0)), answer_run.get("collected_at") or "", answer_run.get("id") or "")
        if sort_key == "cost_asc":
            return (float(answer_run.get("total_cost") or 0), answer_run.get("collected_at") or "", answer_run.get("id") or "")
        if sort_key == "citation_count_desc":
            return (-(int(answer_run.get("citation_count") or 0)), answer_run.get("collected_at") or "", answer_run.get("id") or "")
        if sort_key == "audit_count_desc":
            return (-(int(answer_run.get("audit_event_count") or 0)), answer_run.get("collected_at") or "", answer_run.get("id") or "")
        return (answer_run.get("collected_at") or "", answer_run.get("id") or "")

    if sort_key == "collected_at_desc":
        filtered.sort(key=lambda item: (item.get("collected_at") or "", item.get("id") or ""), reverse=True)
    else:
        filtered.sort(key=sort_value)
    return tuple(filtered), sort_key


def _render_runtime_evidence_csv(page: RuntimeEvidencePage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "answer_run_id",
            "project_id",
            "prompt_question_id",
            "prompt_text",
            "prompt_intent_type",
            "prompt_version",
            "platform",
            "surface",
            "access_method",
            "market_code",
            "city",
            "language",
            "device",
            "sample_index",
            "sample_size",
            "answer_present",
            "surface_triggered",
            "status",
            "collector_backend_id",
            "collector_version",
            "raw_payload_hash",
            "citation_count",
            "asset_count",
            "audit_event_count",
            "total_cost",
        ],
    )
    writer.writeheader()
    for record in page.records:
        answer_run = record.answer_run
        writer.writerow(
            {
                "answer_run_id": answer_run["id"],
                "project_id": answer_run.get("project_id") or "",
                "prompt_question_id": answer_run.get("prompt_question_id") or "",
                "prompt_text": answer_run.get("prompt_text") or "",
                "prompt_intent_type": answer_run.get("prompt_intent_type") or "",
                "prompt_version": answer_run.get("prompt_version") or "",
                "platform": answer_run.get("platform") or "",
                "surface": answer_run.get("surface") or "",
                "access_method": answer_run.get("access_method") or "",
                "market_code": answer_run.get("market_code") or "",
                "city": answer_run.get("city") or "",
                "language": answer_run.get("language") or "",
                "device": answer_run.get("device") or "",
                "sample_index": answer_run.get("sample_index") or "",
                "sample_size": answer_run.get("sample_size") or "",
                "answer_present": answer_run.get("answer_present"),
                "surface_triggered": answer_run.get("surface_triggered"),
                "status": answer_run.get("status") or "",
                "collector_backend_id": answer_run.get("collector_backend_id") or "",
                "collector_version": answer_run.get("collector_version") or "",
                "raw_payload_hash": (record.raw_answer or {}).get("raw_payload_hash", ""),
                "citation_count": len(record.citations),
                "asset_count": len(record.evidence_assets),
                "audit_event_count": len(record.audit_events),
                "total_cost": (record.collection_cost or {}).get("total_cost", ""),
            }
        )
    return output.getvalue()


ANSWER_RUN_COLUMNS = (
    "id",
    "project_id",
    "prompt_question_id",
    "platform",
    "surface",
    "access_method",
    "market_code",
    "city",
    "language",
    "device",
    "answer_present",
    "surface_triggered",
    "sample_index",
    "sample_size",
    "model_or_surface",
    "account_state",
    "collector_backend_id",
    "collector_version",
    "collected_at",
    "status",
)
ANSWER_RUN_READ_COLUMNS = ANSWER_RUN_COLUMNS + (
    "prompt_text",
    "prompt_intent_type",
    "prompt_priority",
    "prompt_version",
)
TENANT_COLUMNS = ("id", "name", "slug", "created_at")
PROJECT_COLUMNS = (
    "id",
    "tenant_id",
    "name",
    "market_code",
    "industry_code",
    "target_brand",
    "category",
    "prompt_version",
    "status",
    "created_at",
)
BRAND_ENTITY_COLUMNS = (
    "id",
    "project_id",
    "canonical_name",
    "official_domains",
    "parent_company",
    "product_lines",
    "status",
)
COMPETITOR_ENTITY_COLUMNS = (
    "id",
    "project_id",
    "canonical_name",
    "official_domains",
    "parent_company",
    "product_lines",
    "status",
)
ENTITY_ALIAS_COLUMNS = (
    "id",
    "entity_id",
    "entity_kind",
    "alias",
    "alias_type",
    "confidence",
    "confirmed_by",
    "created_at",
)
ENTITY_ALIAS_JOIN_COLUMNS = ENTITY_ALIAS_COLUMNS + (
    "project_id",
    "canonical_name",
    "official_domains",
    "parent_company",
    "product_lines",
    "status",
)
RAW_ANSWER_COLUMNS = ("id", "answer_run_id", "answer_text", "raw_payload", "raw_payload_hash", "created_at")
CITATION_COLUMNS = ("id", "answer_run_id", "url", "domain", "position", "source_type", "created_at")
ASSET_COLUMNS = ("id", "answer_run_id", "asset_type", "url", "content_hash", "created_at")
COLLECTOR_LOG_COLUMNS = (
    "id",
    "answer_run_id",
    "collector_backend_id",
    "event_type",
    "payload",
    "created_at",
)
COLLECTION_COST_COLUMNS = (
    "id",
    "answer_run_id",
    "project_id",
    "collector_backend_id",
    "llm_provider",
    "llm_tokens",
    "llm_cost",
    "proxy_or_vendor_cost",
    "compute_cost",
    "total_cost",
    "duration_ms",
    "created_at",
)
COLLECTION_RUN_SUMMARY_COLUMNS = (
    "id",
    "project_id",
    "run_type",
    "mode",
    "planned_runs",
    "attempted_runs",
    "success_count",
    "failure_count",
    "success_rate",
    "trigger_rate",
    "answer_present_rate",
    "total_cost",
    "average_cost_per_run",
    "total_duration_ms",
    "average_duration_ms",
    "collector_backend_ids",
    "platform_distribution",
    "city_distribution",
    "access_method_distribution",
    "failure_summary",
    "answer_run_ids",
    "started_at",
    "completed_at",
    "created_at",
)
VISIBILITY_SCORE_SNAPSHOT_COLUMNS = (
    "id",
    "project_id",
    "scope_type",
    "scope_value",
    "formula_version",
    "platform_weights_snapshot",
    "final_score",
    "trigger_rate",
    "mention_rate",
    "recommendation_rate",
    "answer_run_ids",
    "created_at",
    "dispersion",
    "component_weights_snapshot",
)
SCORE_CONTRIBUTION_COLUMNS = (
    "id",
    "score_snapshot_id",
    "component_name",
    "component_score",
    "weight",
    "weighted_contribution",
    "denominator",
    "evidence_answer_run_ids",
    "positive_evidence_summary",
    "negative_evidence_summary",
    "confidence_note",
    "created_at",
)
ANSWER_ANALYSIS_READ_COLUMNS = (
    "id",
    "answer_run_id",
    "parser_engine_id",
    "analysis_version",
    "payload",
    "confidence",
    "created_at",
)
SOURCE_GRAPH_COLUMNS = (
    "id",
    "project_id",
    "source_url",
    "source_domain",
    "source_type",
    "topic",
    "source_gap_type",
    "answer_run_ids",
    "citation_count",
    "created_at",
)
SOURCE_GRAPH_EVIDENCE_COLUMNS = (
    "id",
    "source_graph_id",
    "answer_run_id",
    "answer_citation_id",
    "relation_type",
    "created_at",
)
SOURCE_GAP_COLUMNS = (
    "id",
    "project_id",
    "source_type",
    "gap_type",
    "observed_count",
    "expected_weight",
    "recommendation",
    "created_at",
)
COMPETITOR_BENCHMARK_COLUMNS = (
    "id",
    "project_id",
    "competitor_name",
    "metric_scope",
    "payload",
    "answer_run_ids",
    "created_at",
)
REPORT_EXPORT_COLUMNS = (
    "id",
    "project_id",
    "market_code",
    "report_version",
    "report_type",
    "score_snapshot_ids",
    "answer_run_ids",
    "prompt_version",
    "scoring_formula_version",
    "platform_weights_snapshot",
    "method_disclosure",
    "sample_size",
    "window_start",
    "window_end",
    "methodology_hash",
    "markdown_url",
    "pdf_url",
    "csv_url",
    "exported_by",
    "exported_at",
)
ACTION_RECOMMENDATION_COLUMNS = (
    "id",
    "project_id",
    "title",
    "description",
    "priority",
    "status",
    "owner_id",
    "source_gap_type",
    "evidence_answer_run_ids",
    "related_source_types",
    "next_check_date",
    "created_at",
)
RETEST_SCHEDULE_COLUMNS = (
    "id",
    "project_id",
    "prompt_version",
    "sample_size",
    "offsets_days",
    "scheduled_dates",
    "answer_run_ids",
    "created_at",
)
RETEST_COMPARISON_COLUMNS = (
    "id",
    "project_id",
    "baseline_score",
    "retest_score",
    "score_delta",
    "baseline_answer_run_ids",
    "retest_answer_run_ids",
    "trend",
    "created_at",
)
LOCALIZED_KNOWLEDGE_FACT_COLUMNS = (
    "id",
    "project_id",
    "market_code",
    "fact_type",
    "subject",
    "predicate",
    "object_value",
    "city",
    "evidence_source_id",
    "confidence",
    "status",
    "valid_from",
    "valid_until",
)
CONTENT_DRAFT_COLUMNS = (
    "id",
    "project_id",
    "title",
    "content_type",
    "content_template_id",
    "target_question_ids",
    "target_city",
    "target_platform",
    "target_source_type",
    "used_knowledge_fact_ids",
    "source_gap_types",
    "source_action_id",
    "evidence_answer_run_ids",
    "draft_markdown",
    "review_status",
    "created_by",
    "created_at",
)
INTEGRATION_CONNECTOR_COLUMNS = (
    "id",
    "project_id",
    "provider",
    "connection_status",
    "capabilities",
    "auth_mode",
    "created_at",
)
MANUAL_DISTRIBUTION_RECORD_COLUMNS = (
    "id",
    "project_id",
    "content_draft_id",
    "platform",
    "target_url",
    "status",
    "submitted_at",
    "checked_at",
    "notes",
)
PROMPT_QUESTION_READ_COLUMNS = (
    "id",
    "project_id",
    "market_code",
    "industry_code",
    "text",
    "intent_type",
    "city",
    "language",
    "target_brand",
    "competitors",
    "priority",
    "intent_weight",
    "prompt_version",
    "status",
)
AUDIT_EVENT_COLUMNS = (
    "id",
    "event_type",
    "project_id",
    "actor_type",
    "actor_id",
    "target_type",
    "target_id",
    "before_hash",
    "after_hash",
    "input_refs",
    "output_refs",
    "method_version",
    "reason",
    "created_at",
)
EVIDENCE_LINK_COLUMNS = (
    "id",
    "project_id",
    "source_type",
    "source_id",
    "target_type",
    "target_id",
    "relation_type",
    "answer_run_ids",
)
TRACEABILITY_BUNDLE_COLUMNS = (
    "id",
    "project_id",
    "subject_type",
    "subject_id",
    "report_export_ids",
    "score_snapshot_ids",
    "score_contribution_ids",
    "answer_run_ids",
    "raw_answer_ids",
    "answer_citation_ids",
    "evidence_asset_ids",
    "source_graph_ids",
    "source_gap_types",
    "action_recommendation_ids",
    "content_draft_ids",
    "audit_event_ids",
    "explanation_summary",
)
RUNTIME_SAVED_VIEW_COLUMNS = (
    "id",
    "project_id",
    "name",
    "view_type",
    "filters",
    "sort",
    "query_path",
    "export_path",
    "created_by",
    "created_at",
    "updated_at",
)
PROJECT_BRAND_KIT_COLUMNS = (
    "id",
    "project_id",
    "client_name",
    "prepared_by",
    "logo_url",
    "primary_color",
    "secondary_color",
    "footer_text",
    "updated_by",
    "created_at",
    "updated_at",
)
SCORE_WEIGHT_CONFIG_COLUMNS = (
    "id",
    "project_id",
    "formula_version",
    "weights",
    "updated_by",
    "notes",
    "created_at",
    "updated_at",
)
HUMAN_REVIEW_COLUMNS = (
    "id",
    "project_id",
    "target_type",
    "target_id",
    "review_status",
    "decision",
    "reviewer_id",
    "notes",
    "payload",
    "created_at",
)


class PostgresEvidenceRepository:
    """DB-API style repository for the GENO runtime evidence chain."""

    def __init__(self, connection: DbConnection) -> None:
        self.connection = connection

    def list_runtime_projects(
        self,
        *,
        project_id: str | None = None,
        market_code: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeProjectPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("p.id = %s")
            params.append(_uuid(project_id))
        if market_code:
            filters.append("p.market_code = %s")
            params.append(market_code)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM projects p
                {where_clause}
                """,
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(f"p.{column}" for column in PROJECT_COLUMNS)}
                FROM projects p
                {where_clause}
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            projects = _rows_dict(cursor.fetchall(), PROJECT_COLUMNS)
            records = tuple(self._load_runtime_project(cursor=cursor, project=project) for project in projects)
        return RuntimeProjectPage(total_count=total_count, limit=limit, offset=offset, records=records)

    def _load_runtime_project(self, *, cursor: DbCursor, project: dict[str, Any]) -> RuntimeProject:
        cursor.execute(
            f"""
            SELECT {", ".join(TENANT_COLUMNS)}
            FROM tenants
            WHERE id = %s
            """,
            (_uuid(project["tenant_id"]),),
        )
        tenant = _row_dict(cursor.fetchone(), TENANT_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(BRAND_ENTITY_COLUMNS)}
            FROM brand_entities
            WHERE project_id = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (_uuid(project["id"]),),
        )
        brand_row = cursor.fetchone()
        cursor.execute(
            f"""
            SELECT {", ".join(COMPETITOR_ENTITY_COLUMNS)}
            FROM competitor_entities
            WHERE project_id = %s
            ORDER BY canonical_name ASC
            """,
            (_uuid(project["id"]),),
        )
        competitors = _rows_dict(cursor.fetchall(), COMPETITOR_ENTITY_COLUMNS)
        cursor.execute(
            """
            SELECT count(*)
            FROM prompt_questions
            WHERE project_id = %s
            """,
            (_uuid(project["id"]),),
        )
        prompt_count_row = cursor.fetchone()
        prompt_count = int(
            prompt_count_row[0] if not isinstance(prompt_count_row, dict) else prompt_count_row["count"]
        )
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            """,
            (_uuid(project["id"]), "project", str(project["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeProject(
            project=project,
            tenant=tenant,
            brand=_row_dict(brand_row, BRAND_ENTITY_COLUMNS) if brand_row else None,
            competitors=competitors,
            prompt_count=prompt_count,
            audit_events=audit_events,
        )

    def list_runtime_entity_aliases(
        self,
        *,
        project_id: str | None = None,
        entity_kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeEntityAliasPage:
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("entity.project_id = %s")
            params.append(_uuid(project_id))
        if entity_kind:
            filters.append("ea.entity_kind = %s")
            params.append(entity_kind)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM entity_aliases ea
                JOIN (
                  SELECT id, project_id, 'brand' AS entity_kind FROM brand_entities
                  UNION ALL
                  SELECT id, project_id, 'competitor' AS entity_kind FROM competitor_entities
                ) entity ON entity.id = ea.entity_id AND entity.entity_kind = ea.entity_kind
                {where_clause}
                """,
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT
                  {", ".join(f"ea.{column}" for column in ENTITY_ALIAS_COLUMNS)},
                  entity.project_id,
                  entity.canonical_name,
                  entity.official_domains,
                  entity.parent_company,
                  entity.product_lines,
                  entity.status
                FROM entity_aliases ea
                JOIN (
                  SELECT id, project_id, 'brand' AS entity_kind, canonical_name, official_domains, parent_company, product_lines, status
                  FROM brand_entities
                  UNION ALL
                  SELECT id, project_id, 'competitor' AS entity_kind, canonical_name, official_domains, parent_company, product_lines, status
                  FROM competitor_entities
                ) entity ON entity.id = ea.entity_id AND entity.entity_kind = ea.entity_kind
                {where_clause}
                ORDER BY ea.created_at DESC, ea.id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = _rows_dict(cursor.fetchall(), ENTITY_ALIAS_JOIN_COLUMNS)
            records = tuple(self._load_runtime_entity_alias(cursor=cursor, row=row) for row in rows)
        return RuntimeEntityAliasPage(total_count=total_count, limit=limit, offset=offset, records=records)

    def get_confirmed_entity_alias_terms(self, project_id: str) -> dict[str, tuple[str, ...]]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ea.entity_id, ea.alias
                FROM entity_aliases ea
                JOIN (
                  SELECT id, project_id, 'brand' AS entity_kind FROM brand_entities
                  UNION ALL
                  SELECT id, project_id, 'competitor' AS entity_kind FROM competitor_entities
                ) entity ON entity.id = ea.entity_id AND entity.entity_kind = ea.entity_kind
                WHERE entity.project_id = %s
                ORDER BY ea.created_at ASC, ea.alias ASC
                """,
                (_uuid(project_id),),
            )
            rows = _rows_dict(cursor.fetchall(), ("entity_id", "alias"))
        aliases: dict[str, list[str]] = {}
        for row in rows:
            entity_id = str(row["entity_id"])
            alias = str(row["alias"]).strip()
            if not alias:
                continue
            aliases.setdefault(entity_id, [])
            if alias.lower() not in {item.lower() for item in aliases[entity_id]}:
                aliases[entity_id].append(alias)
        return {entity_id: tuple(items) for entity_id, items in aliases.items()}

    def list_runtime_entity_alias_candidates(
        self,
        *,
        project_id: str,
        entity_kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeEntityAliasCandidatePage:
        filters: list[str] = ["entity.project_id = %s"]
        params: list[object] = [_uuid(project_id)]
        if entity_kind:
            filters.append("entity.entity_kind = %s")
            params.append(entity_kind)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                  entity.id,
                  entity.project_id,
                  entity.entity_kind,
                  entity.canonical_name,
                  entity.official_domains,
                  entity.parent_company,
                  entity.product_lines,
                  entity.status
                FROM (
                  SELECT id, project_id, 'brand' AS entity_kind, canonical_name, official_domains, parent_company, product_lines, status
                  FROM brand_entities
                  UNION ALL
                  SELECT id, project_id, 'competitor' AS entity_kind, canonical_name, official_domains, parent_company, product_lines, status
                  FROM competitor_entities
                ) entity
                WHERE {" AND ".join(filters)}
                ORDER BY entity.entity_kind ASC, entity.canonical_name ASC
                """,
                tuple(params),
            )
            entities = _rows_dict(
                cursor.fetchall(),
                (
                    "id",
                    "project_id",
                    "entity_kind",
                    "canonical_name",
                    "official_domains",
                    "parent_company",
                    "product_lines",
                    "status",
                ),
            )
        confirmed_aliases = self.get_confirmed_entity_alias_terms(project_id)
        records: list[RuntimeEntityAliasCandidate] = []
        for entity in entities:
            entity_id = str(entity["id"])
            confirmed = confirmed_aliases.get(entity_id, ())
            seen = {str(entity["canonical_name"]).lower(), *(alias.lower() for alias in confirmed)}
            candidates: list[dict[str, Any]] = []
            _append_alias_candidate(
                candidates,
                seen,
                entity=entity,
                alias=f"{entity['canonical_name']} Australia",
                alias_type="alias",
                source="canonical_name_market",
                confidence=0.72,
            )
            for domain in entity.get("official_domains") or ():
                host = _alias_host(str(domain))
                _append_alias_candidate(
                    candidates,
                    seen,
                    entity=entity,
                    alias=host,
                    alias_type="domain",
                    source="official_domain",
                    confidence=0.9,
                )
            for product_line in entity.get("product_lines") or ():
                _append_alias_candidate(
                    candidates,
                    seen,
                    entity=entity,
                    alias=str(product_line),
                    alias_type="product",
                    source="product_line",
                    confidence=0.68,
                )
            if entity.get("parent_company"):
                _append_alias_candidate(
                    candidates,
                    seen,
                    entity=entity,
                    alias=str(entity["parent_company"]),
                    alias_type="parent_company",
                    source="parent_company",
                    confidence=0.74,
                )
            for candidate in candidates:
                records.append(
                    RuntimeEntityAliasCandidate(
                        candidate=candidate,
                        entity=entity,
                        confirmed_aliases=confirmed,
                    )
                )
        total_count = len(records)
        return RuntimeEntityAliasCandidatePage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=tuple(records[offset : offset + limit]),
        )

    def confirm_entity_alias(self, alias: EntityAliasInput) -> RuntimeEntityAlias:
        normalized_kind = alias.entity_kind.strip().lower()
        if normalized_kind not in {"brand", "competitor"}:
            raise ValueError("entity_kind must be brand or competitor")
        normalized_alias = alias.alias.strip()
        normalized_alias_type = alias.alias_type.strip().lower()
        if not normalized_alias:
            raise ValueError("alias is required")
        if not normalized_alias_type:
            raise ValueError("alias_type is required")
        confidence = max(0.0, min(1.0, float(alias.confidence)))
        table_name = "brand_entities" if normalized_kind == "brand" else "competitor_entities"
        alias_id = _stable_id("entity-alias", normalized_kind, alias.entity_id, normalized_alias, normalized_alias_type)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(BRAND_ENTITY_COLUMNS)}
                FROM {table_name}
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(alias.entity_id),),
            )
            entity = _row_dict(cursor.fetchone(), BRAND_ENTITY_COLUMNS)
            if not entity:
                raise ValueError("entity not found")
            cursor.execute(
                f"""
                SELECT {", ".join(ENTITY_ALIAS_COLUMNS)}
                FROM entity_aliases
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(alias_id),),
            )
            existing = cursor.fetchone()
            before = _row_dict(existing, ENTITY_ALIAS_COLUMNS) if existing else None
            after = {
                "id": alias_id,
                "entity_id": alias.entity_id,
                "entity_kind": normalized_kind,
                "alias": normalized_alias,
                "alias_type": normalized_alias_type,
                "confidence": confidence,
                "confirmed_by": alias.confirmed_by.strip() or "runtime-console",
                "notes": alias.notes,
            }
            cursor.execute(
                """
                INSERT INTO entity_aliases (
                  id, entity_id, entity_kind, alias, alias_type, confidence, confirmed_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  alias = EXCLUDED.alias,
                  alias_type = EXCLUDED.alias_type,
                  confidence = EXCLUDED.confidence,
                  confirmed_by = EXCLUDED.confirmed_by
                """,
                (
                    _uuid(alias_id),
                    _uuid(alias.entity_id),
                    normalized_kind,
                    normalized_alias,
                    normalized_alias_type,
                    confidence,
                    after["confirmed_by"],
                ),
            )
            audit_event = build_audit_event(
                event_type="entity_alias_confirmed",
                project_id=str(entity["project_id"]),
                actor_type="user",
                actor_id=str(after["confirmed_by"]),
                target_type="entity_alias",
                target_id=alias_id,
                before=before,
                after=after,
                input_refs={"entity_ids": [alias.entity_id]},
                output_refs={"entity_alias_ids": [alias_id]},
                method_version="entity_alias_confirm_v1",
                reason=alias.notes or "confirm entity alias for parser disambiguation",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT
                  {", ".join(f"ea.{column}" for column in ENTITY_ALIAS_COLUMNS)},
                  entity.project_id,
                  entity.canonical_name,
                  entity.official_domains,
                  entity.parent_company,
                  entity.product_lines,
                  entity.status
                FROM entity_aliases ea
                JOIN (
                  SELECT id, project_id, canonical_name, official_domains, parent_company, product_lines, status
                  FROM {table_name}
                ) entity ON entity.id = ea.entity_id
                WHERE ea.id = %s
                LIMIT 1
                """,
                (_uuid(alias_id),),
            )
            row = _row_dict(cursor.fetchone(), ENTITY_ALIAS_JOIN_COLUMNS)
            record = self._load_runtime_entity_alias(cursor=cursor, row=row)
        self.connection.commit()
        return record

    def _load_runtime_entity_alias(self, *, cursor: DbCursor, row: dict[str, Any]) -> RuntimeEntityAlias:
        entity_alias = {column: row[column] for column in ENTITY_ALIAS_COLUMNS if column in row}
        entity = {
            "id": row["entity_id"],
            "project_id": row["project_id"],
            "entity_kind": row["entity_kind"],
            "canonical_name": row["canonical_name"],
            "official_domains": row["official_domains"],
            "parent_company": row["parent_company"],
            "product_lines": row["product_lines"],
            "status": row["status"],
        }
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            """,
            (_uuid(entity["project_id"]), "entity_alias", str(entity_alias["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeEntityAlias(entity_alias=entity_alias, entity=entity, audit_events=audit_events)

    def list_runtime_prompts(
        self,
        *,
        project_id: str | None = None,
        market_code: str | None = None,
        intent_type: str | None = None,
        city: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> RuntimePromptPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if market_code:
            filters.append("market_code = %s")
            params.append(market_code)
        if intent_type:
            filters.append("intent_type = %s")
            params.append(intent_type)
        if city:
            filters.append("city = %s")
            params.append(city)
        if status:
            filters.append("status = %s")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM prompt_questions
                {where_clause}
                """,
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(PROMPT_QUESTION_READ_COLUMNS)}
                FROM prompt_questions
                {where_clause}
                ORDER BY priority ASC, id ASC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            records = _rows_dict(cursor.fetchall(), PROMPT_QUESTION_READ_COLUMNS)
        return RuntimePromptPage(total_count=total_count, limit=limit, offset=offset, records=records)

    def get_runtime_prompt(self, prompt_question_id: str) -> dict[str, Any] | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROMPT_QUESTION_READ_COLUMNS)}
                FROM prompt_questions
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(prompt_question_id),),
            )
            row = cursor.fetchone()
        return _row_dict(row, PROMPT_QUESTION_READ_COLUMNS) if row else None

    def import_runtime_prompts_csv(self, prompt_import: RuntimePromptImportInput) -> RuntimePromptImportResult:
        project_id = prompt_import.project_id.strip()
        imported_by = prompt_import.imported_by.strip() or "runtime-console"
        max_rows = max(1, min(prompt_import.max_rows, 200))
        if not project_id:
            raise ValueError("project_id is required")
        prompts = _parse_prompt_import_csv(
            project_id=project_id,
            csv_content=prompt_import.csv_content,
            max_rows=max_rows,
        )
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, market_code, industry_code, target_brand, prompt_version
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            project_row = cursor.fetchone()
            if not project_row:
                raise ValueError("project not found")
            project = _row_dict(project_row, ("id", "market_code", "industry_code", "target_brand", "prompt_version"))
            cursor.execute(
                """
                SELECT canonical_name
                FROM competitor_entities
                WHERE project_id = %s
                ORDER BY canonical_name ASC
                """,
                (_uuid(project_id),),
            )
            competitor_rows = _rows_dict(cursor.fetchall(), ("canonical_name",))
            default_competitors = tuple(str(row["canonical_name"]) for row in competitor_rows)
            normalized_prompts = tuple(
                _normalize_import_prompt(
                    prompt=prompt,
                    project=project,
                    default_competitors=default_competitors,
                )
                for prompt in prompts
            )
            before = {"project_id": project_id, "imported_prompt_count": 0}
            prompt_ids: list[str] = []
            for index, prompt in enumerate(normalized_prompts, start=1):
                prompt_id = _stable_id("runtime-prompt-import", project_id, prompt["prompt_version"], index, prompt["text"])
                prompt_ids.append(prompt_id)
                cursor.execute(
                    """
                    INSERT INTO prompt_questions (
                      id, project_id, market_code, industry_code, text, intent_type, city,
                      language, target_brand, competitors, priority, intent_weight,
                      prompt_version, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      text = EXCLUDED.text,
                      intent_type = EXCLUDED.intent_type,
                      city = EXCLUDED.city,
                      language = EXCLUDED.language,
                      target_brand = EXCLUDED.target_brand,
                      competitors = EXCLUDED.competitors,
                      priority = EXCLUDED.priority,
                      intent_weight = EXCLUDED.intent_weight,
                      prompt_version = EXCLUDED.prompt_version,
                      status = EXCLUDED.status
                    """,
                    (
                        _uuid(prompt_id),
                        _uuid(project_id),
                        prompt["market_code"],
                        prompt["industry_code"],
                        prompt["text"],
                        prompt["intent_type"],
                        prompt["city"],
                        prompt["language"],
                        prompt["target_brand"],
                        _json_payload(prompt["competitors"]),
                        prompt["priority"],
                        prompt["intent_weight"],
                        prompt["prompt_version"],
                        prompt["status"],
                    ),
                )
            after = {
                "project_id": project_id,
                "prompt_count": len(normalized_prompts),
                "prompt_ids": prompt_ids,
                "prompt_version": normalized_prompts[0]["prompt_version"] if normalized_prompts else project["prompt_version"],
            }
            audit_event = build_audit_event(
                event_type="runtime_prompts_imported",
                project_id=project_id,
                actor_type="user",
                actor_id=imported_by,
                target_type="prompt_import",
                target_id=_stable_id("prompt-import", project_id, imported_by, len(normalized_prompts)),
                before=before,
                after=after,
                input_refs={"csv_sha256": [_artifact_hash(prompt_import.csv_content)]},
                output_refs={"prompt_question_ids": prompt_ids},
                method_version="runtime_prompt_import_csv_v1",
                reason="import runtime prompts from csv",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            imported_rows: list[dict[str, Any]] = []
            for prompt_id in prompt_ids:
                cursor.execute(
                    f"""
                    SELECT {", ".join(PROMPT_QUESTION_READ_COLUMNS)}
                    FROM prompt_questions
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (_uuid(prompt_id),),
                )
                row = cursor.fetchone()
                if row:
                    imported_rows.append(_row_dict(row, PROMPT_QUESTION_READ_COLUMNS))
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s AND target_type = %s AND target_id = %s
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (_uuid(project_id), "prompt_import", audit_event.target_id),
            )
            audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        self.connection.commit()
        return RuntimePromptImportResult(
            prompt_import=after,
            prompts=tuple(imported_rows),
            audit_events=audit_events,
        )

    def list_runtime_evidence_runs(
        self,
        *,
        project_id: str | None = None,
        platform: str | None = None,
        city: str | None = None,
        intent_type: str | None = None,
        status: str | None = None,
        sort: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeEvidencePage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        sort_key, order_by = _runtime_evidence_sort(sort)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("ar.project_id = %s")
            params.append(_uuid(project_id))
        if platform:
            filters.append("ar.platform = %s")
            params.append(platform)
        if city:
            filters.append("ar.city = %s")
            params.append(city)
        if intent_type:
            filters.append("pq.intent_type = %s")
            params.append(intent_type)
        if status:
            filters.append("ar.status = %s")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM answer_runs ar
                LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                {where_clause}
                """,
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                       pq.text AS prompt_text,
                       pq.intent_type AS prompt_intent_type,
                       pq.priority AS prompt_priority,
                       pq.prompt_version AS prompt_version
                FROM answer_runs ar
                LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                LEFT JOIN collection_costs cc ON cc.answer_run_id = ar.id
                LEFT JOIN (
                    SELECT answer_run_id, count(*) AS citation_count
                    FROM answer_citations
                    GROUP BY answer_run_id
                ) citation_counts ON citation_counts.answer_run_id = ar.id
                LEFT JOIN (
                    SELECT target_id AS answer_run_id, count(*) AS audit_event_count
                    FROM audit_events
                    WHERE target_type = 'answer_run'
                    GROUP BY target_id
                ) audit_counts ON audit_counts.answer_run_id = ar.id::text
                {where_clause}
                ORDER BY {order_by}
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            answer_runs = _rows_dict(cursor.fetchall(), ANSWER_RUN_READ_COLUMNS)
            records: list[RuntimeEvidenceRun] = []
            for answer_run in answer_runs:
                answer_run_id = str(answer_run["id"])
                records.append(self._load_runtime_evidence_run(cursor=cursor, answer_run=answer_run, answer_run_id=answer_run_id))
        return RuntimeEvidencePage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            sort=sort_key,
            records=tuple(records),
        )

    def list_runtime_collection_runs(
        self,
        *,
        project_id: str | None = None,
        run_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeCollectionRunPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if run_type:
            filters.append("run_type = %s")
            params.append(run_type)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM collection_run_summaries {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(COLLECTION_RUN_SUMMARY_COLUMNS)}
                FROM collection_run_summaries
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            runs = tuple(
                _runtime_collection_run_row(run)
                for run in _rows_dict(cursor.fetchall(), COLLECTION_RUN_SUMMARY_COLUMNS)
            )
            records: list[RuntimeCollectionRun] = []
            for run in runs:
                cursor.execute(
                    f"""
                    SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                    FROM audit_events
                    WHERE target_type = %s AND target_id = %s
                    ORDER BY created_at ASC
                    """,
                    ("collection_run", str(run["id"])),
                )
                records.append(
                    RuntimeCollectionRun(
                        collection_run=run,
                        audit_events=_rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS),
                    )
                )
        return RuntimeCollectionRunPage(total_count=total_count, limit=limit, offset=offset, records=tuple(records))

    def export_runtime_evidence_csv(
        self,
        *,
        project_id: str | None = None,
        platform: str | None = None,
        city: str | None = None,
        intent_type: str | None = None,
        status: str | None = None,
        sort: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        page = self.list_runtime_evidence_runs(
            project_id=project_id,
            platform=platform,
            city=city,
            intent_type=intent_type,
            status=status,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_evidence_csv(page)
        filters = {
            "project_id": project_id,
            "platform": platform,
            "city": city,
            "intent_type": intent_type,
            "status": status,
            "sort": page.sort,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_evidence_csv",
            filename="runtime-evidence.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def list_runtime_saved_views(
        self,
        *,
        project_id: str | None = None,
        view_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> RuntimeSavedViewPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if view_type:
            filters.append("view_type = %s")
            params.append(view_type)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM runtime_saved_views {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_SAVED_VIEW_COLUMNS)}
                FROM runtime_saved_views
                {where_clause}
                ORDER BY updated_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            saved_views = _rows_dict(cursor.fetchall(), RUNTIME_SAVED_VIEW_COLUMNS)
            records = tuple(self._load_runtime_saved_view(cursor=cursor, saved_view=saved_view) for saved_view in saved_views)
        return RuntimeSavedViewPage(total_count=total_count, limit=limit, offset=offset, records=records)

    def save_runtime_saved_view(self, view: RuntimeSavedViewInput) -> RuntimeSavedView:
        view_id = _stable_id("runtime-saved-view", view.project_id, view.name)
        after = {
            "id": view_id,
            "project_id": view.project_id,
            "name": view.name,
            "view_type": view.view_type,
            "filters": view.filters,
            "sort": view.sort,
            "query_path": view.query_path,
            "export_path": view.export_path,
            "created_by": view.created_by,
        }
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_SAVED_VIEW_COLUMNS)}
                FROM runtime_saved_views
                WHERE project_id = %s AND name = %s
                LIMIT 1
                """,
                (_uuid(view.project_id), view.name),
            )
            existing = cursor.fetchone()
            before = _row_dict(existing, RUNTIME_SAVED_VIEW_COLUMNS) if existing else None
            cursor.execute(
                """
                INSERT INTO runtime_saved_views (
                  id, project_id, name, view_type, filters, sort, query_path, export_path,
                  created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, name) DO UPDATE SET
                  view_type = EXCLUDED.view_type,
                  filters = EXCLUDED.filters,
                  sort = EXCLUDED.sort,
                  query_path = EXCLUDED.query_path,
                  export_path = EXCLUDED.export_path,
                  created_by = EXCLUDED.created_by,
                  updated_at = now()
                """,
                (
                    _uuid(view_id),
                    _uuid(view.project_id),
                    view.name,
                    view.view_type,
                    _json_payload(view.filters),
                    view.sort,
                    view.query_path,
                    view.export_path,
                    view.created_by,
                ),
            )
            audit_event = build_audit_event(
                event_type="runtime_saved_view_saved",
                project_id=view.project_id,
                actor_type="user",
                actor_id=view.created_by,
                target_type="runtime_saved_view",
                target_id=view_id,
                before=before,
                after=after,
                input_refs={"query_path": [view.query_path], "export_path": [view.export_path]},
                output_refs={"runtime_saved_view_ids": [view_id]},
                method_version="runtime_saved_view_v1",
                reason="save runtime evidence filter view",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_SAVED_VIEW_COLUMNS)}
                FROM runtime_saved_views
                WHERE id = %s
                """,
                (_uuid(view_id),),
            )
            saved_view = _row_dict(cursor.fetchone(), RUNTIME_SAVED_VIEW_COLUMNS)
            record = self._load_runtime_saved_view(cursor=cursor, saved_view=saved_view)
        self.connection.commit()
        return record

    def _load_runtime_saved_view(self, *, cursor: DbCursor, saved_view: dict[str, Any]) -> RuntimeSavedView:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            """,
            (_uuid(saved_view["project_id"]), "runtime_saved_view", str(saved_view["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeSavedView(saved_view=saved_view, audit_events=audit_events)

    def get_project_brand_kit(self, *, project_id: str) -> RuntimeProjectBrandKit | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_BRAND_KIT_COLUMNS)}
                FROM project_brand_kits
                WHERE project_id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._load_project_brand_kit(
                cursor=cursor,
                brand_kit=_row_dict(row, PROJECT_BRAND_KIT_COLUMNS),
            )

    def save_project_brand_kit(self, brand_kit: RuntimeProjectBrandKitInput) -> RuntimeProjectBrandKit:
        project_id = brand_kit.project_id.strip()
        client_name = brand_kit.client_name.strip()
        prepared_by = brand_kit.prepared_by.strip() or "GENO SaaS AU"
        updated_by = brand_kit.updated_by.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        if not client_name:
            raise ValueError("client_name is required")
        kit_id = _stable_id("project-brand-kit", project_id)
        after = {
            "id": kit_id,
            "project_id": project_id,
            "client_name": client_name,
            "prepared_by": prepared_by,
            "logo_url": brand_kit.logo_url.strip() if brand_kit.logo_url else None,
            "primary_color": brand_kit.primary_color.strip() if brand_kit.primary_color else None,
            "secondary_color": brand_kit.secondary_color.strip() if brand_kit.secondary_color else None,
            "footer_text": brand_kit.footer_text.strip() if brand_kit.footer_text else None,
            "updated_by": updated_by,
        }
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_BRAND_KIT_COLUMNS)}
                FROM project_brand_kits
                WHERE project_id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            existing = cursor.fetchone()
            before = _row_dict(existing, PROJECT_BRAND_KIT_COLUMNS) if existing else None
            cursor.execute(
                """
                INSERT INTO project_brand_kits (
                  id, project_id, client_name, prepared_by, logo_url, primary_color,
                  secondary_color, footer_text, updated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id) DO UPDATE SET
                  client_name = EXCLUDED.client_name,
                  prepared_by = EXCLUDED.prepared_by,
                  logo_url = EXCLUDED.logo_url,
                  primary_color = EXCLUDED.primary_color,
                  secondary_color = EXCLUDED.secondary_color,
                  footer_text = EXCLUDED.footer_text,
                  updated_by = EXCLUDED.updated_by,
                  updated_at = now()
                """,
                (
                    _uuid(kit_id),
                    _uuid(project_id),
                    after["client_name"],
                    after["prepared_by"],
                    after["logo_url"],
                    after["primary_color"],
                    after["secondary_color"],
                    after["footer_text"],
                    after["updated_by"],
                ),
            )
            audit_event = build_audit_event(
                event_type="project_brand_kit_saved",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="project_brand_kit",
                target_id=kit_id,
                before=before,
                after=after,
                input_refs={"project_ids": [project_id]},
                output_refs={"project_brand_kit_ids": [kit_id]},
                method_version="project_brand_kit_v1",
                reason="save project white-label brand configuration",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_BRAND_KIT_COLUMNS)}
                FROM project_brand_kits
                WHERE project_id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            saved_row = cursor.fetchone()
            record = self._load_project_brand_kit(
                cursor=cursor,
                brand_kit=_row_dict(saved_row, PROJECT_BRAND_KIT_COLUMNS),
            )
        self.connection.commit()
        return record

    def _load_project_brand_kit(self, *, cursor: DbCursor, brand_kit: dict[str, Any]) -> RuntimeProjectBrandKit:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(brand_kit["project_id"]), "project_brand_kit", str(brand_kit["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeProjectBrandKit(brand_kit=brand_kit, audit_events=audit_events)

    def get_score_weight_config(
        self,
        *,
        project_id: str,
        formula_version: str = "au_visibility_v1",
    ) -> RuntimeScoreWeightConfig | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(SCORE_WEIGHT_CONFIG_COLUMNS)}
                FROM score_weight_configs
                WHERE project_id = %s AND formula_version = %s
                LIMIT 1
                """,
                (_uuid(project_id), formula_version),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._load_score_weight_config(
                cursor=cursor,
                config=_row_dict(row, SCORE_WEIGHT_CONFIG_COLUMNS),
            )

    def save_score_weight_config(self, config: RuntimeScoreWeightConfigInput) -> RuntimeScoreWeightConfig:
        project_id = config.project_id.strip()
        formula_version = config.formula_version.strip() or "au_visibility_v1"
        updated_by = config.updated_by.strip() or "runtime-console"
        if formula_version != "au_visibility_v1":
            raise ValueError("formula_version must be au_visibility_v1")
        if not project_id:
            raise ValueError("project_id is required")
        weights = normalize_score_weights(config.weights)
        config_id = _stable_id("score-weight-config", project_id, formula_version)
        after = {
            "id": config_id,
            "project_id": project_id,
            "formula_version": formula_version,
            "weights": weights,
            "updated_by": updated_by,
            "notes": config.notes.strip() if config.notes else None,
        }
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                f"""
                SELECT {", ".join(SCORE_WEIGHT_CONFIG_COLUMNS)}
                FROM score_weight_configs
                WHERE project_id = %s AND formula_version = %s
                LIMIT 1
                """,
                (_uuid(project_id), formula_version),
            )
            existing = cursor.fetchone()
            before = _row_dict(existing, SCORE_WEIGHT_CONFIG_COLUMNS) if existing else None
            cursor.execute(
                """
                INSERT INTO score_weight_configs (
                  id, project_id, formula_version, weights, updated_by, notes
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, formula_version) DO UPDATE SET
                  weights = EXCLUDED.weights,
                  updated_by = EXCLUDED.updated_by,
                  notes = EXCLUDED.notes,
                  updated_at = now()
                """,
                (
                    _uuid(config_id),
                    _uuid(project_id),
                    formula_version,
                    _json_payload(weights),
                    updated_by,
                    after["notes"],
                ),
            )
            audit_event = build_audit_event(
                event_type="score_weight_config_saved",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="score_weight_config",
                target_id=config_id,
                before=before,
                after=after,
                input_refs={"project_ids": [project_id]},
                output_refs={"score_weight_config_ids": [config_id]},
                method_version="score_weight_config_v1",
                reason="save project-level AU visibility score weights",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(SCORE_WEIGHT_CONFIG_COLUMNS)}
                FROM score_weight_configs
                WHERE project_id = %s AND formula_version = %s
                LIMIT 1
                """,
                (_uuid(project_id), formula_version),
            )
            saved_row = cursor.fetchone()
            record = self._load_score_weight_config(
                cursor=cursor,
                config=_row_dict(saved_row, SCORE_WEIGHT_CONFIG_COLUMNS),
            )
        self.connection.commit()
        return record

    def get_score_weights_snapshot(
        self,
        *,
        project_id: str,
        formula_version: str = "au_visibility_v1",
    ) -> dict[str, float]:
        record = self.get_score_weight_config(project_id=project_id, formula_version=formula_version)
        if record is None:
            return dict(AU_VISIBILITY_V1)
        return normalize_score_weights(dict(record.score_weight_config.get("weights") or {}))

    def _load_score_weight_config(
        self,
        *,
        cursor: DbCursor,
        config: dict[str, Any],
    ) -> RuntimeScoreWeightConfig:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(config["project_id"]), "score_weight_config", str(config["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeScoreWeightConfig(score_weight_config=config, audit_events=audit_events)

    def list_runtime_human_reviews(
        self,
        *,
        project_id: str | None = None,
        target_type: str | None = None,
        review_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeHumanReviewPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if target_type:
            filters.append("target_type = %s")
            params.append(target_type)
        if review_status:
            filters.append("review_status = %s")
            params.append(review_status)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM human_review_records {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(HUMAN_REVIEW_COLUMNS)}
                FROM human_review_records
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            reviews = _rows_dict(cursor.fetchall(), HUMAN_REVIEW_COLUMNS)
            records = tuple(self._load_runtime_human_review(cursor=cursor, human_review=review) for review in reviews)
        return RuntimeHumanReviewPage(total_count=total_count, limit=limit, offset=offset, records=records)

    def save_human_review(self, review: RuntimeHumanReviewInput) -> RuntimeHumanReviewRecord:
        project_id = review.project_id.strip()
        target_type = review.target_type.strip()
        target_id = review.target_id.strip()
        review_status = review.review_status.strip()
        decision = review.decision.strip()
        reviewer_id = review.reviewer_id.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        if not target_type:
            raise ValueError("target_type is required")
        if not target_id:
            raise ValueError("target_id is required")
        if not review_status:
            raise ValueError("review_status is required")
        if not decision:
            raise ValueError("decision is required")
        review_id = str(uuid4())
        after = {
            "id": review_id,
            "project_id": project_id,
            "target_type": target_type,
            "target_id": target_id,
            "review_status": review_status,
            "decision": decision,
            "reviewer_id": reviewer_id,
            "notes": review.notes.strip() if review.notes else None,
            "payload": review.payload or {},
        }
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                """
                INSERT INTO human_review_records (
                  id, project_id, target_type, target_id, review_status,
                  decision, reviewer_id, notes, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    _uuid(review_id),
                    _uuid(project_id),
                    target_type,
                    target_id,
                    review_status,
                    decision,
                    reviewer_id,
                    after["notes"],
                    _json_payload(after["payload"]),
                ),
            )
            audit_event = build_audit_event(
                event_type="human_review_recorded",
                project_id=project_id,
                actor_type="user",
                actor_id=reviewer_id,
                target_type="human_review_record",
                target_id=review_id,
                before=None,
                after=after,
                input_refs={"review_target": [{"target_type": target_type, "target_id": target_id}]},
                output_refs={"human_review_record_ids": [review_id]},
                method_version="human_review_v1",
                reason="record human review decision for an auditable runtime object",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(HUMAN_REVIEW_COLUMNS)}
                FROM human_review_records
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(review_id),),
            )
            record = self._load_runtime_human_review(
                cursor=cursor,
                human_review=_row_dict(cursor.fetchone(), HUMAN_REVIEW_COLUMNS),
            )
        self.connection.commit()
        return record

    def _load_runtime_human_review(
        self,
        *,
        cursor: DbCursor,
        human_review: dict[str, Any],
    ) -> RuntimeHumanReviewRecord:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(human_review["project_id"]), "human_review_record", str(human_review["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeHumanReviewRecord(human_review=human_review, audit_events=audit_events)

    def list_runtime_score_snapshots(
        self,
        *,
        project_id: str | None = None,
        scope_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeScoreSnapshotPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if scope_type:
            filters.append("scope_type = %s")
            params.append(scope_type)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM visibility_score_snapshots {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(VISIBILITY_SCORE_SNAPSHOT_COLUMNS)}
                FROM visibility_score_snapshots
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            snapshots = _rows_dict(cursor.fetchall(), VISIBILITY_SCORE_SNAPSHOT_COLUMNS)
            records = tuple(
                self._load_runtime_score_snapshot(
                    cursor=cursor,
                    snapshot=snapshot,
                    snapshot_id=str(snapshot["id"]),
                )
                for snapshot in snapshots
            )
        return RuntimeScoreSnapshotPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def list_runtime_citation_graphs(
        self,
        *,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeCitationGraphPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        params: list[object] = []
        where_clause = ""
        if project_id:
            where_clause = "WHERE project_id = %s"
            params.append(_uuid(project_id))

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(DISTINCT project_id) FROM source_graphs {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT project_id
                FROM source_graphs
                {where_clause}
                GROUP BY project_id
                ORDER BY max(created_at) DESC, project_id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            project_rows = cursor.fetchall()
            project_ids = tuple(str(row["project_id"] if isinstance(row, dict) else row[0]) for row in project_rows)
            records = tuple(
                self._load_runtime_citation_graph(cursor=cursor, project_id=graph_project_id)
                for graph_project_id in project_ids
            )
        return RuntimeCitationGraphPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def list_runtime_report_exports(
        self,
        *,
        project_id: str | None = None,
        report_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeReportExportPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if report_type:
            filters.append("report_type = %s")
            params.append(report_type)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM report_exports {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(REPORT_EXPORT_COLUMNS)}
                FROM report_exports
                {where_clause}
                ORDER BY exported_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            reports = _rows_dict(cursor.fetchall(), REPORT_EXPORT_COLUMNS)
            records = tuple(
                self._load_runtime_report_export(cursor=cursor, report_export=report)
                for report in reports
            )
        return RuntimeReportExportPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def get_runtime_report_artifact(
        self,
        *,
        report_export_id: str,
        artifact_type: str,
        platform: str | None = None,
        city: str | None = None,
        intent_type: str | None = None,
        status: str | None = None,
        sort: str | None = None,
        template: str | None = None,
        client_name: str | None = None,
        prepared_by: str | None = None,
    ) -> RuntimeReportArtifact | None:
        artifact_type = artifact_type.lower()
        if artifact_type not in {"markdown", "csv", "pdf"}:
            raise ValueError("artifact_type must be markdown, csv, or pdf")
        template_name = (template or "standard").strip().lower() or "standard"
        if template_name not in {"standard", "white_label"}:
            raise ValueError("template must be standard or white_label")
        if template_name == "white_label" and artifact_type != "pdf":
            raise ValueError("white_label template is only supported for pdf artifacts")
        brand_kit: dict[str, Any] | None = None
        with self.connection.cursor() as cursor:
            report_export = self._load_report_export_by_id(
                cursor=cursor,
                report_export_id=report_export_id,
            )
            if not report_export:
                return None
            runtime_report = self._load_runtime_report_export(
                cursor=cursor,
                report_export=report_export,
            )
            if template_name == "white_label" and (not client_name or not prepared_by):
                cursor.execute(
                    f"""
                    SELECT {", ".join(PROJECT_BRAND_KIT_COLUMNS)}
                    FROM project_brand_kits
                    WHERE project_id = %s
                    LIMIT 1
                    """,
                    (_uuid(str(runtime_report.report_export["project_id"])),),
                )
                brand_kit_row = cursor.fetchone()
                brand_kit = _row_dict(brand_kit_row, PROJECT_BRAND_KIT_COLUMNS) if brand_kit_row else None
        white_label_client = (
            client_name
            or (brand_kit.get("client_name") if brand_kit else None)
            or "Client"
        ).strip() or "Client"
        white_label_prepared_by = (
            prepared_by
            or (brand_kit.get("prepared_by") if brand_kit else None)
            or "GENO SaaS"
        ).strip() or "GENO SaaS"
        white_label_logo_url = (brand_kit.get("logo_url") if brand_kit else None) or None
        white_label_primary_color = (brand_kit.get("primary_color") if brand_kit else None) or None
        white_label_secondary_color = (brand_kit.get("secondary_color") if brand_kit else None) or None
        white_label_footer_text = (brand_kit.get("footer_text") if brand_kit else None) or None
        filtered_answer_runs, sort_key = _filter_runtime_report_answer_runs(
            runtime_report.answer_runs,
            platform=platform,
            city=city,
            intent_type=intent_type,
            status=status,
            sort=sort,
        )
        filtered_report = RuntimeReportExport(
            report_export=runtime_report.report_export,
            score_snapshots=runtime_report.score_snapshots,
            answer_runs=filtered_answer_runs,
            citation_graph=runtime_report.citation_graph,
            audit_events=runtime_report.audit_events,
        )
        if artifact_type == "markdown":
            content = _render_runtime_report_markdown(filtered_report)
            extension = "md"
            media_type = "text/markdown; charset=utf-8"
        elif artifact_type == "csv":
            content = _render_runtime_report_csv(filtered_report)
            extension = "csv"
            media_type = "text/csv; charset=utf-8"
        else:
            markdown = (
                _render_white_label_report_markdown(
                    filtered_report,
                    client_name=white_label_client,
                    prepared_by=white_label_prepared_by,
                    logo_url=white_label_logo_url,
                    primary_color=white_label_primary_color,
                    secondary_color=white_label_secondary_color,
                    footer_text=white_label_footer_text,
                )
                if template_name == "white_label"
                else _render_runtime_report_markdown(filtered_report)
            )
            content = render_markdown_pdf(markdown)
            extension = "pdf"
            media_type = "application/pdf"
        template_payload = (
            {
                "template": template_name,
                "client_name": white_label_client,
                "prepared_by": white_label_prepared_by,
                "logo_url": white_label_logo_url,
                "primary_color": white_label_primary_color,
                "secondary_color": white_label_secondary_color,
                "footer_text": white_label_footer_text,
                "source": "project_brand_kit" if brand_kit else "query_or_default",
            }
            if template_name == "white_label"
            else {"template": template_name}
        )
        filters = {
            "platform": platform,
            "city": city,
            "intent_type": intent_type,
            "status": status,
        }
        active_filters = {key: value for key, value in filters.items() if value is not None}
        filename_stem = report_export["report_version"]
        if template_name == "white_label":
            filename_stem = f"{filename_stem}-white-label"
        filename = f"{filename_stem}.{extension}"
        return RuntimeReportArtifact(
            report_export=report_export,
            artifact_type=artifact_type,
            template=template_name,
            template_payload=template_payload,
            template_hash=_artifact_hash(json.dumps(template_payload, ensure_ascii=False, sort_keys=True)),
            filename=filename,
            media_type=media_type,
            content=content,
            content_hash=_artifact_hash(content),
            filters=active_filters,
            filter_hash=_artifact_hash(json.dumps(active_filters, ensure_ascii=False, sort_keys=True)),
            sort=sort_key,
            total_count=len(runtime_report.answer_runs),
            row_count=len(filtered_report.answer_runs),
        )

    def get_runtime_traceability_detail(
        self,
        *,
        project_id: str | None = None,
        report_export_id: str | None = None,
    ) -> RuntimeTraceabilityDetail | None:
        filters: list[str] = []
        params: list[object] = []
        if report_export_id:
            filters.append("subject_type = %s")
            params.append("report_export")
            filters.append("subject_id = %s")
            params.append(_uuid(report_export_id))
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(TRACEABILITY_BUNDLE_COLUMNS)}
                FROM traceability_bundles
                {where_clause}
                ORDER BY id DESC
                LIMIT 1
                """,
                tuple(params),
            )
            bundle_row = cursor.fetchone()
            if not bundle_row:
                return None
            bundle = _row_dict(bundle_row, TRACEABILITY_BUNDLE_COLUMNS)

            report_exports = tuple(
                self._load_report_export_by_id(cursor=cursor, report_export_id=str(value))
                for value in bundle["report_export_ids"]
            )
            report_exports = tuple(report for report in report_exports if report)
            score_snapshots = tuple(
                runtime_snapshot
                for score_snapshot_id in tuple(str(value) for value in bundle["score_snapshot_ids"])
                if (
                    runtime_snapshot := self._load_score_snapshot_by_id(
                        cursor=cursor,
                        score_snapshot_id=score_snapshot_id,
                    )
                )
                is not None
            )
            evidence_runs = tuple(
                runtime_evidence
                for answer_run_id in tuple(str(value) for value in bundle["answer_run_ids"])
                if (
                    runtime_evidence := self._load_evidence_run_by_id(
                        cursor=cursor,
                        answer_run_id=answer_run_id,
                    )
                )
                is not None
            )
            cursor.execute("SELECT count(*) FROM source_graphs WHERE project_id = %s", (_uuid(str(bundle["project_id"])),))
            graph_count_row = cursor.fetchone()
            graph_count = int(graph_count_row[0] if not isinstance(graph_count_row, dict) else graph_count_row["count"])
            citation_graph = (
                self._load_runtime_citation_graph(cursor=cursor, project_id=str(bundle["project_id"]))
                if graph_count > 0
                else None
            )
            action_recommendations = tuple(
                action
                for action_id in tuple(str(value) for value in bundle["action_recommendation_ids"])
                if (action := self._load_action_recommendation_by_id(cursor=cursor, action_id=action_id)) is not None
            )
            content_drafts = tuple(
                draft
                for content_draft_id in tuple(str(value) for value in bundle["content_draft_ids"])
                if (
                    draft := self._load_runtime_content_draft_by_id(
                        cursor=cursor,
                        content_draft_id=content_draft_id,
                    )
                )
                is not None
            )
            audit_events = tuple(
                event
                for audit_event_id in tuple(str(value) for value in bundle["audit_event_ids"])
                if (event := self._load_audit_event_by_id(cursor=cursor, audit_event_id=audit_event_id)) is not None
            )
            cursor.execute(
                f"""
                SELECT {", ".join(EVIDENCE_LINK_COLUMNS)}
                FROM evidence_links
                WHERE project_id = %s AND (
                    source_id = ANY(%s::uuid[]) OR target_id = ANY(%s::uuid[])
                )
                ORDER BY relation_type ASC, id ASC
                """,
                (
                    _uuid(str(bundle["project_id"])),
                    _uuid_array(
                        (
                            str(bundle["subject_id"]),
                            *tuple(str(value) for value in bundle["report_export_ids"]),
                        )
                    ),
                    _uuid_array(
                        (
                            *tuple(str(value) for value in bundle["score_snapshot_ids"]),
                            *tuple(str(value) for value in bundle["score_contribution_ids"]),
                            *tuple(str(value) for value in bundle["source_graph_ids"]),
                            *tuple(str(value) for value in bundle["action_recommendation_ids"]),
                            *tuple(str(value) for value in bundle["content_draft_ids"]),
                        )
                    ),
                ),
            )
            evidence_links = _rows_dict(cursor.fetchall(), EVIDENCE_LINK_COLUMNS)
        return RuntimeTraceabilityDetail(
            traceability_bundle=bundle,
            report_exports=report_exports,
            score_snapshots=score_snapshots,
            evidence_runs=evidence_runs,
            citation_graph=citation_graph,
            action_recommendations=action_recommendations,
            content_drafts=content_drafts,
            audit_events=audit_events,
            evidence_links=evidence_links,
        )

    def _load_report_export_by_id(
        self,
        *,
        cursor: DbCursor,
        report_export_id: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT {", ".join(REPORT_EXPORT_COLUMNS)}
            FROM report_exports
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(report_export_id),),
        )
        report_row = cursor.fetchone()
        return _row_dict(report_row, REPORT_EXPORT_COLUMNS) if report_row else None

    def _load_score_snapshot_by_id(
        self,
        *,
        cursor: DbCursor,
        score_snapshot_id: str,
    ) -> RuntimeScoreSnapshot | None:
        cursor.execute(
            f"""
            SELECT {", ".join(VISIBILITY_SCORE_SNAPSHOT_COLUMNS)}
            FROM visibility_score_snapshots
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(score_snapshot_id),),
        )
        snapshot_row = cursor.fetchone()
        if not snapshot_row:
            return None
        snapshot = _row_dict(snapshot_row, VISIBILITY_SCORE_SNAPSHOT_COLUMNS)
        return self._load_runtime_score_snapshot(
            cursor=cursor,
            snapshot=snapshot,
            snapshot_id=str(snapshot["id"]),
        )

    def _load_evidence_run_by_id(
        self,
        *,
        cursor: DbCursor,
        answer_run_id: str,
    ) -> RuntimeEvidenceRun | None:
        cursor.execute(
            f"""
            SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                   pq.text AS prompt_text,
                   pq.intent_type AS prompt_intent_type,
                   pq.priority AS prompt_priority,
                   pq.prompt_version AS prompt_version
            FROM answer_runs ar
            LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
            WHERE ar.id = %s
            LIMIT 1
            """,
            (_uuid(answer_run_id),),
        )
        answer_run_row = cursor.fetchone()
        if not answer_run_row:
            return None
        answer_run = _row_dict(answer_run_row, ANSWER_RUN_READ_COLUMNS)
        return self._load_runtime_evidence_run(
            cursor=cursor,
            answer_run=answer_run,
            answer_run_id=str(answer_run["id"]),
        )

    def _load_action_recommendation_by_id(
        self,
        *,
        cursor: DbCursor,
        action_id: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT {", ".join(ACTION_RECOMMENDATION_COLUMNS)}
            FROM action_recommendations
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(action_id),),
        )
        action_row = cursor.fetchone()
        return _row_dict(action_row, ACTION_RECOMMENDATION_COLUMNS) if action_row else None

    def _load_runtime_content_draft_by_id(
        self,
        *,
        cursor: DbCursor,
        content_draft_id: str,
    ) -> RuntimeContentDraft | None:
        cursor.execute(
            f"""
            SELECT {", ".join(CONTENT_DRAFT_COLUMNS)}
            FROM content_drafts
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(content_draft_id),),
        )
        draft_row = cursor.fetchone()
        if not draft_row:
            return None
        return self._load_runtime_content_draft(
            cursor=cursor,
            draft=_row_dict(draft_row, CONTENT_DRAFT_COLUMNS),
        )

    def _load_audit_event_by_id(
        self,
        *,
        cursor: DbCursor,
        audit_event_id: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(audit_event_id),),
        )
        event_row = cursor.fetchone()
        return _row_dict(event_row, AUDIT_EVENT_COLUMNS) if event_row else None

    def list_runtime_action_plans(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeActionPlanPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("rs.project_id = %s")
            params.append(_uuid(project_id))
        if status:
            filters.append(
                "EXISTS (SELECT 1 FROM action_recommendations ar WHERE ar.project_id = rs.project_id AND ar.status = %s)"
            )
            params.append(status)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM retest_schedules rs {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(f"rs.{column}" for column in RETEST_SCHEDULE_COLUMNS)}
                FROM retest_schedules rs
                {where_clause}
                ORDER BY rs.created_at DESC, rs.id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            schedules = _rows_dict(cursor.fetchall(), RETEST_SCHEDULE_COLUMNS)
            records = tuple(
                self._load_runtime_action_plan(cursor=cursor, schedule=schedule, status=status)
                for schedule in schedules
            )
        return RuntimeActionPlanPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def _load_runtime_action_plan(
        self,
        *,
        cursor: DbCursor,
        schedule: dict[str, Any],
        status: str | None,
    ) -> RuntimeActionPlan:
        action_filters = ["project_id = %s"]
        action_params: list[object] = [_uuid(str(schedule["project_id"]))]
        if status:
            action_filters.append("status = %s")
            action_params.append(status)
        cursor.execute(
            f"""
            SELECT {", ".join(ACTION_RECOMMENDATION_COLUMNS)}
            FROM action_recommendations
            WHERE {" AND ".join(action_filters)}
            ORDER BY priority ASC, next_check_date ASC, id ASC
            """,
            tuple(action_params),
        )
        actions = _rows_dict(cursor.fetchall(), ACTION_RECOMMENDATION_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(RETEST_COMPARISON_COLUMNS)}
            FROM retest_comparisons
            WHERE project_id = %s
            ORDER BY created_at DESC, id DESC
            """,
            (_uuid(str(schedule["project_id"])),),
        )
        comparisons = _rows_dict(cursor.fetchall(), RETEST_COMPARISON_COLUMNS)
        answer_runs: list[dict[str, Any]] = []
        for answer_run_id in tuple(str(value) for value in schedule["answer_run_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                       pq.text AS prompt_text,
                       pq.intent_type AS prompt_intent_type,
                       pq.priority AS prompt_priority,
                       pq.prompt_version AS prompt_version
                FROM answer_runs ar
                LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                WHERE ar.id = %s
                LIMIT 1
                """,
                (_uuid(answer_run_id),),
            )
            answer_run_row = cursor.fetchone()
            if answer_run_row:
                answer_runs.append(_row_dict(answer_run_row, ANSWER_RUN_READ_COLUMNS))
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at ASC
            """,
            ("action_plan", str(schedule["id"])),
        )
        audit_events = list(_rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS))
        for comparison in comparisons:
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE target_type = %s AND target_id = %s
                ORDER BY created_at ASC
                """,
                ("retest_comparison", str(comparison["id"])),
            )
            audit_events.extend(_rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS))
        return RuntimeActionPlan(
            retest_schedule=schedule,
            action_recommendations=actions,
            retest_comparisons=comparisons,
            answer_runs=tuple(answer_runs),
            audit_events=tuple(audit_events),
        )

    def list_runtime_content_engines(
        self,
        *,
        project_id: str | None = None,
        review_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeContentEnginePage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("cd.project_id = %s")
            params.append(_uuid(project_id))
        if review_status:
            filters.append("cd.review_status = %s")
            params.append(review_status)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(DISTINCT cd.project_id) FROM content_drafts cd {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT cd.project_id
                FROM content_drafts cd
                {where_clause}
                GROUP BY cd.project_id
                ORDER BY max(cd.created_at) DESC, cd.project_id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            project_rows = cursor.fetchall()
            project_ids = tuple(str(row["project_id"] if isinstance(row, dict) else row[0]) for row in project_rows)
            records = tuple(
                self._load_runtime_content_engine(
                    cursor=cursor,
                    project_id=content_project_id,
                    review_status=review_status,
                )
                for content_project_id in project_ids
            )
        return RuntimeContentEnginePage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def _load_runtime_content_engine(
        self,
        *,
        cursor: DbCursor,
        project_id: str,
        review_status: str | None,
    ) -> RuntimeContentEngine:
        cursor.execute(
            f"""
            SELECT {", ".join(LOCALIZED_KNOWLEDGE_FACT_COLUMNS)}
            FROM localized_knowledge_facts
            WHERE project_id = %s
            ORDER BY market_code ASC, fact_type ASC, subject ASC, id ASC
            """,
            (_uuid(project_id),),
        )
        knowledge_facts = _rows_dict(cursor.fetchall(), LOCALIZED_KNOWLEDGE_FACT_COLUMNS)
        draft_filters = ["project_id = %s"]
        draft_params: list[object] = [_uuid(project_id)]
        if review_status:
            draft_filters.append("review_status = %s")
            draft_params.append(review_status)
        cursor.execute(
            f"""
            SELECT {", ".join(CONTENT_DRAFT_COLUMNS)}
            FROM content_drafts
            WHERE {" AND ".join(draft_filters)}
            ORDER BY created_at DESC, id DESC
            """,
            tuple(draft_params),
        )
        drafts = _rows_dict(cursor.fetchall(), CONTENT_DRAFT_COLUMNS)
        runtime_drafts = tuple(
            self._load_runtime_content_draft(cursor=cursor, draft=draft)
            for draft in drafts
        )
        cursor.execute(
            f"""
            SELECT {", ".join(INTEGRATION_CONNECTOR_COLUMNS)}
            FROM integration_connectors
            WHERE project_id = %s
            ORDER BY provider ASC
            """,
            (_uuid(project_id),),
        )
        connectors = _rows_dict(cursor.fetchall(), INTEGRATION_CONNECTOR_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(MANUAL_DISTRIBUTION_RECORD_COLUMNS)}
            FROM manual_distribution_records
            WHERE project_id = %s
            ORDER BY content_draft_id ASC, id ASC
            """,
            (_uuid(project_id),),
        )
        distribution_records = _rows_dict(cursor.fetchall(), MANUAL_DISTRIBUTION_RECORD_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at ASC
            """,
            ("content_engine_fixture", project_id),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeContentEngine(
            project_id=project_id,
            knowledge_facts=knowledge_facts,
            content_drafts=runtime_drafts,
            integration_connectors=connectors,
            manual_distribution_records=distribution_records,
            audit_events=audit_events,
        )

    def _load_runtime_content_draft(self, *, cursor: DbCursor, draft: dict[str, Any]) -> RuntimeContentDraft:
        target_questions: list[dict[str, Any]] = []
        for prompt_id in tuple(str(value) for value in draft["target_question_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(PROMPT_QUESTION_READ_COLUMNS)}
                FROM prompt_questions
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(prompt_id),),
            )
            prompt_row = cursor.fetchone()
            if prompt_row:
                target_questions.append(_row_dict(prompt_row, PROMPT_QUESTION_READ_COLUMNS))
        knowledge_facts: list[dict[str, Any]] = []
        for fact_id in tuple(str(value) for value in draft["used_knowledge_fact_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(LOCALIZED_KNOWLEDGE_FACT_COLUMNS)}
                FROM localized_knowledge_facts
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(fact_id),),
            )
            fact_row = cursor.fetchone()
            if fact_row:
                knowledge_facts.append(_row_dict(fact_row, LOCALIZED_KNOWLEDGE_FACT_COLUMNS))
        answer_runs: list[dict[str, Any]] = []
        for answer_run_id in tuple(str(value) for value in draft["evidence_answer_run_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                       pq.text AS prompt_text,
                       pq.intent_type AS prompt_intent_type,
                       pq.priority AS prompt_priority,
                       pq.prompt_version AS prompt_version
                FROM answer_runs ar
                LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                WHERE ar.id = %s
                LIMIT 1
                """,
                (_uuid(answer_run_id),),
            )
            answer_run_row = cursor.fetchone()
            if answer_run_row:
                answer_runs.append(_row_dict(answer_run_row, ANSWER_RUN_READ_COLUMNS))
        action_recommendation = None
        if draft["source_action_id"]:
            cursor.execute(
                f"""
                SELECT {", ".join(ACTION_RECOMMENDATION_COLUMNS)}
                FROM action_recommendations
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(str(draft["source_action_id"])),),
            )
            action_row = cursor.fetchone()
            if action_row:
                action_recommendation = _row_dict(action_row, ACTION_RECOMMENDATION_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(MANUAL_DISTRIBUTION_RECORD_COLUMNS)}
            FROM manual_distribution_records
            WHERE content_draft_id = %s
            ORDER BY id ASC
            """,
            (_uuid(str(draft["id"])),),
        )
        distribution_records = _rows_dict(cursor.fetchall(), MANUAL_DISTRIBUTION_RECORD_COLUMNS)
        return RuntimeContentDraft(
            draft=draft,
            target_questions=tuple(target_questions),
            knowledge_facts=tuple(knowledge_facts),
            answer_runs=tuple(answer_runs),
            action_recommendation=action_recommendation,
            manual_distribution_records=distribution_records,
        )

    def _load_runtime_report_export(
        self,
        *,
        cursor: DbCursor,
        report_export: dict[str, Any],
    ) -> RuntimeReportExport:
        score_snapshots: list[dict[str, Any]] = []
        for score_snapshot_id in tuple(str(value) for value in report_export["score_snapshot_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(VISIBILITY_SCORE_SNAPSHOT_COLUMNS)}
                FROM visibility_score_snapshots
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(score_snapshot_id),),
            )
            snapshot_row = cursor.fetchone()
            if snapshot_row:
                score_snapshots.append(_row_dict(snapshot_row, VISIBILITY_SCORE_SNAPSHOT_COLUMNS))
        answer_runs: list[dict[str, Any]] = []
        for answer_run_id in tuple(str(value) for value in report_export["answer_run_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                       pq.text AS prompt_text,
                       pq.intent_type AS prompt_intent_type,
                       pq.priority AS prompt_priority,
                       pq.prompt_version AS prompt_version,
                       cc.total_cost AS total_cost,
                       citation_counts.citation_count AS citation_count,
                       audit_counts.audit_event_count AS audit_event_count
                FROM report_evidence re
                JOIN answer_runs ar ON ar.id = re.answer_run_id
                LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                LEFT JOIN collection_costs cc ON cc.answer_run_id = ar.id
                LEFT JOIN (
                    SELECT answer_run_id, count(*) AS citation_count
                    FROM answer_citations
                    GROUP BY answer_run_id
                ) citation_counts ON citation_counts.answer_run_id = ar.id
                LEFT JOIN (
                    SELECT target_id AS answer_run_id, count(*) AS audit_event_count
                    FROM audit_events
                    WHERE target_type = 'answer_run'
                    GROUP BY target_id
                ) audit_counts ON audit_counts.answer_run_id = ar.id::text
                WHERE re.report_export_id = %s AND re.answer_run_id = %s
                ORDER BY re.created_at ASC
                LIMIT 1
                """,
                (_uuid(str(report_export["id"])), _uuid(answer_run_id)),
            )
            answer_run_row = cursor.fetchone()
            if answer_run_row:
                answer_runs.append(
                    _row_dict(
                        answer_run_row,
                        ANSWER_RUN_READ_COLUMNS + ("total_cost", "citation_count", "audit_event_count"),
                    )
                )
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at ASC
            """,
            ("report_export", str(report_export["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        cursor.execute("SELECT count(*) FROM source_graphs WHERE project_id = %s", (_uuid(str(report_export["project_id"])),))
        graph_count_row = cursor.fetchone()
        graph_count = int(graph_count_row[0] if not isinstance(graph_count_row, dict) else graph_count_row["count"])
        citation_graph = (
            self._load_runtime_citation_graph(cursor=cursor, project_id=str(report_export["project_id"]))
            if graph_count > 0
            else None
        )
        return RuntimeReportExport(
            report_export=report_export,
            score_snapshots=tuple(score_snapshots),
            answer_runs=tuple(answer_runs),
            citation_graph=citation_graph,
            audit_events=audit_events,
        )

    def _load_runtime_citation_graph(self, *, cursor: DbCursor, project_id: str) -> RuntimeCitationGraph:
        cursor.execute(
            f"""
            SELECT {", ".join(SOURCE_GRAPH_COLUMNS)}
            FROM source_graphs
            WHERE project_id = %s
            ORDER BY citation_count DESC, source_domain ASC, source_type ASC
            """,
            (_uuid(project_id),),
        )
        nodes = _rows_dict(cursor.fetchall(), SOURCE_GRAPH_COLUMNS)
        runtime_nodes: list[RuntimeCitationGraphNode] = []
        for node in nodes:
            answer_run_ids = tuple(str(answer_run_id) for answer_run_id in node["answer_run_ids"])
            answer_runs: list[dict[str, Any]] = []
            for answer_run_id in answer_run_ids:
                cursor.execute(
                    f"""
                    SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                           pq.text AS prompt_text,
                           pq.intent_type AS prompt_intent_type,
                           pq.priority AS prompt_priority,
                           pq.prompt_version AS prompt_version
                    FROM answer_runs ar
                    LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                    WHERE ar.id = %s
                    LIMIT 1
                    """,
                    (_uuid(answer_run_id),),
                )
                answer_run_row = cursor.fetchone()
                if answer_run_row:
                    answer_runs.append(_row_dict(answer_run_row, ANSWER_RUN_READ_COLUMNS))
            runtime_nodes.append(
                RuntimeCitationGraphNode(
                    node=node,
                    answer_runs=tuple(answer_runs),
                )
            )
        cursor.execute(
            f"""
            SELECT sge.id AS id,
                   sge.source_graph_id AS source_graph_id,
                   sge.answer_run_id AS answer_run_id,
                   sge.answer_citation_id AS answer_citation_id,
                   sge.relation_type AS relation_type,
                   sge.created_at AS created_at
            FROM source_graph_evidence sge
            JOIN source_graphs sg ON sg.id = sge.source_graph_id
            WHERE sg.project_id = %s
            ORDER BY sge.created_at ASC, sge.id ASC
            """,
            (_uuid(project_id),),
        )
        evidence_links = _rows_dict(cursor.fetchall(), SOURCE_GRAPH_EVIDENCE_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(SOURCE_GAP_COLUMNS)}
            FROM source_gaps
            WHERE project_id = %s
            ORDER BY expected_weight DESC, source_type ASC, gap_type ASC
            """,
            (_uuid(project_id),),
        )
        source_gaps = _rows_dict(cursor.fetchall(), SOURCE_GAP_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(COMPETITOR_BENCHMARK_COLUMNS)}
            FROM competitor_benchmarks
            WHERE project_id = %s
            ORDER BY competitor_name ASC
            """,
            (_uuid(project_id),),
        )
        competitor_benchmarks = _rows_dict(cursor.fetchall(), COMPETITOR_BENCHMARK_COLUMNS)
        return RuntimeCitationGraph(
            project_id=project_id,
            nodes=tuple(runtime_nodes),
            evidence_links=evidence_links,
            source_gaps=source_gaps,
            competitor_benchmarks=competitor_benchmarks,
        )

    def _load_runtime_score_snapshot(
        self,
        *,
        cursor: DbCursor,
        snapshot: dict[str, Any],
        snapshot_id: str,
    ) -> RuntimeScoreSnapshot:
        cursor.execute(
            f"""
            SELECT {", ".join(SCORE_CONTRIBUTION_COLUMNS)}
            FROM score_contributions
            WHERE score_snapshot_id = %s
            ORDER BY component_name ASC, created_at ASC
            """,
            (_uuid(snapshot_id),),
        )
        contributions = _rows_dict(cursor.fetchall(), SCORE_CONTRIBUTION_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                   pq.text AS prompt_text,
                   pq.intent_type AS prompt_intent_type,
                   pq.priority AS prompt_priority,
                   pq.prompt_version AS prompt_version
            FROM score_snapshot_runs ssr
            JOIN answer_runs ar ON ar.id = ssr.answer_run_id
            LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
            WHERE ssr.score_snapshot_id = %s
            GROUP BY {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                     pq.text, pq.intent_type, pq.priority, pq.prompt_version
            ORDER BY ar.collected_at ASC, ar.id ASC
            """,
            (_uuid(snapshot_id),),
        )
        answer_runs = _rows_dict(cursor.fetchall(), ANSWER_RUN_READ_COLUMNS)
        runtime_answer_runs: list[RuntimeScoreSnapshotRun] = []
        for answer_run in answer_runs:
            answer_run_id = str(answer_run["id"])
            cursor.execute(
                f"""
                SELECT {", ".join(ANSWER_ANALYSIS_READ_COLUMNS)}
                FROM answer_analyses
                WHERE answer_run_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (_uuid(answer_run_id),),
            )
            analysis_row = cursor.fetchone()
            runtime_answer_runs.append(
                RuntimeScoreSnapshotRun(
                    answer_run=answer_run,
                    analysis=_row_dict(analysis_row, ANSWER_ANALYSIS_READ_COLUMNS) if analysis_row else None,
                )
            )
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at ASC
            """,
            ("visibility_score_snapshot", snapshot_id),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeScoreSnapshot(
            snapshot=snapshot,
            contributions=contributions,
            answer_runs=tuple(runtime_answer_runs),
            audit_events=audit_events,
        )

    def _load_runtime_evidence_run(
        self,
        *,
        cursor: DbCursor,
        answer_run: dict[str, Any],
        answer_run_id: str,
    ) -> RuntimeEvidenceRun:
        cursor.execute(
            f"""
            SELECT {", ".join(RAW_ANSWER_COLUMNS)}
            FROM raw_answers
            WHERE answer_run_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (_uuid(answer_run_id),),
        )
        raw_answer_row = cursor.fetchone()
        cursor.execute(
            f"""
            SELECT {", ".join(CITATION_COLUMNS)}
            FROM answer_citations
            WHERE answer_run_id = %s
            ORDER BY position ASC, created_at ASC
            """,
            (_uuid(answer_run_id),),
        )
        citations = _rows_dict(cursor.fetchall(), CITATION_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(ASSET_COLUMNS)}
            FROM evidence_assets
            WHERE answer_run_id = %s
            ORDER BY asset_type ASC, created_at ASC
            """,
            (_uuid(answer_run_id),),
        )
        assets = _rows_dict(cursor.fetchall(), ASSET_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(COLLECTOR_LOG_COLUMNS)}
            FROM collector_logs
            WHERE answer_run_id = %s
            ORDER BY created_at ASC
            """,
            (_uuid(answer_run_id),),
        )
        logs = _rows_dict(cursor.fetchall(), COLLECTOR_LOG_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(COLLECTION_COST_COLUMNS)}
            FROM collection_costs
            WHERE answer_run_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (_uuid(answer_run_id),),
        )
        cost_row = cursor.fetchone()
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at ASC
            """,
            ("answer_run", answer_run_id),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeEvidenceRun(
            answer_run=answer_run,
            raw_answer=_row_dict(raw_answer_row, RAW_ANSWER_COLUMNS) if raw_answer_row else None,
            citations=citations,
            evidence_assets=assets,
            collector_logs=logs,
            collection_cost=_row_dict(cost_row, COLLECTION_COST_COLUMNS) if cost_row else None,
            audit_events=audit_events,
        )

    def save_project_bootstrap(self, bootstrap: ProjectBootstrap) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_profiles (id, market_code, payload)
                VALUES (%s, %s, %s)
                ON CONFLICT (market_code) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    _uuid(_stable_id("market-profile", bootstrap.market_profile.market_code)),
                    bootstrap.market_profile.market_code,
                    _json_payload(bootstrap.market_profile),
                ),
            )
            cursor.execute(
                """
                INSERT INTO industry_profiles (id, market_code, industry_code, payload)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    _uuid(
                        _stable_id(
                            "industry-profile",
                            bootstrap.industry_profile.market_code,
                            bootstrap.industry_profile.industry_code,
                        )
                    ),
                    bootstrap.industry_profile.market_code,
                    bootstrap.industry_profile.industry_code,
                    _json_payload(bootstrap.industry_profile),
                ),
            )
            cursor.execute(
                """
                INSERT INTO tenants (id, name, slug, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, slug = EXCLUDED.slug
                """,
                (
                    _uuid(bootstrap.tenant.id),
                    bootstrap.tenant.name,
                    bootstrap.tenant.slug,
                    _datetime(bootstrap.tenant.created_at),
                ),
            )
            cursor.execute(
                """
                INSERT INTO projects (
                  id, tenant_id, name, market_code, industry_code, target_brand, category,
                  prompt_version, status, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  name = EXCLUDED.name,
                  market_code = EXCLUDED.market_code,
                  industry_code = EXCLUDED.industry_code,
                  target_brand = EXCLUDED.target_brand,
                  category = EXCLUDED.category,
                  prompt_version = EXCLUDED.prompt_version,
                  status = EXCLUDED.status
                """,
                (
                    _uuid(bootstrap.project.id),
                    _uuid(bootstrap.project.tenant_id),
                    bootstrap.project.name,
                    bootstrap.project.market_code,
                    bootstrap.project.industry_code,
                    bootstrap.project.target_brand,
                    bootstrap.project.category,
                    bootstrap.project.prompt_version,
                    bootstrap.project.status,
                    _datetime(bootstrap.project.created_at),
                ),
            )
            for member in bootstrap.members:
                cursor.execute(
                    """
                    INSERT INTO project_members (id, project_id, user_id, role, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role
                    """,
                    (
                        _uuid(member.id),
                        _uuid(member.project_id),
                        member.user_id,
                        member.role,
                        _datetime(member.created_at),
                    ),
                )
            cursor.execute(
                """
                INSERT INTO brand_entities (
                  id, project_id, canonical_name, official_domains, parent_company, product_lines, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  canonical_name = EXCLUDED.canonical_name,
                  official_domains = EXCLUDED.official_domains,
                  parent_company = EXCLUDED.parent_company,
                  product_lines = EXCLUDED.product_lines,
                  status = EXCLUDED.status
                """,
                (
                    _uuid(bootstrap.brand.id),
                    _uuid(bootstrap.brand.project_id),
                    bootstrap.brand.canonical_name,
                    _json_payload(bootstrap.brand.official_domains),
                    bootstrap.brand.parent_company,
                    _json_payload(bootstrap.brand.product_lines),
                    bootstrap.brand.status,
                ),
            )
            for competitor in bootstrap.competitors:
                cursor.execute(
                    """
                    INSERT INTO competitor_entities (
                      id, project_id, canonical_name, official_domains, parent_company, product_lines, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      canonical_name = EXCLUDED.canonical_name,
                      official_domains = EXCLUDED.official_domains,
                      parent_company = EXCLUDED.parent_company,
                      product_lines = EXCLUDED.product_lines,
                      status = EXCLUDED.status
                    """,
                    (
                        _uuid(competitor.id),
                        _uuid(competitor.project_id),
                        competitor.canonical_name,
                        _json_payload(competitor.official_domains),
                        competitor.parent_company,
                        _json_payload(competitor.product_lines),
                        competitor.status,
                    ),
                )
            for prompt in bootstrap.prompt_questions:
                cursor.execute(
                    """
                    INSERT INTO prompt_questions (
                      id, project_id, market_code, industry_code, text, intent_type, city,
                      language, target_brand, competitors, priority, intent_weight,
                      prompt_version, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      text = EXCLUDED.text,
                      intent_type = EXCLUDED.intent_type,
                      city = EXCLUDED.city,
                      language = EXCLUDED.language,
                      target_brand = EXCLUDED.target_brand,
                      competitors = EXCLUDED.competitors,
                      priority = EXCLUDED.priority,
                      intent_weight = EXCLUDED.intent_weight,
                      prompt_version = EXCLUDED.prompt_version,
                      status = EXCLUDED.status
                    """,
                    (
                        _uuid(prompt.id),
                        _uuid(prompt.project_id),
                        prompt.market_code,
                        prompt.industry_code,
                        prompt.text,
                        prompt.intent_type,
                        prompt.city,
                        prompt.language,
                        prompt.target_brand,
                        _json_payload(prompt.competitors),
                        prompt.priority,
                        prompt.intent_weight,
                        prompt.prompt_version,
                        prompt.status,
                    ),
                )
            self.save_audit_events(bootstrap.audit_events, cursor=cursor)
        self.connection.commit()

    def save_raw_evidence_records(self, records: tuple[RawEvidenceRecord, ...]) -> None:
        with self.connection.cursor() as cursor:
            for record in records:
                cursor.execute(
                    """
                    INSERT INTO answer_runs (
                      id, project_id, prompt_question_id, platform, surface, access_method,
                      market_code, city, language, device, answer_present, surface_triggered,
                      sample_index, sample_size, model_or_surface, account_state,
                      collector_backend_id, collector_version, collected_at, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.answer_run.id),
                        _uuid(record.answer_run.project_id),
                        _uuid(record.answer_run.prompt_question_id),
                        record.answer_run.platform,
                        record.answer_run.surface,
                        record.answer_run.access_method,
                        record.answer_run.market_code,
                        record.answer_run.city,
                        record.answer_run.language,
                        record.answer_run.device,
                        record.answer_run.answer_present,
                        record.answer_run.surface_triggered,
                        record.answer_run.sample_index,
                        record.answer_run.sample_size,
                        record.answer_run.model_or_surface,
                        record.answer_run.account_state,
                        record.answer_run.collector_backend_id,
                        record.answer_run.collector_version,
                        _datetime(record.answer_run.collected_at),
                        record.answer_run.status,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO raw_answers (id, answer_run_id, answer_text, raw_payload, raw_payload_hash)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.raw_answer.id),
                        _uuid(record.raw_answer.answer_run_id),
                        record.raw_answer.answer_text,
                        _json_payload(record.raw_answer.raw_payload),
                        record.raw_answer.raw_payload_hash,
                    ),
                )
                for citation in record.citations:
                    cursor.execute(
                        """
                        INSERT INTO answer_citations (id, answer_run_id, url, domain, position, source_type)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(citation.id),
                            _uuid(citation.answer_run_id),
                            citation.url,
                            citation.domain,
                            citation.position,
                            citation.source_type,
                        ),
                    )
                for asset in record.evidence_assets:
                    cursor.execute(
                        """
                        INSERT INTO evidence_assets (id, answer_run_id, asset_type, url, content_hash)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(asset.id),
                            _uuid(asset.answer_run_id),
                            asset.asset_type,
                            asset.url,
                            asset.content_hash,
                        ),
                    )
                for log in record.collector_logs:
                    cursor.execute(
                        """
                        INSERT INTO collector_logs (
                          id, answer_run_id, collector_backend_id, event_type, payload, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(log.id),
                            _uuid(log.answer_run_id),
                            log.collector_backend_id,
                            log.event_type,
                            _json_payload(log.payload),
                            _datetime(log.created_at),
                        ),
                    )
                cursor.execute(
                    """
                    INSERT INTO collection_costs (
                      id, answer_run_id, project_id, collector_backend_id, llm_provider, llm_tokens,
                      llm_cost, proxy_or_vendor_cost, compute_cost, total_cost, duration_ms, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.collection_cost.id),
                        _uuid(record.collection_cost.answer_run_id),
                        _uuid(record.collection_cost.project_id),
                        record.collection_cost.collector_backend_id,
                        record.collection_cost.llm_provider,
                        record.collection_cost.llm_tokens,
                        record.collection_cost.llm_cost,
                        record.collection_cost.proxy_or_vendor_cost,
                        record.collection_cost.compute_cost,
                        record.collection_cost.total_cost,
                        record.collection_cost.duration_ms,
                        _datetime(record.collection_cost.created_at),
                    ),
                )
                self.save_audit_events(record.audit_events, cursor=cursor)
        self.connection.commit()

    def save_collection_failure_records(self, records: tuple[CollectionFailureRecord, ...]) -> None:
        with self.connection.cursor() as cursor:
            for record in records:
                cursor.execute(
                    """
                    INSERT INTO answer_runs (
                      id, project_id, prompt_question_id, platform, surface, access_method,
                      market_code, city, language, device, answer_present, surface_triggered,
                      sample_index, sample_size, model_or_surface, account_state,
                      collector_backend_id, collector_version, collected_at, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.answer_run.id),
                        _uuid(record.answer_run.project_id),
                        _uuid(record.answer_run.prompt_question_id),
                        record.answer_run.platform,
                        record.answer_run.surface,
                        record.answer_run.access_method,
                        record.answer_run.market_code,
                        record.answer_run.city,
                        record.answer_run.language,
                        record.answer_run.device,
                        record.answer_run.answer_present,
                        record.answer_run.surface_triggered,
                        record.answer_run.sample_index,
                        record.answer_run.sample_size,
                        record.answer_run.model_or_surface,
                        record.answer_run.account_state,
                        record.answer_run.collector_backend_id,
                        record.answer_run.collector_version,
                        _datetime(record.answer_run.collected_at),
                        record.answer_run.status,
                    ),
                )
                for log in record.collector_logs:
                    cursor.execute(
                        """
                        INSERT INTO collector_logs (
                          id, answer_run_id, collector_backend_id, event_type, payload, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(log.id),
                            _uuid(log.answer_run_id),
                            log.collector_backend_id,
                            log.event_type,
                            _json_payload(log.payload),
                            _datetime(log.created_at),
                        ),
                    )
                cursor.execute(
                    """
                    INSERT INTO collection_costs (
                      id, answer_run_id, project_id, collector_backend_id, llm_provider, llm_tokens,
                      llm_cost, proxy_or_vendor_cost, compute_cost, total_cost, duration_ms, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.collection_cost.id),
                        _uuid(record.collection_cost.answer_run_id),
                        _uuid(record.collection_cost.project_id),
                        record.collection_cost.collector_backend_id,
                        record.collection_cost.llm_provider,
                        record.collection_cost.llm_tokens,
                        record.collection_cost.llm_cost,
                        record.collection_cost.proxy_or_vendor_cost,
                        record.collection_cost.compute_cost,
                        record.collection_cost.total_cost,
                        record.collection_cost.duration_ms,
                        _datetime(record.collection_cost.created_at),
                    ),
                )
                self.save_audit_events(record.audit_events, cursor=cursor)
        self.connection.commit()

    def save_collection_run_summary(self, summary: CollectionRunSummary, audit_event: AuditEvent) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO collection_run_summaries (
                  id, project_id, run_type, mode, planned_runs, attempted_runs, success_count,
                  failure_count, success_rate, trigger_rate, answer_present_rate, total_cost,
                  average_cost_per_run, total_duration_ms, average_duration_ms,
                  collector_backend_ids, platform_distribution,
                  city_distribution, access_method_distribution, failure_summary, answer_run_ids,
                  started_at, completed_at, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(summary.id),
                    _uuid(summary.project_id),
                    summary.run_type,
                    summary.mode,
                    summary.planned_runs,
                    summary.attempted_runs,
                    summary.success_count,
                    summary.failure_count,
                    summary.success_rate,
                    summary.trigger_rate,
                    summary.answer_present_rate,
                    summary.total_cost,
                    summary.average_cost_per_run,
                    summary.total_duration_ms,
                    summary.average_duration_ms,
                    list(summary.collector_backend_ids),
                    _json_payload(summary.platform_distribution),
                    _json_payload(summary.city_distribution),
                    _json_payload(summary.access_method_distribution),
                    _json_payload(summary.failure_summary),
                    _uuid_array(summary.answer_run_ids),
                    _datetime(summary.started_at),
                    _datetime(summary.completed_at),
                    _datetime(summary.created_at),
                ),
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()

    def save_answer_analyses(self, analyses: tuple[AnswerAnalysis, ...]) -> None:
        with self.connection.cursor() as cursor:
            for analysis in analyses:
                cursor.execute(
                    """
                    INSERT INTO answer_analyses (
                      id, answer_run_id, parser_engine_id, analysis_version, payload, confidence
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      parser_engine_id = EXCLUDED.parser_engine_id,
                      analysis_version = EXCLUDED.analysis_version,
                      payload = EXCLUDED.payload,
                      confidence = EXCLUDED.confidence,
                      created_at = now()
                    """,
                    (
                        _uuid(analysis.id),
                        _uuid(analysis.answer_run_id),
                        analysis.parser_engine_id,
                        analysis.analysis_version,
                        _json_payload(analysis),
                        analysis.confidence,
                    ),
                )
                for call_log in _llm_call_logs_from_analysis(analysis):
                    cursor.execute(
                        """
                        INSERT INTO llm_call_logs (
                          id, project_id, answer_run_id, purpose, provider, model, prompt_version,
                          request_hash, response_hash, prompt_tokens, completion_tokens, total_tokens,
                          estimated_cost, latency_ms, status, error_message, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                          project_id = EXCLUDED.project_id,
                          answer_run_id = EXCLUDED.answer_run_id,
                          purpose = EXCLUDED.purpose,
                          provider = EXCLUDED.provider,
                          model = EXCLUDED.model,
                          prompt_version = EXCLUDED.prompt_version,
                          request_hash = EXCLUDED.request_hash,
                          response_hash = EXCLUDED.response_hash,
                          prompt_tokens = EXCLUDED.prompt_tokens,
                          completion_tokens = EXCLUDED.completion_tokens,
                          total_tokens = EXCLUDED.total_tokens,
                          estimated_cost = EXCLUDED.estimated_cost,
                          latency_ms = EXCLUDED.latency_ms,
                          status = EXCLUDED.status,
                          error_message = EXCLUDED.error_message,
                          created_at = EXCLUDED.created_at
                        """,
                        (
                            _uuid(str(call_log.get("id"))),
                            _uuid(str(call_log["project_id"])) if call_log.get("project_id") else None,
                            _uuid(str(call_log["answer_run_id"])) if call_log.get("answer_run_id") else None,
                            str(call_log.get("purpose") or "unknown"),
                            str(call_log.get("provider") or "unknown"),
                            str(call_log.get("model") or "unknown"),
                            str(call_log.get("prompt_version") or "unknown"),
                            str(call_log.get("request_hash") or ""),
                            str(call_log["response_hash"]) if call_log.get("response_hash") else None,
                            int(call_log.get("prompt_tokens") or 0),
                            int(call_log.get("completion_tokens") or 0),
                            int(call_log.get("total_tokens") or 0),
                            float(call_log.get("estimated_cost") or 0.0),
                            int(call_log.get("latency_ms") or 0),
                            str(call_log.get("status") or "unknown"),
                            str(call_log["error_message"]) if call_log.get("error_message") else None,
                            call_log.get("created_at"),
                        ),
                    )
        self.connection.commit()

    def save_score_snapshot(
        self,
        snapshot: VisibilityScoreSnapshot,
        contributions: tuple[ScoreContribution, ...],
        audit_event: AuditEvent,
    ) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO visibility_score_snapshots (
                  id, project_id, scope_type, scope_value, formula_version, platform_weights_snapshot,
                  final_score, trigger_rate, mention_rate, recommendation_rate, answer_run_ids,
                  created_at, dispersion, component_weights_snapshot
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(snapshot.id),
                    _uuid(snapshot.project_id),
                    snapshot.scope_type,
                    snapshot.scope_value,
                    snapshot.formula_version,
                    _json_payload(snapshot.platform_weights_snapshot),
                    snapshot.final_score,
                    snapshot.trigger_rate,
                    snapshot.mention_rate,
                    snapshot.recommendation_rate,
                    _uuid_array(snapshot.answer_run_ids),
                    _datetime(snapshot.created_at),
                    snapshot.dispersion,
                    _json_payload(snapshot.component_weights_snapshot),
                ),
            )
            for contribution in contributions:
                cursor.execute(
                    """
                    INSERT INTO score_contributions (
                      id, score_snapshot_id, component_name, component_score, weight,
                      weighted_contribution, denominator, evidence_answer_run_ids,
                      positive_evidence_summary, negative_evidence_summary, confidence_note,
                      created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(contribution.id),
                        _uuid(contribution.score_snapshot_id),
                        contribution.component_name,
                        contribution.component_score,
                        contribution.weight,
                        contribution.weighted_contribution,
                        contribution.denominator,
                        _uuid_array(contribution.evidence_answer_run_ids),
                        contribution.positive_evidence_summary,
                        contribution.negative_evidence_summary,
                        contribution.confidence_note,
                        _datetime(contribution.created_at),
                    ),
                )
                for answer_run_id in contribution.evidence_answer_run_ids:
                    cursor.execute(
                        """
                        INSERT INTO score_snapshot_runs (id, score_snapshot_id, answer_run_id, contribution_role)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(_stable_id("score-snapshot-run", snapshot.id, answer_run_id, contribution.component_name)),
                            _uuid(snapshot.id),
                            _uuid(answer_run_id),
                            contribution.component_name,
                        ),
                    )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()

    def save_citation_graph(self, project_id: str, graph: CitationGraphResult) -> None:
        with self.connection.cursor() as cursor:
            for node in graph.nodes:
                cursor.execute(
                    """
                    INSERT INTO source_graphs (
                      id, project_id, source_url, source_domain, source_type, topic,
                      source_gap_type, answer_run_ids, citation_count
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(node.id),
                        _uuid(node.project_id),
                        node.source_url,
                        node.source_domain,
                        node.source_type,
                        node.topic,
                        node.source_gap_type,
                        _uuid_array(node.answer_run_ids),
                        node.citation_count,
                    ),
                )
            for evidence in graph.evidence_links:
                cursor.execute(
                    """
                    INSERT INTO source_graph_evidence (
                      id, source_graph_id, answer_run_id, answer_citation_id, relation_type
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(evidence.id),
                        _uuid(evidence.source_graph_id),
                        _uuid(evidence.answer_run_id),
                        _uuid(evidence.answer_citation_id),
                        evidence.relation_type,
                    ),
                )
            for gap in graph.source_gaps:
                cursor.execute(
                    """
                    INSERT INTO source_gaps (
                      id, project_id, source_type, gap_type, observed_count,
                      expected_weight, recommendation
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (project_id, source_type, gap_type) DO UPDATE SET
                      observed_count = EXCLUDED.observed_count,
                      expected_weight = EXCLUDED.expected_weight,
                      recommendation = EXCLUDED.recommendation
                    """,
                    (
                        _uuid(_stable_id("source-gap", project_id, gap.source_type, gap.gap_type)),
                        _uuid(project_id),
                        gap.source_type,
                        gap.gap_type,
                        gap.observed_count,
                        gap.expected_weight,
                        gap.recommendation,
                    ),
                )
            for benchmark in graph.competitor_benchmarks:
                cursor.execute(
                    """
                    INSERT INTO competitor_benchmarks (
                      id, project_id, competitor_name, metric_scope, payload, answer_run_ids
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(benchmark.id),
                        _uuid(benchmark.project_id),
                        benchmark.competitor_name,
                        "project",
                        _json_payload(benchmark),
                        _uuid_array(benchmark.answer_run_ids),
                    ),
                )
        self.connection.commit()

    def save_report_export(self, report_export: ReportExport, audit_event: AuditEvent) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO report_exports (
                  id, project_id, market_code, report_version, report_type, score_snapshot_ids,
                  answer_run_ids, prompt_version, scoring_formula_version, platform_weights_snapshot,
                  method_disclosure, sample_size, window_start, window_end, methodology_hash, markdown_url, pdf_url,
                  csv_url, exported_by, exported_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(report_export.id),
                    _uuid(report_export.project_id),
                    report_export.market_code,
                    report_export.report_version,
                    report_export.report_type,
                    _uuid_array(report_export.score_snapshot_ids),
                    _uuid_array(report_export.answer_run_ids),
                    report_export.prompt_version,
                    report_export.scoring_formula_version,
                    _json_payload(report_export.platform_weights_snapshot),
                    _json_payload(report_export.method_disclosure),
                    report_export.sample_size,
                    _datetime(report_export.window_start),
                    _datetime(report_export.window_end),
                    report_export.methodology_hash,
                    report_export.markdown_url,
                    report_export.pdf_url,
                    report_export.csv_url,
                    report_export.exported_by,
                    _datetime(report_export.exported_at),
                ),
            )
            for answer_run_id in report_export.answer_run_ids:
                cursor.execute(
                    """
                    INSERT INTO report_evidence (id, report_export_id, answer_run_id, evidence_role)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(_stable_id("report-evidence", report_export.id, answer_run_id, "raw_evidence")),
                        _uuid(report_export.id),
                        _uuid(answer_run_id),
                        "raw_evidence",
                    ),
                )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()

    def save_action_plan(
        self,
        *,
        actions: tuple[ActionRecommendation, ...],
        schedule: RetestSchedule,
        comparison: RetestComparison | None,
        audit_events: tuple[AuditEvent, ...],
    ) -> None:
        with self.connection.cursor() as cursor:
            for action in actions:
                cursor.execute(
                    """
                    INSERT INTO action_recommendations (
                      id, project_id, title, description, priority, status, owner_id,
                      source_gap_type, evidence_answer_run_ids, related_source_types,
                      next_check_date, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(action.id),
                        _uuid(action.project_id),
                        action.title,
                        action.description,
                        action.priority,
                        action.status,
                        action.owner_id,
                        action.source_gap_type,
                        _uuid_array(action.evidence_answer_run_ids),
                        list(action.related_source_types),
                        _datetime(action.next_check_date),
                        _datetime(action.created_at),
                    ),
                )
            cursor.execute(
                """
                INSERT INTO retest_schedules (
                  id, project_id, prompt_version, sample_size, offsets_days,
                  scheduled_dates, answer_run_ids, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(schedule.id),
                    _uuid(schedule.project_id),
                    schedule.prompt_version,
                    schedule.sample_size,
                    list(schedule.offsets_days),
                    list(schedule.scheduled_dates),
                    _uuid_array(schedule.answer_run_ids),
                    _datetime(schedule.created_at),
                ),
            )
            if comparison:
                cursor.execute(
                    """
                    INSERT INTO retest_comparisons (
                      id, project_id, baseline_score, retest_score, score_delta,
                      baseline_answer_run_ids, retest_answer_run_ids, trend, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(comparison.id),
                        _uuid(comparison.project_id),
                        comparison.baseline_score,
                        comparison.retest_score,
                        comparison.score_delta,
                        _uuid_array(comparison.baseline_answer_run_ids),
                        _uuid_array(comparison.retest_answer_run_ids),
                        comparison.trend,
                        _datetime(comparison.created_at),
                    ),
                )
            self.save_audit_events(audit_events, cursor=cursor)
        self.connection.commit()

    def save_content_engine(
        self,
        *,
        facts: tuple[LocalizedKnowledgeFact, ...],
        drafts: tuple[ContentDraft, ...],
        connectors: tuple[IntegrationConnector, ...],
        distribution_records: tuple[ManualDistributionRecord, ...],
        audit_event: AuditEvent,
    ) -> None:
        with self.connection.cursor() as cursor:
            for fact in facts:
                cursor.execute(
                    """
                    INSERT INTO localized_knowledge_facts (
                      id, project_id, market_code, fact_type, subject, predicate, object_value,
                      city, evidence_source_id, confidence, status, valid_from, valid_until
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(fact.id),
                        _uuid(fact.project_id),
                        fact.market_code,
                        fact.fact_type,
                        fact.subject,
                        fact.predicate,
                        fact.object_value,
                        fact.city,
                        _uuid(fact.evidence_source_id),
                        fact.confidence,
                        fact.status,
                        _datetime(fact.valid_from),
                        _datetime(fact.valid_until),
                    ),
                )
            for draft in drafts:
                cursor.execute(
                    """
                    INSERT INTO content_drafts (
                      id, project_id, title, content_type, content_template_id, target_question_ids,
                      target_city, target_platform, target_source_type, used_knowledge_fact_ids,
                      source_gap_types, source_action_id, evidence_answer_run_ids,
                      draft_markdown, review_status, created_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(draft.id),
                        _uuid(draft.project_id),
                        draft.title,
                        draft.content_type,
                        draft.content_template_id,
                        _uuid_array(draft.target_question_ids),
                        draft.target_city,
                        draft.target_platform,
                        draft.target_source_type,
                        _uuid_array(draft.used_knowledge_fact_ids),
                        list(draft.source_gap_types),
                        _uuid(draft.source_action_id),
                        _uuid_array(draft.evidence_answer_run_ids),
                        draft.draft_markdown,
                        draft.review_status,
                        draft.created_by,
                        _datetime(draft.created_at),
                    ),
                )
            for connector in connectors:
                cursor.execute(
                    """
                    INSERT INTO integration_connectors (
                      id, project_id, provider, connection_status, capabilities, auth_mode, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(connector.id),
                        _uuid(connector.project_id),
                        connector.provider,
                        connector.connection_status,
                        list(connector.capabilities),
                        connector.auth_mode,
                        _datetime(connector.created_at),
                    ),
                )
            for record in distribution_records:
                cursor.execute(
                    """
                    INSERT INTO manual_distribution_records (
                      id, project_id, content_draft_id, platform, target_url, status,
                      submitted_at, checked_at, notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.id),
                        _uuid(record.project_id),
                        _uuid(record.content_draft_id),
                        record.platform,
                        record.target_url,
                        record.status,
                        _datetime(record.submitted_at),
                        _datetime(record.checked_at),
                        record.notes,
                    ),
                )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()

    def save_traceability_bundle(self, bundle: TraceabilityBundle) -> None:
        with self.connection.cursor() as cursor:
            for link in bundle.evidence_links:
                cursor.execute(
                    """
                    INSERT INTO evidence_links (
                      id, project_id, source_type, source_id, target_type, target_id,
                      relation_type, answer_run_ids
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(link.id),
                        _uuid(link.project_id),
                        link.source_type,
                        _uuid(link.source_id),
                        link.target_type,
                        _uuid(link.target_id),
                        link.relation_type,
                        _uuid_array(link.answer_run_ids),
                    ),
                )
            cursor.execute(
                """
                INSERT INTO traceability_bundles (
                  id, project_id, subject_type, subject_id, report_export_ids,
                  score_snapshot_ids, score_contribution_ids, answer_run_ids, raw_answer_ids,
                  answer_citation_ids, evidence_asset_ids, source_graph_ids, source_gap_types,
                  action_recommendation_ids, content_draft_ids, audit_event_ids,
                  explanation_summary
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(bundle.id),
                    _uuid(bundle.project_id),
                    bundle.subject_type,
                    _uuid(bundle.subject_id),
                    _uuid_array(bundle.report_export_ids),
                    _uuid_array(bundle.score_snapshot_ids),
                    _uuid_array(bundle.score_contribution_ids),
                    _uuid_array(bundle.answer_run_ids),
                    _uuid_array(bundle.raw_answer_ids),
                    _uuid_array(bundle.answer_citation_ids),
                    _uuid_array(bundle.evidence_asset_ids),
                    _uuid_array(bundle.source_graph_ids),
                    list(bundle.source_gap_types),
                    _uuid_array(bundle.action_recommendation_ids),
                    _uuid_array(bundle.content_draft_ids),
                    _uuid_array(bundle.audit_event_ids),
                    bundle.explanation_summary,
                ),
            )
        self.connection.commit()

    def save_audit_events(self, events: tuple[AuditEvent, ...], *, cursor: DbCursor | None = None) -> None:
        owns_cursor = cursor is None
        if cursor is None:
            cursor = self.connection.cursor().__enter__()
        try:
            for event in events:
                cursor.execute(
                    """
                    INSERT INTO audit_events (
                      id, event_type, project_id, actor_type, actor_id, target_type, target_id,
                      before_hash, after_hash, input_refs, output_refs, method_version, reason,
                      created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(event.id),
                        event.event_type,
                        _uuid(event.project_id),
                        event.actor_type,
                        event.actor_id,
                        event.target_type,
                        event.target_id,
                        event.before_hash,
                        event.after_hash,
                        _json_payload(event.input_refs),
                        _json_payload(event.output_refs),
                        event.method_version,
                        event.reason,
                        _datetime(event.created_at),
                    ),
                )
        finally:
            if owns_cursor:
                assert cursor is not None
                cursor.__exit__(None, None, None)
                self.connection.commit()
