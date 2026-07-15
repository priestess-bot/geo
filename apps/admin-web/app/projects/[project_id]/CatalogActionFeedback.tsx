"use client";

import type { CatalogActionState } from "./catalogTypes";
import styles from "./Catalog.module.css";

export function CatalogActionFeedback({ state }: { state: CatalogActionState }) {
  if (state.kind === "idle") return null;
  return (
    <div
      className={state.kind === "error" ? styles.error : styles.success}
      role={state.kind === "error" ? "alert" : "status"}
      aria-live="polite"
    >
      <strong>{state.kind === "error" ? errorTitle(state.status) : "操作完成"}</strong>
      <span>{state.message}</span>
      {state.correlationId ? <small>关联 ID：{state.correlationId}</small> : null}
    </div>
  );
}

function errorTitle(status: number | undefined): string {
  if (status === 401) return "登录已失效";
  if (status === 403) return "无权执行此操作";
  if (status === 409) return "资源状态冲突";
  if (status === 422) return "提交内容无效";
  return "操作失败";
}
