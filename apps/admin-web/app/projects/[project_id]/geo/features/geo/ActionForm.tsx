"use client";

import Link from "next/link";
import { useActionState, useEffect, useState, type ReactNode } from "react";
import styles from "./GeoWorkspace.module.css";

export type FormResult = { ok?: string; error?: string; status?: number; code?: string; correlationId?: string; retryable?: boolean; nextHref?: string; };
type FormAction = (state: FormResult, payload: FormData) => Promise<FormResult>;

export function ActionForm({ action, children, submitLabel, pendingLabel = "处理中...", title, disabled = false, danger = false }:
  { action: FormAction; children: ReactNode; submitLabel: string; pendingLabel?: string; title?: string; disabled?: boolean; danger?: boolean; }) {
  const [state, formAction, pending] = useActionState(action, {});
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  useEffect(() => { if (state.ok) setIdempotencyKey(crypto.randomUUID()); }, [state.ok]);
  return <form action={formAction} className={styles.form}>
    {title ? <h3>{title}</h3> : null}
    <input type="hidden" name="idempotency_key" value={idempotencyKey} />
    {children}
    <button className={danger ? "button danger" : "button"} type="submit" disabled={disabled || pending}>
      {pending ? pendingLabel : submitLabel}
    </button>
    {state.ok ? <p className={styles.success} role="status">{state.ok}{state.nextHref ? <> · <Link href={state.nextHref}>打开结果</Link></> : null}</p> : null}
    {state.error ? <div className={styles.actionError} role="alert">
      <strong>{state.status === 403 ? "权限不足" : state.status === 409 ? "状态冲突" : state.status === 422 ? "输入未通过校验" : "操作失败"}</strong>
      <span>{state.error}</span>
      {state.correlationId ? <code>Correlation {state.correlationId}</code> : null}
      {state.retryable ? <span>当前错误可重试，请检查输入后再次提交。</span> : null}
    </div> : null}
  </form>;
}
