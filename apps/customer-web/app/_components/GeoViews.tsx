import type {
  CustomerApprovedMeasurement,
  CustomerCampaignReadModel,
  CustomerGeoMetric,
  CustomerProblemDetails,
  CustomerVerifiedUrl,
  MeasurementStatus,
  MeasurementWindow
} from "@geo/types/customer";

import type { CustomerGeoReadModel } from "../runtime";

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
  if (model.status === "error") {
    return <ResourceProblem problem={model.problem} title="Campaign 概览不可用" />;
  }
  const { approved_measurements: approved, summary } = model.data;
  const latest = approved[0];
  return (
    <>
      <section className="pageHeading">
        <div>
          <p className="eyebrow">{summary.campaign_name}</p>
          <h2>AI 推荐表现与投放验证</h2>
        </div>
        <p className="methodNote">{summary.interpretation}</p>
      </section>
      <section aria-label="Campaign 指标摘要" className="metricStrip">
        <MetricStat label="冻结协议" value={String(summary.frozen_protocol_count)} />
        <MetricStat label="批准窗口" value={String(summary.measurement_window_count)} />
        <MetricStat label="已验证 URL" value={String(summary.verified_url_count)} />
        <MetricStat label="已批准报告" value={String(summary.approved_report_count)} />
      </section>
      <section className="contentSection">
        <div className="sectionHeader">
          <h2>最近批准的测量</h2>
          {latest ? <ContractBadge measurement={latest} /> : null}
        </div>
        {latest ? (
          <MetricTable measurements={[latest]} compact />
        ) : (
          <NoApprovedReport />
        )}
      </section>
    </>
  );
}

export function MetricsView({ model }: Readonly<{ model: CustomerGeoReadModel }>) {
  if (model.status === "error") {
    return <ResourceProblem problem={model.problem} title="趋势指标不可用" />;
  }
  const measurements = orderedMeasurements(model.data.approved_measurements);
  return (
    <section className="contentSection">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">趋势指标</p>
          <h2>已批准报告关联的不可变快照</h2>
        </div>
        <p className="muted">混杂或证据不足的窗口仅作观察。</p>
      </div>
      {measurements.length ? <MetricTable measurements={measurements} /> : <NoApprovedReport />}
    </section>
  );
}

export function PlacementsView({ model }: Readonly<{ model: CustomerGeoReadModel }>) {
  if (model.status === "error") {
    return <ResourceProblem problem={model.problem} title="投放数据不可用" />;
  }
  return (
    <div className="sectionStack">
      <section className="contentSection">
        <div className="sectionHeader">
          <div>
            <p className="eyebrow">已验证 URL</p>
            <h2>公开投放地址</h2>
          </div>
        </div>
        {model.data.verified_urls.length ? (
          <VerifiedUrlTable urls={model.data.verified_urls} />
        ) : (
          <EmptyData detail="暂无验证通过的公开投放 URL。" />
        )}
      </section>
      <section className="contentSection">
        <div className="sectionHeader">
          <div>
            <p className="eyebrow">批准窗口</p>
            <h2>采样完整性与快照口径</h2>
          </div>
        </div>
        {model.data.approved_measurements.length ? (
          <WindowTable measurements={orderedMeasurements(model.data.approved_measurements)} />
        ) : (
          <NoApprovedReport />
        )}
      </section>
    </div>
  );
}

export function ReportsView({ model }: Readonly<{ model: CustomerGeoReadModel }>) {
  if (model.status === "error") {
    return <ResourceProblem problem={model.problem} title="报告不可用" />;
  }
  return (
    <section className="contentSection">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">已批准报告</p>
          <h2>报告与不可变测量快照</h2>
        </div>
      </div>
      {model.data.approved_measurements.length ? (
        <div className="reportList">
          {model.data.approved_measurements.map((item) => (
            <ReportItem key={item.report.id} measurement={item} />
          ))}
        </div>
      ) : (
        <NoApprovedReport />
      )}
    </section>
  );
}

function MetricTable({
  compact = false,
  measurements
}: Readonly<{
  compact?: boolean;
  measurements: CustomerApprovedMeasurement[];
}>) {
  return (
    <div className="tableScroll">
      <table className={compact ? "dataTable compact" : "dataTable"}>
        <thead>
          <tr>
            <th>窗口</th><th>来源 / 问题簇</th><th>推荐占比</th><th>产品提及</th>
            <th>投放引用</th><th>目的地</th><th>竞争差值</th><th>样本完成度</th>
          </tr>
        </thead>
        <tbody>
          {measurements.map((item) => (
            <tr key={item.report.id}>
              <td>
                <strong>{WINDOW_LABELS[item.snapshot.measurement_window]}</strong>
                <span className="tableMeta">{metricStatus(item.snapshot.status)}</span>
                <span className="tableMeta">{contractLabel(item)}</span>
              </td>
              <td>
                {sourceLabel(item.snapshot)}
                <span className="tableMeta">问题簇：{item.snapshot.query_cluster_key || "未知"}</span>
              </td>
              <EstimateCell
                high={item.snapshot.recommendation_ci_high}
                low={item.snapshot.recommendation_ci_low}
                maximum={item.snapshot.recommendation_query_max}
                minimum={item.snapshot.recommendation_query_min}
                value={item.snapshot.recommendation_share}
              />
              <EstimateCell
                high={item.snapshot.product_mention_ci_high}
                low={item.snapshot.product_mention_ci_low}
                maximum={item.snapshot.product_mention_query_max}
                minimum={item.snapshot.product_mention_query_min}
                value={item.snapshot.product_mention_share}
              />
              <EstimateCell
                high={item.snapshot.placement_citation_ci_high}
                low={item.snapshot.placement_citation_ci_low}
                maximum={item.snapshot.placement_citation_query_max}
                minimum={item.snapshot.placement_citation_query_min}
                value={item.snapshot.placement_citation_share}
              />
              <td>
                {item.snapshot.verified_destination_ids.length}/
                {item.snapshot.qualified_destination_ids.length}/
                {item.snapshot.selected_destination_ids.length}
                <span className="tableMeta">验证 / 合规 / 选择</span>
              </td>
              <td>{signedPercent(item.snapshot.competitive_delta)}</td>
              <td>
                {item.snapshot.eligible_sample_count}/{item.snapshot.expected_sample_count}
                <span className="tableMeta">
                  有效率：{optionalPercent(item.snapshot.valid_completion_ratio)}
                </span>
                <span className="tableMeta">
                  无效 {optionalCount(item.snapshot.invalid_sample_count)} · 缺失 {optionalCount(item.snapshot.missing_sample_count)}
                </span>
              </td>
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
        <thead><tr><th>目的地</th><th>首次验证</th><th>AI 观测</th></tr></thead>
        <tbody>
          {urls.map((item) => (
            <tr key={`${item.destination_id}-${item.url}`}>
              <td className="urlCell">
                <a href={item.url} rel="noreferrer" target="_blank">{item.title || item.url}</a>
                {item.title ? <span className="tableMeta">{item.url}</span> : null}
              </td>
              <td>{formatDate(item.first_verified_at)}</td>
              <td>{item.observation_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WindowTable({
  measurements
}: Readonly<{ measurements: CustomerApprovedMeasurement[] }>) {
  return (
    <div className="tableScroll">
      <table className="dataTable">
        <thead><tr><th>窗口</th><th>分层</th><th>状态</th><th>有效样本</th><th>计算时间</th><th>口径</th></tr></thead>
        <tbody>
          {measurements.map((item) => (
            <tr key={item.report.id}>
              <td><strong>{WINDOW_LABELS[item.snapshot.measurement_window]}</strong></td>
              <td>
                {sourceLabel(item.snapshot)}
                <span className="tableMeta">{item.snapshot.query_cluster_key || "问题簇未知"}</span>
              </td>
              <td><StatusBadge status={item.snapshot.status} /></td>
              <td>
                {item.snapshot.eligible_sample_count}/{item.snapshot.expected_sample_count}
                <span className="tableMeta">
                  有效率 {optionalPercent(item.snapshot.valid_completion_ratio)}
                </span>
              </td>
              <td>{formatDate(item.snapshot.computed_at)}</td>
              <td>{contractLabel(item)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReportItem({
  measurement
}: Readonly<{ measurement: CustomerApprovedMeasurement }>) {
  const { report, snapshot } = measurement;
  return (
    <article className="reportItem">
      <header>
        <div>
          <h3>{report.title}</h3>
          <p className="muted">
            批准时间：{formatDate(report.approved_at)} · {WINDOW_LABELS[snapshot.measurement_window]}
          </p>
        </div>
        <ContractBadge measurement={measurement} />
      </header>
      <p>{report.body}</p>
      <p className="methodNote">{report.methodology_statement}</p>
      <p className="snapshotLineage">
        快照 <code>{shortId(snapshot.id)}</code> · 协议 <code>{shortId(snapshot.protocol_id)}</code>
        {snapshot.query_cluster_key ? ` · 问题簇 ${snapshot.query_cluster_key}` : " · 问题簇未知"}
      </p>
      <p className="snapshotLineage">
        {sourceLabel(snapshot)} · 最差问题 {snapshot.worst_query_id ? shortId(snapshot.worst_query_id) : "未知"}
        {snapshot.result_hash ? ` · 结果 ${shortId(snapshot.result_hash)}` : " · 结果 hash 未知"}
      </p>
      <p className="snapshotLineage">{reproducibilityLabel(snapshot)}</p>
    </article>
  );
}

function ContractBadge({
  measurement
}: Readonly<{ measurement: CustomerApprovedMeasurement }>) {
  const legacy = measurement.snapshot_contract === "legacy_unknown";
  return (
    <span className={legacy ? "status warning" : "status"}>{contractLabel(measurement)}</span>
  );
}

function StatusBadge({ status }: Readonly<{ status: MeasurementStatus }>) {
  return (
    <span className={status === "complete" ? "status" : "status warning"}>
      {metricStatus(status)}
    </span>
  );
}

function NoApprovedReport() {
  return <EmptyData detail="当前 Campaign 暂无已批准报告。草稿和未批准快照不会显示。" />;
}

function MetricStat({ label, value }: Readonly<{ label: string; value: string }>) {
  return <div className="metricStat"><span>{label}</span><strong>{value}</strong></div>;
}

function EstimateCell({
  high,
  low,
  maximum,
  minimum,
  value
}: Readonly<{
  high: number | null;
  low: number | null;
  maximum: number | null;
  minimum: number | null;
  value: number;
}>) {
  return (
    <td>
      {percent(value)}
      <span className="tableMeta">
        95% CI：{percentageRange(low, high)}
      </span>
      <span className="tableMeta">
        每题：{percentageRange(minimum, maximum)}
      </span>
    </td>
  );
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
      <strong>{problem.status === 403 ? "无权查看所选 Campaign" : title}</strong>
      <p>{problem.detail}</p>
      {problem.request_id ? <p className="muted">请求 ID：{problem.request_id}</p> : null}
    </div>
  );
}

function orderedMeasurements(
  measurements: CustomerApprovedMeasurement[]
): CustomerApprovedMeasurement[] {
  return [...measurements].sort((left, right) => (
    WINDOW_ORDER[left.snapshot.measurement_window]
    - WINDOW_ORDER[right.snapshot.measurement_window]
  ));
}

function metricStatus(status: MeasurementStatus): string {
  if (status === "complete") return "完整";
  if (status === "insufficient_evidence") return "证据不足";
  return "混杂";
}

function contractLabel(measurement: CustomerApprovedMeasurement): string {
  return measurement.snapshot_contract === "statistics_v2" ? "统计口径 v2" : "历史口径 · 未知字段";
}

function sourceLabel(metric: CustomerGeoMetric): string {
  const source = metric.source_stratum;
  if (!source) return "来源未知";
  const model = source.reported_model.value || source.configured_model.value || "模型未披露";
  const platform = source.platform_detail
    ? `${source.platform} (${source.platform_detail})`
    : source.platform;
  const surface = source.surface_detail
    ? `${source.surface} (${source.surface_detail})`
    : source.surface;
  return `${platform} / ${surface} / ${model}`;
}

function reproducibilityLabel(metric: CustomerGeoMetric): string {
  if (
    metric.observation_membership_version
    && metric.observation_membership_hash
    && metric.observation_membership_count !== null
  ) {
    return `观测成员已冻结 · ${metric.observation_membership_count} 条 · ${shortId(metric.observation_membership_hash)}`;
  }
  return metric.statistics_contract_version === "geo-observation-statistics-v2"
    ? "历史统计 v2 · 未冻结观测成员，不可复算"
    : "历史口径 · 不可复算";
}

function percentageRange(low: number | null, high: number | null): string {
  return low === null || high === null ? "未知" : `${percent(low)}–${percent(high)}`;
}

function optionalPercent(value: number | null): string {
  return value === null ? "未知" : percent(value);
}

function optionalCount(value: number | null): string {
  return value === null ? "未知" : String(value);
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
