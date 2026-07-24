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
  if (resource.problem) return <LoadProblem label="Semantic Metric Snapshot" problem={resource.problem} />;
  if (!resource.data) return <EmptyState title="Metric Snapshot 未选择" />;
  const data = resource.data;
  const negative = data.performance.negative_gain;
  return (
    <div className={styles.sectionStack}>
      <section>
        <SectionHeading eyebrow="Semantic metrics" title={`Snapshot ${data.snapshot_hash}`} />
        <dl className={styles.factGrid}>
          <Fact label="Computed" value={formatTime(data.computed_at)} />
          <Fact label="Worst question" value={`${data.performance.worst_question_id} · ${data.performance.worst_question_score}`} />
          <Fact label="Worst cluster" value={`${data.performance.worst_cluster} · ${data.performance.worst_cluster_score}`} />
          <Fact label="Input Set SHA-256" value={data.input_set_hash} />
          <Fact label="Suite SHA-256" value={data.suite_hash} />
          <Fact label="SourceStratum SHA-256" value={data.stratum_hash} />
        </dl>
        {negative ? (
          <div className={styles.negativeBand}>
            <div><span>Affected questions</span><strong>{negative.affected_question_count} / {negative.compared_question_count}</strong></div>
            <div><span>Mean negative gain</span><strong>{negative.mean_negative_gain}</strong></div>
            <div><span>Observed range</span><strong>[{negative.range_low}, {negative.range_high}]</strong></div>
            <div><span>Worst delta</span><strong>{negative.worst_question_id || "-"} · {negative.worst_question_delta || "-"}</strong></div>
          </div>
        ) : null}
      </section>
      <section>
        <SectionHeading eyebrow="Frozen inventory" title={`${data.results.length} metrics`} />
        <div className={styles.tableWrap}>
          <table className={styles.dataTable}>
            <thead><tr><th>Metric</th><th>Status</th><th>Estimate</th><th>Interval</th><th>Valid / Invalid / Missing</th><th>Evidence</th></tr></thead>
            <tbody>{data.results.map((metric) => (
              <tr key={metric.metric_key}>
                <td><strong>{metricLabel(metric.metric_key)}</strong><small>{metric.metric_version} · {metric.value_kind}</small></td>
                <td><Status value={metric.status} /></td>
                <td>{metric.estimate}<small>{metric.numerator} / {metric.denominator}</small></td>
                <td>[{metric.interval.low}, {metric.interval.high}]<small>{metric.interval.method}</small></td>
                <td>{metric.valid_input_count} / {metric.invalid_input_count} / {metric.missing_input_count}</td>
                <td>{metric.evidence_locators.length}<small>{metric.judge_version || "deterministic"}</small></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
      <section>
        <SectionHeading eyebrow="Evidence locators" title="Metric evidence" />
        <div className={styles.locatorList}>
          {data.results.map((metric) => (
            <details key={metric.metric_key}>
              <summary><span>{metricLabel(metric.metric_key)}</span><strong>{metric.evidence_locators.length} locators</strong></summary>
              {metric.evidence_locators.length ? (
                <ul>{metric.evidence_locators.map((locator, index) => (
                  <li key={`${locator.kind}-${locator.reference_id}-${index}`}>
                    <span>{locator.kind}</span>
                    <code>{locator.reference_id}</code>
                    <small>{evidenceLocatorLabel(locator)}</small>
                    {locator.content_hash ? <code>{locator.content_hash}</code> : null}
                    {locator.redacted_quote_hash ? (
                      <small>Redacted excerpt SHA-256: {locator.redacted_quote_hash}</small>
                    ) : null}
                  </li>
                ))}</ul>
              ) : <p>无 locator。</p>}
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
  if (resource.problem) return <LoadProblem label="Comparison Family" problem={resource.problem} />;
  if (!resource.data) return <EmptyState title="Comparison Family 未选择" />;
  const data = resource.data;
  return (
    <div className={styles.sectionStack}>
      <section>
        <SectionHeading eyebrow="Paired comparison" title={data.family} />
        <div className={styles.conclusionLegend} aria-label="比较结论">
          {(["win", "equivalent", "loss", "inconclusive", "insufficient_evidence"] as EvidenceConclusion[]).map((value) => (
            <Status key={value} label={conclusionLabel(value)} value={value} />
          ))}
        </div>
        <dl className={styles.factGrid}>
          <Fact label="Family SHA-256" value={data.family_hash} />
          <Fact label="Alpha" value={data.alpha} />
          <Fact label="Correction" value={data.correction_method} />
        </dl>
      </section>
      <section>
        <div className={styles.tableWrap}>
          <table className={styles.dataTable}>
            <thead><tr><th>Comparison</th><th>Conclusion</th><th>Effect</th><th>Adjusted interval</th><th>Completion</th><th>Power</th><th>p adjusted</th></tr></thead>
            <tbody>{data.results.map((result) => (
              <tr key={result.comparison_id}>
                <td><strong>{result.comparison_id}</strong><code>{result.result_hash}</code></td>
                <td><Status label={conclusionLabel(result.conclusion)} value={result.conclusion} /></td>
                <td>{result.point_estimate}</td>
                <td>[{result.adjusted_interval.low}, {result.adjusted_interval.high}]<small>{result.adjusted_interval.method}</small></td>
                <td>{percent(result.completion_ratio)}<small>{result.valid_pair_count} / {result.planned_pair_count} pairs</small></td>
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
  if (resource.problem) return <LoadProblem label="Drift Report" problem={resource.problem} />;
  if (!resource.data) return <EmptyState title="Drift Report 未选择" />;
  const data = resource.data;
  return (
    <div className={styles.sectionStack}>
      <section>
        <SectionHeading eyebrow="Strict-stratum drift" title={`Report ${data.report_hash}`} />
        <div className={styles.denominatorBand}>
          <Signal label="Model" value={data.model_drift.length} tone="warning" />
          <Signal label="Source" value={data.source_drift.length} tone="warning" />
          <Signal label="Effect" value={data.effect_drift.length} tone="bad" />
          <Signal label="Unmatched baseline" value={data.unmatched_baseline_strata.length} />
          <Signal label="Unmatched current" value={data.unmatched_current_strata.length} />
        </div>
        <dl className={styles.factGrid}>
          <Fact label="Method" value={data.method_version} />
          <Fact label="Baseline SHA-256" value={data.baseline_input_hash} />
          <Fact label="Current SHA-256" value={data.current_input_hash} />
        </dl>
      </section>
      <DriftGroup label="Model drift" values={data.model_drift} />
      <DriftGroup label="Source composition drift" values={data.source_drift} />
      <DriftGroup label="Effect drift" values={data.effect_drift} />
      <section className={styles.unmatchedGrid}>
        <StringList label="Baseline-only strata" values={data.unmatched_baseline_strata} />
        <StringList label="Current-only strata" values={data.unmatched_current_strata} />
      </section>
    </div>
  );
}

function DriftGroup({ label, values }: { label: string; values: Array<Record<string, unknown>> }) {
  return (
    <section>
      <SectionHeading eyebrow="Drift signals" title={label} />
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
  return <span className={styles.status} data-status={value}>{label || value.replaceAll("_", " ")}</span>;
}

function range(start: number | null, end: number | null): string {
  return start === null || end === null ? "-" : `${start}:${end}`;
}

function metricLabel(value: string): string {
  return value.replaceAll("_", " ");
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
