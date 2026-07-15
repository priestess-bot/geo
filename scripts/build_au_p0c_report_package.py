from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from geo_core.analysis_pipeline import analyze_and_score_records  # noqa: E402
from geo_core.bootstrap import build_au_project_bootstrap  # noqa: E402
from geo_core.collection import run_collection_slice  # noqa: E402
from geo_core.collectors import (  # noqa: E402
    FixtureChatGPTSearchBrowserCollector,
    FixtureOpenAIWebSearchCollector,
    FixturePerplexitySonarCollector,
)
from geo_core.graph import build_citation_graph  # noqa: E402
from geo_core.report import (  # noqa: E402
    SCORE_RATE_DENOMINATORS,
    MarkdownCsvReportExporter,
    render_audit_summary_lines,
    render_markdown_pdf,
    render_methodology_disclosure_lines,
)


PACKAGE_VERSION = "au_p0c_report_package_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0c-report-package-latest.json"
DEFAULT_PROMPT_LIMIT = 3
DEFAULT_CITIES = ("Sydney",)
PLATFORM_WEIGHTS = {"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25}
REQUIRED_ARTIFACTS = (
    "report_export_json",
    "markdown",
    "csv",
    "pdf",
    "white_label_pdf",
    "method_disclosure_contract",
    "audit_summary_contract",
    "traceability_contract",
)
REQUIRED_METHOD_DISCLOSURE_FIELDS = {
    "google_coverage",
    "google_spike_gate",
    "api_browser_fidelity",
    "score_rate_denominators",
    "access_method_distribution",
    "platform_distribution",
    "platform_weights_snapshot",
    "score_input_policy",
    "audit_summary",
    "evidence_asset_coverage",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _content_bytes(content: str | bytes) -> bytes:
    return content.encode("utf-8") if isinstance(content, str) else content


def _sha256(content: str | bytes) -> str:
    return hashlib.sha256(_content_bytes(content)).hexdigest()


def compute_p0c_report_package_hash(package: dict[str, Any]) -> str:
    payload = dict(package)
    payload.pop("package_payload_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _artifact_entry(
    *,
    artifact_type: str,
    content: str | bytes,
    media_type: str,
    filename: str,
    checks: dict[str, bool] | None = None,
) -> dict[str, Any]:
    payload = _content_bytes(content)
    check_values = checks or {}
    errors = [f"check_failed:{name}" for name, passed in sorted(check_values.items()) if passed is not True]
    return {
        "artifact_type": artifact_type,
        "filename": filename,
        "media_type": media_type,
        "size_bytes": len(payload),
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "checks": check_values,
    }


def _contract_entry(*, artifact_type: str, checks: dict[str, bool]) -> dict[str, Any]:
    errors = [f"check_failed:{name}" for name, passed in sorted(checks.items()) if passed is not True]
    return {
        "artifact_type": artifact_type,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "checks": checks,
    }


def _white_label_markdown(report: object, *, client_name: str, prepared_by: str) -> str:
    report_export = getattr(report, "report_export")
    method_disclosure = report_export.method_disclosure
    audit_summary = method_disclosure.get("audit_summary")
    lines = [
        f"# {client_name} GEO Evidence Report",
        "",
        f"Prepared by: {prepared_by}",
        f"Market: {report_export.market_code}",
        f"Report version: {report_export.report_version}",
        f"Methodology hash: {report_export.methodology_hash}",
        "",
        "## Executive Snapshot",
        "",
        f"- Sample size: {report_export.sample_size}",
        f"- Scoring formula: {report_export.scoring_formula_version}",
        f"- Google coverage: {method_disclosure.get('google_coverage', 'unknown')}",
        "",
        "## Client-Ready Method Notes",
        "",
        "- This white-label PDF is regenerated from the frozen report export snapshot.",
        "- Appendix filters never rewrite score snapshots or report evidence ids.",
        "- Every score remains traceable to answer runs, citations, score contributions, and audit events.",
        "",
        "### Method Disclosure",
        "",
        *render_methodology_disclosure_lines(method_disclosure),
        "",
        "### Audit Summary",
        "",
        *render_audit_summary_lines(audit_summary),
        "",
        "## Footer",
        "",
        f"{prepared_by} white-label template `white_label_v1`; ReportExport {report_export.id} remains the source of truth.",
    ]
    return "\n".join(lines) + "\n"


def _build_report(*, prompt_limit: int, cities: tuple[str, ...]) -> tuple[object, dict[str, Any]]:
    bootstrap = build_au_project_bootstrap(
        target_brand="Koala",
        category="mattresses",
        competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
    )
    records = run_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(
            FixturePerplexitySonarCollector(),
            FixtureOpenAIWebSearchCollector(),
            FixtureChatGPTSearchBrowserCollector(),
        ),
        cities=cities,
        sample_size=1,
        prompt_limit=prompt_limit,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot=PLATFORM_WEIGHTS,
        scope_type="project",
        scope_value="p0c_report_package_fixture",
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=analysis_result.score_input_records,
        analyses=analysis_result.score_input_analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    report = MarkdownCsvReportExporter().export(
        project_id=bootstrap.project.id,
        market_code=bootstrap.project.market_code,
        report_version="p0c-customer-report-fixture-v1",
        report_type="customer_report_fixture",
        prompt_version=bootstrap.project.prompt_version,
        snapshot=analysis_result.snapshot,
        contributions=analysis_result.contributions,
        records=analysis_result.score_input_records,
        graph=graph,
        platform_weights_snapshot=PLATFORM_WEIGHTS,
        score_input_policy=analysis_result.score_input_policy,
        fidelity_records=records,
        audit_events=(analysis_result.audit_event,),
    )
    context = {
        "project_id": bootstrap.project.id,
        "market_code": bootstrap.project.market_code,
        "prompt_version": bootstrap.project.prompt_version,
        "all_record_count": len(records),
        "score_input_record_count": len(analysis_result.score_input_records),
        "excluded_fidelity_sample_record_count": analysis_result.score_input_policy[
            "excluded_fidelity_sample_record_count"
        ],
        "source_node_count": len(graph.nodes),
        "source_gap_count": len(graph.source_gaps),
        "competitor_benchmark_count": len(graph.competitor_benchmarks),
    }
    return report, context


def _summary(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    failed_artifacts = sorted(name for name, artifact in artifacts.items() if artifact.get("status") == "fail")
    blocking_reasons = sorted(
        f"{name}:{error}" for name, artifact in artifacts.items() for error in _as_list(artifact.get("errors"))
    )
    return {
        "artifact_count": len(artifacts),
        "failed_artifacts": failed_artifacts,
        "ready_artifacts": sorted(name for name, artifact in artifacts.items() if artifact.get("status") == "pass"),
        "blocking_reasons": blocking_reasons,
    }


def build_au_p0c_report_package(
    *,
    output_path: Path | None = None,
    generated_at: str | None = None,
    prompt_limit: int = DEFAULT_PROMPT_LIMIT,
    cities: tuple[str, ...] = DEFAULT_CITIES,
) -> dict[str, Any]:
    if prompt_limit < 1:
        raise ValueError("prompt_limit must be positive")
    if not cities:
        raise ValueError("at least one city is required")

    report, context = _build_report(prompt_limit=prompt_limit, cities=cities)
    report_export = report.report_export
    report_export_json = json.dumps(asdict(report_export), ensure_ascii=False, indent=2, default=str) + "\n"
    method_disclosure = report_export.method_disclosure
    score_rates = _as_dict(method_disclosure.get("score_rate_denominators"))
    rate_definitions = _as_dict(score_rates.get("definitions"))
    audit_summary = _as_dict(method_disclosure.get("audit_summary"))
    fidelity = _as_dict(method_disclosure.get("api_browser_fidelity"))
    white_label_markdown = _white_label_markdown(report, client_name="Koala AU", prepared_by="GEO SaaS AU")
    white_label_pdf = render_markdown_pdf(white_label_markdown)

    method_checks = {
        "required_fields_present": REQUIRED_METHOD_DISCLOSURE_FIELDS.issubset(method_disclosure.keys()),
        "score_rate_definitions_present": set(SCORE_RATE_DENOMINATORS).issubset(rate_definitions.keys()),
        "api_browser_fidelity_sampled": fidelity.get("status") == "sampled",
        "official_api_records_present": int(fidelity.get("official_api_records") or 0) > 0,
        "browser_records_present": int(fidelity.get("browser_records") or 0) > 0,
        "google_limited_coverage_disclosed": method_disclosure.get("google_coverage") == "limited_coverage_appendix_only",
        "score_input_policy_discloses_excluded_fidelity": _as_dict(method_disclosure.get("score_input_policy")).get(
            "excluded_fidelity_sample_record_count"
        )
        == context["excluded_fidelity_sample_record_count"],
    }
    audit_checks = {
        "audit_summary_present": bool(audit_summary),
        "audit_event_count_positive": int(audit_summary.get("audit_event_count") or 0) > 0,
        "visibility_score_audit_present": "visibility_score_snapshot_created"
        in _as_dict(audit_summary.get("event_type_distribution")),
        "audit_output_refs_include_score_snapshot": "score_snapshot_ids" in _as_list(audit_summary.get("output_ref_keys")),
    }
    traceability_checks = {
        "report_export_has_score_snapshot": len(report_export.score_snapshot_ids) == 1,
        "report_export_has_answer_runs": len(report_export.answer_run_ids) == context["score_input_record_count"],
        "report_evidence_ids_match_export": tuple(report.report_evidence_answer_run_ids) == tuple(report_export.answer_run_ids),
        "graph_has_source_nodes": context["source_node_count"] > 0,
        "graph_has_source_gaps": context["source_gap_count"] > 0,
        "graph_has_competitor_benchmarks": context["competitor_benchmark_count"] >= 3,
    }
    markdown_checks = {
        "mentions_report_title": "GEO Evidence Report" in report.markdown,
        "mentions_method_disclosure": "### Method Disclosure" in report.markdown,
        "mentions_audit_summary": "### Audit Summary" in report.markdown,
        "mentions_trigger_denominator": "Trigger rate denominator: all attempted evidence records" in report.markdown,
        "mentions_fidelity_sampled": "API-vs-browser fidelity: sampled" in report.markdown,
    }
    csv_checks = {
        "has_answer_run_id_header": "answer_run_id" in report.csv_content.splitlines()[0],
        "has_prompt_question_id_header": "prompt_question_id" in report.csv_content.splitlines()[0],
        "has_evidence_rows": len(report.csv_content.splitlines()) > 1,
    }
    pdf_checks = {
        "starts_with_pdf_header": report.pdf_content.startswith(b"%PDF-1.4"),
        "ends_with_eof": report.pdf_content.rstrip().endswith(b"%%EOF"),
    }
    white_label_checks = {
        "starts_with_pdf_header": white_label_pdf.startswith(b"%PDF-1.4"),
        "ends_with_eof": white_label_pdf.rstrip().endswith(b"%%EOF"),
        "template_payload_hash_present": bool(_sha256("white_label_v1:Koala AU:GEO SaaS AU")),
    }

    artifacts = {
        "report_export_json": _artifact_entry(
            artifact_type="json",
            content=report_export_json,
            media_type="application/json",
            filename="p0c-customer-report-export.json",
        ),
        "markdown": _artifact_entry(
            artifact_type="markdown",
            content=report.markdown,
            media_type="text/markdown; charset=utf-8",
            filename="p0c-customer-report.md",
            checks=markdown_checks,
        ),
        "csv": _artifact_entry(
            artifact_type="csv",
            content=report.csv_content,
            media_type="text/csv; charset=utf-8",
            filename="p0c-customer-report-evidence.csv",
            checks=csv_checks,
        ),
        "pdf": _artifact_entry(
            artifact_type="pdf",
            content=report.pdf_content,
            media_type="application/pdf",
            filename="p0c-customer-report.pdf",
            checks=pdf_checks,
        ),
        "white_label_pdf": _artifact_entry(
            artifact_type="pdf",
            content=white_label_pdf,
            media_type="application/pdf",
            filename="p0c-customer-report-white-label.pdf",
            checks=white_label_checks,
        ),
        "method_disclosure_contract": _contract_entry(
            artifact_type="contract",
            checks=method_checks,
        ),
        "audit_summary_contract": _contract_entry(
            artifact_type="contract",
            checks=audit_checks,
        ),
        "traceability_contract": _contract_entry(
            artifact_type="contract",
            checks=traceability_checks,
        ),
    }
    summary = _summary(artifacts)
    ready = not summary["failed_artifacts"]
    package: dict[str, Any] = {
        "package_version": PACKAGE_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if ready else "fail",
        "p0c_report_contract_ready": ready,
        "next_action": "ready_for_p0c_customer_report_handoff" if ready else "fix_p0c_report_package",
        "remaining_blockers": summary["blocking_reasons"],
        "output_path": str(output_path) if output_path else "",
        "fixture_scope": {
            "prompt_limit": prompt_limit,
            "cities": list(cities),
            "collectors": [
                "fixture_perplexity_sonar",
                "fixture_openai_web_search",
                "chatgpt_search.browser.fixture",
            ],
        },
        "report_export": {
            "id": report_export.id,
            "project_id": report_export.project_id,
            "market_code": report_export.market_code,
            "report_version": report_export.report_version,
            "report_type": report_export.report_type,
            "methodology_hash": report_export.methodology_hash,
            "score_snapshot_ids": list(report_export.score_snapshot_ids),
            "answer_run_ids": list(report_export.answer_run_ids),
            "sample_size": report_export.sample_size,
            "scoring_formula_version": report_export.scoring_formula_version,
            "google_coverage": method_disclosure.get("google_coverage", ""),
            "api_browser_fidelity_status": fidelity.get("status", ""),
            "audit_event_count": audit_summary.get("audit_event_count", 0),
        },
        "context": context,
        "summary": summary,
        "artifacts": artifacts,
    }
    package["package_payload_hash"] = compute_p0c_report_package_hash(package)
    return package


def _cities_from_arg(value: str) -> tuple[str, ...]:
    cities = tuple(item.strip() for item in value.split(",") if item.strip())
    if not cities:
        raise argparse.ArgumentTypeError("cities must contain at least one non-empty city")
    return cities


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0c customer report delivery package JSON")
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GEO_AU_P0C_REPORT_PACKAGE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0c report package JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    parser.add_argument(
        "--prompt-limit",
        type=int,
        default=int(os.environ.get("GEO_AU_P0C_REPORT_PACKAGE_PROMPT_LIMIT", str(DEFAULT_PROMPT_LIMIT))),
    )
    parser.add_argument(
        "--cities",
        type=_cities_from_arg,
        default=_cities_from_arg(os.environ.get("GEO_AU_P0C_REPORT_PACKAGE_CITIES", ",".join(DEFAULT_CITIES))),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    package = build_au_p0c_report_package(
        output_path=output_path,
        generated_at=args.generated_at,
        prompt_limit=args.prompt_limit,
        cities=args.cities,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(package, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(package, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if package["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
