import { isAuthIdentity, type AuthIdentity } from "@geo/types/auth";

import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  isProjectMemberListResponse,
  type ManagedMemberRole,
  type ProjectMemberListResponse
} from "../../memberTypes";
import { isAlertRecord } from "./workflowCTypeGuards";
import type {
  AlertRecord,
  NotificationProjection,
  WorkflowCActionState
} from "./workflowCTypes";

export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export type AlertCommandFields = Readonly<{
  projectId: string;
  alertId: string;
  expectedVersion: number;
  idempotencyKey: string;
  reason: string;
}>;

export type AlertCommandResponse = Readonly<{
  alert: AlertRecord;
  notifications: NotificationProjection[];
  replayed: boolean;
}>;

export async function verifyWorkflowCActor(
  projectId: string,
  allowedRoles: readonly ManagedMemberRole[]
): Promise<{ ok: true; actorId: string; role: ManagedMemberRole } | {
  ok: false;
  state: WorkflowCActionState;
}> {
  if (!UUID_PATTERN.test(projectId)) return { ok: false, state: invalid("项目 ID 无效。") };
  const [identity, firstMembers] = await Promise.all([
    runtimeRequest<AuthIdentity>("/v1/auth/me"),
    runtimeRequest<ProjectMemberListResponse>(
      `/v1/projects/${encodeURIComponent(projectId)}/members`,
      { query: { limit: 100, offset: 0 } }
    )
  ]);
  if (!identity.ok) return { ok: false, state: commandFailure(identity, "身份验证失败。") };
  if (!firstMembers.ok) return { ok: false, state: commandFailure(firstMembers, "项目成员验证失败。") };
  if (!isAuthIdentity(identity.data) || !isProjectMemberListResponse(firstMembers.data)) {
    return { ok: false, state: invalidUpstream("身份或成员接口返回无效数据。") };
  }
  if (!identity.data.project_ids.includes(projectId)) {
    return { ok: false, state: forbidden("当前身份未获授权访问此项目。") };
  }
  let membership = activeMembership(firstMembers.data, identity.data.actor_id);
  for (
    let offset = firstMembers.data.offset + firstMembers.data.limit;
    !membership && offset < firstMembers.data.total;
    offset += firstMembers.data.limit
  ) {
    const page = await runtimeRequest<ProjectMemberListResponse>(
      `/v1/projects/${encodeURIComponent(projectId)}/members`,
      { query: { limit: firstMembers.data.limit, offset } }
    );
    if (!page.ok) return { ok: false, state: commandFailure(page, "项目成员验证失败。") };
    if (!isProjectMemberListResponse(page.data)) {
      return { ok: false, state: invalidUpstream("项目成员接口返回无效数据。") };
    }
    membership = activeMembership(page.data, identity.data.actor_id);
  }
  if (!membership || !allowedRoles.includes(membership.role)) {
    return { ok: false, state: forbidden("当前项目角色不能执行此操作。") };
  }
  return { ok: true, actorId: identity.data.actor_id, role: membership.role };
}

export function parseAlertCommand(
  formData: FormData
): { ok: true; value: AlertCommandFields } | {
  ok: false;
  state: WorkflowCActionState;
} {
  const projectId = field(formData, "project_id");
  const alertId = field(formData, "alert_id");
  const expectedVersion = integerField(formData, "expected_version");
  const idempotencyKey = field(formData, "idempotency_key");
  const reason = field(formData, "reason");
  if (!UUID_PATTERN.test(projectId) || !UUID_PATTERN.test(alertId)) {
    return { ok: false, state: invalid("项目或 Alert ID 无效。") };
  }
  if (expectedVersion === null || expectedVersion < 1) {
    return { ok: false, state: invalid("期望版本无效，请刷新页面后重试。") };
  }
  if (idempotencyKey.length < 16 || idempotencyKey.length > 200 || /[\r\n]/.test(idempotencyKey)) {
    return { ok: false, state: invalid("Idempotency-Key 无效，请刷新页面后重试。") };
  }
  if (!reason || reason.length > 1000) {
    return { ok: false, state: invalid("处置原因不能为空且不能超过 1000 字符。") };
  }
  return {
    ok: true,
    value: { projectId, alertId, expectedVersion, idempotencyKey, reason }
  };
}

export function isAlertCommandResponse(value: unknown): value is AlertCommandResponse {
  if (!record(value) || !isAlertRecord(value.alert) || typeof value.replayed !== "boolean") {
    return false;
  }
  return Array.isArray(value.notifications) && value.notifications.every((item) => {
    return record(item)
      && UUID_PATTERN.test(String(item.id))
      && UUID_PATTERN.test(String(item.alert_id))
      && typeof item.payload_hash === "string";
  });
}

export function alertResult(value: AlertCommandResponse) {
  return {
    id: value.alert.id,
    status: value.alert.status,
    version: value.alert.version
  } as const;
}

export function commandFailure(
  response: Extract<RuntimeResult<unknown>, { ok: false }>,
  fallback: string
): WorkflowCActionState {
  return {
    kind: "error",
    ...(response.status === undefined ? {} : { status: response.status }),
    message: `${failureLabel(response.status)}${response.error || fallback}`,
    ...(response.problem.correlation_id
      ? { correlationId: response.problem.correlation_id }
      : {})
  };
}

export function invalid(message: string): WorkflowCActionState {
  return { kind: "error", status: 422, message: `输入无效：${message}` };
}

export function invalidUpstream(message: string): WorkflowCActionState {
  return { kind: "error", status: 502, message };
}

export function field(formData: FormData, name: string): string {
  return String(formData.get(name) || "").trim();
}

export function normalizedDate(value: string): string | null {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? null : date.toISOString();
}

function activeMembership(page: ProjectMemberListResponse, actorId: string) {
  return page.items.find((item) => item.status === "active" && item.subject === actorId);
}

function integerField(formData: FormData, name: string): number | null {
  const value = Number(field(formData, name));
  return Number.isSafeInteger(value) ? value : null;
}

function forbidden(message: string): WorkflowCActionState {
  return { kind: "error", status: 403, message: `权限不足：${message}` };
}

function failureLabel(status: number | undefined): string {
  if (status === 401) return "登录已失效：";
  if (status === 403) return "权限不足：";
  if (status === 409) return "状态冲突：";
  if (status === 422) return "输入无效：";
  if (status === 503) return "服务不可用：";
  return "";
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
