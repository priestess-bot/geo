from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from geno_core.action_plan import (
    build_action_plan_audit_event,
    build_action_recommendations,
    build_retest_comparison_audit_event,
    build_retest_schedule,
    compare_retest_windows,
)
from geno_core.analysis_pipeline import analyze_and_score_records
from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import run_collection_slice
from geno_core.collectors import (
    FixtureGoogleAIModeCollector,
    FixtureGoogleAIOCollector,
    FixtureOpenAIWebSearchCollector,
    FixturePerplexitySonarCollector,
    OpenAIWebSearchCollector,
    PerplexitySonarCollector,
)
from geno_core.contracts import CollectorBackend
from geno_core.graph import build_citation_graph
from geno_core.google_spike import (
    build_google_spike_plan,
    evaluate_google_spike_gate,
    select_google_spike_prompts,
)
from geno_core.models import CollectionFailureRecord, ProjectBootstrap, RawEvidenceRecord
from geno_core.report import MarkdownCsvReportExporter
from geno_core.runtime import RuntimePersistenceError, build_repository_from_env


def _collectors(mode: str) -> tuple[CollectorBackend, ...]:
    if mode == "fixture":
        return (FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector())
    if mode == "api":
        return (PerplexitySonarCollector(), OpenAIWebSearchCollector())
    if mode == "google-fixture":
        return (FixtureGoogleAIOCollector(), FixtureGoogleAIModeCollector())
    raise ValueError(f"Unsupported collector mode: {mode}")


def _persist_records(
    *,
    bootstrap: ProjectBootstrap,
    successes: tuple[RawEvidenceRecord, ...],
    failures: tuple[CollectionFailureRecord, ...],
    persist_analysis: bool,
) -> dict[str, object]:
    repository = build_repository_from_env()
    repository.save_project_bootstrap(bootstrap)
    if successes:
        repository.save_raw_evidence_records(successes)
    if failures:
        repository.save_collection_failure_records(failures)
    analysis_summary: dict[str, object] = {"enabled": False}
    if persist_analysis and successes:
        platform_weights_snapshot = {
            item.platform: item.weight
            for item in bootstrap.market_profile.platforms
            if item.enabled and item.platform in {"chatgpt", "perplexity"}
        }
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=successes,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot=platform_weights_snapshot,
            scope_type="collection_slice",
            scope_value="worker_runtime",
        )
        repository.save_answer_analyses(analysis_result.analyses)
        repository.save_score_snapshot(
            analysis_result.snapshot,
            analysis_result.contributions,
            analysis_result.audit_event,
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=successes,
            analyses=analysis_result.analyses,
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        repository.save_citation_graph(bootstrap.project.id, graph)
        report = MarkdownCsvReportExporter().export(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            report_version="worker-runtime-v1",
            report_type="worker_runtime",
            prompt_version=bootstrap.project.prompt_version,
            snapshot=analysis_result.snapshot,
            contributions=analysis_result.contributions,
            records=successes,
            graph=graph,
            platform_weights_snapshot=platform_weights_snapshot,
        )
        repository.save_report_export(report.report_export, report.audit_event)
        actions = build_action_recommendations(
            project_id=bootstrap.project.id,
            graph=graph,
            snapshot=analysis_result.snapshot,
        )
        schedule = build_retest_schedule(
            project_id=bootstrap.project.id,
            prompt_version=bootstrap.project.prompt_version,
            sample_size=successes[0].answer_run.sample_size,
            answer_run_ids=tuple(record.answer_run.id for record in successes),
        )
        action_audit = build_action_plan_audit_event(
            project_id=bootstrap.project.id,
            actions=actions,
            schedule=schedule,
        )
        retest_snapshot = analysis_result.snapshot.__class__(
            **{
                **asdict(analysis_result.snapshot),
                "id": f"retest-{analysis_result.snapshot.id}",
                "final_score": round(analysis_result.snapshot.final_score + 2.5, 4),
            }
        )
        comparison = compare_retest_windows(
            project_id=bootstrap.project.id,
            baseline=analysis_result.snapshot,
            retest=retest_snapshot,
        )
        comparison_audit = build_retest_comparison_audit_event(
            project_id=bootstrap.project.id,
            comparison=comparison,
        )
        repository.save_action_plan(
            actions=actions,
            schedule=schedule,
            comparison=comparison,
            audit_events=(action_audit, comparison_audit),
        )
        analysis_summary = {
            "enabled": True,
            "analysis_count": len(analysis_result.analyses),
            "score_snapshot_id": analysis_result.snapshot.id,
            "score_contributions": len(analysis_result.contributions),
            "final_score": analysis_result.snapshot.final_score,
            "source_graph_nodes": len(graph.nodes),
            "source_graph_evidence": len(graph.evidence_links),
            "source_gaps": len(graph.source_gaps),
            "competitor_benchmarks": len(graph.competitor_benchmarks),
            "report_export_id": report.report_export.id,
            "report_evidence_answer_runs": len(report.report_evidence_answer_run_ids),
            "action_recommendations": len(actions),
            "retest_schedule_id": schedule.id,
            "retest_comparison_id": comparison.id,
            "retest_trend": comparison.trend,
        }
    elif persist_analysis:
        analysis_summary = {
            "enabled": True,
            "analysis_count": 0,
            "score_contributions": 0,
            "reason": "no_successful_records",
        }
    return {
        "enabled": True,
        "project_bootstrap": True,
        "tenant_id": bootstrap.tenant.id,
        "project_id": bootstrap.project.id,
        "prompt_questions": len(bootstrap.prompt_questions),
        "competitors": len(bootstrap.competitors),
        "raw_evidence_records": len(successes),
        "collection_failure_records": len(failures),
        "analysis": analysis_summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a small AU P0a collection slice")
    parser.add_argument("--mode", choices=["fixture", "api", "google-fixture"], default="fixture")
    parser.add_argument("--prompt-limit", type=int, default=2)
    parser.add_argument("--sample-size", type=int, default=1)
    parser.add_argument("--cities", default="Australia,Sydney")
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist successful and failed collection records through DATABASE_URL",
    )
    parser.add_argument(
        "--persist-analysis",
        action="store_true",
        help="After --persist, parse successful records and persist score snapshot/contributions",
    )
    args = parser.parse_args()
    if args.persist_analysis and not args.persist:
        parser.error("--persist-analysis requires --persist")

    bootstrap = build_au_project_bootstrap()
    prompts = bootstrap.prompt_questions
    cities = tuple(city.strip() for city in args.cities.split(",") if city.strip())
    if args.mode == "google-fixture":
        plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        prompts = select_google_spike_prompts(bootstrap.prompt_questions)
        cities = plan.geo_cities
        args.sample_size = plan.sample_size
        args.prompt_limit = plan.prompt_count
    else:
        plan = None
    records = run_collection_slice(
        project_id=bootstrap.project.id,
        prompts=prompts,
        market_profile=bootstrap.market_profile,
        collectors=_collectors(args.mode),
        cities=cities,
        sample_size=args.sample_size,
        prompt_limit=args.prompt_limit,
    )
    successes = tuple(record for record in records if isinstance(record, RawEvidenceRecord))
    failures = tuple(record for record in records if isinstance(record, CollectionFailureRecord))
    persistence: dict[str, object] = {"enabled": False}
    if args.persist:
        try:
            persistence = _persist_records(
                bootstrap=bootstrap,
                successes=successes,
                failures=failures,
                persist_analysis=args.persist_analysis,
            )
        except RuntimePersistenceError as exc:
            print(f"persistence_error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    output = {
        "mode": args.mode,
        "record_count": len(records),
        "success_count": len(successes),
        "failure_count": len(failures),
        "answer_run_ids": [record.answer_run.id for record in records],
        "failure_events": [asdict(record) for record in failures],
        "persistence": persistence,
    }
    if plan is not None:
        output["google_spike_gate"] = asdict(
            evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=plan, records=records)
        )
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
