import { isAuthIdentity, type AuthIdentity } from "@geo/types/auth";

import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  isProjectMemberListResponse,
  type ManagedMemberRole,
  type ProjectMemberListResponse
} from "../../memberTypes";
import type {
  PromptActionState,
  PromptProgramRelease
} from "./promptProgramTypes";

export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PURPOSE_PATTERN = /^[a-z][a-z0-9_.-]{2,127}$/;
const HASH_PATTERN = /^[0-9a-f]{64}$/;

export type PromptReleasePayload = Readonly<{
  system_template: string;
  user_template: string;
  schemas: Readonly<{
    variable_schema_version: string;
    variable_schema: Record<string, unknown>;
    input_schema_version: string;
    input_schema: Record<string, unknown>;
    output_schema_version: string;
    output_schema: Record<string, unknown>;
    application_output_schema_version: string;
    application_output_schema: Record<string, unknown>;
  }>;
  model_policy: Readonly<{
    version: string;
    policy: Record<string, unknown>;
  }>;
  test_set_id: string;
  test_set_version: number;
  test_set_hash: string;
  compiler_version: string;
  expected_version: number;
}>;

export type ParsedReleasePayload =
  | { ok: true; value: PromptReleasePayload }
  | { ok: false; state: PromptActionState };

export async function verifyPromptActor(
  projectId: string,
  allowedRoles: readonly ManagedMemberRole[]
): Promise<{ ok: true; actorId: string; role: ManagedMemberRole } | {
  ok: false;
  state: PromptActionState;
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
  if (!identity.ok) return { ok: false, state: accessFailure(identity, "身份验证失败。") };
  if (!members.ok) return { ok: false, state: accessFailure(members, "项目成员验证失败。") };
  if (!isAuthIdentity(identity.data) || !isProjectMemberListResponse(members.data)) {
    return { ok: false, state: upstreamInvalid("身份或项目成员接口返回无效数据。") };
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
      return { ok: false, state: accessFailure(nextPage, "项目成员验证失败。") };
    }
    if (!isProjectMemberListResponse(nextPage.data)) {
      return { ok: false, state: upstreamInvalid("项目成员接口返回无效数据。") };
    }
    membership = nextPage.data.items.find(
      (item) => item.status === "active" && item.subject === identity.data.actor_id
    );
  }
  if (!membership || !allowedRoles.includes(membership.role)) {
    return { ok: false, state: forbidden("当前项目角色不能执行此 Prompt 操作。") };
  }
  return { ok: true, actorId: identity.data.actor_id, role: membership.role };
}

export function parseReleasePayload(
  formData: FormData,
  minimumExpectedVersion: number
): ParsedReleasePayload {
  const systemTemplate = field(formData, "system_template");
  const userTemplate = field(formData, "user_template");
  const variableSchema = parseJsonObjectField(formData, "variable_schema", "变量 Schema");
  const inputSchema = parseJsonObjectField(formData, "input_schema", "输入 Schema");
  const outputSchema = parseJsonObjectField(formData, "output_schema", "输出 Schema");
  const applicationOutputSchema = parseJsonObjectField(
    formData,
    "application_output_schema",
    "应用输出 Schema"
  );
  const modelPolicy = parseJsonObjectField(formData, "model_policy", "模型策略");
  if (!systemTemplate || !userTemplate) {
    return { ok: false, state: invalid("系统与用户模板均为必填项。") };
  }
  if (systemTemplate.length > 100_000 || userTemplate.length > 100_000) {
    return { ok: false, state: invalid("单个 Template 不能超过 100000 个字符。") };
  }
  if (!variableSchema.ok) return { ok: false, state: invalid(variableSchema.error) };
  if (!inputSchema.ok) return { ok: false, state: invalid(inputSchema.error) };
  if (!outputSchema.ok) return { ok: false, state: invalid(outputSchema.error) };
  if (!applicationOutputSchema.ok) {
    return { ok: false, state: invalid(applicationOutputSchema.error) };
  }
  if (!modelPolicy.ok) return { ok: false, state: invalid(modelPolicy.error) };
  const variableSchemaVersion = field(formData, "variable_schema_version");
  const inputSchemaVersion = field(formData, "input_schema_version");
  const outputSchemaVersion = field(formData, "output_schema_version");
  const applicationOutputSchemaVersion = field(
    formData,
    "application_output_schema_version"
  );
  const modelPolicyVersion = field(formData, "model_policy_version");
  const compilerVersion = field(formData, "compiler_version");
  if ([variableSchemaVersion, inputSchemaVersion, outputSchemaVersion,
    applicationOutputSchemaVersion, modelPolicyVersion, compilerVersion]
    .some((value) => value.length === 0 || value.length > 100)) {
    return { ok: false, state: invalid("Schema、模型策略与编译器版本必须为 1 至 100 个字符。") };
  }
  const testSetId = field(formData, "test_set_id");
  const testSetVersion = integerField(formData, "test_set_version");
  const testSetHash = field(formData, "test_set_hash");
  const expectedVersion = integerField(formData, "expected_version");
  if (
    !UUID_PATTERN.test(testSetId)
    || testSetVersion === null
    || testSetVersion < 1
    || !validHash(testSetHash)
  ) {
    return { ok: false, state: invalid("测试集必须包含有效 UUID、版本和 SHA-256。") };
  }
  if (expectedVersion === null || expectedVersion < minimumExpectedVersion) {
    return { ok: false, state: invalid("期望版本无效，请刷新页面后重试。") };
  }
  return {
    ok: true,
    value: {
      system_template: systemTemplate,
      user_template: userTemplate,
      schemas: {
        variable_schema_version: variableSchemaVersion,
        variable_schema: variableSchema.value,
        input_schema_version: inputSchemaVersion,
        input_schema: inputSchema.value,
        output_schema_version: outputSchemaVersion,
        output_schema: outputSchema.value,
        application_output_schema_version: applicationOutputSchemaVersion,
        application_output_schema: applicationOutputSchema.value
      },
      model_policy: { version: modelPolicyVersion, policy: modelPolicy.value },
      test_set_id: testSetId,
      test_set_version: testSetVersion,
      test_set_hash: testSetHash,
      compiler_version: compilerVersion,
      expected_version: expectedVersion
    }
  };
}

export function commandKey(formData: FormData): string | null {
  const value = field(formData, "idempotency_key");
  return value.length >= 16 && value.length <= 200 && !/[\r\n]/.test(value)
    ? value
    : null;
}

export function field(formData: FormData, name: string): string {
  return String(formData.get(name) || "").trim();
}

export function integerField(formData: FormData, name: string): number | null {
  const value = Number(field(formData, name));
  return Number.isSafeInteger(value) ? value : null;
}

export function validPurpose(value: string): boolean {
  return PURPOSE_PATTERN.test(value);
}

export function validHash(value: string): boolean {
  return HASH_PATTERN.test(value);
}

export function parseJsonObjectField(
  formData: FormData,
  name: string,
  label: string
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const raw = field(formData, name);
  if (!raw) return { ok: false, error: `${label}不能为空。` };
  try {
    const value = JSON.parse(raw) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return { ok: false, error: `${label}必须是 JSON object。` };
    }
    return { ok: true, value: value as Record<string, unknown> };
  } catch {
    return { ok: false, error: `${label}不是有效 JSON。` };
  }
}

export function invalid(message: string): PromptActionState {
  return { kind: "error", status: 422, message: `输入无效：${message}` };
}

export function upstreamInvalid(message: string): PromptActionState {
  return { kind: "error", status: 502, message };
}

export function commandFailure(
  response: Extract<RuntimeResult<unknown>, { ok: false }>,
  fallback: string
): PromptActionState {
  return {
    kind: "error",
    ...(response.status === undefined ? {} : { status: response.status }),
    message: `${failureLabel(response.status)}${response.error || fallback}`,
    ...(response.problem.correlation_id
      ? { correlationId: response.problem.correlation_id }
      : {})
  };
}

export function releaseResult(release: PromptProgramRelease) {
  return {
    id: release.id,
    version: release.version,
    releaseHash: release.release_hash,
    status: release.state.status
  } as const;
}

export function promptHref(
  projectId: string,
  programId: string,
  releaseId?: string
): string {
  const params = new URLSearchParams({ tab: "prompts", prompt_program_id: programId });
  if (releaseId) params.set("prompt_release_id", releaseId);
  return `/projects/${encodeURIComponent(projectId)}?${params.toString()}`;
}

export function promptBase(projectId: string): string {
  return `/v1/projects/${encodeURIComponent(projectId)}/prompt-programs`;
}

function accessFailure(
  response: Extract<RuntimeResult<unknown>, { ok: false }>,
  fallback: string
): PromptActionState {
  return commandFailure(response, fallback);
}

function forbidden(message: string): PromptActionState {
  return { kind: "error", status: 403, message: `权限不足：${message}` };
}

function failureLabel(status: number | undefined): string {
  if (status === 401) return "登录已失效：";
  if (status === 403) return "权限不足：";
  if (status === 409) return "状态冲突：";
  if (status === 422) return "输入无效：";
  return "";
}
