"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest, type RuntimeResult } from "../../runtime";
import {
  isManagedMemberRole,
  isProjectMemberMutationResponse,
  type AddProjectMemberRequest,
  type ChangeProjectMemberRoleRequest,
  type MemberActionState,
  type ProjectMemberMutationResponse
} from "./memberTypes";

export async function addProjectMemberAction(
  _previous: MemberActionState,
  formData: FormData
): Promise<MemberActionState> {
  const projectId = field(formData, "project_id");
  const role = field(formData, "role");
  if (!projectId || !isManagedMemberRole(role)) {
    return invalid("项目和成员角色不能为空。");
  }
  const payload: AddProjectMemberRequest = {
    issuer: field(formData, "issuer"),
    subject: field(formData, "subject"),
    email: field(formData, "email").toLowerCase(),
    display_name: field(formData, "display_name"),
    role
  };
  if (!payload.issuer || !payload.subject || !payload.email || !payload.display_name) {
    return invalid("OIDC issuer、subject、邮箱和显示名称均为必填项。");
  }
  const key = idempotencyKey(formData);
  if (!key) return invalid("Idempotency-Key 无效，请刷新页面后重试。");
  const response = await runtimeRequest<ProjectMemberMutationResponse>(
    `/v1/projects/${encodeURIComponent(projectId)}/members`,
    commandOptions(key, payload)
  );
  if (response.ok && !isProjectMemberMutationResponse(response.data)) return invalidUpstream();
  return finish(response, projectId, response.ok
    ? response.data.replayed ? "成员已存在，已恢复原请求结果。" : "OIDC 成员已添加。"
    : "成员添加失败。");
}

export async function changeProjectMemberRoleAction(
  _previous: MemberActionState,
  formData: FormData
): Promise<MemberActionState> {
  const projectId = field(formData, "project_id");
  const membershipId = field(formData, "membership_id");
  const role = field(formData, "role");
  if (!projectId || !membershipId || !isManagedMemberRole(role)) {
    return invalid("项目、成员和目标角色不能为空。");
  }
  const key = idempotencyKey(formData);
  if (!key) return invalid("Idempotency-Key 无效，请刷新页面后重试。");
  const payload: ChangeProjectMemberRoleRequest = { role };
  const response = await runtimeRequest<ProjectMemberMutationResponse>(
    memberCommandPath(projectId, membershipId, "role"),
    commandOptions(key, payload)
  );
  if (response.ok && !isProjectMemberMutationResponse(response.data)) return invalidUpstream();
  return finish(response, projectId, response.ok
    ? response.data.replayed ? "角色未变化，已恢复原请求结果。" : "成员角色已更新。"
    : "角色更新失败。");
}

export async function revokeProjectMemberAction(
  _previous: MemberActionState,
  formData: FormData
): Promise<MemberActionState> {
  return memberStatusAction(formData, "revoke", "成员访问已撤销。", "成员撤销失败。");
}

export async function reactivateProjectMemberAction(
  _previous: MemberActionState,
  formData: FormData
): Promise<MemberActionState> {
  return memberStatusAction(formData, "reactivate", "成员访问已恢复。", "成员恢复失败。");
}

async function memberStatusAction(
  formData: FormData,
  command: "revoke" | "reactivate",
  successMessage: string,
  failureMessage: string
): Promise<MemberActionState> {
  const projectId = field(formData, "project_id");
  const membershipId = field(formData, "membership_id");
  if (!projectId || !membershipId) {
    return invalid("项目和成员不能为空。");
  }
  const key = idempotencyKey(formData);
  if (!key) return invalid("Idempotency-Key 无效，请刷新页面后重试。");
  const response = await runtimeRequest<ProjectMemberMutationResponse>(
    memberCommandPath(projectId, membershipId, command),
    commandOptions(key)
  );
  if (response.ok && !isProjectMemberMutationResponse(response.data)) return invalidUpstream();
  return finish(response, projectId, response.ok && response.data.replayed
    ? "已恢复原请求结果。"
    : response.ok ? successMessage : failureMessage);
}

function commandOptions(idempotencyKey: string, body?: unknown) {
  return {
    method: "POST",
    ...(body === undefined ? {} : { body }),
    idempotencyKey
  };
}

function memberCommandPath(
  projectId: string,
  membershipId: string,
  command: "role" | "revoke" | "reactivate"
): string {
  return `/v1/projects/${encodeURIComponent(projectId)}/members/`
    + `${encodeURIComponent(membershipId)}/${command}`;
}

function finish(
  response: RuntimeResult<ProjectMemberMutationResponse>,
  projectId: string,
  message: string
): MemberActionState {
  if (!response.ok) {
    return {
      kind: "error",
      message: `${failureLabel(response.status)}${response.error || message}`,
      ...(response.status === undefined ? {} : { status: response.status }),
      ...(response.problem.correlation_id
        ? { correlationId: response.problem.correlation_id }
        : {})
    };
  }
  revalidatePath(`/projects/${projectId}`);
  return { kind: "success", message };
}

function failureLabel(status: number | undefined): string {
  if (status === 403) return "权限不足：";
  if (status === 409) return "状态冲突：";
  if (status === 422) return "输入无效：";
  return "";
}

function invalid(message: string): MemberActionState {
  return { kind: "error", status: 422, message };
}

function invalidUpstream(): MemberActionState {
  return { kind: "error", status: 502, message: "成员接口返回了无法识别的响应。" };
}

function field(formData: FormData, name: string): string {
  return String(formData.get(name) || "").trim();
}

function idempotencyKey(formData: FormData): string | null {
  const key = field(formData, "idempotency_key");
  return key.length >= 16 && key.length <= 512 && !/[\r\n]/.test(key) ? key : null;
}
