"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import styles from "./GeoWorkspace.module.css";

export type FormResult = { ok?: string; error?: string; status?: number; code?: string; correlationId?: string; retryable?: boolean; nextHref?: string; };
type FormAction = (state: FormResult, payload: FormData) => Promise<FormResult>;

export function ActionForm({ action, children, submitLabel, pendingLabel = "处理中...", title,
  disabled = false, danger = false, onSuccess, refreshOnSuccess = false }:
  { action: FormAction; children: ReactNode; submitLabel: string; pendingLabel?: string;
    title?: string; disabled?: boolean; danger?: boolean;
    onSuccess?: (result: FormResult) => void; refreshOnSuccess?: boolean; }) {
  const router = useRouter();
  const [state, setState] = useState<FormResult>({});
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  const [idempotencyKey, setIdempotencyKey] = useState("");
  useEffect(() => { setIdempotencyKey(browserUuid()); }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabled || pendingRef.current || !idempotencyKey) return;
    pendingRef.current = true;
    setPending(true);
    setState({});
    try {
      const result = await action(state, new FormData(event.currentTarget));
      setState(result);
      if (result.ok) {
        setIdempotencyKey(browserUuid());
      }
      // Release the button before refreshing the route. A refresh can take a
      // separate network round trip and must never leave the action stranded
      // in its pending presentation when the server action has completed.
      pendingRef.current = false;
      setPending(false);
      if (result.ok) {
        onSuccess?.(result);
        if (refreshOnSuccess) router.refresh();
      }
    } catch (error) {
      pendingRef.current = false;
      setPending(false);
      setState({
        error: error instanceof Error ? error.message : "操作失败，请重试。",
        retryable: true,
      });
    }
  }

  return <form onSubmit={handleSubmit} className={styles.form}>
    {title ? <h3>{title}</h3> : null}
    <input type="hidden" name="idempotency_key" value={idempotencyKey} />
    {children}
    <button
      className={danger ? "button danger" : "button"}
      type="submit"
      disabled={disabled || pending || !idempotencyKey}
    >
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

function browserUuid(): string {
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
}
