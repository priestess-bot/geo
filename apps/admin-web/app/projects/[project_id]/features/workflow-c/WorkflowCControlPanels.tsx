import { randomUUID } from "node:crypto";

import { WorkflowCAnalysisJobCommands } from "./WorkflowCAnalysisJobCommands";
import { WorkflowCProtocolCommands } from "./WorkflowCProtocolCommands";
import { WorkflowCReportCommands } from "./WorkflowCReportCommands";
import type {
  MetricProtocol,
  StatisticalProtocol,
  WorkflowCApprovedSafePayload,
  WorkflowCReport
} from "./workflowCControlTypes";
import type { WorkflowCWorkspaceData } from "./workflowCTypes";
import { EmptyState, LoadProblem, SectionHeading } from "./WorkflowCWorkspace";
import styles from "./WorkflowC.module.css";
import controlStyles from "./WorkflowCControls.module.css";

export function ProtocolsPanel({
  canAnalyze,
  canManage,
  data,
  projectId
}: {
  canAnalyze: boolean;
  canManage: boolean;
  data: WorkflowCWorkspaceData;
  projectId: string;
}) {
  const metrics = data.metricProtocols.data?.items || [];
  const statistics = data.statisticalProtocols.data?.items || [];
  return (
    <div className={styles.sectionStack}>
      <section>
        <SectionHeading eyebrow="Frozen governance" title="Analysis Protocols" />
        {data.metricProtocols.problem ? <LoadProblem label="Metric Protocols" problem={data.metricProtocols.problem} /> : null}
        {data.statisticalProtocols.problem ? <LoadProblem label="Statistical Protocols" problem={data.statisticalProtocols.problem} /> : null}
        {!data.metricProtocols.problem && !data.statisticalProtocols.problem && !metrics.length && !statistics.length
          ? <EmptyState title="Protocol inventory 为空" />
          : <ProtocolInventory metrics={metrics} statistics={statistics} />}
      </section>
      <WorkflowCProtocolCommands
        actorId={data.actorId}
        canManage={canManage}
        commandKeys={{
          metricCreate: `workflow-c-metric-protocol-create-${randomUUID()}`,
          statisticalCreate: `workflow-c-stat-protocol-create-${randomUUID()}`,
          metricTransition: `workflow-c-metric-protocol-transition-${randomUUID()}`,
          statisticalTransition: `workflow-c-stat-protocol-transition-${randomUUID()}`
        }}
        metricProtocols={metrics}
        projectId={projectId}
        statisticalProtocols={statistics}
      />
      <WorkflowCAnalysisJobCommands
        canAnalyze={canAnalyze}
        commandKeys={{
          semantic: `workflow-c-semantic-job-${randomUUID()}`,
          comparison: `workflow-c-comparison-job-${randomUUID()}`,
          drift: `workflow-c-drift-job-${randomUUID()}`
        }}
        metricProtocols={metrics}
        projectId={projectId}
        runs={data.runs.data?.items || []}
        snapshots={data.metricSnapshots.data?.items || []}
        statisticalProtocols={statistics}
      />
    </div>
  );
}

export function ReportsPanel({
  canManage,
  data,
  projectId
}: {
  canManage: boolean;
  data: WorkflowCWorkspaceData;
  projectId: string;
}) {
  const reports = data.workflowCReports.data?.items || [];
  return (
    <div className={styles.sectionStack}>
      <section>
        <SectionHeading eyebrow="Customer-safe projection" title="Approved Workflow C Reports" />
        {data.workflowCReports.problem
          ? <LoadProblem label="Workflow C Reports" problem={data.workflowCReports.problem} />
          : reports.length ? <ReportInventory reports={reports} /> : <EmptyState title="Workflow C Report inventory 为空" />}
      </section>
      <WorkflowCReportCommands
        canManage={canManage}
        commandKeys={{
          create: `workflow-c-report-create-${randomUUID()}`,
          transition: `workflow-c-report-transition-${randomUUID()}`
        }}
        currentIdentityId={data.currentIdentityId}
        projectId={projectId}
        reports={reports}
        snapshots={data.metricSnapshots.data?.items || []}
      />
    </div>
  );
}

function ProtocolInventory({
  metrics,
  statistics
}: {
  metrics: MetricProtocol[];
  statistics: StatisticalProtocol[];
}) {
  const rows = [
    ...metrics.map((item) => ({
      id: item.id,
      kind: "metric",
      version: item.version,
      status: item.status,
      hash: item.protocol_hash,
      actor: item.created_by,
      updated: item.updated_at
    })),
    ...statistics.map((item) => ({
      id: item.id,
      kind: item.kind,
      version: item.version,
      status: item.status,
      hash: item.definition_hash,
      actor: item.created_by,
      updated: item.updated_at
    }))
  ];
  return (
    <div className={styles.tableWrap}>
      <table className={styles.dataTable}>
        <thead><tr><th>Kind</th><th>Version</th><th>Status</th><th>Definition SHA-256</th><th>Maker</th><th>Updated</th></tr></thead>
        <tbody>{rows.map((row) => (
          <tr key={row.id}>
            <td><strong>{row.kind.replaceAll("_", " ")}</strong><small>{row.id}</small></td>
            <td>v{row.version}</td>
            <td><span className={styles.status} data-status={row.status}>{row.status}</span></td>
            <td><code>{row.hash}</code></td>
            <td>{row.actor}</td>
            <td>{formatTime(row.updated)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function ReportInventory({ reports }: { reports: WorkflowCReport[] }) {
  return (
    <div className={controlStyles.reportList}>
      {reports.map((report) => (
        <article key={report.report_id}>
          <header>
            <div><strong>{report.approved_safe_payload.headline}</strong><small>{report.report_id} · {report.source_kind.replaceAll("_", " ")} · v{report.version}</small></div>
            <span className={styles.status} data-status={report.status}>{report.status}</span>
          </header>
          {report.approved_safe_payload.summary ? <p>{report.approved_safe_payload.summary}</p> : null}
          <SafeMetrics payload={report.approved_safe_payload} />
          {report.approved_safe_payload.warnings?.length ? (
            <ul>{report.approved_safe_payload.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          ) : null}
          <footer><code>{report.version_hash}</code><small>{formatTime(report.occurred_at)}</small></footer>
        </article>
      ))}
    </div>
  );
}

function SafeMetrics({ payload }: { payload: WorkflowCApprovedSafePayload }) {
  const values = {
    ...(payload.metrics || {}),
    ...(payload.mention_rate === undefined ? {} : { mention_rate: payload.mention_rate }),
    ...(payload.recommendation_rate === undefined
      ? {}
      : { recommendation_rate: payload.recommendation_rate })
  };
  if (!Object.keys(values).length) return null;
  return (
    <dl className={controlStyles.safeMetrics}>
      {Object.entries(values).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{value}</dd></div>)}
    </dl>
  );
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN");
}
