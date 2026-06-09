from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

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
from geno_core.market import build_au_market_profile
from geno_core.models import AnswerAnalysis, CollectionFailureRecord, ReportExport
from geno_core.prompt_pack import INTENT_WEIGHTS
from geno_core.parser import RuleBasedAnswerParser
from geno_core.report import MarkdownCsvReportExporter
from geno_core.scoring import AU_VISIBILITY_V1, score_answer_analysis


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


if __name__ == "__main__":
    unittest.main()
