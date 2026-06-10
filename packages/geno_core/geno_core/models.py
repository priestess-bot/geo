from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


ActorType = Literal["user", "system", "worker", "api"]
AccessMethod = Literal["browser", "official_api", "third_party_api", "manual"]
ProjectRole = Literal["owner", "admin", "analyst", "viewer"]
CollectionStatus = Literal["planned", "completed", "failed"]
GoogleSpikeFailureReason = Literal[
    "not_triggered",
    "layout_changed",
    "blocked",
    "timeout",
    "geo_mismatch",
    "account_state",
    "not_configured",
]


@dataclass(frozen=True)
class PlatformConfig:
    platform: str
    surface: str
    build_stage: str
    weight: float
    enabled: bool


@dataclass(frozen=True)
class MarketProfile:
    market: str
    market_code: str
    locale: str
    timezone: str
    currency: str
    primary_language: str
    cities: list[str]
    source_types: list[str]
    platforms: list[PlatformConfig]


@dataclass(frozen=True)
class IndustryProfile:
    market_code: str
    industry_code: str
    display_name: str
    default_prompt_templates: tuple[str, ...]
    source_type_weights: dict[str, float]
    competitor_fields: tuple[str, ...]
    required_local_facts: tuple[str, ...]
    report_template: str


@dataclass(frozen=True)
class Tenant:
    id: str
    name: str
    slug: str
    created_at: datetime


@dataclass(frozen=True)
class Project:
    id: str
    tenant_id: str
    name: str
    market_code: str
    industry_code: str
    target_brand: str
    category: str
    prompt_version: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class ProjectMember:
    id: str
    project_id: str
    user_id: str
    role: ProjectRole
    created_at: datetime


@dataclass(frozen=True)
class BrandEntity:
    id: str
    project_id: str
    canonical_name: str
    official_domains: tuple[str, ...]
    parent_company: str | None
    product_lines: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class CompetitorEntity:
    id: str
    project_id: str
    canonical_name: str
    official_domains: tuple[str, ...]
    parent_company: str | None
    product_lines: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class EntityAlias:
    id: str
    entity_id: str
    entity_kind: str
    alias: str
    alias_type: str
    confidence: float
    confirmed_by: str | None
    created_at: datetime


@dataclass(frozen=True)
class PromptQuestion:
    id: str
    project_id: str
    market_code: str
    industry_code: str
    text: str
    intent_type: str
    city: str
    language: str
    target_brand: str
    competitors: tuple[str, ...]
    priority: int
    intent_weight: float
    prompt_version: str
    status: str


@dataclass(frozen=True)
class ProjectBootstrap:
    tenant: Tenant
    project: Project
    members: tuple[ProjectMember, ...]
    brand: BrandEntity
    competitors: tuple[CompetitorEntity, ...]
    market_profile: MarketProfile
    industry_profile: IndustryProfile
    prompt_questions: tuple[PromptQuestion, ...]
    audit_events: tuple["AuditEvent", ...]


@dataclass(frozen=True)
class RawCollectResult:
    answer_present: bool
    surface_triggered: bool
    answer_text: str
    citations: list[dict[str, Any]]
    screenshot_url: str | None
    html_snapshot_url: str | None
    raw_payload: dict[str, Any]
    model_or_surface: str
    account_state: str | None
    collector_version: str


@dataclass(frozen=True)
class AnswerRun:
    id: str
    project_id: str
    prompt_question_id: str
    platform: str
    surface: str
    access_method: AccessMethod
    market_code: str
    city: str
    language: str
    device: str
    answer_present: bool
    surface_triggered: bool
    sample_index: int
    sample_size: int
    model_or_surface: str | None
    account_state: str | None
    collector_backend_id: str
    collector_version: str
    collected_at: datetime
    status: CollectionStatus


@dataclass(frozen=True)
class RawAnswer:
    id: str
    answer_run_id: str
    answer_text: str
    raw_payload: dict[str, Any]
    raw_payload_hash: str


@dataclass(frozen=True)
class AnswerCitation:
    id: str
    answer_run_id: str
    url: str
    domain: str
    position: int
    source_type: str | None


@dataclass(frozen=True)
class EvidenceAsset:
    id: str
    answer_run_id: str
    asset_type: str
    url: str
    content_hash: str | None


@dataclass(frozen=True)
class CollectorLog:
    id: str
    answer_run_id: str | None
    collector_backend_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class CollectionCost:
    id: str
    answer_run_id: str | None
    project_id: str
    collector_backend_id: str
    llm_provider: str | None
    llm_tokens: int
    llm_cost: float
    proxy_or_vendor_cost: float
    compute_cost: float
    total_cost: float
    created_at: datetime


@dataclass(frozen=True)
class RawEvidenceRecord:
    answer_run: AnswerRun
    raw_answer: RawAnswer
    citations: tuple[AnswerCitation, ...]
    evidence_assets: tuple[EvidenceAsset, ...]
    collector_logs: tuple[CollectorLog, ...]
    collection_cost: CollectionCost
    audit_events: tuple["AuditEvent", ...]


@dataclass(frozen=True)
class ManualBackfillInput:
    project_id: str
    prompt_question_id: str
    prompt_text: str
    market_code: str
    city: str
    language: str
    platform: str
    surface: str
    answer_text: str
    citation_urls: tuple[str, ...] = ()
    screenshot_url: str | None = None
    html_snapshot_url: str | None = None
    answer_present: bool = True
    surface_triggered: bool = True
    sample_index: int = 1
    sample_size: int = 1
    device: str = "desktop"
    account_state: str | None = None
    submitted_by: str = "manual-backfill"
    notes: str | None = None
    collected_at: datetime | None = None


@dataclass(frozen=True)
class CollectionFailureRecord:
    answer_run: AnswerRun
    collector_logs: tuple[CollectorLog, ...]
    collection_cost: CollectionCost
    audit_events: tuple["AuditEvent", ...]
    error_type: str
    error_message: str


@dataclass(frozen=True)
class CollectionPlan:
    project_id: str
    prompt_count: int
    platform_count: int
    geo_count: int
    sample_size: int
    planned_runs: int
    platform_surfaces: tuple[str, ...]
    geo_cities: tuple[str, ...]


@dataclass(frozen=True)
class GoogleSpikePlan:
    project_id: str
    prompt_count: int
    surfaces: tuple[str, ...]
    geo_cities: tuple[str, ...]
    sample_size: int
    planned_runs: int
    candidate_backends: tuple[str, ...]
    failure_reasons: tuple[GoogleSpikeFailureReason, ...]


@dataclass(frozen=True)
class GoogleSpikeGateResult:
    project_id: str
    gate_status: Literal["pass", "fail"]
    planned_runs: int
    completed_runs: int
    google_aio_completed_runs: int
    success_rate: float
    trigger_rate: float
    best_backend_id: str | None
    limited_coverage: bool
    failure_summary: dict[str, int]
    recommendation: str


@dataclass(frozen=True)
class SourceGraphNode:
    id: str
    project_id: str
    source_url: str
    source_domain: str
    source_type: str
    topic: str | None
    source_gap_type: str | None
    answer_run_ids: tuple[str, ...]
    citation_count: int


@dataclass(frozen=True)
class SourceGraphEvidence:
    id: str
    source_graph_id: str
    answer_run_id: str
    answer_citation_id: str | None
    relation_type: str


@dataclass(frozen=True)
class SourceGap:
    source_type: str
    gap_type: str
    observed_count: int
    expected_weight: float
    recommendation: str


@dataclass(frozen=True)
class CompetitorBenchmark:
    id: str
    project_id: str
    competitor_name: str
    mention_count: int
    mention_rate: float
    recommendation_count: int
    citation_overlap_count: int
    local_relevance_average: float
    answer_run_ids: tuple[str, ...]


@dataclass(frozen=True)
class CitationGraphResult:
    nodes: tuple[SourceGraphNode, ...]
    evidence_links: tuple[SourceGraphEvidence, ...]
    source_gaps: tuple[SourceGap, ...]
    competitor_benchmarks: tuple[CompetitorBenchmark, ...]


@dataclass(frozen=True)
class ActionRecommendation:
    id: str
    project_id: str
    title: str
    description: str
    priority: str
    status: str
    owner_id: str
    source_gap_type: str | None
    evidence_answer_run_ids: tuple[str, ...]
    related_source_types: tuple[str, ...]
    next_check_date: datetime
    created_at: datetime


@dataclass(frozen=True)
class RetestSchedule:
    id: str
    project_id: str
    prompt_version: str
    sample_size: int
    offsets_days: tuple[int, ...]
    scheduled_dates: tuple[datetime, ...]
    answer_run_ids: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class RetestComparison:
    id: str
    project_id: str
    baseline_score: float
    retest_score: float
    score_delta: float
    baseline_answer_run_ids: tuple[str, ...]
    retest_answer_run_ids: tuple[str, ...]
    trend: str
    created_at: datetime


@dataclass(frozen=True)
class LocalizedKnowledgeFact:
    id: str
    project_id: str
    market_code: str
    fact_type: str
    subject: str
    predicate: str
    object_value: str
    city: str | None
    evidence_source_id: str | None
    confidence: float
    status: str
    valid_from: datetime
    valid_until: datetime | None


@dataclass(frozen=True)
class KnowledgeSearchResult:
    fact: LocalizedKnowledgeFact
    score: float
    fallback_used: bool


@dataclass(frozen=True)
class ContentDraft:
    id: str
    project_id: str
    title: str
    content_type: str
    content_template_id: str
    target_question_ids: tuple[str, ...]
    target_city: str
    target_platform: str
    target_source_type: str
    used_knowledge_fact_ids: tuple[str, ...]
    source_gap_types: tuple[str, ...]
    source_action_id: str | None
    evidence_answer_run_ids: tuple[str, ...]
    draft_markdown: str
    review_status: str
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class IntegrationConnector:
    id: str
    project_id: str
    provider: str
    connection_status: str
    capabilities: tuple[str, ...]
    auth_mode: str
    created_at: datetime


@dataclass(frozen=True)
class ManualDistributionRecord:
    id: str
    project_id: str
    content_draft_id: str
    platform: str
    target_url: str
    status: str
    submitted_at: datetime | None
    checked_at: datetime | None
    notes: str


@dataclass(frozen=True)
class AnswerAnalysis:
    id: str
    answer_run_id: str
    parser_engine_id: str
    analysis_version: str
    brand_mentioned: bool
    brand_recommended: bool
    brand_position: int | None
    competitors_mentioned: list[str]
    citation_count: int
    local_relevance_score: float
    sentiment_score: float
    freshness_score: float
    competitor_share_score: float
    confidence: float
    uncertainty_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VisibilityScoreSnapshot:
    id: str
    project_id: str
    scope_type: str
    scope_value: str
    formula_version: str
    platform_weights_snapshot: dict[str, float]
    final_score: float
    trigger_rate: float
    mention_rate: float
    recommendation_rate: float
    answer_run_ids: list[str]
    created_at: datetime
    dispersion: float = 0.0


@dataclass(frozen=True)
class ScoreContribution:
    id: str
    score_snapshot_id: str
    component_name: str
    component_score: float
    weight: float
    weighted_contribution: float
    denominator: str
    evidence_answer_run_ids: list[str]
    positive_evidence_summary: str
    negative_evidence_summary: str
    confidence_note: str
    created_at: datetime


@dataclass(frozen=True)
class EvidenceLink:
    id: str
    project_id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relation_type: str
    answer_run_ids: tuple[str, ...]


@dataclass(frozen=True)
class TraceabilityBundle:
    id: str
    project_id: str
    subject_type: str
    subject_id: str
    report_export_ids: tuple[str, ...]
    score_snapshot_ids: tuple[str, ...]
    score_contribution_ids: tuple[str, ...]
    answer_run_ids: tuple[str, ...]
    raw_answer_ids: tuple[str, ...]
    answer_citation_ids: tuple[str, ...]
    evidence_asset_ids: tuple[str, ...]
    source_graph_ids: tuple[str, ...]
    source_gap_types: tuple[str, ...]
    action_recommendation_ids: tuple[str, ...]
    content_draft_ids: tuple[str, ...]
    audit_event_ids: tuple[str, ...]
    evidence_links: tuple[EvidenceLink, ...]
    explanation_summary: str


@dataclass(frozen=True)
class RuntimeEvidenceRun:
    answer_run: dict[str, Any]
    raw_answer: dict[str, Any] | None
    citations: tuple[dict[str, Any], ...]
    evidence_assets: tuple[dict[str, Any], ...]
    collector_logs: tuple[dict[str, Any], ...]
    collection_cost: dict[str, Any] | None
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeEvidencePage:
    total_count: int
    limit: int
    offset: int
    sort: str
    records: tuple[RuntimeEvidenceRun, ...]


@dataclass(frozen=True)
class RuntimeEvidenceExport:
    export_type: str
    filename: str
    media_type: str
    content: str | bytes
    content_hash: str
    filters: dict[str, Any]
    total_count: int
    row_count: int


@dataclass(frozen=True)
class RuntimeSavedView:
    saved_view: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeSavedViewPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeSavedView, ...]


@dataclass(frozen=True)
class RuntimeSavedViewInput:
    project_id: str
    name: str
    view_type: str
    filters: dict[str, Any]
    sort: str
    query_path: str
    export_path: str
    created_by: str


@dataclass(frozen=True)
class EntityAliasInput:
    entity_id: str
    entity_kind: str
    alias: str
    alias_type: str
    confidence: float = 1.0
    confirmed_by: str = "runtime-console"
    notes: str | None = None


@dataclass(frozen=True)
class RuntimeEntityAlias:
    entity_alias: dict[str, Any]
    entity: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeEntityAliasPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeEntityAlias, ...]


@dataclass(frozen=True)
class RuntimeEntityAliasCandidate:
    candidate: dict[str, Any]
    entity: dict[str, Any]
    confirmed_aliases: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeEntityAliasCandidatePage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeEntityAliasCandidate, ...]


@dataclass(frozen=True)
class RuntimeScoreSnapshotRun:
    answer_run: dict[str, Any]
    analysis: dict[str, Any] | None


@dataclass(frozen=True)
class RuntimeScoreSnapshot:
    snapshot: dict[str, Any]
    contributions: tuple[dict[str, Any], ...]
    answer_runs: tuple[RuntimeScoreSnapshotRun, ...]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeScoreSnapshotPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeScoreSnapshot, ...]


@dataclass(frozen=True)
class RuntimeCitationGraphNode:
    node: dict[str, Any]
    answer_runs: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeCitationGraph:
    project_id: str
    nodes: tuple[RuntimeCitationGraphNode, ...]
    evidence_links: tuple[dict[str, Any], ...]
    source_gaps: tuple[dict[str, Any], ...]
    competitor_benchmarks: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeCitationGraphPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeCitationGraph, ...]


@dataclass(frozen=True)
class RuntimeProject:
    project: dict[str, Any]
    tenant: dict[str, Any]
    brand: dict[str, Any] | None
    competitors: tuple[dict[str, Any], ...]
    prompt_count: int
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeProjectPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeProject, ...]


@dataclass(frozen=True)
class RuntimeProjectBrandKit:
    brand_kit: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeProjectBrandKitInput:
    project_id: str
    client_name: str
    prepared_by: str
    logo_url: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    footer_text: str | None = None
    updated_by: str = "runtime-console"


@dataclass(frozen=True)
class RuntimePromptPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimePromptImportInput:
    project_id: str
    csv_content: str
    imported_by: str = "runtime-console"
    max_rows: int = 100


@dataclass(frozen=True)
class RuntimePromptImportResult:
    prompt_import: dict[str, Any]
    prompts: tuple[dict[str, Any], ...]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeReportExport:
    report_export: dict[str, Any]
    score_snapshots: tuple[dict[str, Any], ...]
    answer_runs: tuple[dict[str, Any], ...]
    citation_graph: RuntimeCitationGraph | None
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeReportExportPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeReportExport, ...]


@dataclass(frozen=True)
class RuntimeReportArtifact:
    report_export: dict[str, Any]
    artifact_type: str
    template: str
    template_payload: dict[str, Any]
    template_hash: str
    filename: str
    media_type: str
    content: str | bytes
    content_hash: str
    filters: dict[str, Any]
    filter_hash: str
    sort: str
    total_count: int
    row_count: int


@dataclass(frozen=True)
class RuntimeActionPlan:
    retest_schedule: dict[str, Any]
    action_recommendations: tuple[dict[str, Any], ...]
    retest_comparisons: tuple[dict[str, Any], ...]
    answer_runs: tuple[dict[str, Any], ...]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeActionPlanPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeActionPlan, ...]


@dataclass(frozen=True)
class RuntimeContentDraft:
    draft: dict[str, Any]
    target_questions: tuple[dict[str, Any], ...]
    knowledge_facts: tuple[dict[str, Any], ...]
    answer_runs: tuple[dict[str, Any], ...]
    action_recommendation: dict[str, Any] | None
    manual_distribution_records: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeContentEngine:
    project_id: str
    knowledge_facts: tuple[dict[str, Any], ...]
    content_drafts: tuple[RuntimeContentDraft, ...]
    integration_connectors: tuple[dict[str, Any], ...]
    manual_distribution_records: tuple[dict[str, Any], ...]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeContentEnginePage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeContentEngine, ...]


@dataclass(frozen=True)
class RuntimeTraceabilityDetail:
    traceability_bundle: dict[str, Any]
    report_exports: tuple[dict[str, Any], ...]
    score_snapshots: tuple[RuntimeScoreSnapshot, ...]
    evidence_runs: tuple[RuntimeEvidenceRun, ...]
    citation_graph: RuntimeCitationGraph | None
    action_recommendations: tuple[dict[str, Any], ...]
    content_drafts: tuple[RuntimeContentDraft, ...]
    audit_events: tuple[dict[str, Any], ...]
    evidence_links: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class AuditEvent:
    id: str
    event_type: str
    project_id: str
    actor_type: ActorType
    actor_id: str
    target_type: str
    target_id: str
    before_hash: str | None
    after_hash: str | None
    input_refs: dict[str, list[str]]
    output_refs: dict[str, list[str]]
    method_version: str | None
    reason: str | None
    created_at: datetime


@dataclass(frozen=True)
class ReportExport:
    id: str
    project_id: str
    market_code: str
    report_version: str
    report_type: str
    score_snapshot_ids: tuple[str, ...]
    answer_run_ids: tuple[str, ...]
    prompt_version: str
    scoring_formula_version: str
    platform_weights_snapshot: dict[str, float]
    method_disclosure: dict[str, Any]
    sample_size: int
    window_start: datetime
    window_end: datetime
    methodology_hash: str
    markdown_url: str | None
    pdf_url: str | None
    csv_url: str | None
    exported_by: str
    exported_at: datetime
