import type { SyntheticActionState } from "./syntheticLabTypes";
import styles from "./SyntheticLab.module.css";

export function SyntheticActionFeedback({ state }: { state: SyntheticActionState }) {
  if (state.kind === "idle") return null;
  return (
    <div
      className={state.kind === "error" ? styles.errorFeedback : styles.successFeedback}
      role={state.kind === "error" ? "alert" : "status"}
    >
      <strong>{state.status ? `${state.status} · ` : ""}{state.message}</strong>
      {state.correlationId ? <small>关联 ID：{state.correlationId}</small> : null}
      {state.job ? (
        <dl className={styles.feedbackMetadata}>
          <div><dt>Job</dt><dd><code>{state.job.id}</code></dd></div>
          <div><dt>Kind / status</dt><dd>{state.job.kind} · {state.job.status}</dd></div>
          <div><dt>Input hash</dt><dd><code>{state.job.input_hash}</code></dd></div>
        </dl>
      ) : null}
      {state.importResult ? (
        <dl className={styles.feedbackMetadata}>
          <div><dt>Rows</dt><dd>{state.importResult.row_count}</dd></div>
          <div><dt>Accepted / rejected</dt><dd>{state.importResult.accepted_count} / {state.importResult.rejected_count}</dd></div>
          <div><dt>Manifest hash</dt><dd><code>{state.importResult.manifest_hash}</code></dd></div>
        </dl>
      ) : null}
      {state.nextHref ? <a className={styles.resultLink} href={state.nextHref}>打开 Job</a> : null}
    </div>
  );
}
