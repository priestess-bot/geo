import { randomUUID } from "node:crypto";

import { isAuthIdentity, type AuthIdentity } from "@geo/types/auth";

import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  isProjectMemberListResponse,
  type ProjectMemberListResponse
} from "../../memberTypes";
import { SECRET_MAX_BYTES, type SecretActionState } from "./secretStoreTypes";

export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PURPOSE_PATTERN = /^[a-z][a-z0-9_.-]{0,127}$/;

export async function verifySecretActor(
  projectId: string
): Promise<{ ok: true } | { ok: false; state: SecretActionState }> {
  if (!UUID_PATTERN.test(projectId)) {
    return { ok: false, state: invalid("项目 ID 无效。") };
  }
  const [identity, members] = await Promise.all([
    runtimeRequest<AuthIdentity>("/v1/auth/me"),
    runtimeRequest<ProjectMemberListResponse>(
      `/v1/projects/${encodeURIComponent(projectId)}/members`,
      { query: { limit: 100, offset: 0 } }
    )
  ]);
  if (!identity.ok) return { ok: false, state: accessFailure(identity, "身份验证失败。") };
  if (!members.ok) return { ok: false, state: accessFailure(members, "项目成员验证失败。") };
  if (!isAuthIdentity(identity.data) || !isProjectMemberListResponse(members.data)) {
    return { ok: false, state: invalidUpstream("身份或项目成员元数据无效。") };
  }
  if (!identity.data.project_ids.includes(projectId)) {
    return { ok: false, state: forbidden() };
  }
  let membership = members.data.items.find(
    (item) => item.status === "active" && item.subject === identity.data.actor_id
  );
  for (
    let offset = members.data.offset + members.data.limit;
    !membership && offset < members.data.total;
    offset += members.data.limit
  ) {
    const nextPage = await runtimeRequest<ProjectMemberListResponse>(
      `/v1/projects/${encodeURIComponent(projectId)}/members`,
      { query: { limit: members.data.limit, offset } }
    );
    if (!nextPage.ok) {
      return { ok: false, state: accessFailure(nextPage, "项目成员验证失败。") };
    }
    if (!isProjectMemberListResponse(nextPage.data)) {
      return { ok: false, state: invalidUpstream("项目成员元数据无效。") };
    }
    membership = nextPage.data.items.find(
      (item) => item.status === "active" && item.subject === identity.data.actor_id
    );
  }
  if (!membership || (membership.role !== "owner" && membership.role !== "admin")) {
    return { ok: false, state: forbidden() };
  }
  return { ok: true };
}

export function secretInput(
  formData: FormData
): { ok: true; value: string } | { ok: false; state: SecretActionState } {
  const entry = formData.get("secret_value");
  const value = typeof entry === "string" ? entry : "";
  const bytes = Buffer.byteLength(value, "utf8");
  if (bytes < 1) return { ok: false, state: invalid("SecretValue 不能为空。") };
  if (bytes > SECRET_MAX_BYTES) {
    return { ok: false, state: invalid("SecretValue 超过 64 KiB 限制。") };
  }
  return { ok: true, value };
}

export function field(formData: FormData, name: string): string {
  return String(formData.get(name) || "").trim();
}

export function nonNegativeIntegerField(formData: FormData, name: string): number | null {
  const value = Number(field(formData, name));
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

export function positiveIntegerField(formData: FormData, name: string): number | null {
  const value = nonNegativeIntegerField(formData, name);
  return value !== null && value > 0 ? value : null;
}

export function validPurpose(value: string): boolean {
  return PURPOSE_PATTERN.test(value);
}

export function idempotencyKey(formData: FormData): string | null {
  const value = field(formData, "idempotency_key");
  return value.length >= 8
    && value.length <= 256
    && !Array.from(value).some((character) => /\s/.test(character) || character.charCodeAt(0) < 32)
    ? value
    : null;
}

export function invalid(message: string): SecretActionState {
  return safeState({ kind: "error", status: 422, message: `输入无效：${message}` });
}

export function invalidUpstream(message: string): SecretActionState {
  return safeState({ kind: "error", status: 502, message });
}

export function secretCommandFailure(
  response: Extract<RuntimeResult<unknown>, { ok: false }>
): SecretActionState {
  return safeState({
    kind: "error",
    ...(response.status === undefined ? {} : { status: response.status }),
    message: failureMessage(response.status),
    ...(response.problem.correlation_id
      ? { correlationId: response.problem.correlation_id }
      : {})
  });
}

export function safeState(
  state: Omit<SecretActionState, "responseToken">
): SecretActionState {
  return { ...state, responseToken: randomUUID() };
}

export function secretBase(projectId: string): string {
  return `/v1/projects/${encodeURIComponent(projectId)}/secrets`;
}

export function secretHref(projectId: string, referenceId: string): string {
  const query = new URLSearchParams({
    tab: "secrets",
    secret_reference_id: referenceId
  });
  return `/projects/${encodeURIComponent(projectId)}?${query.toString()}`;
}

function accessFailure(
  response: Extract<RuntimeResult<unknown>, { ok: false }>,
  fallback: string
): SecretActionState {
  return safeState({
    kind: "error",
    ...(response.status === undefined ? {} : { status: response.status }),
    message: response.status === 503 ? "Secret Store unavailable：身份或成员服务不可用。" : fallback,
    ...(response.problem.correlation_id
      ? { correlationId: response.problem.correlation_id }
      : {})
  });
}

function forbidden(): SecretActionState {
  return safeState({
    kind: "error",
    status: 403,
    message: "权限不足：Secret Store 仅允许项目负责人或管理员操作。"
  });
}

function failureMessage(status: number | undefined): string {
  if (status === 401) return "登录已失效，请重新登录。";
  if (status === 403) return "权限不足或双人激活条件未满足。";
  if (status === 404) return "Secret Reference 或版本不存在。";
  if (status === 409) return "状态冲突：Secret 生命周期已变化，请刷新后重试。";
  if (status === 422) return "输入或 Secret 生命周期请求无效。";
  if (status === 503) return "Secret Store unavailable：持久化或密钥服务不可用。";
  return "Secret Store 命令失败。";
}
