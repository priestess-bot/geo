from __future__ import annotations

from pathlib import Path
import unittest


class WebConsoleContractsTest(unittest.TestCase):
    def test_runtime_console_contains_traceability_links_and_graph_maps(self) -> None:
        page_source = Path("apps/web/app/page.tsx").read_text(encoding="utf-8")

        self.assertIn("function CitationGraphMap", page_source)
        self.assertIn("function TraceabilityMap", page_source)
        self.assertIn("function NodeLink", page_source)
        self.assertIn('id={anchorId("traceability-map", "runtime")}', page_source)
        self.assertIn('id={anchorId("source-node", item.node.id)}', page_source)
        self.assertIn('id={anchorId("answer-run", run.answer_run.id)}', page_source)
        self.assertIn('href={anchorHref("answer-run", run.answer_run.id)}', page_source)
        self.assertIn('href={anchorHref("source-node", item.node.id)}', page_source)

    def test_runtime_console_styles_highlight_deep_link_targets(self) -> None:
        css_source = Path("apps/web/app/globals.css").read_text(encoding="utf-8")

        self.assertIn(".graphCanvas", css_source)
        self.assertIn(".traceMapCanvas", css_source)
        self.assertIn(".nodeLink", css_source)
        self.assertIn(":target", css_source)

    def test_runtime_console_discloses_report_method_boundaries(self) -> None:
        page_source = Path("apps/web/app/page.tsx").read_text(encoding="utf-8")

        self.assertIn("Method Disclosure", page_source)
        self.assertIn("Google coverage", page_source)
        self.assertIn("Google gate", page_source)
        self.assertIn("API/browser fidelity", page_source)
        self.assertIn("Trigger denominator", page_source)
        self.assertIn("Mention denominator", page_source)
        self.assertIn("Recommendation denominator", page_source)
        self.assertIn("Attempted records", page_source)
        self.assertIn("Surface-triggered records", page_source)
        self.assertIn("Evidence trigger rate", page_source)
        self.assertIn("score_rate_denominators", page_source)
        self.assertIn("Access distribution", page_source)
        self.assertIn("Google remains outside the main scoring denominator", page_source)

    def test_runtime_console_surfaces_api_browser_fidelity_checks(self) -> None:
        page_source = Path("apps/web/app/page.tsx").read_text(encoding="utf-8")

        self.assertIn('fidelityChecks: "/v1/fidelity-checks/runtime"', page_source)
        self.assertIn('fidelityTrend: "/v1/fidelity-checks/runtime/trend"', page_source)
        self.assertIn("RuntimeFidelityCheck", page_source)
        self.assertIn("RuntimeFidelityTrend", page_source)
        self.assertIn("api_browser_fidelity_checked", page_source)
        self.assertIn("Fidelity audit", page_source)
        self.assertIn("Fidelity query", page_source)
        self.assertIn("Fidelity trend", page_source)
        self.assertIn("Trend query", page_source)
        self.assertIn("Payload hash", page_source)

    def test_runtime_console_surfaces_collection_run_quality(self) -> None:
        page_source = Path("apps/web/app/page.tsx").read_text(encoding="utf-8")

        self.assertIn('collectionRuns: "/v1/collection-runs/runtime"', page_source)
        self.assertIn("type CollectionRun", page_source)
        self.assertIn("Collection Run Quality", page_source)
        self.assertIn("Success rate", page_source)
        self.assertIn("Trigger rate", page_source)
        self.assertIn("Answer rate", page_source)
        self.assertIn("Total cost", page_source)
        self.assertIn("Avg cost/run", page_source)
        self.assertIn("Avg duration", page_source)
        self.assertIn("Duration", page_source)
        self.assertIn("duration_ms", page_source)
        self.assertIn("total_duration_ms", page_source)
        self.assertIn("average_duration_ms", page_source)
        self.assertIn("failure_summary", page_source)

    def test_runtime_console_surfaces_parser_comparison(self) -> None:
        page_source = Path("apps/web/app/page.tsx").read_text(encoding="utf-8")

        self.assertIn("Parser agreement", page_source)
        self.assertIn("parser_comparison", page_source)
        self.assertIn("parser_ab_compare_v1", page_source)
        self.assertIn("parserComparisonText", page_source)
        self.assertIn("mismatches", page_source)
        self.assertIn("llm_call_log", page_source)
        self.assertIn("LLM call", page_source)

    def test_runtime_console_surfaces_score_weight_configuration(self) -> None:
        page_source = Path("apps/web/app/page.tsx").read_text(encoding="utf-8")

        self.assertIn("Score Weights", page_source)
        self.assertIn("saveScoreWeightConfig", page_source)
        self.assertIn("/v1/score-weight-configs/runtime", page_source)
        self.assertIn("/v1/score-formulas/runtime", page_source)
        self.assertIn("Formula catalog", page_source)
        self.assertIn("Formula version", page_source)
        self.assertIn("Selected formula", page_source)
        self.assertIn("Formula status", page_source)
        self.assertIn("Formula note", page_source)
        self.assertIn("Supersedes", page_source)
        self.assertIn("component_weights_snapshot", page_source)
        self.assertIn("Weight snapshot", page_source)

    def test_runtime_console_surfaces_brand_logo_upload(self) -> None:
        page_source = Path("apps/web/app/page.tsx").read_text(encoding="utf-8")

        self.assertIn("Logo Upload", page_source)
        self.assertIn("uploadProjectBrandLogo", page_source)
        self.assertIn("/v1/project-brand-kits/runtime/logo", page_source)
        self.assertIn('name="brand_logo"', page_source)
        self.assertIn('type="file"', page_source)
        self.assertIn("project_brand_logo_uploaded", page_source)

    def test_runtime_console_surfaces_prompt_file_import(self) -> None:
        page_source = Path("apps/web/app/page.tsx").read_text(encoding="utf-8")

        self.assertIn("Prompt CSV Import", page_source)
        self.assertIn("Prompt File Import", page_source)
        self.assertIn("importRuntimePromptsFile", page_source)
        self.assertIn("/v1/prompts/runtime/import.csv", page_source)
        self.assertIn("/v1/prompts/runtime/import.file", page_source)
        self.assertIn("/v1/prompts/runtime/imports", page_source)
        self.assertIn("RuntimePromptImportHistoryItem", page_source)
        self.assertIn("Prompt Import History", page_source)
        self.assertIn("Import query", page_source)
        self.assertIn(".csv or .xlsx", page_source)
        self.assertIn('name="prompt_file"', page_source)

    def test_runtime_console_surfaces_human_review_trail(self) -> None:
        page_source = Path("apps/web/app/page.tsx").read_text(encoding="utf-8")
        css_source = Path("apps/web/app/globals.css").read_text(encoding="utf-8")

        self.assertIn("Human Review Trail", page_source)
        self.assertIn("Review Queue", page_source)
        self.assertIn("submitHumanReview", page_source)
        self.assertIn("/v1/human-reviews/runtime", page_source)
        self.assertIn("/v1/human-reviews/runtime/queue", page_source)
        self.assertIn("RuntimeHumanReviewQueueItem", page_source)
        self.assertIn("Queue query", page_source)
        self.assertIn("human_review_recorded", page_source)
        self.assertIn("content_draft_review_status_updated", page_source)
        self.assertIn("Draft audit", page_source)
        self.assertIn("human_review_v1", page_source)
        self.assertIn("approved_for_report", page_source)
        self.assertIn(".humanReviewGrid", css_source)
        self.assertIn(".humanReviewForm", css_source)

    def test_runtime_console_surfaces_pgvector_knowledge_search(self) -> None:
        page_source = Path("apps/web/app/page.tsx").read_text(encoding="utf-8")

        self.assertIn("pgvector Knowledge Search", page_source)
        self.assertIn("/v1/knowledge-facts/runtime/search", page_source)
        self.assertIn("RuntimeKnowledgeSearch", page_source)
        self.assertIn("knowledge_fact_embeddings_indexed", page_source)
        self.assertIn("fixture-knowledge-embedding-v1", page_source)


if __name__ == "__main__":
    unittest.main()
