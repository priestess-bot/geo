import type { WarningSummary } from "./syntheticLabTypes";
import styles from "./SyntheticLab.module.css";

const strata: ReadonlyArray<readonly [keyof WarningSummary, string]> = [
  ["by_code", "Warning code"],
  ["by_channel", "Channel"],
  ["by_scenario_mode", "Scenario mode"],
  ["by_competitor", "Competitor"],
  ["by_model", "Model"],
  ["by_question_cluster", "Question cluster"]
];

export function SyntheticLabWarnings({ summary }: { summary?: WarningSummary }) {
  return (
    <section className={styles.warningSection} aria-labelledby="synthetic-warning-heading">
      <div className={styles.sectionHeading}>
        <div><p>Required evidence</p><h3 id="synthetic-warning-heading">Warning 数量、占比与分层</h3></div>
        <span className={styles.evidenceState}>{summary ? "evidence available" : "evidence unavailable"}</span>
      </div>
      <div className={styles.warningTotals}>
        <Metric label="Warning 数量" value={summary ? String(summary.warning_count) : "--"} />
        <Metric label="候选总数" value={summary ? String(summary.candidate_count) : "--"} />
        <Metric label="Warning 占比" value={summary ? formatRatio(summary.warning_ratio) : "--"} />
      </div>
      {!summary ? (
        <p className={styles.unknownEvidence}>暂无可分层 warning evidence；不会将缺失证据记为 0。</p>
      ) : null}
      <div className={styles.strataGrid}>
        {strata.map(([key, label]) => (
          <Stratum key={key} label={label} values={summary?.[key] as Readonly<Record<string, number>> | undefined} />
        ))}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function Stratum({ label, values }: { label: string; values?: Readonly<Record<string, number>> }) {
  const rows = Object.entries(values || {});
  return (
    <section className={styles.stratum} aria-label={`${label} warning 分层`}>
      <h4>{label}</h4>
      {rows.length ? (
        <dl>{rows.map(([key, count]) => <div key={key}><dt>{key}</dt><dd>{count}</dd></div>)}</dl>
      ) : <span>无证据</span>}
    </section>
  );
}

function formatRatio(value: number): string {
  return `${(value * 100).toFixed(value * 100 % 1 === 0 ? 0 : 1)}%`;
}
