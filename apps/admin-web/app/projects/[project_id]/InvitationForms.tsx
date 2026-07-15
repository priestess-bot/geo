"use client";

import { useActionState } from "react";

import {
  createInvitationAction,
  revokeInvitationAction
} from "./invitationActions";
import {
  initialInvitationActionState,
  type InvitationActionState
} from "./invitationTypes";
import styles from "./Catalog.module.css";

export function InvitationCreateForm({
  idempotencyKey,
  projectId
}: {
  idempotencyKey: string;
  projectId: string;
}) {
  const [state, action, pending] = useActionState(
    createInvitationAction,
    initialInvitationActionState
  );
  return (
    <form action={action} className={styles.form}>
      <input type="hidden" name="project_id" value={projectId} />
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <div className={styles.formGrid}>
        <label className={styles.wide}>
          <span>客户邮箱</span>
          <input name="email" type="email" autoComplete="email" required />
        </label>
      </div>
      <div className={styles.formActions}>
        <button type="submit" disabled={pending}>{pending ? "创建中..." : "创建客户邀请"}</button>
      </div>
      <InvitationFeedback state={state} />
    </form>
  );
}

export function InvitationRevokeForm({
  invitationId,
  projectId
}: {
  invitationId: string;
  projectId: string;
}) {
  const [state, action, pending] = useActionState(
    revokeInvitationAction,
    initialInvitationActionState
  );
  return (
    <form action={action}>
      <input type="hidden" name="project_id" value={projectId} />
      <input type="hidden" name="invitation_id" value={invitationId} />
      <button
        className="danger"
        type="submit"
        disabled={pending}
        onClick={(event) => {
          if (!window.confirm("确认撤销这条客户邀请？原 token 将立即失效。")) event.preventDefault();
        }}
      >
        {pending ? "撤销中..." : "撤销"}
      </button>
      <InvitationFeedback state={state} />
    </form>
  );
}

function InvitationFeedback({ state }: { state: InvitationActionState }) {
  if (state.kind === "idle") return null;
  return (
    <div className={state.kind === "error" ? styles.error : styles.success} role={state.kind === "error" ? "alert" : "status"}>
      <strong>{state.kind === "error" ? errorTitle(state.status) : "邀请操作完成"}</strong>
      <span>{state.message}</span>
      {state.rawInviteToken ? <span>一次性邀请 token：<code>{state.rawInviteToken}</code></span> : null}
      {state.invitationId ? <small>邀请 ID：{state.invitationId}</small> : null}
      {state.correlationId ? <small>关联 ID：{state.correlationId}</small> : null}
    </div>
  );
}

function errorTitle(status: number | undefined): string {
  if (status === 403) return "无权管理客户邀请";
  if (status === 409) return "邀请状态冲突";
  if (status === 422) return "邀请输入无效";
  return "邀请操作失败";
}
