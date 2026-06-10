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
    build_manual_backfill_record,
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
from geno_core.repository import PostgresEvidenceRepository
from geno_core.runtime import (
    RuntimePersistenceError,
    build_object_store_from_env,
    build_repository_from_env,
    close_repository_connection,
    connect_postgres_from_env,
)
from geno_core.scoring import AU_VISIBILITY_V1, score_answer_analyses, score_answer_analysis
from geno_core.traceability import build_traceability_bundle

__all__ = [
    "AU_VISIBILITY_V1",
    "analyze_and_score_records",
    "build_action_plan_audit_event",
    "build_action_recommendations",
    "build_au_dtc_ecommerce_profile",
    "build_au_dtc_prompt_pack",
    "build_au_market_profile",
    "build_au_project_bootstrap",
    "build_manual_backfill_record",
    "build_p0a_collection_plan",
    "build_retest_schedule",
    "build_traceability_bundle",
    "build_retest_comparison_audit_event",
    "collect_prompt_with_failure_record",
    "compare_retest_windows",
    "build_google_spike_plan",
    "build_object_store_from_env",
    "build_citation_graph",
    "build_content_drafts",
    "build_content_engine_audit_event",
    "build_integration_connectors",
    "build_localized_knowledge_facts",
    "build_manual_distribution_records",
    "evaluate_google_spike_gate",
    "build_repository_from_env",
    "close_repository_connection",
    "connect_postgres_from_env",
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
    "PostgresEvidenceRepository",
    "RuntimePersistenceError",
    "run_collection_slice",
    "run_fixture_collection_slice",
    "score_answer_analyses",
    "score_answer_analysis",
    "search_knowledge_facts",
    "StaticAUGeoProvider",
    "ThirdPartySerpCollector",
]
