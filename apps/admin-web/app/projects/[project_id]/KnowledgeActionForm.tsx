"use client";

import { useActionState, type ReactNode } from "react";
import type { KnowledgeActionState } from "./knowledgeTypes";
import styles from "./KnowledgeWorkspace.module.css";

const initial: KnowledgeActionState = { kind: "idle", message: "" };

export function KnowledgeActionForm({
  action,
  children,
  className,
  submitLabel
}: {
  action: (state: KnowledgeActionState, form: FormData) => Promise<KnowledgeActionState>;
  children: ReactNode;
  className?: string;
  submitLabel: string;
}) {
  const [state, formAction, pending] = useActionState(action, initial);
  return (
    <form action={formAction} className={className || styles.form}>
      {children}
      <button disabled={pending} type="submit">{pending ? "处理中..." : submitLabel}</button>
      {state.kind !== "idle" ? (
        <p className={state.kind === "error" ? styles.error : styles.success} role={state.kind === "error" ? "alert" : "status"}>
          {state.message}{state.correlationId ? ` · ${state.correlationId}` : ""}
        </p>
      ) : null}
    </form>
  );
}
