from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response

from geno_core.action_plan import (
    build_action_plan_audit_event,
    build_action_recommendations,
    build_retest_schedule,
    build_retest_comparison_audit_event,
    compare_retest_windows,
)
from geno_core.analysis_pipeline import analyze_and_score_records
from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import (
    build_p0a_collection_plan,
    run_collection_slice,
    run_fixture_collection_slice,
)
from geno_core.collectors import (
    FixtureGoogleAIModeCollector,
    FixtureGoogleAIOCollector,
    FixtureOpenAIWebSearchCollector,
    FixturePerplexitySonarCollector,
)
from geno_core.google_spike import (
    build_google_spike_plan,
    evaluate_google_spike_gate,
    select_google_spike_prompts,
)
from geno_core.graph import build_citation_graph
from geno_core.industry import build_au_dtc_ecommerce_profile
from geno_core.knowledge import (
    build_content_drafts,
    build_content_engine_audit_event,
    build_integration_connectors,
    build_localized_knowledge_facts,
    build_manual_distribution_records,
    search_knowledge_facts,
)
from geno_core.market import build_au_market_profile
from geno_core.prompt_pack import build_au_dtc_prompt_pack
from geno_core.report import MarkdownCsvReportExporter
from geno_core.runtime import RuntimePersistenceError, build_repository_from_env, close_repository_connection
from geno_core.traceability import build_traceability_bundle

app = FastAPI(title="GENO SaaS AU API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "geno-saas-au-api"}


@app.get("/v1/market-profiles/au")
def au_market_profile() -> dict[str, object]:
    return asdict(build_au_market_profile())


@app.get("/v1/industry-profiles/au/dtc-ecommerce")
def au_dtc_industry_profile() -> dict[str, object]:
    return asdict(build_au_dtc_ecommerce_profile())


@app.get("/v1/prompt-packs/au/dtc-ecommerce")
def au_dtc_prompt_pack() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    return {
        "prompt_version": bootstrap.project.prompt_version,
        "market_code": bootstrap.project.market_code,
        "industry_code": bootstrap.project.industry_code,
        "target_brand": bootstrap.project.target_brand,
        "category": bootstrap.project.category,
        "count": len(bootstrap.prompt_questions),
        "prompts": [asdict(prompt) for prompt in bootstrap.prompt_questions],
    }


@app.get("/v1/project-bootstraps/au/dtc-ecommerce")
def au_dtc_project_bootstrap() -> dict[str, object]:
    return asdict(build_au_project_bootstrap())


@app.get("/v1/collection-plans/au/p0a")
def au_p0a_collection_plan() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    return asdict(
        build_p0a_collection_plan(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
        )
    )


@app.get("/v1/evidence-runs/au/p0a-fixture-slice")
def au_p0a_fixture_slice() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
    )
    return {
        "record_count": len(records),
        "answer_run_ids": [record.answer_run.id for record in records],
        "records": [asdict(record) for record in records],
    }


@app.get("/v1/evidence-runs/runtime")
def runtime_evidence_runs(
    project_id: str | None = None,
    platform: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_evidence_runs(
            project_id=project_id,
            platform=platform,
            status=status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/visibility-scores/runtime")
def runtime_visibility_scores(
    project_id: str | None = None,
    scope_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_score_snapshots(
            project_id=project_id,
            scope_type=scope_type,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/citation-graphs/runtime")
def runtime_citation_graphs(
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_citation_graphs(
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/reports/runtime")
def runtime_reports(
    project_id: str | None = None,
    report_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_report_exports(
            project_id=project_id,
            report_type=report_type,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/reports/runtime/{report_export_id}/artifact")
def runtime_report_artifact(
    report_export_id: str,
    artifact_type: str = Query(default="markdown", alias="type", pattern="^(markdown|csv)$"),
) -> Response:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        artifact = repository.get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type=artifact_type,
        )
        if artifact is None:
            raise HTTPException(status_code=404, detail="Runtime report artifact not found")
        return Response(
            content=artifact.content,
            media_type=artifact.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{artifact.filename}"',
                "X-GENO-Report-Artifact-Hash": artifact.content_hash,
            },
        )
    finally:
        close_repository_connection(repository)


@app.get("/v1/action-plans/runtime")
def runtime_action_plans(
    project_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_action_plans(
            project_id=project_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/content-engines/runtime")
def runtime_content_engines(
    project_id: str | None = None,
    review_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_content_engines(
            project_id=project_id,
            review_status=review_status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/traceability/runtime")
def runtime_traceability(
    project_id: str | None = None,
    report_export_id: str | None = None,
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        detail = repository.get_runtime_traceability_detail(
            project_id=project_id,
            report_export_id=report_export_id,
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="Runtime traceability bundle not found")
        return asdict(detail)
    finally:
        close_repository_connection(repository)


@app.get("/v1/google-spikes/au/plan")
def au_google_spike_plan() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    return asdict(build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions))


@app.get("/v1/google-spikes/au/fixture-gate")
def au_google_spike_fixture_gate() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
    prompts = select_google_spike_prompts(bootstrap.prompt_questions)
    records = run_collection_slice(
        project_id=bootstrap.project.id,
        prompts=prompts,
        market_profile=bootstrap.market_profile,
        collectors=(FixtureGoogleAIOCollector(), FixtureGoogleAIModeCollector()),
        cities=plan.geo_cities,
        sample_size=plan.sample_size,
        prompt_limit=plan.prompt_count,
    )
    gate = evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=plan, records=records)
    return {
        "plan": asdict(plan),
        "gate": asdict(gate),
        "record_count": len(records),
    }


@app.get("/v1/visibility-scores/au/p0a-fixture")
def au_p0a_fixture_visibility_score() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
        scope_type="project",
        scope_value="p0a_fixture",
    )
    return {
        "analysis_count": len(result.analyses),
        "snapshot": asdict(result.snapshot),
        "contributions": [asdict(contribution) for contribution in result.contributions],
        "audit_event": asdict(result.audit_event),
    }


@app.get("/v1/citation-graphs/au/p0a-fixture")
def au_p0a_fixture_citation_graph() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    return {
        "node_count": len(graph.nodes),
        "evidence_link_count": len(graph.evidence_links),
        "source_gap_count": len(graph.source_gaps),
        "competitor_count": len(graph.competitor_benchmarks),
        "nodes": [asdict(node) for node in graph.nodes],
        "source_gaps": [asdict(gap) for gap in graph.source_gaps],
        "competitor_benchmarks": [asdict(item) for item in graph.competitor_benchmarks],
    }


@app.get("/v1/reports/au/p0a-fixture")
def au_p0a_fixture_report() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    report = MarkdownCsvReportExporter().export(
        project_id=bootstrap.project.id,
        market_code=bootstrap.project.market_code,
        report_version="p0a-fixture-v1",
        report_type="design_partner_fixture",
        prompt_version=bootstrap.project.prompt_version,
        snapshot=analysis_result.snapshot,
        contributions=analysis_result.contributions,
        records=records,
        graph=graph,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    return {
        "report_export": asdict(report.report_export),
        "markdown": report.markdown,
        "csv_content": report.csv_content,
        "audit_event": asdict(report.audit_event),
        "report_evidence_answer_run_ids": list(report.report_evidence_answer_run_ids),
    }


@app.get("/v1/action-plans/au/p0a-fixture")
def au_p0a_fixture_action_plan() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    actions = build_action_recommendations(
        project_id=bootstrap.project.id,
        graph=graph,
        snapshot=analysis_result.snapshot,
    )
    schedule = build_retest_schedule(
        project_id=bootstrap.project.id,
        prompt_version=bootstrap.project.prompt_version,
        sample_size=1,
        answer_run_ids=tuple(record.answer_run.id for record in records),
    )
    audit_event = build_action_plan_audit_event(
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
    comparison_audit_event = build_retest_comparison_audit_event(
        project_id=bootstrap.project.id,
        comparison=comparison,
    )
    return {
        "action_count": len(actions),
        "actions": [asdict(action) for action in actions],
        "retest_schedule": asdict(schedule),
        "retest_comparison": asdict(comparison),
        "audit_event": asdict(audit_event),
        "comparison_audit_event": asdict(comparison_audit_event),
    }


@app.get("/v1/content-engines/au/p0a-fixture")
def au_p0a_fixture_content_engine() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    actions = build_action_recommendations(
        project_id=bootstrap.project.id,
        graph=graph,
        snapshot=analysis_result.snapshot,
    )
    answer_run_ids = tuple(record.answer_run.id for record in records)
    facts = build_localized_knowledge_facts(
        project_id=bootstrap.project.id,
        market_code=bootstrap.project.market_code,
        brand=bootstrap.brand,
        category=bootstrap.project.category,
        answer_run_ids=answer_run_ids,
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
    audit_event = build_content_engine_audit_event(
        project_id=bootstrap.project.id,
        facts=facts,
        drafts=drafts,
        connectors=connectors,
        distribution_records=distribution_records,
    )
    return {
        "knowledge_fact_count": len(facts),
        "search_results": [asdict(result) for result in knowledge_results],
        "content_draft_count": len(drafts),
        "content_drafts": [asdict(draft) for draft in drafts],
        "integration_connectors": [asdict(connector) for connector in connectors],
        "manual_distribution_records": [asdict(record) for record in distribution_records],
        "audit_event": asdict(audit_event),
    }


@app.get("/v1/traceability/au/p0a-fixture")
def au_p0a_fixture_traceability() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    report = MarkdownCsvReportExporter().export(
        project_id=bootstrap.project.id,
        market_code=bootstrap.project.market_code,
        report_version="p0a-fixture-v1",
        report_type="design_partner_fixture",
        prompt_version=bootstrap.project.prompt_version,
        snapshot=analysis_result.snapshot,
        contributions=analysis_result.contributions,
        records=records,
        graph=graph,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    actions = build_action_recommendations(
        project_id=bootstrap.project.id,
        graph=graph,
        snapshot=analysis_result.snapshot,
    )
    facts = build_localized_knowledge_facts(
        project_id=bootstrap.project.id,
        market_code=bootstrap.project.market_code,
        brand=bootstrap.brand,
        category=bootstrap.project.category,
        answer_run_ids=tuple(record.answer_run.id for record in records),
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
    bundle = build_traceability_bundle(
        project_id=bootstrap.project.id,
        report_export=report.report_export,
        snapshot=analysis_result.snapshot,
        contributions=analysis_result.contributions,
        records=records,
        graph=graph,
        actions=actions,
        content_drafts=drafts,
        audit_events=tuple(record.audit_events[0] for record in records)
        + (analysis_result.audit_event, report.audit_event),
    )
    return {
        "traceability_bundle": asdict(bundle),
        "report_export": asdict(report.report_export),
        "score_contribution_count": len(analysis_result.contributions),
        "answer_run_count": len(records),
    }


@app.get("/v1/contracts")
def contracts() -> dict[str, list[str]]:
    return {
        "interfaces": [
            "CollectorBackend",
            "LLMGateway",
            "ParserEngine",
            "VectorStore",
            "GraphStore",
            "GeoProvider",
            "ScoringFormula",
            "ReportExporter",
        ],
        "auditability": [
            "AuditEvent",
            "EvidenceLink",
            "ScoreContribution",
            "ReportExport",
            "TraceabilityBundle",
        ],
        "m1_bootstrap": [
            "Tenant",
            "Project",
            "ProjectMember",
            "BrandEntity",
            "CompetitorEntity",
            "IndustryProfile",
            "PromptQuestion",
            "ProjectBootstrap",
        ],
        "m2a_evidence": [
            "CollectionPlan",
            "AnswerRun",
            "RawAnswer",
            "AnswerCitation",
            "EvidenceAsset",
            "CollectorLog",
            "CollectionCost",
            "RawEvidenceRecord",
            "CollectionFailureRecord",
            "PerplexitySonarCollector",
            "OpenAIWebSearchCollector",
        ],
        "m2b_google_spike": [
            "GoogleSpikePlan",
            "GoogleSpikeGateResult",
            "PlaywrightGoogleAIOCollector",
            "PlaywrightAIModeCollector",
            "ThirdPartySerpCollector",
            "ManualBackfillCollector",
        ],
        "m3_analysis_scoring": [
            "RuleBasedAnswerParser",
            "AnswerAnalysis",
            "VisibilityScoreSnapshot",
            "ScoreContribution",
            "au_visibility_v1",
        ],
        "m4_graph_benchmark": [
            "SourceGraphNode",
            "SourceGraphEvidence",
            "SourceGap",
            "CompetitorBenchmark",
            "CitationGraphResult",
        ],
        "m5_report_export": [
            "ReportExport",
            "MarkdownCsvReportExporter",
            "EvidenceReport",
        ],
        "m6_action_retest": [
            "ActionRecommendation",
            "RetestSchedule",
            "RetestComparison",
        ],
        "m7_content_integrations": [
            "LocalizedKnowledgeFact",
            "KnowledgeSearchResult",
            "ContentDraft",
            "IntegrationConnector",
            "ManualDistributionRecord",
        ],
        "traceability": [
            "EvidenceLink",
            "TraceabilityBundle",
            "build_traceability_bundle",
        ],
        "persistence": [
            "build_repository_from_env",
            "connect_postgres_from_env",
            "close_repository_connection",
            "RuntimePersistenceError",
            "PostgresEvidenceRepository",
            "save_project_bootstrap",
            "RuntimeEvidenceRun",
            "RuntimeEvidencePage",
            "RuntimeScoreSnapshot",
            "RuntimeScoreSnapshotPage",
            "RuntimeCitationGraph",
            "RuntimeCitationGraphPage",
            "RuntimeReportArtifact",
            "RuntimeReportExport",
            "RuntimeReportExportPage",
            "RuntimeActionPlan",
            "RuntimeActionPlanPage",
            "RuntimeContentDraft",
            "RuntimeContentEngine",
            "RuntimeContentEnginePage",
            "RuntimeTraceabilityDetail",
            "ProjectBootstrap",
            "PromptQuestion",
            "RawEvidenceRecord",
            "CollectionFailureRecord",
            "VisibilityScoreSnapshot",
            "ReportExport",
            "TraceabilityBundle",
            "/v1/evidence-runs/runtime",
            "worker --persist",
            "worker --persist-analysis",
            "/v1/visibility-scores/runtime",
            "/v1/citation-graphs/runtime",
            "/v1/reports/runtime",
            "/v1/reports/runtime/{report_export_id}/artifact",
            "/v1/action-plans/runtime",
            "/v1/content-engines/runtime",
            "/v1/traceability/runtime",
        ],
    }
