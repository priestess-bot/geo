import { revalidatePath } from "next/cache";
import type { ReactNode } from "react";

type PageResponse<T> = {
  total_count: number;
  sort?: string;
  records: T[];
};

type RuntimeProject = {
  project: {
    id: string;
    name: string;
    market_code: string;
    industry_code: string;
    target_brand: string;
    category: string;
    prompt_version: string;
    status: string;
  };
  tenant: { id: string; name: string };
  brand: { id?: string; canonical_name: string; official_domains?: string[]; status?: string } | null;
  competitors: Array<{ id?: string; canonical_name: string; official_domains?: string[]; status?: string }>;
  prompt_count: number;
  audit_events: Array<{ event_type: string; method_version?: string | null }>;
};

type RuntimeProjectMember = {
  member: {
    id: string;
    project_id: string;
    user_id: string;
    role: string;
    created_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; method_version?: string | null; after_hash?: string | null }>;
};

type RuntimePrompt = {
  id: string;
  market_code: string;
  industry_code: string;
  text: string;
  intent_type: string;
  city: string;
  language: string;
  target_brand: string;
  competitors: string[];
  priority: number;
  intent_weight: number;
  prompt_version: string;
  status: string;
};

type RuntimePromptImportHistoryItem = {
  prompt_import: {
    id?: string;
    project_id?: string;
    actor_id?: string;
    source_format?: string;
    source_filename?: string | null;
    source_content_type?: string | null;
    csv_sha256?: string | null;
    prompt_count?: number;
    prompt_question_ids?: string[];
    method_version?: string | null;
    after_hash?: string | null;
    created_at?: string | null;
  };
  audit_events: Array<{ event_type?: string; method_version?: string | null; after_hash?: string | null; created_at?: string | null }>;
};

type EvidenceRun = {
  answer_run: {
    id: string;
    project_id?: string;
    prompt_question_id?: string;
    platform: string;
    surface: string;
    access_method?: string;
    market_code?: string;
    city: string;
    language?: string;
    device?: string;
    status: string;
    answer_present?: boolean;
    surface_triggered?: boolean;
    sample_index?: number;
    sample_size?: number;
    model_or_surface?: string;
    account_state?: string | null;
    collector_backend_id?: string;
    collector_version?: string;
    prompt_text?: string;
    prompt_intent_type?: string;
    prompt_priority?: number;
    prompt_version?: string;
    collected_at: string;
  };
  raw_answer?: {
    answer_text?: string;
    raw_payload_hash?: string;
  } | null;
  citations: Array<{ domain?: string; url?: string; source_type?: string; position?: number }>;
  evidence_assets: Array<{ asset_type?: string; url?: string; content_hash?: string | null }>;
  collector_logs: Array<{ event_type?: string; collector_backend_id?: string; payload?: Record<string, unknown> }>;
  collection_cost?: {
    total_cost?: number;
    llm_provider?: string;
    llm_tokens?: number;
    duration_ms?: number;
  } | null;
  audit_events: Array<{ event_type?: string; method_version?: string | null; target_type?: string }>;
};

type CollectionRun = {
  collection_run: {
    id: string;
    project_id?: string;
    run_type?: string;
    mode?: string;
    planned_runs?: number;
    attempted_runs?: number;
    success_count?: number;
    failure_count?: number;
    success_rate?: number;
    trigger_rate?: number;
    answer_present_rate?: number;
    total_cost?: number;
    average_cost_per_run?: number;
    total_duration_ms?: number;
    average_duration_ms?: number;
    collector_backend_ids?: string[];
    platform_distribution?: Record<string, number>;
    city_distribution?: Record<string, number>;
    access_method_distribution?: Record<string, number>;
    failure_summary?: Record<string, number>;
    answer_run_ids?: string[];
    started_at?: string;
    completed_at?: string;
    created_at?: string;
  };
  audit_events: Array<{ event_type?: string; method_version?: string | null; target_type?: string }>;
};

type ScoreSnapshot = {
  snapshot: {
    id?: string;
    final_score: number;
    trigger_rate: number;
    mention_rate: number;
    recommendation_rate: number;
    dispersion?: number;
    scope_type?: string;
    scope_value?: string;
    formula_version: string;
    component_weights_snapshot?: Record<string, number>;
  };
  contributions: Array<{
    id?: string;
    component_name: string;
    component_score: number;
    weight?: number;
    weighted_contribution: number;
    denominator?: string;
    evidence_answer_run_ids?: string[];
    positive_evidence_summary?: string;
    negative_evidence_summary?: string;
    confidence_note?: string;
  }>;
  answer_runs: Array<{
    answer_run: {
      id: string;
      platform?: string;
      city?: string;
      prompt_text?: string;
      prompt_intent_type?: string;
    };
    analysis?: {
      confidence?: number;
      parser_engine_id?: string;
      analysis_version?: string;
      payload?: {
        parser_comparison?: {
          secondary_parser_engine_id?: string;
          secondary_analysis_version?: string;
          secondary_prompt_version?: string;
          comparison_method_version?: string;
          agreement_rate?: number;
          mismatched_fields?: Record<string, unknown>;
          secondary_result?: {
            llm_call_log?: {
              provider?: string;
              model?: string;
              prompt_version?: string;
              total_tokens?: number;
              estimated_cost?: number;
              latency_ms?: number;
              status?: string;
              request_hash?: string;
            };
          };
        };
      } & Record<string, unknown>;
    } | null;
  }>;
  audit_events: Array<{ event_type?: string; method_version?: string | null }>;
};

type CitationGraph = {
  project_id: string;
  nodes: Array<{
    node: {
      id: string;
      source_url?: string;
      source_domain?: string;
      source_type?: string;
      topic?: string | null;
      source_gap_type?: string | null;
      answer_run_ids?: string[];
      citation_count?: number;
    };
    answer_runs: Array<{
      id: string;
      platform?: string;
      city?: string;
      prompt_text?: string;
      prompt_intent_type?: string;
    }>;
  }>;
  evidence_links: Array<{
    source_graph_id?: string;
    answer_run_id?: string;
    answer_citation_id?: string | null;
    relation_type?: string;
  }>;
  source_gaps: Array<{
    source_type: string;
    gap_type: string;
    observed_count?: number;
    expected_weight?: number;
    recommendation: string;
  }>;
  competitor_benchmarks: Array<{
    competitor_name: string;
    metric_scope?: string;
    payload?: {
      mention_count?: number;
      mention_rate?: number;
      recommendation_count?: number;
      citation_overlap_count?: number;
      local_relevance_average?: number;
    };
    answer_run_ids?: string[];
  }>;
};

type ReportExport = {
  report_export: {
    id: string;
    market_code?: string;
    report_version: string;
    report_type?: string;
    sample_size: number;
    prompt_version?: string;
    scoring_formula_version?: string;
    platform_weights_snapshot?: Record<string, number>;
    method_disclosure?: {
      google_coverage?: string;
      google_spike_gate?: {
        gate_status?: string;
        limited_coverage?: boolean;
      };
      api_browser_fidelity?: {
        status?: string;
        official_api_records?: number;
        browser_records?: number;
        comparable_prompt_city_pairs?: number;
        mismatch_count?: number;
        difference_rate?: number | null;
      };
      score_rate_denominators?: {
        definitions?: Record<
          string,
          {
            label?: string;
            numerator?: string;
            denominator?: string;
            formula?: string;
            note?: string;
          }
        >;
        evidence_denominators?: {
          attempted_records?: number;
          surface_triggered_records?: number;
        };
        evidence_trigger_rate?: number;
      };
      access_method_distribution?: Record<string, number>;
      platform_distribution?: Record<string, number>;
      evidence_asset_coverage?: {
        screenshot_records?: number;
        html_snapshot_records?: number;
      };
    };
    window_start?: string;
    window_end?: string;
    methodology_hash?: string;
    exported_at: string;
    markdown_url?: string | null;
    pdf_url?: string | null;
    csv_url?: string | null;
  };
  score_snapshots: Array<{
    final_score?: number;
    trigger_rate?: number;
    mention_rate?: number;
    recommendation_rate?: number;
    dispersion?: number;
    formula_version?: string;
  }>;
  answer_runs: Array<{
    id: string;
    prompt_text?: string;
    prompt_intent_type?: string;
    prompt_version?: string;
    platform?: string;
    surface?: string;
    access_method?: string;
    market_code?: string;
    city?: string;
    language?: string;
    device?: string;
    sample_index?: number;
    sample_size?: number;
    answer_present?: boolean;
    surface_triggered?: boolean;
    status?: string;
  }>;
  citation_graph?: CitationGraph | null;
  audit_events: Array<{ event_type?: string; target_type?: string; method_version?: string | null }>;
};

type ActionPlan = {
  retest_schedule: {
    id?: string;
    project_id?: string;
    prompt_version: string;
    sample_size?: number;
    offsets_days: number[];
    scheduled_dates?: string[];
    answer_run_ids?: string[];
    created_at?: string;
  };
  action_recommendations: Array<{
    id?: string;
    title: string;
    description?: string;
    priority: string;
    status: string;
    owner_id?: string;
    source_gap_type?: string | null;
    evidence_answer_run_ids?: string[];
    related_source_types?: string[];
    next_check_date?: string;
    created_at?: string;
  }>;
  retest_comparisons: Array<{
    id?: string;
    baseline_score?: number;
    retest_score?: number;
    score_delta: number;
    baseline_answer_run_ids?: string[];
    retest_answer_run_ids?: string[];
    trend: string;
    created_at?: string;
  }>;
  answer_runs: Array<{
    id: string;
    platform?: string;
    surface?: string;
    city?: string;
    access_method?: string;
    prompt_text?: string;
    prompt_intent_type?: string;
    prompt_version?: string;
    sample_index?: number;
    sample_size?: number;
    answer_present?: boolean;
    surface_triggered?: boolean;
  }>;
  audit_events: Array<{ event_type?: string; target_type?: string; method_version?: string | null }>;
};

type RuntimeAlert = {
  alert: {
    id: string;
    project_id: string;
    alert_type: string;
    severity: string;
    title: string;
    summary?: string;
    metric_name?: string;
    metric_value?: number;
    threshold?: number;
    rule_version?: string;
    source?: string;
    source_id?: string;
    created_at?: string;
  };
  evidence_refs: Array<{ target_type?: string; target_id?: string }>;
  related_actions: Array<{
    id?: string;
    title?: string;
    priority?: string;
    status?: string;
    source_gap_type?: string | null;
  }>;
  audit_events: Array<{ event_type?: string; method_version?: string | null; after_hash?: string | null }>;
};

type ContentEngine = {
  project_id?: string;
  knowledge_facts: Array<{
    id: string;
    market_code?: string;
    fact_type?: string;
    subject?: string;
    predicate?: string;
    object_value?: string;
    city?: string | null;
    evidence_source_id?: string | null;
    confidence?: number;
    status?: string;
  }>;
  content_drafts: Array<{
    draft: {
      id?: string;
      title: string;
      content_type?: string;
      content_template_id?: string;
      target_city: string;
      target_platform?: string;
      target_source_type?: string;
      source_gap_types?: string[];
      evidence_answer_run_ids?: string[];
      draft_markdown?: string;
      review_status: string;
      created_by?: string;
      created_at?: string;
    };
    target_questions: Array<{ text: string; intent_type?: string; city?: string }>;
    knowledge_facts: Array<{
      id: string;
      market_code?: string;
      fact_type?: string;
      object_value?: string;
      confidence?: number;
    }>;
    answer_runs: Array<{
      id: string;
      platform?: string;
      city?: string;
      prompt_text?: string;
      prompt_intent_type?: string;
    }>;
    action_recommendation?: {
      title?: string;
      priority?: string;
      status?: string;
      source_gap_type?: string | null;
    } | null;
    manual_distribution_records: Array<{
      platform?: string;
      target_url?: string;
      status?: string;
      submitted_at?: string | null;
      checked_at?: string | null;
      notes?: string;
    }>;
    audit_events: Array<{ event_type?: string; actor_id?: string; method_version?: string | null; created_at?: string | null }>;
  }>;
  integration_connectors: Array<{
    provider: string;
    connection_status: string;
    capabilities?: string[];
    auth_mode?: string;
  }>;
  manual_distribution_records: Array<{ platform?: string; status?: string; target_url?: string; notes?: string }>;
  audit_events: Array<{ event_type?: string; target_type?: string; method_version?: string | null }>;
};

type TraceabilityDetail = {
  traceability_bundle: {
    explanation_summary: string;
    report_export_ids: string[];
    score_snapshot_ids: string[];
    score_contribution_ids: string[];
    answer_run_ids: string[];
    raw_answer_ids: string[];
    answer_citation_ids: string[];
    evidence_asset_ids: string[];
    source_graph_ids: string[];
    source_gap_types: string[];
    action_recommendation_ids: string[];
    content_draft_ids: string[];
    audit_event_ids: string[];
  };
  report_exports: Array<{ id?: string; report_version: string }>;
  score_snapshots: ScoreSnapshot[];
  evidence_runs: EvidenceRun[];
  action_recommendations: Array<{
    id?: string;
    title: string;
    priority: string;
    status: string;
    source_gap_type?: string | null;
  }>;
  content_drafts: Array<{
    draft: { id?: string; title: string; review_status: string; target_city?: string; target_platform?: string };
    target_questions?: Array<{ text: string }>;
    answer_runs?: Array<{ prompt_text?: string; platform?: string; city?: string }>;
  }>;
  audit_events: Array<{ event_type: string; target_type: string; method_version?: string | null }>;
  evidence_links: Array<{
    source_type: string;
    target_type: string;
    relation_type: string;
    answer_run_ids: string[];
  }>;
};

type RuntimeData = {
  projects: PageResponse<RuntimeProject>;
  projectMembers: PageResponse<RuntimeProjectMember>;
  brandKit: RuntimeProjectBrandKit | null;
  scoreWeights: RuntimeScoreWeightConfig | null;
  scoreFormulas: RuntimeScoreFormulaCatalog;
  humanReviews: PageResponse<RuntimeHumanReview>;
  humanReviewQueue: PageResponse<RuntimeHumanReviewQueueItem>;
  knowledgeSearch: RuntimeKnowledgeSearch | null;
  prompts: PageResponse<RuntimePrompt>;
  promptImports: PageResponse<RuntimePromptImportHistoryItem>;
  evidence: PageResponse<EvidenceRun>;
  questionEvidence: PageResponse<EvidenceRun>;
  collectionRuns: PageResponse<CollectionRun>;
  fidelityChecks: PageResponse<RuntimeFidelityCheck>;
  fidelityTrend: RuntimeFidelityTrend | null;
  entityAliases: PageResponse<RuntimeEntityAlias>;
  entityAliasCandidates: PageResponse<RuntimeEntityAliasCandidate>;
  savedViews: PageResponse<RuntimeSavedView>;
  scores: PageResponse<ScoreSnapshot>;
  graphs: PageResponse<CitationGraph>;
  reports: PageResponse<ReportExport>;
  actions: PageResponse<ActionPlan>;
  alerts: PageResponse<RuntimeAlert>;
  content: PageResponse<ContentEngine>;
  traceability: TraceabilityDetail | null;
};

type RuntimePaths = Record<keyof typeof endpoints, string> & {
  questionEvidence: string;
};

type RuntimeProjectBrandKit = {
  brand_kit: {
    id: string;
    project_id: string;
    client_name: string;
    prepared_by: string;
    logo_url?: string | null;
    primary_color?: string | null;
    secondary_color?: string | null;
    footer_text?: string | null;
    updated_by: string;
    created_at?: string;
    updated_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type RuntimeScoreWeightConfig = {
  score_weight_config: {
    id?: string | null;
    project_id: string;
    formula_version: string;
    weights: Record<string, number>;
    updated_by: string;
    notes?: string | null;
    created_at?: string;
    updated_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type RuntimeScoreFormulaCatalog = {
  formulas: Array<{
    formula_version: string;
    weights: Record<string, number>;
    description: string;
    status: string;
    supersedes?: string | null;
  }>;
};

type RuntimeHumanReview = {
  human_review: {
    id: string;
    project_id: string;
    target_type: string;
    target_id: string;
    review_status: string;
    decision: string;
    reviewer_id: string;
    notes?: string | null;
    payload?: Record<string, unknown>;
    created_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type RuntimeHumanReviewQueueItem = {
  project_id: string;
  target_type: string;
  target_id: string;
  title: string;
  queue_status: string;
  priority: number;
  reason: string;
  created_at?: string | null;
  latest_review?: {
    id?: string;
    review_status?: string;
    decision?: string;
    reviewer_id?: string;
    notes?: string | null;
    created_at?: string | null;
  } | null;
  evidence_refs: Record<string, unknown>;
};

type RuntimeKnowledgeSearch = {
  total_count: number;
  limit: number;
  offset: number;
  query: string;
  market_code: string;
  city?: string | null;
  embedding_model: string;
  records: Array<{
    fact: {
      id: string;
      market_code?: string;
      fact_type?: string;
      subject?: string;
      predicate?: string;
      object_value?: string;
      city?: string | null;
      evidence_source_id?: string | null;
      confidence?: number;
      status?: string;
    };
    score: number;
    fallback_used: boolean;
    embedding_model: string;
  }>;
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type RuntimeFidelityCheck = {
  fidelity_check: {
    id: string;
    project_id: string;
    report_export_id?: string | null;
    status: string;
    official_api_records: number;
    browser_records: number;
    comparable_prompt_city_pairs: number;
    mismatch_count: number;
    difference_rate?: number | null;
    payload?: {
      summary?: string;
      status?: string;
      official_api_records?: number;
      browser_records?: number;
      comparable_prompt_city_pairs?: number;
      mismatch_count?: number;
      difference_rate?: number | null;
    } & Record<string, unknown>;
    payload_hash?: string;
    answer_run_ids?: string[];
    checked_by: string;
    checked_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type RuntimeFidelityTrend = {
  project_id?: string | null;
  report_export_id?: string | null;
  total_count: number;
  sampled_count: number;
  limit: number;
  latest_status?: string | null;
  latest_checked_at?: string | null;
  earliest_checked_at?: string | null;
  latest_difference_rate?: number | null;
  earliest_difference_rate?: number | null;
  average_difference_rate?: number | null;
  max_difference_rate?: number | null;
  trend_direction: string;
  points: Array<{
    id: string;
    project_id: string;
    report_export_id?: string | null;
    status: string;
    official_api_records: number;
    browser_records: number;
    comparable_prompt_city_pairs: number;
    mismatch_count: number;
    difference_rate?: number | null;
    payload_hash?: string | null;
    checked_at?: string | null;
  }>;
};

type RuntimeEntityAlias = {
  entity_alias: {
    id: string;
    entity_id: string;
    entity_kind: string;
    alias: string;
    alias_type: string;
    confidence?: number;
    confirmed_by?: string | null;
    created_at?: string;
  };
  entity: {
    id: string;
    project_id: string;
    entity_kind: string;
    canonical_name: string;
    official_domains?: string[];
    status?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type RuntimeEntityAliasCandidate = {
  candidate: {
    id: string;
    entity_id: string;
    entity_kind: string;
    alias: string;
    alias_type: string;
    source: string;
    confidence?: number;
    reason?: string;
  };
  entity: {
    id: string;
    project_id: string;
    entity_kind: string;
    canonical_name: string;
    status?: string;
  };
  confirmed_aliases: string[];
};

type RuntimeFilters = {
  project_id?: string;
  platform?: string;
  city?: string;
  intent_type?: string;
  sort?: string;
};

type RuntimeSavedView = {
  saved_view: {
    id: string;
    project_id: string;
    name: string;
    view_type: string;
    filters: Record<string, unknown>;
    sort: string;
    query_path: string;
    export_path: string;
    created_by: string;
    created_at: string;
    updated_at: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type QuestionCoverageStatus = "covered" | "no_evidence" | "platform_gap" | "trigger_gap" | "answer_gap" | "source_gap";

type QuestionDetailRow = {
  prompt: RuntimePrompt;
  evidenceRuns: EvidenceRun[];
  runCount: number;
  answerCount: number;
  triggeredCount: number;
  citationCount: number;
  assetCount: number;
  auditCount: number;
  totalCost: number;
  averageDurationMs: number;
  platforms: string[];
  requiredPlatforms: string[];
  missingPlatforms: string[];
  cities: string[];
  accessMethods: string[];
  surfaceCounts: Record<string, number>;
  statusCounts: Record<string, number>;
  latestRun?: EvidenceRun;
  status: QuestionCoverageStatus;
  gapLabel: string;
};

const endpoints = {
  projects: "/v1/projects/runtime",
  projectMembers: "/v1/project-members/runtime",
  prompts: "/v1/prompts/runtime",
  promptImports: "/v1/prompts/runtime/imports",
  evidence: "/v1/evidence-runs/runtime",
  collectionRuns: "/v1/collection-runs/runtime",
  fidelityChecks: "/v1/fidelity-checks/runtime",
  fidelityTrend: "/v1/fidelity-checks/runtime/trend",
  evidenceExport: "/v1/evidence-runs/runtime/export.csv",
  entityAliases: "/v1/entity-aliases/runtime",
  entityAliasCandidates: "/v1/entity-aliases/runtime/candidates",
  savedViews: "/v1/runtime-saved-views",
  brandKit: "/v1/project-brand-kits/runtime",
  scoreWeights: "/v1/score-weight-configs/runtime",
  scoreFormulas: "/v1/score-formulas/runtime",
  humanReviews: "/v1/human-reviews/runtime",
  humanReviewQueue: "/v1/human-reviews/runtime/queue",
  knowledgeSearch: "/v1/knowledge-facts/runtime/search",
  scores: "/v1/visibility-scores/runtime",
  graphs: "/v1/citation-graphs/runtime",
  reports: "/v1/reports/runtime",
  actions: "/v1/action-plans/runtime",
  alerts: "/v1/runtime-alerts",
  content: "/v1/content-engines/runtime",
  traceability: "/v1/traceability/runtime"
} as const;

const brandLogoEndpoint = "/v1/project-brand-kits/runtime/logo";

const emptyPage = <T,>(): PageResponse<T> => ({ total_count: 0, records: [] });

const scoreComponentNames = [
  "MentionScore",
  "RecommendationScore",
  "PositionScore",
  "CitationScore",
  "LocalRelevanceScore",
  "SentimentScore",
  "FreshnessScore",
  "CompetitorShareScore"
] as const;

const defaultScoreWeights: Record<string, number> = {
  MentionScore: 0.18,
  RecommendationScore: 0.22,
  PositionScore: 0.12,
  CitationScore: 0.16,
  LocalRelevanceScore: 0.14,
  SentimentScore: 0.08,
  FreshnessScore: 0.05,
  CompetitorShareScore: 0.05
};

export const dynamic = "force-dynamic";

async function createAuRuntimeProject(formData?: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const itemList = (field: string): string[] =>
    String(formData?.get(field) || "")
      .split(/\r?\n|,/)
      .map((item) => item.trim())
      .filter(Boolean);
  const payload = formData
    ? {
        tenant_name: String(formData.get("tenant_name") || "Design Partner AU").trim(),
        project_name: String(formData.get("project_name") || "AU DTC Evidence Pilot").trim(),
        target_brand: String(formData.get("target_brand") || "ExampleBrand").trim(),
        category: String(formData.get("category") || "DTC ecommerce products").trim(),
        competitors: itemList("competitors"),
        brand_official_domains: itemList("brand_official_domains"),
        brand_parent_company: String(formData.get("brand_parent_company") || "").trim() || undefined,
        brand_product_lines: itemList("brand_product_lines"),
        owner_user_id: String(formData.get("owner_user_id") || "runtime-console").trim()
      }
    : undefined;
  const response = await fetch(`${baseUrl}/v1/projects/runtime/au/dtc-ecommerce`, {
    method: "POST",
    headers: payload ? { "content-type": "application/json" } : undefined,
    body: payload ? JSON.stringify(payload) : undefined,
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/projects/runtime/au/dtc-ecommerce returned ${response.status}`);
  }
  revalidatePath("/");
}

async function saveCurrentRuntimeView(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const name = String(formData.get("name") || "").trim() || "Runtime evidence view";
  if (!projectId) {
    throw new Error("project_id is required to save a runtime view");
  }
  const payload = {
    project_id: projectId,
    name,
    view_type: "runtime_evidence",
    filters: {
      platform: String(formData.get("platform") || "").trim() || undefined,
      city: String(formData.get("city") || "").trim() || undefined,
      intent_type: String(formData.get("intent_type") || "").trim() || undefined
    },
    sort: String(formData.get("sort") || "collected_at_desc").trim(),
    query_path: String(formData.get("query_path") || "").trim(),
    export_path: String(formData.get("export_path") || "").trim(),
    created_by: "runtime-console"
  };
  const response = await fetch(`${baseUrl}/v1/runtime-saved-views`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/runtime-saved-views returned ${response.status}`);
  }
  revalidatePath("/");
}

async function saveProjectBrandKit(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const clientName = String(formData.get("client_name") || "").trim();
  if (!projectId || !clientName) {
    throw new Error("project_id and client_name are required to save a project brand kit");
  }
  const optionalText = (field: string): string | undefined =>
    String(formData.get(field) || "").trim() || undefined;
  const payload = {
    project_id: projectId,
    client_name: clientName,
    prepared_by: String(formData.get("prepared_by") || "GENO SaaS AU").trim(),
    logo_url: optionalText("logo_url"),
    primary_color: optionalText("primary_color"),
    secondary_color: optionalText("secondary_color"),
    footer_text: optionalText("footer_text"),
    updated_by: "runtime-console"
  };
  const response = await fetch(`${baseUrl}/v1/project-brand-kits/runtime`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/project-brand-kits/runtime returned ${response.status}`);
  }
  revalidatePath("/");
}

async function saveRuntimeProjectMember(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const userId = String(formData.get("user_id") || "").trim();
  if (!projectId || !userId) {
    throw new Error("project_id and user_id are required to save a project member");
  }
  const payload = {
    project_id: projectId,
    user_id: userId,
    role: String(formData.get("role") || "viewer").trim(),
    updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/project-members/runtime`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/project-members/runtime returned ${response.status}`);
  }
  revalidatePath("/");
}

async function deleteRuntimeProjectMember(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const userId = String(formData.get("user_id") || "").trim();
  if (!projectId || !userId) {
    throw new Error("project_id and user_id are required to delete a project member");
  }
  const payload = {
    project_id: projectId,
    user_id: userId,
    deleted_by: String(formData.get("deleted_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/project-members/runtime`, {
    method: "DELETE",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/project-members/runtime DELETE returned ${response.status}`);
  }
  revalidatePath("/");
}

async function uploadProjectBrandLogo(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const uploadedBy = String(formData.get("uploaded_by") || "runtime-console").trim();
  const file = formData.get("brand_logo");
  if (!projectId || !(file instanceof File) || file.size === 0) {
    throw new Error("project_id and brand_logo file are required to upload a project logo");
  }
  const params = new URLSearchParams({
    project_id: projectId,
    filename: file.name || "logo.bin",
    uploaded_by: uploadedBy || "runtime-console"
  });
  const response = await fetch(`${baseUrl}${brandLogoEndpoint}?${params.toString()}`, {
    method: "POST",
    headers: { "content-type": file.type || "application/octet-stream" },
    body: Buffer.from(await file.arrayBuffer()),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`${brandLogoEndpoint} returned ${response.status}`);
  }
  revalidatePath("/");
}

async function saveScoreWeightConfig(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  if (!projectId) {
    throw new Error("project_id is required to save score weights");
  }
  const weights = Object.fromEntries(
    scoreComponentNames.map((component) => [component, Number(formData.get(component) || 0)])
  );
  const payload = {
    project_id: projectId,
    formula_version: String(formData.get("formula_version") || "au_visibility_v1").trim(),
    weights,
    updated_by: "runtime-console",
    notes: String(formData.get("notes") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/score-weight-configs/runtime`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/score-weight-configs/runtime returned ${response.status}`);
  }
  revalidatePath("/");
}

async function submitHumanReview(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const targetType = String(formData.get("target_type") || "").trim();
  const targetId = String(formData.get("target_id") || "").trim();
  const decision = String(formData.get("decision") || "").trim();
  if (!projectId || !targetType || !targetId || !decision) {
    throw new Error("project_id, target_type, target_id and decision are required for human review");
  }
  const payload = {
    project_id: projectId,
    target_type: targetType,
    target_id: targetId,
    review_status: String(formData.get("review_status") || "approved").trim(),
    decision,
    reviewer_id: String(formData.get("reviewer_id") || "runtime-console").trim(),
    notes: String(formData.get("notes") || "").trim() || undefined,
    payload: {
      source: "runtime-console",
      target_label: String(formData.get("target_label") || "").trim() || undefined
    }
  };
  const response = await fetch(`${baseUrl}/v1/human-reviews/runtime`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/human-reviews/runtime returned ${response.status}`);
  }
  revalidatePath("/");
}

async function submitManualBackfill(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const promptQuestionId = String(formData.get("prompt_question_id") || "").trim();
  const answerText = String(formData.get("answer_text") || "").trim();
  if (!promptQuestionId || !answerText) {
    throw new Error("prompt_question_id and answer_text are required for manual backfill");
  }
  const citationUrls = String(formData.get("citation_urls") || "")
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
  const payload = {
    prompt_question_id: promptQuestionId,
    platform: String(formData.get("platform") || "google").trim(),
    surface: String(formData.get("surface") || "google_ai_mode").trim(),
    answer_text: answerText,
    citation_urls: citationUrls,
    screenshot_url: String(formData.get("screenshot_url") || "").trim() || undefined,
    html_snapshot_url: String(formData.get("html_snapshot_url") || "").trim() || undefined,
    submitted_by: String(formData.get("submitted_by") || "runtime-console").trim(),
    notes: String(formData.get("notes") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/evidence-runs/runtime/manual-backfill`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/evidence-runs/runtime/manual-backfill returned ${response.status}`);
  }
  revalidatePath("/");
}

async function importRuntimePromptsCsv(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const csvContent = String(formData.get("csv_content") || "").trim();
  if (!projectId || !csvContent) {
    throw new Error("project_id and csv_content are required to import prompts");
  }
  const response = await fetch(`${baseUrl}/v1/prompts/runtime/import.csv`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      csv_content: csvContent,
      imported_by: "runtime-console",
      max_rows: 100
    }),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/prompts/runtime/import.csv returned ${response.status}`);
  }
  revalidatePath("/");
}

async function importRuntimePromptsFile(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const promptFile = formData.get("prompt_file");
  if (!projectId || !(promptFile instanceof File) || !promptFile.name) {
    throw new Error("project_id and prompt_file are required to import prompt files");
  }
  const params = new URLSearchParams({
    project_id: projectId,
    filename: promptFile.name,
    imported_by: "runtime-console",
    max_rows: "100"
  });
  const response = await fetch(`${baseUrl}/v1/prompts/runtime/import.file?${params.toString()}`, {
    method: "POST",
    headers: { "content-type": promptFile.type || "application/octet-stream" },
    body: Buffer.from(await promptFile.arrayBuffer()),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/prompts/runtime/import.file returned ${response.status}`);
  }
  revalidatePath("/");
}

async function confirmEntityAlias(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const entityRef = String(formData.get("entity_ref") || "").trim();
  const alias = String(formData.get("alias") || "").trim();
  const [entityKind, entityId] = entityRef.split(":");
  if (!entityKind || !entityId || !alias) {
    throw new Error("entity_ref and alias are required for entity alias confirmation");
  }
  const payload = {
    entity_id: entityId,
    entity_kind: entityKind,
    alias,
    alias_type: String(formData.get("alias_type") || "alias").trim(),
    confidence: Number(String(formData.get("confidence") || "1")),
    confirmed_by: String(formData.get("confirmed_by") || "runtime-console").trim(),
    notes: String(formData.get("notes") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/entity-aliases/runtime/confirm`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/entity-aliases/runtime/confirm returned ${response.status}`);
  }
  revalidatePath("/");
}

async function fetchRuntimeEndpoint<T>(
  baseUrl: string,
  path: string,
  fallback: T,
  options: { optionalNotFound?: boolean } = {}
): Promise<{ payload: T; error: string | null }> {
  try {
    const response = await fetch(`${baseUrl}${path}`, { cache: "no-store" });
    if (response.status === 404 && options.optionalNotFound) {
      return { payload: fallback, error: null };
    }
    if (!response.ok) {
      return { payload: fallback, error: `${path} returned ${response.status}` };
    }
    return { payload: (await response.json()) as T, error: null };
  } catch (error) {
    return {
      payload: fallback,
      error: error instanceof Error ? `${path} failed: ${error.message}` : `${path} failed`
    };
  }
}

function cleanFilter(value: string | string[] | undefined): string | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  const trimmed = raw?.trim();
  return trimmed || undefined;
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      query.set(key, String(value));
    }
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}

function runtimePath(path: string, params: Record<string, string | number | undefined>): string {
  return `${path}${buildQuery(params)}`;
}

function reportArtifactPath(
  reportArtifactBase: string | null,
  artifactType: "markdown" | "csv" | "pdf",
  filters: RuntimeFilters,
  extras: Record<string, string | number | undefined> = {}
): string | null {
  if (!reportArtifactBase) return null;
  return runtimePath(reportArtifactBase, {
    type: artifactType,
    platform: filters.platform,
    city: filters.city,
    intent_type: filters.intent_type,
    sort: filters.sort,
    ...extras
  });
}

async function fetchRuntimeData(filters: RuntimeFilters = {}): Promise<{
  data: RuntimeData;
  error: string | null;
  fetchUrl: string;
  displayUrl: string;
  paths: RuntimePaths;
}> {
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const displayUrl = process.env.NEXT_PUBLIC_API_BASE_URL || baseUrl;
  const projectListParams = { market_code: "AU", limit: 20 };
  const paths: RuntimePaths = {
    projects: runtimePath(endpoints.projects, projectListParams),
    projectMembers: endpoints.projectMembers,
    prompts: runtimePath(endpoints.prompts, {
      market_code: "AU",
      intent_type: filters.intent_type,
      limit: 200
    }),
    promptImports: runtimePath(endpoints.promptImports, {
      limit: 5
    }),
    evidence: runtimePath(endpoints.evidence, {
      platform: filters.platform,
      city: filters.city,
      intent_type: filters.intent_type,
      sort: filters.sort,
      limit: 5
    }),
    questionEvidence: runtimePath(endpoints.evidence, {
      platform: filters.platform,
      city: filters.city,
      intent_type: filters.intent_type,
      sort: filters.sort,
      limit: 200
    }),
    collectionRuns: runtimePath(endpoints.collectionRuns, {
      limit: 5
    }),
    evidenceExport: runtimePath(endpoints.evidenceExport, {
      platform: filters.platform,
      city: filters.city,
      intent_type: filters.intent_type,
      sort: filters.sort,
      limit: 200
    }),
    entityAliases: runtimePath(endpoints.entityAliases, {
      limit: 5
    }),
    entityAliasCandidates: runtimePath(endpoints.entityAliasCandidates, {
      limit: 5
    }),
    fidelityChecks: runtimePath(endpoints.fidelityChecks, {
      limit: 5
    }),
    fidelityTrend: runtimePath(endpoints.fidelityTrend, {
      limit: 20
    }),
    savedViews: runtimePath(endpoints.savedViews, {
      view_type: "runtime_evidence",
      limit: 5
    }),
    brandKit: endpoints.brandKit,
    scoreWeights: endpoints.scoreWeights,
    scoreFormulas: endpoints.scoreFormulas,
    humanReviews: runtimePath(endpoints.humanReviews, {
      limit: 5
    }),
    humanReviewQueue: runtimePath(endpoints.humanReviewQueue, {
      limit: 5
    }),
    knowledgeSearch: endpoints.knowledgeSearch,
    scores: runtimePath(endpoints.scores, { limit: 1 }),
    graphs: runtimePath(endpoints.graphs, { limit: 1 }),
    reports: runtimePath(endpoints.reports, { limit: 5 }),
    actions: runtimePath(endpoints.actions, { limit: 1 }),
    alerts: runtimePath(endpoints.alerts, { limit: 10 }),
    content: runtimePath(endpoints.content, { limit: 1 }),
    traceability: endpoints.traceability
  };
  const projects = await fetchRuntimeEndpoint<PageResponse<RuntimeProject>>(
    baseUrl,
    paths.projects,
    emptyPage<RuntimeProject>()
  );
  let projectRecords = projects.payload.records;
  if (filters.project_id && !projectRecords.some((record) => record.project.id === filters.project_id)) {
    const selectedProject = await fetchRuntimeEndpoint<PageResponse<RuntimeProject>>(
      baseUrl,
      runtimePath(endpoints.projects, {
        project_id: filters.project_id,
        market_code: "AU",
        limit: 1
      }),
      emptyPage<RuntimeProject>()
    );
    if (selectedProject.payload.records.length) {
      projectRecords = [...selectedProject.payload.records, ...projectRecords];
      projects.payload = {
        ...projects.payload,
        records: projectRecords,
        total_count: Math.max(projects.payload.total_count, projectRecords.length)
      };
    }
  }
  const selectedProjectId =
    (filters.project_id && projectRecords.some((record) => record.project.id === filters.project_id)
      ? filters.project_id
      : undefined) || projectRecords[0]?.project.id;
  const selectedProjectParams = selectedProjectId ? { project_id: selectedProjectId } : {};
  paths.projectMembers = selectedProjectId
    ? runtimePath(endpoints.projectMembers, { project_id: selectedProjectId, limit: 20 })
    : endpoints.projectMembers;
  paths.prompts = runtimePath(endpoints.prompts, {
    ...selectedProjectParams,
    market_code: "AU",
    intent_type: filters.intent_type,
    limit: 200
  });
  paths.promptImports = runtimePath(endpoints.promptImports, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.evidence = runtimePath(endpoints.evidence, {
    ...selectedProjectParams,
    platform: filters.platform,
    city: filters.city,
    intent_type: filters.intent_type,
    sort: filters.sort,
    limit: 5
  });
  paths.questionEvidence = runtimePath(endpoints.evidence, {
    ...selectedProjectParams,
    platform: filters.platform,
    city: filters.city,
    intent_type: filters.intent_type,
    sort: filters.sort,
    limit: 200
  });
  paths.collectionRuns = runtimePath(endpoints.collectionRuns, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.fidelityChecks = runtimePath(endpoints.fidelityChecks, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.fidelityTrend = runtimePath(endpoints.fidelityTrend, {
    ...selectedProjectParams,
    limit: 20
  });
  paths.evidenceExport = runtimePath(endpoints.evidenceExport, {
    ...selectedProjectParams,
    platform: filters.platform,
    city: filters.city,
    intent_type: filters.intent_type,
    sort: filters.sort,
    limit: 200
  });
  paths.entityAliases = runtimePath(endpoints.entityAliases, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.entityAliasCandidates = selectedProjectId
    ? runtimePath(endpoints.entityAliasCandidates, {
        project_id: selectedProjectId,
        limit: 5
      })
    : paths.entityAliasCandidates;
  paths.savedViews = runtimePath(endpoints.savedViews, {
    ...selectedProjectParams,
    view_type: "runtime_evidence",
    limit: 5
  });
  paths.brandKit = selectedProjectId
    ? runtimePath(endpoints.brandKit, { project_id: selectedProjectId })
    : endpoints.brandKit;
  paths.scoreWeights = selectedProjectId
    ? runtimePath(endpoints.scoreWeights, { project_id: selectedProjectId })
    : endpoints.scoreWeights;
  paths.scoreFormulas = endpoints.scoreFormulas;
  paths.humanReviews = runtimePath(endpoints.humanReviews, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.humanReviewQueue = runtimePath(endpoints.humanReviewQueue, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.knowledgeSearch = selectedProjectId
    ? runtimePath(endpoints.knowledgeSearch, {
        project_id: selectedProjectId,
        query: "Australia shipping returns local reviews",
        market_code: "AU",
        city: filters.city,
        limit: 5
      })
    : endpoints.knowledgeSearch;
  paths.scores = runtimePath(endpoints.scores, {
    ...selectedProjectParams,
    limit: 1
  });
  paths.graphs = runtimePath(endpoints.graphs, {
    ...selectedProjectParams,
    limit: 1
  });
  paths.reports = runtimePath(endpoints.reports, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.actions = runtimePath(endpoints.actions, {
    ...selectedProjectParams,
    limit: 1
  });
  paths.alerts = runtimePath(endpoints.alerts, {
    ...selectedProjectParams,
    limit: 10
  });
  paths.content = runtimePath(endpoints.content, {
    ...selectedProjectParams,
    limit: 1
  });
  paths.traceability = runtimePath(endpoints.traceability, selectedProjectParams);

  const [
    prompts,
    projectMembers,
    promptImports,
    evidence,
    questionEvidence,
    collectionRuns,
    fidelityChecks,
    fidelityTrend,
    entityAliases,
    entityAliasCandidates,
    savedViews,
    brandKit,
    scoreWeights,
    scoreFormulas,
    humanReviews,
    humanReviewQueue,
    knowledgeSearch,
    scores,
    graphs,
    reports,
    actions,
    alerts,
    content,
    traceability
  ] = await Promise.all([
    fetchRuntimeEndpoint<PageResponse<RuntimePrompt>>(baseUrl, paths.prompts, emptyPage<RuntimePrompt>()),
    selectedProjectId
      ? fetchRuntimeEndpoint<PageResponse<RuntimeProjectMember>>(
          baseUrl,
          paths.projectMembers,
          emptyPage<RuntimeProjectMember>()
        )
      : Promise.resolve({ payload: emptyPage<RuntimeProjectMember>(), error: null }),
    fetchRuntimeEndpoint<PageResponse<RuntimePromptImportHistoryItem>>(
      baseUrl,
      paths.promptImports,
      emptyPage<RuntimePromptImportHistoryItem>()
    ),
    fetchRuntimeEndpoint<PageResponse<EvidenceRun>>(baseUrl, paths.evidence, emptyPage<EvidenceRun>()),
    fetchRuntimeEndpoint<PageResponse<EvidenceRun>>(baseUrl, paths.questionEvidence, emptyPage<EvidenceRun>()),
    fetchRuntimeEndpoint<PageResponse<CollectionRun>>(baseUrl, paths.collectionRuns, emptyPage<CollectionRun>()),
    fetchRuntimeEndpoint<PageResponse<RuntimeFidelityCheck>>(
      baseUrl,
      paths.fidelityChecks,
      emptyPage<RuntimeFidelityCheck>()
    ),
    fetchRuntimeEndpoint<RuntimeFidelityTrend | null>(baseUrl, paths.fidelityTrend, null),
    fetchRuntimeEndpoint<PageResponse<RuntimeEntityAlias>>(
      baseUrl,
      paths.entityAliases,
      emptyPage<RuntimeEntityAlias>()
    ),
    selectedProjectId
      ? fetchRuntimeEndpoint<PageResponse<RuntimeEntityAliasCandidate>>(
          baseUrl,
          paths.entityAliasCandidates,
          emptyPage<RuntimeEntityAliasCandidate>()
        )
      : Promise.resolve({ payload: emptyPage<RuntimeEntityAliasCandidate>(), error: null }),
    fetchRuntimeEndpoint<PageResponse<RuntimeSavedView>>(baseUrl, paths.savedViews, emptyPage<RuntimeSavedView>()),
    selectedProjectId
      ? fetchRuntimeEndpoint<RuntimeProjectBrandKit | null>(baseUrl, paths.brandKit, null, { optionalNotFound: true })
      : Promise.resolve({ payload: null, error: null }),
    selectedProjectId
      ? fetchRuntimeEndpoint<RuntimeScoreWeightConfig | null>(baseUrl, paths.scoreWeights, null)
      : Promise.resolve({ payload: null, error: null }),
    fetchRuntimeEndpoint<RuntimeScoreFormulaCatalog>(baseUrl, paths.scoreFormulas, { formulas: [] }),
    fetchRuntimeEndpoint<PageResponse<RuntimeHumanReview>>(
      baseUrl,
      paths.humanReviews,
      emptyPage<RuntimeHumanReview>()
    ),
    fetchRuntimeEndpoint<PageResponse<RuntimeHumanReviewQueueItem>>(
      baseUrl,
      paths.humanReviewQueue,
      emptyPage<RuntimeHumanReviewQueueItem>()
    ),
    selectedProjectId
      ? fetchRuntimeEndpoint<RuntimeKnowledgeSearch | null>(baseUrl, paths.knowledgeSearch, null, {
          optionalNotFound: true
        })
      : Promise.resolve({ payload: null, error: null }),
    fetchRuntimeEndpoint<PageResponse<ScoreSnapshot>>(baseUrl, paths.scores, emptyPage<ScoreSnapshot>()),
    fetchRuntimeEndpoint<PageResponse<CitationGraph>>(baseUrl, paths.graphs, emptyPage<CitationGraph>()),
    fetchRuntimeEndpoint<PageResponse<ReportExport>>(baseUrl, paths.reports, emptyPage<ReportExport>()),
    fetchRuntimeEndpoint<PageResponse<ActionPlan>>(baseUrl, paths.actions, emptyPage<ActionPlan>()),
    fetchRuntimeEndpoint<PageResponse<RuntimeAlert>>(baseUrl, paths.alerts, emptyPage<RuntimeAlert>()),
    fetchRuntimeEndpoint<PageResponse<ContentEngine>>(baseUrl, paths.content, emptyPage<ContentEngine>()),
    fetchRuntimeEndpoint<TraceabilityDetail | null>(baseUrl, paths.traceability, null, { optionalNotFound: true })
  ]);
  const errors = [
    projects,
    prompts,
    projectMembers,
    promptImports,
    evidence,
    questionEvidence,
    collectionRuns,
    fidelityChecks,
    fidelityTrend,
    entityAliases,
    entityAliasCandidates,
    savedViews,
    brandKit,
    scoreWeights,
    scoreFormulas,
    humanReviews,
    humanReviewQueue,
    knowledgeSearch,
    scores,
    graphs,
    reports,
    actions,
    alerts,
    content,
    traceability
  ]
    .map((result) => result.error)
    .filter((item): item is string => Boolean(item));
  return {
    data: {
      projects: projects.payload,
      projectMembers: projectMembers.payload,
      brandKit: brandKit.payload,
      scoreWeights: scoreWeights.payload,
      scoreFormulas: scoreFormulas.payload,
      humanReviews: humanReviews.payload,
      humanReviewQueue: humanReviewQueue.payload,
      knowledgeSearch: knowledgeSearch.payload,
      prompts: prompts.payload,
      promptImports: promptImports.payload,
      evidence: evidence.payload,
      questionEvidence: questionEvidence.payload,
      collectionRuns: collectionRuns.payload,
      fidelityChecks: fidelityChecks.payload,
      fidelityTrend: fidelityTrend.payload,
      entityAliases: entityAliases.payload,
      entityAliasCandidates: entityAliasCandidates.payload,
      savedViews: savedViews.payload,
      scores: scores.payload,
      graphs: graphs.payload,
      reports: reports.payload,
      actions: actions.payload,
      alerts: alerts.payload,
      content: content.payload,
      traceability: traceability.payload
    },
    error: errors.length ? errors.join("; ") : null,
    fetchUrl: baseUrl,
    displayUrl,
    paths
  };
}

function pct(value: number | undefined): string {
  return `${Math.round((value || 0) * 100)}%`;
}

function optionalPct(value: number | null | undefined): string {
  return value === null || value === undefined ? "n/a" : pct(value);
}

function num(value: number | undefined): string {
  return Number(value || 0).toFixed(2);
}

function parserAgreement(run: ScoreSnapshot["answer_runs"][number] | undefined): string {
  return num(run?.analysis?.payload?.parser_comparison?.agreement_rate);
}

function parserMismatchCount(run: ScoreSnapshot["answer_runs"][number]): number {
  return Object.keys(run.analysis?.payload?.parser_comparison?.mismatched_fields || {}).length;
}

function parserComparisonText(run: ScoreSnapshot["answer_runs"][number]): string {
  const comparison = run.analysis?.payload?.parser_comparison;
  if (!comparison) return "No parser comparison";
  const callLog = comparison.secondary_result?.llm_call_log;
  const llmText = callLog
    ? ` · LLM call ${callLog.status || "unknown"}/${callLog.model || comparison.secondary_parser_engine_id || "model"} · tokens ${
        callLog.total_tokens || 0
      }`
    : "";
  return `${comparison.comparison_method_version || "parser_ab_compare_v1"} · ${
    comparison.secondary_parser_engine_id || "judge"
  } · agreement ${num(
    comparison.agreement_rate,
  )} · mismatches ${parserMismatchCount(run)}${llmText}`;
}

function shortId(value: string | undefined): string {
  return value ? value.slice(0, 8) : "unknown";
}

function boolText(value: boolean | undefined): string {
  if (value === true) return "yes";
  if (value === false) return "no";
  return "unknown";
}

function dateText(value: string | undefined): string {
  if (!value) return "unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toISOString();
}

function uniqueText(values: Array<string | undefined>): string {
  const items = Array.from(new Set(values.filter((item): item is string => Boolean(item))));
  return items.length ? items.join(", ") : "unknown";
}

function savedViewHref(savedView: RuntimeSavedView["saved_view"]): string {
  const params = new URLSearchParams();
  const filters = savedView.filters || {};
  if (savedView.project_id) {
    params.set("project_id", savedView.project_id);
  }
  ["platform", "city", "intent_type"].forEach((key) => {
    const value = filters[key];
    if (typeof value === "string" && value) {
      params.set(key, value);
    }
  });
  if (savedView.sort) {
    params.set("sort", savedView.sort);
  }
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

function alertTone(severity: string | undefined): string {
  if (severity === "critical") return "critical";
  if (severity === "high") return "high";
  if (severity === "medium") return "medium";
  return "low";
}

function anchorId(kind: string, value: string | undefined): string {
  const raw = value || "unknown";
  return `${kind}-${raw.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function anchorHref(kind: string, value: string | undefined): string {
  return `#${anchorId(kind, value)}`;
}

function clipText(value: string | undefined, maxLength: number): string {
  const text = value || "unknown";
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}...` : text;
}

function safeHexColor(value: string | null | undefined, fallback: string): string {
  const color = (value || "").trim();
  return /^#[0-9a-fA-F]{6}$/.test(color) ? color : fallback;
}

function countBy<T>(items: T[], selector: (item: T) => string | undefined): Record<string, number> {
  return items.reduce<Record<string, number>>((counts, item) => {
    const key = selector(item) || "unknown";
    counts[key] = (counts[key] || 0) + 1;
    return counts;
  }, {});
}

function formatCounts(counts: Record<string, number>): string {
  const entries = Object.entries(counts);
  return entries.length ? entries.map(([key, value]) => `${key}:${value}`).join(", ") : "none";
}

const p0aRequiredPlatforms = ["chatgpt", "perplexity"];

function questionCoverageStatus(row: Omit<QuestionDetailRow, "status" | "gapLabel">): {
  status: QuestionCoverageStatus;
  gapLabel: string;
} {
  if (row.runCount === 0) {
    return { status: "no_evidence", gapLabel: "No evidence runs" };
  }
  if (row.missingPlatforms.length) {
    return { status: "platform_gap", gapLabel: `Missing ${row.missingPlatforms.join(", ")}` };
  }
  if (row.triggeredCount === 0) {
    return { status: "trigger_gap", gapLabel: "No triggered answer" };
  }
  if (row.answerCount === 0) {
    return { status: "answer_gap", gapLabel: "No answer present" };
  }
  if (row.citationCount === 0 && row.assetCount === 0) {
    return { status: "source_gap", gapLabel: "No citation or asset" };
  }
  return { status: "covered", gapLabel: "Covered" };
}

function buildQuestionDetailRows(
  prompts: RuntimePrompt[],
  evidenceRuns: EvidenceRun[],
  filters: RuntimeFilters
): QuestionDetailRow[] {
  const promptIdByText = new Map(prompts.map((prompt) => [prompt.text, prompt.id]));
  const evidenceByPrompt = new Map<string, EvidenceRun[]>();
  evidenceRuns.forEach((run) => {
    const promptId =
      run.answer_run.prompt_question_id ||
      (run.answer_run.prompt_text ? promptIdByText.get(run.answer_run.prompt_text) : undefined);
    if (!promptId) return;
    const records = evidenceByPrompt.get(promptId) || [];
    records.push(run);
    evidenceByPrompt.set(promptId, records);
  });

  return prompts.map((prompt) => {
    const records = evidenceByPrompt.get(prompt.id) || [];
    const platforms = Array.from(new Set(records.map((run) => run.answer_run.platform).filter(Boolean))).sort();
    const requiredPlatforms = filters.platform ? [filters.platform] : p0aRequiredPlatforms;
    const missingPlatforms = requiredPlatforms.filter((platform) => !platforms.includes(platform));
    const durations = records
      .map((run) => run.collection_cost?.duration_ms || 0)
      .filter((duration) => duration > 0);
    const latestRun = records
      .slice()
      .sort(
        (left, right) =>
          new Date(right.answer_run.collected_at || "").getTime() -
          new Date(left.answer_run.collected_at || "").getTime()
      )[0];
    const baseRow = {
      prompt,
      evidenceRuns: records,
      runCount: records.length,
      answerCount: records.filter((run) => run.answer_run.answer_present === true).length,
      triggeredCount: records.filter((run) => run.answer_run.surface_triggered === true).length,
      citationCount: records.reduce((total, run) => total + run.citations.length, 0),
      assetCount: records.reduce((total, run) => total + run.evidence_assets.length, 0),
      auditCount: records.reduce((total, run) => total + run.audit_events.length, 0),
      totalCost: records.reduce((total, run) => total + Number(run.collection_cost?.total_cost || 0), 0),
      averageDurationMs: durations.length
        ? Math.round(durations.reduce((total, duration) => total + duration, 0) / durations.length)
        : 0,
      platforms,
      requiredPlatforms,
      missingPlatforms,
      cities: Array.from(new Set(records.map((run) => run.answer_run.city).filter(Boolean))).sort(),
      accessMethods: Array.from(new Set(records.map((run) => run.answer_run.access_method || "unknown"))).sort(),
      surfaceCounts: countBy(records, (run) => run.answer_run.surface),
      statusCounts: countBy(records, (run) => run.answer_run.status),
      latestRun
    };
    const status = questionCoverageStatus(baseRow);
    return { ...baseRow, ...status };
  });
}

export default async function Home({
  searchParams
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const resolvedSearchParams = (await searchParams) || {};
  const filters: RuntimeFilters = {
    project_id: cleanFilter(resolvedSearchParams.project_id),
    platform: cleanFilter(resolvedSearchParams.platform),
    city: cleanFilter(resolvedSearchParams.city),
    intent_type: cleanFilter(resolvedSearchParams.intent_type),
    sort: cleanFilter(resolvedSearchParams.sort)
  };
  const { data, error, displayUrl, paths } = await fetchRuntimeData(filters);
  const selectedProject =
    (filters.project_id && data.projects.records.find((record) => record.project.id === filters.project_id)) ||
    data.projects.records[0];
  const selectedProjectId = selectedProject?.project.id;
  const latestProject = selectedProject;
  const projectBrandKit = data.brandKit?.brand_kit || null;
  const entityAliasOptions = latestProject
    ? [
        ...(latestProject.brand?.id
          ? [
              {
                ref: `brand:${latestProject.brand.id}`,
                label: `${latestProject.brand.canonical_name} · brand`,
                defaultAlias:
                  latestProject.brand.official_domains?.[0] ||
                  latestProject.brand.canonical_name ||
                  latestProject.project.target_brand
              }
            ]
          : []),
        ...latestProject.competitors
          .filter((competitor) => competitor.id)
          .map((competitor) => ({
            ref: `competitor:${competitor.id}`,
            label: `${competitor.canonical_name} · competitor`,
            defaultAlias: competitor.official_domains?.[0] || competitor.canonical_name
          }))
      ]
    : [];
  const defaultEntityAlias = entityAliasOptions[0]?.defaultAlias || latestProject?.project.target_brand || "";
  const latestPrompt = data.prompts.records[0];
  const latestEvidence = data.evidence.records[0];
  const latestCollectionRun = data.collectionRuns.records[0];
  const latestScore = data.scores.records[0];
  const latestGraph = data.graphs.records[0];
  const latestReport = data.reports.records[0];
  const latestAction = data.actions.records[0];
  const latestContent = data.content.records[0];
  const traceability = data.traceability;
  const scoreWeightConfig = data.scoreWeights?.score_weight_config || null;
  const savedScoreWeightConfig = scoreWeightConfig?.id ? scoreWeightConfig : null;
  const scoreWeightAuditEvent = data.scoreWeights?.audit_events[0]?.event_type || "default weights";
  const scoreFormulaOptions = data.scoreFormulas.formulas.length
    ? data.scoreFormulas.formulas
    : [
        {
          formula_version: "au_visibility_v1",
          weights: defaultScoreWeights,
          description: "Default AU visibility score weights",
          status: "active",
          supersedes: null
        }
      ];
  const selectedFormulaVersion =
    savedScoreWeightConfig?.formula_version ||
    latestScore?.snapshot.formula_version ||
    scoreWeightConfig?.formula_version ||
    scoreFormulaOptions[0].formula_version;
  const selectedFormula =
    scoreFormulaOptions.find((formula) => formula.formula_version === selectedFormulaVersion) || scoreFormulaOptions[0];
  const configuredScoreWeights =
    savedScoreWeightConfig?.weights ||
    latestScore?.snapshot.component_weights_snapshot ||
    scoreWeightConfig?.weights ||
    selectedFormula.weights ||
    defaultScoreWeights;
  const scoreWeightTotal = scoreComponentNames.reduce(
    (total, component) => total + Number(configuredScoreWeights[component] || 0),
    0
  );
  const latestScoreWeightTotal = scoreComponentNames.reduce(
    (total, component) => total + Number(latestScore?.snapshot.component_weights_snapshot?.[component] || 0),
    0
  );
  const reportArtifactBase = latestReport
    ? `${displayUrl}/v1/reports/runtime/${latestReport.report_export.id}/artifact`
    : null;
  const totalAuditEvents =
    (latestEvidence?.audit_events.length || 0) +
    data.collectionRuns.records.reduce((total, item) => total + item.audit_events.length, 0) +
    data.fidelityChecks.records.reduce((total, item) => total + item.audit_events.length, 0) +
    data.entityAliases.records.reduce((total, item) => total + item.audit_events.length, 0) +
    data.humanReviews.records.reduce((total, item) => total + item.audit_events.length, 0) +
    (latestScore?.audit_events.length || 0) +
    (latestReport?.audit_events.length || 0) +
    (latestAction?.audit_events.length || 0) +
    (latestContent?.audit_events.length || 0) +
    (traceability?.audit_events.length || 0);
  const promptIntentCount = new Set(data.prompts.records.map((prompt) => prompt.intent_type)).size;
  const promptCityCount = new Set(data.prompts.records.map((prompt) => prompt.city)).size;
  const questionDetailRows = buildQuestionDetailRows(data.prompts.records, data.questionEvidence.records, filters);
  const coveredQuestionCount = questionDetailRows.filter((row) => row.status === "covered").length;
  const questionCoverageRate = questionDetailRows.length ? coveredQuestionCount / questionDetailRows.length : 0;
  const questionGapRows = questionDetailRows.filter((row) => row.status !== "covered");
  const questionStatusCounts = countBy(questionDetailRows, (row) => row.status);
  const latestReportScore = latestReport?.score_snapshots[0];
  const latestReportGraph = latestReport?.citation_graph;
  const reportPlatformWeights = latestReport?.report_export.platform_weights_snapshot || {};
  const reportPlatforms = latestReport ? uniqueText(latestReport.answer_runs.map((run) => run.platform)) : "unknown";
  const reportAccessMethods = latestReport
    ? uniqueText(latestReport.answer_runs.map((run) => run.access_method))
    : "unknown";
  const reportCities = latestReport ? uniqueText(latestReport.answer_runs.map((run) => run.city)) : "unknown";
  const reportAccessMethodCounts = latestReport ? countBy(latestReport.answer_runs, (run) => run.access_method) : {};
  const reportPlatformCounts = latestReport ? countBy(latestReport.answer_runs, (run) => run.platform) : {};
  const reportMethodDisclosure = latestReport?.report_export.method_disclosure;
  const latestFidelityCheck =
    data.fidelityChecks.records.find((item) => item.fidelity_check.report_export_id === latestReport?.report_export.id) ||
    data.fidelityChecks.records[0];
  const reportFrozenAccessMethodCounts = reportMethodDisclosure?.access_method_distribution || reportAccessMethodCounts;
  const reportFrozenPlatformCounts = reportMethodDisclosure?.platform_distribution || reportPlatformCounts;
  const reportFidelity = reportMethodDisclosure?.api_browser_fidelity;
  const reportScoreRateDisclosure = reportMethodDisclosure?.score_rate_denominators;
  const reportRateDefinitions = reportScoreRateDisclosure?.definitions || {};
  const reportRateEvidenceDenominators = reportScoreRateDisclosure?.evidence_denominators || {};
  const runtimeFidelity = latestFidelityCheck?.fidelity_check;
  const reportGate = reportMethodDisclosure?.google_spike_gate;
  const reportOfficialApiCount =
    runtimeFidelity?.official_api_records ?? reportFidelity?.official_api_records ?? reportFrozenAccessMethodCounts.official_api ?? 0;
  const reportBrowserCount =
    runtimeFidelity?.browser_records ?? reportFidelity?.browser_records ?? reportFrozenAccessMethodCounts.browser ?? 0;
  const reportFidelityStatus =
    runtimeFidelity?.status || reportFidelity?.status || (reportOfficialApiCount && reportBrowserCount ? "sample_required" : "not_run");
  const reportGoogleCoverage =
    reportMethodDisclosure?.google_coverage ||
    ((reportPlatformCounts.google || 0) > 0 ? "limited_coverage_appendix_only" : "limited_coverage_no_google_rows");
  const reportGoogleGateStatus = reportGate?.gate_status || "not_run";
  const reportLimitedCoverage = reportGate?.limited_coverage ?? true;
  const reportComparablePairs = runtimeFidelity?.comparable_prompt_city_pairs ?? reportFidelity?.comparable_prompt_city_pairs ?? 0;
  const reportDifferenceRateValue = runtimeFidelity?.difference_rate ?? reportFidelity?.difference_rate;
  const reportDifferenceRate: string | number =
    reportDifferenceRateValue === null || reportDifferenceRateValue === undefined ? "n/a" : reportDifferenceRateValue;
  const reportFidelityMismatchCount = runtimeFidelity?.mismatch_count ?? reportFidelity?.mismatch_count ?? 0;
  const fidelityTrend = data.fidelityTrend;
  const fidelityTrendSampleText = fidelityTrend
    ? `${fidelityTrend.sampled_count}/${fidelityTrend.total_count}`
    : "0/0";
  const fidelityTrendWindow = fidelityTrend
    ? `${dateText(fidelityTrend.earliest_checked_at || undefined)} -> ${dateText(
        fidelityTrend.latest_checked_at || undefined,
      )}`
    : "unknown";
  const reportFidelityAudit =
    latestFidelityCheck?.audit_events[0]?.event_type || (latestFidelityCheck ? "api_browser_fidelity_checked" : "no check");
  const reportScreenshotCount =
    reportMethodDisclosure?.evidence_asset_coverage?.screenshot_records ??
    (latestReport?.answer_runs.filter((run) => run.access_method === "browser" || run.access_method === "manual").length || 0);
  const reportHtmlSnapshotCount = reportMethodDisclosure?.evidence_asset_coverage?.html_snapshot_records ?? 0;
  const reportTriggerDenominator =
    reportRateDefinitions.trigger_rate?.denominator || "all attempted evidence records in this report window";
  const reportMentionDenominator =
    reportRateDefinitions.mention_rate?.denominator || "surface_triggered evidence records, not all attempted records";
  const reportRecommendationDenominator =
    reportRateDefinitions.recommendation_rate?.denominator ||
    "surface_triggered evidence records, not all attempted records";
  const reportEvidenceAttemptedRecords = reportRateEvidenceDenominators.attempted_records ?? latestReport?.answer_runs.length ?? 0;
  const reportEvidenceTriggeredRecords =
    reportRateEvidenceDenominators.surface_triggered_records ??
    latestReport?.answer_runs.filter((run) => run.surface_triggered).length ??
    0;
  const reportEvidenceTriggerRate =
    reportScoreRateDisclosure?.evidence_trigger_rate ??
    (reportEvidenceAttemptedRecords ? reportEvidenceTriggeredRecords / reportEvidenceAttemptedRecords : 0);
  const latestRetestComparison = latestAction?.retest_comparisons[0];
  const activeFilterCount = [filters.platform, filters.city, filters.intent_type].filter(Boolean).length;
  const filterLabel = activeFilterCount
    ? [filters.platform, filters.city, filters.intent_type].filter(Boolean).join(" / ")
    : "All runtime evidence";
  const selectedProjectLabel = selectedProject
    ? `${selectedProject.tenant.name} / ${selectedProject.project.name}`
    : "No runtime project";
  const evidenceExportUrl = `${displayUrl}${paths.evidenceExport}`;
  const evidenceSort = data.evidence.sort || filters.sort || "collected_at_desc";
  const runtimeViewName = activeFilterCount
    ? `${selectedProject?.project.name || "Runtime project"} · ${filterLabel} · ${evidenceSort}`
    : `${selectedProject?.project.name || "Runtime project"} · All runtime evidence · ${evidenceSort}`;
  const reportMarkdownUrl = reportArtifactPath(reportArtifactBase, "markdown", { ...filters, sort: evidenceSort });
  const reportCsvUrl = reportArtifactPath(reportArtifactBase, "csv", { ...filters, sort: evidenceSort });
  const reportPdfUrl = reportArtifactPath(reportArtifactBase, "pdf", { ...filters, sort: evidenceSort });
  const whiteLabelClientName =
    projectBrandKit?.client_name || latestProject?.brand?.canonical_name || latestProject?.project.target_brand || "Client";
  const whiteLabelPreparedBy = projectBrandKit?.prepared_by || "GENO SaaS AU";
  const whiteLabelLogoUrl = projectBrandKit?.logo_url || "https://examplebrand.example/logo.png";
  const whiteLabelPrimaryColor = safeHexColor(projectBrandKit?.primary_color, "#0f766e");
  const whiteLabelSecondaryColor = safeHexColor(projectBrandKit?.secondary_color, "#111827");
  const whiteLabelFooterText = projectBrandKit?.footer_text || "Prepared for AU GEO visibility review";
  const brandKitAudit = data.brandKit?.audit_events[0];
  const reportWhiteLabelPdfUrl = reportArtifactPath(
    reportArtifactBase,
    "pdf",
    { ...filters, sort: evidenceSort },
    {
      template: "white_label",
      client_name: whiteLabelClientName,
      prepared_by: whiteLabelPreparedBy
    }
  );
  const reportArtifactFilters = { ...filters, sort: evidenceSort };
  const latestContentDraft = latestContent?.content_drafts[0];
  const topReviewQueueItem = data.humanReviewQueue.records[0];
  const reviewTarget =
    topReviewQueueItem
      ? {
          targetType: topReviewQueueItem.target_type,
          targetId: topReviewQueueItem.target_id,
          label: topReviewQueueItem.title
        }
      : latestScore?.snapshot.id
      ? {
          targetType: "visibility_score_snapshot",
          targetId: latestScore.snapshot.id,
          label: `score ${num(latestScore.snapshot.final_score)}`
        }
      : latestContentDraft?.draft.id
        ? {
            targetType: "content_draft",
            targetId: latestContentDraft.draft.id,
            label: latestContentDraft.draft.title
          }
        : latestEvidence?.answer_run.id
          ? {
              targetType: "answer_run",
              targetId: latestEvidence.answer_run.id,
              label: latestEvidence.answer_run.prompt_text || latestEvidence.answer_run.id
            }
          : latestProject?.project.id
            ? {
                targetType: "project",
                targetId: latestProject.project.id,
                label: latestProject.project.name
              }
            : null;

  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">GENO SaaS AU</p>
          <h1>Runtime Evidence Console</h1>
        </div>
        <div className="apiBox">
          <span>Runtime API</span>
          <strong>{displayUrl}</strong>
        </div>
      </section>

      {error ? (
        <section className="notice">
          <strong>Runtime data unavailable.</strong>
          <span>{error}</span>
          <code>docker compose -f infra/docker-compose.yml --profile worker run --rm collector-worker</code>
        </section>
      ) : null}

      <section className="filterBar" aria-label="runtime filters">
        <div>
          <h2>Runtime Filters</h2>
          <span>
            {selectedProjectLabel} · {filterLabel}
          </span>
        </div>
        <form className="filterForm">
          <label>
            <span>Project</span>
            <select name="project_id" defaultValue={selectedProjectId || ""}>
              {data.projects.records.length ? (
                data.projects.records.map((record) => (
                  <option key={record.project.id} value={record.project.id}>
                    {record.tenant.name} / {record.project.name}
                  </option>
                ))
              ) : (
                <option value="">No runtime project</option>
              )}
            </select>
          </label>
          <label>
            <span>Platform</span>
            <select name="platform" defaultValue={filters.platform || ""}>
              <option value="">All platforms</option>
              <option value="chatgpt">chatgpt</option>
              <option value="google">google</option>
              <option value="perplexity">perplexity</option>
            </select>
          </label>
          <label>
            <span>Evidence city</span>
            <select name="city" defaultValue={filters.city || ""}>
              <option value="">All cities</option>
              <option value="Australia">Australia</option>
              <option value="Sydney">Sydney</option>
              <option value="Melbourne">Melbourne</option>
              <option value="Brisbane">Brisbane</option>
            </select>
          </label>
          <label>
            <span>Intent</span>
            <select name="intent_type" defaultValue={filters.intent_type || ""}>
              <option value="">All intents</option>
              <option value="brand_awareness">brand_awareness</option>
              <option value="category_recommendation">category_recommendation</option>
              <option value="city_category_recommendation">city_category_recommendation</option>
              <option value="competitor_comparison">competitor_comparison</option>
              <option value="purchase_decision">purchase_decision</option>
              <option value="review_reputation">review_reputation</option>
              <option value="price">price</option>
              <option value="service_coverage">service_coverage</option>
              <option value="local_trust">local_trust</option>
              <option value="alternative">alternative</option>
            </select>
          </label>
          <label>
            <span>Sort evidence</span>
            <select name="sort" defaultValue={filters.sort || "collected_at_desc"}>
              <option value="collected_at_desc">Newest first</option>
              <option value="collected_at_asc">Oldest first</option>
              <option value="cost_desc">Highest cost</option>
              <option value="cost_asc">Lowest cost</option>
              <option value="citation_count_desc">Most citations</option>
              <option value="audit_count_desc">Most audit events</option>
            </select>
          </label>
          <button className="actionButton" type="submit">
            Apply filters
          </button>
          <a className="resetLink" href="/">
            Reset
          </a>
          <a className="resetLink" href={evidenceExportUrl}>
            Export Evidence CSV
          </a>
        </form>
        <dl className="facts filterFacts">
          <Fact label="Project query" value={paths.projects} />
          <Fact label="Selected project" value={selectedProjectId || "No project selected"} />
          <Fact label="Prompts query" value={paths.prompts} />
          <Fact label="Evidence query" value={paths.evidence} />
          <Fact label="Export query" value={paths.evidenceExport} />
          <Fact label="Saved views query" value={paths.savedViews} />
          <Fact label="Brand kit query" value={paths.brandKit} />
          <Fact label="Report query" value={paths.reports} />
          <Fact label="Evidence sort" value={evidenceSort} />
        </dl>
        <div className="savedViews">
          <form action={saveCurrentRuntimeView} className="saveViewForm">
            <input type="hidden" name="project_id" value={selectedProjectId || ""} />
            <input type="hidden" name="platform" value={filters.platform || ""} />
            <input type="hidden" name="city" value={filters.city || ""} />
            <input type="hidden" name="intent_type" value={filters.intent_type || ""} />
            <input type="hidden" name="sort" value={evidenceSort} />
            <input type="hidden" name="query_path" value={paths.evidence} />
            <input type="hidden" name="export_path" value={paths.evidenceExport} />
            <label>
              <span>Saved view name</span>
              <input name="name" defaultValue={runtimeViewName} />
            </label>
            <button className="actionButton" type="submit" disabled={!latestProject}>
              Save view
            </button>
          </form>
          <div className="savedViewList">
            <h3>Saved Views</h3>
            {data.savedViews.records.length ? (
              <ul className="plainList">
                {data.savedViews.records.map((item) => (
                  <li key={item.saved_view.id}>
                    <strong>{item.saved_view.name}</strong>
                    <a href={savedViewHref(item.saved_view)}>{item.saved_view.query_path}</a>
                    <small>
                      {item.saved_view.sort} · {item.audit_events[0]?.event_type || "no audit"} ·{" "}
                      {item.audit_events[0]?.after_hash || "no hash"}
                    </small>
                  </li>
                ))}
              </ul>
            ) : (
              <small>No saved runtime views yet.</small>
            )}
          </div>
        </div>
      </section>

      <section className="metrics" aria-label="runtime metrics">
        <Metric label="Projects" value={data.projects.total_count} />
        <Metric label="Prompts" value={data.prompts.total_count} />
        <Metric label="Evidence runs" value={data.evidence.total_count} />
        <Metric label="Question coverage" value={pct(questionCoverageRate)} />
        <Metric label="Final score" value={num(latestScore?.snapshot.final_score)} />
        <Metric label="Source gaps" value={latestGraph?.source_gaps.length || 0} />
        <Metric label="Open actions" value={latestAction?.action_recommendations.length || 0} />
        <Metric label="Content drafts" value={latestContent?.content_drafts.length || 0} />
        <Metric label="Human reviews" value={data.humanReviews.total_count} />
        <Metric label="Audit events" value={totalAuditEvents} />
        <Metric label="Trace links" value={traceability?.evidence_links.length || 0} />
      </section>

      <section className="dashboard">
        <Panel title="Project Bootstrap" subtitle={latestProject?.project.name || "No runtime project"}>
          <div className="stack">
            {latestProject ? (
              <>
                <dl className="facts">
                  <Fact label="Tenant" value={latestProject.tenant.name} />
                  <Fact label="Project ID" value={shortId(latestProject.project.id)} />
                  <Fact label="Market" value={latestProject.project.market_code} />
                  <Fact label="Industry" value={latestProject.project.industry_code} />
                  <Fact label="Brand" value={latestProject.brand?.canonical_name || latestProject.project.target_brand} />
                  <Fact label="Category" value={latestProject.project.category} />
                  <Fact label="Prompts" value={latestProject.prompt_count} />
                  <Fact label="Competitors" value={latestProject.competitors.length} />
                </dl>
                <ul className="plainList">
                  {latestProject.competitors.slice(0, 4).map((competitor) => (
                    <li key={competitor.canonical_name}>
                      <strong>{competitor.status || "competitor"}</strong>
                      <span>{competitor.canonical_name}</span>
                      <small>{competitor.official_domains?.[0] || "domain pending"}</small>
                    </li>
                  ))}
                </ul>
                <small className="auditLine">
                  {latestProject.audit_events[0]?.event_type || "no bootstrap audit"} ·{" "}
                  {latestProject.audit_events[0]?.method_version || "no method version"}
                </small>
                <div className="projectMembers">
                  <div className="formHeader">
                    <h3>Project Members</h3>
                    <small>
                      {data.projectMembers.total_count} members · project_members gate · project_member_saved ·
                      project_member_deleted
                    </small>
                  </div>
                  {data.projectMembers.records.length ? (
                    <ul className="plainList">
                      {data.projectMembers.records.slice(0, 6).map((record) => (
                        <li key={record.member.id}>
                          <strong>{record.member.role}</strong>
                          <span>{record.member.user_id}</span>
                          <small>
                            {record.audit_events[0]?.event_type || "bootstrap member"} ·{" "}
                            {record.audit_events[0]?.actor_id || "system"} ·{" "}
                            {record.audit_events[0]?.after_hash || "no hash"}
                          </small>
                          <form action={deleteRuntimeProjectMember} className="projectMemberDeleteForm">
                            <input type="hidden" name="project_id" value={latestProject.project.id} />
                            <input type="hidden" name="user_id" value={record.member.user_id} />
                            <input type="hidden" name="deleted_by" value="runtime-console" />
                            <input type="hidden" name="reason" value="Remove runtime project collaborator" />
                            <button className="textButton" type="submit">
                              Remove
                            </button>
                          </form>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <small>No runtime project members found.</small>
                  )}
                  <form action={saveRuntimeProjectMember} className="projectMemberForm">
                    <input type="hidden" name="project_id" value={latestProject.project.id} />
                    <label>
                      <span>User ID</span>
                      <input name="user_id" defaultValue="analyst@example.com" />
                    </label>
                    <label>
                      <span>Role</span>
                      <select name="role" defaultValue="analyst">
                        <option value="owner">owner</option>
                        <option value="admin">admin</option>
                        <option value="analyst">analyst</option>
                        <option value="viewer">viewer</option>
                      </select>
                    </label>
                    <label className="wideField">
                      <span>Reason</span>
                      <input name="reason" defaultValue="Add runtime project collaborator" />
                    </label>
                    <input type="hidden" name="updated_by" value="runtime-console" />
                    <button className="actionButton" type="submit">
                      Save member
                    </button>
                  </form>
                </div>
                <form action={confirmEntityAlias} className="entityAliasForm">
                  <div className="formHeader">
                    <h3>Entity Alias</h3>
                    <small>
                      {data.entityAliases.total_count} confirmed · {data.entityAliasCandidates.total_count} candidates
                    </small>
                  </div>
                  <label className="wideField">
                    <span>Entity</span>
                    <select name="entity_ref" defaultValue={entityAliasOptions[0]?.ref || ""}>
                      {entityAliasOptions.map((option) => (
                        <option key={option.ref} value={option.ref}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Alias type</span>
                    <select name="alias_type" defaultValue="alias">
                      <option value="alias">alias</option>
                      <option value="domain">domain</option>
                      <option value="product">product</option>
                      <option value="parent_company">parent_company</option>
                    </select>
                  </label>
                  <label>
                    <span>Confidence</span>
                    <input name="confidence" type="number" min="0" max="1" step="0.01" defaultValue="1" />
                  </label>
                  <label className="wideField">
                    <span>Alias</span>
                    <input name="alias" defaultValue={defaultEntityAlias} />
                  </label>
                  <label className="wideField">
                    <span>Notes</span>
                    <input name="notes" defaultValue="Runtime entity alias confirmation for parser disambiguation" />
                  </label>
                  <input type="hidden" name="confirmed_by" value="runtime-console" />
                  <button className="actionButton" type="submit" disabled={!entityAliasOptions.length}>
                    Confirm alias
                  </button>
                </form>
                {data.entityAliasCandidates.records.length ? (
                  <ul className="plainList">
                    {data.entityAliasCandidates.records.slice(0, 4).map((record) => (
                      <li key={record.candidate.id}>
                        <strong>
                          Candidate · {record.candidate.alias_type} · {record.entity.entity_kind}
                        </strong>
                        <span>{record.candidate.alias}</span>
                        <small>
                          {record.entity.canonical_name} · {record.candidate.source} · confidence{" "}
                          {num(record.candidate.confidence)}
                        </small>
                        <form action={confirmEntityAlias} className="inlineAliasForm">
                          <input
                            type="hidden"
                            name="entity_ref"
                            value={`${record.candidate.entity_kind}:${record.candidate.entity_id}`}
                          />
                          <input type="hidden" name="alias" value={record.candidate.alias} />
                          <input type="hidden" name="alias_type" value={record.candidate.alias_type} />
                          <input type="hidden" name="confidence" value={String(record.candidate.confidence || 0.7)} />
                          <input type="hidden" name="confirmed_by" value="runtime-console" />
                          <input
                            type="hidden"
                            name="notes"
                            value={`Confirm generated alias candidate from ${record.candidate.source}`}
                          />
                          <button className="actionButton compactAction" type="submit">
                            Confirm candidate
                          </button>
                        </form>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {data.entityAliases.records.length ? (
                  <ul className="plainList">
                    {data.entityAliases.records.slice(0, 4).map((record) => (
                      <li key={record.entity_alias.id}>
                        <strong>
                          {record.entity_alias.alias_type} · {record.entity.entity_kind}
                        </strong>
                        <span>{record.entity_alias.alias}</span>
                        <small>
                          {record.entity.canonical_name} ·{" "}
                          {record.audit_events[0]?.event_type || "no alias audit"} ·{" "}
                          {record.audit_events[0]?.after_hash || "no hash"}
                        </small>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </>
            ) : (
              <EmptyState />
            )}
            <form action={createAuRuntimeProject} className="projectCreateForm">
              <div className="formHeader">
                <h3>Client Project</h3>
                <small>AU / DTC ecommerce / 100 prompts</small>
              </div>
              <label>
                <span>Tenant</span>
                <input name="tenant_name" defaultValue="Design Partner AU" />
              </label>
              <label>
                <span>Project</span>
                <input name="project_name" defaultValue="AU DTC Evidence Pilot" />
              </label>
              <label>
                <span>Brand</span>
                <input name="target_brand" defaultValue="ExampleBrand" />
              </label>
              <label>
                <span>Category</span>
                <input name="category" defaultValue="DTC ecommerce products" />
              </label>
              <label className="wideField">
                <span>Brand domains</span>
                <input name="brand_official_domains" defaultValue="examplebrand.example" />
              </label>
              <label className="wideField">
                <span>Product lines</span>
                <input name="brand_product_lines" defaultValue="Flagship product, Premium bundle" />
              </label>
              <label className="wideField">
                <span>Competitors</span>
                <textarea
                  name="competitors"
                  defaultValue={"Emma Sleep\nSleeping Duck\nEcosa\nIKEA Australia"}
                  rows={4}
                />
              </label>
              <input type="hidden" name="owner_user_id" value="runtime-console" />
              <button className="actionButton" type="submit">
                Create client project
              </button>
            </form>
            <form action={saveProjectBrandKit} className="brandKitForm">
              <div className="formHeader">
                <h3>Brand Kit</h3>
                <small>
                  {projectBrandKit
                    ? `${projectBrandKit.updated_by} · ${brandKitAudit?.event_type || "saved"}`
                    : "project-level white-label defaults"}
                </small>
              </div>
              <input type="hidden" name="project_id" value={selectedProjectId || ""} />
              <label>
                <span>Client name</span>
                <input
                  name="client_name"
                  defaultValue={
                    projectBrandKit?.client_name ||
                    latestProject?.brand?.canonical_name ||
                    latestProject?.project.target_brand ||
                    "ExampleBrand AU"
                  }
                />
              </label>
              <label>
                <span>Prepared by</span>
                <input name="prepared_by" defaultValue={projectBrandKit?.prepared_by || "GENO SaaS AU"} />
              </label>
              <label className="wideField">
                <span>Logo URL</span>
                <input name="logo_url" defaultValue={whiteLabelLogoUrl} />
              </label>
              <label className="themeColorField">
                <span>Primary color</span>
                <input name="primary_color" type="color" defaultValue={whiteLabelPrimaryColor} />
              </label>
              <label className="themeColorField">
                <span>Secondary color</span>
                <input name="secondary_color" type="color" defaultValue={whiteLabelSecondaryColor} />
              </label>
              <label className="wideField">
                <span>Footer text</span>
                <textarea
                  name="footer_text"
                  defaultValue={whiteLabelFooterText}
                  rows={2}
                />
              </label>
              <button className="actionButton" type="submit" disabled={!selectedProjectId}>
                Save brand kit
              </button>
            </form>
            <section className="themeEditorPreview" aria-label="advanced white-label theme editor">
              <div className="formHeader">
                <h3>Theme Editor</h3>
                <small>
                  {brandKitAudit?.method_version || "project_brand_kit_v1"} ·{" "}
                  {brandKitAudit?.after_hash ? `hash ${clipText(brandKitAudit.after_hash, 18)}` : "not saved"}
                </small>
              </div>
              <div className="themePreviewCard">
                <div className="themePreviewHeader" style={{ backgroundColor: whiteLabelPrimaryColor }}>
                  <span className="themeLogoMark" style={{ borderColor: whiteLabelSecondaryColor }}>
                    {whiteLabelClientName.slice(0, 2).toUpperCase()}
                  </span>
                  <div>
                    <strong>{whiteLabelClientName}</strong>
                    <span>{whiteLabelPreparedBy}</span>
                  </div>
                </div>
                <div className="themePreviewBody">
                  <h3>AU GEO Visibility Report</h3>
                  <p>{filterLabel} · {evidenceSort}</p>
                  <div className="themeMetricStrip">
                    <span style={{ borderColor: whiteLabelPrimaryColor }}>
                      Score {num(latestScore?.snapshot.final_score)}
                    </span>
                    <span style={{ borderColor: whiteLabelSecondaryColor }}>
                      Evidence {latestReport?.answer_runs.length || data.evidence.total_count}
                    </span>
                  </div>
                  <small>{whiteLabelFooterText}</small>
                </div>
              </div>
              <dl className="facts themePreviewFacts">
                <Fact label="Primary color" value={whiteLabelPrimaryColor} />
                <Fact label="Secondary color" value={whiteLabelSecondaryColor} />
                <Fact label="Logo source" value={whiteLabelLogoUrl} />
                <Fact
                  label="White-label path"
                  value={reportWhiteLabelPdfUrl?.replace(displayUrl, "") || "No white-label artifact"}
                />
                <Fact label="Template payload" value="client_name/prepared_by/logo_url/primary_color/secondary_color/footer_text" />
                <Fact label="Audit event" value={brandKitAudit?.event_type || "project_brand_kit_saved pending"} />
              </dl>
            </section>
            <form action={uploadProjectBrandLogo} className="brandKitForm">
              <div className="formHeader">
                <h3>Logo Upload</h3>
                <small>{projectBrandKit?.logo_url || "archive to object storage"}</small>
              </div>
              <input type="hidden" name="project_id" value={selectedProjectId || ""} />
              <input type="hidden" name="uploaded_by" value="runtime-console" />
              <label className="wideField">
                <span>Logo file</span>
                <input name="brand_logo" type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml,image/gif" />
              </label>
              <button className="actionButton" type="submit" disabled={!selectedProjectId}>
                Upload logo
              </button>
              <p className="formHint">
                {data.brandKit?.audit_events[0]?.event_type === "project_brand_logo_uploaded"
                  ? `Last upload · ${data.brandKit.audit_events[0]?.method_version || "project_brand_logo_upload_v1"}`
                  : "Uploaded logo URI becomes the Brand Kit default for white-label PDF artifacts."}
              </p>
            </form>
            <form action={saveScoreWeightConfig} className="brandKitForm">
              <div className="formHeader">
                <h3>Score Weights</h3>
                <small>
                  {scoreWeightConfig?.updated_by || "system-default"} · {scoreWeightAuditEvent} ·{" "}
                  {selectedFormulaVersion} · total {num(scoreWeightTotal)}
                </small>
              </div>
              <input type="hidden" name="project_id" value={selectedProjectId || ""} />
              <label className="wideField">
                <span>Formula version</span>
                <select name="formula_version" defaultValue={selectedFormulaVersion}>
                  {scoreFormulaOptions.map((formula) => (
                    <option key={formula.formula_version} value={formula.formula_version}>
                      {formula.formula_version} · {formula.status}
                    </option>
                  ))}
                </select>
              </label>
              <dl className="facts contributionFacts">
                <Fact label="Formula catalog" value={paths.scoreFormulas} />
                <Fact label="Selected formula" value={selectedFormula.formula_version} />
                <Fact label="Snapshot formula" value={latestScore?.snapshot.formula_version || "no snapshot"} />
                <Fact label="Formula status" value={selectedFormula.status} />
                <Fact label="Supersedes" value={selectedFormula.supersedes || "none"} />
                <Fact label="Formula note" value={selectedFormula.description} />
              </dl>
              {scoreComponentNames.map((component) => (
                <label key={component}>
                  <span>{component}</span>
                  <input
                    name={component}
                    type="number"
                    step="0.01"
                    min="0"
                    max="1"
                    defaultValue={String(configuredScoreWeights[component] ?? defaultScoreWeights[component])}
                  />
                </label>
              ))}
              <label className="wideField">
                <span>Notes</span>
                <textarea
                  name="notes"
                  defaultValue={scoreWeightConfig?.notes || "Project-level scoring weight review"}
                  rows={2}
                />
              </label>
              <button className="actionButton" type="submit" disabled={!selectedProjectId}>
                Save score weights
              </button>
            </form>
          </div>
        </Panel>

        <Panel title="Prompt Pack" subtitle={latestPrompt?.prompt_version || "No runtime prompts"}>
          {data.prompts.records.length ? (
            <div className="stack">
              <dl className="facts">
                <Fact label="Total prompts" value={data.prompts.total_count} />
                <Fact label="Loaded" value={data.prompts.records.length} />
                <Fact label="Intent types" value={promptIntentCount} />
                <Fact label="Cities" value={promptCityCount} />
                <Fact label="Brand" value={latestPrompt?.target_brand || "unknown"} />
                <Fact label="Language" value={latestPrompt?.language || "unknown"} />
              </dl>
              <ul className="plainList promptList">
                {data.prompts.records.slice(0, 5).map((prompt) => (
                  <li key={prompt.id}>
                    <strong>
                      {prompt.priority} · {prompt.intent_type} · {prompt.city}
                    </strong>
                    <span>{prompt.text}</span>
                    <small>
                      weight {num(prompt.intent_weight)} · {prompt.status} · {prompt.competitors.length} competitors
                    </small>
                  </li>
                ))}
              </ul>
              <form action={importRuntimePromptsCsv} className="promptImportForm">
                <input type="hidden" name="project_id" value={selectedProjectId || ""} />
                <div className="formHeader">
                  <h3>Prompt CSV Import</h3>
                  <small>text,intent_type,city,priority,intent_weight</small>
                </div>
                <label className="wideField">
                  <span>CSV rows</span>
                  <textarea
                    name="csv_content"
                    defaultValue={
                      "text,intent_type,city,priority,intent_weight\n" +
                      `"Is ${latestProject?.project.target_brand || "ExampleBrand"} visible in Sydney AI recommendations?",brand_awareness,Sydney,1,0.9\n` +
                      `"Best ${latestProject?.project.category || "DTC ecommerce products"} for Melbourne shoppers",category_recommendation,Melbourne,2,1.0`
                    }
                    rows={5}
                  />
                </label>
                <button className="actionButton" type="submit" disabled={!selectedProjectId}>
                  Import prompts
                </button>
              </form>
              <form action={importRuntimePromptsFile} className="promptImportForm">
                <input type="hidden" name="project_id" value={selectedProjectId || ""} />
                <div className="formHeader">
                  <h3>Prompt File Import</h3>
                  <small>.csv or .xlsx · first worksheet</small>
                </div>
                <label>
                  <span>Prompt file</span>
                  <input
                    name="prompt_file"
                    type="file"
                    accept=".csv,.txt,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  />
                </label>
                <button className="actionButton" type="submit" disabled={!selectedProjectId}>
                  Import file
                </button>
              </form>
              <div className="detailBlock">
                <div className="sectionHeader">
                  <h3>Prompt Import History</h3>
                  <small>Import query {paths.promptImports}</small>
                </div>
                {data.promptImports.records.length ? (
                  <ul className="plainList">
                    {data.promptImports.records.map((record) => {
                      const item = record.prompt_import;
                      const audit = record.audit_events[0];
                      return (
                        <li key={item.id || `${item.source_format}-${item.created_at}`}>
                          <strong>
                            {item.source_format || "csv"} · {item.prompt_count || 0} prompts ·{" "}
                            {dateText(item.created_at || undefined)}
                          </strong>
                          <span>
                            {item.source_filename || "inline CSV"} · {item.source_content_type || "no content type"}
                          </span>
                          <small>
                            {audit?.event_type || "runtime_prompts_imported"} ·{" "}
                            {audit?.method_version || item.method_version || "no method version"} · hash{" "}
                            {clipText(item.csv_sha256 || item.after_hash || audit?.after_hash || "no hash", 16)}
                          </small>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="mutedText">No prompt imports recorded for this project.</p>
                )}
              </div>
              <form action={submitManualBackfill} className="manualBackfillForm">
                <input type="hidden" name="prompt_question_id" value={latestPrompt?.id || ""} />
                <div className="formHeader">
                  <h3>Manual Backfill</h3>
                  <small>{latestPrompt ? shortId(latestPrompt.id) : "no prompt"}</small>
                </div>
                <label>
                  <span>Platform</span>
                  <select name="platform" defaultValue="google">
                    <option value="google">google</option>
                    <option value="perplexity">perplexity</option>
                    <option value="chatgpt">chatgpt</option>
                  </select>
                </label>
                <label>
                  <span>Surface</span>
                  <select name="surface" defaultValue="google_ai_mode">
                    <option value="google_ai_mode">google_ai_mode</option>
                    <option value="google_aio">google_aio</option>
                    <option value="sonar">sonar</option>
                    <option value="chatgpt_search">chatgpt_search</option>
                  </select>
                </label>
                <label className="wideField">
                  <span>Answer text</span>
                  <textarea
                    name="answer_text"
                    defaultValue={`Manual backfill answer for: ${latestPrompt?.text || "selected prompt"}`}
                    rows={4}
                  />
                </label>
                <label className="wideField">
                  <span>Citation URLs</span>
                  <textarea
                    name="citation_urls"
                    defaultValue={"https://examplebrand.example/au/manual-backfill\nhttps://reviews.example/manual-backfill"}
                    rows={2}
                  />
                </label>
                <label>
                  <span>Screenshot URL</span>
                  <input name="screenshot_url" defaultValue="s3://manual-backfill/examplebrand-google-ai-mode.png" />
                </label>
                <label>
                  <span>HTML URL</span>
                  <input name="html_snapshot_url" defaultValue="s3://manual-backfill/examplebrand-google-ai-mode.html" />
                </label>
                <label className="wideField">
                  <span>Notes</span>
                  <input name="notes" defaultValue="Manual Google AI Mode backfill for auditable spike coverage" />
                </label>
                <input type="hidden" name="submitted_by" value="runtime-console" />
                <button className="actionButton" type="submit" disabled={!latestPrompt}>
                  Save backfill
                </button>
              </form>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Question Detail"
          subtitle={`${coveredQuestionCount}/${questionDetailRows.length} covered · evidence window ${data.questionEvidence.records.length}/${data.questionEvidence.total_count}`}
          wide
        >
          {questionDetailRows.length ? (
            <div className="questionDetail">
              <dl className="facts questionSummaryFacts">
                <Fact label="Coverage" value={pct(questionCoverageRate)} />
                <Fact label="Covered" value={coveredQuestionCount} />
                <Fact label="Open gaps" value={questionGapRows.length} />
                <Fact label="Evidence window" value={`${data.questionEvidence.records.length}/${data.questionEvidence.total_count}`} />
                <Fact label="Question evidence query" value={paths.questionEvidence} />
                <Fact label="Status mix" value={formatCounts(questionStatusCounts)} />
              </dl>
              <div className="questionTable" role="table" aria-label="question detail coverage matrix">
                <div className="questionTableHeader" role="row">
                  <span>Question</span>
                  <span>Coverage</span>
                  <span>Runs</span>
                  <span>Platforms</span>
                  <span>Evidence</span>
                  <span>Latest</span>
                </div>
                {questionDetailRows.map((row) => (
                  <details className="questionRow" key={row.prompt.id} open={row.status !== "covered"}>
                    <summary>
                      <span>
                        <strong>{row.prompt.priority}</strong>
                        {row.prompt.intent_type} · {row.prompt.city}
                      </span>
                      <span className={`coverageBadge coverage-${row.status}`}>{row.gapLabel}</span>
                      <span>
                        {row.runCount} runs · {row.answerCount} answers
                      </span>
                      <span>{row.platforms.length ? row.platforms.join(", ") : "none"}</span>
                      <span>
                        {row.citationCount} citations · {row.assetCount} assets
                      </span>
                      <span>{dateText(row.latestRun?.answer_run.collected_at)}</span>
                    </summary>
                    <div className="questionRowBody">
                      <p className="prompt">{row.prompt.text}</p>
                      <dl className="facts questionFacts">
                        <Fact label="Prompt ID" value={shortId(row.prompt.id)} />
                        <Fact label="Language" value={row.prompt.language} />
                        <Fact label="Target brand" value={row.prompt.target_brand} />
                        <Fact label="Competitors" value={row.prompt.competitors.length} />
                        <Fact label="Trigger rate" value={pct(row.runCount ? row.triggeredCount / row.runCount : 0)} />
                        <Fact label="Answer rate" value={pct(row.runCount ? row.answerCount / row.runCount : 0)} />
                        <Fact label="Missing platforms" value={row.missingPlatforms.length ? row.missingPlatforms.join(", ") : "none"} />
                        <Fact label="Cities observed" value={row.cities.length ? row.cities.join(", ") : "none"} />
                        <Fact label="Access methods" value={row.accessMethods.length ? row.accessMethods.join(", ") : "none"} />
                        <Fact label="Surface mix" value={formatCounts(row.surfaceCounts)} />
                        <Fact label="Run status mix" value={formatCounts(row.statusCounts)} />
                        <Fact label="Cost" value={num(row.totalCost)} />
                        <Fact label="Avg duration" value={`${row.averageDurationMs} ms`} />
                        <Fact label="Audit events" value={row.auditCount} />
                      </dl>
                      {row.evidenceRuns.length ? (
                        <ul className="plainList questionEvidenceList">
                          {row.evidenceRuns.slice(0, 4).map((run) => (
                            <li key={run.answer_run.id}>
                              <strong>
                                {run.answer_run.platform} · {run.answer_run.surface} · {shortId(run.answer_run.id)}
                              </strong>
                              <span>
                                {run.answer_run.status} · triggered {boolText(run.answer_run.surface_triggered)} · answer{" "}
                                {boolText(run.answer_run.answer_present)}
                              </span>
                              <small>
                                {run.citations.length} citations · {run.evidence_assets.length} assets · raw hash{" "}
                                {clipText(run.raw_answer?.raw_payload_hash, 18)}
                              </small>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mutedText">No evidence runs in the current question evidence window.</p>
                      )}
                    </div>
                  </details>
                ))}
              </div>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Latest Evidence" subtitle={latestEvidence?.answer_run.platform || "No runtime evidence"}>
          {latestEvidence ? (
            <div className="stack">
              <p className="prompt">{latestEvidence.answer_run.prompt_text}</p>
              <dl className="facts">
                <Fact label="Surface" value={latestEvidence.answer_run.surface} />
                <Fact label="City" value={latestEvidence.answer_run.city} />
                <Fact label="Intent" value={latestEvidence.answer_run.prompt_intent_type || "unknown"} />
                <Fact label="Citations" value={latestEvidence.citations.length} />
                <Fact label="Assets" value={latestEvidence.evidence_assets.length} />
              </dl>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Human Review Trail"
          subtitle={`${data.humanReviewQueue.total_count} queue items · ${data.humanReviews.total_count} review records`}
          wide
        >
          <div className="humanReviewGrid">
            <form action={submitHumanReview} className="humanReviewForm">
              <div className="formHeader">
                <h3>Record Review</h3>
                <small>{reviewTarget ? `${reviewTarget.targetType} · ${shortId(reviewTarget.targetId)}` : "No target"}</small>
              </div>
              <input type="hidden" name="project_id" value={selectedProjectId || ""} />
              <input type="hidden" name="target_label" value={reviewTarget?.label || ""} />
              <label>
                <span>Target type</span>
                <select name="target_type" defaultValue={reviewTarget?.targetType || "project"}>
                  <option value="visibility_score_snapshot">visibility_score_snapshot</option>
                  <option value="content_draft">content_draft</option>
                  <option value="answer_analysis">answer_analysis</option>
                  <option value="answer_run">answer_run</option>
                  <option value="score_weight_config">score_weight_config</option>
                  <option value="project">project</option>
                </select>
              </label>
              <label>
                <span>Target ID</span>
                <input name="target_id" defaultValue={reviewTarget?.targetId || selectedProjectId || ""} />
              </label>
              <label>
                <span>Status</span>
                <select name="review_status" defaultValue="approved">
                  <option value="approved">approved</option>
                  <option value="needs_changes">needs_changes</option>
                  <option value="rejected">rejected</option>
                  <option value="acknowledged">acknowledged</option>
                </select>
              </label>
              <label>
                <span>Reviewer</span>
                <input name="reviewer_id" defaultValue="runtime-console" />
              </label>
              <label className="wideField">
                <span>Decision</span>
                <input name="decision" defaultValue="approved_for_report" />
              </label>
              <label className="wideField">
                <span>Notes</span>
                <textarea
                  name="notes"
                  defaultValue={`Reviewed ${reviewTarget?.label || "runtime object"} against evidence and traceability bundle`}
                  rows={3}
                />
              </label>
              <button className="actionButton" type="submit" disabled={!selectedProjectId || !reviewTarget}>
                Record review
              </button>
            </form>
            <div className="humanReviewList">
              <h3>Review Queue</h3>
              {data.humanReviewQueue.records.length ? (
                <ul className="plainList">
                  {data.humanReviewQueue.records.map((item) => (
                    <li key={`${item.target_type}:${item.target_id}`}>
                      <strong>
                        {item.queue_status} · {item.target_type}
                      </strong>
                      <span>{item.title}</span>
                      <small>
                        priority {item.priority} · {item.reason} · {dateText(item.created_at || undefined)}
                      </small>
                      <small>
                        {item.latest_review?.decision || "no decision"} · {shortId(item.target_id)}
                      </small>
                    </li>
                  ))}
                </ul>
              ) : (
                <small>No human review queue items.</small>
              )}
              <h3>Recent Reviews</h3>
              {data.humanReviews.records.length ? (
                <ul className="plainList">
                  {data.humanReviews.records.map((item) => (
                    <li key={item.human_review.id}>
                      <strong>
                        {item.human_review.review_status} · {item.human_review.target_type}
                      </strong>
                      <span>
                        {item.human_review.decision} · {shortId(item.human_review.target_id)}
                      </span>
                      <small>
                        {item.human_review.reviewer_id} · {dateText(item.human_review.created_at)} ·{" "}
                        {item.audit_events[0]?.event_type || "no review audit"} ·{" "}
                        {item.audit_events[0]?.after_hash || "no hash"}
                      </small>
                    </li>
                  ))}
                </ul>
              ) : (
                <small>No human review records yet.</small>
              )}
              <dl className="facts">
                <Fact label="Review query" value={paths.humanReviews} />
                <Fact label="Queue query" value={paths.humanReviewQueue} />
                <Fact label="Method" value="human_review_v1" />
                <Fact label="Audit event" value="human_review_recorded" />
                <Fact label="Draft projection" value="content_draft_review_status_updated" />
              </dl>
            </div>
          </div>
        </Panel>

        <Panel title="Collection Run Quality" subtitle={latestCollectionRun?.collection_run.run_type || "No collection run"}>
          {latestCollectionRun ? (
            <div className="stack">
              <dl className="facts">
                <Fact label="Planned" value={latestCollectionRun.collection_run.planned_runs || 0} />
                <Fact label="Attempted" value={latestCollectionRun.collection_run.attempted_runs || 0} />
                <Fact label="Success" value={latestCollectionRun.collection_run.success_count || 0} />
                <Fact label="Failure" value={latestCollectionRun.collection_run.failure_count || 0} />
                <Fact label="Success rate" value={pct(latestCollectionRun.collection_run.success_rate)} />
                <Fact label="Trigger rate" value={pct(latestCollectionRun.collection_run.trigger_rate)} />
                <Fact label="Answer rate" value={pct(latestCollectionRun.collection_run.answer_present_rate)} />
                <Fact label="Total cost" value={num(latestCollectionRun.collection_run.total_cost)} />
                <Fact label="Avg cost/run" value={num(latestCollectionRun.collection_run.average_cost_per_run)} />
                <Fact label="Avg duration" value={`${latestCollectionRun.collection_run.average_duration_ms || 0} ms`} />
                <Fact label="Mode" value={latestCollectionRun.collection_run.mode || "unknown"} />
                <Fact
                  label="Platforms"
                  value={formatCounts(latestCollectionRun.collection_run.platform_distribution || {})}
                />
                <Fact
                  label="Access"
                  value={formatCounts(latestCollectionRun.collection_run.access_method_distribution || {})}
                />
                <Fact label="Audit" value={latestCollectionRun.audit_events.length} />
              </dl>
              <small className="auditLine">
                Collection run {shortId(latestCollectionRun.collection_run.id)} ·{" "}
                {dateText(latestCollectionRun.collection_run.started_at)} to{" "}
                {dateText(latestCollectionRun.collection_run.completed_at)} · total duration{" "}
                {latestCollectionRun.collection_run.total_duration_ms || 0} ms · failures{" "}
                {formatCounts(latestCollectionRun.collection_run.failure_summary || {})}
              </small>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Score Explanation" subtitle={latestScore?.snapshot.formula_version || "No score"}>
          {latestScore ? (
            <div className="stack">
              <div className="scoreRow">
                <strong>{num(latestScore.snapshot.final_score)}</strong>
                <span>Trigger {pct(latestScore.snapshot.trigger_rate)}</span>
                <span>Mention {pct(latestScore.snapshot.mention_rate)}</span>
                <span>Recommend {pct(latestScore.snapshot.recommendation_rate)}</span>
              </div>
              <ul className="compactList">
                {latestScore.contributions.slice(0, 4).map((item) => (
                  <li key={item.component_name}>
                    <span>{item.component_name}</span>
                    <strong>{num(item.weighted_contribution)}</strong>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Citation Graph" subtitle={`${latestGraph?.nodes.length || 0} nodes`}>
          {latestGraph ? (
            <div className="stack">
              <dl className="facts">
                <Fact label="Competitors" value={latestGraph.competitor_benchmarks.length} />
                <Fact label="Gaps" value={latestGraph.source_gaps.length} />
              </dl>
              <ul className="plainList">
                {latestGraph.source_gaps.slice(0, 3).map((gap) => (
                  <li key={`${gap.source_type}-${gap.gap_type}`}>
                    <strong>{gap.source_type}</strong>
                    <span>{gap.recommendation}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Report Snapshot" subtitle={latestReport?.report_export.report_version || "No report"}>
          {latestReport ? (
            <div className="stack" id={anchorId("report-export", latestReport.report_export.id)}>
              <dl className="facts">
                <Fact label="Sample size" value={latestReport.report_export.sample_size} />
                <Fact label="Evidence links" value={latestReport.answer_runs.length} />
                <Fact label="Formula" value={latestReport.report_export.scoring_formula_version || "unknown"} />
                <Fact label="Frozen MD URL" value={latestReport.report_export.markdown_url || "pending object store"} />
                <Fact label="Frozen PDF URL" value={latestReport.report_export.pdf_url || "pending object store"} />
                <Fact label="Frozen CSV URL" value={latestReport.report_export.csv_url || "pending object store"} />
              </dl>
              <div className="downloadRow">
                {reportMarkdownUrl ? <a href={reportMarkdownUrl}>Download Markdown</a> : null}
                {reportCsvUrl ? <a href={reportCsvUrl}>Download CSV</a> : null}
                {reportPdfUrl ? <a href={reportPdfUrl}>Download PDF</a> : null}
                {reportWhiteLabelPdfUrl ? <a href={reportWhiteLabelPdfUrl}>White-label PDF</a> : null}
              </div>
              <div className="traceLinkRow" aria-label="report trace links">
                <NodeLink label="Trace bundle" kind="traceability-map" value="runtime" />
                <NodeLink label="Score package" kind="score-snapshot" value={latestScore?.snapshot.id || "latest"} />
                {latestReport.answer_runs[0] ? (
                  <NodeLink label="First evidence" kind="answer-run" value={latestReport.answer_runs[0].id} />
                ) : null}
                {latestReportGraph?.nodes[0] ? (
                  <NodeLink label="First source" kind="source-node" value={latestReportGraph.nodes[0].node.id} />
                ) : null}
              </div>
              <dl className="facts">
                <Fact label="Artifact filters" value={reportCsvUrl?.replace(displayUrl, "") || "No report artifact"} />
                <Fact
                  label="White-label template"
                  value={reportWhiteLabelPdfUrl?.replace(displayUrl, "") || "No white-label artifact"}
                />
              </dl>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Report History" subtitle={`${data.reports.total_count} stored exports`} wide>
          {data.reports.records.length ? (
            <div className="reportHistory">
              {data.reports.records.map((report) => {
                const artifactBase = `${displayUrl}/v1/reports/runtime/${report.report_export.id}/artifact`;
                const markdownUrl = reportArtifactPath(artifactBase, "markdown", reportArtifactFilters);
                const csvUrl = reportArtifactPath(artifactBase, "csv", reportArtifactFilters);
                const pdfUrl = reportArtifactPath(artifactBase, "pdf", reportArtifactFilters);
                const whiteLabelPdfUrl = reportArtifactPath(artifactBase, "pdf", reportArtifactFilters, {
                  template: "white_label",
                  client_name: whiteLabelClientName,
                  prepared_by: whiteLabelPreparedBy
                });
                const scoreSnapshot = report.score_snapshots[0];
                return (
                  <article className="reportHistoryItem" key={report.report_export.id}>
                    <header>
                      <div>
                        <h3>{report.report_export.report_version}</h3>
                        <span>{dateText(report.report_export.exported_at)}</span>
                      </div>
                      <strong>{report.report_export.report_type || "report"}</strong>
                    </header>
                    <dl className="facts contributionFacts">
                      <Fact label="Report ID" value={shortId(report.report_export.id)} />
                      <Fact label="Market" value={report.report_export.market_code || "unknown"} />
                      <Fact label="Sample size" value={report.report_export.sample_size} />
                      <Fact label="Evidence links" value={report.answer_runs.length} />
                      <Fact label="Score snapshots" value={report.score_snapshots.length} />
                      <Fact label="Audit events" value={report.audit_events.length} />
                      <Fact label="Final score" value={num(scoreSnapshot?.final_score)} />
                      <Fact label="Method hash" value={shortId(report.report_export.methodology_hash)} />
                    </dl>
                    <div className="downloadRow reportHistoryDownloads">
                      {markdownUrl ? <a href={markdownUrl}>Markdown</a> : null}
                      {csvUrl ? <a href={csvUrl}>CSV</a> : null}
                      {pdfUrl ? <a href={pdfUrl}>PDF</a> : null}
                      {whiteLabelPdfUrl ? <a href={whiteLabelPdfUrl}>White-label PDF</a> : null}
                    </div>
                    <ul className="plainList">
                      <li>
                        <strong>Frozen artifact URLs</strong>
                        <span>{report.report_export.markdown_url || "markdown pending"}</span>
                        <small>
                          {report.report_export.pdf_url || "pdf pending"} · {report.report_export.csv_url || "csv pending"}
                        </small>
                      </li>
                      <li>
                        <strong>Artifact filter path</strong>
                        <span>{csvUrl?.replace(displayUrl, "") || "No artifact API path"}</span>
                        <small>
                          {filters.platform || "all platforms"} · {filters.city || "all cities"} ·{" "}
                          {filters.intent_type || "all intents"} · {evidenceSort}
                        </small>
                      </li>
                      <li>
                        <strong>White-label template</strong>
                        <span>{whiteLabelPdfUrl?.replace(displayUrl, "") || "No white-label artifact path"}</span>
                        <small>{whiteLabelClientName} · {whiteLabelPreparedBy} · template white_label</small>
                      </li>
                      <li>
                        <strong>{report.audit_events[0]?.event_type || "no report audit"}</strong>
                        <span>{report.audit_events[0]?.target_type || "report_export"}</span>
                        <small>{report.audit_events[0]?.method_version || "no method version"}</small>
                      </li>
                    </ul>
                  </article>
                );
              })}
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Report Method & Evidence Appendix"
          subtitle={latestReport?.report_export.methodology_hash || "No frozen methodology"}
          wide
        >
          {latestReport ? (
            <div className="reportDetail">
              <section className="reportSection reportMethod">
                <h3>Frozen Methodology</h3>
                <dl className="facts">
                  <Fact label="Report type" value={latestReport.report_export.report_type || "unknown"} />
                  <Fact label="Market" value={latestReport.report_export.market_code || "unknown"} />
                  <Fact label="Prompt version" value={latestReport.report_export.prompt_version || "unknown"} />
                  <Fact label="Formula version" value={latestReport.report_export.scoring_formula_version || "unknown"} />
                  <Fact label="Window start" value={dateText(latestReport.report_export.window_start)} />
                  <Fact label="Window end" value={dateText(latestReport.report_export.window_end)} />
                  <Fact label="Platforms" value={reportPlatforms} />
                  <Fact label="Access methods" value={reportAccessMethods} />
                  <Fact label="Cities" value={reportCities} />
                  <Fact label="Method hash" value={latestReport.report_export.methodology_hash || "unknown"} />
                </dl>
              </section>

              <section className="reportSection">
                <h3>Method Disclosure</h3>
                <dl className="facts">
                  <Fact label="Google coverage" value={reportGoogleCoverage} />
                  <Fact label="Google gate" value={reportGoogleGateStatus} />
                  <Fact label="Limited coverage" value={reportLimitedCoverage ? "yes" : "no"} />
                  <Fact label="API/browser fidelity" value={reportFidelityStatus} />
                  <Fact label="Trigger denominator" value={reportTriggerDenominator} />
                  <Fact label="Mention denominator" value={reportMentionDenominator} />
                  <Fact label="Recommendation denominator" value={reportRecommendationDenominator} />
                  <Fact label="Attempted records" value={reportEvidenceAttemptedRecords} />
                  <Fact label="Surface-triggered records" value={reportEvidenceTriggeredRecords} />
                  <Fact label="Evidence trigger rate" value={pct(reportEvidenceTriggerRate)} />
                  <Fact label="Official API rows" value={reportOfficialApiCount} />
                  <Fact label="Browser rows" value={reportBrowserCount} />
                  <Fact label="Comparable pairs" value={reportComparablePairs} />
                  <Fact label="Mismatch count" value={reportFidelityMismatchCount} />
                  <Fact label="Difference rate" value={reportDifferenceRate} />
                  <Fact label="Fidelity trend" value={fidelityTrend?.trend_direction || "no_data"} />
                  <Fact label="Trend samples" value={fidelityTrendSampleText} />
                  <Fact label="Trend average" value={optionalPct(fidelityTrend?.average_difference_rate)} />
                  <Fact label="Trend max" value={optionalPct(fidelityTrend?.max_difference_rate)} />
                  <Fact label="Trend window" value={fidelityTrendWindow} />
                  <Fact label="Fidelity audit" value={reportFidelityAudit} />
                  <Fact label="Fidelity query" value={paths.fidelityChecks} />
                  <Fact label="Trend query" value={paths.fidelityTrend} />
                  <Fact label="Payload hash" value={shortId(runtimeFidelity?.payload_hash)} />
                  <Fact label="Access distribution" value={formatCounts(reportFrozenAccessMethodCounts)} />
                  <Fact label="Platform distribution" value={formatCounts(reportFrozenPlatformCounts)} />
                  <Fact label="Screenshot records" value={reportScreenshotCount} />
                  <Fact label="HTML records" value={reportHtmlSnapshotCount} />
                </dl>
                <small className="auditLine">
                  Google remains outside the main scoring denominator until a stored Google AIO / AI Mode spike gate passes.
                  API-vs-browser fidelity is frozen as a runtime check and audited with api_browser_fidelity_checked.
                </small>
              </section>

              <section className="reportSection">
                <h3>Score Snapshot</h3>
                <dl className="facts">
                  <Fact label="Final score" value={num(latestReportScore?.final_score)} />
                  <Fact label="Trigger rate" value={pct(latestReportScore?.trigger_rate)} />
                  <Fact label="Mention rate" value={pct(latestReportScore?.mention_rate)} />
                  <Fact label="Recommendation" value={pct(latestReportScore?.recommendation_rate)} />
                  <Fact label="Dispersion" value={num(latestReportScore?.dispersion)} />
                  <Fact label="Snapshot formula" value={latestReportScore?.formula_version || "unknown"} />
                </dl>
                <h3>Platform Weights</h3>
                <ul className="plainList">
                  {Object.entries(reportPlatformWeights).map(([platform, weight]) => (
                    <li key={platform}>
                      <strong>{platform}</strong>
                      <span>{num(weight)}</span>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="reportSection">
                <h3>Evidence Appendix</h3>
                <ul className="plainList">
                  {latestReport.answer_runs.slice(0, 8).map((run) => (
                    <li key={run.id}>
                      <strong>
                        {run.platform || "platform"} / {run.surface || "surface"} / {run.city || "city"}
                      </strong>
                      <span>{run.prompt_text || run.id}</span>
                      <small>
                        intent {run.prompt_intent_type || "unknown"} · access {run.access_method || "unknown"} · sample{" "}
                        {run.sample_index || 0}/{run.sample_size || 0} · answer {boolText(run.answer_present)} ·
                        surface {boolText(run.surface_triggered)} · run {shortId(run.id)}
                      </small>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="reportSection">
                <h3>Citation & Audit Summary</h3>
                <dl className="facts">
                  <Fact label="Graph nodes" value={latestReportGraph?.nodes.length || 0} />
                  <Fact label="Graph links" value={latestReportGraph?.evidence_links.length || 0} />
                  <Fact label="Source gaps" value={latestReportGraph?.source_gaps.length || 0} />
                  <Fact label="Benchmarks" value={latestReportGraph?.competitor_benchmarks.length || 0} />
                  <Fact label="Audit events" value={latestReport.audit_events.length} />
                </dl>
                <ul className="plainList">
                  {latestReport.audit_events.slice(0, 5).map((event, index) => (
                    <li key={`${event.event_type}-${index}`}>
                      <strong>{event.event_type || "audit_event"}</strong>
                      <span>{event.target_type || "target"} · {event.method_version || "no method version"}</span>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Action & Retest" subtitle={latestAction?.retest_comparisons[0]?.trend || "No action plan"}>
          {latestAction ? (
            <div className="stack">
              <dl className="facts">
                <Fact label="Retest days" value={latestAction.retest_schedule.offsets_days.join("/")} />
                <Fact label="Score delta" value={num(latestAction.retest_comparisons[0]?.score_delta)} />
                <Fact label="Open actions" value={latestAction.action_recommendations.length} />
                <Fact label="Evidence runs" value={latestAction.answer_runs.length} />
              </dl>
              <ul className="plainList">
                {latestAction.action_recommendations.slice(0, 3).map((action) => (
                  <li key={action.title}>
                    <strong>{action.priority}</strong>
                    <span>{action.title}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Runtime Alerts"
          subtitle={`${data.alerts.total_count} active evidence-derived alerts`}
          wide
        >
          {data.alerts.records.length ? (
            <div className="alertGrid">
              {data.alerts.records.map((item) => (
                <article className={`alertItem ${alertTone(item.alert.severity)}`} key={item.alert.id}>
                  <header>
                    <h3>{item.alert.title}</h3>
                    <span>{item.alert.severity}</span>
                  </header>
                  <p>{item.alert.summary || "No alert summary"}</p>
                  <dl className="facts contributionFacts">
                    <Fact label="Type" value={item.alert.alert_type} />
                    <Fact label="Metric" value={item.alert.metric_name || "unknown"} />
                    <Fact label="Value" value={num(item.alert.metric_value)} />
                    <Fact label="Threshold" value={num(item.alert.threshold)} />
                    <Fact label="Source" value={item.alert.source || "derived"} />
                    <Fact label="Rule" value={item.alert.rule_version || "runtime_alerts_v1"} />
                  </dl>
                  <div className="traceLinkRow">
                    {item.evidence_refs.slice(0, 4).map((ref, index) => (
                      <NodeLink
                        key={`${item.alert.id}-${ref.target_type}-${ref.target_id}-${index}`}
                        label={ref.target_type || "Evidence"}
                        kind={ref.target_type || "evidence"}
                        value={ref.target_id || item.alert.source_id}
                      />
                    ))}
                  </div>
                  {item.related_actions.length ? (
                    <ul className="plainList compactList">
                      {item.related_actions.slice(0, 2).map((action) => (
                        <li key={action.id || action.title}>
                          <strong>{action.title || "Related action"}</strong>
                          <span>
                            {action.priority || "priority"} · {action.status || "status"} ·{" "}
                            {action.source_gap_type || "no source gap"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  <small>
                    {item.audit_events[0]?.event_type || "derived alert"} ·{" "}
                    {item.audit_events[0]?.method_version || "runtime_alerts_v1"} ·{" "}
                    {shortId(item.alert.source_id)}
                  </small>
                </article>
              ))}
              <dl className="facts">
                <Fact label="Alert query" value={paths.alerts} />
                <Fact label="Method" value="runtime_alerts_v1" />
                <Fact label="Evidence refs" value="score/source_gap/benchmark/action" />
              </dl>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Action Plan & Retest Detail"
          subtitle={latestAction?.retest_schedule.prompt_version || "No retest schedule"}
          wide
        >
          {latestAction ? (
            <div className="actionDetail">
              <section className="actionSection actionSchedule">
                <h3>Retest Schedule</h3>
                <dl className="facts">
                  <Fact label="Schedule ID" value={shortId(latestAction.retest_schedule.id)} />
                  <Fact label="Prompt version" value={latestAction.retest_schedule.prompt_version} />
                  <Fact label="Sample size" value={latestAction.retest_schedule.sample_size || 0} />
                  <Fact label="Offsets" value={latestAction.retest_schedule.offsets_days.join("/")} />
                  <Fact label="Answer runs" value={latestAction.retest_schedule.answer_run_ids?.length || 0} />
                  <Fact label="Created" value={dateText(latestAction.retest_schedule.created_at)} />
                </dl>
                <ul className="plainList">
                  {(latestAction.retest_schedule.scheduled_dates || []).map((date, index) => (
                    <li key={`${date}-${index}`}>
                      <strong>T+{latestAction.retest_schedule.offsets_days[index] ?? index}</strong>
                      <span>{dateText(date)}</span>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="actionSection">
                <h3>Action Recommendations</h3>
                <div className="actionCards">
                  {latestAction.action_recommendations.map((action) => (
                    <article
                      className="actionCard"
                      id={
                        traceability?.traceability_bundle.action_recommendation_ids.includes(action.id || "")
                          ? undefined
                          : anchorId("action", action.id || action.title)
                      }
                      key={action.id || action.title}
                    >
                      <header>
                        <h3>{action.title}</h3>
                        <span>{action.priority}</span>
                      </header>
                      <p>{action.description || "No description"}</p>
                      <dl className="facts contributionFacts">
                        <Fact label="Status" value={action.status} />
                        <Fact label="Owner" value={action.owner_id || "unassigned"} />
                        <Fact label="Source gap" value={action.source_gap_type || "none"} />
                        <Fact label="Source types" value={(action.related_source_types || []).join(", ") || "none"} />
                        <Fact label="Evidence runs" value={action.evidence_answer_run_ids?.length || 0} />
                        <Fact label="Next check" value={dateText(action.next_check_date)} />
                      </dl>
                    </article>
                  ))}
                </div>
              </section>

              <section className="actionSection">
                <h3>Retest Comparison</h3>
                <dl className="facts">
                  <Fact label="Trend" value={latestRetestComparison?.trend || "unknown"} />
                  <Fact label="Baseline score" value={num(latestRetestComparison?.baseline_score)} />
                  <Fact label="Retest score" value={num(latestRetestComparison?.retest_score)} />
                  <Fact label="Score delta" value={num(latestRetestComparison?.score_delta)} />
                  <Fact label="Baseline runs" value={latestRetestComparison?.baseline_answer_run_ids?.length || 0} />
                  <Fact label="Retest runs" value={latestRetestComparison?.retest_answer_run_ids?.length || 0} />
                  <Fact label="Compared at" value={dateText(latestRetestComparison?.created_at)} />
                </dl>
              </section>

              <section className="actionSection">
                <h3>Evidence Runs & Audit</h3>
                <ul className="plainList">
                  {latestAction.answer_runs.slice(0, 6).map((run) => (
                    <li key={run.id}>
                      <strong>
                        {run.platform || "platform"} / {run.surface || "surface"} / {run.city || "city"}
                      </strong>
                      <span>{run.prompt_text || run.id}</span>
                      <small>
                        intent {run.prompt_intent_type || "unknown"} · access {run.access_method || "unknown"} · sample{" "}
                        {run.sample_index || 0}/{run.sample_size || 0} · answer {boolText(run.answer_present)} ·
                        surface {boolText(run.surface_triggered)} · run {shortId(run.id)}
                      </small>
                    </li>
                  ))}
                </ul>
                <h3>Audit Trail</h3>
                <ul className="plainList">
                  {latestAction.audit_events.map((event, index) => (
                    <li key={`${event.event_type}-${index}`}>
                      <strong>{event.event_type || "audit_event"}</strong>
                      <span>{event.target_type || "target"} · {event.method_version || "no method version"}</span>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Content Engine" subtitle={`${latestContent?.integration_connectors.length || 0} connectors`}>
          {latestContent ? (
            <div className="stack">
              <dl className="facts">
                <Fact label="Facts" value={latestContent.knowledge_facts.length} />
                  <Fact label="Drafts" value={latestContent.content_drafts.length} />
                  <Fact label="Manual records" value={latestContent.manual_distribution_records.length} />
                </dl>
                <ul className="plainList">
                  {latestContent.content_drafts.slice(0, 3).map((item) => (
                  <li key={item.draft.title}>
                    <strong>{item.draft.review_status}</strong>
                    <span>{item.draft.title}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Content Engine Detail"
          subtitle={`${latestContent?.content_drafts.length || 0} evidence-backed drafts`}
          wide
        >
          {latestContent ? (
            <div className="contentDetail">
              <section className="contentSection">
                <h3>Localized Knowledge Facts</h3>
                <ul className="plainList">
                  {latestContent.knowledge_facts.slice(0, 8).map((fact) => (
                    <li key={fact.id} id={anchorId("knowledge-fact", fact.id)}>
                      <strong>
                        {fact.market_code || "market"} · {fact.fact_type || "fact"}
                      </strong>
                      <span>
                        {fact.subject || "subject"} {fact.predicate || "predicate"} {fact.object_value || "value"}
                      </span>
                      <small>
                        city {fact.city || "global"} · confidence {num(fact.confidence)} · status {fact.status || "unknown"} ·
                        evidence {shortId(fact.evidence_source_id || undefined)}
                      </small>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="contentSection">
                <h3>pgvector Knowledge Search</h3>
                {data.knowledgeSearch ? (
                  <div className="knowledgeSearch">
                    <dl className="facts contributionFacts">
                      <Fact label="Query" value={data.knowledgeSearch.query} />
                      <Fact label="Model" value={data.knowledgeSearch.embedding_model} />
                      <Fact label="Market" value={data.knowledgeSearch.market_code} />
                      <Fact label="City" value={data.knowledgeSearch.city || "global"} />
                      <Fact label="Matches" value={data.knowledgeSearch.total_count} />
                      <Fact label="Search API" value={paths.knowledgeSearch} />
                      <Fact
                        label="Index audit"
                        value={data.knowledgeSearch.audit_events[0]?.event_type || "no index audit"}
                      />
                    </dl>
                    <ul className="plainList">
                      {data.knowledgeSearch.records.map((item) => (
                        <li key={item.fact.id}>
                          <strong>
                            {item.fact.market_code || "market"} · {item.fact.fact_type || "fact"} · score{" "}
                            {num(item.score)}
                          </strong>
                          <span>
                            {item.fact.subject || "subject"} {item.fact.predicate || "predicate"}{" "}
                            {item.fact.object_value || "value"}
                          </span>
                          <small>
                            fallback {item.fallback_used ? "yes" : "no"} · confidence {num(item.fact.confidence)} ·
                            model {item.embedding_model}
                          </small>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <small>
                    No pgvector knowledge search results yet. Expected audit: knowledge_fact_embeddings_indexed · model
                    fixture-knowledge-embedding-v1.
                  </small>
                )}
              </section>

              <section className="contentSection">
                <h3>Integration Connectors</h3>
                <div className="connectorGrid">
                  {latestContent.integration_connectors.map((connector) => (
                    <article className="connectorItem" key={connector.provider}>
                      <header>
                        <h3>{connector.provider}</h3>
                        <span>{connector.connection_status}</span>
                      </header>
                      <dl className="facts contributionFacts">
                        <Fact label="Auth" value={connector.auth_mode || "unknown"} />
                        <Fact label="Capabilities" value={(connector.capabilities || []).join(", ") || "none"} />
                      </dl>
                    </article>
                  ))}
                </div>
              </section>

              <section className="contentSection contentDrafts">
                <h3>Content Drafts</h3>
                <div className="contentDraftGrid">
                  {latestContent.content_drafts.map((item) => (
                    <article
                      className="contentDraftCard"
                      id={
                        traceability?.traceability_bundle.content_draft_ids.includes(item.draft.id || "")
                          ? undefined
                          : anchorId("content-draft", item.draft.id || item.draft.title)
                      }
                      key={item.draft.id || item.draft.title}
                    >
                      <header>
                        <h3>{item.draft.title}</h3>
                        <span>{item.draft.review_status}</span>
                      </header>
                      <dl className="facts contributionFacts">
                        <Fact label="Template" value={item.draft.content_template_id || "unknown"} />
                        <Fact label="Type" value={item.draft.content_type || "unknown"} />
                        <Fact label="City" value={item.draft.target_city || "unknown"} />
                        <Fact label="Platform" value={item.draft.target_platform || "unknown"} />
                        <Fact label="Source type" value={item.draft.target_source_type || "unknown"} />
                        <Fact label="Source gaps" value={(item.draft.source_gap_types || []).join(", ") || "none"} />
                        <Fact label="Facts used" value={item.knowledge_facts.length} />
                        <Fact label="Evidence runs" value={item.answer_runs.length} />
                        <Fact label="Manual records" value={item.manual_distribution_records.length} />
                      </dl>
                      <div className="contentBinding">
                        <h3>Target Questions</h3>
                        <ul className="plainList">
                          {item.target_questions.slice(0, 3).map((question, index) => (
                            <li key={`${item.draft.id}-question-${index}`}>
                              <strong>{question.intent_type || "intent"}</strong>
                              <span>{question.text}</span>
                              <small>{question.city || "unknown city"}</small>
                            </li>
                          ))}
                        </ul>
                        <h3>Evidence Runs</h3>
                        <ul className="plainList">
                          {item.answer_runs.slice(0, 3).map((run) => (
                            <li key={run.id}>
                              <strong>
                                <a href={anchorHref("answer-run", run.id)}>
                                  {run.platform || "platform"} · {run.city || "city"}
                                </a>
                              </strong>
                              <span>{run.prompt_text || run.id}</span>
                              <small>
                                intent {run.prompt_intent_type || "unknown"} · run {shortId(run.id)}
                              </small>
                            </li>
                          ))}
                        </ul>
                      </div>
                      {item.action_recommendation ? (
                        <small className="auditLine">
                          Source action: {item.action_recommendation.priority || "priority"} ·{" "}
                          {item.action_recommendation.status || "status"} ·{" "}
                          {item.action_recommendation.source_gap_type || "no source gap"} ·{" "}
                          {item.action_recommendation.title || "untitled"}
                        </small>
                      ) : null}
                      {item.audit_events.length ? (
                        <small className="auditLine">
                          Draft audit: {item.audit_events[0].event_type || "audit_event"} ·{" "}
                          {item.audit_events[0].method_version || "no method version"} ·{" "}
                          {dateText(item.audit_events[0].created_at || undefined)}
                        </small>
                      ) : null}
                    </article>
                  ))}
                </div>
              </section>

              <section className="contentSection">
                <h3>Manual Distribution & Audit</h3>
                <ul className="plainList">
                  {latestContent.manual_distribution_records.map((record, index) => (
                    <li key={`${record.platform}-${index}`}>
                      <strong>
                        {record.platform || "manual"} · {record.status || "unknown"}
                      </strong>
                      <span>{record.target_url || "URL pending human review"}</span>
                      <small>{record.notes || "No notes"}</small>
                    </li>
                  ))}
                </ul>
                <h3>Audit Trail</h3>
                <ul className="plainList">
                  {latestContent.audit_events.map((event, index) => (
                    <li key={`${event.event_type}-${index}`}>
                      <strong>{event.event_type || "audit_event"}</strong>
                      <span>{event.target_type || "target"} · {event.method_version || "no method version"}</span>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Evidence Runs" subtitle={`${data.evidence.total_count} stored runs · ${evidenceSort}`} wide>
          {data.evidence.records.length ? (
            <div className="evidenceGrid">
              {data.evidence.records.map((run) => (
                <details
                  className="evidenceItem"
                  id={
                    traceability?.traceability_bundle.answer_run_ids.includes(run.answer_run.id)
                      ? undefined
                      : anchorId("answer-run", run.answer_run.id)
                  }
                  key={run.answer_run.id}
                  open
                >
                  <summary>
                    {run.answer_run.platform} · {run.answer_run.city} · {shortId(run.answer_run.id)}
                  </summary>
                  <div className="evidenceBody">
                    <p className="prompt">{run.answer_run.prompt_text || "No prompt text"}</p>
                    <dl className="facts evidenceFacts">
                      <Fact label="Intent" value={run.answer_run.prompt_intent_type || "unknown"} />
                      <Fact label="Priority" value={run.answer_run.prompt_priority || "unknown"} />
                      <Fact label="Surface" value={run.answer_run.surface} />
                      <Fact label="Access" value={run.answer_run.access_method || "unknown"} />
                      <Fact label="Device" value={run.answer_run.device || "unknown"} />
                      <Fact label="Language" value={run.answer_run.language || "unknown"} />
                      <Fact label="Answer" value={boolText(run.answer_run.answer_present)} />
                      <Fact label="Triggered" value={boolText(run.answer_run.surface_triggered)} />
                      <Fact
                        label="Sample"
                        value={`${run.answer_run.sample_index || "?"}/${run.answer_run.sample_size || "?"}`}
                      />
                      <Fact label="Collector" value={run.answer_run.collector_backend_id || "unknown"} />
                      <Fact label="Version" value={run.answer_run.collector_version || "unknown"} />
                      <Fact label="Cost" value={num(run.collection_cost?.total_cost)} />
                      <Fact label="Duration" value={`${run.collection_cost?.duration_ms || 0} ms`} />
                      <Fact label="Citations" value={run.citations.length} />
                      <Fact label="Assets" value={run.evidence_assets.length} />
                      <Fact label="Raw hash" value={run.raw_answer?.raw_payload_hash || "missing"} />
                      <Fact label="Audit" value={run.audit_events.length} />
                    </dl>
                    <div className="evidenceColumns">
                      <div>
                        <h3>Citations</h3>
                        <ul className="plainList">
                          {run.citations.slice(0, 3).map((citation, index) => (
                            <li key={`${run.answer_run.id}-citation-${index}`}>
                              <strong>{citation.domain || citation.source_type || "citation"}</strong>
                              <span>{citation.url || "No URL"}</span>
                              <small>position {citation.position || index + 1}</small>
                            </li>
                          ))}
                        </ul>
                      </div>
                      <div>
                        <h3>Assets & Audit</h3>
                        <ul className="plainList">
                          {run.evidence_assets.slice(0, 2).map((asset, index) => (
                            <li key={`${run.answer_run.id}-asset-${index}`}>
                              <strong>{asset.asset_type || "asset"}</strong>
                              <span>{asset.url || "No URL"}</span>
                              <small>{asset.content_hash || "No content hash"}</small>
                            </li>
                          ))}
                          {run.collector_logs.slice(0, 1).map((log, index) => (
                            <li key={`${run.answer_run.id}-log-${index}`}>
                              <strong>{log.event_type || "collector_log"}</strong>
                              <span>{log.collector_backend_id || run.answer_run.collector_backend_id || "unknown"}</span>
                              <small>{JSON.stringify(log.payload || {})}</small>
                            </li>
                          ))}
                          {run.audit_events.slice(0, 1).map((event, index) => (
                            <li key={`${run.answer_run.id}-audit-${index}`}>
                              <strong>{event.event_type || "audit_event"}</strong>
                              <span>{event.target_type || "answer_run"}</span>
                              <small>{event.method_version || "no method version"}</small>
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </div>
                </details>
              ))}
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Score Contributions"
          subtitle={latestScore?.snapshot.formula_version || "No score contribution package"}
          wide
        >
          {latestScore ? (
            <div className="scoreDetail" id={anchorId("score-snapshot", latestScore.snapshot.id || "latest")}>
              <div className="scoreSummary">
                <div className="scoreTotal">
                  <span>Final score</span>
                  <strong>{num(latestScore.snapshot.final_score)}</strong>
                </div>
                <dl className="facts">
                  <Fact label="Scope" value={latestScore.snapshot.scope_value || latestScore.snapshot.scope_type || "unknown"} />
                  <Fact label="Formula" value={latestScore.snapshot.formula_version} />
                  <Fact label="Trigger" value={pct(latestScore.snapshot.trigger_rate)} />
                  <Fact label="Mention" value={pct(latestScore.snapshot.mention_rate)} />
                  <Fact label="Recommend" value={pct(latestScore.snapshot.recommendation_rate)} />
                  <Fact label="Dispersion" value={num(latestScore.snapshot.dispersion)} />
                  <Fact label="Weight snapshot" value={latestScore.snapshot.component_weights_snapshot ? num(latestScoreWeightTotal) : "legacy"} />
                  <Fact label="Answer runs" value={latestScore.answer_runs.length} />
                  <Fact label="Parser agreement" value={parserAgreement(latestScore.answer_runs[0])} />
                  <Fact label="Audit events" value={latestScore.audit_events.length} />
                </dl>
              </div>
              <div className="contributionGrid">
                {latestScore.contributions.map((item) => (
                  <article
                    className="contributionItem"
                    id={anchorId("score-contribution", item.id || item.component_name)}
                    key={item.id || item.component_name}
                  >
                    <header>
                      <h3>{item.component_name}</h3>
                      <strong>{num(item.weighted_contribution)}</strong>
                    </header>
                    <dl className="facts contributionFacts">
                      <Fact label="Raw score" value={num(item.component_score)} />
                      <Fact label="Weight" value={num(item.weight)} />
                      <Fact label="Denominator" value={item.denominator || "unknown"} />
                      <Fact label="Evidence runs" value={item.evidence_answer_run_ids?.length || 0} />
                    </dl>
                    <div className="evidenceNote positiveNote">
                      <strong>Positive evidence</strong>
                      <span>{item.positive_evidence_summary || "No positive evidence summary"}</span>
                    </div>
                    <div className="evidenceNote">
                      <strong>Negative evidence</strong>
                      <span>{item.negative_evidence_summary || "No negative evidence summary"}</span>
                    </div>
                    {(item.evidence_answer_run_ids || []).length ? (
                      <div className="traceLinkRow">
                        {(item.evidence_answer_run_ids || []).slice(0, 3).map((runId) => (
                          <NodeLink key={runId} label="Evidence" kind="answer-run" value={runId} />
                        ))}
                      </div>
                    ) : null}
                    <small>{item.confidence_note || "No confidence note"}</small>
                  </article>
                ))}
              </div>
              <div className="scoreRuns">
                <h3>Linked Answer Runs</h3>
                <ul className="plainList">
                  {latestScore.answer_runs.slice(0, 6).map((run) => (
                    <li key={run.answer_run.id}>
                      <strong>
                        <a href={anchorHref("answer-run", run.answer_run.id)}>
                          {run.answer_run.platform || "platform"} · {run.answer_run.city || "city"} ·{" "}
                          {shortId(run.answer_run.id)}
                        </a>
                      </strong>
                      <span>{run.answer_run.prompt_text || "No prompt text"}</span>
                      <small>
                        {run.answer_run.prompt_intent_type || "unknown intent"} · parser{" "}
                        {run.analysis?.analysis_version || "unknown"} · confidence {num(run.analysis?.confidence)}
                        {" · "}
                        {parserComparisonText(run)}
                      </small>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Citation Graph & Competitors"
          subtitle={`${latestGraph?.nodes.length || 0} sources · ${latestGraph?.competitor_benchmarks.length || 0} competitors`}
          wide
        >
          {latestGraph ? (
            <div className="graphDetail">
              <CitationGraphMap graph={latestGraph} />
              <div className="graphColumns">
                <section className="graphSection">
                  <h3>Source Nodes</h3>
                  <ul className="plainList">
                    {latestGraph.nodes.slice(0, 8).map((item) => (
                      <li id={anchorId("source-node", item.node.id)} key={item.node.id}>
                        <strong>
                          {item.node.source_domain || "source"} · {item.node.source_type || "unknown"}
                        </strong>
                        <span>{item.node.source_url || "No source URL"}</span>
                        <small>
                          topic {item.node.topic || "unknown"} · citations {item.node.citation_count || 0} · runs{" "}
                          {item.answer_runs.length}
                        </small>
                        {item.answer_runs.length ? (
                          <div className="traceLinkRow">
                            {item.answer_runs.slice(0, 3).map((run) => (
                              <NodeLink key={run.id} label="Run" kind="answer-run" value={run.id} />
                            ))}
                          </div>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </section>
                <section className="graphSection">
                  <h3>Source Gaps</h3>
                  <ul className="plainList">
                    {latestGraph.source_gaps.map((gap) => (
                      <li key={`${gap.source_type}-${gap.gap_type}`}>
                        <strong>
                          {gap.source_type} · {gap.gap_type}
                        </strong>
                        <span>{gap.recommendation}</span>
                        <small>
                          observed {gap.observed_count || 0} · expected weight {num(gap.expected_weight)}
                        </small>
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
              <div className="graphColumns">
                <section className="graphSection">
                  <h3>Competitor Benchmarks</h3>
                  <div className="benchmarkGrid">
                    {latestGraph.competitor_benchmarks.map((benchmark) => (
                      <article className="benchmarkItem" key={benchmark.competitor_name}>
                        <header>
                          <h3>{benchmark.competitor_name}</h3>
                          <span>{benchmark.metric_scope || "project"}</span>
                        </header>
                        <dl className="facts contributionFacts">
                          <Fact label="Mentions" value={benchmark.payload?.mention_count || 0} />
                          <Fact label="Mention rate" value={pct(benchmark.payload?.mention_rate)} />
                          <Fact label="Recs" value={benchmark.payload?.recommendation_count || 0} />
                          <Fact label="Overlap" value={benchmark.payload?.citation_overlap_count || 0} />
                          <Fact label="Local avg" value={num(benchmark.payload?.local_relevance_average)} />
                          <Fact label="Runs" value={benchmark.answer_run_ids?.length || 0} />
                        </dl>
                      </article>
                    ))}
                  </div>
                </section>
                <section className="graphSection">
                  <h3>Graph Evidence Links</h3>
                  <ul className="plainList">
                    {latestGraph.evidence_links.slice(0, 8).map((link, index) => (
                      <li key={`${link.source_graph_id}-${link.answer_run_id}-${index}`}>
                        <strong>{link.relation_type || "graph_evidence"}</strong>
                        <span className="inlineLinks">
                          <NodeLink label="Source" kind="source-node" value={link.source_graph_id} />
                          <NodeLink label="Run" kind="answer-run" value={link.answer_run_id} />
                        </span>
                        <small>citation {shortId(link.answer_citation_id || undefined)}</small>
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Traceability Detail"
          subtitle={traceability?.report_exports[0]?.report_version || "No traceability bundle"}
          wide
        >
          {traceability ? (
            <div className="traceGrid">
              <div className="traceSummary">
                <p className="prompt">{traceability.traceability_bundle.explanation_summary}</p>
                <dl className="facts">
                  <Fact label="Reports" value={traceability.traceability_bundle.report_export_ids.length} />
                  <Fact label="Score snapshots" value={traceability.traceability_bundle.score_snapshot_ids.length} />
                  <Fact label="Score parts" value={traceability.traceability_bundle.score_contribution_ids.length} />
                  <Fact label="Answer runs" value={traceability.traceability_bundle.answer_run_ids.length} />
                  <Fact label="Raw answers" value={traceability.traceability_bundle.raw_answer_ids.length} />
                  <Fact label="Citations" value={traceability.traceability_bundle.answer_citation_ids.length} />
                  <Fact label="Assets" value={traceability.traceability_bundle.evidence_asset_ids.length} />
                  <Fact label="Graph nodes" value={traceability.traceability_bundle.source_graph_ids.length} />
                  <Fact label="Actions" value={traceability.traceability_bundle.action_recommendation_ids.length} />
                  <Fact label="Drafts" value={traceability.traceability_bundle.content_draft_ids.length} />
                </dl>
              </div>
              <TraceabilityMap
                graph={latestGraph}
                report={latestReport}
                score={latestScore}
                traceability={traceability}
              />
              <div className="traceColumn">
                <h3>Evidence Links</h3>
                <ul className="plainList">
                  {traceability.evidence_links.slice(0, 5).map((link, index) => (
                    <li key={`${link.relation_type}-${index}`}>
                      <strong>{link.relation_type}</strong>
                      <span>
                        {link.source_type} to {link.target_type} · {link.answer_run_ids.length} answer runs
                      </span>
                      <div className="traceLinkRow">
                        {link.answer_run_ids.slice(0, 3).map((runId) => (
                          <NodeLink key={runId} label="Run" kind="answer-run" value={runId} />
                        ))}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="traceColumn">
                <h3>Audit Trail</h3>
                <ul className="plainList">
                  {traceability.audit_events.slice(0, 5).map((event, index) => (
                    <li key={`${event.event_type}-${index}`}>
                      <strong>{event.event_type}</strong>
                      <span>
                        {event.target_type} · {event.method_version || "no method version"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="traceDrilldown">
                <h3>Node Drilldown</h3>
                <div className="detailGrid">
                  <details open>
                    <summary>Score Components</summary>
                    <ul className="nodeList">
                      {traceability.score_snapshots[0]?.contributions.map((item) => (
                        <li key={item.component_name}>
                          <strong>{item.component_name}</strong>
                          <span>
                            {num(item.weighted_contribution)} weighted · denominator {item.denominator || "unknown"}
                          </span>
                          <small>{item.positive_evidence_summary || "No positive evidence summary"}</small>
                        </li>
                      ))}
                    </ul>
                  </details>
                  <details open>
                    <summary>Answer Evidence</summary>
                    <ul className="nodeList">
                      {traceability.evidence_runs.slice(0, 4).map((run) => (
                        <li id={anchorId("answer-run", run.answer_run.id)} key={run.answer_run.id}>
                          <strong>
                            {run.answer_run.platform} · {run.answer_run.city} · {shortId(run.answer_run.id)}
                          </strong>
                          <span>{run.answer_run.prompt_text || "No prompt text"}</span>
                          <small>
                            {run.citations.length} citations · {run.evidence_assets.length} assets · raw_payload_hash{" "}
                            {run.raw_answer?.raw_payload_hash || "missing"}
                          </small>
                        </li>
                      ))}
                    </ul>
                  </details>
                  <details>
                    <summary>Citation & Asset Nodes</summary>
                    <ul className="nodeList">
                      {traceability.evidence_runs.slice(0, 3).flatMap((run) =>
                        [
                          ...run.citations.slice(0, 2).map((citation, index) => ({
                            key: `${run.answer_run.id}-citation-${index}`,
                            title: citation.domain || citation.url || "citation",
                            body: citation.url || "No URL",
                            meta: `${citation.source_type || "unknown source"} · position ${citation.position || index + 1}`
                          })),
                          ...run.evidence_assets.slice(0, 1).map((asset, index) => ({
                            key: `${run.answer_run.id}-asset-${index}`,
                            title: asset.asset_type || "asset",
                            body: asset.url || "No asset URL",
                            meta: asset.content_hash || "No content hash"
                          }))
                        ].map((item) => (
                          <li key={item.key}>
                            <strong>{item.title}</strong>
                            <span>{item.body}</span>
                            <small>{item.meta}</small>
                          </li>
                        ))
                      )}
                    </ul>
                  </details>
                  <details>
                    <summary>Actions & Content Drafts</summary>
                    <ul className="nodeList">
                      {traceability.action_recommendations.slice(0, 4).map((action) => (
                        <li id={anchorId("action", action.id || action.title)} key={action.id || action.title}>
                          <strong>{action.priority}</strong>
                          <span>{action.title}</span>
                          <small>
                            {action.status} · {action.source_gap_type || "no source gap"}
                          </small>
                        </li>
                      ))}
                      {traceability.content_drafts.slice(0, 4).map((item) => (
                        <li id={anchorId("content-draft", item.draft.id || item.draft.title)} key={item.draft.id || item.draft.title}>
                          <strong>{item.draft.review_status}</strong>
                          <span>{item.draft.title}</span>
                          <small>
                            {item.draft.target_city || "no city"} · {item.draft.target_platform || "no platform"}
                          </small>
                        </li>
                      ))}
                    </ul>
                  </details>
                  <details>
                    <summary>Audit Event Nodes</summary>
                    <ul className="nodeList">
                      {traceability.audit_events.map((event, index) => (
                        <li key={`${event.event_type}-${index}`}>
                          <strong>{event.event_type}</strong>
                          <span>{event.target_type}</span>
                          <small>{event.method_version || "no method version"}</small>
                        </li>
                      ))}
                    </ul>
                  </details>
                </div>
              </div>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <article className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function Panel({
  title,
  subtitle,
  children,
  wide = false
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <article className={wide ? "panel panelWide" : "panel"}>
      <header className="panelHeader">
        <h2>{title}</h2>
        <span>{subtitle}</span>
      </header>
      {children}
    </article>
  );
}

function NodeLink({ label, kind, value }: { label: string; kind: string; value: string | undefined }) {
  return (
    <a className="nodeLink" href={anchorHref(kind, value)} title={`${label}: ${value || "unknown"}`}>
      {label} {shortId(value)}
    </a>
  );
}

function CitationGraphMap({ graph }: { graph: CitationGraph }) {
  const nodes = graph.nodes.slice(0, 5);
  const runIds = Array.from(
    new Set(
      nodes
        .flatMap((item) => item.answer_runs.map((run) => run.id))
        .concat(graph.evidence_links.map((link) => link.answer_run_id || ""))
        .filter(Boolean)
    )
  ).slice(0, 5);
  const nodePositions = nodes.map((item, index) => ({
    item,
    x: 140 + index * 150,
    y: index % 2 === 0 ? 88 : 158
  }));
  const runPositions = runIds.map((runId, index) => ({
    runId,
    x: 120 + index * 150,
    y: 280
  }));
  return (
    <section className="graphSection graphMapPanel" aria-label="citation graph map">
      <div className="sectionHeader">
        <h3>Citation Graph Map</h3>
        <span>
          {nodes.length} sources · {runIds.length} runs · {graph.evidence_links.length} links
        </span>
      </div>
      <div className="graphCanvas">
        <svg viewBox="0 0 820 360" role="img" aria-label="Source nodes linked to answer runs">
          <line x1="50" y1="34" x2="770" y2="34" className="graphRail" />
          <text x="50" y="22" className="graphLabel">
            Source nodes
          </text>
          <text x="50" y="340" className="graphLabel">
            Answer runs
          </text>
          {graph.evidence_links.slice(0, 12).map((link, index) => {
            const sourceIndex = nodePositions.findIndex((node) => node.item.node.id === link.source_graph_id);
            const runIndex = runPositions.findIndex((run) => run.runId === link.answer_run_id);
            if (sourceIndex < 0 || runIndex < 0) return null;
            const source = nodePositions[sourceIndex];
            const run = runPositions[runIndex];
            return (
              <line
                className="graphEdge"
                key={`${link.source_graph_id}-${link.answer_run_id}-${index}`}
                x1={source.x}
                y1={source.y + 24}
                x2={run.x}
                y2={run.y - 24}
              />
            );
          })}
          {nodePositions.map(({ item, x, y }) => (
            <a href={anchorHref("source-node", item.node.id)} key={item.node.id}>
              <circle className="graphSourceNode" cx={x} cy={y} r="24" />
              <text className="graphNodeText" x={x} y={y - 34} textAnchor="middle">
                {clipText(item.node.source_domain || item.node.source_type || "source", 18)}
              </text>
              <text className="graphNodeMeta" x={x} y={y + 5} textAnchor="middle">
                {item.node.citation_count || 0}
              </text>
            </a>
          ))}
          {runPositions.map(({ runId, x, y }) => (
            <a href={anchorHref("answer-run", runId)} key={runId}>
              <rect className="graphRunNode" height="42" rx="6" width="104" x={x - 52} y={y - 21} />
              <text className="graphRunText" x={x} y={y + 4} textAnchor="middle">
                {shortId(runId)}
              </text>
            </a>
          ))}
        </svg>
      </div>
    </section>
  );
}

function TraceabilityMap({
  graph,
  report,
  score,
  traceability
}: {
  graph: CitationGraph | undefined;
  report: ReportExport | undefined;
  score: ScoreSnapshot | undefined;
  traceability: TraceabilityDetail;
}) {
  const firstRunId = traceability.traceability_bundle.answer_run_ids[0] || report?.answer_runs[0]?.id;
  const firstSourceId = graph?.nodes[0]?.node.id || traceability.traceability_bundle.source_graph_ids[0];
  const firstActionId =
    traceability.traceability_bundle.action_recommendation_ids[0] || traceability.action_recommendations[0]?.id;
  const firstDraftId = traceability.traceability_bundle.content_draft_ids[0] || traceability.content_drafts[0]?.draft.id;
  const nodes = [
    {
      label: "Report",
      kind: "report-export",
      value: report?.report_export.id || traceability.traceability_bundle.report_export_ids[0],
      x: 80,
      y: 58
    },
    {
      label: "Score",
      kind: "score-snapshot",
      value: score?.snapshot.id || traceability.traceability_bundle.score_snapshot_ids[0] || "latest",
      x: 250,
      y: 58
    },
    { label: "Evidence", kind: "answer-run", value: firstRunId, x: 420, y: 58 },
    { label: "Source", kind: "source-node", value: firstSourceId, x: 590, y: 58 },
    { label: "Action", kind: "action", value: firstActionId, x: 250, y: 166 },
    { label: "Draft", kind: "content-draft", value: firstDraftId, x: 420, y: 166 }
  ];
  return (
    <section className="traceMap" id={anchorId("traceability-map", "runtime")}>
      <div className="sectionHeader">
        <h3>Traceability Map</h3>
        <span>report to score to evidence to source</span>
      </div>
      <div className="traceMapCanvas">
        <svg viewBox="0 0 700 230" role="img" aria-label="Runtime traceability map">
          <path className="traceEdge" d="M128 58 H202" />
          <path className="traceEdge" d="M298 58 H372" />
          <path className="traceEdge" d="M468 58 H542" />
          <path className="traceEdge" d="M420 90 C420 128 330 128 250 142" />
          <path className="traceEdge" d="M420 90 V136" />
          {nodes.map((node) => (
            <a href={anchorHref(node.kind, node.value)} key={`${node.kind}-${node.value}`}>
              <rect className="traceNode" height="52" rx="7" width="96" x={node.x - 48} y={node.y - 26} />
              <text className="traceNodeLabel" x={node.x} y={node.y - 4} textAnchor="middle">
                {node.label}
              </text>
              <text className="traceNodeMeta" x={node.x} y={node.y + 15} textAnchor="middle">
                {shortId(node.value)}
              </text>
            </a>
          ))}
        </svg>
      </div>
      <div className="traceLinkRow">
        <NodeLink label="Report" kind="report-export" value={report?.report_export.id} />
        <NodeLink label="Score" kind="score-snapshot" value={score?.snapshot.id || "latest"} />
        <NodeLink label="Evidence" kind="answer-run" value={firstRunId} />
        <NodeLink label="Source" kind="source-node" value={firstSourceId} />
      </div>
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string | number }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function EmptyState() {
  return <p className="empty">Run the collector worker to populate runtime data.</p>;
}
