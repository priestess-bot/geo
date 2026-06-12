type PageResponse<T> = {
  total_count: number;
  records: T[];
};

type RuntimeProject = {
  project: {
    id: string;
    name: string;
    market_code: string;
    target_brand: string;
  };
  tenant: { name: string };
};

type EvidenceRun = {
  answer_run: {
    id: string;
    platform?: string;
    surface?: string;
    access_method?: string;
    city?: string;
    status?: string;
    prompt_text?: string;
    collected_at?: string;
  };
  raw_answer?: {
    answer_text?: string;
    raw_payload_hash?: string;
  } | null;
  citations: Array<{ domain?: string; url?: string; source_type?: string; position?: number }>;
  evidence_assets: Array<{ asset_type?: string; url?: string; content_hash?: string | null }>;
  audit_events: Array<{ event_type?: string; method_version?: string | null; target_type?: string }>;
};

type ScoreSnapshot = {
  snapshot: {
    id?: string;
    final_score: number;
    trigger_rate: number;
    mention_rate: number;
    recommendation_rate: number;
    formula_version: string;
  };
  contributions: Array<{
    id?: string;
    component_name: string;
    weighted_contribution: number;
    denominator?: string;
    positive_evidence_summary?: string;
    negative_evidence_summary?: string;
    evidence_answer_run_ids?: string[];
  }>;
};

type CitationGraph = {
  nodes: Array<{
    node: {
      id: string;
      source_url?: string;
      source_domain?: string;
      source_type?: string;
      topic?: string | null;
      source_gap_type?: string | null;
      citation_count?: number;
    };
    answer_runs: Array<{ id: string; platform?: string; city?: string; prompt_text?: string }>;
  }>;
  evidence_links: Array<{
    source_graph_id?: string;
    answer_run_id?: string;
    relation_type?: string;
  }>;
  source_gaps: Array<{ gap_type: string; source_type: string; recommendation: string }>;
  competitor_benchmarks: Array<{
    competitor_name: string;
    metric_scope?: string;
    answer_run_ids?: string[];
  }>;
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

type FixtureTraceability = {
  traceability_bundle: TraceabilityDetail["traceability_bundle"] & { project_id?: string };
  report_export?: { id?: string; report_version?: string };
  score_contribution_count?: number;
  answer_run_count?: number;
};

type FixtureCitationGraph = {
  nodes: Array<{
    id: string;
    source_url?: string;
    source_domain?: string;
    source_type?: string;
    topic?: string | null;
    source_gap_type?: string | null;
    answer_run_ids?: string[];
    citation_count?: number;
  }>;
  source_gaps: CitationGraph["source_gaps"];
  competitor_benchmarks: CitationGraph["competitor_benchmarks"];
};

const endpoints = {
  projects: "/v1/projects/runtime",
  traceability: "/v1/traceability/runtime",
  graphs: "/v1/citation-graphs/runtime",
  fixtureTraceability: "/v1/traceability/au/p0a-fixture",
  fixtureGraph: "/v1/citation-graphs/au/p0a-fixture"
} as const;

const emptyPage = <T,>(): PageResponse<T> => ({ total_count: 0, records: [] });

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

function buildQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}

function runtimePath(path: string, params: Record<string, string | number | undefined>): string {
  return `${path}${buildQuery(params)}`;
}

function cleanFilter(value: string | string[] | undefined): string | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  const trimmed = raw?.trim();
  return trimmed || undefined;
}

function anchorId(kind: string, value: string | undefined): string {
  const raw = value || "unknown";
  return `${kind}-${raw.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function anchorHref(kind: string, value: string | undefined): string {
  return `#${anchorId(kind, value)}`;
}

function shortId(value: string | undefined): string {
  return value ? value.slice(0, 12) : "unknown";
}

function num(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "n/a";
  return Number(value).toFixed(2);
}

function clipText(value: string | undefined, maxLength: number): string {
  const text = value || "unknown";
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}...` : text;
}

function normalizeFixtureTraceability(payload: FixtureTraceability): TraceabilityDetail {
  return {
    traceability_bundle: payload.traceability_bundle,
    report_exports: payload.report_export
      ? [
          {
            id: payload.report_export.id,
            report_version: payload.report_export.report_version || "p0a-fixture-v1"
          }
        ]
      : [],
    score_snapshots: [],
    evidence_runs: [],
    action_recommendations: [],
    content_drafts: [],
    audit_events: [],
    evidence_links: [
      {
        source_type: "fixture_traceability_bundle",
        target_type: "answer_run",
        relation_type: "fixture_bundle_membership",
        answer_run_ids: payload.traceability_bundle.answer_run_ids
      }
    ]
  };
}

function normalizeFixtureGraph(payload: FixtureCitationGraph): CitationGraph {
  return {
    nodes: payload.nodes.map((node) => ({
      node: {
        id: node.id,
        source_url: node.source_url,
        source_domain: node.source_domain,
        source_type: node.source_type,
        topic: node.topic,
        source_gap_type: node.source_gap_type,
        citation_count: node.citation_count
      },
      answer_runs: (node.answer_run_ids || []).slice(0, 12).map((runId) => ({ id: runId }))
    })),
    evidence_links: payload.nodes.flatMap((node) =>
      (node.answer_run_ids || []).slice(0, 12).map((runId) => ({
        source_graph_id: node.id,
        answer_run_id: runId,
        relation_type: "fixture_cited_by_ai"
      }))
    ),
    source_gaps: payload.source_gaps,
    competitor_benchmarks: payload.competitor_benchmarks
  };
}

async function fetchTraceabilityData(projectId: string | undefined): Promise<{
  baseUrl: string;
  displayUrl: string;
  projects: PageResponse<RuntimeProject>;
  selectedProjectId: string | undefined;
  selectedProject: RuntimeProject | undefined;
  traceability: TraceabilityDetail | null;
  graph: CitationGraph | undefined;
  dataMode: "runtime" | "fixture_fallback" | "empty";
  paths: { projects: string; traceability: string; graph: string; console: string };
  errors: string[];
}> {
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
  const displayUrl = process.env.NEXT_PUBLIC_API_BASE_URL || baseUrl;
  const projectParams = { market_code: "AU", limit: 20 };
  const projectsPath = runtimePath(endpoints.projects, projectParams);
  const projectsResult = await fetchRuntimeEndpoint<PageResponse<RuntimeProject>>(
    baseUrl,
    projectsPath,
    emptyPage<RuntimeProject>()
  );
  let projectRecords = projectsResult.payload.records;
  if (projectId && !projectRecords.some((record) => record.project.id === projectId)) {
    const selectedProjectResult = await fetchRuntimeEndpoint<PageResponse<RuntimeProject>>(
      baseUrl,
      runtimePath(endpoints.projects, { project_id: projectId, market_code: "AU", limit: 1 }),
      emptyPage<RuntimeProject>()
    );
    if (selectedProjectResult.payload.records.length) {
      projectRecords = [...selectedProjectResult.payload.records, ...projectRecords];
    }
  }
  let selectedProjectId =
    (projectId && projectRecords.some((record) => record.project.id === projectId) ? projectId : undefined) ||
    projectRecords[0]?.project.id;
  let selectedProject = projectRecords.find((record) => record.project.id === selectedProjectId);
  const params = selectedProjectId ? { project_id: selectedProjectId } : {};
  const traceabilityPath = runtimePath(endpoints.traceability, params);
  const graphPath = runtimePath(endpoints.graphs, { ...params, limit: 1 });
  const [traceabilityResult, graphResult] = await Promise.all([
    fetchRuntimeEndpoint<TraceabilityDetail | null>(baseUrl, traceabilityPath, null, { optionalNotFound: true }),
    fetchRuntimeEndpoint<PageResponse<CitationGraph>>(baseUrl, graphPath, emptyPage<CitationGraph>())
  ]);
  let traceability = traceabilityResult.payload;
  let graph = graphResult.payload.records[0];
  let dataMode: "runtime" | "fixture_fallback" | "empty" = traceability && graph ? "runtime" : "empty";
  const errors = [projectsResult.error, traceabilityResult.error, graphResult.error].filter(Boolean) as string[];
  if (!traceability || !graph) {
    const [fixtureTraceabilityResult, fixtureGraphResult] = await Promise.all([
      fetchRuntimeEndpoint<FixtureTraceability | null>(baseUrl, endpoints.fixtureTraceability, null),
      fetchRuntimeEndpoint<FixtureCitationGraph | null>(baseUrl, endpoints.fixtureGraph, null)
    ]);
    if (fixtureTraceabilityResult.payload && fixtureGraphResult.payload) {
      traceability = normalizeFixtureTraceability(fixtureTraceabilityResult.payload);
      graph = normalizeFixtureGraph(fixtureGraphResult.payload);
      const fixtureProjectId =
        selectedProjectId || fixtureTraceabilityResult.payload.traceability_bundle.project_id || "au-p0a-fixture";
      selectedProjectId = fixtureProjectId;
      selectedProject =
        selectedProject ||
        {
          project: {
            id: fixtureProjectId,
            name: "AU P0a fixture project",
            market_code: "AU",
            target_brand: "ExampleBrand"
          },
          tenant: { name: "Fixture tenant" }
        };
      dataMode = "fixture_fallback";
      errors.push("runtime traceability unavailable; rendering AU P0a fixture fallback");
    } else {
      errors.push(
        fixtureTraceabilityResult.error ||
          fixtureGraphResult.error ||
          "runtime traceability and fixture fallback are unavailable"
      );
    }
  }
  return {
    baseUrl,
    displayUrl,
    projects: { total_count: projectRecords.length, records: projectRecords },
    selectedProjectId,
    selectedProject,
    traceability,
    graph,
    dataMode,
    paths: {
      projects: projectsPath,
      traceability: traceabilityPath,
      graph: graphPath,
      console: selectedProjectId ? `/?project_id=${encodeURIComponent(selectedProjectId)}#traceability-map-runtime` : "/#traceability-map-runtime"
    },
    errors
  };
}

export default async function TraceabilityPage({
  searchParams
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const resolvedSearchParams = (await searchParams) || {};
  const selectedProjectFilter = cleanFilter(resolvedSearchParams.project_id);
  const { displayUrl, projects, selectedProjectId, selectedProject, traceability, graph, dataMode, paths, errors } =
    await fetchTraceabilityData(selectedProjectFilter);
  const bundle = traceability?.traceability_bundle;
  const latestReport = traceability?.report_exports[0];
  const latestScore = traceability?.score_snapshots[0];
  const firstRunId = bundle?.answer_run_ids[0] || traceability?.evidence_runs[0]?.answer_run.id;
  const firstSourceId = graph?.nodes[0]?.node.id || bundle?.source_graph_ids[0];
  const firstActionId = bundle?.action_recommendation_ids[0] || traceability?.action_recommendations[0]?.id;
  const firstDraftId = bundle?.content_draft_ids[0] || traceability?.content_drafts[0]?.draft.id;

  return (
    <main className="shell traceabilityPage">
      <header className="topbar">
        <div>
          <p className="eyebrow">GENO AU Traceability</p>
          <h1>Traceability Detail</h1>
          <p className="traceabilitySubtitle">
            {selectedProject
              ? `${selectedProject.tenant.name} / ${selectedProject.project.name} / ${selectedProject.project.target_brand}`
              : "No AU runtime project selected"}
          </p>
        </div>
        <div className="apiBox">
          <span>Runtime API</span>
          <strong>{displayUrl}</strong>
          <span>{dataMode === "fixture_fallback" ? "Fixture fallback" : dataMode}</span>
          <a className="inlineLink" href={paths.console}>
            Back to console
          </a>
        </div>
      </header>

      {errors.length ? (
        <section className="notice">
          <strong>Runtime API warnings</strong>
          {errors.map((item) => (
            <code key={item}>{item}</code>
          ))}
        </section>
      ) : null}

      <section className="filterBar traceabilityFilter">
        <div>
          <strong>Project scope</strong>
          <span>{paths.traceability}</span>
        </div>
        <form className="filterForm">
          <label>
            <span>Project</span>
            <select name="project_id" defaultValue={selectedProjectId || ""}>
              {projects.records.map((record) => (
                <option key={record.project.id} value={record.project.id}>
                  {record.tenant.name} / {record.project.name}
                </option>
              ))}
            </select>
          </label>
          <button className="actionButton" type="submit">
            Load detail
          </button>
        </form>
      </section>

      {traceability && bundle ? (
        <>
          <section className="metrics traceabilityMetrics">
            <Metric label="Reports" value={bundle.report_export_ids.length} />
            <Metric label="Score snapshots" value={bundle.score_snapshot_ids.length} />
            <Metric label="Answer runs" value={bundle.answer_run_ids.length} />
            <Metric label="Sources" value={bundle.source_graph_ids.length} />
            <Metric label="Actions" value={bundle.action_recommendation_ids.length} />
            <Metric label="Drafts" value={bundle.content_draft_ids.length} />
          </section>

          <section className="dashboard traceabilityDashboard">
            <Panel title="Bundle Summary" subtitle={latestReport?.report_version || "No report"}>
              {dataMode === "fixture_fallback" ? (
                <p className="noticeMini">Fixture fallback: runtime traceability was unavailable, so this page is rendering the AU P0a fixture evidence bundle.</p>
              ) : null}
              <p className="prompt">{bundle.explanation_summary}</p>
              <dl className="facts">
                <Fact label="Traceability API" value={paths.traceability} />
                <Fact label="Graph API" value={paths.graph} />
                <Fact label="Report" value={shortId(latestReport?.id || bundle.report_export_ids[0])} />
                <Fact label="Score" value={shortId(latestScore?.snapshot.id || bundle.score_snapshot_ids[0])} />
                <Fact label="Raw answers" value={bundle.raw_answer_ids.length} />
                <Fact label="Citations" value={bundle.answer_citation_ids.length} />
                <Fact label="Assets" value={bundle.evidence_asset_ids.length} />
                <Fact label="Audit events" value={bundle.audit_event_ids.length} />
              </dl>
            </Panel>

            <Panel title="Score Explanation" subtitle={latestScore?.snapshot.formula_version || "No score"}>
              {latestScore ? (
                <div className="stack" id={anchorId("score-snapshot", latestScore.snapshot.id || "latest")}>
                  <dl className="facts">
                    <Fact label="Final score" value={num(latestScore.snapshot.final_score)} />
                    <Fact label="Trigger rate" value={num(latestScore.snapshot.trigger_rate)} />
                    <Fact label="Mention rate" value={num(latestScore.snapshot.mention_rate)} />
                    <Fact label="Recommendation rate" value={num(latestScore.snapshot.recommendation_rate)} />
                  </dl>
                  <ul className="plainList">
                    {latestScore.contributions.slice(0, 5).map((item) => (
                      <li id={anchorId("score-contribution", item.id || item.component_name)} key={item.id || item.component_name}>
                        <strong>{item.component_name}</strong>
                        <span>
                          {num(item.weighted_contribution)} weighted / denominator {item.denominator || "unknown"}
                        </span>
                        <small>{item.positive_evidence_summary || item.negative_evidence_summary || "No evidence summary"}</small>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <EmptyState />
              )}
            </Panel>

            <Panel title="Deep Links" subtitle="Report to evidence graph">
              <div className="traceLinkColumn">
                <NodeLink label="Report" kind="report-export" value={latestReport?.id || bundle.report_export_ids[0]} />
                <NodeLink label="Score" kind="score-snapshot" value={latestScore?.snapshot.id || bundle.score_snapshot_ids[0]} />
                <NodeLink label="Evidence" kind="answer-run" value={firstRunId} />
                <NodeLink label="Source" kind="source-node" value={firstSourceId} />
                <NodeLink label="Action" kind="action" value={firstActionId} />
                <NodeLink label="Draft" kind="content-draft" value={firstDraftId} />
              </div>
            </Panel>

            <Panel title="Traceability Map" subtitle="report to score to evidence to source" wide>
              <TraceabilityMap
                actionId={firstActionId}
                draftId={firstDraftId}
                reportId={latestReport?.id || bundle.report_export_ids[0]}
                runId={firstRunId}
                scoreId={latestScore?.snapshot.id || bundle.score_snapshot_ids[0]}
                sourceId={firstSourceId}
              />
            </Panel>

            <Panel title="Evidence Runs" subtitle={`${traceability.evidence_runs.length} runs`} wide>
              <ul className="nodeList traceabilityNodeList">
                {traceability.evidence_runs.map((run) => (
                  <li id={anchorId("answer-run", run.answer_run.id)} key={run.answer_run.id}>
                    <strong>
                      {run.answer_run.platform || "platform"} / {run.answer_run.city || "city"} / {shortId(run.answer_run.id)}
                    </strong>
                    <span>{run.answer_run.prompt_text || "No prompt text"}</span>
                    <small>
                      status {run.answer_run.status || "unknown"} / {run.citations.length} citations /{" "}
                      {run.evidence_assets.length} assets / raw hash {run.raw_answer?.raw_payload_hash || "missing"}
                    </small>
                    <div className="traceLinkRow">
                      {run.citations.slice(0, 3).map((citation, index) => (
                        <a className="nodeLink" href={citation.url || "#"} key={`${run.answer_run.id}-citation-${index}`}>
                          Citation {citation.domain || index + 1}
                        </a>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>

            <Panel title="Source Graph" subtitle={`${graph?.nodes.length || 0} sources`} wide>
              {graph ? (
                <div className="traceabilityTwoColumn">
                  <ul className="nodeList">
                    {graph.nodes.map((item) => (
                      <li id={anchorId("source-node", item.node.id)} key={item.node.id}>
                        <strong>{item.node.source_domain || item.node.source_type || "source"}</strong>
                        <span>{item.node.source_url || "No URL"}</span>
                        <small>
                          topic {item.node.topic || "unknown"} / citations {item.node.citation_count || 0} / gap{" "}
                          {item.node.source_gap_type || "none"}
                        </small>
                        <div className="traceLinkRow">
                          {item.answer_runs.slice(0, 4).map((run) => (
                            <NodeLink key={run.id} label="Run" kind="answer-run" value={run.id} />
                          ))}
                        </div>
                      </li>
                    ))}
                  </ul>
                  <ul className="plainList">
                    {graph.source_gaps.slice(0, 6).map((gap, index) => (
                      <li key={`${gap.gap_type}-${index}`}>
                        <strong>{gap.gap_type}</strong>
                        <span>{gap.source_type}</span>
                        <small>{gap.recommendation}</small>
                      </li>
                    ))}
                    {graph.competitor_benchmarks.slice(0, 4).map((benchmark) => (
                      <li key={benchmark.competitor_name}>
                        <strong>{benchmark.competitor_name}</strong>
                        <span>{benchmark.metric_scope || "benchmark"}</span>
                        <small>{benchmark.answer_run_ids?.length || 0} linked answer runs</small>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <EmptyState />
              )}
            </Panel>

            <Panel title="Actions And Drafts" subtitle="evidence-backed follow-up" wide>
              <div className="traceabilityTwoColumn">
                <ul className="nodeList">
                  {traceability.action_recommendations.map((action) => (
                    <li id={anchorId("action", action.id || action.title)} key={action.id || action.title}>
                      <strong>
                        {action.priority} / {action.status}
                      </strong>
                      <span>{action.title}</span>
                      <small>{action.source_gap_type || "no source gap"}</small>
                    </li>
                  ))}
                </ul>
                <ul className="nodeList">
                  {traceability.content_drafts.map((item) => (
                    <li id={anchorId("content-draft", item.draft.id || item.draft.title)} key={item.draft.id || item.draft.title}>
                      <strong>{item.draft.review_status}</strong>
                      <span>{item.draft.title}</span>
                      <small>
                        {item.draft.target_city || "no city"} / {item.draft.target_platform || "no platform"} /{" "}
                        {item.answer_runs?.length || 0} evidence runs
                      </small>
                    </li>
                  ))}
                </ul>
              </div>
            </Panel>

            <Panel title="Audit And Evidence Links" subtitle={`${traceability.audit_events.length} audit events`} wide>
              <div className="traceabilityTwoColumn">
                <ul className="plainList">
                  {traceability.evidence_links.map((link, index) => (
                    <li key={`${link.relation_type}-${index}`}>
                      <strong>{link.relation_type}</strong>
                      <span>
                        {link.source_type} to {link.target_type}
                      </span>
                      <small>{link.answer_run_ids.length} answer runs</small>
                    </li>
                  ))}
                </ul>
                <ul className="plainList">
                  {traceability.audit_events.map((event, index) => (
                    <li key={`${event.event_type}-${index}`}>
                      <strong>{event.event_type}</strong>
                      <span>{event.target_type}</span>
                      <small>{event.method_version || "no method version"}</small>
                    </li>
                  ))}
                </ul>
              </div>
            </Panel>
          </section>
        </>
      ) : (
        <section className="dashboard">
          <Panel title="Traceability Detail" subtitle="No traceability bundle" wide>
            <EmptyState />
          </Panel>
        </section>
      )}
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
  children: React.ReactNode;
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
  return <p className="empty">No runtime data returned for the selected project.</p>;
}

function NodeLink({ label, kind, value }: { label: string; kind: string; value: string | undefined }) {
  return (
    <a className="nodeLink" href={anchorHref(kind, value)} title={`${label}: ${value || "unknown"}`}>
      {label} {shortId(value)}
    </a>
  );
}

function TraceabilityMap({
  actionId,
  draftId,
  reportId,
  runId,
  scoreId,
  sourceId
}: {
  actionId: string | undefined;
  draftId: string | undefined;
  reportId: string | undefined;
  runId: string | undefined;
  scoreId: string | undefined;
  sourceId: string | undefined;
}) {
  const nodes = [
    { label: "Report", kind: "report-export", value: reportId, x: 80, y: 58 },
    { label: "Score", kind: "score-snapshot", value: scoreId, x: 250, y: 58 },
    { label: "Evidence", kind: "answer-run", value: runId, x: 420, y: 58 },
    { label: "Source", kind: "source-node", value: sourceId, x: 590, y: 58 },
    { label: "Action", kind: "action", value: actionId, x: 250, y: 166 },
    { label: "Draft", kind: "content-draft", value: draftId, x: 420, y: 166 }
  ];
  return (
    <section className="traceMap traceabilityStandaloneMap" id={anchorId("traceability-map", "standalone")}>
      <div className="traceMapCanvas">
        <svg viewBox="0 0 700 230" role="img" aria-label="Standalone runtime traceability map">
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
    </section>
  );
}
