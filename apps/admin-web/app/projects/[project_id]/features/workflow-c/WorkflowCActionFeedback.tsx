"use client";

import type { WorkflowCActionState } from "./workflowCTypes";
import styles from "./WorkflowCAlerts.module.css";

export function WorkflowCActionFeedback({ state }: { state: WorkflowCActionState }) {
  if (state.kind === "idle") return null;
  return (
    <div
      className={`${styles.actionFeedback} ${state.kind === "error" ? styles.feedbackError : styles.feedbackSuccess}`}
      role="status"
    >
      <strong>{state.kind === "error" ? "处置未完成" : "处置已记录"}</strong>
      <span>{state.message}</span>
      {state.alert ? (
        <small>Alert {state.alert.id} · {state.alert.status} · v{state.alert.version}</small>
      ) : null}
      {state.policy ? (
        <small>
          Admission Policy {state.policy.id} · {state.policy.status} · v{state.policy.version}
        </small>
      ) : null}
      {state.correlationId ? <small>关联 ID：{state.correlationId}</small> : null}
    </div>
  );
}
