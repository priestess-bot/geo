import type {
  CustomerWorkflowCMetricKey,
  CustomerWorkflowCMetricValue,
  CustomerWorkflowCReport,
  CustomerWorkflowCReportPayload,
  CustomerWorkflowCReportSourceKind
} from "@geo/types/customer";

import type { CustomerWorkflowCReports } from "../runtime";

const METRIC_LABELS: Record<CustomerWorkflowCMetricKey, string> = {
  mention: "提及",
  mention_rate: "提及率",
  recommendation_rate: "推荐率",
  brand_mention: "品牌提及",
  product_mention: "产品提及",
  recommendation: "推荐",
  recommendation_strength: "推荐强度",
  competitor_mention: "竞品提及",
  competitor_relative_position: "竞品相对位置",
  sentiment: "情感",
  fact_accuracy: "事实准确性",
  explicit_conflict: "明确冲突",
  subject_mixup: "主体混用",
  key_fact_omission: "关键事实遗漏",
  citation_entailment: "引用蕴含",
  citation_position: "引用位置",
  citation_order: "引用顺序",
  verified_url_hit: "已验证 URL 命中",
  source_domain_diversity: "来源域名多样性",
  source_type_diversity: "来源类型多样性",
  approved_corpus_absorption: "批准语料吸收度"
};

const SOURCE_LABELS: Record<CustomerWorkflowCReportSourceKind, string> = {
  provider_api: "Provider API",
  proxy_grounded_api: "代理 Grounded API",
  automated_ui: "消费者界面自动采样"
};

export function WorkflowCReportsSection({
  reports
}: Readonly<{ reports: CustomerWorkflowCReports }>) {
  return (
    <section aria-labelledby="workflow-c-report-heading" className="contentSection">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">Workflow C</p>
          <h2 id="workflow-c-report-heading">已批准跨引擎报告</h2>
        </div>
        {reports.status === "ready" ? (
          <span className="status">{reports.data.total} 份已批准</span>
        ) : null}
      </div>
      {reports.status === "error" ? (
        <div aria-live="polite" className="inlineProblem" role="alert">
          <strong>Workflow C 报告暂不可用</strong>
          <p>{reports.problem.detail}</p>
          {reports.problem.request_id ? (
            <p className="muted">请求 ID：{reports.problem.request_id}</p>
          ) : null}
        </div>
      ) : reports.data.items.length ? (
        <ul aria-label="已批准 Workflow C 报告" className="reportList workflowReportList">
          {reports.data.items.map((report, index) => (
            <li key={report.id}>
              <WorkflowCReportItem index={index} report={report} />
            </li>
          ))}
        </ul>
      ) : (
        <div aria-live="polite" className="inlineEmpty" role="status">
          <p>当前 Campaign 暂无已批准的 Workflow C 报告。</p>
        </div>
      )}
    </section>
  );
}

function WorkflowCReportItem({
  index,
  report
}: Readonly<{ index: number; report: CustomerWorkflowCReport }>) {
  const payload = report.approved_safe_payload;
  const metrics = metricEntries(payload);
  const titleId = `workflow-c-report-title-${index}`;
  return (
    <article aria-labelledby={titleId} className="reportItem workflowCReportItem">
      <header>
        <div>
          <h3 id={titleId}>{payload.headline}</h3>
          <p className="muted">
            批准时间：<time dateTime={report.approved_at}>{formatDate(report.approved_at)}</time>
          </p>
        </div>
        <span className="status">已批准</span>
      </header>
      {payload.summary ? <p>{payload.summary}</p> : null}
      <dl className="reportMetadata">
        <div><dt>采样来源</dt><dd>{SOURCE_LABELS[report.source_kind]}</dd></div>
        <div><dt>报告 Hash</dt><dd><code>{report.report_hash}</code></dd></div>
      </dl>
      {metrics.length ? <WorkflowCMetricTable metrics={metrics} /> : null}
      {payload.methodology ? <p className="methodNote">{payload.methodology}</p> : null}
      {payload.warnings?.length ? (
        <aside aria-label="报告注意事项" className="reportWarnings">
          <strong>注意事项</strong>
          <ul>
            {payload.warnings.map((warning, index) => (
              <li key={`${index}-${warning}`}>{warning}</li>
            ))}
          </ul>
        </aside>
      ) : null}
    </article>
  );
}

function WorkflowCMetricTable({
  metrics
}: Readonly<{ metrics: ReadonlyArray<readonly [CustomerWorkflowCMetricKey, CustomerWorkflowCMetricValue]> }>) {
  return (
    <div className="tableScroll workflowMetricTable">
      <table className="dataTable">
        <caption className="srOnly">Workflow C 已批准指标</caption>
        <thead><tr><th scope="col">指标</th><th scope="col">批准值</th></tr></thead>
        <tbody>
          {metrics.map(([key, value]) => (
            <tr key={key}><td>{METRIC_LABELS[key]}</td><td>{String(value)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function metricEntries(
  payload: CustomerWorkflowCReportPayload
): Array<readonly [CustomerWorkflowCMetricKey, CustomerWorkflowCMetricValue]> {
  const metrics = new Map<CustomerWorkflowCMetricKey, CustomerWorkflowCMetricValue>();
  for (const [key, value] of Object.entries(payload.metrics || {})) {
    if (value !== undefined) metrics.set(key as CustomerWorkflowCMetricKey, value);
  }
  if (payload.mention_rate !== undefined && !metrics.has("mention_rate")) {
    metrics.set("mention_rate", payload.mention_rate);
  }
  if (payload.recommendation_rate !== undefined && !metrics.has("recommendation_rate")) {
    metrics.set("recommendation_rate", payload.recommendation_rate);
  }
  return [...metrics.entries()];
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC"
  }).format(date);
}
