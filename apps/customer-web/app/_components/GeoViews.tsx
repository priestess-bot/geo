import type {
  CustomerApprovedReport,
  CustomerGeoMetric,
  CustomerMeasurementWindow,
  CustomerProblemDetails,
  CustomerVerifiedUrl,
  MeasurementWindow
} from "@geo/types/customer";

import type { CustomerGeoReadModel, ResourceState } from "../runtime";

const WINDOW_ORDER: Record<MeasurementWindow, number> = {
  baseline: 0,
  t28: 1,
  t56: 2,
  t84: 3,
  ad_hoc: 4
};

const WINDOW_LABELS: Record<MeasurementWindow, string> = {
  baseline: "基线",
  t28: "T+28",
  t56: "T+56",
  t84: "T+84",
  ad_hoc: "临时测量"
};

export function SummaryView({ model }: Readonly<{ model: CustomerGeoReadModel }>) {
  if (model.summary.status === "error") {
    return <ResourceProblem problem={model.summary.problem} title="项目概览不可用" />;
  }
  const summary = model.summary.data;
  const latestMetric = summary.latest_metrics[0];
  return (
    <>
      <section className="pageHeading">
        <div>
          <p className="eyebrow">项目概览</p>
          <h2>AI 推荐表现与投放验证</h2>
        </div>
        <p className="methodNote">{summary.interpretation}</p>
      </section>
      <section aria-label="项目指标摘要" className="metricStrip">
        <MetricStat label="冻结协议" value={String(summary.frozen_protocol_count)} />
        <MetricStat label="测量窗口" value={String(summary.measurement_window_count)} />
        <MetricStat label="已验证 URL" value={String(summary.verified_url_count)} />
        <MetricStat label="已批准报告" value={String(summary.approved_report_count)} />
      </section>
      <section className="contentSection">
        <div className="sectionHeader">
          <h2>最近一次测量</h2>
          <span className={latestMetric?.status === "confounded" ? "status warning" : "status"}>
            {latestMetric ? metricStatus(latestMetric) : "暂无数据"}
          </span>
        </div>
        {latestMetric ? (
          <MetricTable metrics={[latestMetric]} compact />
        ) : (
          <EmptyData detail="当前项目尚未生成客户可见的测量指标。" />
        )}
      </section>
    </>
  );
}

export function MetricsView({ state }: Readonly<{
  state: ResourceState<CustomerGeoMetric[]>;
}>) {
  if (state.status === "error") {
    return <ResourceProblem problem={state.problem} title="趋势指标不可用" />;
  }
  const metrics = [...state.data].sort(
    (left, right) => WINDOW_ORDER[left.measurement_window] - WINDOW_ORDER[right.measurement_window]
  );
  return (
    <section className="contentSection">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">趋势指标</p>
          <h2>冻结协议下的测量结果</h2>
        </div>
        <p className="muted">混杂窗口仅作观察，不用于因果归因。</p>
      </div>
      {metrics.length ? (
        <MetricTable metrics={metrics} />
      ) : (
        <EmptyData detail="当前项目尚无完成或混杂的测量窗口。" />
      )}
    </section>
  );
}

export function PlacementsView({
  urls,
  windows
}: Readonly<{
  urls: ResourceState<CustomerVerifiedUrl[]>;
  windows: ResourceState<CustomerMeasurementWindow[]>;
}>) {
  return (
    <div className="sectionStack">
      <section className="contentSection">
        <div className="sectionHeader">
          <div>
            <p className="eyebrow">已验证 URL</p>
            <h2>公开投放地址</h2>
          </div>
        </div>
        {urls.status === "error" ? (
          <ResourceProblem problem={urls.problem} title="已验证 URL 不可用" />
        ) : urls.data.length ? (
          <VerifiedUrlTable urls={urls.data} />
        ) : (
          <EmptyData detail="暂无验证通过的公开投放 URL。未验证地址不会在此显示。" />
        )}
      </section>
      <section className="contentSection">
        <div className="sectionHeader">
          <div>
            <p className="eyebrow">测量窗口</p>
            <h2>采样完整性与状态</h2>
          </div>
        </div>
        {windows.status === "error" ? (
          <ResourceProblem problem={windows.problem} title="测量窗口不可用" />
        ) : windows.data.length ? (
          <WindowTable windows={windows.data} />
        ) : (
          <EmptyData detail="暂无客户可见的测量窗口。" />
        )}
      </section>
    </div>
  );
}

export function ReportsView({ state }: Readonly<{
  state: ResourceState<CustomerApprovedReport[]>;
}>) {
  if (state.status === "error") {
    return <ResourceProblem problem={state.problem} title="报告不可用" />;
  }
  return (
    <section className="contentSection">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">已批准报告</p>
          <h2>客户可见测量报告</h2>
        </div>
      </div>
      {state.data.length ? (
        <div className="reportList">
          {state.data.map((report) => <ReportItem key={report.id} report={report} />)}
        </div>
      ) : (
        <EmptyData detail="暂无已批准报告。草稿和未批准内容不会在客户门户显示。" />
      )}
    </section>
  );
}

function MetricTable({ metrics, compact = false }: Readonly<{
  compact?: boolean;
  metrics: CustomerGeoMetric[];
}>) {
  return (
    <div className="tableScroll">
      <table className={compact ? "dataTable compact" : "dataTable"}>
        <thead>
          <tr>
            <th>窗口</th>
            <th>推荐占比</th>
            <th>产品提及</th>
            <th>投放引用</th>
            <th>合规目的地</th>
            <th>验证投放</th>
            <th>竞争差值</th>
            <th>样本</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((metric) => (
            <tr key={metric.id}>
              <td>
                <strong>{WINDOW_LABELS[metric.measurement_window]}</strong>
                <span className="tableMeta">{metricStatus(metric)}</span>
              </td>
              <td>{percent(metric.recommendation_share)}</td>
              <td>{percent(metric.product_mention_share)}</td>
              <td>{percent(metric.placement_citation_share)}</td>
              <td>{percent(metric.qualified_destination_coverage)}</td>
              <td>{percent(metric.verified_placement_coverage)}</td>
              <td>{signedPercent(metric.competitive_delta)}</td>
              <td>{metric.eligible_sample_count}/{metric.expected_sample_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function VerifiedUrlTable({ urls }: Readonly<{ urls: CustomerVerifiedUrl[] }>) {
  return (
    <div className="tableScroll">
      <table className="dataTable">
        <thead><tr><th>目的地</th><th>首次验证</th><th>AI 观测</th><th>Campaign</th></tr></thead>
        <tbody>
          {urls.map((item) => (
            <tr key={`${item.campaign_id}-${item.destination_id}-${item.url}`}>
              <td className="urlCell">
                <a href={item.url} rel="noreferrer" target="_blank">{item.title || item.url}</a>
                {item.title ? <span className="tableMeta">{item.url}</span> : null}
              </td>
              <td>{formatDate(item.first_verified_at)}</td>
              <td>{item.observation_count}</td>
              <td><code>{shortId(item.campaign_id)}</code></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WindowTable({ windows }: Readonly<{ windows: CustomerMeasurementWindow[] }>) {
  const ordered = [...windows].sort(
    (left, right) => WINDOW_ORDER[left.measurement_window] - WINDOW_ORDER[right.measurement_window]
  );
  return (
    <div className="tableScroll">
      <table className="dataTable">
        <thead><tr><th>窗口</th><th>状态</th><th>有效样本</th><th>计算时间</th><th>说明</th></tr></thead>
        <tbody>
          {ordered.map((window) => (
            <tr key={`${window.protocol_id}-${window.measurement_window}`}>
              <td><strong>{WINDOW_LABELS[window.measurement_window]}</strong></td>
              <td><span className={window.status === "confounded" ? "status warning" : "status"}>{window.status === "complete" ? "完整" : "混杂"}</span></td>
              <td>{window.eligible_sample_count}/{window.expected_sample_count}</td>
              <td>{formatDate(window.computed_at)}</td>
              <td>{window.confounded_reasons.length ? window.confounded_reasons.join("、") : "无混杂标记"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReportItem({ report }: Readonly<{ report: CustomerApprovedReport }>) {
  return (
    <article className="reportItem">
      <header>
        <div>
          <h3>{report.title}</h3>
          <p className="muted">批准时间：{formatDate(report.approved_at)}</p>
        </div>
        <span className="status">已批准</span>
      </header>
      <p>{report.body}</p>
      <p className="methodNote">{report.methodology_statement}</p>
    </article>
  );
}

function MetricStat({ label, value }: Readonly<{ label: string; value: string }>) {
  return <div className="metricStat"><span>{label}</span><strong>{value}</strong></div>;
}

function EmptyData({ detail }: Readonly<{ detail: string }>) {
  return <div className="inlineEmpty"><p>{detail}</p></div>;
}

function ResourceProblem({
  problem,
  title
}: Readonly<{ problem: CustomerProblemDetails; title: string }>) {
  return (
    <div aria-live="polite" className="inlineProblem" role="status">
      <strong>{problem.status === 403 ? "无权查看此项目资源" : title}</strong>
      <p>{problem.detail}</p>
      {problem.request_id ? <p className="muted">请求 ID：{problem.request_id}</p> : null}
    </div>
  );
}

function metricStatus(metric: CustomerGeoMetric): string {
  return metric.status === "complete" ? "完整" : "混杂";
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function signedPercent(value: number): string {
  const rounded = Math.round(value * 100);
  return `${rounded > 0 ? "+" : ""}${rounded}%`;
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

function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}
