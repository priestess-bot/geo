from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from geno_core.audit import build_audit_event
from geno_core.action_plan import (
    build_action_plan_audit_event,
    build_action_recommendations,
    build_retest_comparison_audit_event,
    build_retest_schedule,
    compare_retest_windows,
)
from geno_core.analysis_pipeline import analyze_and_score_records, build_score_input_policy, select_score_input_records
from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import (
    build_collection_run_audit_event,
    build_collection_run_summary,
    run_collection_slice,
    evaluate_p0a_collection_readiness,
)
from geno_core.collectors import (
    FixtureChatGPTSearchBrowserCollector,
    FixtureGoogleAIModeCollector,
    FixtureGoogleAIOCollector,
    FixtureOpenAIWebSearchCollector,
    FixturePerplexitySonarCollector,
    OpenAIWebSearchCollector,
    PerplexitySonarCollector,
    PlaywrightChatGPTSearchCollector,
)
from geno_core.contracts import CollectorBackend
from geno_core.graph import build_citation_graph
from geno_core.fidelity import build_runtime_fidelity_check_from_records
from geno_core.fidelity_schedule import build_browser_fidelity_sampling_plan
from geno_core.google_spike import (
    build_google_spike_plan,
    evaluate_google_spike_gate,
    evaluate_google_spike_readiness_gate,
    select_google_spike_prompts,
)
from geno_core.llm_gateway import LiteLLMGateway
from geno_core.models import CollectionFailureRecord, ProjectBootstrap, PromptQuestion, RawEvidenceRecord
from geno_core.object_store import (
    archive_api_snapshot_assets,
    archive_browser_capture_assets,
    archive_report_artifacts,
)
from geno_core.parser import ComparativeAnswerParser, LLMJudgeAnswerParser
from geno_core.knowledge import (
    build_content_drafts,
    build_content_engine_audit_event,
    build_integration_connectors,
    build_localized_knowledge_facts,
    build_manual_distribution_records,
    search_knowledge_facts,
)
from geno_core.report import MarkdownCsvReportExporter
from geno_core.runtime import RuntimePersistenceError, build_object_store_from_env, build_repository_from_env
from geno_core.traceability import build_traceability_bundle


def _collectors(mode: str) -> tuple[CollectorBackend, ...]:
    if mode == "fixture":
        return (FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector())
    if mode == "api":
        return (PerplexitySonarCollector(), OpenAIWebSearchCollector())
    if mode == "google-fixture":
        return (FixtureGoogleAIOCollector(), FixtureGoogleAIModeCollector())
    raise ValueError(f"Unsupported collector mode: {mode}")


def _fidelity_fixture_collectors(mode: str) -> tuple[CollectorBackend, ...]:
    if mode == "fixture":
        return (FixtureChatGPTSearchBrowserCollector(),)
    return ()


def _fidelity_playwright_collectors(mode: str) -> tuple[CollectorBackend, ...]:
    if mode == "api":
        return (PlaywrightChatGPTSearchCollector(),)
    return ()


def _collector_health_report(collectors: tuple[CollectorBackend, ...]) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "collector_backend_id": collector.id(),
            "health": collector.health(),
            "capabilities": collector.capabilities(),
        }
        for collector in collectors
    )


def _collector_health_failure_reasons(collector_health: tuple[dict[str, object], ...]) -> tuple[str, ...]:
    ready_statuses = {"ready", "fixture_ready"}
    return tuple(
        f"{item['collector_backend_id']}:{item['health']}"
        for item in collector_health
        if item["health"] not in ready_statuses
    )


def _analysis_parser(*, judge_gateway: str, judge_model: str) -> ComparativeAnswerParser:
    if judge_gateway == "fixture":
        return ComparativeAnswerParser()
    if judge_gateway == "litellm":
        return ComparativeAnswerParser(
            judge_parser=LLMJudgeAnswerParser(
                model=judge_model,
                gateway=LiteLLMGateway(),
            )
        )
    raise ValueError(f"Unsupported judge gateway: {judge_gateway}")


def _filter_prompts_by_ids(
    prompts: tuple[PromptQuestion, ...],
    prompt_ids_csv: str | None,
) -> tuple[PromptQuestion, ...]:
    if not prompt_ids_csv:
        return prompts
    requested_ids = tuple(item.strip() for item in prompt_ids_csv.split(",") if item.strip())
    if not requested_ids:
        return prompts
    prompt_by_id = {str(getattr(prompt, "id")): prompt for prompt in prompts}
    missing = tuple(prompt_id for prompt_id in requested_ids if prompt_id not in prompt_by_id)
    if missing:
        raise ValueError(f"Unknown prompt ids: {', '.join(missing)}")
    return tuple(prompt_by_id[prompt_id] for prompt_id in requested_ids)


def _default_market_run_date(bootstrap: ProjectBootstrap) -> date:
    try:
        return datetime.now(ZoneInfo(bootstrap.market_profile.timezone)).date()
    except ZoneInfoNotFoundError:
        return datetime.now().date()


def _persist_records(
    *,
    bootstrap: ProjectBootstrap,
    mode: str,
    run_type: str,
    planned_runs: int,
    records: tuple[RawEvidenceRecord | CollectionFailureRecord, ...],
    successes: tuple[RawEvidenceRecord, ...],
    failures: tuple[CollectionFailureRecord, ...],
    persist_analysis: bool,
    score_formula_version: str,
    judge_gateway: str,
    judge_model: str,
) -> dict[str, object]:
    repository = build_repository_from_env()
    repository.save_project_bootstrap(bootstrap)
    snapshot_archive_summary: dict[str, object] = {
        "enabled": False,
        "reason": "OBJECT_STORE_ENDPOINT not configured",
    }
    browser_archive_summary: dict[str, object] = {
        "enabled": False,
        "reason": "OBJECT_STORE_ENDPOINT not configured",
    }
    snapshot_archive_audit = None
    browser_archive_audit = None
    if successes and os.environ.get("OBJECT_STORE_ENDPOINT", "").strip():
        object_store = build_object_store_from_env()
        successes, stored_snapshot_assets = archive_api_snapshot_assets(
            records=successes,
            store=object_store,
        )
        if stored_snapshot_assets:
            snapshot_archive_audit = build_audit_event(
                event_type="api_snapshot_assets_archived",
                project_id=bootstrap.project.id,
                actor_type="worker",
                actor_id="collector_worker",
                target_type="project",
                target_id=bootstrap.project.id,
                before=None,
                after={
                    "stored_snapshot_assets": [asdict(item) for item in stored_snapshot_assets],
                },
                input_refs={"answer_run_ids": [record.answer_run.id for record in successes]},
                output_refs={"artifact_uris": [item.uri for item in stored_snapshot_assets]},
                method_version="s3_compatible_api_snapshot_archive_v1",
                reason="Archive official API response snapshots to configured object storage",
            )
            snapshot_archive_summary = {
                "enabled": True,
                "stored_snapshot_assets": [asdict(item) for item in stored_snapshot_assets],
                "audit_event_id": snapshot_archive_audit.id,
            }
        else:
            snapshot_archive_summary = {
                "enabled": True,
                "stored_snapshot_assets": [],
                "reason": "no_api_snapshot_assets",
            }
        successes, stored_browser_assets = archive_browser_capture_assets(
            records=successes,
            store=object_store,
        )
        if stored_browser_assets:
            browser_archive_audit = build_audit_event(
                event_type="browser_capture_assets_archived",
                project_id=bootstrap.project.id,
                actor_type="worker",
                actor_id="collector_worker",
                target_type="project",
                target_id=bootstrap.project.id,
                before=None,
                after={
                    "stored_browser_assets": [asdict(item) for item in stored_browser_assets],
                },
                input_refs={"answer_run_ids": [record.answer_run.id for record in successes]},
                output_refs={"artifact_uris": [item.uri for item in stored_browser_assets]},
                method_version="s3_compatible_browser_capture_archive_v1",
                reason="Archive browser screenshots and HTML captures to configured object storage",
            )
            browser_archive_summary = {
                "enabled": True,
                "stored_browser_assets": [asdict(item) for item in stored_browser_assets],
                "audit_event_id": browser_archive_audit.id,
            }
        else:
            browser_archive_summary = {
                "enabled": True,
                "stored_browser_assets": [],
                "reason": "no_browser_capture_assets",
            }
    else:
        pass
    if successes:
        repository.save_raw_evidence_records(successes)
    archive_audit_events = tuple(
        audit_event
        for audit_event in (snapshot_archive_audit, browser_archive_audit)
        if audit_event is not None
    )
    if archive_audit_events:
        repository.save_audit_events(archive_audit_events)
    if failures:
        repository.save_collection_failure_records(failures)
    collection_summary = build_collection_run_summary(
        project_id=bootstrap.project.id,
        run_type=run_type,
        mode=mode,
        planned_runs=planned_runs,
        records=records,
    )
    collection_summary_audit = build_collection_run_audit_event(collection_summary)
    repository.save_collection_run_summary(collection_summary, collection_summary_audit)
    analysis_summary: dict[str, object] = {"enabled": False}
    if persist_analysis and successes:
        entity_aliases = repository.get_confirmed_entity_alias_terms(bootstrap.project.id)
        platform_weights_snapshot = {
            item.platform: item.weight
            for item in bootstrap.market_profile.platforms
            if item.enabled and item.platform in {"chatgpt", "perplexity"}
        }
        score_weights = repository.get_score_weights_snapshot(
            project_id=bootstrap.project.id,
            formula_version=score_formula_version,
        )
        google_plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        google_gate = evaluate_google_spike_gate(
            project_id=bootstrap.project.id,
            plan=google_plan,
            records=records if run_type == "google_spike" else (),
        )
        google_readiness_gate = evaluate_google_spike_readiness_gate(
            project_id=bootstrap.project.id,
            plan=google_plan,
            records=records if run_type == "google_spike" else (),
        )
        score_input_successes = select_score_input_records(
            records=successes,
            google_spike_gate=google_gate,
            google_spike_readiness_gate=google_readiness_gate,
        )
        score_input_policy = build_score_input_policy(
            records=successes,
            score_input_records=score_input_successes,
            google_spike_gate=google_gate,
            google_spike_readiness_gate=google_readiness_gate,
        )
        if not score_input_successes:
            return {
                "enabled": True,
                "project_bootstrap": True,
                "tenant_id": bootstrap.tenant.id,
                "project_id": bootstrap.project.id,
                "prompt_questions": len(bootstrap.prompt_questions),
                "competitors": len(bootstrap.competitors),
                "raw_evidence_records": len(successes),
                "collection_failure_records": len(failures),
                "api_snapshot_artifacts": snapshot_archive_summary,
                "browser_capture_artifacts": browser_archive_summary,
                "evidence_artifacts": {
                    "api_snapshot_artifacts": snapshot_archive_summary,
                    "browser_capture_artifacts": browser_archive_summary,
                },
                "collection_run_summary": asdict(collection_summary),
                "collection_run_audit_event_id": collection_summary_audit.id,
                "analysis": {
                    "enabled": True,
                    "analysis_count": 0,
                    "score_input_record_count": 0,
                    "score_input_policy": score_input_policy,
                    "score_contributions": 0,
                    "reason": "no_score_input_records",
                },
            }
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=successes,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot=platform_weights_snapshot,
            score_weights=score_weights,
            formula_version=score_formula_version,
            entity_aliases=entity_aliases,
            scope_type="collection_slice",
            scope_value="worker_runtime",
            google_spike_gate=google_gate,
            google_spike_readiness_gate=google_readiness_gate,
            parser=_analysis_parser(judge_gateway=judge_gateway, judge_model=judge_model),
        )
        repository.save_answer_analyses(analysis_result.analyses)
        repository.save_score_snapshot(
            analysis_result.snapshot,
            analysis_result.contributions,
            analysis_result.audit_event,
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=analysis_result.score_input_records,
            analyses=analysis_result.score_input_analyses,
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
            records=analysis_result.score_input_records,
            graph=graph,
            platform_weights_snapshot=platform_weights_snapshot,
            google_spike_gate=google_gate,
            score_input_policy=analysis_result.score_input_policy,
            fidelity_records=successes,
        )
        repository.save_report_export(report.report_export, report.audit_event)
        fidelity_check, fidelity_audit = build_runtime_fidelity_check_from_records(
            project_id=bootstrap.project.id,
            report_export_id=report.report_export.id,
            records=successes,
            checked_by="collector_worker",
        )
        repository.save_fidelity_check(fidelity_check, fidelity_audit)
        report_artifact_summary: dict[str, object] = {
            "enabled": False,
            "reason": "OBJECT_STORE_ENDPOINT not configured",
        }
        if os.environ.get("OBJECT_STORE_ENDPOINT", "").strip():
            stored_artifacts = archive_report_artifacts(report, build_object_store_from_env())
            archive_audit = build_audit_event(
                event_type="report_artifacts_archived",
                project_id=bootstrap.project.id,
                actor_type="worker",
                actor_id="collector_worker",
                target_type="report_export",
                target_id=report.report_export.id,
                before=None,
                after={
                    "report_export_id": report.report_export.id,
                    "stored_artifacts": [asdict(item) for item in stored_artifacts],
                },
                input_refs={"report_export_ids": [report.report_export.id]},
                output_refs={"artifact_uris": [item.uri for item in stored_artifacts]},
                method_version="s3_compatible_report_artifact_archive_v1",
                reason="Archive M5 report artifacts to configured object storage",
            )
            repository.save_audit_events((archive_audit,))
            report_artifact_summary = {
                "enabled": True,
                "stored_artifacts": [asdict(item) for item in stored_artifacts],
                "audit_event_id": archive_audit.id,
            }
        actions = build_action_recommendations(
            project_id=bootstrap.project.id,
            graph=graph,
            snapshot=analysis_result.snapshot,
        )
        schedule = build_retest_schedule(
            project_id=bootstrap.project.id,
            prompt_version=bootstrap.project.prompt_version,
            sample_size=analysis_result.score_input_records[0].answer_run.sample_size,
            answer_run_ids=tuple(record.answer_run.id for record in analysis_result.score_input_records),
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
        facts = build_localized_knowledge_facts(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            brand=bootstrap.brand,
            category=bootstrap.project.category,
            answer_run_ids=tuple(record.answer_run.id for record in analysis_result.score_input_records),
        )
        knowledge_results = search_knowledge_facts(
            facts=facts,
            query=f"{bootstrap.project.target_brand} {bootstrap.project.category} Australia shipping reviews",
            market_code=bootstrap.project.market_code,
            city="Sydney",
            limit=5,
        )
        drafts = build_content_drafts(
            project_id=bootstrap.project.id,
            target_brand=bootstrap.project.target_brand,
            category=bootstrap.project.category,
            actions=actions,
            prompts=bootstrap.prompt_questions,
            knowledge_results=knowledge_results,
        )
        connectors = build_integration_connectors(project_id=bootstrap.project.id)
        distribution_records = build_manual_distribution_records(project_id=bootstrap.project.id, drafts=drafts)
        content_audit = build_content_engine_audit_event(
            project_id=bootstrap.project.id,
            facts=facts,
            drafts=drafts,
            connectors=connectors,
            distribution_records=distribution_records,
        )
        repository.save_content_engine(
            facts=facts,
            drafts=drafts,
            connectors=connectors,
            distribution_records=distribution_records,
            audit_event=content_audit,
        )
        traceability_bundle = build_traceability_bundle(
            project_id=bootstrap.project.id,
            report_export=report.report_export,
            snapshot=analysis_result.snapshot,
            contributions=analysis_result.contributions,
            records=analysis_result.score_input_records,
            graph=graph,
            actions=actions,
            content_drafts=drafts,
            audit_events=tuple(record.audit_events[0] for record in analysis_result.score_input_records)
            + (
                analysis_result.audit_event,
                report.audit_event,
                action_audit,
                comparison_audit,
                content_audit,
            ),
        )
        repository.save_traceability_bundle(traceability_bundle)
        analysis_summary = {
            "enabled": True,
            "analysis_count": len(analysis_result.analyses),
            "score_input_record_count": len(analysis_result.score_input_records),
            "score_input_policy": analysis_result.score_input_policy,
            "entity_alias_entity_count": len(entity_aliases),
            "entity_alias_term_count": sum(len(aliases) for aliases in entity_aliases.values()),
            "judge_gateway": judge_gateway,
            "judge_model": judge_model,
            "score_snapshot_id": analysis_result.snapshot.id,
            "score_formula_version": analysis_result.snapshot.formula_version,
            "score_contributions": len(analysis_result.contributions),
            "final_score": analysis_result.snapshot.final_score,
            "source_graph_nodes": len(graph.nodes),
            "source_graph_evidence": len(graph.evidence_links),
            "source_gaps": len(graph.source_gaps),
            "competitor_benchmarks": len(graph.competitor_benchmarks),
            "report_export_id": report.report_export.id,
            "report_evidence_answer_runs": len(report.report_evidence_answer_run_ids),
            "fidelity_check_id": fidelity_check["id"],
            "fidelity_check_status": fidelity_check["status"],
            "fidelity_difference_rate": fidelity_check["difference_rate"],
            "report_artifacts": report_artifact_summary,
            "action_recommendations": len(actions),
            "retest_schedule_id": schedule.id,
            "retest_comparison_id": comparison.id,
            "retest_trend": comparison.trend,
            "knowledge_facts": len(facts),
            "content_drafts": len(drafts),
            "integration_connectors": len(connectors),
            "manual_distribution_records": len(distribution_records),
            "traceability_bundle_id": traceability_bundle.id,
            "evidence_links": len(traceability_bundle.evidence_links),
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
        "api_snapshot_artifacts": snapshot_archive_summary,
        "browser_capture_artifacts": browser_archive_summary,
        "evidence_artifacts": {
            "api_snapshot_artifacts": snapshot_archive_summary,
            "browser_capture_artifacts": browser_archive_summary,
        },
        "collection_run_summary": asdict(collection_summary),
        "collection_run_audit_event_id": collection_summary_audit.id,
        "analysis": analysis_summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a small AU P0a collection slice")
    parser.add_argument("--mode", choices=["fixture", "api", "google-fixture"], default="fixture")
    parser.add_argument("--prompt-limit", type=int, default=2)
    parser.add_argument(
        "--prompt-ids",
        default=None,
        help="Comma-separated PromptQuestion ids to run; used by scheduled fidelity sampling plans.",
    )
    parser.add_argument("--sample-size", type=int, default=1)
    parser.add_argument("--cities", default="Australia,Sydney")
    parser.add_argument(
        "--plan-browser-fidelity-sampling",
        action="store_true",
        help="Only build a deterministic API-vs-browser sampling plan; do not collect.",
    )
    parser.add_argument(
        "--fidelity-run-date",
        default=None,
        help="YYYY-MM-DD date used to seed browser fidelity sampling; defaults to today.",
    )
    parser.add_argument("--fidelity-cadence", default="weekly")
    parser.add_argument("--fidelity-prompt-count", type=int, default=10)
    parser.add_argument("--fidelity-city-count", type=int, default=2)
    parser.add_argument("--fidelity-selection-seed", default=None)
    parser.add_argument(
        "--include-browser-fidelity-fixture",
        action="store_true",
        help="In fixture mode, add paired browser answer runs for API-vs-browser fidelity sampling only.",
    )
    parser.add_argument(
        "--include-browser-fidelity-playwright",
        action="store_true",
        help="In api mode, add the Playwright browser collector for real API-vs-browser fidelity sampling.",
    )
    parser.add_argument(
        "--require-ready-collectors",
        action="store_true",
        help="Exit before collection if any selected collector health is not ready.",
    )
    parser.add_argument(
        "--require-p0a-readiness",
        action="store_true",
        help="Exit non-zero when the P0a readiness gate fails after collection.",
    )
    parser.add_argument(
        "--require-no-collection-failures",
        action="store_true",
        help="Exit non-zero after collection if any selected collector produced a failure record.",
    )
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
    parser.add_argument(
        "--score-formula-version",
        default="au_visibility_v1",
        help="Registered score formula version to use with --persist-analysis",
    )
    parser.add_argument(
        "--judge-gateway",
        choices=["fixture", "litellm"],
        default="fixture",
        help="LLMGateway implementation for parser judge calls during --persist-analysis.",
    )
    parser.add_argument(
        "--judge-model",
        default="local-fixture-judge",
        help="Judge model name passed to the selected LLMGateway.",
    )
    args = parser.parse_args()
    if args.persist_analysis and not args.persist:
        parser.error("--persist-analysis requires --persist")
    if args.require_p0a_readiness and args.mode == "google-fixture":
        parser.error("--require-p0a-readiness is only valid for fixture/api P0a modes")
    if args.prompt_ids and args.mode == "google-fixture":
        parser.error("--prompt-ids is only valid for fixture/api modes")

    bootstrap = build_au_project_bootstrap()
    if args.plan_browser_fidelity_sampling:
        try:
            run_date = (
                date.fromisoformat(args.fidelity_run_date)
                if args.fidelity_run_date
                else _default_market_run_date(bootstrap)
            )
            sampling_plan, sampling_audit = build_browser_fidelity_sampling_plan(
                project_id=bootstrap.project.id,
                prompts=bootstrap.prompt_questions,
                available_cities=tuple(bootstrap.market_profile.cities),
                run_date=run_date,
                cadence=args.fidelity_cadence,
                prompt_count=args.fidelity_prompt_count,
                city_count=args.fidelity_city_count,
                sample_size=args.sample_size,
                selection_seed=args.fidelity_selection_seed,
            )
        except ValueError as exc:
            parser.error(str(exc))
        persistence: dict[str, object] = {"enabled": False}
        if args.persist:
            try:
                repository = build_repository_from_env()
                repository.save_project_bootstrap(bootstrap)
                repository.save_audit_events((sampling_audit,))
                persistence = {
                    "enabled": True,
                    "project_bootstrap": True,
                    "audit_event_id": sampling_audit.id,
                }
            except RuntimePersistenceError as exc:
                print(f"persistence_error: {exc}", file=sys.stderr)
                raise SystemExit(2) from exc
        output = {
            "mode": "browser_fidelity_sampling_plan",
            "record_count": 0,
            "planned_runs": sampling_plan.planned_runs,
            "browser_fidelity_sampling_plan": asdict(sampling_plan),
            "audit_event": asdict(sampling_audit),
            "recommended_worker_args": list(sampling_plan.recommended_worker_args),
            "persistence": persistence,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        return

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
        try:
            prompts = _filter_prompts_by_ids(prompts, args.prompt_ids)
        except ValueError as exc:
            parser.error(str(exc))
        if args.prompt_ids:
            args.prompt_limit = max(args.prompt_limit, len(prompts))
    base_collectors = _collectors(args.mode)
    fidelity_collectors = _fidelity_fixture_collectors(args.mode) if args.include_browser_fidelity_fixture else ()
    if args.include_browser_fidelity_playwright:
        fidelity_collectors = fidelity_collectors + _fidelity_playwright_collectors(args.mode)
    collectors = base_collectors + fidelity_collectors
    collector_health = _collector_health_report(collectors)
    collector_health_failure_reasons = _collector_health_failure_reasons(collector_health)
    collector_health_gate = {
        "gate_status": "fail" if collector_health_failure_reasons else "pass",
        "failure_reasons": collector_health_failure_reasons,
    }
    planned_runs = (
        plan.planned_runs
        if plan is not None
        else len(prompts[: args.prompt_limit]) * len(collectors) * len(cities) * args.sample_size
    )
    if args.require_ready_collectors and collector_health_failure_reasons:
        output = {
            "mode": args.mode,
            "record_count": 0,
            "planned_runs": planned_runs,
            "success_count": 0,
            "failure_count": 0,
            "collector_health": collector_health,
            "collector_health_gate": collector_health_gate,
            "p0a_readiness_gate": None,
            "persistence": {"enabled": False},
        }
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        print(f"collector_preflight_failed: {', '.join(collector_health_failure_reasons)}", file=sys.stderr)
        raise SystemExit(3)
    records = run_collection_slice(
        project_id=bootstrap.project.id,
        prompts=prompts,
        market_profile=bootstrap.market_profile,
        collectors=collectors,
        cities=cities,
        sample_size=args.sample_size,
        prompt_limit=args.prompt_limit,
    )
    successes = tuple(record for record in records if isinstance(record, RawEvidenceRecord))
    failures = tuple(record for record in records if isinstance(record, CollectionFailureRecord))
    p0a_readiness_gate = evaluate_p0a_collection_readiness(records=records) if args.mode != "google-fixture" else None
    persistence: dict[str, object] = {"enabled": False}
    if args.persist:
        try:
            persistence = _persist_records(
                bootstrap=bootstrap,
                mode=args.mode,
                run_type="google_spike" if args.mode == "google-fixture" else "p0a_slice",
                planned_runs=planned_runs,
                records=records,
                successes=successes,
                failures=failures,
                persist_analysis=args.persist_analysis,
                score_formula_version=args.score_formula_version,
                judge_gateway=args.judge_gateway,
                judge_model=args.judge_model,
            )
        except RuntimePersistenceError as exc:
            print(f"persistence_error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    output = {
        "mode": args.mode,
        "record_count": len(records),
        "planned_runs": planned_runs,
        "success_count": len(successes),
        "failure_count": len(failures),
        "answer_run_ids": [record.answer_run.id for record in records],
        "failure_events": [asdict(record) for record in failures],
        "collector_health": collector_health,
        "collector_health_gate": collector_health_gate,
        "p0a_readiness_gate": asdict(p0a_readiness_gate) if p0a_readiness_gate is not None else None,
        "persistence": persistence,
    }
    if plan is not None:
        output["google_spike_gate"] = asdict(
            evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=plan, records=records)
        )
        output["google_spike_readiness_gate"] = asdict(
            evaluate_google_spike_readiness_gate(project_id=bootstrap.project.id, plan=plan, records=records)
        )
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    if args.require_no_collection_failures and failures:
        print(
            f"collection_failures_found: {len(failures)}",
            file=sys.stderr,
        )
        raise SystemExit(5)
    if args.require_p0a_readiness and p0a_readiness_gate is not None and p0a_readiness_gate.gate_status != "pass":
        print(
            f"p0a_readiness_failed: {', '.join(p0a_readiness_gate.failure_reasons)}",
            file=sys.stderr,
        )
        raise SystemExit(4)


if __name__ == "__main__":
    main()
