"use server";

import { adminActorId, customerInvitationUrl, runtimeRequest } from "../../runtime";

export type ProjectActionState = {
  ok: boolean;
  message?: string;
  error?: string;
  rawToken?: string;
  inviteUrl?: string;
  rawInviteToken?: string;
};

type TokenResponse = {
  raw_token?: string;
  portal_token?: { id?: string };
};

type InvitationResponse = {
  invitation?: { id?: string; invite_token?: string; email?: string };
};

function projectId(formData: FormData): string {
  return String(formData.get("project_id") || "").trim();
}

export async function createPortalTokenAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const payload = {
    project_id: projectId(formData),
    member_user_id: String(formData.get("member_user_id") || "").trim(),
    invitation_id: String(formData.get("invitation_id") || "").trim() || null,
    issued_by: adminActorId(),
    metadata: { created_from: "admin_web" },
    reason: "admin_web_customer_portal_token_create"
  };
  const response = await runtimeRequest<TokenResponse>("/v1/customer-portal/tokens/runtime", {
    method: "POST",
    body: payload
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "门户 token 创建失败。" };
  }
  return {
    ok: true,
    message: `token 已创建：${response.data?.portal_token?.id || "created"}`,
    rawToken: response.data?.raw_token
  };
}

export async function revokePortalTokenAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const payload = {
    project_id: projectId(formData),
    token_id: String(formData.get("token_id") || "").trim(),
    revoked_by: adminActorId(),
    reason: "admin_web_customer_portal_token_revoke"
  };
  const response = await runtimeRequest<TokenResponse>("/v1/customer-portal/tokens/runtime/revoke", {
    method: "POST",
    body: payload
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "门户 token 撤销失败。" };
  }
  return { ok: true, message: `token 已撤销：${response.data?.portal_token?.id || payload.token_id}` };
}

export async function createInvitationAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const payload = {
    project_id: projectId(formData),
    email: String(formData.get("email") || "").trim(),
    role: "viewer",
    invited_by: adminActorId(),
    metadata: { created_from: "admin_web_project_detail" },
    reason: "admin_web_customer_invitation_create"
  };
  const response = await runtimeRequest<InvitationResponse>("/v1/project-member-invitations/runtime", {
    method: "POST",
    body: payload
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "客户邀请创建失败。" };
  }
  const invitation = response.data?.invitation;
  const inviteUrl =
    invitation?.id && invitation?.invite_token
      ? customerInvitationUrl(invitation.id, invitation.invite_token)
      : undefined;
  return {
    ok: true,
    message: `邀请已创建：${invitation?.email || payload.email}`,
    inviteUrl,
    rawInviteToken: invitation?.invite_token
  };
}
