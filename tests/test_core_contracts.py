from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

from geno_core.audit import build_audit_event, hash_payload
from geno_core.market import build_au_market_profile
from geno_core.models import AnswerAnalysis, ReportExport
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
            pdf_url=None,
            csv_url=None,
            exported_by="system",
            exported_at=datetime(2026, 6, 9, tzinfo=UTC),
        )
        with self.assertRaises(FrozenInstanceError):
            report.report_version = "v2"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
