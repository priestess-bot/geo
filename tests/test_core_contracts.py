from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

from geno_core.action_plan import (
    build_action_plan_audit_event,
    build_action_recommendations,
    build_retest_schedule,
    build_retest_comparison_audit_event,
    compare_retest_windows,
)
from geno_core.audit import build_audit_event, hash_payload
from geno_core.analysis_pipeline import analyze_and_score_records
from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import (
    build_p0a_collection_plan,
    collect_prompt_with_failure_record,
    run_collection_slice,
    run_fixture_collection_slice,
)
from geno_core.collectors import (
    FixtureGoogleAIModeCollector,
    FixtureGoogleAIOCollector,
    FixtureOpenAIWebSearchCollector,
    FixturePerplexitySonarCollector,
    OpenAIWebSearchCollector,
    PerplexitySonarCollector,
)
from geno_core.geo import StaticAUGeoProvider
from geno_core.google_spike import (
    build_google_spike_plan,
    evaluate_google_spike_gate,
    select_google_spike_prompts,
)
from geno_core.graph import build_citation_graph
from geno_core.knowledge import (
    build_content_drafts,
    build_content_engine_audit_event,
    build_integration_connectors,
    build_localized_knowledge_facts,
    build_manual_distribution_records,
    search_knowledge_facts,
)
from geno_core.market import build_au_market_profile
from geno_core.models import (
    AnswerAnalysis,
    CollectionFailureRecord,
    ReportExport,
    RuntimeEvidencePage,
    RuntimeCitationGraphPage,
    RuntimeActionPlanPage,
    RuntimeScoreSnapshotPage,
    RuntimeReportExportPage,
)
from geno_core.prompt_pack import INTENT_WEIGHTS
from geno_core.parser import RuleBasedAnswerParser
from geno_core.report import MarkdownCsvReportExporter
from geno_core.repository import PostgresEvidenceRepository
from geno_core.runtime import RuntimePersistenceError, build_repository_from_env
from geno_core.scoring import AU_VISIBILITY_V1, score_answer_analysis
from geno_core.traceability import build_traceability_bundle


class RecordingCursor:
    def __init__(
        self,
        calls: list[tuple[str, tuple[object, ...]]],
        result_sets: list[object],
    ) -> None:
        self.calls = calls
        self.result_sets = result_sets

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self) -> object:
        result = self.result_sets.pop(0)
        if isinstance(result, list):
            return result[0] if result else None
        return result

    def fetchall(self) -> object:
        result = self.result_sets.pop(0)
        return result


class RecordingConnection:
    def __init__(self, result_sets: list[object] | None = None) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.commit_count = 0
        self.result_sets = result_sets or []

    def cursor(self) -> RecordingCursor:
        return RecordingCursor(self.calls, self.result_sets)

    def commit(self) -> None:
        self.commit_count += 1


class CoreContractsTest(unittest.TestCase):
    def test_au_weights_sum_to_one(self) -> None:
        self.assertAlmostEqual(sum(AU_VISIBILITY_V1.values()), 1.0)

    def test_market_profile_separates_weight_and_build_stage(self) -> None:
        profile = build_au_market_profile()
        stages = {(item.platform, item.surface): item.build_stage for item in profile.platforms}
        self.assertEqual(stages[("google", "google_aio")], "P0b")
        self.assertEqual(stages[("perplexity", "sonar")], "P0a")

    def test_score_contributions_explain_final_score(self) -> None:
        analysis = AnswerAnalysis(
            id="analysis-1",
            answer_run_id="run-1",
            parser_engine_id="rule",
            analysis_version="v1",
            brand_mentioned=True,
            brand_recommended=False,
            brand_position=2,
            competitors_mentioned=["competitor"],
            citation_count=2,
            local_relevance_score=75.0,
            sentiment_score=80.0,
            freshness_score=60.0,
            competitor_share_score=40.0,
            confidence=0.92,
        )
        result = score_answer_analysis(
            project_id="project-1",
            analysis=analysis,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        contribution_total = round(sum(item.weighted_contribution for item in result.contributions), 4)
        self.assertEqual(result.snapshot.formula_version, "au_visibility_v1")
        self.assertEqual(contribution_total, result.snapshot.final_score)
        self.assertEqual(len(result.contributions), len(AU_VISIBILITY_V1))

    def test_audit_event_hashes_are_stable(self) -> None:
        before = {"b": 2, "a": 1}
        after = {"a": 1, "b": 3}
        event = build_audit_event(
            event_type="score_snapshot_created",
            project_id="00000000-0000-0000-0000-000000000001",
            actor_type="system",
            actor_id="scoring-engine",
            target_type="score_snapshot",
            target_id="snapshot-1",
            before=before,
            after=after,
            input_refs={"answer_run_ids": ["run-1"]},
            output_refs={"score_snapshot_ids": ["snapshot-1"]},
            method_version="au_visibility_v1",
        )
        self.assertEqual(event.before_hash, hash_payload({"a": 1, "b": 2}))
        self.assertEqual(event.after_hash, hash_payload({"b": 3, "a": 1}))

    def test_report_export_is_immutable_snapshot(self) -> None:
        report = ReportExport(
            id="00000000-0000-0000-0000-000000000002",
            project_id="00000000-0000-0000-0000-000000000001",
            market_code="AU",
            report_version="v1",
            report_type="design_partner",
            score_snapshot_ids=("score-1",),
            answer_run_ids=("run-1",),
            prompt_version="prompt-v1",
            scoring_formula_version="au_visibility_v1",
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            sample_size=3,
            window_start=datetime(2026, 6, 1, tzinfo=UTC),
            window_end=datetime(2026, 6, 8, tzinfo=UTC),
            methodology_hash="hash",
            markdown_url=None,
            pdf_url=None,
            csv_url=None,
            exported_by="system",
            exported_at=datetime(2026, 6, 9, tzinfo=UTC),
        )
        with self.assertRaises(FrozenInstanceError):
            report.report_version = "v2"  # type: ignore[misc]

    def test_m1_project_bootstrap_builds_au_prompt_pack(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa", "IKEA Australia"),
        )
        prompts = bootstrap.prompt_questions
        self.assertEqual(bootstrap.project.market_code, "AU")
        self.assertEqual(bootstrap.industry_profile.industry_code, "dtc_ecommerce")
        self.assertEqual(len(bootstrap.competitors), 4)
        self.assertEqual(len(prompts), 100)
        self.assertEqual({prompt.language for prompt in prompts}, {"en-AU"})
        self.assertEqual({prompt.prompt_version for prompt in prompts}, {"au_dtc_ecommerce_v1"})
        self.assertEqual({prompt.intent_type for prompt in prompts}, set(INTENT_WEIGHTS))
        self.assertEqual(
            {prompt.city for prompt in prompts if prompt.intent_type == "city_category_recommendation"},
            {"Sydney", "Melbourne", "Brisbane"},
        )
        self.assertIn("Australia", {prompt.city for prompt in prompts})
        self.assertEqual(bootstrap.audit_events[0].event_type, "project_bootstrap_created")
        self.assertEqual(
            bootstrap.audit_events[0].output_refs["prompt_question_ids"],
            [prompt.id for prompt in prompts],
        )

    def test_m1_bootstrap_rejects_invalid_competitor_count(self) -> None:
        with self.assertRaises(ValueError):
            build_au_project_bootstrap(competitors=("Only One",))

    def test_m2a_p0a_collection_plan_matches_2400_runs(self) -> None:
        bootstrap = build_au_project_bootstrap()
        plan = build_p0a_collection_plan(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
        )
        self.assertEqual(plan.prompt_count, 100)
        self.assertEqual(plan.platform_count, 2)
        self.assertEqual(plan.geo_count, 4)
        self.assertEqual(plan.sample_size, 3)
        self.assertEqual(plan.planned_runs, 2400)
        self.assertEqual(set(plan.platform_surfaces), {"chatgpt:chatgpt_search", "perplexity:sonar"})
        self.assertEqual(set(plan.geo_cities), {"Australia", "Sydney", "Melbourne", "Brisbane"})

    def test_m2a_fixture_collection_slice_preserves_raw_evidence(self) -> None:
        bootstrap = build_au_project_bootstrap()
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia", "Sydney"),
            sample_size=1,
            prompt_limit=2,
        )
        self.assertEqual(len(records), 8)
        first = records[0]
        self.assertTrue(first.answer_run.answer_present)
        self.assertTrue(first.answer_run.surface_triggered)
        self.assertEqual(first.answer_run.sample_index, 1)
        self.assertEqual(first.answer_run.sample_size, 1)
        self.assertEqual(first.answer_run.access_method, "official_api")
        self.assertEqual(len(first.citations), 3)
        self.assertEqual({asset.asset_type for asset in first.evidence_assets}, {"screenshot", "html_snapshot"})
        self.assertTrue(first.raw_answer.raw_payload_hash)
        self.assertIsNotNone(first.audit_events[0].after_hash)
        self.assertGreater(first.collection_cost.total_cost, 0)
        self.assertEqual(first.audit_events[0].event_type, "answer_run_collected")
        self.assertIn(first.answer_run.id, first.audit_events[0].output_refs["answer_run_ids"])
        self.assertIn(first.raw_answer.id, first.audit_events[0].output_refs["raw_answer_ids"])
        self.assertEqual(
            len(first.audit_events[0].output_refs["answer_citation_ids"]),
            len(first.citations),
        )
        self.assertEqual(
            len(first.audit_events[0].output_refs["evidence_asset_ids"]),
            len(first.evidence_assets),
        )

    def test_m2a_static_au_geo_provider_resolves_city_params(self) -> None:
        params = StaticAUGeoProvider().resolve(
            market_code="AU",
            city="Sydney",
            language="en-AU",
            device="desktop",
        )
        self.assertEqual(params["gl"], "au")
        self.assertEqual(params["near"], "Sydney, New South Wales")
        self.assertEqual(params["device"], "desktop")

    def test_m2a_real_collectors_build_expected_payloads(self) -> None:
        bootstrap = build_au_project_bootstrap()
        prompt = bootstrap.prompt_questions[0]
        perplexity = PerplexitySonarCollector(api_key="test-key")
        openai = OpenAIWebSearchCollector(api_key="test-key")
        perplexity_payload = perplexity.build_payload(
            prompt=prompt.text,
            market=bootstrap.market_profile,
            city="Sydney",
            language=prompt.language,
        )
        openai_payload = openai.build_payload(
            prompt=prompt.text,
            market=bootstrap.market_profile,
            city="Sydney",
            language=prompt.language,
        )
        self.assertEqual(perplexity_payload["model"], "sonar")
        self.assertIn("messages", perplexity_payload)
        self.assertEqual(openai_payload["tools"], [{"type": "web_search_preview"}])
        self.assertIn("input", openai_payload)

    def test_m2a_real_collectors_parse_citations(self) -> None:
        perplexity = PerplexitySonarCollector(api_key="test-key")
        openai = OpenAIWebSearchCollector(api_key="test-key")
        perplexity_result = perplexity.parse_response(
            {
                "choices": [{"message": {"content": "Perplexity answer"}}],
                "citations": ["https://source.example/a"],
            }
        )
        openai_result = openai.parse_response(
            {
                "output": [
                    {
                        "content": [
                            {
                                "text": "OpenAI answer",
                                "annotations": [{"url": "https://source.example/b"}],
                            }
                        ]
                    }
                ]
            }
        )
        self.assertEqual(perplexity_result.answer_text, "Perplexity answer")
        self.assertEqual(perplexity_result.citations[0]["domain"], "source.example")
        self.assertEqual(openai_result.answer_text, "OpenAI answer")
        self.assertEqual(openai_result.citations[0]["url"], "https://source.example/b")

    def test_m2a_unconfigured_real_collector_returns_failure_record(self) -> None:
        bootstrap = build_au_project_bootstrap()
        result = collect_prompt_with_failure_record(
            project_id=bootstrap.project.id,
            prompt=bootstrap.prompt_questions[0],
            market_profile=bootstrap.market_profile,
            collector=PerplexitySonarCollector(api_key=""),
            city="Australia",
            sample_index=1,
            sample_size=1,
        )
        self.assertIsInstance(result, CollectionFailureRecord)
        assert isinstance(result, CollectionFailureRecord)
        self.assertEqual(result.answer_run.status, "failed")
        self.assertEqual(result.audit_events[0].event_type, "answer_run_failed")
        self.assertIn("PERPLEXITY_API_KEY", result.error_message)

    def test_m2b_google_spike_plan_matches_240_runs(self) -> None:
        bootstrap = build_au_project_bootstrap()
        plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        self.assertEqual(plan.prompt_count, 30)
        self.assertEqual(plan.surfaces, ("google_aio", "google_ai_mode"))
        self.assertEqual(plan.geo_cities, ("Australia", "Sydney"))
        self.assertEqual(plan.sample_size, 2)
        self.assertEqual(plan.planned_runs, 240)
        self.assertIn("blocked", plan.failure_reasons)

    def test_m2b_google_spike_fixture_gate_passes(self) -> None:
        bootstrap = build_au_project_bootstrap()
        plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=select_google_spike_prompts(bootstrap.prompt_questions),
            market_profile=bootstrap.market_profile,
            collectors=(FixtureGoogleAIOCollector(), FixtureGoogleAIModeCollector()),
            cities=plan.geo_cities,
            sample_size=plan.sample_size,
            prompt_limit=plan.prompt_count,
        )
        gate = evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=plan, records=records)
        self.assertEqual(len(records), 240)
        self.assertEqual(gate.gate_status, "pass")
        self.assertFalse(gate.limited_coverage)
        self.assertGreaterEqual(gate.google_aio_completed_runs, 120)

    def test_m2b_google_spike_gate_fails_without_google_aio_coverage(self) -> None:
        bootstrap = build_au_project_bootstrap()
        plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=select_google_spike_prompts(bootstrap.prompt_questions),
            market_profile=bootstrap.market_profile,
            collectors=(FixtureGoogleAIModeCollector(),),
            cities=plan.geo_cities,
            sample_size=plan.sample_size,
            prompt_limit=plan.prompt_count,
        )
        gate = evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=plan, records=records)
        self.assertEqual(gate.gate_status, "fail")
        self.assertTrue(gate.limited_coverage)

    def test_m3_rule_parser_extracts_brand_competitors_and_citations(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        analysis = RuleBasedAnswerParser().parse_record(
            record=records[0],
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
        )
        self.assertTrue(analysis.brand_mentioned)
        self.assertTrue(analysis.brand_recommended)
        self.assertEqual(analysis.citation_count, 3)
        self.assertGreaterEqual(analysis.local_relevance_score, 40)
        self.assertEqual(analysis.parser_engine_id, "rule_based_v1")

    def test_m3_analysis_pipeline_creates_aggregate_score_and_explanation(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
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
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        contribution_total = round(sum(item.weighted_contribution for item in result.contributions), 4)
        self.assertEqual(len(result.analyses), 40)
        self.assertEqual(len(result.contributions), len(AU_VISIBILITY_V1))
        self.assertEqual(contribution_total, result.snapshot.final_score)
        self.assertGreater(result.snapshot.mention_rate, 0)
        self.assertLessEqual(result.snapshot.mention_rate, 1)
        self.assertGreaterEqual(result.snapshot.dispersion, 0)
        self.assertEqual(result.audit_event.event_type, "visibility_score_snapshot_created")
        self.assertEqual(
            result.audit_event.output_refs["score_snapshot_ids"],
            [result.snapshot.id],
        )

    def test_m4_citation_graph_and_competitor_benchmark_trace_to_answer_runs(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
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
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=records,
            analyses=analysis_result.analyses,
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        self.assertGreaterEqual(len(graph.nodes), 3)
        self.assertGreater(len(graph.evidence_links), 0)
        self.assertTrue(graph.source_gaps)
        self.assertEqual(len(graph.competitor_benchmarks), 3)
        self.assertTrue(all(node.answer_run_ids for node in graph.nodes))
        self.assertTrue(all(link.answer_run_id for link in graph.evidence_links))
        self.assertTrue(any(item.mention_count > 0 for item in graph.competitor_benchmarks))

    def test_m5_report_export_freezes_snapshot_and_evidence_refs(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
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
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
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
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        self.assertEqual(report.report_export.score_snapshot_ids, (analysis_result.snapshot.id,))
        self.assertEqual(report.report_export.answer_run_ids, tuple(record.answer_run.id for record in records))
        self.assertIn("GENO AU Evidence Report", report.markdown)
        self.assertIn("answer_run_id", report.csv_content)
        self.assertEqual(report.audit_event.event_type, "report_export_created")
        self.assertEqual(report.audit_event.output_refs["report_export_ids"], [report.report_export.id])
        self.assertEqual(report.report_evidence_answer_run_ids, report.report_export.answer_run_ids)

    def test_m6_action_plan_and_retest_schedule_trace_evidence(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
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
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
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
            owner_id="owner-1",
            now=datetime(2026, 6, 10, tzinfo=UTC),
        )
        schedule = build_retest_schedule(
            project_id=bootstrap.project.id,
            prompt_version=bootstrap.project.prompt_version,
            sample_size=1,
            answer_run_ids=tuple(record.answer_run.id for record in records),
            start_at=datetime(2026, 6, 10, tzinfo=UTC),
        )
        audit_event = build_action_plan_audit_event(
            project_id=bootstrap.project.id,
            actions=actions,
            schedule=schedule,
        )
        self.assertTrue(actions)
        self.assertTrue(all(action.status == "open" for action in actions))
        self.assertTrue(all(action.next_check_date for action in actions))
        self.assertTrue(all(action.evidence_answer_run_ids for action in actions))
        self.assertEqual(schedule.offsets_days, (0, 7, 14, 30))
        self.assertEqual(len(schedule.scheduled_dates), 4)
        self.assertEqual(schedule.answer_run_ids, tuple(record.answer_run.id for record in records))
        self.assertEqual(audit_event.event_type, "action_plan_created")
        self.assertEqual(audit_event.output_refs["retest_schedule_ids"], [schedule.id])

    def test_m6_retest_comparison_classifies_trend(self) -> None:
        bootstrap = build_au_project_bootstrap()
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=2,
        )
        baseline = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        ).snapshot
        retest = baseline.__class__(
            **{
                **baseline.__dict__,
                "id": "retest-snapshot",
                "final_score": baseline.final_score + 3,
            }
        )
        comparison = compare_retest_windows(
            project_id=bootstrap.project.id,
            baseline=baseline,
            retest=retest,
            now=datetime(2026, 6, 17, tzinfo=UTC),
        )
        self.assertEqual(comparison.trend, "improved")
        self.assertEqual(comparison.score_delta, 3)
        self.assertEqual(comparison.baseline_answer_run_ids, tuple(baseline.answer_run_ids))
        audit_event = build_retest_comparison_audit_event(
            project_id=bootstrap.project.id,
            comparison=comparison,
        )
        self.assertEqual(audit_event.event_type, "retest_comparison_created")
        self.assertEqual(audit_event.output_refs["retest_comparison_ids"], [comparison.id])

    def test_m7_content_drafts_bind_knowledge_gap_and_evidence(self) -> None:
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
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
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
        facts = build_localized_knowledge_facts(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            brand=bootstrap.brand,
            category=bootstrap.project.category,
            answer_run_ids=tuple(record.answer_run.id for record in records),
            now=datetime(2026, 6, 10, tzinfo=UTC),
        )
        search_results = search_knowledge_facts(
            facts=facts,
            query="ExampleBrand Australia shipping review Sydney",
            market_code="AU",
            city="Sydney",
            limit=6,
        )
        drafts = build_content_drafts(
            project_id=bootstrap.project.id,
            target_brand=bootstrap.project.target_brand,
            category=bootstrap.project.category,
            actions=actions,
            prompts=bootstrap.prompt_questions,
            knowledge_results=search_results,
            now=datetime(2026, 6, 10, tzinfo=UTC),
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
        self.assertTrue(facts)
        self.assertTrue(search_results)
        self.assertTrue(any(result.fallback_used for result in search_results))
        self.assertTrue(drafts)
        self.assertTrue(all(draft.review_status == "pending_human_review" for draft in drafts))
        self.assertTrue(all(draft.used_knowledge_fact_ids for draft in drafts))
        self.assertTrue(all(draft.source_gap_types for draft in drafts))
        self.assertTrue(all(draft.evidence_answer_run_ids for draft in drafts))
        self.assertEqual(len(connectors), 7)
        self.assertEqual(len(distribution_records), len(drafts))
        self.assertEqual(audit_event.event_type, "content_engine_fixture_created")
        self.assertEqual(audit_event.output_refs["content_draft_ids"], [draft.id for draft in drafts])

    def test_traceability_bundle_connects_report_to_raw_evidence_and_actions(self) -> None:
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
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
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
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
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
        search_results = search_knowledge_facts(
            facts=facts,
            query="ExampleBrand Australia shipping review Sydney",
            market_code="AU",
            city="Sydney",
            limit=5,
        )
        drafts = build_content_drafts(
            project_id=bootstrap.project.id,
            target_brand=bootstrap.project.target_brand,
            category=bootstrap.project.category,
            actions=actions,
            prompts=bootstrap.prompt_questions,
            knowledge_results=search_results,
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
        self.assertEqual(bundle.report_export_ids, (report.report_export.id,))
        self.assertEqual(bundle.score_snapshot_ids, (analysis_result.snapshot.id,))
        self.assertEqual(bundle.answer_run_ids, report.report_export.answer_run_ids)
        self.assertEqual(len(bundle.score_contribution_ids), len(analysis_result.contributions))
        self.assertEqual(len(bundle.raw_answer_ids), len(records))
        self.assertGreater(len(bundle.answer_citation_ids), 0)
        self.assertGreater(len(bundle.evidence_asset_ids), 0)
        self.assertEqual(bundle.action_recommendation_ids, tuple(action.id for action in actions))
        self.assertEqual(bundle.content_draft_ids, tuple(draft.id for draft in drafts))
        self.assertTrue(any(link.relation_type == "explained_by" for link in bundle.evidence_links))
        self.assertTrue(any(link.relation_type == "supports_draft" for link in bundle.evidence_links))
        self.assertIn("answer runs", bundle.explanation_summary)

    def test_postgres_repository_maps_fixture_chain_to_runtime_tables(self) -> None:
        bootstrap = build_au_project_bootstrap()
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
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
            report_version="repository-fixture-v1",
            report_type="repository_fixture",
            prompt_version=bootstrap.project.prompt_version,
            snapshot=analysis_result.snapshot,
            contributions=analysis_result.contributions,
            records=records,
            graph=graph,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
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
        action_audit = build_action_plan_audit_event(
            project_id=bootstrap.project.id,
            actions=actions,
            schedule=schedule,
        )
        facts = build_localized_knowledge_facts(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            brand=bootstrap.brand,
            category=bootstrap.project.category,
            answer_run_ids=tuple(record.answer_run.id for record in records),
        )
        search_results = search_knowledge_facts(
            facts=facts,
            query="ExampleBrand Australia shipping",
            market_code="AU",
            limit=3,
        )
        drafts = build_content_drafts(
            project_id=bootstrap.project.id,
            target_brand=bootstrap.project.target_brand,
            category=bootstrap.project.category,
            actions=actions,
            prompts=bootstrap.prompt_questions,
            knowledge_results=search_results,
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
            + (analysis_result.audit_event, report.audit_event, action_audit, content_audit),
        )
        connection = RecordingConnection()
        repository = PostgresEvidenceRepository(connection)
        repository.save_raw_evidence_records(records)
        repository.save_answer_analyses(analysis_result.analyses)
        repository.save_score_snapshot(
            analysis_result.snapshot,
            analysis_result.contributions,
            analysis_result.audit_event,
        )
        repository.save_citation_graph(bootstrap.project.id, graph)
        repository.save_report_export(report.report_export, report.audit_event)
        repository.save_action_plan(
            actions=actions,
            schedule=schedule,
            comparison=None,
            audit_events=(action_audit,),
        )
        repository.save_content_engine(
            facts=facts,
            drafts=drafts,
            connectors=connectors,
            distribution_records=distribution_records,
            audit_event=content_audit,
        )
        repository.save_traceability_bundle(bundle)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        expected_tables = (
            "answer_runs",
            "raw_answers",
            "answer_citations",
            "evidence_assets",
            "collector_logs",
            "collection_costs",
            "answer_analyses",
            "visibility_score_snapshots",
            "score_contributions",
            "source_graphs",
            "source_gaps",
            "competitor_benchmarks",
            "report_exports",
            "action_recommendations",
            "retest_schedules",
            "localized_knowledge_facts",
            "content_drafts",
            "integration_connectors",
            "manual_distribution_records",
            "evidence_links",
            "traceability_bundles",
            "audit_events",
        )
        for table in expected_tables:
            self.assertIn(f"INSERT INTO {table}", executed_sql)
        self.assertGreaterEqual(connection.commit_count, 8)
        first_answer_run_insert = next(params for sql, params in connection.calls if "INSERT INTO answer_runs" in sql)
        self.assertEqual(str(first_answer_run_insert[0]), records[0].answer_run.id)
        first_analysis_insert = next(params for sql, params in connection.calls if "INSERT INTO answer_analyses" in sql)
        self.assertEqual(str(first_analysis_insert[0]), analysis_result.analyses[0].id)
        self.assertEqual(len(str(first_analysis_insert[0])), 36)

    def test_postgres_repository_persists_project_bootstrap_metadata(self) -> None:
        bootstrap = build_au_project_bootstrap()
        connection = RecordingConnection()

        PostgresEvidenceRepository(connection).save_project_bootstrap(bootstrap)

        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        expected_tables = (
            "market_profiles",
            "industry_profiles",
            "tenants",
            "projects",
            "project_members",
            "brand_entities",
            "competitor_entities",
            "prompt_questions",
            "audit_events",
        )
        for table in expected_tables:
            self.assertIn(f"INSERT INTO {table}", executed_sql)
        prompt_inserts = [params for sql, params in connection.calls if "INSERT INTO prompt_questions" in sql]
        competitor_inserts = [params for sql, params in connection.calls if "INSERT INTO competitor_entities" in sql]
        first_project_insert = next(params for sql, params in connection.calls if "INSERT INTO projects" in sql)
        first_prompt_insert = prompt_inserts[0]
        self.assertEqual(len(prompt_inserts), 100)
        self.assertEqual(len(competitor_inserts), 4)
        self.assertEqual(str(first_project_insert[0]), bootstrap.project.id)
        self.assertEqual(str(first_prompt_insert[0]), bootstrap.prompt_questions[0].id)
        self.assertEqual(first_prompt_insert[4], bootstrap.prompt_questions[0].text)
        self.assertEqual(connection.commit_count, 1)

    def test_runtime_repository_requires_database_url(self) -> None:
        with self.assertRaises(RuntimePersistenceError):
            build_repository_from_env({})

    def test_runtime_repository_uses_database_url_connector(self) -> None:
        seen_urls: list[str] = []
        connection = RecordingConnection()

        def connector(database_url: str) -> RecordingConnection:
            seen_urls.append(database_url)
            return connection

        repository = build_repository_from_env(
            {"DATABASE_URL": "postgresql://geno:geno@localhost:5432/geno"},
            connector=connector,
        )
        self.assertIsInstance(repository, PostgresEvidenceRepository)
        self.assertEqual(seen_urls, ["postgresql://geno:geno@localhost:5432/geno"])

    def test_postgres_repository_maps_collection_failures_to_audit_tables(self) -> None:
        bootstrap = build_au_project_bootstrap()
        failure = collect_prompt_with_failure_record(
            project_id=bootstrap.project.id,
            prompt=bootstrap.prompt_questions[0],
            market_profile=bootstrap.market_profile,
            collector=OpenAIWebSearchCollector(api_key=""),
            city="Australia",
            sample_index=1,
            sample_size=1,
        )
        self.assertIsInstance(failure, CollectionFailureRecord)
        assert isinstance(failure, CollectionFailureRecord)
        connection = RecordingConnection()
        PostgresEvidenceRepository(connection).save_collection_failure_records((failure,))
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO answer_runs", executed_sql)
        self.assertIn("INSERT INTO collector_logs", executed_sql)
        self.assertIn("INSERT INTO collection_costs", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        first_answer_run_insert = next(params for sql, params in connection.calls if "INSERT INTO answer_runs" in sql)
        self.assertEqual(first_answer_run_insert[19], "failed")
        self.assertEqual(connection.commit_count, 1)

    def test_postgres_repository_reads_runtime_evidence_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": answer_run_id,
                        "project_id": project_id,
                        "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
                        "platform": "perplexity",
                        "surface": "sonar",
                        "access_method": "official_api",
                        "market_code": "AU",
                        "city": "Australia",
                        "language": "en-AU",
                        "device": "desktop",
                        "answer_present": True,
                        "surface_triggered": True,
                        "sample_index": 1,
                        "sample_size": 1,
                        "model_or_surface": "sonar",
                        "account_state": "api_key",
                        "collector_backend_id": "fixture_perplexity_sonar",
                        "collector_version": "fixture-v1",
                        "collected_at": now,
                        "status": "completed",
                        "prompt_text": "Best mattresses in Australia",
                        "prompt_intent_type": "category_recommendation",
                        "prompt_priority": 1,
                        "prompt_version": "au_dtc_ecommerce_v1",
                    }
                ],
                {
                    "id": "5d714ed1-25aa-5651-b8b3-5e4b275d278a",
                    "answer_run_id": answer_run_id,
                    "answer_text": "answer",
                    "raw_payload": {"citations": 1},
                    "raw_payload_hash": "hash",
                    "created_at": now,
                },
                [
                    {
                        "id": "6e5c424e-1674-58ce-b075-6c52259bbbe5",
                        "answer_run_id": answer_run_id,
                        "url": "https://reviews.example/koala",
                        "domain": "reviews.example",
                        "position": 1,
                        "source_type": "review_site",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "29a279b8-3313-5306-a959-4f0f0de9c950",
                        "answer_run_id": answer_run_id,
                        "asset_type": "html_snapshot",
                        "url": "s3://asset.html",
                        "content_hash": "asset-hash",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "09e818ce-9c02-5fb4-af15-60f3fef55d55",
                        "answer_run_id": answer_run_id,
                        "collector_backend_id": "fixture_perplexity_sonar",
                        "event_type": "collection_completed",
                        "payload": {"answer_present": True},
                        "created_at": now,
                    }
                ],
                {
                    "id": "a428e674-b6ee-51cb-b59c-f0676654c46f",
                    "answer_run_id": answer_run_id,
                    "project_id": project_id,
                    "collector_backend_id": "fixture_perplexity_sonar",
                    "llm_provider": "perplexity",
                    "llm_tokens": 12,
                    "llm_cost": 0.001,
                    "proxy_or_vendor_cost": 0.001,
                    "compute_cost": 0.0005,
                    "total_cost": 0.0015,
                    "created_at": now,
                },
                [
                    {
                        "id": "495d24da-90cf-4073-bd9c-16afeb5b3169",
                        "event_type": "answer_run_collected",
                        "project_id": project_id,
                        "actor_type": "worker",
                        "actor_id": "fixture_perplexity_sonar",
                        "target_type": "answer_run",
                        "target_id": answer_run_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"prompt_question_ids": ["prompt"]},
                        "output_refs": {"answer_run_ids": [answer_run_id]},
                        "method_version": "fixture-v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_evidence_runs(
            project_id=project_id,
            platform="perplexity",
            status="completed",
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeEvidencePage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(len(page.records), 1)
        record = page.records[0]
        self.assertEqual(record.answer_run["id"], answer_run_id)
        self.assertEqual(record.answer_run["prompt_text"], "Best mattresses in Australia")
        self.assertEqual(record.answer_run["prompt_version"], "au_dtc_ecommerce_v1")
        self.assertEqual(record.raw_answer["raw_payload"]["citations"], 1)
        self.assertEqual(record.citations[0]["domain"], "reviews.example")
        self.assertEqual(record.evidence_assets[0]["asset_type"], "html_snapshot")
        self.assertEqual(record.collector_logs[0]["event_type"], "collection_completed")
        self.assertEqual(record.collection_cost["total_cost"], 0.0015)
        self.assertEqual(record.audit_events[0]["event_type"], "answer_run_collected")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM answer_runs ar WHERE ar.project_id = %s AND ar.platform = %s AND ar.status = %s", executed_sql)
        self.assertIn("LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id", executed_sql)
        self.assertIn("FROM raw_answers", executed_sql)

    def test_postgres_repository_reads_runtime_score_snapshot_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": snapshot_id,
                        "project_id": project_id,
                        "scope_type": "collection_slice",
                        "scope_value": "worker_runtime",
                        "formula_version": "au_visibility_v1",
                        "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
                        "final_score": 72.5,
                        "trigger_rate": 1.0,
                        "mention_rate": 1.0,
                        "recommendation_rate": 0.75,
                        "answer_run_ids": [answer_run_id],
                        "created_at": now,
                        "dispersion": 2.5,
                    }
                ],
                [
                    {
                        "id": "df03794b-e8fc-4b69-aa62-2304a55ff3a9",
                        "score_snapshot_id": snapshot_id,
                        "component_name": "MentionScore",
                        "component_score": 100.0,
                        "weight": 0.18,
                        "weighted_contribution": 18.0,
                        "denominator": "surface_triggered",
                        "evidence_answer_run_ids": [answer_run_id],
                        "positive_evidence_summary": "brand mentioned",
                        "negative_evidence_summary": "",
                        "confidence_note": "avg_parser_confidence=0.9",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": answer_run_id,
                        "project_id": project_id,
                        "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
                        "platform": "perplexity",
                        "surface": "sonar",
                        "access_method": "official_api",
                        "market_code": "AU",
                        "city": "Australia",
                        "language": "en-AU",
                        "device": "desktop",
                        "answer_present": True,
                        "surface_triggered": True,
                        "sample_index": 1,
                        "sample_size": 1,
                        "model_or_surface": "sonar",
                        "account_state": "api_key",
                        "collector_backend_id": "fixture_perplexity_sonar",
                        "collector_version": "fixture-v1",
                        "collected_at": now,
                        "status": "completed",
                        "prompt_text": "Is ExampleBrand good in Australia?",
                        "prompt_intent_type": "brand_awareness",
                        "prompt_priority": 1,
                        "prompt_version": "au_dtc_ecommerce_v1",
                    }
                ],
                {
                    "id": "d1466dad-237b-5f5f-b7cc-44e67d628d15",
                    "answer_run_id": answer_run_id,
                    "parser_engine_id": "rule_based_v1",
                    "analysis_version": "v1",
                    "payload": {"brand_mentioned": True},
                    "confidence": 0.9,
                    "created_at": now,
                },
                [
                    {
                        "id": "9b663656-4a0e-4fda-a764-0a4d62fa15f1",
                        "event_type": "visibility_score_snapshot_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.scoring",
                        "target_type": "visibility_score_snapshot",
                        "target_id": snapshot_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"score_snapshot_ids": [snapshot_id]},
                        "method_version": "au_visibility_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_score_snapshots(
            project_id=project_id,
            scope_type="collection_slice",
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeScoreSnapshotPage)
        self.assertEqual(page.total_count, 1)
        record = page.records[0]
        self.assertEqual(record.snapshot["final_score"], 72.5)
        self.assertEqual(record.contributions[0]["component_name"], "MentionScore")
        self.assertEqual(record.answer_runs[0].answer_run["prompt_text"], "Is ExampleBrand good in Australia?")
        self.assertEqual(record.answer_runs[0].analysis["payload"]["brand_mentioned"], True)
        self.assertEqual(record.audit_events[0]["event_type"], "visibility_score_snapshot_created")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM visibility_score_snapshots WHERE project_id = %s AND scope_type = %s", executed_sql)
        self.assertIn("FROM score_snapshot_runs ssr JOIN answer_runs ar ON ar.id = ssr.answer_run_id", executed_sql)
        self.assertIn("LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id", executed_sql)

    def test_postgres_repository_reads_runtime_citation_graph_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        source_graph_id = "41c2fd71-a32f-51a7-92e4-3d4c0f7ab1c2"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [{"project_id": project_id}],
                [
                    {
                        "id": source_graph_id,
                        "project_id": project_id,
                        "source_url": "https://reviews.example/koala",
                        "source_domain": "reviews.example",
                        "source_type": "review_site",
                        "topic": "reviews",
                        "source_gap_type": None,
                        "answer_run_ids": [answer_run_id],
                        "citation_count": 4,
                        "created_at": now,
                    }
                ],
                {
                    "id": answer_run_id,
                    "project_id": project_id,
                    "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
                    "platform": "perplexity",
                    "surface": "sonar",
                    "access_method": "official_api",
                    "market_code": "AU",
                    "city": "Australia",
                    "language": "en-AU",
                    "device": "desktop",
                    "answer_present": True,
                    "surface_triggered": True,
                    "sample_index": 1,
                    "sample_size": 1,
                    "model_or_surface": "sonar",
                    "account_state": "api_key",
                    "collector_backend_id": "fixture_perplexity_sonar",
                    "collector_version": "fixture-v1",
                    "collected_at": now,
                    "status": "completed",
                    "prompt_text": "Is ExampleBrand good in Australia?",
                    "prompt_intent_type": "brand_awareness",
                    "prompt_priority": 1,
                    "prompt_version": "au_dtc_ecommerce_v1",
                },
                [
                    {
                        "id": "36bf7c88-0d03-52a9-87f5-7f2a0e35e72a",
                        "source_graph_id": source_graph_id,
                        "answer_run_id": answer_run_id,
                        "answer_citation_id": "6e5c424e-1674-58ce-b075-6c52259bbbe5",
                        "relation_type": "cited_by_answer",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "7cc36d44-0f20-5681-8613-3998050e3267",
                        "project_id": project_id,
                        "source_type": "official_site",
                        "gap_type": "missing_high_weight_source_type",
                        "observed_count": 0,
                        "expected_weight": 0.95,
                        "recommendation": "Add official AU evidence",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "8c6e21aa-5df2-558e-ad5d-220b0de78a98",
                        "project_id": project_id,
                        "competitor_name": "Emma Sleep",
                        "metric_scope": "project",
                        "payload": {"mention_count": 2},
                        "answer_run_ids": [answer_run_id],
                        "created_at": now,
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_citation_graphs(
            project_id=project_id,
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeCitationGraphPage)
        self.assertEqual(page.total_count, 1)
        record = page.records[0]
        self.assertEqual(record.project_id, project_id)
        self.assertEqual(record.nodes[0].node["source_domain"], "reviews.example")
        self.assertEqual(record.nodes[0].answer_runs[0]["prompt_text"], "Is ExampleBrand good in Australia?")
        self.assertEqual(record.evidence_links[0]["relation_type"], "cited_by_answer")
        self.assertEqual(record.source_gaps[0]["source_type"], "official_site")
        self.assertEqual(record.competitor_benchmarks[0]["competitor_name"], "Emma Sleep")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM source_graphs WHERE project_id = %s", executed_sql)
        self.assertIn("FROM source_graph_evidence sge JOIN source_graphs sg ON sg.id = sge.source_graph_id", executed_sql)
        self.assertIn("FROM source_gaps", executed_sql)
        self.assertIn("FROM competitor_benchmarks", executed_sql)

    def test_postgres_repository_reads_runtime_report_export_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        source_graph_id = "41c2fd71-a32f-51a7-92e4-3d4c0f7ab1c2"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [snapshot_id],
            "answer_run_ids": [answer_run_id],
            "prompt_version": "au_dtc_ecommerce_v1",
            "scoring_formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
            "sample_size": 1,
            "window_start": now,
            "window_end": now,
            "methodology_hash": "methodology-hash",
            "markdown_url": "s3://geno-reports/report.md",
            "pdf_url": None,
            "csv_url": "s3://geno-reports/report.csv",
            "exported_by": "system",
            "exported_at": now,
        }
        answer_run_row = {
            "id": answer_run_id,
            "project_id": project_id,
            "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
            "platform": "perplexity",
            "surface": "sonar",
            "access_method": "official_api",
            "market_code": "AU",
            "city": "Australia",
            "language": "en-AU",
            "device": "desktop",
            "answer_present": True,
            "surface_triggered": True,
            "sample_index": 1,
            "sample_size": 1,
            "model_or_surface": "sonar",
            "account_state": "api_key",
            "collector_backend_id": "fixture_perplexity_sonar",
            "collector_version": "fixture-v1",
            "collected_at": now,
            "status": "completed",
            "prompt_text": "Is ExampleBrand good in Australia?",
            "prompt_intent_type": "brand_awareness",
            "prompt_priority": 1,
            "prompt_version": "au_dtc_ecommerce_v1",
        }
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [report_row],
                {
                    "id": snapshot_id,
                    "project_id": project_id,
                    "scope_type": "collection_slice",
                    "scope_value": "worker_runtime",
                    "formula_version": "au_visibility_v1",
                    "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
                    "final_score": 87.35,
                    "trigger_rate": 1.0,
                    "mention_rate": 1.0,
                    "recommendation_rate": 1.0,
                    "answer_run_ids": [answer_run_id],
                    "created_at": now,
                    "dispersion": 0.0,
                },
                answer_run_row,
                [
                    {
                        "id": "d5f57d79-4834-4bd3-92a3-a1c917fbb3cf",
                        "event_type": "report_export_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "markdown_csv_report_exporter_v1",
                        "target_type": "report_export",
                        "target_id": report_export_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"report_export_ids": [report_export_id]},
                        "method_version": "markdown_csv_report_exporter_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
                {"count": 1},
                [
                    {
                        "id": source_graph_id,
                        "project_id": project_id,
                        "source_url": "https://reviews.example/koala",
                        "source_domain": "reviews.example",
                        "source_type": "review_site",
                        "topic": "reviews",
                        "source_gap_type": None,
                        "answer_run_ids": [answer_run_id],
                        "citation_count": 1,
                        "created_at": now,
                    }
                ],
                answer_run_row,
                [],
                [],
                [],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_report_exports(
            project_id=project_id,
            report_type="worker_runtime",
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeReportExportPage)
        self.assertEqual(page.total_count, 1)
        record = page.records[0]
        self.assertEqual(record.report_export["report_version"], "worker-runtime-v1")
        self.assertEqual(record.score_snapshots[0]["final_score"], 87.35)
        self.assertEqual(record.answer_runs[0]["prompt_text"], "Is ExampleBrand good in Australia?")
        self.assertIsNotNone(record.citation_graph)
        assert record.citation_graph is not None
        self.assertEqual(record.citation_graph.nodes[0].node["source_domain"], "reviews.example")
        self.assertEqual(record.audit_events[0]["event_type"], "report_export_created")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM report_exports WHERE project_id = %s AND report_type = %s", executed_sql)
        self.assertIn("FROM report_evidence re JOIN answer_runs ar ON ar.id = re.answer_run_id", executed_sql)
        self.assertIn("SELECT count(*) FROM source_graphs WHERE project_id = %s", executed_sql)

    def test_postgres_repository_reads_runtime_action_plan_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        schedule_id = "7fbc98b0-6b37-529d-ad3c-1c70b8f6a880"
        action_id = "4cfd7cd0-a0cc-580f-b448-7b52f3b2937e"
        comparison_id = "fd17704e-8f18-5cb5-a1e4-28f6d0af62cf"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": schedule_id,
                        "project_id": project_id,
                        "prompt_version": "au_dtc_ecommerce_v1",
                        "sample_size": 1,
                        "offsets_days": [0, 7, 14, 30],
                        "scheduled_dates": [now],
                        "answer_run_ids": [answer_run_id],
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": action_id,
                        "project_id": project_id,
                        "title": "Strengthen AU review evidence",
                        "description": "Add review evidence",
                        "priority": "high",
                        "status": "open",
                        "owner_id": "system",
                        "source_gap_type": "missing_high_weight_source_type",
                        "evidence_answer_run_ids": [answer_run_id],
                        "related_source_types": ["review_site"],
                        "next_check_date": now,
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": comparison_id,
                        "project_id": project_id,
                        "baseline_score": 87.35,
                        "retest_score": 89.85,
                        "score_delta": 2.5,
                        "baseline_answer_run_ids": [answer_run_id],
                        "retest_answer_run_ids": [answer_run_id],
                        "trend": "improved",
                        "created_at": now,
                    }
                ],
                {
                    "id": answer_run_id,
                    "project_id": project_id,
                    "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
                    "platform": "perplexity",
                    "surface": "sonar",
                    "access_method": "official_api",
                    "market_code": "AU",
                    "city": "Australia",
                    "language": "en-AU",
                    "device": "desktop",
                    "answer_present": True,
                    "surface_triggered": True,
                    "sample_index": 1,
                    "sample_size": 1,
                    "model_or_surface": "sonar",
                    "account_state": "api_key",
                    "collector_backend_id": "fixture_perplexity_sonar",
                    "collector_version": "fixture-v1",
                    "collected_at": now,
                    "status": "completed",
                    "prompt_text": "Is ExampleBrand good in Australia?",
                    "prompt_intent_type": "brand_awareness",
                    "prompt_priority": 1,
                    "prompt_version": "au_dtc_ecommerce_v1",
                },
                [
                    {
                        "id": "425f980b-138f-4afa-8784-79d6f16f92ce",
                        "event_type": "action_plan_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.action_plan",
                        "target_type": "action_plan",
                        "target_id": schedule_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"retest_schedule_ids": [schedule_id]},
                        "method_version": "action_plan_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "e0d7a395-b585-481a-bffa-07c3375416fe",
                        "event_type": "retest_comparison_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.action_plan",
                        "target_type": "retest_comparison",
                        "target_id": comparison_id,
                        "before_hash": "before",
                        "after_hash": "after",
                        "input_refs": {"baseline_answer_run_ids": [answer_run_id]},
                        "output_refs": {"retest_comparison_ids": [comparison_id]},
                        "method_version": "retest_comparison_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_action_plans(
            project_id=project_id,
            status="open",
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeActionPlanPage)
        self.assertEqual(page.total_count, 1)
        record = page.records[0]
        self.assertEqual(record.retest_schedule["prompt_version"], "au_dtc_ecommerce_v1")
        self.assertEqual(record.action_recommendations[0]["status"], "open")
        self.assertEqual(record.retest_comparisons[0]["trend"], "improved")
        self.assertEqual(record.answer_runs[0]["prompt_text"], "Is ExampleBrand good in Australia?")
        self.assertEqual(record.audit_events[0]["event_type"], "action_plan_created")
        self.assertEqual(record.audit_events[1]["event_type"], "retest_comparison_created")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM retest_schedules rs WHERE rs.project_id = %s", executed_sql)
        self.assertIn("FROM action_recommendations WHERE project_id = %s AND status = %s", executed_sql)
        self.assertIn("FROM retest_comparisons", executed_sql)
        self.assertIn("WHERE target_type = %s AND target_id = %s", executed_sql)


if __name__ == "__main__":
    unittest.main()
