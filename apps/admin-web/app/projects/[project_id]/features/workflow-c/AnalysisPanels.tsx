import {
  EmptyState,
  Fact,
  LoadProblem,
  SectionHeading,
  conclusionLabel
} from "./WorkflowCWorkspace";
import type {
  ComparisonFamily,
  DriftReport,
  EvidenceConclusion,
  Resource,
  SemanticMetricSnapshot
} from "./workflowCTypes";
import styles from "./WorkflowC.module.css";

export function MetricsPanel({ resource }: { resource: Resource<SemanticMetricSnapshot> }) {
  if (resource.problem) return <LoadProblem label="语义指标快照" problem={resource.problem} />;
  if (!resource.data) return <EmptyState title="未选择指标快照" />;
  const data = resource.data;
  const negative = data.performance.negative_gain;
  return (
    <div className={styles.sectionStack}>
      <section>
        <SectionHeading eyebrow="语义指标" title={`快照 ${data.snapshot_hash}`} />
        <dl className={styles.factGrid}>
          <Fact label="计算时间" value={formatTime(data.computed_at)} />
          <Fact label="最差问题" value={`${data.performance.worst_question_id} · ${data.performance.worst_question_score}`} />
          <Fact label="最差聚类" value={`${data.performance.worst_cluster} · ${data.performance.worst_cluster_score}`} />
          <Fact label="输入集 SHA-256" value={data.input_set_hash} />
          <Fact label="采样套件 SHA-256" value={data.suite_hash} />
          <Fact label="来源分层 SHA-256" value={data.stratum_hash} />
        </dl>
        {negative ? (
          <div className={styles.negativeBand}>
            <div><span>受影响问题</span><strong>{negative.affected_question_count} / {negative.compared_question_count}</strong></div>
            <div><span>平均负向收益</span><strong>{negative.mean_negative_gain}</strong></div>
            <div><span>观测范围</span><strong>[{negative.range_low}, {negative.range_high}]</strong></div>
            <div><span>最差差值</span><strong>{negative.worst_question_id || "-"} · {negative.worst_question_delta || "-"}</strong></div>
          </div>
        ) : null}
      </section>
      <section>
        <SectionHeading eyebrow="冻结清单" title={`${data.results.length} 项指标`} />
        <div className={styles.tableWrap}>
          <table className={styles.dataTable}>
            <thead><tr><th>指标</th><th>状态</th><th>估计值</th><th>区间</th><th>有效 / 无效 / 缺失</th><th>证据</th></tr></thead>
            <tbody>{data.results.map((metric) => (
              <tr key={metric.metric_key}>
                <td><strong>{metricLabel(metric.metric_key)}</strong><small>{metric.metric_version} · {metric.value_kind}</small></td>
                <td><Status value={metric.status} /></td>
                <td>{metric.estimate}<small>{metric.numerator} / {metric.denominator}</small></td>
                <td>[{metric.interval.low}, {metric.interval.high}]<small>{metric.interval.method}</small></td>
                <td>{metric.valid_input_count} / {metric.invalid_input_count} / {metric.missing_input_count}</td>
                <td>{metric.evidence_locators.length}<small>{metric.judge_version || "确定性"}</small></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
      <section>
        <SectionHeading eyebrow="证据定位" title="指标证据" />
        <div className={styles.locatorList}>
          {data.results.map((metric) => (
            <details key={metric.metric_key}>
              <summary><span>{metricLabel(metric.metric_key)}</span><strong>{metric.evidence_locators.length} 条定位记录</strong></summary>
              {metric.evidence_locators.length ? (
                <ul>{metric.evidence_locators.map((locator, index) => (
                  <li key={`${locator.kind}-${locator.reference_id}-${index}`}>
                    <span>{locator.kind}</span>
                    <code>{locator.reference_id}</code>
                    <small>{evidenceLocatorLabel(locator)}</small>
                    {locator.content_hash ? <code>{locator.content_hash}</code> : null}
                    {locator.redacted_quote_hash ? (
                      <small>脱敏摘录 SHA-256：{locator.redacted_quote_hash}</small>
                    ) : null}
                  </li>
                ))}</ul>
              ) : <p>无定位记录。</p>}
              {Object.keys(metric.breakdown).length ? (
                <dl className={styles.compactFacts}>{Object.entries(metric.breakdown).map(([key, value]) => <Fact key={key} label={key} value={value} />)}</dl>
              ) : null}
              <code>{metric.result_hash}</code>
            </details>
          ))}
        </div>
      </section>
    </div>
  );
}

function evidenceLocatorLabel(locator: {
  version: string | null;
  start: number | null;
  end: number | null;
}): string {
  const offsetRange = range(locator.start, locator.end);
  return locator.version ? `${locator.version} · ${offsetRange}` : offsetRange;
}

export function ComparisonPanel({ resource }: { resource: Resource<ComparisonFamily> }) {
  if (resource.problem) return <LoadProblem label="比较族" problem={resource.problem} />;
  if (!resource.data) return <EmptyState title="未选择比较族" />;
  const data = resource.data;
  return (
    <div className={styles.sectionStack}>
      <section>
        <SectionHeading eyebrow="配对比较" title={data.family} />
        <div className={styles.conclusionLegend} aria-label="比较结论">
          {(["win", "equivalent", "loss", "inconclusive", "insufficient_evidence"] as EvidenceConclusion[]).map((value) => (
            <Status key={value} label={conclusionLabel(value)} value={value} />
          ))}
        </div>
        <dl className={styles.factGrid}>
          <Fact label="比较族 SHA-256" value={data.family_hash} />
          <Fact label="显著性水平" value={data.alpha} />
          <Fact label="校正方法" value={data.correction_method} />
        </dl>
      </section>
      <section>
        <div className={styles.tableWrap}>
          <table className={styles.dataTable}>
            <thead><tr><th>比较</th><th>结论</th><th>效应</th><th>校正后区间</th><th>完成度</th><th>功效</th><th>校正后 p 值</th></tr></thead>
            <tbody>{data.results.map((result) => (
              <tr key={result.comparison_id}>
                <td><strong>{result.comparison_id}</strong><code>{result.result_hash}</code></td>
                <td><Status label={conclusionLabel(result.conclusion)} value={result.conclusion} /></td>
                <td>{result.point_estimate}</td>
                <td>[{result.adjusted_interval.low}, {result.adjusted_interval.high}]<small>{result.adjusted_interval.method}</small></td>
                <td>{percent(result.completion_ratio)}<small>{result.valid_pair_count} / {result.planned_pair_count} 对</small></td>
                <td>{result.a_priori_design_power} · {result.power_method_version}<code>{result.power_plan_hash}</code></td>
                <td>{result.adjusted_p_value}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export function DriftPanel({ resource }: { resource: Resource<DriftReport> }) {
  if (resource.problem) return <LoadProblem label="漂移报告" problem={resource.problem} />;
  if (!resource.data) return <EmptyState title="未选择漂移报告" />;
  const data = resource.data;
  return (
    <div className={styles.sectionStack}>
      <section>
        <SectionHeading eyebrow="严格分层漂移" title={`报告 ${data.report_hash}`} />
        <div className={styles.denominatorBand}>
          <Signal label="模型" value={data.model_drift.length} tone="warning" />
          <Signal label="来源" value={data.source_drift.length} tone="warning" />
          <Signal label="效应" value={data.effect_drift.length} tone="bad" />
          <Signal label="未匹配基线" value={data.unmatched_baseline_strata.length} />
          <Signal label="未匹配当前" value={data.unmatched_current_strata.length} />
        </div>
        <dl className={styles.factGrid}>
          <Fact label="方法" value={data.method_version} />
          <Fact label="基线 SHA-256" value={data.baseline_input_hash} />
          <Fact label="当前 SHA-256" value={data.current_input_hash} />
        </dl>
      </section>
      <DriftGroup label="模型漂移" values={data.model_drift} />
      <DriftGroup label="来源构成漂移" values={data.source_drift} />
      <DriftGroup label="效应漂移" values={data.effect_drift} />
      <section className={styles.unmatchedGrid}>
        <StringList label="仅基线存在的分层" values={data.unmatched_baseline_strata} />
        <StringList label="仅当前存在的分层" values={data.unmatched_current_strata} />
      </section>
    </div>
  );
}

function DriftGroup({ label, values }: { label: string; values: Array<Record<string, unknown>> }) {
  return (
    <section>
      <SectionHeading eyebrow="漂移信号" title={label} />
      {values.length ? <div className={styles.driftList}>{values.map((value, index) => (
        <dl key={`${label}-${index}`}>{Object.entries(value).map(([key, item]) => (
          <Fact key={key} label={key} value={displayValue(item)} />
        ))}</dl>
      ))}</div> : <EmptyState title={`${label} 无信号`} />}
    </section>
  );
}

function StringList({ label, values }: { label: string; values: string[] }) {
  return <div><h3>{label}</h3>{values.length ? <ul>{values.map((value) => <li key={value}><code>{value}</code></li>)}</ul> : <p>无</p>}</div>;
}

function Signal({ label, tone, value }: { label: string; tone?: string; value: number }) {
  return <div data-tone={tone}><span>{label}</span><strong>{value}</strong></div>;
}

function Status({ label, value }: { label?: string; value: string }) {
  return <span className={styles.status} data-status={value}>{label || statusLabel(value)}</span>;
}

function range(start: number | null, end: number | null): string {
  return start === null || end === null ? "-" : `${start}:${end}`;
}

function metricLabel(value: string): string {
  return ({ mention_rate: "提及率", recommendation_rate: "推荐率", competitor_relative_position: "竞品相对位置", sentiment: "情感倾向", source_domain_diversity: "来源域名多样性", source_type_diversity: "来源类型多样性", fact_accuracy: "事实准确性", omission_rate: "遗漏率", citation_entailment: "引用蕴含度", citation_position: "引用位置", answer_absorption: "答案吸收度" } as Record<string, string>)[value] || value.replaceAll("_", " ");
}

function statusLabel(value: string): string {
  return ({ complete: "已完成", insufficient_evidence: "证据不足", eligible: "合格", ineligible: "不合格", pending: "待处理", running: "运行中", failed: "失败", win: "胜出", loss: "负向", equivalent: "达到等效门槛", inconclusive: "不确定" } as Record<string, string>)[value] || value.replaceAll("_", " ");
}

function percent(value: string): string {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : value;
}

function displayValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN");
}
