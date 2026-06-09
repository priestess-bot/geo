"""Core contracts and data models for the GENO AU evidence platform."""

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
    collect_prompt_with_failure_record,
    run_collection_slice,
    run_fixture_collection_slice,
)
from geno_core.collectors import (
    FixtureGoogleAIModeCollector,
    FixtureGoogleAIOCollector,
    FixtureManualBackfillCollector,
    FixtureThirdPartySerpCollector,
    ManualBackfillCollector,
    OpenAIWebSearchCollector,
    PerplexitySonarCollector,
    PlaywrightAIModeCollector,
    PlaywrightGoogleAIOCollector,
    ThirdPartySerpCollector,
)
from geno_core.geo import StaticAUGeoProvider
from geno_core.google_spike import build_google_spike_plan, evaluate_google_spike_gate
from geno_core.graph import build_citation_graph
from geno_core.industry import build_au_dtc_ecommerce_profile
from geno_core.market import build_au_market_profile
from geno_core.prompt_pack import build_au_dtc_prompt_pack
from geno_core.report import MarkdownCsvReportExporter
from geno_core.scoring import AU_VISIBILITY_V1, score_answer_analyses, score_answer_analysis

__all__ = [
    "AU_VISIBILITY_V1",
    "analyze_and_score_records",
    "build_action_plan_audit_event",
    "build_action_recommendations",
    "build_au_dtc_ecommerce_profile",
    "build_au_dtc_prompt_pack",
    "build_au_market_profile",
    "build_au_project_bootstrap",
    "build_p0a_collection_plan",
    "build_retest_schedule",
    "build_retest_comparison_audit_event",
    "collect_prompt_with_failure_record",
    "compare_retest_windows",
    "build_google_spike_plan",
    "build_citation_graph",
    "evaluate_google_spike_gate",
    "FixtureGoogleAIModeCollector",
    "FixtureGoogleAIOCollector",
    "FixtureManualBackfillCollector",
    "FixtureThirdPartySerpCollector",
    "ManualBackfillCollector",
    "MarkdownCsvReportExporter",
    "OpenAIWebSearchCollector",
    "PerplexitySonarCollector",
    "PlaywrightAIModeCollector",
    "PlaywrightGoogleAIOCollector",
    "run_collection_slice",
    "run_fixture_collection_slice",
    "score_answer_analyses",
    "score_answer_analysis",
    "StaticAUGeoProvider",
    "ThirdPartySerpCollector",
]
