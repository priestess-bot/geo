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
    evidence_asset_hashes: dict[str, str] | None = None


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
    duration_ms: int
    created_at: datetime


@dataclass(frozen=True)
class LLMCallLog:
    id: str
    project_id: str | None
    answer_run_id: str | None
    purpose: str
    provider: str
    model: str
    prompt_version: str
    request_hash: str
    response_hash: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    latency_ms: int
    status: str
    error_message: str | None
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
class BrowserFidelitySamplingPlan:
    id: str
    project_id: str
    cadence: str
    run_date: str
    selection_seed: str
    source_prompt_count: int
    source_city_count: int
    prompt_count: int
    city_count: int
    sample_size: int
    prompt_question_ids: tuple[str, ...]
    prompt_texts: tuple[str, ...]
    cities: tuple[str, ...]
    official_api_backend_ids: tuple[str, ...]
    browser_backend_ids: tuple[str, ...]
    planned_runs: int
    recommended_worker_args: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class CollectionRunSummary:
    id: str
    project_id: str
    run_type: str
    mode: str
    planned_runs: int
    attempted_runs: int
    success_count: int
    failure_count: int
    success_rate: float
    trigger_rate: float
    answer_present_rate: float
    total_cost: float
    average_cost_per_run: float
    total_duration_ms: int
    average_duration_ms: int
    collector_backend_ids: tuple[str, ...]
    platform_distribution: dict[str, int]
    city_distribution: dict[str, int]
    access_method_distribution: dict[str, int]
    failure_summary: dict[str, int]
    answer_run_ids: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class P0ACollectionReadinessGate:
    gate_status: str
    required_platforms: tuple[str, ...]
    observed_platforms: tuple[str, ...]
    required_sample_size: int
    observed_sample_sizes: tuple[int, ...]
    attempted_runs: int
    success_count: int
    failure_count: int
    missing_metadata_fields: dict[str, tuple[str, ...]]
    records_without_citations: tuple[str, ...]
    records_without_evidence_assets: tuple[str, ...]
    records_without_answer_flags: tuple[str, ...]
    records_below_sample_size: tuple[str, ...]
    failure_reasons: tuple[str, ...]


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
class GoogleSpikeReadinessGate:
    project_id: str
    gate_status: Literal["pass", "fail"]
    required_path_count: int
    observed_access_methods: tuple[str, ...]
    observed_backend_ids: tuple[str, ...]
    planned_runs: int
    attempted_runs: int
    completed_runs: int
    surface_triggered_runs: int
    answer_present_runs: int
    screenshot_or_html_runs: int
    failure_summary: dict[str, int]
    failure_reasons: tuple[str, ...]


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
class KnowledgeFactEmbedding:
    id: str
    project_id: str
    knowledge_fact_id: str
    embedding_model: str
    embedding: tuple[float, ...]
    content_hash: str
    created_at: datetime


@dataclass(frozen=True)
class RuntimeKnowledgeSearchResult:
    fact: dict[str, Any]
    score: float
    fallback_used: bool
    embedding_model: str


@dataclass(frozen=True)
class RuntimeKnowledgeSearchPage:
    total_count: int
    limit: int
    offset: int
    query: str
    market_code: str
    city: str | None
    embedding_model: str
    records: tuple[RuntimeKnowledgeSearchResult, ...]
    audit_events: tuple[dict[str, Any], ...]


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
    parser_comparison: dict[str, Any] | None = None


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
    component_weights_snapshot: dict[str, float] = field(default_factory=dict)


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
class RuntimeCollectionRun:
    collection_run: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeCollectionRunPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeCollectionRun, ...]


@dataclass(frozen=True)
class RuntimeFidelityCheck:
    fidelity_check: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeFidelityCheckPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeFidelityCheck, ...]


@dataclass(frozen=True)
class RuntimeFidelityTrendPoint:
    id: str
    project_id: str
    report_export_id: str | None
    status: str
    official_api_records: int
    browser_records: int
    comparable_prompt_city_pairs: int
    mismatch_count: int
    difference_rate: float | None
    payload_hash: str | None
    checked_at: str | None


@dataclass(frozen=True)
class RuntimeFidelityTrend:
    project_id: str | None
    report_export_id: str | None
    total_count: int
    sampled_count: int
    limit: int
    latest_status: str | None
    latest_checked_at: str | None
    earliest_checked_at: str | None
    latest_difference_rate: float | None
    earliest_difference_rate: float | None
    average_difference_rate: float | None
    max_difference_rate: float | None
    trend_direction: str
    points: tuple[RuntimeFidelityTrendPoint, ...]


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
class RuntimeScoreWeightConfig:
    score_weight_config: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeScoreWeightConfigInput:
    project_id: str
    weights: dict[str, float]
    formula_version: str = "au_visibility_v1"
    updated_by: str = "runtime-console"
    notes: str | None = None


@dataclass(frozen=True)
class RuntimeHumanReviewRecord:
    human_review: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeHumanReviewPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeHumanReviewRecord, ...]


@dataclass(frozen=True)
class RuntimeHumanReviewQueueItem:
    project_id: str
    target_type: str
    target_id: str
    title: str
    queue_status: str
    priority: int
    reason: str
    created_at: str | None
    latest_review: dict[str, Any] | None
    evidence_refs: dict[str, Any]


@dataclass(frozen=True)
class RuntimeHumanReviewQueuePage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeHumanReviewQueueItem, ...]


@dataclass(frozen=True)
class RuntimeHumanReviewInput:
    project_id: str
    target_type: str
    target_id: str
    review_status: str
    decision: str
    reviewer_id: str = "runtime-console"
    notes: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


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
class RuntimeEntityAliasBatchConfirmResult:
    batch_version: str
    requested_count: int
    confirmed_count: int
    failed_count: int
    records: tuple[RuntimeEntityAlias, ...]
    errors: tuple[dict[str, Any], ...]
    audit_summary: dict[str, Any]


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
class EntityAliasCandidateReviewInput:
    project_id: str
    candidate_id: str
    entity_id: str
    entity_kind: str
    alias: str
    alias_type: str
    decision: str
    reviewed_by: str = "runtime-console"
    source: str | None = None
    confidence: float | None = None
    reason: str | None = None
    notes: str | None = None
    evidence_answer_run_ids: tuple[str, ...] = ()
    evidence_urls: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EntityAliasCandidateAssignmentInput:
    project_id: str
    candidate_id: str
    assigned_to: str
    assigned_by: str = "runtime-console"
    assignment_status: str = "assigned"
    priority: str = "normal"
    due_at: datetime | None = None
    assignment_note: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class EntityAliasCandidateAssignmentActionInput:
    project_id: str
    candidate_id: str
    action: str
    updated_by: str = "runtime-console"
    note: str | None = None
    force: bool = False


@dataclass(frozen=True)
class RuntimeEntityAliasCandidateReview:
    review: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeEntityAliasCandidateReviewPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeEntityAliasCandidateReview, ...]


@dataclass(frozen=True)
class RuntimeEntityAliasCandidateAssignmentQueueStats:
    project_id: str
    generated_at: datetime
    method_version: str
    active_statuses: tuple[str, ...]
    total_count: int
    active_count: int
    unassigned_count: int
    overdue_count: int
    due_soon_count: int
    status_counts: dict[str, int]
    priority_counts: dict[str, int]
    oldest_due_at: datetime | None = None
    next_due_at: datetime | None = None


@dataclass(frozen=True)
class RuntimeEntityAliasCandidateBatchReviewResult:
    batch_version: str
    requested_count: int
    reviewed_count: int
    failed_count: int
    records: tuple[RuntimeEntityAliasCandidateReview, ...]
    errors: tuple[dict[str, Any], ...]
    audit_summary: dict[str, Any]


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
class RuntimeProjectUpdateInput:
    project_id: str
    name: str | None = None
    target_brand: str | None = None
    category: str | None = None
    status: str | None = None
    updated_by: str = "runtime-console"
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeProjectActionInput:
    project_id: str
    action: str
    updated_by: str = "runtime-console"
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeProjectMember:
    member: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeProjectMemberPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeProjectMember, ...]


@dataclass(frozen=True)
class RuntimeProjectMemberInvitation:
    invitation: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeProjectMemberInvitationPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeProjectMemberInvitation, ...]


@dataclass(frozen=True)
class RuntimeProjectMemberInput:
    project_id: str
    user_id: str
    role: ProjectRole
    updated_by: str = "runtime-console"
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeProjectMemberDeleteInput:
    project_id: str
    user_id: str
    deleted_by: str = "runtime-console"
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeProjectMemberInvitationInput:
    project_id: str
    email: str
    role: ProjectRole
    invited_by: str = "runtime-console"
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeProjectMemberInvitationActionInput:
    project_id: str
    invitation_id: str
    action: str
    updated_by: str = "runtime-console"
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeProjectMemberInvitationAcceptInput:
    invitation_id: str
    invite_token: str
    accepted_by: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeProjectMemberInvitationEmailInput:
    project_id: str
    invitation_id: str
    invite_token: str
    accept_base_url: str
    sent_by: str = "runtime-console"
    smtp_env_prefix: str = "GENO_NOTIFICATION_SMTP"
    subject: str | None = None
    message: str | None = None
    reason: str | None = None


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
class RuntimeProjectBrandLogoUpload:
    project_id: str
    logo_url: str
    filename: str
    content_type: str
    content_hash: str
    uploaded_by: str = "runtime-console"


@dataclass(frozen=True)
class RuntimeProjectBrandAsset:
    asset: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeProjectBrandAssetPage:
    project_id: str
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeProjectBrandAsset, ...]


@dataclass(frozen=True)
class RuntimeProjectBrandAssetInput:
    project_id: str
    asset_type: str
    asset_url: str
    category: str = "uncategorized"
    preview_url: str | None = None
    source_filename: str | None = None
    source_content_type: str | None = None
    content_hash: str | None = None
    storage_version: str | None = None
    status: str = "active"
    uploaded_by: str = "runtime-console"
    metadata: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeProjectBrandAssetScanInput:
    asset_id: str
    scan_status: str
    scanned_by: str = "runtime-console"
    scan_method_version: str = "manual_asset_scan_v1"
    scan_notes: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeProjectBrandAssetVersion:
    version_id: str
    project_id: str
    asset_type: str
    asset_url: str
    source_filename: str | None
    source_content_type: str | None
    content_hash: str | None
    uploaded_by: str | None
    uploaded_at: datetime | None
    is_active: bool
    audit_event: dict[str, Any]


@dataclass(frozen=True)
class RuntimeProjectBrandAssetVersionPage:
    project_id: str
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeProjectBrandAssetVersion, ...]


@dataclass(frozen=True)
class RuntimeProjectBrandAssetActivationInput:
    project_id: str
    asset_url: str
    activated_by: str = "runtime-console"
    reason: str | None = None


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
    source_filename: str | None = None
    source_format: str = "csv"
    source_content_type: str | None = None


@dataclass(frozen=True)
class RuntimePromptImportResult:
    prompt_import: dict[str, Any]
    prompts: tuple[dict[str, Any], ...]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimePromptImportHistoryItem:
    prompt_import: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimePromptImportHistoryPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimePromptImportHistoryItem, ...]


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
class RuntimeReportManagementInput:
    report_export_id: str
    status: str
    updated_by: str
    note: str | None = None


@dataclass(frozen=True)
class RuntimeReportExportJob:
    report_export_job: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeReportExportJobPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeReportExportJob, ...]


@dataclass(frozen=True)
class RuntimeReportExportJobInput:
    project_id: str
    report_export_id: str | None
    artifact_type: str
    template: str = "standard"
    filters: dict[str, Any] = field(default_factory=dict)
    sort: str = "collected_at_desc"
    requested_by: str = "runtime-console"
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeReportExportJobStatusInput:
    job_id: str
    status: str
    updated_by: str
    report_export_id: str | None = None
    artifact_url: str | None = None
    error_message: str | None = None
    next_attempt_at: datetime | None = None
    lease_expires_at: datetime | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeReportExportJobQueueStats:
    total_count: int
    status_counts: dict[str, int]
    retryable_count: int
    expired_running_count: int
    max_attempts_reached_count: int
    oldest_queued_at: datetime | None
    generated_at: datetime


@dataclass(frozen=True)
class RuntimeNotification:
    notification: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeNotificationPage:
    total_count: int
    unread_count: int
    limit: int
    offset: int
    records: tuple[RuntimeNotification, ...]


@dataclass(frozen=True)
class RuntimeNotificationStatusInput:
    notification_id: str
    status: str
    updated_by: str = "runtime-console"
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeNotificationSubscription:
    subscription: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeNotificationSubscriptionPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeNotificationSubscription, ...]


@dataclass(frozen=True)
class RuntimeNotificationSubscriptionInput:
    project_id: str
    endpoint_url: str
    channel: str = "webhook"
    event_types: tuple[str, ...] = ("report_export_job",)
    severity_threshold: str = "info"
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_by: str = "runtime-console"
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeNotificationDelivery:
    delivery: dict[str, Any]
    notification: dict[str, Any] | None
    subscription: dict[str, Any] | None
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeNotificationDeliveryPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeNotificationDelivery, ...]


@dataclass(frozen=True)
class RuntimeNotificationDeliveryStatusInput:
    delivery_id: str
    status: str
    updated_by: str = "notification-worker"
    response_status: int | None = None
    response_body_hash: str | None = None
    error_message: str | None = None
    next_attempt_at: datetime | None = None
    lease_expires_at: datetime | None = None
    reason: str | None = None


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
class RuntimeAlertItem:
    alert: dict[str, Any]
    evidence_refs: tuple[dict[str, Any], ...]
    related_actions: tuple[dict[str, Any], ...]
    audit_events: tuple[dict[str, Any], ...]
    management_events: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class RuntimeAlertPage:
    total_count: int
    limit: int
    offset: int
    records: tuple[RuntimeAlertItem, ...]


@dataclass(frozen=True)
class RuntimeAlertEvent:
    alert_event: dict[str, Any]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeAlertEventInput:
    project_id: str
    alert_id: str
    alert_type: str
    source: str
    source_id: str
    status: str
    updated_by: str = "runtime-console"
    note: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeAlertNotificationResult:
    project_id: str
    notification_count: int
    delivery_count: int
    skipped_count: int
    notifications: tuple[dict[str, Any], ...]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeEntityAliasAssignmentNotificationResult:
    project_id: str
    notification_count: int
    delivery_count: int
    skipped_count: int
    notifications: tuple[dict[str, Any], ...]
    audit_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeContentDraft:
    draft: dict[str, Any]
    target_questions: tuple[dict[str, Any], ...]
    knowledge_facts: tuple[dict[str, Any], ...]
    answer_runs: tuple[dict[str, Any], ...]
    action_recommendation: dict[str, Any] | None
    manual_distribution_records: tuple[dict[str, Any], ...]
    audit_events: tuple[dict[str, Any], ...]


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
