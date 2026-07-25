import type { BinaryEstimateView, MetricView } from "@geo/types/geo";

import { Status, TechnicalInfo } from "./common";
import styles from "./GeoWorkspace.module.css";

export function MonitoringMetricSnapshot({ metric }: { metric: MetricView }) {
  const worstQuery = metric.query_results.find(
    (item) => item.monitoring_query_id === metric.worst_query_id
  );
  const invalidReasons = Object.entries(metric.invalid_reason_counts);
  const confounders = Array.from(new Set([
    ...metric.declared_confounding_factors,
    ...metric.confounded_reasons
  ]));
  return <article className={styles.metricSnapshot} data-testid="monitoring-metric-snapshot">
    <header className={styles.rowHeader}>
      <strong>{metric.measurement_window} · {metric.query_cluster_key || "历史问题簇未知"}</strong>
      <Status value={metric.status} />
    </header>
    {metric.status === "insufficient_evidence" ? <div className={styles.metricWarning}>
      有效重复未达到冻结门槛，本快照不作趋势判断。
    </div> : null}
    <div className={styles.keyValues}>
      <MetricValue label="已采样" value={count(metric.sampled_sample_count)} />
      <MetricValue label="有效" value={count(metric.eligible_sample_count)} />
      <MetricValue label="无效" value={count(metric.invalid_sample_count)} />
      <MetricValue label="缺失" value={count(metric.missing_sample_count)} />
      <MetricValue label="有效门槛" value={count(metric.minimum_valid_repeats)} />
      <MetricValue label="问题达标" value={`${count(metric.sufficient_query_count)} / ${count(metric.query_count)}`} />
      <MetricValue label="采样完成度" value={percent(metric.sampling_completion_ratio)} />
      <MetricValue label="有效完成度" value={percent(metric.valid_completion_ratio)} />
    </div>
    <table className={styles.table}>
      <thead><tr><th>指标</th><th>估计值</th><th>Wilson 95% CI</th><th>问题区间</th></tr></thead>
      <tbody>
        <IntervalRow label="推荐出现" share={metric.recommendation_share}
          low={metric.recommendation_ci_low} high={metric.recommendation_ci_high}
          queryMin={metric.recommendation_query_min} queryMax={metric.recommendation_query_max} />
        <IntervalRow label="产品提及" share={metric.product_mention_share}
          low={metric.product_mention_ci_low} high={metric.product_mention_ci_high}
          queryMin={metric.product_mention_query_min} queryMax={metric.product_mention_query_max} />
        <IntervalRow label="已验证引用" share={metric.placement_citation_share}
          low={metric.placement_citation_ci_low} high={metric.placement_citation_ci_high}
          queryMin={metric.placement_citation_query_min} queryMax={metric.placement_citation_query_max} />
      </tbody>
    </table>
    <div className={styles.metricEvidence}>
      <div><span>无效原因</span><strong>{invalidReasons.length
        ? invalidReasons.map(([reason, total]) => `${reasonLabel(reason)} ${total}`).join(" · ")
        : "无"}</strong></div>
      <div><span>混杂因素</span><strong>{confounders.length
        ? confounders.map(reasonLabel).join(" · ")
        : "无"}</strong></div>
      <div><span>最弱问题</span><strong>{worstQuery?.query_text_snapshot || metric.worst_query_id || "未记录"}</strong></div>
    </div>
    {metric.query_results.length ? <details className={styles.metricDetails}>
      <summary>逐问题分母与区间</summary>
      <table className={styles.table}>
        <thead><tr><th>冻结问题</th><th>样本</th><th>推荐 Wilson CI</th><th>产品提及</th><th>引用</th></tr></thead>
        <tbody>{metric.query_results.map((query) => <tr key={query.monitoring_query_id}>
          <td><strong>{query.query_text_snapshot}</strong><div className={styles.meta}>{query.query_cluster_key}</div></td>
          <td>{query.sampled_sample_count} 已采样 · {query.valid_sample_count} 有效 · {query.invalid_sample_count} 无效 · {query.missing_sample_count} 缺失<div className={styles.meta}>{query.meets_threshold ? "达到门槛" : "未达到门槛"}</div></td>
          <td>{estimate(query.recommendation)}</td>
          <td>{estimate(query.product_mention)}</td>
          <td>{estimate(query.placement_citation)}</td>
        </tr>)}</tbody>
      </table>
    </details> : null}
    <TechnicalInfo label="指标审计信息">
      <code>结果 {metric.result_hash || "历史结果哈希不可用"}</code>
      <code>输入 {metric.input_hash}</code>
      <code>分析 {metric.analysis_stratum_hash || "历史分析哈希不可用"}</code>
      <code>观察记录 {metric.observation_membership_hash || "历史成员记录不可用"}</code>
      <span>{metric.observation_membership_version || "历史成员版本不可用"} · {count(metric.observation_membership_count)} 条观察记录</span>
      <span>{metric.statistics_contract_version} · {metric.method_version}</span>
      <span>{new Date(metric.computed_at).toLocaleString("zh-CN")}</span>
    </TechnicalInfo>
  </article>;
}

function MetricValue({ label, value }: { label: string; value: string }) {
  return <div><span className={styles.meta}>{label}</span><br /><strong>{value}</strong></div>;
}

function IntervalRow({ label, share, low, high, queryMin, queryMax }: {
  label: string; share: number; low: number | null; high: number | null;
  queryMin: number | null; queryMax: number | null;
}) {
  return <tr><td><strong>{label}</strong></td><td>{percent(share)}</td>
    <td>{interval(low, high)}</td><td>{interval(queryMin, queryMax)}</td></tr>;
}

function estimate(value: BinaryEstimateView): string {
  return `${value.numerator}/${value.denominator} · ${percent(value.share)} · ${interval(value.ci_low, value.ci_high)}`;
}

function count(value: number | null): string {
  return value === null ? "-" : String(value);
}

function percent(value: number | null): string {
  return value === null ? "-" : `${(value * 100).toFixed(1)}%`;
}

function interval(low: number | null, high: number | null): string {
  return low === null || high === null ? "-" : `${percent(low)} - ${percent(high)}`;
}

function reasonLabel(value: string): string {
  return ({
    result_failed: "采集失败",
    requested_ineligible: "人工标记无效",
    source_stratum_mismatch: "来源分层不匹配",
    query_cluster_mismatch: "问题簇不匹配",
    declared_confounding_factors: "声明了混杂因素",
    insufficient_valid_repeats: "有效重复不足"
  } as Record<string, string>)[value] || value.replaceAll("_", " ");
}
