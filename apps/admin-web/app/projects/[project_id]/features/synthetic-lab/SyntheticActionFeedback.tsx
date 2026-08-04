import Link from "next/link";

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
          <div><dt>任务</dt><dd><code>{state.job.id}</code></dd></div>
          <div><dt>类型 / 状态</dt><dd>{state.job.kind} · {state.job.status}</dd></div>
          <div><dt>输入哈希</dt><dd><code>{state.job.input_hash}</code></dd></div>
        </dl>
      ) : null}
      {state.importResult ? (
        <dl className={styles.feedbackMetadata}>
          <div><dt>行数</dt><dd>{state.importResult.row_count}</dd></div>
          <div><dt>已接受 / 已拒绝</dt><dd>{state.importResult.accepted_count} / {state.importResult.rejected_count}</dd></div>
          <div><dt>清单哈希</dt><dd><code>{state.importResult.manifest_hash}</code></dd></div>
        </dl>
      ) : null}
      {state.nextHref ? (
        <Link className={styles.resultLink} href={state.nextHref} scroll={false}>
          查看任务与结果
        </Link>
      ) : null}
    </div>
  );
}
