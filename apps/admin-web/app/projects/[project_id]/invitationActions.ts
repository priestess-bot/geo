"use server";

import type { CreatedProjectInvitationResponse } from "@geo/types/auth";
import { revalidatePath } from "next/cache";

import { runtimeRequest } from "../../runtime";
import {
  isCreatedInvitationResponse,
  type InvitationActionState
} from "./invitationTypes";

export async function createInvitationAction(
  _previous: InvitationActionState,
  formData: FormData
): Promise<InvitationActionState> {
  const projectId = field(formData, "project_id");
  const email = field(formData, "email").toLowerCase();
  const idempotencyKey = key(formData);
  if (!projectId || !email || !email.includes("@")) return invalid("项目和有效客户邮箱不能为空。");
  if (!idempotencyKey) return invalid("Idempotency-Key 无效，请刷新页面后重试。");
  const response = await runtimeRequest<CreatedProjectInvitationResponse>(
    invitationPath(projectId),
    {
      method: "POST",
      body: {
        email,
        role: "viewer",
        target_surface: "customer",
        expires_in_hours: 72
      },
      idempotencyKey
    }
  );
  if (!response.ok) return failure(response.status, response.error, response.problem.correlation_id);
  if (!isCreatedInvitationResponse(response.data)) {
    return {
      kind: "error",
      status: 502,
      message: "客户邀请接口返回了无法识别的响应。",
      ...(response.response.correlationId
        ? { correlationId: response.response.correlationId }
        : {})
    };
  }
  revalidatePath(`/projects/${projectId}`);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复相同创建请求的结果。" : "客户邀请已创建。",
    rawInviteToken: response.data.invite_token,
    invitationId: response.data.invitation.id
  };
}

export async function revokeInvitationAction(
  _previous: InvitationActionState,
  formData: FormData
): Promise<InvitationActionState> {
  const projectId = field(formData, "project_id");
  const invitationId = field(formData, "invitation_id");
  if (!projectId || !invitationId) return invalid("项目和邀请不能为空。");
  const response = await runtimeRequest<{ status: "revoked" }>(
    `${invitationPath(projectId)}/${encodeURIComponent(invitationId)}/revoke`,
    { method: "POST" }
  );
  if (!response.ok) return failure(response.status, response.error, response.problem.correlation_id);
  if (response.data.status !== "revoked") {
    return { kind: "error", status: 502, message: "客户邀请接口返回了无法识别的响应。" };
  }
  revalidatePath(`/projects/${projectId}`);
  return { kind: "success", message: "客户邀请已撤销。" };
}

function invitationPath(projectId: string): string {
  return `/v1/projects/${encodeURIComponent(projectId)}/invitations`;
}

function field(formData: FormData, name: string): string {
  return String(formData.get(name) || "").trim();
}

function key(formData: FormData): string | null {
  const value = field(formData, "idempotency_key");
  return value.length >= 16 && value.length <= 512 && !/[\r\n]/.test(value) ? value : null;
}

function invalid(message: string): InvitationActionState {
  return { kind: "error", status: 422, message };
}

function failure(
  status: number | undefined,
  detail: string,
  correlationId: string | undefined
): InvitationActionState {
  return {
    kind: "error",
    ...(status === undefined ? {} : { status }),
    message: `${failureLabel(status)}${detail || "邀请操作失败。"}`,
    ...(correlationId ? { correlationId } : {})
  };
}

function failureLabel(status: number | undefined): string {
  if (status === 401) return "登录已失效：";
  if (status === 403) return "权限不足：";
  if (status === 409) return "状态冲突：";
  if (status === 422) return "输入无效：";
  return "";
}
