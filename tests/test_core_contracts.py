from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID

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
    build_collection_run_audit_event,
    build_collection_run_summary,
    build_manual_backfill_record,
    build_p0a_collection_plan,
    collect_prompt_with_failure_record,
    evaluate_p0a_collection_readiness,
    run_collection_slice,
    run_fixture_collection_slice,
)
from geno_core.contracts import CollectorBackend, ParserEngine, ReportExporter, ScoringFormula
from geno_core.collectors import (
    FixtureGoogleAIModeCollector,
    FixtureGoogleAIOCollector,
    FixtureOpenAIWebSearchCollector,
    FixturePerplexitySonarCollector,
    FixtureThirdPartySerpCollector,
    OpenAIWebSearchCollector,
    PerplexitySonarCollector,
)
from geno_core.geo import StaticAUGeoProvider
from geno_core.fidelity import build_runtime_fidelity_check
from geno_core.google_spike import (
    build_google_spike_plan,
    evaluate_google_spike_gate,
    evaluate_google_spike_readiness_gate,
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
from geno_core.llm_gateway import FixtureLLMGateway
from geno_core.market import build_au_market_profile
from geno_core.models import (
    AnswerAnalysis,
    CollectionFailureRecord,
    EntityAliasInput,
    ManualBackfillInput,
    ReportExport,
    RuntimeEvidencePage,
    RuntimeEvidenceExport,
    RuntimeEntityAlias,
    RuntimeEntityAliasCandidatePage,
    RuntimeEntityAliasPage,
    RuntimeFidelityCheck,
    RuntimeFidelityCheckPage,
    RuntimeHumanReviewInput,
    RuntimeHumanReviewPage,
    RuntimeHumanReviewRecord,
    RuntimeCitationGraphPage,
    RuntimeProjectBrandKit,
    RuntimeProjectBrandKitInput,
    RuntimePromptImportInput,
    RuntimePromptImportResult,
    RuntimeActionPlanPage,
    RuntimeContentEnginePage,
    RuntimeCollectionRunPage,
    RuntimeScoreSnapshotPage,
    RuntimeReportArtifact,
    RuntimeReportExportPage,
    RuntimeSavedView,
    RuntimeSavedViewInput,
    RuntimeSavedViewPage,
    RuntimeScoreWeightConfig,
    RuntimeScoreWeightConfigInput,
    RuntimeTraceabilityDetail,
)
from geno_core.object_store import S3CompatibleObjectStore, archive_report_artifacts
from geno_core.prompt_pack import INTENT_WEIGHTS
from geno_core.parser import ComparativeAnswerParser, LLMJudgeAnswerParser, RuleBasedAnswerParser
from geno_core.report import MarkdownCsvReportExporter
from geno_core.repository import PostgresEvidenceRepository
from geno_core.runtime import RuntimePersistenceError, build_repository_from_env
from geno_core.scoring import (
    AU_VISIBILITY_V1,
    AU_VISIBILITY_V1_1_LOCAL_BOOST,
    RegistryScoringFormula,
    get_score_formula,
    list_score_formulas,
    normalize_score_weights,
    rescore_snapshot_with_formula,
    score_answer_analysis,
)
from geno_core.stubs import (
    NotConfiguredCollectorBackend,
    NotConfiguredParserEngine,
    NotConfiguredReportExporter,
    NotConfiguredScoringFormula,
)
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

    def test_p0a_pluggable_interfaces_have_stubs_and_working_implementations(self) -> None:
        collector_stub = NotConfiguredCollectorBackend(
            "collector.not_configured",
            "chatgpt",
            "chatgpt_search",
            "official_api",
        )
        parser_stub = NotConfiguredParserEngine()
        scoring_stub = NotConfiguredScoringFormula()
        report_stub = NotConfiguredReportExporter()

        self.assertIsInstance(collector_stub, CollectorBackend)
        self.assertIsInstance(parser_stub, ParserEngine)
        self.assertIsInstance(scoring_stub, ScoringFormula)
        self.assertIsInstance(report_stub, ReportExporter)
        self.assertEqual(collector_stub.health(), "not_configured")
        self.assertEqual(parser_stub.parser_engine_id, "parser.not_configured")
        self.assertEqual(scoring_stub.formula_version, "scoring.not_configured")
        self.assertEqual(report_stub.exporter_id, "report_exporter.not_configured")

        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        collector = FixturePerplexitySonarCollector()
        parser = RuleBasedAnswerParser()
        scoring_formula = RegistryScoringFormula("au_visibility_v1_1_local_boost")
        report_exporter = MarkdownCsvReportExporter()
        self.assertIsInstance(collector, CollectorBackend)
        self.assertIsInstance(parser, ParserEngine)
        self.assertIsInstance(scoring_formula, ScoringFormula)
        self.assertIsInstance(report_exporter, ReportExporter)

        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(collector,),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        analysis = parser.parse_record(
            record=records[0],
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
        )
        score_result = scoring_formula.score_analyses(
            project_id=bootstrap.project.id,
            analyses=(analysis,),
            platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25},
            scope_type="interface_contract",
            scope_value="p0a",
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=records,
            analyses=(analysis,),
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        report = report_exporter.export(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            report_version="interface-contract-v1",
            report_type="contract_fixture",
            prompt_version=bootstrap.project.prompt_version,
            snapshot=score_result.snapshot,
            contributions=tuple(score_result.contributions),
            records=records,
            graph=graph,
            platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25},
        )

        self.assertEqual(analysis.parser_engine_id, "rule_based_v2_aliases")
        self.assertEqual(score_result.snapshot.formula_version, "au_visibility_v1_1_local_boost")
        self.assertIn("Trigger rate", report.markdown)
        self.assertIn("Mention rate", report.markdown)
        self.assertIn("Recommendation rate", report.markdown)
        self.assertEqual(report.report_export.scoring_formula_version, "au_visibility_v1_1_local_boost")

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
        self.assertEqual(result.snapshot.component_weights_snapshot, AU_VISIBILITY_V1)

    def test_score_weights_are_configurable_and_frozen_in_snapshot(self) -> None:
        weights = normalize_score_weights(
            {
                **AU_VISIBILITY_V1,
                "MentionScore": 0.20,
                "FreshnessScore": 0.03,
            }
        )
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
            score_weights=weights,
        )

        self.assertEqual(result.snapshot.component_weights_snapshot, weights)
        self.assertEqual({item.component_name: item.weight for item in result.contributions}, weights)
        self.assertAlmostEqual(sum(result.snapshot.component_weights_snapshot.values()), 1.0)

    def test_score_formula_registry_supports_versioned_replay(self) -> None:
        self.assertEqual(get_score_formula("au_visibility_v1").weights, AU_VISIBILITY_V1)
        self.assertEqual(get_score_formula("au_visibility_v1_1_local_boost").weights, AU_VISIBILITY_V1_1_LOCAL_BOOST)
        self.assertTrue(any(item["formula_version"] == "au_visibility_v1_1_local_boost" for item in list_score_formulas()))
        analysis = AnswerAnalysis(
            id="analysis-1",
            answer_run_id="run-1",
            parser_engine_id="rule",
            analysis_version="v1",
            brand_mentioned=True,
            brand_recommended=True,
            brand_position=1,
            competitors_mentioned=["competitor"],
            citation_count=1,
            local_relevance_score=40.0,
            sentiment_score=80.0,
            freshness_score=30.0,
            competitor_share_score=40.0,
            confidence=0.92,
        )
        baseline = rescore_snapshot_with_formula(
            project_id="project-1",
            analyses=(analysis,),
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            target_formula_version="au_visibility_v1",
        )
        local_boost = rescore_snapshot_with_formula(
            project_id="project-1",
            analyses=(analysis,),
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            target_formula_version="au_visibility_v1_1_local_boost",
        )

        self.assertEqual(baseline.snapshot.formula_version, "au_visibility_v1")
        self.assertEqual(local_boost.snapshot.formula_version, "au_visibility_v1_1_local_boost")
        self.assertEqual(local_boost.snapshot.component_weights_snapshot, AU_VISIBILITY_V1_1_LOCAL_BOOST)
        self.assertNotEqual(baseline.snapshot.final_score, local_boost.snapshot.final_score)
        self.assertEqual(local_boost.audit_event.event_type, "visibility_score_snapshot_rescored")
        self.assertEqual(local_boost.audit_event.method_version, "au_visibility_v1_1_local_boost")

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
            method_disclosure={},
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

    def test_m1_project_bootstrap_accepts_client_project_configuration(self) -> None:
        bootstrap = build_au_project_bootstrap(
            tenant_name="Agency Client AU",
            project_name="Koala Mattress GEO Pilot",
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
            brand_official_domains=("koala.com",),
            brand_parent_company="Koala",
            brand_product_lines=("Mattress", "Sofa Bed"),
            owner_user_id="agency-owner",
        )

        self.assertEqual(bootstrap.tenant.name, "Agency Client AU")
        self.assertEqual(bootstrap.project.name, "Koala Mattress GEO Pilot")
        self.assertEqual(bootstrap.project.target_brand, "Koala")
        self.assertEqual(bootstrap.brand.official_domains, ("koala.com",))
        self.assertEqual(bootstrap.brand.parent_company, "Koala")
        self.assertEqual(bootstrap.brand.product_lines, ("Mattress", "Sofa Bed"))
        self.assertEqual([competitor.canonical_name for competitor in bootstrap.competitors], ["Emma Sleep", "Sleeping Duck", "Ecosa"])
        self.assertEqual(bootstrap.members[0].user_id, "agency-owner")
        self.assertEqual(len(bootstrap.prompt_questions), 100)
        self.assertTrue(all(prompt.project_id == bootstrap.project.id for prompt in bootstrap.prompt_questions))
        self.assertTrue(any("Koala" in prompt.text for prompt in bootstrap.prompt_questions))
        self.assertEqual(bootstrap.audit_events[0].after_hash is not None, True)

    def test_m1_project_bootstrap_audit_event_id_is_stable(self) -> None:
        first = build_au_project_bootstrap()
        second = build_au_project_bootstrap()

        self.assertEqual(first.project.id, second.project.id)
        self.assertEqual(first.audit_events[0].id, second.audit_events[0].id)

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

    def test_m2a_p0a_collection_readiness_gate_passes_fixture_k3(self) -> None:
        bootstrap = build_au_project_bootstrap()
        records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia",),
            sample_size=3,
            prompt_limit=1,
        )
        gate = evaluate_p0a_collection_readiness(records=records)

        self.assertEqual(gate.gate_status, "pass")
        self.assertEqual(gate.required_platforms, ("chatgpt", "perplexity"))
        self.assertEqual(set(gate.observed_platforms), {"chatgpt", "perplexity"})
        self.assertEqual(gate.required_sample_size, 3)
        self.assertEqual(gate.observed_sample_sizes, (3,))
        self.assertEqual(gate.attempted_runs, 6)
        self.assertEqual(gate.success_count, 6)
        self.assertEqual(gate.failure_count, 0)
        self.assertEqual(gate.failure_reasons, ())
        self.assertEqual(gate.records_without_citations, ())
        self.assertEqual(gate.records_without_evidence_assets, ())
        self.assertEqual(gate.records_without_answer_flags, ())
        self.assertEqual(gate.records_below_sample_size, ())

    def test_m2a_p0a_collection_readiness_gate_explains_failures(self) -> None:
        class NoAssetChatGPTCollector(FixtureOpenAIWebSearchCollector):
            def collect(self, **kwargs):  # type: ignore[no-untyped-def]
                result = super().collect(**kwargs)
                return result.__class__(
                    answer_present=result.answer_present,
                    surface_triggered=result.surface_triggered,
                    answer_text=result.answer_text,
                    citations=result.citations,
                    screenshot_url=None,
                    html_snapshot_url=None,
                    raw_payload=result.raw_payload,
                    model_or_surface=result.model_or_surface,
                    account_state=result.account_state,
                    collector_version=result.collector_version,
                )

        bootstrap = build_au_project_bootstrap()
        success = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )[0]
        failure = collect_prompt_with_failure_record(
            project_id=bootstrap.project.id,
            prompt=bootstrap.prompt_questions[0],
            market_profile=bootstrap.market_profile,
            collector=OpenAIWebSearchCollector(api_key=""),
            city="Australia",
            sample_index=1,
            sample_size=1,
        )
        gate = evaluate_p0a_collection_readiness(records=(success, failure))

        self.assertEqual(gate.gate_status, "fail")
        self.assertEqual(gate.attempted_runs, 2)
        self.assertEqual(gate.success_count, 1)
        self.assertEqual(gate.failure_count, 1)
        self.assertIn("collection_failures=1", gate.failure_reasons)
        self.assertIn("below_required_sample_size=2", gate.failure_reasons)
        self.assertEqual(gate.records_below_sample_size, (success.answer_run.id, failure.answer_run.id))
        self.assertEqual(gate.records_without_citations, ())
        self.assertEqual(gate.records_without_evidence_assets, ())

        api_record = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(NoAssetChatGPTCollector(),),
            cities=("Australia",),
            sample_size=3,
            prompt_limit=1,
        )[0]
        asset_gate = evaluate_p0a_collection_readiness(records=(api_record,))
        self.assertEqual(asset_gate.gate_status, "fail")
        self.assertIn("missing_platforms=perplexity", asset_gate.failure_reasons)
        self.assertIn("records_without_evidence_assets=1", asset_gate.failure_reasons)
        self.assertEqual(asset_gate.records_without_evidence_assets, (api_record.answer_run.id,))

    def test_m2a_collection_run_summary_explains_success_cost_and_failures(self) -> None:
        bootstrap = build_au_project_bootstrap()
        success = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )[0]
        failure = collect_prompt_with_failure_record(
            project_id=bootstrap.project.id,
            prompt=bootstrap.prompt_questions[0],
            market_profile=bootstrap.market_profile,
            collector=OpenAIWebSearchCollector(api_key=""),
            city="Australia",
            sample_index=1,
            sample_size=1,
        )

        summary = build_collection_run_summary(
            project_id=bootstrap.project.id,
            run_type="p0a_slice",
            mode="fixture",
            planned_runs=2,
            records=(success, failure),
        )
        audit_event = build_collection_run_audit_event(summary)

        self.assertEqual(summary.planned_runs, 2)
        self.assertEqual(summary.attempted_runs, 2)
        self.assertEqual(summary.success_count, 1)
        self.assertEqual(summary.failure_count, 1)
        self.assertEqual(summary.success_rate, 0.5)
        self.assertEqual(summary.trigger_rate, 0.5)
        self.assertEqual(summary.answer_present_rate, 0.5)
        self.assertAlmostEqual(summary.total_cost, 0.0026)
        self.assertAlmostEqual(summary.average_cost_per_run, 0.0013)
        self.assertGreaterEqual(summary.total_duration_ms, 0)
        self.assertGreaterEqual(summary.average_duration_ms, 0)
        self.assertEqual(summary.platform_distribution, {"chatgpt": 1, "perplexity": 1})
        self.assertEqual(summary.city_distribution, {"Australia": 2})
        self.assertEqual(summary.access_method_distribution, {"official_api": 2})
        self.assertEqual(summary.failure_summary, {"OPENAI_API_KEY is required": 1})
        self.assertEqual(len(summary.answer_run_ids), 2)
        self.assertEqual(audit_event.event_type, "collection_run_summarized")
        self.assertEqual(audit_event.target_type, "collection_run")
        self.assertEqual(audit_event.target_id, summary.id)
        self.assertEqual(audit_event.method_version, "collection_run_summary_v1")
        self.assertIsNotNone(audit_event.after_hash)
        self.assertEqual(audit_event.input_refs["answer_run_ids"], list(summary.answer_run_ids))
        self.assertEqual(audit_event.output_refs["collection_run_ids"], [summary.id])

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

    def test_manual_backfill_builds_auditable_raw_evidence_record(self) -> None:
        bootstrap = build_au_project_bootstrap()
        prompt = bootstrap.prompt_questions[0]
        record = build_manual_backfill_record(
            ManualBackfillInput(
                project_id=bootstrap.project.id,
                prompt_question_id=prompt.id,
                prompt_text=prompt.text,
                market_code=prompt.market_code,
                city=prompt.city,
                language=prompt.language,
                platform="google",
                surface="google_ai_mode",
                answer_text="Manual Google AI Mode answer mentioning ExampleBrand with sources.",
                citation_urls=("https://examplebrand.example/au/manual", "https://reviews.example/manual"),
                screenshot_url="s3://manual-backfill/examplebrand-google-ai-mode.png",
                html_snapshot_url="s3://manual-backfill/examplebrand-google-ai-mode.html",
                submitted_by="analyst@example.com",
                notes="Backfilled during Google AI Mode spike",
            )
        )
        self.assertEqual(record.answer_run.access_method, "manual")
        self.assertEqual(record.answer_run.platform, "google")
        self.assertEqual(record.answer_run.surface, "google_ai_mode")
        self.assertEqual(record.answer_run.collector_backend_id, "google.manual_backfill")
        self.assertEqual(record.raw_answer.raw_payload["source"], "manual_backfill")
        self.assertEqual(len(record.citations), 2)
        self.assertEqual(record.citations[0].domain, "examplebrand.example")
        self.assertEqual(len(record.evidence_assets), 2)
        self.assertEqual(record.collection_cost.total_cost, 0.0)
        self.assertEqual(record.collector_logs[0].event_type, "manual_backfill_recorded")
        self.assertEqual(record.audit_events[0].event_type, "manual_backfill_recorded")
        self.assertEqual(record.audit_events[0].actor_type, "user")
        self.assertEqual(record.audit_events[0].actor_id, "analyst@example.com")
        self.assertTrue(record.raw_answer.raw_payload_hash)

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

    def test_m2b_google_spike_readiness_requires_two_collection_paths(self) -> None:
        bootstrap = build_au_project_bootstrap()
        plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        browser_only_records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=select_google_spike_prompts(bootstrap.prompt_questions),
            market_profile=bootstrap.market_profile,
            collectors=(FixtureGoogleAIOCollector(), FixtureGoogleAIModeCollector()),
            cities=plan.geo_cities,
            sample_size=plan.sample_size,
            prompt_limit=plan.prompt_count,
        )
        browser_only_gate = evaluate_google_spike_readiness_gate(
            project_id=bootstrap.project.id,
            plan=plan,
            records=browser_only_records,
        )
        self.assertEqual(browser_only_gate.gate_status, "fail")
        self.assertEqual(browser_only_gate.observed_access_methods, ("browser",))
        self.assertIn("insufficient_collection_paths=1/2", browser_only_gate.failure_reasons)

        multi_path_records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=select_google_spike_prompts(bootstrap.prompt_questions),
            market_profile=bootstrap.market_profile,
            collectors=(FixtureGoogleAIOCollector(), FixtureThirdPartySerpCollector()),
            cities=plan.geo_cities,
            sample_size=plan.sample_size,
            prompt_limit=plan.prompt_count,
        )
        multi_path_gate = evaluate_google_spike_readiness_gate(
            project_id=bootstrap.project.id,
            plan=plan,
            records=multi_path_records,
        )
        self.assertEqual(multi_path_gate.gate_status, "pass")
        self.assertEqual(set(multi_path_gate.observed_access_methods), {"browser", "third_party_api"})
        self.assertEqual(multi_path_gate.completed_runs, 240)
        self.assertEqual(multi_path_gate.screenshot_or_html_runs, 240)
        self.assertEqual(multi_path_gate.failure_reasons, ())

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
        self.assertEqual(analysis.parser_engine_id, "rule_based_v2_aliases")

    def test_m3_comparative_parser_records_judge_result_and_agreement(self) -> None:
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
        judge_analysis = LLMJudgeAnswerParser().parse_record(
            record=records[0],
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
        )
        analysis = ComparativeAnswerParser().parse_record(
            record=records[0],
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
        )
        self.assertEqual(judge_analysis.parser_engine_id, "llm_judge_fixture_v1")
        self.assertEqual(analysis.parser_engine_id, "rule_based_v2_aliases")
        self.assertEqual(analysis.analysis_version, "rule_based_v2_aliases+llm_judge_fixture_v1")
        self.assertIsNotNone(analysis.parser_comparison)
        comparison = analysis.parser_comparison or {}
        self.assertEqual(comparison["secondary_parser_engine_id"], "llm_judge_fixture_v1")
        self.assertEqual(comparison["comparison_method_version"], "parser_ab_compare_v1")
        self.assertIn("agreement_rate", comparison)
        self.assertGreaterEqual(comparison["agreement_rate"], 0)
        self.assertLessEqual(comparison["agreement_rate"], 1)
        self.assertIn("secondary_result", comparison)
        self.assertEqual(comparison["secondary_prompt_version"], "llm_judge_prompt_v1")
        call_log = comparison["secondary_result"]["llm_call_log"]
        self.assertEqual(call_log["purpose"], "parser_judge")
        self.assertEqual(call_log["provider"], "fixture")
        self.assertEqual(call_log["model"], "local-fixture-judge")
        self.assertEqual(call_log["prompt_version"], "llm_judge_prompt_v1")
        self.assertEqual(call_log["status"], "succeeded")
        self.assertGreater(call_log["total_tokens"], 0)
        self.assertEqual(len(call_log["request_hash"]), 64)
        self.assertEqual(len(call_log["response_hash"]), 64)

    def test_m0_fixture_llm_gateway_records_auditable_chat_log(self) -> None:
        gateway = FixtureLLMGateway()

        response = gateway.chat(
            messages=[{"role": "user", "content": "Judge Koala in Australia."}],
            model="local-fixture-judge",
            metadata={"project_id": "project-1", "answer_run_id": "run-1", "purpose": "parser_judge"},
        )

        call_log = response["call_log"]
        self.assertEqual(call_log["project_id"], "project-1")
        self.assertEqual(call_log["answer_run_id"], "run-1")
        self.assertEqual(call_log["purpose"], "parser_judge")
        self.assertEqual(call_log["provider"], "fixture")
        self.assertEqual(call_log["status"], "succeeded")
        self.assertGreater(call_log["prompt_tokens"], 0)
        self.assertGreater(call_log["completion_tokens"], 0)
        self.assertEqual(call_log["total_tokens"], call_log["prompt_tokens"] + call_log["completion_tokens"])

    def test_m3_rule_parser_uses_confirmed_entity_aliases(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        prompt = bootstrap.prompt_questions[0]
        record = build_manual_backfill_record(
            ManualBackfillInput(
                project_id=bootstrap.project.id,
                prompt_question_id=prompt.id,
                prompt_text=prompt.text,
                market_code=prompt.market_code,
                city=prompt.city,
                language=prompt.language,
                platform="google",
                surface="google_ai_mode",
                answer_text=(
                    "K-Brand AU is a good choice in Sydney. "
                    "Emma-Sleep-AU is also visible in Australian recommendations."
                ),
                citation_urls=("https://example.com/koala-alias",),
            )
        )
        analysis = RuleBasedAnswerParser().parse_record(
            record=record,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            entity_aliases={
                bootstrap.brand.id: ("K-Brand AU",),
                bootstrap.competitors[0].id: ("Emma-Sleep-AU",),
            },
        )
        self.assertTrue(analysis.brand_mentioned)
        self.assertTrue(analysis.brand_recommended)
        self.assertEqual(analysis.brand_position, 1)
        self.assertEqual(analysis.competitors_mentioned, ["Emma Sleep"])
        self.assertIn("brand_alias_matched", analysis.uncertainty_flags)
        self.assertIn("competitor_alias_matched:Emma Sleep", analysis.uncertainty_flags)
        self.assertNotIn("brand_not_mentioned", analysis.uncertainty_flags)

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
        self.assertTrue(all(analysis.parser_comparison for analysis in result.analyses))
        self.assertTrue(all("parser_ab_agreement=" in item.confidence_note for item in result.contributions))
        self.assertEqual(contribution_total, result.snapshot.final_score)
        self.assertGreater(result.snapshot.mention_rate, 0)
        self.assertLessEqual(result.snapshot.mention_rate, 1)
        self.assertGreaterEqual(result.snapshot.dispersion, 0)
        self.assertEqual(result.audit_event.event_type, "visibility_score_snapshot_created")
        self.assertEqual(
            result.audit_event.output_refs["score_snapshot_ids"],
            [result.snapshot.id],
        )

    def test_m3_score_input_policy_excludes_google_until_both_spike_gates_pass(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        stable_records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        google_records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=select_google_spike_prompts(bootstrap.prompt_questions),
            market_profile=bootstrap.market_profile,
            collectors=(FixtureGoogleAIOCollector(), FixtureGoogleAIModeCollector()),
            cities=plan.geo_cities,
            sample_size=plan.sample_size,
            prompt_limit=plan.prompt_count,
        )
        google_gate = evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=plan, records=google_records)
        browser_only_readiness_gate = evaluate_google_spike_readiness_gate(
            project_id=bootstrap.project.id,
            plan=plan,
            records=google_records,
        )
        limited_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=stable_records + google_records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            google_spike_gate=google_gate,
            google_spike_readiness_gate=browser_only_readiness_gate,
        )
        self.assertEqual(len(limited_result.analyses), len(stable_records) + len(google_records))
        self.assertEqual(len(limited_result.score_input_analyses), len(stable_records))
        self.assertEqual(set(limited_result.snapshot.answer_run_ids), {record.answer_run.id for record in stable_records})
        self.assertEqual(limited_result.score_input_policy["google_gate_status"], "pass")
        self.assertEqual(limited_result.score_input_policy["google_readiness_gate_status"], "fail")
        self.assertFalse(limited_result.score_input_policy["google_main_scoring_allowed"])
        self.assertEqual(limited_result.score_input_policy["excluded_google_record_count"], len(google_records))
        self.assertEqual(
            limited_result.audit_event.input_refs["score_input_answer_run_ids"],
            [record.answer_run.id for record in stable_records],
        )
        self.assertEqual(
            set(limited_result.audit_event.input_refs["excluded_google_answer_run_ids"]),
            {record.answer_run.id for record in google_records},
        )
        self.assertTrue(
            all("excluded_answer_runs=240" in contribution.confidence_note for contribution in limited_result.contributions)
        )

        multi_path_google_records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=select_google_spike_prompts(bootstrap.prompt_questions),
            market_profile=bootstrap.market_profile,
            collectors=(FixtureGoogleAIOCollector(), FixtureThirdPartySerpCollector()),
            cities=plan.geo_cities,
            sample_size=plan.sample_size,
            prompt_limit=plan.prompt_count,
        )
        multi_path_gate = evaluate_google_spike_gate(
            project_id=bootstrap.project.id,
            plan=plan,
            records=multi_path_google_records,
        )
        multi_path_readiness_gate = evaluate_google_spike_readiness_gate(
            project_id=bootstrap.project.id,
            plan=plan,
            records=multi_path_google_records,
        )
        allowed_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=stable_records + multi_path_google_records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            google_spike_gate=multi_path_gate,
            google_spike_readiness_gate=multi_path_readiness_gate,
        )
        self.assertTrue(allowed_result.score_input_policy["google_main_scoring_allowed"])
        self.assertEqual(allowed_result.score_input_policy["excluded_google_record_count"], 0)
        self.assertEqual(len(allowed_result.score_input_analyses), len(stable_records) + len(multi_path_google_records))

    def test_m3_analysis_pipeline_scores_alias_only_mentions(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        prompt = bootstrap.prompt_questions[0]
        record = build_manual_backfill_record(
            ManualBackfillInput(
                project_id=bootstrap.project.id,
                prompt_question_id=prompt.id,
                prompt_text=prompt.text,
                market_code=prompt.market_code,
                city=prompt.city,
                language=prompt.language,
                platform="perplexity",
                surface="sonar",
                answer_text="K-Brand AU is recommended for Australian mattress shoppers.",
                citation_urls=("https://example.com/k-brand",),
            )
        )
        without_alias = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=(record,),
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        with_alias = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=(record,),
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            entity_aliases={bootstrap.brand.id: ("K-Brand AU",)},
        )
        self.assertEqual(without_alias.snapshot.mention_rate, 0.0)
        self.assertEqual(with_alias.snapshot.mention_rate, 1.0)
        self.assertEqual(with_alias.snapshot.recommendation_rate, 1.0)
        self.assertIn("brand_alias_matched", with_alias.analyses[0].uncertainty_flags)

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
            score_input_policy=analysis_result.score_input_policy,
        )
        self.assertEqual(report.report_export.score_snapshot_ids, (analysis_result.snapshot.id,))
        self.assertEqual(report.report_export.answer_run_ids, tuple(record.answer_run.id for record in records))
        self.assertTrue(report.report_export.markdown_url.endswith(".md"))
        assert report.report_export.pdf_url is not None
        self.assertTrue(report.report_export.pdf_url.endswith(".pdf"))
        self.assertTrue(report.report_export.csv_url.endswith(".csv"))
        self.assertIn("GENO AU Evidence Report", report.markdown)
        self.assertIn("### Method Disclosure", report.markdown)
        self.assertIn("Google spike gate: not_run", report.markdown)
        self.assertIn("Google limited coverage: yes", report.markdown)
        self.assertIn("Main scoring Google allowed: False", report.markdown)
        self.assertIn("Main scoring records: 40", report.markdown)
        self.assertIn("Excluded Google records from main scoring: 0", report.markdown)
        self.assertIn("API-vs-browser fidelity: not_run", report.markdown)
        self.assertIn("Trigger rate denominator: all attempted evidence records in this report window", report.markdown)
        self.assertIn("Mention rate denominator: surface_triggered evidence records, not all attempted records", report.markdown)
        self.assertIn(
            "Recommendation rate denominator: surface_triggered evidence records, not all attempted records",
            report.markdown,
        )
        self.assertIn("Report evidence attempted records: 40", report.markdown)
        self.assertIn("Report evidence surface-triggered records: 40", report.markdown)
        self.assertIn("Access method distribution", report.markdown)
        score_rate_disclosure = report.report_export.method_disclosure["score_rate_denominators"]
        self.assertEqual(
            score_rate_disclosure["definitions"]["trigger_rate"]["formula"],
            "surface_triggered_records / attempted_records",
        )
        self.assertEqual(
            score_rate_disclosure["definitions"]["mention_rate"]["denominator"],
            "surface_triggered evidence records, not all attempted records",
        )
        self.assertEqual(score_rate_disclosure["evidence_denominators"]["attempted_records"], len(records))
        self.assertEqual(score_rate_disclosure["evidence_denominators"]["surface_triggered_records"], len(records))
        self.assertEqual(report.report_export.method_disclosure["score_input_policy"], analysis_result.score_input_policy)
        self.assertIn("answer_run_id", report.csv_content)
        self.assertTrue(report.pdf_content.startswith(b"%PDF-1.4"))
        self.assertIn(b"%%EOF", report.pdf_content)
        self.assertEqual(report.audit_event.event_type, "report_export_created")
        self.assertEqual(report.audit_event.output_refs["report_export_ids"], [report.report_export.id])
        self.assertEqual(report.report_evidence_answer_run_ids, report.report_export.answer_run_ids)

    def test_report_artifacts_archive_to_s3_compatible_store(self) -> None:
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
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25},
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
            platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25},
        )
        requests: list[tuple[str, str, dict[str, str], bytes]] = []

        def requester(
            method: str,
            url: str,
            headers: object,
            body: bytes,
        ) -> tuple[int, dict[str, str], bytes]:
            requests.append((method, url, dict(headers), body))
            return 200, {"ETag": '"test-etag"'}, b""

        store = S3CompatibleObjectStore(
            endpoint="http://minio:9000",
            bucket="geno-reports",
            access_key="minio",
            secret_key="minio123",
            requester=requester,
        )
        stored = archive_report_artifacts(report, store)

        self.assertEqual(len(stored), 3)
        self.assertEqual(
            [item.content_type for item in stored],
            ["text/markdown; charset=utf-8", "application/pdf", "text/csv; charset=utf-8"],
        )
        self.assertTrue(all(item.uri.startswith("s3://geno-reports/") for item in stored))
        self.assertTrue(all(item.content_hash for item in stored))
        object_puts = [item for item in requests if item[0] == "PUT" and item[1].count("/") > 3]
        self.assertEqual(len(object_puts), 3)
        self.assertTrue(any(item[1].endswith(".pdf") and item[3].startswith(b"%PDF-1.4") for item in object_puts))

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
        fidelity_check, fidelity_audit = build_runtime_fidelity_check(
            project_id=bootstrap.project.id,
            report_export_id=report.report_export.id,
            answer_run_rows=tuple(
                {
                    "id": record.answer_run.id,
                    "prompt_question_id": record.answer_run.prompt_question_id,
                    "access_method": record.answer_run.access_method,
                    "city": record.answer_run.city,
                    "answer_present": record.answer_run.answer_present,
                    "surface_triggered": record.answer_run.surface_triggered,
                }
                for record in records
            ),
            checked_by="unit-test",
        )
        repository.save_fidelity_check(fidelity_check, fidelity_audit)
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
            "llm_call_logs",
            "visibility_score_snapshots",
            "score_contributions",
            "source_graphs",
            "source_gaps",
            "competitor_benchmarks",
            "report_exports",
            "api_browser_fidelity_checks",
            "action_recommendations",
            "retest_schedules",
            "localized_knowledge_facts",
            "knowledge_fact_embeddings",
            "content_drafts",
            "integration_connectors",
            "manual_distribution_records",
            "evidence_links",
            "traceability_bundles",
            "audit_events",
        )
        for table in expected_tables:
            self.assertIn(f"INSERT INTO {table}", executed_sql)
        self.assertIn("method_disclosure", executed_sql)
        audit_inserts = [params for sql, params in connection.calls if "INSERT INTO audit_events" in sql]
        self.assertTrue(any(params[1] == "api_browser_fidelity_checked" for params in audit_inserts))
        self.assertGreaterEqual(connection.commit_count, 8)
        first_answer_run_insert = next(params for sql, params in connection.calls if "INSERT INTO answer_runs" in sql)
        self.assertEqual(str(first_answer_run_insert[0]), records[0].answer_run.id)
        first_analysis_insert = next(params for sql, params in connection.calls if "INSERT INTO answer_analyses" in sql)
        self.assertEqual(str(first_analysis_insert[0]), analysis_result.analyses[0].id)
        self.assertEqual(len(str(first_analysis_insert[0])), 36)
        first_llm_call_insert = next(params for sql, params in connection.calls if "INSERT INTO llm_call_logs" in sql)
        self.assertEqual(str(first_llm_call_insert[2]), records[0].answer_run.id)
        self.assertEqual(first_llm_call_insert[3], "parser_judge")

    def test_postgres_repository_searches_runtime_knowledge_facts_with_pgvector(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        fact_id = "06975d61-853b-5a25-ae0e-b62bbfe82c15"
        fact_row = {
            "id": fact_id,
            "project_id": project_id,
            "market_code": "AU",
            "fact_type": "australian_shipping_policy",
            "subject": "ExampleBrand",
            "predicate": "supports_market",
            "object_value": "AU shipping and returns",
            "city": None,
            "evidence_source_id": "438ab927-5873-5516-8df3-47f6c75ef007",
            "confidence": 0.72,
            "status": "active",
            "valid_from": now,
            "valid_until": None,
            "embedding_model": "fixture-knowledge-embedding-v1",
            "vector_score": 0.91,
            "fallback_used": False,
        }
        audit_row = {
            "id": "425f980b-138f-4afa-8784-79d6f16f92ce",
            "event_type": "knowledge_fact_embeddings_indexed",
            "project_id": project_id,
            "actor_type": "system",
            "actor_id": "geno-core.knowledge",
            "target_type": "knowledge_fact_embedding_index",
            "target_id": project_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"knowledge_fact_ids": [fact_id]},
            "output_refs": {"knowledge_fact_embedding_ids": ["embedding-1"]},
            "method_version": "knowledge_fact_embedding_v1",
            "reason": "index localized knowledge facts into pgvector for runtime retrieval",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [fact_row], [audit_row]])

        page = PostgresEvidenceRepository(connection).search_runtime_knowledge_facts(
            project_id=project_id,
            query="Australia shipping returns",
            market_code="AU",
            city="Sydney",
            limit=5,
            offset=0,
        )

        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].fact["fact_type"], "australian_shipping_policy")
        self.assertEqual(page.records[0].score, 0.91)
        self.assertFalse(page.records[0].fallback_used)
        self.assertEqual(page.audit_events[0]["event_type"], "knowledge_fact_embeddings_indexed")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("JOIN knowledge_fact_embeddings kfe ON kfe.knowledge_fact_id = kf.id", executed_sql)
        self.assertIn("kfe.embedding <=> %s::vector", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

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

    def test_postgres_repository_reads_runtime_project_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        tenant_id = "8330ea73-6914-5278-90cb-147f8369fed6"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": project_id,
                        "tenant_id": tenant_id,
                        "name": "AU DTC Evidence Pilot",
                        "market_code": "AU",
                        "industry_code": "dtc_ecommerce",
                        "target_brand": "ExampleBrand",
                        "category": "DTC ecommerce products",
                        "prompt_version": "au_dtc_ecommerce_v1",
                        "status": "configured",
                        "created_at": now,
                    }
                ],
                {
                    "id": tenant_id,
                    "name": "Design Partner AU",
                    "slug": "design-partner-au",
                    "created_at": now,
                },
                {
                    "id": "a44c30bf-27e5-55ff-988e-cfe61130e2a9",
                    "project_id": project_id,
                    "canonical_name": "ExampleBrand",
                    "official_domains": [],
                    "parent_company": None,
                    "product_lines": [],
                    "status": "active",
                },
                [
                    {
                        "id": "78db4b2e-1bc6-5cd1-ab03-6a9243a0993c",
                        "project_id": project_id,
                        "canonical_name": "Ecosa",
                        "official_domains": [],
                        "parent_company": None,
                        "product_lines": [],
                        "status": "active",
                    }
                ],
                {"count": 100},
                [
                    {
                        "id": "7f28023e-977f-4c14-9007-95e7e84db71a",
                        "event_type": "project_bootstrap_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.bootstrap",
                        "target_type": "project",
                        "target_id": project_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {},
                        "output_refs": {"prompt_question_ids": ["prompt-1"]},
                        "method_version": "m1_project_bootstrap_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )

        page = PostgresEvidenceRepository(connection).list_runtime_projects(
            market_code="AU",
            limit=10,
            offset=0,
        )

        self.assertEqual(page.total_count, 1)
        record = page.records[0]
        self.assertEqual(record.project["id"], project_id)
        self.assertEqual(record.tenant["name"], "Design Partner AU")
        assert record.brand is not None
        self.assertEqual(record.brand["canonical_name"], "ExampleBrand")
        self.assertEqual(record.competitors[0]["canonical_name"], "Ecosa")
        self.assertEqual(record.prompt_count, 100)
        self.assertEqual(record.audit_events[0]["event_type"], "project_bootstrap_created")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM projects p WHERE p.market_code = %s", executed_sql)
        self.assertIn("FROM tenants WHERE id = %s", executed_sql)
        self.assertIn("FROM prompt_questions WHERE project_id = %s", executed_sql)

    def test_postgres_repository_filters_runtime_project_page_by_id(self) -> None:
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        connection = RecordingConnection(result_sets=[{"count": 0}, []])

        page = PostgresEvidenceRepository(connection).list_runtime_projects(
            project_id=project_id,
            market_code="AU",
            limit=10,
            offset=0,
        )

        self.assertEqual(page.total_count, 0)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM projects p WHERE p.id = %s AND p.market_code = %s", executed_sql)
        self.assertEqual(connection.calls[0][1], (UUID(project_id), "AU"))
        self.assertEqual(connection.calls[1][1], (UUID(project_id), "AU", 10, 0))

    def test_postgres_repository_reads_runtime_prompt_page(self) -> None:
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        prompt_id = "5b9615f3-533b-5f18-96fb-5c8cbcb934c1"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": prompt_id,
                        "project_id": project_id,
                        "market_code": "AU",
                        "industry_code": "dtc_ecommerce",
                        "text": "Is ExampleBrand good in Australia?",
                        "intent_type": "brand_awareness",
                        "city": "Australia",
                        "language": "en-AU",
                        "target_brand": "ExampleBrand",
                        "competitors": ["Emma Sleep", "Sleeping Duck", "Ecosa", "IKEA Australia"],
                        "priority": 1,
                        "intent_weight": 0.9,
                        "prompt_version": "au_dtc_ecommerce_v1",
                        "status": "active",
                    }
                ],
            ]
        )

        page = PostgresEvidenceRepository(connection).list_runtime_prompts(
            project_id=project_id,
            intent_type="brand_awareness",
            city="Australia",
            status="active",
            limit=10,
            offset=0,
        )

        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0]["id"], prompt_id)
        self.assertEqual(page.records[0]["text"], "Is ExampleBrand good in Australia?")
        self.assertEqual(page.records[0]["competitors"][0], "Emma Sleep")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM prompt_questions WHERE project_id = %s", executed_sql)
        self.assertIn("intent_type = %s", executed_sql)
        self.assertIn("ORDER BY priority ASC, id ASC", executed_sql)

    def test_postgres_repository_imports_runtime_prompts_csv_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        prompt_id = "c5070b70-1c9b-55a1-aad1-457ed04b9707"
        audit_id = "f858da95-fb57-4086-9fa2-eac9e13c0d19"
        imported_prompt_row = {
            "id": prompt_id,
            "project_id": project_id,
            "market_code": "AU",
            "industry_code": "dtc_ecommerce",
            "text": "Is ExampleBrand visible in Sydney AI recommendations?",
            "intent_type": "brand_awareness",
            "city": "Sydney",
            "language": "en-AU",
            "target_brand": "ExampleBrand",
            "competitors": ["Emma Sleep", "Sleeping Duck", "Ecosa"],
            "priority": 1,
            "intent_weight": 0.9,
            "prompt_version": "au_dtc_ecommerce_v1_imported",
            "status": "active",
        }
        audit_row = {
            "id": audit_id,
            "event_type": "runtime_prompts_imported",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "prompt_import",
            "target_id": "prompt-import-1",
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"csv_sha256": ["hash"]},
            "output_refs": {"prompt_question_ids": [prompt_id]},
            "method_version": "runtime_prompt_import_csv_v1",
            "reason": "import runtime prompts from csv",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": project_id,
                    "market_code": "AU",
                    "industry_code": "dtc_ecommerce",
                    "target_brand": "ExampleBrand",
                    "prompt_version": "au_dtc_ecommerce_v1",
                },
                [
                    {"canonical_name": "Emma Sleep"},
                    {"canonical_name": "Sleeping Duck"},
                    {"canonical_name": "Ecosa"},
                ],
                imported_prompt_row,
                [audit_row],
            ]
        )
        result = PostgresEvidenceRepository(connection).import_runtime_prompts_csv(
            RuntimePromptImportInput(
                project_id=project_id,
                csv_content=(
                    "text,intent_type,city,priority,intent_weight,prompt_version\n"
                    "Is ExampleBrand visible in Sydney AI recommendations?,brand_awareness,Sydney,1,0.9,au_dtc_ecommerce_v1_imported\n"
                ),
                imported_by="runtime-console",
            )
        )
        self.assertIsInstance(result, RuntimePromptImportResult)
        self.assertEqual(result.prompt_import["prompt_count"], 1)
        self.assertEqual(result.prompts[0]["text"], "Is ExampleBrand visible in Sydney AI recommendations?")
        self.assertEqual(result.audit_events[0]["event_type"], "runtime_prompts_imported")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO prompt_questions", executed_sql)
        self.assertIn("ON CONFLICT (id) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

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

    def test_postgres_repository_maps_manual_backfill_to_raw_evidence_tables(self) -> None:
        bootstrap = build_au_project_bootstrap()
        prompt = bootstrap.prompt_questions[0]
        record = build_manual_backfill_record(
            ManualBackfillInput(
                project_id=bootstrap.project.id,
                prompt_question_id=prompt.id,
                prompt_text=prompt.text,
                market_code=prompt.market_code,
                city=prompt.city,
                language=prompt.language,
                platform="google",
                surface="google_ai_mode",
                answer_text="Manual Google AI Mode answer mentioning ExampleBrand with sources.",
                citation_urls=("https://examplebrand.example/au/manual",),
                screenshot_url="s3://manual-backfill/examplebrand-google-ai-mode.png",
                submitted_by="runtime-console",
            )
        )
        connection = RecordingConnection()
        PostgresEvidenceRepository(connection).save_raw_evidence_records((record,))
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO answer_runs", executed_sql)
        self.assertIn("INSERT INTO raw_answers", executed_sql)
        self.assertIn("INSERT INTO answer_citations", executed_sql)
        self.assertIn("INSERT INTO evidence_assets", executed_sql)
        self.assertIn("INSERT INTO collector_logs", executed_sql)
        self.assertIn("INSERT INTO collection_costs", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        first_answer_run_insert = next(params for sql, params in connection.calls if "INSERT INTO answer_runs" in sql)
        self.assertEqual(first_answer_run_insert[5], "manual")
        self.assertEqual(first_answer_run_insert[16], "google.manual_backfill")
        self.assertEqual(first_answer_run_insert[19], "completed")
        audit_insert = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertEqual(audit_insert[1], "manual_backfill_recorded")
        self.assertEqual(connection.commit_count, 1)

    def test_postgres_repository_saves_collection_run_summary_with_audit_event(self) -> None:
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
        summary = build_collection_run_summary(
            project_id=bootstrap.project.id,
            run_type="p0a_slice",
            mode="fixture",
            planned_runs=1,
            records=records,
        )
        audit_event = build_collection_run_audit_event(summary)
        connection = RecordingConnection()

        PostgresEvidenceRepository(connection).save_collection_run_summary(summary, audit_event)

        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO collection_run_summaries", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        self.assertIn("ON CONFLICT (id) DO NOTHING", executed_sql)
        collection_run_insert = next(
            params for sql, params in connection.calls if "INSERT INTO collection_run_summaries" in sql
        )
        self.assertEqual(str(collection_run_insert[0]), summary.id)
        self.assertEqual(str(collection_run_insert[1]), bootstrap.project.id)
        self.assertEqual(collection_run_insert[2], "p0a_slice")
        self.assertEqual(collection_run_insert[3], "fixture")
        self.assertEqual(collection_run_insert[4], 1)
        self.assertEqual(collection_run_insert[5], 1)
        self.assertEqual(collection_run_insert[13], summary.total_duration_ms)
        self.assertEqual(collection_run_insert[14], summary.average_duration_ms)
        audit_insert = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertEqual(audit_insert[1], "collection_run_summarized")
        self.assertEqual(audit_insert[5], "collection_run")
        self.assertEqual(str(audit_insert[6]), summary.id)
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
                    "duration_ms": 123,
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
            city="Australia",
            intent_type="category_recommendation",
            status="completed",
            sort="citation_count_desc",
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeEvidencePage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.sort, "citation_count_desc")
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
        self.assertEqual(record.collection_cost["duration_ms"], 123)
        self.assertEqual(record.audit_events[0]["event_type"], "answer_run_collected")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM answer_runs ar LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id", executed_sql)
        self.assertIn(
            "WHERE ar.project_id = %s AND ar.platform = %s AND ar.city = %s AND pq.intent_type = %s AND ar.status = %s",
            executed_sql,
        )
        self.assertIn("ORDER BY citation_counts.citation_count DESC NULLS LAST", executed_sql)
        self.assertIn("LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id", executed_sql)
        self.assertIn("LEFT JOIN collection_costs cc ON cc.answer_run_id = ar.id", executed_sql)
        self.assertIn("FROM raw_answers", executed_sql)

    def test_postgres_repository_reads_runtime_collection_run_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        collection_run_id = "67b5d761-bd78-51c8-923e-f934ac31cae2"
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": collection_run_id,
                        "project_id": project_id,
                        "run_type": "p0a_slice",
                        "mode": "fixture",
                        "planned_runs": 4,
                        "attempted_runs": 4,
                        "success_count": 3,
                        "failure_count": 1,
                        "success_rate": 0.75,
                        "trigger_rate": 0.75,
                        "answer_present_rate": 0.75,
                        "total_cost": 0.0076,
                        "average_cost_per_run": 0.0019,
                        "total_duration_ms": 400,
                        "average_duration_ms": 100,
                        "collector_backend_ids": ["perplexity.sonar.fixture", "openai.web_search.api"],
                        "platform_distribution": {"perplexity": 3, "chatgpt": 1},
                        "city_distribution": {"Australia": 4},
                        "access_method_distribution": {"official_api": 4},
                        "failure_summary": {"OPENAI_API_KEY is required": 1},
                        "answer_run_ids": [answer_run_id],
                        "started_at": now,
                        "completed_at": now,
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "495d24da-90cf-4073-bd9c-16afeb5b3169",
                        "event_type": "collection_run_summarized",
                        "project_id": project_id,
                        "actor_type": "worker",
                        "actor_id": "collector_worker",
                        "target_type": "collection_run",
                        "target_id": collection_run_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"collection_run_ids": [collection_run_id]},
                        "method_version": "collection_run_summary_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )

        page = PostgresEvidenceRepository(connection).list_runtime_collection_runs(
            project_id=project_id,
            run_type="p0a_slice",
            limit=10,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeCollectionRunPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(len(page.records), 1)
        record = page.records[0]
        self.assertEqual(record.collection_run["id"], collection_run_id)
        self.assertEqual(record.collection_run["success_rate"], 0.75)
        self.assertIsInstance(record.collection_run["success_rate"], float)
        self.assertIsInstance(record.collection_run["planned_runs"], int)
        self.assertEqual(record.collection_run["total_duration_ms"], 400)
        self.assertEqual(record.collection_run["average_duration_ms"], 100)
        self.assertIsInstance(record.collection_run["average_duration_ms"], int)
        self.assertEqual(record.collection_run["failure_summary"], {"OPENAI_API_KEY is required": 1})
        self.assertEqual(record.audit_events[0]["event_type"], "collection_run_summarized")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM collection_run_summaries WHERE project_id = %s AND run_type = %s", executed_sql)
        self.assertIn("ORDER BY created_at DESC, id DESC", executed_sql)
        self.assertIn("WHERE target_type = %s AND target_id = %s", executed_sql)

    def test_runtime_fidelity_check_records_mismatch_and_audit_event(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        prompt_id = "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0"
        check, audit_event = build_runtime_fidelity_check(
            project_id=project_id,
            report_export_id=report_export_id,
            answer_run_rows=(
                {
                    "id": "438ab927-5873-5516-8df3-47f6c75ef007",
                    "project_id": project_id,
                    "prompt_question_id": prompt_id,
                    "platform": "chatgpt",
                    "surface": "chatgpt_search",
                    "access_method": "official_api",
                    "city": "Sydney",
                    "answer_present": True,
                    "surface_triggered": True,
                    "screenshot_count": 0,
                    "html_snapshot_count": 0,
                },
                {
                    "id": "4c498fd9-7aac-5f62-b29f-f15450c836d3",
                    "project_id": project_id,
                    "prompt_question_id": prompt_id,
                    "platform": "chatgpt",
                    "surface": "chatgpt_search",
                    "access_method": "browser",
                    "city": "Sydney",
                    "answer_present": False,
                    "surface_triggered": True,
                    "screenshot_count": 1,
                    "html_snapshot_count": 1,
                },
            ),
            checked_by="unit-test",
        )

        self.assertEqual(check["status"], "sampled")
        self.assertEqual(check["official_api_records"], 1)
        self.assertEqual(check["browser_records"], 1)
        self.assertEqual(check["comparable_prompt_city_pairs"], 1)
        self.assertEqual(check["mismatch_count"], 1)
        self.assertEqual(check["difference_rate"], 1.0)
        self.assertEqual(len(check["payload_hash"]), 64)
        self.assertEqual(audit_event.event_type, "api_browser_fidelity_checked")
        self.assertEqual(audit_event.target_type, "api_browser_fidelity_check")
        self.assertEqual(audit_event.method_version, "api_browser_fidelity_check_v1")
        self.assertEqual(audit_event.input_refs["report_export_ids"], [report_export_id])

    def test_postgres_repository_creates_runtime_fidelity_check_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        official_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        browser_run_id = "4c498fd9-7aac-5f62-b29f-f15450c836d3"
        prompt_id = "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0"
        official_answer_row = {
            "id": official_run_id,
            "project_id": project_id,
            "prompt_question_id": prompt_id,
            "platform": "chatgpt",
            "surface": "chatgpt_search",
            "access_method": "official_api",
            "market_code": "AU",
            "city": "Sydney",
            "language": "en-AU",
            "device": "desktop",
            "answer_present": True,
            "surface_triggered": True,
            "sample_index": 1,
            "sample_size": 1,
            "model_or_surface": "gpt-search",
            "account_state": "api_key",
            "collector_backend_id": "fixture_openai_web_search",
            "collector_version": "fixture-v1",
            "collected_at": now,
            "status": "completed",
            "screenshot_count": 0,
            "html_snapshot_count": 0,
        }
        browser_answer_row = {
            **official_answer_row,
            "id": browser_run_id,
            "access_method": "browser",
            "answer_present": False,
            "collector_backend_id": "browser_chatgpt_search",
            "screenshot_count": 1,
            "html_snapshot_count": 1,
        }
        connection = RecordingConnection(
            result_sets=[
                {"id": project_id},
                {"id": report_export_id},
                [{"answer_run_id": official_run_id}, {"answer_run_id": browser_run_id}],
                [official_answer_row, browser_answer_row],
                [
                    {
                        "id": "d0ba559d-13f3-4b79-a984-b39cb273b6a4",
                        "event_type": "api_browser_fidelity_checked",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "runtime-console",
                        "target_type": "api_browser_fidelity_check",
                        "target_id": "check-id",
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [official_run_id, browser_run_id]},
                        "output_refs": {"api_browser_fidelity_check_ids": ["check-id"]},
                        "method_version": "api_browser_fidelity_check_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )

        record = PostgresEvidenceRepository(connection).create_runtime_fidelity_check(
            project_id=project_id,
            report_export_id=report_export_id,
            checked_by="runtime-console",
        )

        self.assertIsInstance(record, RuntimeFidelityCheck)
        self.assertEqual(record.fidelity_check["status"], "sampled")
        self.assertEqual(record.fidelity_check["mismatch_count"], 1)
        self.assertEqual(record.audit_events[0]["event_type"], "api_browser_fidelity_checked")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM report_evidence", executed_sql)
        self.assertIn("GROUP BY ar.id", executed_sql)
        self.assertIn("INSERT INTO api_browser_fidelity_checks", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        audit_insert = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertEqual(audit_insert[1], "api_browser_fidelity_checked")

    def test_postgres_repository_lists_runtime_fidelity_checks_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        check_id = "9128c59e-54ca-5ceb-9272-3efe226bd07b"
        check_row = {
            "id": check_id,
            "project_id": project_id,
            "report_export_id": report_export_id,
            "status": "not_run",
            "official_api_records": 4,
            "browser_records": 0,
            "comparable_prompt_city_pairs": 0,
            "mismatch_count": 0,
            "difference_rate": None,
            "payload": {"status": "not_run", "summary": "browser sample not collected"},
            "payload_hash": "f" * 64,
            "answer_run_ids": ["438ab927-5873-5516-8df3-47f6c75ef007"],
            "checked_by": "collector_worker",
            "checked_at": now,
        }
        audit_row = {
            "id": "d0ba559d-13f3-4b79-a984-b39cb273b6a4",
            "event_type": "api_browser_fidelity_checked",
            "project_id": project_id,
            "actor_type": "system",
            "actor_id": "collector_worker",
            "target_type": "api_browser_fidelity_check",
            "target_id": check_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"report_export_ids": [report_export_id]},
            "output_refs": {"api_browser_fidelity_check_ids": [check_id]},
            "method_version": "api_browser_fidelity_check_v1",
            "reason": "test",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [check_row], [audit_row]])

        page = PostgresEvidenceRepository(connection).list_runtime_fidelity_checks(
            project_id=project_id,
            report_export_id=report_export_id,
            status="not_run",
            limit=5,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeFidelityCheckPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].fidelity_check["payload_hash"], "f" * 64)
        self.assertEqual(page.records[0].audit_events[0]["method_version"], "api_browser_fidelity_check_v1")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn(
            "FROM api_browser_fidelity_checks WHERE project_id = %s AND report_export_id = %s AND status = %s",
            executed_sql,
        )
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_exports_filtered_runtime_evidence_csv(self) -> None:
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
                        "city": "Sydney",
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
                    "id": "5d714ed1-25aa-5651-b8b3-5e4b275d278a",
                    "answer_run_id": answer_run_id,
                    "answer_text": "answer",
                    "raw_payload": {"citations": 1},
                    "raw_payload_hash": "raw-hash",
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
                [],
                [],
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
        export = PostgresEvidenceRepository(connection).export_runtime_evidence_csv(
            platform="perplexity",
            city="Sydney",
            intent_type="brand_awareness",
            sort="cost_desc",
            limit=200,
            offset=0,
        )
        self.assertIsInstance(export, RuntimeEvidenceExport)
        self.assertEqual(export.filename, "runtime-evidence.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["platform"], "perplexity")
        self.assertEqual(export.filters["sort"], "cost_desc")
        self.assertIn("answer_run_id", export.content)
        self.assertIn("prompt_intent_type", export.content)
        self.assertIn("Is ExampleBrand good in Australia?", export.content)
        self.assertIn("raw-hash", export.content)
        self.assertTrue(export.content_hash)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("pq.intent_type = %s", executed_sql)
        self.assertIn("ORDER BY cc.total_cost DESC NULLS LAST", executed_sql)

    def test_postgres_repository_falls_back_for_unknown_runtime_evidence_sort(self) -> None:
        connection = RecordingConnection(result_sets=[{"count": 0}, []])
        page = PostgresEvidenceRepository(connection).list_runtime_evidence_runs(
            sort="cc.total_cost DESC; DROP TABLE answer_runs",
            limit=5,
            offset=0,
        )
        self.assertEqual(page.sort, "collected_at_desc")
        self.assertEqual(page.total_count, 0)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("ORDER BY ar.collected_at DESC, ar.id DESC", executed_sql)
        self.assertNotIn("DROP TABLE", executed_sql)

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
                    "parser_engine_id": "rule_based_v2_aliases",
                    "analysis_version": "rule_based_v2_aliases",
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
            "method_disclosure": {
                "google_coverage": "limited_coverage_appendix_only",
                "google_spike_gate": {
                    "gate_status": "fail",
                    "planned_runs": 240,
                    "completed_runs": 0,
                    "google_aio_completed_runs": 0,
                    "success_rate": 0.0,
                    "trigger_rate": 0.0,
                    "limited_coverage": True,
                    "recommendation": "Keep Google in limited coverage appendix until a google_aio backend reaches 80% completion",
                },
                "api_browser_fidelity": {
                    "status": "not_run",
                    "official_api_records": 1,
                    "browser_records": 0,
                    "comparable_prompt_city_pairs": 0,
                    "difference_rate": None,
                },
                "access_method_distribution": {"official_api": 1},
                "platform_distribution": {"perplexity": 1},
                "evidence_asset_coverage": {"screenshot_records": 1, "html_snapshot_records": 1},
            },
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
            "city": "Sydney",
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

    def test_postgres_repository_renders_runtime_report_artifact(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
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
            "method_disclosure": {
                "google_coverage": "limited_coverage_appendix_only",
                "google_spike_gate": {
                    "gate_status": "fail",
                    "planned_runs": 240,
                    "completed_runs": 0,
                    "google_aio_completed_runs": 0,
                    "success_rate": 0.0,
                    "trigger_rate": 0.0,
                    "limited_coverage": True,
                    "recommendation": "Keep Google in limited coverage appendix until a google_aio backend reaches 80% completion",
                },
                "api_browser_fidelity": {
                    "status": "not_run",
                    "official_api_records": 1,
                    "browser_records": 0,
                    "comparable_prompt_city_pairs": 0,
                    "difference_rate": None,
                },
                "access_method_distribution": {"official_api": 1},
                "platform_distribution": {"perplexity": 1},
                "evidence_asset_coverage": {"screenshot_records": 1, "html_snapshot_records": 1},
            },
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
            "city": "Sydney",
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
                report_row,
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
                {"count": 0},
            ]
        )
        artifact = PostgresEvidenceRepository(connection).get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type="markdown",
        )
        self.assertIsInstance(artifact, RuntimeReportArtifact)
        assert artifact is not None
        self.assertEqual(artifact.filename, "worker-runtime-v1.md")
        self.assertEqual(artifact.media_type, "text/markdown; charset=utf-8")
        self.assertIn("GENO AU Evidence Report", artifact.content)
        self.assertIn("Is ExampleBrand good in Australia?", artifact.content)
        self.assertIn("## Method Disclosure", artifact.content)
        self.assertIn("Google spike gate: fail", artifact.content)
        self.assertIn("Google limited coverage: yes", artifact.content)
        self.assertIn("Google AIO completed runs: 0 / planned 240", artifact.content)
        self.assertIn("API-vs-browser fidelity: not_run", artifact.content)
        self.assertIn("Trigger rate denominator: all attempted evidence records in this report window", artifact.content)
        self.assertIn("Mention rate denominator: surface_triggered evidence records, not all attempted records", artifact.content)
        self.assertIn("Report evidence attempted records: 1", artifact.content)
        self.assertIn("Report evidence surface-triggered records: 1", artifact.content)
        self.assertIn("Screenshot records: 1", artifact.content)
        self.assertIn("HTML snapshot records: 1", artifact.content)
        self.assertIn("ReportExport -> VisibilityScoreSnapshot", artifact.content)
        self.assertTrue(artifact.content_hash)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM report_exports WHERE id = %s", executed_sql)

    def test_postgres_repository_renders_runtime_report_csv_artifact(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        other_answer_run_id = "a20ec948-0443-5de5-8151-5ec1db8aef01"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [snapshot_id],
            "answer_run_ids": [answer_run_id, other_answer_run_id],
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
            "city": "Sydney",
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
        other_answer_run_row = {
            **answer_run_row,
            "id": other_answer_run_id,
            "platform": "chatgpt",
            "surface": "chatgpt_search",
            "city": "Melbourne",
            "prompt_text": "Best ExampleBrand alternatives in Melbourne",
            "prompt_intent_type": "alternative",
        }
        connection = RecordingConnection(
            result_sets=[
                report_row,
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
                    "answer_run_ids": [answer_run_id, other_answer_run_id],
                    "created_at": now,
                    "dispersion": 0.0,
                },
                answer_run_row,
                other_answer_run_row,
                [],
                {"count": 0},
            ]
        )
        artifact = PostgresEvidenceRepository(connection).get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type="csv",
            platform="perplexity",
            city="Sydney",
            intent_type="brand_awareness",
            sort="cost_desc",
        )
        self.assertIsInstance(artifact, RuntimeReportArtifact)
        assert artifact is not None
        self.assertEqual(artifact.filename, "worker-runtime-v1.csv")
        self.assertEqual(artifact.media_type, "text/csv; charset=utf-8")
        self.assertEqual(artifact.filters["platform"], "perplexity")
        self.assertEqual(artifact.sort, "cost_desc")
        self.assertEqual(artifact.total_count, 2)
        self.assertEqual(artifact.row_count, 1)
        self.assertIn("answer_run_id", artifact.content)
        self.assertIn("Is ExampleBrand good in Australia?", artifact.content)
        self.assertNotIn("Best ExampleBrand alternatives in Melbourne", artifact.content)
        self.assertTrue(artifact.content_hash)
        self.assertTrue(artifact.filter_hash)

    def test_postgres_repository_renders_runtime_report_pdf_artifact(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
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
                report_row,
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
                [],
                {"count": 0},
            ]
        )
        artifact = PostgresEvidenceRepository(connection).get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type="pdf",
        )
        self.assertIsInstance(artifact, RuntimeReportArtifact)
        assert artifact is not None
        self.assertEqual(artifact.filename, "worker-runtime-v1.pdf")
        self.assertEqual(artifact.template, "standard")
        self.assertEqual(artifact.template_payload, {"template": "standard"})
        self.assertTrue(artifact.template_hash)
        self.assertEqual(artifact.media_type, "application/pdf")
        self.assertIsInstance(artifact.content, bytes)
        self.assertTrue(artifact.content.startswith(b"%PDF-1.4"))
        self.assertIn(b"%%EOF", artifact.content)
        self.assertTrue(artifact.content_hash)

    def test_postgres_repository_renders_runtime_report_white_label_pdf_artifact(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
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
                report_row,
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
                [],
                {"count": 0},
            ]
        )
        artifact = PostgresEvidenceRepository(connection).get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type="pdf",
            template="white_label",
            client_name="ExampleBrand AU",
            prepared_by="Partner Agency",
        )
        self.assertIsInstance(artifact, RuntimeReportArtifact)
        assert artifact is not None
        self.assertEqual(artifact.filename, "worker-runtime-v1-white-label.pdf")
        self.assertEqual(artifact.template, "white_label")
        self.assertEqual(artifact.template_payload["client_name"], "ExampleBrand AU")
        self.assertEqual(artifact.template_payload["prepared_by"], "Partner Agency")
        self.assertTrue(artifact.template_hash)
        self.assertEqual(artifact.media_type, "application/pdf")
        self.assertIsInstance(artifact.content, bytes)
        self.assertTrue(artifact.content.startswith(b"%PDF-1.4"))
        self.assertIn(b"ExampleBrand AU GEO Evidence Report", artifact.content)
        self.assertIn(b"white-label template", artifact.content)
        self.assertIn(b"%%EOF", artifact.content)
        self.assertTrue(artifact.content_hash)

    def test_postgres_repository_renders_runtime_report_white_label_pdf_from_project_brand_kit(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
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
        brand_kit_row = {
            "id": "0ada83ad-b669-507e-b3c8-9d8574569a62",
            "project_id": project_id,
            "client_name": "Koala AU",
            "prepared_by": "Partner Agency",
            "logo_url": "https://koala.example/logo.png",
            "primary_color": "#0f766e",
            "secondary_color": "#111827",
            "footer_text": "Prepared for Koala AU board review",
            "updated_by": "runtime-console",
            "created_at": now,
            "updated_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                report_row,
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
                [],
                {"count": 0},
                brand_kit_row,
            ]
        )
        artifact = PostgresEvidenceRepository(connection).get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type="pdf",
            template="white_label",
        )
        self.assertIsInstance(artifact, RuntimeReportArtifact)
        assert artifact is not None
        self.assertEqual(artifact.template_payload["client_name"], "Koala AU")
        self.assertEqual(artifact.template_payload["prepared_by"], "Partner Agency")
        self.assertEqual(artifact.template_payload["logo_url"], "https://koala.example/logo.png")
        self.assertEqual(artifact.template_payload["primary_color"], "#0f766e")
        self.assertEqual(artifact.template_payload["source"], "project_brand_kit")
        self.assertIn(b"Koala AU GEO Evidence Report", artifact.content)
        self.assertIn(b"Partner Agency", artifact.content)
        self.assertIn(b"Prepared for Koala AU board review", artifact.content)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM project_brand_kits WHERE project_id = %s", executed_sql)

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

    def test_postgres_repository_reads_runtime_content_engine_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        draft_id = "51dcc4cb-c798-5eac-a08d-86f596c78f0f"
        fact_id = "06975d61-853b-5a25-ae0e-b62bbfe82c15"
        prompt_id = "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0"
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        action_id = "4cfd7cd0-a0cc-580f-b448-7b52f3b2937e"
        distribution_id = "042f3450-77b4-5cb3-8a61-8057db7c11bd"
        connector_id = "70655f5b-4b7e-56cc-9974-84d6d5f08020"
        fact_row = {
            "id": fact_id,
            "project_id": project_id,
            "market_code": "AU",
            "fact_type": "australian_shipping_policy",
            "subject": "ExampleBrand",
            "predicate": "supports_market",
            "object_value": "AU",
            "city": None,
            "evidence_source_id": answer_run_id,
            "confidence": 0.72,
            "status": "active",
            "valid_from": now,
            "valid_until": None,
        }
        draft_row = {
            "id": draft_id,
            "project_id": project_id,
            "title": "ExampleBrand FAQ for Australian customers",
            "content_type": "evidence_backed_outline",
            "content_template_id": "faq_for_australian_customers",
            "target_question_ids": [prompt_id],
            "target_city": "Sydney",
            "target_platform": "chatgpt/perplexity",
            "target_source_type": "official_site",
            "used_knowledge_fact_ids": [fact_id],
            "source_gap_types": ["low_mention_rate"],
            "source_action_id": action_id,
            "evidence_answer_run_ids": [answer_run_id],
            "draft_markdown": "# ExampleBrand FAQ",
            "review_status": "pending_human_review",
            "created_by": "geno-core.knowledge",
            "created_at": now,
        }
        distribution_row = {
            "id": distribution_id,
            "project_id": project_id,
            "content_draft_id": draft_id,
            "platform": "manual",
            "target_url": "",
            "status": "draft_created",
            "submitted_at": None,
            "checked_at": None,
            "notes": "Manual distribution only.",
        }
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [{"project_id": project_id}],
                [fact_row],
                [draft_row],
                {
                    "id": prompt_id,
                    "project_id": project_id,
                    "market_code": "AU",
                    "industry_code": "dtc_ecommerce",
                    "text": "Is ExampleBrand good in Australia?",
                    "intent_type": "brand_awareness",
                    "city": "Australia",
                    "language": "en-AU",
                    "target_brand": "ExampleBrand",
                    "competitors": ["CompetitorA"],
                    "priority": 1,
                    "intent_weight": 1.0,
                    "prompt_version": "au_dtc_ecommerce_v1",
                    "status": "active",
                },
                fact_row,
                {
                    "id": answer_run_id,
                    "project_id": project_id,
                    "prompt_question_id": prompt_id,
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
                {
                    "id": action_id,
                    "project_id": project_id,
                    "title": "Improve brand mention coverage",
                    "description": "Create citation-ready pages.",
                    "priority": "high",
                    "status": "open",
                    "owner_id": "system",
                    "source_gap_type": "low_mention_rate",
                    "evidence_answer_run_ids": [answer_run_id],
                    "related_source_types": [],
                    "next_check_date": now,
                    "created_at": now,
                },
                [distribution_row],
                [
                    {
                        "id": connector_id,
                        "project_id": project_id,
                        "provider": "google_search_console",
                        "connection_status": "planned",
                        "capabilities": ["read_search_queries"],
                        "auth_mode": "oauth",
                        "created_at": now,
                    }
                ],
                [distribution_row],
                [
                    {
                        "id": "425f980b-138f-4afa-8784-79d6f16f92ce",
                        "event_type": "content_engine_fixture_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.knowledge",
                        "target_type": "content_engine_fixture",
                        "target_id": project_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"knowledge_fact_ids": [fact_id]},
                        "output_refs": {"content_draft_ids": [draft_id]},
                        "method_version": "content_engine_fixture_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_content_engines(
            project_id=project_id,
            review_status="pending_human_review",
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeContentEnginePage)
        self.assertEqual(page.total_count, 1)
        record = page.records[0]
        self.assertEqual(record.project_id, project_id)
        self.assertEqual(record.knowledge_facts[0]["fact_type"], "australian_shipping_policy")
        draft = record.content_drafts[0]
        self.assertEqual(draft.draft["review_status"], "pending_human_review")
        self.assertEqual(draft.target_questions[0]["text"], "Is ExampleBrand good in Australia?")
        self.assertEqual(draft.knowledge_facts[0]["id"], fact_id)
        self.assertEqual(draft.answer_runs[0]["prompt_text"], "Is ExampleBrand good in Australia?")
        self.assertEqual(draft.action_recommendation["source_gap_type"], "low_mention_rate")
        self.assertEqual(draft.manual_distribution_records[0]["status"], "draft_created")
        self.assertEqual(record.integration_connectors[0]["provider"], "google_search_console")
        self.assertEqual(record.audit_events[0]["event_type"], "content_engine_fixture_created")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM content_drafts cd WHERE cd.project_id = %s AND cd.review_status = %s", executed_sql)
        self.assertIn("FROM localized_knowledge_facts", executed_sql)
        self.assertIn("FROM prompt_questions WHERE id = %s", executed_sql)
        self.assertIn("FROM action_recommendations WHERE id = %s", executed_sql)

    def test_postgres_repository_reads_runtime_traceability_detail(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        contribution_id = "df03794b-e8fc-4b69-aa62-2304a55ff3a9"
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        raw_answer_id = "5d714ed1-25aa-5651-b8b3-5e4b275d278a"
        citation_id = "6e5c424e-1674-58ce-b075-6c52259bbbe5"
        asset_id = "29a279b8-3313-5306-a959-4f0f0de9c950"
        source_graph_id = "41c2fd71-a32f-51a7-92e4-3d4c0f7ab1c2"
        action_id = "4cfd7cd0-a0cc-580f-b448-7b52f3b2937e"
        draft_id = "51dcc4cb-c798-5eac-a08d-86f596c78f0f"
        fact_id = "06975d61-853b-5a25-ae0e-b62bbfe82c15"
        prompt_id = "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0"
        audit_event_id = "495d24da-90cf-4073-bd9c-16afeb5b3169"
        answer_run_row = {
            "id": answer_run_id,
            "project_id": project_id,
            "prompt_question_id": prompt_id,
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
        snapshot_row = {
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
        }
        action_row = {
            "id": action_id,
            "project_id": project_id,
            "title": "Improve brand mention coverage",
            "description": "Create citation-ready pages.",
            "priority": "high",
            "status": "open",
            "owner_id": "system",
            "source_gap_type": "low_mention_rate",
            "evidence_answer_run_ids": [answer_run_id],
            "related_source_types": [],
            "next_check_date": now,
            "created_at": now,
        }
        draft_row = {
            "id": draft_id,
            "project_id": project_id,
            "title": "ExampleBrand FAQ for Australian customers",
            "content_type": "evidence_backed_outline",
            "content_template_id": "faq_for_australian_customers",
            "target_question_ids": [prompt_id],
            "target_city": "Sydney",
            "target_platform": "chatgpt/perplexity",
            "target_source_type": "official_site",
            "used_knowledge_fact_ids": [fact_id],
            "source_gap_types": ["low_mention_rate"],
            "source_action_id": action_id,
            "evidence_answer_run_ids": [answer_run_id],
            "draft_markdown": "# ExampleBrand FAQ",
            "review_status": "pending_human_review",
            "created_by": "geno-core.knowledge",
            "created_at": now,
        }
        fact_row = {
            "id": fact_id,
            "project_id": project_id,
            "market_code": "AU",
            "fact_type": "australian_shipping_policy",
            "subject": "ExampleBrand",
            "predicate": "supports_market",
            "object_value": "AU",
            "city": None,
            "evidence_source_id": answer_run_id,
            "confidence": 0.72,
            "status": "active",
            "valid_from": now,
            "valid_until": None,
        }
        audit_row = {
            "id": audit_event_id,
            "event_type": "answer_run_collected",
            "project_id": project_id,
            "actor_type": "worker",
            "actor_id": "fixture_perplexity_sonar",
            "target_type": "answer_run",
            "target_id": answer_run_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"prompt_question_ids": [prompt_id]},
            "output_refs": {"answer_run_ids": [answer_run_id]},
            "method_version": "fixture-v1",
            "reason": "test",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": "b11a8445-6d8f-58f8-b1b5-50c45e22d384",
                    "project_id": project_id,
                    "subject_type": "report_export",
                    "subject_id": report_export_id,
                    "report_export_ids": [report_export_id],
                    "score_snapshot_ids": [snapshot_id],
                    "score_contribution_ids": [contribution_id],
                    "answer_run_ids": [answer_run_id],
                    "raw_answer_ids": [raw_answer_id],
                    "answer_citation_ids": [citation_id],
                    "evidence_asset_ids": [asset_id],
                    "source_graph_ids": [source_graph_id],
                    "source_gap_types": ["official_site:missing_high_weight_source_type"],
                    "action_recommendation_ids": [action_id],
                    "content_draft_ids": [draft_id],
                    "audit_event_ids": [audit_event_id],
                    "explanation_summary": "Report worker-runtime-v1 traces 1 answer runs.",
                },
                report_row,
                snapshot_row,
                [
                    {
                        "id": contribution_id,
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
                [answer_run_row],
                {
                    "id": "d1466dad-237b-5f5f-b7cc-44e67d628d15",
                    "answer_run_id": answer_run_id,
                    "parser_engine_id": "rule_based_v2_aliases",
                    "analysis_version": "rule_based_v2_aliases",
                    "payload": {"brand_mentioned": True},
                    "confidence": 0.9,
                    "created_at": now,
                },
                [],
                answer_run_row,
                {
                    "id": raw_answer_id,
                    "answer_run_id": answer_run_id,
                    "answer_text": "answer",
                    "raw_payload": {"citations": 1},
                    "raw_payload_hash": "hash",
                    "created_at": now,
                },
                [
                    {
                        "id": citation_id,
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
                        "id": asset_id,
                        "answer_run_id": answer_run_id,
                        "asset_type": "html_snapshot",
                        "url": "s3://asset.html",
                        "content_hash": "asset-hash",
                        "created_at": now,
                    }
                ],
                [],
                None,
                [audit_row],
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
                action_row,
                draft_row,
                {
                    "id": prompt_id,
                    "project_id": project_id,
                    "market_code": "AU",
                    "industry_code": "dtc_ecommerce",
                    "text": "Is ExampleBrand good in Australia?",
                    "intent_type": "brand_awareness",
                    "city": "Australia",
                    "language": "en-AU",
                    "target_brand": "ExampleBrand",
                    "competitors": ["CompetitorA"],
                    "priority": 1,
                    "intent_weight": 1.0,
                    "prompt_version": "au_dtc_ecommerce_v1",
                    "status": "active",
                },
                fact_row,
                answer_run_row,
                action_row,
                [],
                audit_row,
                [
                    {
                        "id": "53ce3658-f908-56bf-b6de-585bcb7900d1",
                        "project_id": project_id,
                        "source_type": "report_export",
                        "source_id": report_export_id,
                        "target_type": "visibility_score_snapshot",
                        "target_id": snapshot_id,
                        "relation_type": "contains_score_snapshot",
                        "answer_run_ids": [answer_run_id],
                    }
                ],
            ]
        )
        detail = PostgresEvidenceRepository(connection).get_runtime_traceability_detail(
            project_id=project_id,
            report_export_id=report_export_id,
        )
        self.assertIsInstance(detail, RuntimeTraceabilityDetail)
        assert detail is not None
        self.assertEqual(detail.traceability_bundle["subject_id"], report_export_id)
        self.assertEqual(detail.report_exports[0]["report_version"], "worker-runtime-v1")
        self.assertEqual(detail.score_snapshots[0].snapshot["final_score"], 87.35)
        self.assertEqual(detail.evidence_runs[0].raw_answer["id"], raw_answer_id)
        self.assertEqual(detail.evidence_runs[0].citations[0]["id"], citation_id)
        self.assertIsNotNone(detail.citation_graph)
        assert detail.citation_graph is not None
        self.assertEqual(detail.citation_graph.nodes[0].node["source_domain"], "reviews.example")
        self.assertEqual(detail.action_recommendations[0]["id"], action_id)
        self.assertEqual(detail.content_drafts[0].draft["review_status"], "pending_human_review")
        self.assertEqual(detail.audit_events[0]["event_type"], "answer_run_collected")
        self.assertEqual(detail.evidence_links[0]["relation_type"], "contains_score_snapshot")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM traceability_bundles WHERE subject_type = %s", executed_sql)
        self.assertIn("FROM evidence_links WHERE project_id = %s", executed_sql)
        self.assertIn("FROM report_exports WHERE id = %s", executed_sql)
        self.assertIn("FROM content_drafts WHERE id = %s", executed_sql)

    def test_postgres_repository_saves_runtime_saved_view_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        saved_view_id = "dcb0b54f-2d65-5ce3-bd46-c08b85bc4020e"
        saved_view_row = {
            "id": saved_view_id,
            "project_id": project_id,
            "name": "Perplexity Sydney",
            "view_type": "runtime_evidence",
            "filters": {"platform": "perplexity", "city": "Sydney", "intent_type": "brand_awareness"},
            "sort": "cost_desc",
            "query_path": "/v1/evidence-runs/runtime?platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc&limit=5",
            "export_path": "/v1/evidence-runs/runtime/export.csv?platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc&limit=200",
            "created_by": "runtime-console",
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "725067ce-00b5-49a5-a3ec-8b8e74c85f4f",
            "event_type": "runtime_saved_view_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "runtime_saved_view",
            "target_id": saved_view_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"query_path": [saved_view_row["query_path"]]},
            "output_refs": {"runtime_saved_view_ids": [saved_view_id]},
            "method_version": "runtime_saved_view_v1",
            "reason": "save runtime evidence filter view",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[None, saved_view_row, [audit_row]])
        record = PostgresEvidenceRepository(connection).save_runtime_saved_view(
            RuntimeSavedViewInput(
                project_id=project_id,
                name="Perplexity Sydney",
                view_type="runtime_evidence",
                filters=saved_view_row["filters"],
                sort="cost_desc",
                query_path=saved_view_row["query_path"],
                export_path=saved_view_row["export_path"],
                created_by="runtime-console",
            )
        )
        self.assertIsInstance(record, RuntimeSavedView)
        self.assertEqual(record.saved_view["name"], "Perplexity Sydney")
        self.assertEqual(record.saved_view["sort"], "cost_desc")
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_saved_view_saved")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO runtime_saved_views", executed_sql)
        self.assertIn("ON CONFLICT (project_id, name) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_lists_runtime_saved_views_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        saved_view_id = "dcb0b54f-2d65-5ce3-bd46-c08b85bc4020e"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": saved_view_id,
                        "project_id": project_id,
                        "name": "Perplexity Sydney",
                        "view_type": "runtime_evidence",
                        "filters": {"platform": "perplexity", "city": "Sydney"},
                        "sort": "cost_desc",
                        "query_path": "/v1/evidence-runs/runtime?platform=perplexity&city=Sydney&sort=cost_desc&limit=5",
                        "export_path": "/v1/evidence-runs/runtime/export.csv?platform=perplexity&city=Sydney&sort=cost_desc&limit=200",
                        "created_by": "runtime-console",
                        "created_at": now,
                        "updated_at": now,
                    }
                ],
                [
                    {
                        "id": "725067ce-00b5-49a5-a3ec-8b8e74c85f4f",
                        "event_type": "runtime_saved_view_saved",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "runtime-console",
                        "target_type": "runtime_saved_view",
                        "target_id": saved_view_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {},
                        "output_refs": {"runtime_saved_view_ids": [saved_view_id]},
                        "method_version": "runtime_saved_view_v1",
                        "reason": "save runtime evidence filter view",
                        "created_at": now,
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_saved_views(
            project_id=project_id,
            view_type="runtime_evidence",
            limit=5,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeSavedViewPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].saved_view["name"], "Perplexity Sydney")
        self.assertEqual(page.records[0].audit_events[0]["event_type"], "runtime_saved_view_saved")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM runtime_saved_views WHERE project_id = %s AND view_type = %s", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_saves_project_brand_kit_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_kit_id = "0ada83ad-b669-507e-b3c8-9d8574569a62"
        brand_kit_row = {
            "id": brand_kit_id,
            "project_id": project_id,
            "client_name": "Koala AU",
            "prepared_by": "Partner Agency",
            "logo_url": "https://koala.example/logo.png",
            "primary_color": "#0f766e",
            "secondary_color": "#111827",
            "footer_text": "Prepared for Koala AU board review",
            "updated_by": "runtime-console",
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "2782a901-8cdf-47e7-bbdb-345d9ca66efe",
            "event_type": "project_brand_kit_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "project_brand_kit",
            "target_id": brand_kit_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"project_ids": [project_id]},
            "output_refs": {"project_brand_kit_ids": [brand_kit_id]},
            "method_version": "project_brand_kit_v1",
            "reason": "save project white-label brand configuration",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, None, brand_kit_row, [audit_row]])
        record = PostgresEvidenceRepository(connection).save_project_brand_kit(
            RuntimeProjectBrandKitInput(
                project_id=project_id,
                client_name="Koala AU",
                prepared_by="Partner Agency",
                logo_url="https://koala.example/logo.png",
                primary_color="#0f766e",
                secondary_color="#111827",
                footer_text="Prepared for Koala AU board review",
                updated_by="runtime-console",
            )
        )
        self.assertIsInstance(record, RuntimeProjectBrandKit)
        self.assertEqual(record.brand_kit["client_name"], "Koala AU")
        self.assertEqual(record.brand_kit["prepared_by"], "Partner Agency")
        self.assertEqual(record.audit_events[0]["event_type"], "project_brand_kit_saved")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO project_brand_kits", executed_sql)
        self.assertIn("ON CONFLICT (project_id) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_reads_project_brand_kit_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_kit_id = "0ada83ad-b669-507e-b3c8-9d8574569a62"
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": brand_kit_id,
                    "project_id": project_id,
                    "client_name": "Koala AU",
                    "prepared_by": "Partner Agency",
                    "logo_url": "https://koala.example/logo.png",
                    "primary_color": "#0f766e",
                    "secondary_color": "#111827",
                    "footer_text": "Prepared for Koala AU board review",
                    "updated_by": "runtime-console",
                    "created_at": now,
                    "updated_at": now,
                },
                [
                    {
                        "id": "2782a901-8cdf-47e7-bbdb-345d9ca66efe",
                        "event_type": "project_brand_kit_saved",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "runtime-console",
                        "target_type": "project_brand_kit",
                        "target_id": brand_kit_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"project_ids": [project_id]},
                        "output_refs": {"project_brand_kit_ids": [brand_kit_id]},
                        "method_version": "project_brand_kit_v1",
                        "reason": "save project white-label brand configuration",
                        "created_at": now,
                    }
                ],
            ]
        )
        record = PostgresEvidenceRepository(connection).get_project_brand_kit(project_id=project_id)
        self.assertIsInstance(record, RuntimeProjectBrandKit)
        assert record is not None
        self.assertEqual(record.brand_kit["client_name"], "Koala AU")
        self.assertEqual(record.audit_events[0]["target_type"], "project_brand_kit")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM project_brand_kits WHERE project_id = %s", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_saves_score_weight_config_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        config_id = "7daa9492-8fb2-565e-827a-bfd3de846cde"
        weights = {
            **AU_VISIBILITY_V1,
            "MentionScore": 0.20,
            "FreshnessScore": 0.03,
        }
        config_row = {
            "id": config_id,
            "project_id": project_id,
            "formula_version": "au_visibility_v1",
            "weights": weights,
            "updated_by": "runtime-console",
            "notes": "prioritize mention",
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "2d3d80f1-74de-49ee-a990-a47e44d88ccf",
            "event_type": "score_weight_config_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "score_weight_config",
            "target_id": config_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"project_ids": [project_id]},
            "output_refs": {"score_weight_config_ids": [config_id]},
            "method_version": "score_weight_config_v1",
            "reason": "save project-level AU visibility score weights",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, None, config_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).save_score_weight_config(
            RuntimeScoreWeightConfigInput(
                project_id=project_id,
                weights=weights,
                updated_by="runtime-console",
                notes="prioritize mention",
            )
        )

        self.assertIsInstance(record, RuntimeScoreWeightConfig)
        self.assertEqual(record.score_weight_config["weights"]["MentionScore"], 0.20)
        self.assertEqual(record.audit_events[0]["event_type"], "score_weight_config_saved")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO score_weight_configs", executed_sql)
        self.assertIn("ON CONFLICT (project_id, formula_version) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_saves_candidate_score_formula_weights(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        config_id = "74ef8cfb-06e4-5659-a178-d1e3ee7dc7cb"
        config_row = {
            "id": config_id,
            "project_id": project_id,
            "formula_version": "au_visibility_v1_1_local_boost",
            "weights": AU_VISIBILITY_V1_1_LOCAL_BOOST,
            "updated_by": "runtime-console",
            "notes": "test local boost formula",
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "2d3d80f1-74de-49ee-a990-a47e44d88ccf",
            "event_type": "score_weight_config_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "score_weight_config",
            "target_id": config_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"project_ids": [project_id]},
            "output_refs": {"score_weight_config_ids": [config_id]},
            "method_version": "score_weight_config_v1",
            "reason": "save project-level AU visibility score weights",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, None, config_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).save_score_weight_config(
            RuntimeScoreWeightConfigInput(
                project_id=project_id,
                formula_version="au_visibility_v1_1_local_boost",
                weights=AU_VISIBILITY_V1_1_LOCAL_BOOST,
                updated_by="runtime-console",
                notes="test local boost formula",
            )
        )

        self.assertEqual(record.score_weight_config["formula_version"], "au_visibility_v1_1_local_boost")
        self.assertEqual(record.score_weight_config["weights"], AU_VISIBILITY_V1_1_LOCAL_BOOST)
        insert_params = next(params for sql, params in connection.calls if "INSERT INTO score_weight_configs" in sql)
        self.assertEqual(insert_params[2], "au_visibility_v1_1_local_boost")

    def test_postgres_repository_reads_score_weight_config_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        config_id = "7daa9492-8fb2-565e-827a-bfd3de846cde"
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": config_id,
                    "project_id": project_id,
                    "formula_version": "au_visibility_v1",
                    "weights": AU_VISIBILITY_V1,
                    "updated_by": "runtime-console",
                    "notes": "default review",
                    "created_at": now,
                    "updated_at": now,
                },
                [
                    {
                        "id": "2d3d80f1-74de-49ee-a990-a47e44d88ccf",
                        "event_type": "score_weight_config_saved",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "runtime-console",
                        "target_type": "score_weight_config",
                        "target_id": config_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"project_ids": [project_id]},
                        "output_refs": {"score_weight_config_ids": [config_id]},
                        "method_version": "score_weight_config_v1",
                        "reason": "save project-level AU visibility score weights",
                        "created_at": now,
                    }
                ],
            ]
        )
        record = PostgresEvidenceRepository(connection).get_score_weight_config(project_id=project_id)
        self.assertIsInstance(record, RuntimeScoreWeightConfig)
        assert record is not None
        self.assertEqual(record.score_weight_config["weights"], AU_VISIBILITY_V1)
        self.assertEqual(record.audit_events[0]["target_type"], "score_weight_config")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM score_weight_configs WHERE project_id = %s AND formula_version = %s", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_saves_human_review_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        target_id = "38f0251c-c380-4197-b6c9-3e630b127844"
        review_row = {
            "id": "f25cdddc-c3e7-4fcb-90b8-557fd6465ea7",
            "project_id": project_id,
            "target_type": "visibility_score_snapshot",
            "target_id": target_id,
            "review_status": "approved",
            "decision": "approved_for_report",
            "reviewer_id": "runtime-console",
            "notes": "reviewed score evidence",
            "payload": {"source": "runtime-console"},
            "created_at": now,
        }
        audit_row = {
            "id": "b9b398cf-7a61-465e-bfdd-0870b9633523",
            "event_type": "human_review_recorded",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "human_review_record",
            "target_id": review_row["id"],
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"review_target": [{"target_type": "visibility_score_snapshot", "target_id": target_id}]},
            "output_refs": {"human_review_record_ids": [review_row["id"]]},
            "method_version": "human_review_v1",
            "reason": "record human review decision for an auditable runtime object",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, review_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).save_human_review(
            RuntimeHumanReviewInput(
                project_id=project_id,
                target_type="visibility_score_snapshot",
                target_id=target_id,
                review_status="approved",
                decision="approved_for_report",
                reviewer_id="runtime-console",
                notes="reviewed score evidence",
                payload={"source": "runtime-console"},
            )
        )

        self.assertIsInstance(record, RuntimeHumanReviewRecord)
        self.assertEqual(record.human_review["decision"], "approved_for_report")
        self.assertEqual(record.audit_events[0]["event_type"], "human_review_recorded")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO human_review_records", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_lists_runtime_human_reviews_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        review_id = "f25cdddc-c3e7-4fcb-90b8-557fd6465ea7"
        review_row = {
            "id": review_id,
            "project_id": project_id,
            "target_type": "content_draft",
            "target_id": "1e53e0b4-7b1a-54d6-a918-fd8774df7bdd",
            "review_status": "needs_changes",
            "decision": "rewrite_local_examples",
            "reviewer_id": "editor@example.com",
            "notes": "needs stronger AU evidence",
            "payload": {"target_label": "draft"},
            "created_at": now,
        }
        audit_row = {
            "id": "b9b398cf-7a61-465e-bfdd-0870b9633523",
            "event_type": "human_review_recorded",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "editor@example.com",
            "target_type": "human_review_record",
            "target_id": review_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"review_target": [{"target_type": "content_draft", "target_id": review_row["target_id"]}]},
            "output_refs": {"human_review_record_ids": [review_id]},
            "method_version": "human_review_v1",
            "reason": "record human review decision for an auditable runtime object",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [review_row], [audit_row]])

        page = PostgresEvidenceRepository(connection).list_runtime_human_reviews(
            project_id=project_id,
            target_type="content_draft",
            review_status="needs_changes",
            limit=5,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeHumanReviewPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].human_review["decision"], "rewrite_local_examples")
        self.assertEqual(page.records[0].audit_events[0]["target_type"], "human_review_record")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM human_review_records WHERE project_id = %s AND target_type = %s AND review_status = %s", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_confirms_entity_alias_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        alias_row = {
            "id": "b7f7a2fb-9191-50f0-aa33-a56fed6b0ac5",
            "entity_id": brand_id,
            "entity_kind": "brand",
            "alias": "examplebrand.com.au",
            "alias_type": "domain",
            "confidence": 1.0,
            "confirmed_by": "runtime-console",
            "created_at": now,
            "project_id": project_id,
            "canonical_name": "ExampleBrand",
            "official_domains": ["https://examplebrand.com.au"],
            "parent_company": None,
            "product_lines": ["mattresses"],
            "status": "active",
        }
        audit_row = {
            "id": "725067ce-00b5-49a5-a3ec-8b8e74c85f4f",
            "event_type": "entity_alias_confirmed",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "entity_alias",
            "target_id": alias_row["id"],
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"entity_ids": [brand_id]},
            "output_refs": {"entity_alias_ids": [alias_row["id"]]},
            "method_version": "entity_alias_confirm_v1",
            "reason": "Runtime entity alias confirmation for parser disambiguation",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": brand_id,
                    "project_id": project_id,
                    "canonical_name": "ExampleBrand",
                    "official_domains": ["https://examplebrand.com.au"],
                    "parent_company": None,
                    "product_lines": ["mattresses"],
                    "status": "active",
                },
                None,
                alias_row,
                [audit_row],
            ]
        )
        record = PostgresEvidenceRepository(connection).confirm_entity_alias(
            EntityAliasInput(
                entity_id=brand_id,
                entity_kind="brand",
                alias="examplebrand.com.au",
                alias_type="domain",
                confirmed_by="runtime-console",
                notes="Runtime entity alias confirmation for parser disambiguation",
            )
        )
        self.assertIsInstance(record, RuntimeEntityAlias)
        self.assertEqual(record.entity_alias["alias"], "examplebrand.com.au")
        self.assertEqual(record.entity["canonical_name"], "ExampleBrand")
        self.assertEqual(record.audit_events[0]["event_type"], "entity_alias_confirmed")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM brand_entities WHERE id = %s", executed_sql)
        self.assertIn("INSERT INTO entity_aliases", executed_sql)
        self.assertIn("ON CONFLICT (id) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_reads_confirmed_entity_alias_terms(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        competitor_id = "0c0a4e87-c27a-58ee-b379-3cf3adaf7c0d"
        connection = RecordingConnection(
            result_sets=[
                [
                    {"entity_id": brand_id, "alias": "ExampleBrand Australia"},
                    {"entity_id": brand_id, "alias": "examplebrand.com.au"},
                    {"entity_id": competitor_id, "alias": "Competitor AU"},
                    {"entity_id": brand_id, "alias": "ExampleBrand Australia"},
                ]
            ]
        )
        aliases = PostgresEvidenceRepository(connection).get_confirmed_entity_alias_terms(project_id)
        self.assertEqual(
            aliases,
            {
                brand_id: ("ExampleBrand Australia", "examplebrand.com.au"),
                competitor_id: ("Competitor AU",),
            },
        )
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM entity_aliases ea JOIN", executed_sql)
        self.assertIn("entity.entity_kind = ea.entity_kind", executed_sql)
        self.assertIn("WHERE entity.project_id = %s", executed_sql)

    def test_postgres_repository_lists_runtime_entity_alias_candidates(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        connection = RecordingConnection(
            result_sets=[
                [
                    {
                        "id": brand_id,
                        "project_id": project_id,
                        "entity_kind": "brand",
                        "canonical_name": "ExampleBrand",
                        "official_domains": ["https://www.examplebrand.com.au"],
                        "parent_company": "Example Holdings",
                        "product_lines": ["mattresses", "pillows"],
                        "status": "active",
                    }
                ],
                [
                    {"entity_id": brand_id, "alias": "ExampleBrand Australia"},
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_entity_alias_candidates(
            project_id=project_id,
            entity_kind="brand",
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeEntityAliasCandidatePage)
        aliases = [record.candidate["alias"] for record in page.records]
        self.assertNotIn("ExampleBrand Australia", aliases)
        self.assertIn("examplebrand.com.au", aliases)
        self.assertIn("mattresses", aliases)
        self.assertIn("pillows", aliases)
        self.assertIn("Example Holdings", aliases)
        self.assertEqual(page.records[0].confirmed_aliases, ("ExampleBrand Australia",))
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM ( SELECT id, project_id, 'brand' AS entity_kind", executed_sql)
        self.assertIn("WHERE entity.project_id = %s AND entity.entity_kind = %s", executed_sql)

    def test_postgres_repository_lists_runtime_entity_aliases_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        alias_id = "b7f7a2fb-9191-50f0-aa33-a56fed6b0ac5"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": alias_id,
                        "entity_id": brand_id,
                        "entity_kind": "brand",
                        "alias": "ExampleBrand Australia",
                        "alias_type": "alias",
                        "confidence": 0.98,
                        "confirmed_by": "runtime-console",
                        "created_at": now,
                        "project_id": project_id,
                        "canonical_name": "ExampleBrand",
                        "official_domains": ["https://examplebrand.com.au"],
                        "parent_company": None,
                        "product_lines": ["mattresses"],
                        "status": "active",
                    }
                ],
                [
                    {
                        "id": "725067ce-00b5-49a5-a3ec-8b8e74c85f4f",
                        "event_type": "entity_alias_confirmed",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "runtime-console",
                        "target_type": "entity_alias",
                        "target_id": alias_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"entity_ids": [brand_id]},
                        "output_refs": {"entity_alias_ids": [alias_id]},
                        "method_version": "entity_alias_confirm_v1",
                        "reason": "confirm entity alias for parser disambiguation",
                        "created_at": now,
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_entity_aliases(
            project_id=project_id,
            entity_kind="brand",
            limit=5,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeEntityAliasPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].entity_alias["alias"], "ExampleBrand Australia")
        self.assertEqual(page.records[0].audit_events[0]["event_type"], "entity_alias_confirmed")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM entity_aliases ea JOIN", executed_sql)
        self.assertIn("entity.entity_kind = ea.entity_kind", executed_sql)
        self.assertIn("WHERE entity.project_id = %s AND ea.entity_kind = %s", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)


if __name__ == "__main__":
    unittest.main()
