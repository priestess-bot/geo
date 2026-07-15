"use client";

import type { MemberActionState } from "./memberTypes";
import styles from "./MemberGovernance.module.css";

export function MemberActionFeedback({ state }: { state: MemberActionState }) {
  if (state.kind === "idle") return null;
  return (
    <div
      className={state.kind === "error" ? styles.errorFeedback : styles.successFeedback}
      aria-live="polite"
      role={state.kind === "error" ? "alert" : "status"}
    >
      <span>{state.message}</span>
      {state.correlationId ? <small>关联 ID：{state.correlationId}</small> : null}
    </div>
  );
}
