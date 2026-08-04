import type { WarningSummary } from "./syntheticLabTypes";
import styles from "./SyntheticLab.module.css";

const strata: ReadonlyArray<readonly [keyof WarningSummary, string]> = [
  ["by_code", "提醒类型"],
  ["by_channel", "渠道"],
  ["by_scenario_mode", "场景模式"],
  ["by_competitor", "竞品场景"],
  ["by_model", "模型"],
  ["by_question_cluster", "问题簇"]
];

export function SyntheticLabWarnings({ summary }: { summary?: WarningSummary }) {
  return (
    <section className={styles.warningSection} aria-labelledby="synthetic-warning-heading">
      <div className={styles.sectionHeading}>
        <div><p>必需证据</p><h3 id="synthetic-warning-heading">警告数量、占比与分层</h3></div>
        <span className={styles.evidenceState}>{summary ? "已有分层证据" : "暂无分层证据"}</span>
      </div>
      <div className={styles.warningTotals}>
        <Metric label="警告数量" value={summary ? String(summary.warning_count) : "--"} />
        <Metric label="候选总数" value={summary ? String(summary.candidate_count) : "--"} />
        <Metric label="警告占比" value={summary ? formatRatio(summary.warning_ratio) : "--"} />
      </div>
      {!summary ? (
        <p className={styles.unknownEvidence}>暂无可分层的提醒证据；不会将缺失证据记为 0。</p>
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
    <section className={styles.stratum} aria-label={`${label}提醒分层`}>
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
