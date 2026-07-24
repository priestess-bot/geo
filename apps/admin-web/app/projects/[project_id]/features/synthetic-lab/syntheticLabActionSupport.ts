import { randomUUID } from "node:crypto";

import { isAuthIdentity, type AuthIdentity } from "@geo/types/auth";

import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  isProjectMemberListResponse,
  type ManagedMemberRole,
  type ProjectMemberListResponse
} from "../../memberTypes";
import type { SyntheticActionState, SyntheticChannel } from "./syntheticLabTypes";
import { syntheticChannels } from "./syntheticLabTypes";

export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const HASH_PATTERN = /^[0-9a-f]{64}$/;
const COMMAND_PATTERN = /^[\x21-\x7e]{16,200}$/;

export async function verifySyntheticActor(
  projectId: string,
  allowedRoles: readonly ManagedMemberRole[]
): Promise<{ ok: true; actorId: string; role: ManagedMemberRole } | {
  ok: false;
  state: SyntheticActionState;
}> {
  if (!UUID_PATTERN.test(projectId)) return { ok: false, state: invalid("项目 ID 无效。") };
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
    return { ok: false, state: upstreamInvalid("身份或项目成员接口返回无效数据。") };
  }
  if (!identity.data.project_ids.includes(projectId)) return { ok: false, state: forbidden() };
  let membership = members.data.items.find(
    (item) => item.status === "active" && item.subject === identity.data.actor_id
  );
  for (
    let offset = members.data.offset + members.data.limit;
    !membership && offset < members.data.total;
    offset += members.data.limit
  ) {
    const page = await runtimeRequest<ProjectMemberListResponse>(
      `/v1/projects/${encodeURIComponent(projectId)}/members`,
      { query: { limit: members.data.limit, offset } }
    );
    if (!page.ok) return { ok: false, state: accessFailure(page, "项目成员验证失败。") };
    if (!isProjectMemberListResponse(page.data)) {
      return { ok: false, state: upstreamInvalid("项目成员接口返回无效数据。") };
    }
    membership = page.data.items.find(
      (item) => item.status === "active" && item.subject === identity.data.actor_id
    );
  }
  if (!membership || !allowedRoles.includes(membership.role)) {
    return { ok: false, state: forbidden() };
  }
  return { ok: true, actorId: identity.data.actor_id, role: membership.role };
}

export function field(formData: FormData, name: string): string {
  return String(formData.get(name) || "").trim();
}

export function requiredField(
  formData: FormData,
  name: string,
  maximum: number
): string | null {
  const value = field(formData, name);
  return value.length > 0 && value.length <= maximum ? value : null;
}

export function optionalField(formData: FormData, name: string, maximum: number): string | null {
  const value = field(formData, name);
  return value.length <= maximum ? value || null : null;
}

export function integerField(formData: FormData, name: string, minimum = 0): number | null {
  const value = Number(field(formData, name));
  return Number.isSafeInteger(value) && value >= minimum ? value : null;
}

export function optionalPositiveInteger(formData: FormData, name: string): number | null | undefined {
  const raw = field(formData, name);
  if (!raw) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value > 0 ? value : undefined;
}

export function decimalField(formData: FormData, name: string, minimum: number, maximum: number): number | null {
  const value = Number(field(formData, name));
  return Number.isFinite(value) && value >= minimum && value <= maximum ? value : null;
}

export function booleanField(formData: FormData, name: string): boolean {
  return field(formData, name) === "true";
}

export function uuidField(formData: FormData, name: string): string | null {
  const value = field(formData, name);
  return UUID_PATTERN.test(value) ? value : null;
}

export function hashField(formData: FormData, name: string, optional = false): string | null {
  const value = field(formData, name);
  if (optional && !value) return "";
  return HASH_PATTERN.test(value) ? value : null;
}

export function channelField(formData: FormData): SyntheticChannel | null {
  const value = field(formData, "channel");
  return syntheticChannels.some((channel) => channel === value)
    ? value as SyntheticChannel
    : null;
}

export function lines(formData: FormData, name: string): string[] {
  return field(formData, name).split(/[\r\n,]+/).map((item) => item.trim()).filter(Boolean);
}

export function uuidLines(formData: FormData, name: string): string[] | null {
  const values = lines(formData, name);
  return values.length > 0 && values.every((value) => UUID_PATTERN.test(value)) ? values : null;
}

export function commandKey(formData: FormData): string | null {
  const value = field(formData, "idempotency_key");
  return COMMAND_PATTERN.test(value) ? value : null;
}

export function syntheticBase(projectId: string): string {
  return `/v1/projects/${encodeURIComponent(projectId)}/synthetic-lab`;
}

export function syntheticHref(projectId: string, values: Record<string, string>): string {
  const query = new URLSearchParams({ tab: "synthetic-lab", ...values });
  return `/projects/${encodeURIComponent(projectId)}?${query.toString()}`;
}

export function invalid(message: string): SyntheticActionState {
  return safeState({ kind: "error", status: 422, message: `输入无效：${message}` });
}

export function upstreamInvalid(message: string): SyntheticActionState {
  return safeState({ kind: "error", status: 502, message });
}

export function commandFailure(
  response: Extract<RuntimeResult<unknown>, { ok: false }>
): SyntheticActionState {
  return safeState({
    kind: "error",
    ...(response.status === undefined ? {} : { status: response.status }),
    message: failureMessage(response.status),
    ...(response.problem.correlation_id ? { correlationId: response.problem.correlation_id } : {})
  });
}

export function safeState(
  state: Omit<SyntheticActionState, "responseToken">
): SyntheticActionState {
  return { ...state, responseToken: randomUUID() };
}

function accessFailure(
  response: Extract<RuntimeResult<unknown>, { ok: false }>,
  fallback: string
): SyntheticActionState {
  return safeState({
    kind: "error",
    ...(response.status === undefined ? {} : { status: response.status }),
    message: response.status === 503 ? "Synthetic Lab unavailable：身份或成员服务不可用。" : fallback,
    ...(response.problem.correlation_id ? { correlationId: response.problem.correlation_id } : {})
  });
}

function forbidden(): SyntheticActionState {
  return safeState({
    kind: "error",
    status: 403,
    message: "权限不足：当前项目角色不能执行此 Synthetic Lab 操作。"
  });
}

function failureMessage(status: number | undefined): string {
  if (status === 401) return "登录已失效，请重新登录。";
  if (status === 403) return "权限不足，或授权/双人批准条件未满足。";
  if (status === 404) return "Synthetic Lab 资源不存在。";
  if (status === 409) return "状态冲突：版本、冻结输入或任务租约已变化，请刷新后重试。";
  if (status === 422) return "输入不符合 Synthetic Lab 契约。";
  if (status === 503) return "Synthetic Lab unavailable：持久化运行时未连接。";
  return "Synthetic Lab 命令失败。";
}
