import { isAuthIdentity, type AuthIdentity } from "@geo/types/auth";

import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  isProjectMemberListResponse,
  type ManagedMemberRole,
  type ProjectMemberListResponse
} from "../../memberTypes";
import type {
  LinkedDraft,
  RecommendationActionState,
  RecommendationWorkflow
} from "./recommendationTypes";

export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export type RecommendationCommandFields = Readonly<{
  projectId: string;
  recommendationId: string;
  expectedVersion: number;
  idempotencyKey: string;
}>;

export async function verifyRecommendationActor(
  projectId: string,
  allowedRoles: readonly ManagedMemberRole[]
): Promise<{ ok: true; actorId: string; role: ManagedMemberRole } | {
  ok: false;
  state: RecommendationActionState;
}> {
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
  if (!identity.ok) return { ok: false, state: commandFailure(identity, "身份验证失败。") };
  if (!members.ok) return { ok: false, state: commandFailure(members, "项目成员验证失败。") };
  if (!isAuthIdentity(identity.data) || !isProjectMemberListResponse(members.data)) {
    return { ok: false, state: upstreamInvalid("身份或成员接口返回无效数据。") };
  }
  if (!identity.data.project_ids.includes(projectId)) {
    return { ok: false, state: forbidden("当前身份未获授权访问此项目。") };
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
      return { ok: false, state: commandFailure(nextPage, "项目成员验证失败。") };
    }
    if (!isProjectMemberListResponse(nextPage.data)) {
      return { ok: false, state: upstreamInvalid("项目成员接口返回无效数据。") };
    }
    membership = nextPage.data.items.find(
      (item) => item.status === "active" && item.subject === identity.data.actor_id
    );
  }
  if (!membership || !allowedRoles.includes(membership.role)) {
    return { ok: false, state: forbidden("当前项目角色不能执行此 Recommendation 操作。") };
  }
  return { ok: true, actorId: identity.data.actor_id, role: membership.role };
}

export function parseCommandFields(
  formData: FormData
): { ok: true; value: RecommendationCommandFields } | {
  ok: false;
  state: RecommendationActionState;
} {
  const projectId = field(formData, "project_id");
  const recommendationId = field(formData, "recommendation_id");
  const expectedVersion = integerField(formData, "expected_version");
  const idempotencyKey = commandKey(formData);
  if (!UUID_PATTERN.test(projectId) || !UUID_PATTERN.test(recommendationId)) {
    return { ok: false, state: invalid("项目或 Recommendation ID 无效。") };
  }
  if (expectedVersion === null || expectedVersion < 1) {
    return { ok: false, state: invalid("期望版本无效，请刷新页面后重试。") };
  }
  if (!idempotencyKey) {
    return { ok: false, state: invalid("Idempotency-Key 无效，请刷新页面后重试。") };
  }
  return {
    ok: true,
    value: { projectId, recommendationId, expectedVersion, idempotencyKey }
  };
}

export function field(formData: FormData, name: string): string {
  return String(formData.get(name) || "").trim();
}

export function boundedReason(formData: FormData): string | null {
  const reason = field(formData, "reason");
  return reason.length >= 1 && reason.length <= 5000 ? reason : null;
}

export function commandPath(fields: RecommendationCommandFields, command: string): string {
  return `${recommendationPath(fields)}/${command}`;
}

export function recommendationPath(fields: RecommendationCommandFields): string {
  return `/v1/projects/${encodeURIComponent(fields.projectId)}/recommendations/`
    + encodeURIComponent(fields.recommendationId);
}

export function recommendationResult(workflow: RecommendationWorkflow) {
  const recommendation = workflow.recommendation;
  return {
    id: recommendation.id,
    status: recommendation.status,
    version: recommendation.version,
    evidenceGraphHash: recommendation.evidence_graph_hash
  } as const;
}

export function draftResult(draft: LinkedDraft, authorized?: boolean) {
  return {
    id: draft.id,
    kind: draft.kind,
    status: draft.status,
    ...(authorized === undefined ? {} : { authorized })
  } as const;
}

export function commandFailure(
  response: Extract<RuntimeResult<unknown>, { ok: false }>,
  fallback: string
): RecommendationActionState {
  return {
    kind: "error",
    ...(response.status === undefined ? {} : { status: response.status }),
    message: `${failureLabel(response.status)}${response.error || fallback}`,
    ...(response.problem.correlation_id
      ? { correlationId: response.problem.correlation_id }
      : {})
  };
}

export function invalid(message: string): RecommendationActionState {
  return { kind: "error", status: 422, message: `输入无效：${message}` };
}

export function upstreamInvalid(message: string): RecommendationActionState {
  return { kind: "error", status: 502, message };
}

function commandKey(formData: FormData): string | null {
  const value = field(formData, "idempotency_key");
  return value.length >= 16 && value.length <= 200 && !/[\r\n]/.test(value)
    ? value
    : null;
}

function integerField(formData: FormData, name: string): number | null {
  const value = Number(field(formData, name));
  return Number.isSafeInteger(value) ? value : null;
}

function forbidden(message: string): RecommendationActionState {
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
