import type { RecommendationActionState } from "./recommendationTypes";
import styles from "./Recommendations.module.css";

export function RecommendationActionFeedback({
  state
}: {
  state: RecommendationActionState;
}) {
  if (state.kind === "idle") return null;
  return (
    <div
      className={`${styles.actionFeedback} ${state.kind === "error" ? styles.feedbackError : styles.feedbackSuccess}`}
      role={state.kind === "error" ? "alert" : "status"}
    >
      <strong>{state.kind === "error" ? failureHeading(state.status) : state.message}</strong>
      {state.kind === "error" ? <span>{state.message}</span> : null}
      {state.recommendation ? (
        <dl className={styles.feedbackFacts}>
          <Fact label="建议" value={state.recommendation.id} />
          <Fact
            label="状态 / 版本"
            value={`${state.recommendation.status} / v${state.recommendation.version}`}
          />
          <Fact label="证据图谱 SHA-256" value={state.recommendation.evidenceGraphHash} />
        </dl>
      ) : null}
      {state.draft ? (
        <dl className={styles.feedbackFacts}>
          <Fact label="草稿" value={`${state.draft.kind} · ${state.draft.id}`} />
          <Fact label="草稿状态" value={state.draft.status} />
          {state.draft.authorized !== undefined ? (
            <Fact label="来源复核" value={state.draft.authorized ? "通过" : "未通过"} />
          ) : null}
        </dl>
      ) : null}
      {state.actionBoundary ? (
        <span className={styles.boundaryResult}>{boundaryLabel(state.actionBoundary)}</span>
      ) : null}
      {state.cancelledOutboxCount !== undefined ? (
        <small>已取消 {state.cancelledOutboxCount} 条尚未发布的 outbox 记录。</small>
      ) : null}
      {state.correlationId ? <small>关联 ID：{state.correlationId}</small> : null}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd><code>{value}</code></dd></div>;
}

function failureHeading(status: number | undefined): string {
  return status ? `操作未完成 · HTTP ${status}` : "操作未完成";
}

function boundaryLabel(value: NonNullable<RecommendationActionState["actionBoundary"]>): string {
  if (value === "draft_only_unstarted") return "边界：仅创建未启动草稿，未执行、未发布。";
  return "边界：来源已复核，但草稿仍未执行、未发布。";
}
