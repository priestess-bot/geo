"use client";

import { useActionState } from "react";

import {
  createInvitationAction,
  createPortalTokenAction,
  revokePortalTokenAction,
  type ProjectActionState
} from "./actions";

const initialState: ProjectActionState = { ok: false };

export function InvitationForm({ projectId, defaultEmail }: { projectId: string; defaultEmail?: string }) {
  const [state, formAction, pending] = useActionState(createInvitationAction, initialState);
  return (
    <form className="inlineForm" action={formAction}>
      <input type="hidden" name="project_id" value={projectId} />
      <label><span>客户邮箱</span><input name="email" type="email" defaultValue={defaultEmail || ""} placeholder="customer@example.com" required /></label>
      <button type="submit" disabled={pending}>{pending ? "创建中..." : "创建邀请"}</button>
      <ActionState state={state} />
    </form>
  );
}

export function TokenCreateForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(createPortalTokenAction, initialState);
  return (
    <form className="inlineForm" action={formAction}>
      <input type="hidden" name="project_id" value={projectId} />
      <label><span>viewer user id</span><input name="member_user_id" placeholder="customer@example.com" required /></label>
      <label><span>invitation id</span><input name="invitation_id" placeholder="可选" /></label>
      <button type="submit" disabled={pending}>{pending ? "生成中..." : "生成 token"}</button>
      <ActionState state={state} />
    </form>
  );
}

export function TokenRevokeForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(revokePortalTokenAction, initialState);
  return (
    <form className="inlineForm" action={formAction}>
      <input type="hidden" name="project_id" value={projectId} />
      <label><span>token id</span><input name="token_id" placeholder="customer_portal_token id" required /></label>
      <button type="submit" disabled={pending}>{pending ? "撤销中..." : "撤销 token"}</button>
      <ActionState state={state} />
    </form>
  );
}

function ActionState({ state }: { state: ProjectActionState }) {
  if (state.error) {
    return <p className="muted errorText">{state.error}</p>;
  }
  if (!state.ok) {
    return null;
  }
  return (
    <div className="actionResult">
      {state.message ? <p>{state.message}</p> : null}
      {state.rawToken ? <p>raw portal token：<code>{state.rawToken}</code></p> : null}
      {state.rawInviteToken ? <p>raw invite token：<code>{state.rawInviteToken}</code></p> : null}
      {state.inviteUrl ? <a className="button secondary" href={state.inviteUrl}>打开客户邀请入口</a> : null}
    </div>
  );
}
