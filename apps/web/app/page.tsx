type PageResponse<T> = {
  total_count: number;
  records: T[];
};

type EvidenceRun = {
  answer_run: {
    id: string;
    platform: string;
    surface: string;
    city: string;
    status: string;
    prompt_text?: string;
    prompt_intent_type?: string;
    collected_at: string;
  };
  citations: unknown[];
  evidence_assets: unknown[];
  audit_events: unknown[];
};

type ScoreSnapshot = {
  snapshot: {
    final_score: number;
    trigger_rate: number;
    mention_rate: number;
    recommendation_rate: number;
    formula_version: string;
  };
  contributions: Array<{
    component_name: string;
    component_score: number;
    weighted_contribution: number;
  }>;
  answer_runs: unknown[];
  audit_events: unknown[];
};

type CitationGraph = {
  nodes: unknown[];
  source_gaps: Array<{ source_type: string; gap_type: string; recommendation: string }>;
  competitor_benchmarks: Array<{ competitor_name: string }>;
};

type ReportExport = {
  report_export: {
    report_version: string;
    sample_size: number;
    exported_at: string;
    markdown_url?: string | null;
    csv_url?: string | null;
  };
  answer_runs: unknown[];
  audit_events: unknown[];
};

type ActionPlan = {
  retest_schedule: { offsets_days: number[]; prompt_version: string };
  action_recommendations: Array<{ title: string; priority: string; status: string }>;
  retest_comparisons: Array<{ trend: string; score_delta: number }>;
  audit_events: unknown[];
};

type ContentEngine = {
  knowledge_facts: unknown[];
  content_drafts: Array<{
    draft: { title: string; review_status: string; target_city: string };
    target_questions: Array<{ text: string }>;
    answer_runs: unknown[];
  }>;
  integration_connectors: Array<{ provider: string; connection_status: string }>;
  manual_distribution_records: unknown[];
  audit_events: unknown[];
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
  action_recommendations: Array<{ title: string; priority: string; status: string }>;
  content_drafts: Array<{
    draft: { title: string; review_status: string };
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
  evidence: PageResponse<EvidenceRun>;
  scores: PageResponse<ScoreSnapshot>;
  graphs: PageResponse<CitationGraph>;
  reports: PageResponse<ReportExport>;
  actions: PageResponse<ActionPlan>;
  content: PageResponse<ContentEngine>;
  traceability: TraceabilityDetail | null;
};

const endpoints = {
  evidence: "/v1/evidence-runs/runtime?limit=5",
  scores: "/v1/visibility-scores/runtime?limit=1",
  graphs: "/v1/citation-graphs/runtime?limit=1",
  reports: "/v1/reports/runtime?limit=1",
  actions: "/v1/action-plans/runtime?limit=1",
  content: "/v1/content-engines/runtime?limit=1",
  traceability: "/v1/traceability/runtime"
} as const;

const emptyPage = { total_count: 0, records: [] };

export const dynamic = "force-dynamic";

async function fetchRuntimeData(): Promise<{
  data: RuntimeData;
  error: string | null;
  fetchUrl: string;
  displayUrl: string;
}> {
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const displayUrl = process.env.NEXT_PUBLIC_API_BASE_URL || baseUrl;

  try {
    const entries = await Promise.all(
      Object.entries(endpoints).map(async ([key, path]) => {
        const response = await fetch(`${baseUrl}${path}`, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`${path} returned ${response.status}`);
        }
        return [key, await response.json()] as const;
      })
    );
    return {
      data: Object.fromEntries(entries) as RuntimeData,
      error: null,
      fetchUrl: baseUrl,
      displayUrl
    };
  } catch (error) {
    return {
      data: {
        evidence: emptyPage,
        scores: emptyPage,
        graphs: emptyPage,
        reports: emptyPage,
        actions: emptyPage,
        content: emptyPage,
        traceability: null
      },
      error: error instanceof Error ? error.message : "Runtime API unavailable",
      fetchUrl: baseUrl,
      displayUrl
    };
  }
}

function pct(value: number | undefined): string {
  return `${Math.round((value || 0) * 100)}%`;
}

function num(value: number | undefined): string {
  return Number(value || 0).toFixed(2);
}

export default async function Home() {
  const { data, error, displayUrl } = await fetchRuntimeData();
  const latestEvidence = data.evidence.records[0];
  const latestScore = data.scores.records[0];
  const latestGraph = data.graphs.records[0];
  const latestReport = data.reports.records[0];
  const latestAction = data.actions.records[0];
  const latestContent = data.content.records[0];
  const traceability = data.traceability;
  const totalAuditEvents =
    (latestEvidence?.audit_events.length || 0) +
    (latestScore?.audit_events.length || 0) +
    (latestReport?.audit_events.length || 0) +
    (latestAction?.audit_events.length || 0) +
    (latestContent?.audit_events.length || 0) +
    (traceability?.audit_events.length || 0);

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

      <section className="metrics" aria-label="runtime metrics">
        <Metric label="Evidence runs" value={data.evidence.total_count} />
        <Metric label="Final score" value={num(latestScore?.snapshot.final_score)} />
        <Metric label="Source gaps" value={latestGraph?.source_gaps.length || 0} />
        <Metric label="Open actions" value={latestAction?.action_recommendations.length || 0} />
        <Metric label="Content drafts" value={latestContent?.content_drafts.length || 0} />
        <Metric label="Audit events" value={totalAuditEvents} />
        <Metric label="Trace links" value={traceability?.evidence_links.length || 0} />
      </section>

      <section className="dashboard">
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
            <dl className="facts">
              <Fact label="Sample size" value={latestReport.report_export.sample_size} />
              <Fact label="Evidence links" value={latestReport.answer_runs.length} />
              <Fact label="Markdown" value={latestReport.report_export.markdown_url || "pending object store"} />
              <Fact label="CSV" value={latestReport.report_export.csv_url || "pending object store"} />
            </dl>
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
import type { ReactNode } from "react";
