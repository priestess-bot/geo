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
  brand: { canonical_name: string; official_domains?: string[]; status?: string } | null;
  competitors: Array<{ canonical_name: string; official_domains?: string[]; status?: string }>;
  prompt_count: number;
  audit_events: Array<{ event_type: string; method_version?: string | null }>;
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
  collection_cost?: { total_cost?: number; llm_provider?: string; llm_tokens?: number } | null;
  audit_events: Array<{ event_type?: string; method_version?: string | null; target_type?: string }>;
};

type ScoreSnapshot = {
  snapshot: {
    final_score: number;
    trigger_rate: number;
    mention_rate: number;
    recommendation_rate: number;
    dispersion?: number;
    scope_type?: string;
    scope_value?: string;
    formula_version: string;
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
    analysis?: { confidence?: number; payload?: Record<string, unknown> } | null;
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
  report_exports: Array<{ report_version: string }>;
  score_snapshots: ScoreSnapshot[];
  evidence_runs: EvidenceRun[];
  action_recommendations: Array<{
    title: string;
    priority: string;
    status: string;
    source_gap_type?: string | null;
  }>;
  content_drafts: Array<{
    draft: { title: string; review_status: string; target_city?: string; target_platform?: string };
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
  prompts: PageResponse<RuntimePrompt>;
  evidence: PageResponse<EvidenceRun>;
  scores: PageResponse<ScoreSnapshot>;
  graphs: PageResponse<CitationGraph>;
  reports: PageResponse<ReportExport>;
  actions: PageResponse<ActionPlan>;
  content: PageResponse<ContentEngine>;
  traceability: TraceabilityDetail | null;
};

type RuntimeFilters = {
  platform?: string;
  city?: string;
  intent_type?: string;
  sort?: string;
};

const endpoints = {
  projects: "/v1/projects/runtime",
  prompts: "/v1/prompts/runtime",
  evidence: "/v1/evidence-runs/runtime",
  evidenceExport: "/v1/evidence-runs/runtime/export.csv",
  scores: "/v1/visibility-scores/runtime",
  graphs: "/v1/citation-graphs/runtime",
  reports: "/v1/reports/runtime",
  actions: "/v1/action-plans/runtime",
  content: "/v1/content-engines/runtime",
  traceability: "/v1/traceability/runtime"
} as const;

const emptyPage = <T,>(): PageResponse<T> => ({ total_count: 0, records: [] });

export const dynamic = "force-dynamic";

async function createAuRuntimeProject() {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const response = await fetch(`${baseUrl}/v1/projects/runtime/au/dtc-ecommerce`, {
    method: "POST",
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/projects/runtime/au/dtc-ecommerce returned ${response.status}`);
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

async function fetchRuntimeData(filters: RuntimeFilters = {}): Promise<{
  data: RuntimeData;
  error: string | null;
  fetchUrl: string;
  displayUrl: string;
  paths: Record<keyof typeof endpoints, string>;
}> {
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const displayUrl = process.env.NEXT_PUBLIC_API_BASE_URL || baseUrl;
  const sharedProjectParams = { market_code: "AU", limit: 1 };
  const paths = {
    projects: runtimePath(endpoints.projects, sharedProjectParams),
    prompts: runtimePath(endpoints.prompts, {
      market_code: "AU",
      intent_type: filters.intent_type,
      limit: 20
    }),
    evidence: runtimePath(endpoints.evidence, {
      platform: filters.platform,
      city: filters.city,
      intent_type: filters.intent_type,
      sort: filters.sort,
      limit: 5
    }),
    evidenceExport: runtimePath(endpoints.evidenceExport, {
      platform: filters.platform,
      city: filters.city,
      intent_type: filters.intent_type,
      sort: filters.sort,
      limit: 200
    }),
    scores: runtimePath(endpoints.scores, { limit: 1 }),
    graphs: runtimePath(endpoints.graphs, { limit: 1 }),
    reports: runtimePath(endpoints.reports, { limit: 1 }),
    actions: runtimePath(endpoints.actions, { limit: 1 }),
    content: runtimePath(endpoints.content, { limit: 1 }),
    traceability: endpoints.traceability
  };

  const [projects, prompts, evidence, scores, graphs, reports, actions, content, traceability] = await Promise.all([
    fetchRuntimeEndpoint<PageResponse<RuntimeProject>>(baseUrl, paths.projects, emptyPage<RuntimeProject>()),
    fetchRuntimeEndpoint<PageResponse<RuntimePrompt>>(baseUrl, paths.prompts, emptyPage<RuntimePrompt>()),
    fetchRuntimeEndpoint<PageResponse<EvidenceRun>>(baseUrl, paths.evidence, emptyPage<EvidenceRun>()),
    fetchRuntimeEndpoint<PageResponse<ScoreSnapshot>>(baseUrl, paths.scores, emptyPage<ScoreSnapshot>()),
    fetchRuntimeEndpoint<PageResponse<CitationGraph>>(baseUrl, paths.graphs, emptyPage<CitationGraph>()),
    fetchRuntimeEndpoint<PageResponse<ReportExport>>(baseUrl, paths.reports, emptyPage<ReportExport>()),
    fetchRuntimeEndpoint<PageResponse<ActionPlan>>(baseUrl, paths.actions, emptyPage<ActionPlan>()),
    fetchRuntimeEndpoint<PageResponse<ContentEngine>>(baseUrl, paths.content, emptyPage<ContentEngine>()),
    fetchRuntimeEndpoint<TraceabilityDetail | null>(baseUrl, paths.traceability, null, { optionalNotFound: true })
  ]);
  const errors = [projects, prompts, evidence, scores, graphs, reports, actions, content, traceability]
    .map((result) => result.error)
    .filter((item): item is string => Boolean(item));
  return {
    data: {
      projects: projects.payload,
      prompts: prompts.payload,
      evidence: evidence.payload,
      scores: scores.payload,
      graphs: graphs.payload,
      reports: reports.payload,
      actions: actions.payload,
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

function num(value: number | undefined): string {
  return Number(value || 0).toFixed(2);
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

export default async function Home({
  searchParams
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const resolvedSearchParams = (await searchParams) || {};
  const filters: RuntimeFilters = {
    platform: cleanFilter(resolvedSearchParams.platform),
    city: cleanFilter(resolvedSearchParams.city),
    intent_type: cleanFilter(resolvedSearchParams.intent_type),
    sort: cleanFilter(resolvedSearchParams.sort)
  };
  const { data, error, displayUrl, paths } = await fetchRuntimeData(filters);
  const latestProject = data.projects.records[0];
  const latestPrompt = data.prompts.records[0];
  const latestEvidence = data.evidence.records[0];
  const latestScore = data.scores.records[0];
  const latestGraph = data.graphs.records[0];
  const latestReport = data.reports.records[0];
  const latestAction = data.actions.records[0];
  const latestContent = data.content.records[0];
  const traceability = data.traceability;
  const reportArtifactBase = latestReport
    ? `${displayUrl}/v1/reports/runtime/${latestReport.report_export.id}/artifact`
    : null;
  const totalAuditEvents =
    (latestEvidence?.audit_events.length || 0) +
    (latestScore?.audit_events.length || 0) +
    (latestReport?.audit_events.length || 0) +
    (latestAction?.audit_events.length || 0) +
    (latestContent?.audit_events.length || 0) +
    (traceability?.audit_events.length || 0);
  const promptIntentCount = new Set(data.prompts.records.map((prompt) => prompt.intent_type)).size;
  const promptCityCount = new Set(data.prompts.records.map((prompt) => prompt.city)).size;
  const latestReportScore = latestReport?.score_snapshots[0];
  const latestReportGraph = latestReport?.citation_graph;
  const reportPlatformWeights = latestReport?.report_export.platform_weights_snapshot || {};
  const reportPlatforms = latestReport ? uniqueText(latestReport.answer_runs.map((run) => run.platform)) : "unknown";
  const reportAccessMethods = latestReport
    ? uniqueText(latestReport.answer_runs.map((run) => run.access_method))
    : "unknown";
  const reportCities = latestReport ? uniqueText(latestReport.answer_runs.map((run) => run.city)) : "unknown";
  const latestRetestComparison = latestAction?.retest_comparisons[0];
  const activeFilterCount = [filters.platform, filters.city, filters.intent_type].filter(Boolean).length;
  const filterLabel = activeFilterCount
    ? [filters.platform, filters.city, filters.intent_type].filter(Boolean).join(" / ")
    : "All runtime evidence";
  const evidenceExportUrl = `${displayUrl}${paths.evidenceExport}`;
  const evidenceSort = data.evidence.sort || filters.sort || "collected_at_desc";

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
          <span>{filterLabel}</span>
        </div>
        <form className="filterForm">
          <label>
            <span>Platform</span>
            <select name="platform" defaultValue={filters.platform || ""}>
              <option value="">All platforms</option>
              <option value="chatgpt">chatgpt</option>
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
          <Fact label="Prompts query" value={paths.prompts} />
          <Fact label="Evidence query" value={paths.evidence} />
          <Fact label="Export query" value={paths.evidenceExport} />
          <Fact label="Evidence sort" value={evidenceSort} />
        </dl>
      </section>

      <section className="metrics" aria-label="runtime metrics">
        <Metric label="Projects" value={data.projects.total_count} />
        <Metric label="Prompts" value={data.prompts.total_count} />
        <Metric label="Evidence runs" value={data.evidence.total_count} />
        <Metric label="Final score" value={num(latestScore?.snapshot.final_score)} />
        <Metric label="Source gaps" value={latestGraph?.source_gaps.length || 0} />
        <Metric label="Open actions" value={latestAction?.action_recommendations.length || 0} />
        <Metric label="Content drafts" value={latestContent?.content_drafts.length || 0} />
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
              </>
            ) : (
              <EmptyState />
            )}
            <form action={createAuRuntimeProject}>
              <button className="actionButton" type="submit">
                Create AU project
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
            <div className="stack">
              <dl className="facts">
                <Fact label="Sample size" value={latestReport.report_export.sample_size} />
                <Fact label="Evidence links" value={latestReport.answer_runs.length} />
                <Fact label="Formula" value={latestReport.report_export.scoring_formula_version || "unknown"} />
                <Fact label="Frozen MD URL" value={latestReport.report_export.markdown_url || "pending object store"} />
                <Fact label="Frozen PDF URL" value={latestReport.report_export.pdf_url || "pending object store"} />
                <Fact label="Frozen CSV URL" value={latestReport.report_export.csv_url || "pending object store"} />
              </dl>
              <div className="downloadRow">
                <a href={`${reportArtifactBase}?type=markdown`}>Download Markdown</a>
                <a href={`${reportArtifactBase}?type=csv`}>Download CSV</a>
                <a href={`${reportArtifactBase}?type=pdf`}>Download PDF</a>
              </div>
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
                    <article className="actionCard" key={action.id || action.title}>
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
                    <li key={fact.id}>
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
                    <article className="contentDraftCard" key={item.draft.id || item.draft.title}>
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
                                {run.platform || "platform"} · {run.city || "city"}
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
                <details className="evidenceItem" key={run.answer_run.id} open>
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
            <div className="scoreDetail">
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
                  <Fact label="Answer runs" value={latestScore.answer_runs.length} />
                  <Fact label="Audit events" value={latestScore.audit_events.length} />
                </dl>
              </div>
              <div className="contributionGrid">
                {latestScore.contributions.map((item) => (
                  <article className="contributionItem" key={item.id || item.component_name}>
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
                        {run.answer_run.platform || "platform"} · {run.answer_run.city || "city"} ·{" "}
                        {shortId(run.answer_run.id)}
                      </strong>
                      <span>{run.answer_run.prompt_text || "No prompt text"}</span>
                      <small>
                        {run.answer_run.prompt_intent_type || "unknown intent"} · parser confidence{" "}
                        {num(run.analysis?.confidence)}
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
              <div className="graphColumns">
                <section className="graphSection">
                  <h3>Source Nodes</h3>
                  <ul className="plainList">
                    {latestGraph.nodes.slice(0, 8).map((item) => (
                      <li key={item.node.id}>
                        <strong>
                          {item.node.source_domain || "source"} · {item.node.source_type || "unknown"}
                        </strong>
                        <span>{item.node.source_url || "No source URL"}</span>
                        <small>
                          topic {item.node.topic || "unknown"} · citations {item.node.citation_count || 0} · runs{" "}
                          {item.answer_runs.length}
                        </small>
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
                        <span>
                          source {shortId(link.source_graph_id)} · run {shortId(link.answer_run_id)}
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
              <div className="traceColumn">
                <h3>Evidence Links</h3>
                <ul className="plainList">
                  {traceability.evidence_links.slice(0, 5).map((link, index) => (
                    <li key={`${link.relation_type}-${index}`}>
                      <strong>{link.relation_type}</strong>
                      <span>
                        {link.source_type} to {link.target_type} · {link.answer_run_ids.length} answer runs
                      </span>
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
                        <li key={run.answer_run.id}>
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
                        <li key={action.title}>
                          <strong>{action.priority}</strong>
                          <span>{action.title}</span>
                          <small>
                            {action.status} · {action.source_gap_type || "no source gap"}
                          </small>
                        </li>
                      ))}
                      {traceability.content_drafts.slice(0, 4).map((item) => (
                        <li key={item.draft.title}>
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
