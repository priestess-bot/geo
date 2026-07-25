"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest } from "../../../../runtime";
import {
  isPromptBootstrapCatalog,
  type PromptBootstrapCatalog
} from "./promptBootstrapTypes";
import {
  commandFailure,
  commandKey,
  field,
  integerField,
  invalid,
  parseJsonObjectField,
  parseReleasePayload,
  promptBase,
  promptHref,
  releaseResult,
  type PromptReleasePayload,
  upstreamInvalid,
  UUID_PATTERN,
  validHash,
  validPurpose,
  verifyPromptActor
} from "./promptProgramActionSupport";
import {
  isCreatedPromptProgramResponse,
  isCreatedPromptReleaseResponse,
  isPromptProgramBindingOptionPage,
  isPromptProgramBindingResponse,
  isPromptProgramDiffResponse,
  isPromptProgramSummary,
  isPromptProgramRelease,
  isPromptTestJobResponse,
  isTransitionedPromptProgramResponse,
  promptProgramKinds,
  type CreatedPromptProgramResponse,
  type CreatedPromptReleaseResponse,
  type PromptActionState,
  type PromptProgramBindingOptionPage,
  type PromptProgramBindingResponse,
  type PromptProgramDiffResponse,
  type PromptProgramKind,
  type PromptProgramRelease,
  type PromptProgramSummary,
  type PromptTestJobResponse,
  type TransitionedPromptProgramResponse
} from "./promptProgramTypes";

const CONTRIBUTORS = ["owner", "admin", "analyst"] as const;
const APPROVERS = ["owner", "admin"] as const;

export async function createPromptProgramAction(
  _previous: PromptActionState,
  formData: FormData
): Promise<PromptActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifyPromptActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const kindValue = field(formData, "program_kind");
  if (kindValue === "reference_translation") {
    return invalid("reference_translation 仅为预留类型，当前不允许创建发布版本。");
  }
  const kind = promptProgramKinds.find((candidate) => candidate === kindValue);
  if (!kind) {
    return invalid("Prompt Program 类型无效。");
  }
  const purpose = field(formData, "purpose");
  if (!validPurpose(purpose)) return invalid("用途格式无效。");
  const parsed = parseReleasePayload(formData, 0);
  if (!parsed.ok) return parsed.state;
  if (parsed.value.expected_version !== 0) {
    return invalid("新 Program 的期望版本必须为 0。");
  }
  const idempotencyKey = commandKey(formData);
  if (!idempotencyKey) return invalid("Idempotency-Key 无效，请刷新页面后重试。");
  const selectionFailure = await verifyBootstrapSelection({
    projectId,
    kind,
    purpose,
    release: parsed.value
  });
  if (selectionFailure) return selectionFailure;
  const response = await runtimeRequest<CreatedPromptProgramResponse>(promptBase(projectId), {
    method: "POST",
    idempotencyKey,
    body: { program_kind: kind, purpose, ...parsed.value }
  });
  if (!response.ok) return commandFailure(response, "Prompt Program 创建失败。");
  if (!isCreatedPromptProgramResponse(response.data)) {
    return upstreamInvalid("Prompt Program 创建接口返回了无法识别的响应。");
  }
  revalidateProject(projectId);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原创建结果。" : "Prompt Program v1 已创建。",
    nextHref: promptHref(projectId, response.data.program.id, response.data.release.id),
    release: releaseResult(response.data.release)
  };
}

export async function createPromptReleaseAction(
  _previous: PromptActionState,
  formData: FormData
): Promise<PromptActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifyPromptActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const programId = field(formData, "program_id");
  if (!UUID_PATTERN.test(programId)) return invalid("Program ID 无效。");
  const kindValue = field(formData, "program_kind");
  const kind = promptProgramKinds.find((candidate) => candidate === kindValue);
  if (!kind) return invalid("Prompt Program 类型无效。");
  const purpose = field(formData, "purpose");
  if (!validPurpose(purpose)) return invalid("用途格式无效。");
  const parsed = parseReleasePayload(formData, 1);
  if (!parsed.ok) return parsed.state;
  const idempotencyKey = commandKey(formData);
  if (!idempotencyKey) return invalid("Idempotency-Key 无效，请刷新页面后重试。");
  const selectionFailure = await verifyBootstrapSelection({
    projectId,
    programId,
    kind,
    purpose,
    release: parsed.value
  });
  if (selectionFailure) return selectionFailure;
  const response = await runtimeRequest<CreatedPromptReleaseResponse>(
    `${promptBase(projectId)}/${encodeURIComponent(programId)}/releases`,
    { method: "POST", idempotencyKey, body: parsed.value }
  );
  if (!response.ok) return commandFailure(response, "Prompt 发布版本创建失败。");
  if (!isCreatedPromptReleaseResponse(response.data)) {
    return upstreamInvalid("Prompt 发布版本创建接口返回了无法识别的响应。");
  }
  revalidateProject(projectId);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原发布版本结果。" : `发布版本 v${response.data.release.version} 已创建。`,
    nextHref: promptHref(projectId, programId, response.data.release.id),
    release: releaseResult(response.data.release)
  };
}

export async function enqueuePromptTestAction(
  _previous: PromptActionState,
  formData: FormData
): Promise<PromptActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifyPromptActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const ids = releaseIds(formData);
  if (!ids.ok) return ids.state;
  const testSetId = field(formData, "test_set_id");
  const testSetVersion = integerField(formData, "test_set_version");
  const testSetHash = field(formData, "test_set_hash");
  const runtimeSelectionId = field(formData, "runtime_selection_id");
  const expectedVersion = positiveStateVersion(formData);
  if (!UUID_PATTERN.test(testSetId) || testSetVersion === null || testSetVersion < 1 || !validHash(testSetHash)) {
    return invalid("冻结 TestSet 身份无效。");
  }
  if (!UUID_PATTERN.test(runtimeSelectionId)) return invalid("已批准运行时选择无效。");
  if (expectedVersion === null) return invalid("发布版本状态版本无效。");
  const idempotencyKey = commandKey(formData);
  if (!idempotencyKey) return invalid("Idempotency-Key 无效，请刷新页面后重试。");
  const response = await runtimeRequest<PromptTestJobResponse>(
    releaseCommandPath(projectId, ids.programId, ids.releaseId, "tests"),
    {
      method: "POST",
      idempotencyKey,
      body: {
        test_set_id: testSetId,
        test_set_version: testSetVersion,
        test_set_hash: testSetHash,
        runtime_selection_id: runtimeSelectionId,
        expected_version: expectedVersion
      }
    }
  );
  if (!response.ok) return commandFailure(response, "Prompt 测试任务排队失败。");
  if (!isPromptTestJobResponse(response.data)) {
    return upstreamInvalid("Prompt 测试接口返回了无法识别的响应。");
  }
  revalidateProject(projectId);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原测试任务。" : "测试任务已排队。",
    job: {
      id: response.data.job_id,
      status: response.data.status,
      inputHash: response.data.input_hash,
      testSetHash: response.data.test_set_hash
    }
  };
}

export async function approvePromptReleaseAction(
  _previous: PromptActionState,
  formData: FormData
): Promise<PromptActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifyPromptActor(projectId, APPROVERS);
  if (!access.ok) return access.state;
  return transitionRelease(formData, projectId, "approve", "发布版本已批准。");
}

export async function freezePromptReleaseAction(
  _previous: PromptActionState,
  formData: FormData
): Promise<PromptActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifyPromptActor(projectId, APPROVERS);
  if (!access.ok) return access.state;
  return transitionRelease(formData, projectId, "freeze", "发布版本已冻结。");
}

export async function retirePromptReleaseAction(
  _previous: PromptActionState,
  formData: FormData
): Promise<PromptActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifyPromptActor(projectId, APPROVERS);
  if (!access.ok) return access.state;
  if (field(formData, "confirm_retirement") !== "confirmed") {
    return invalid("退役前必须确认该发布版本将不再用于新的运行时解析。");
  }
  return transitionRelease(formData, projectId, "retire", "发布版本已退役。");
}

export async function bindPromptReleaseAction(
  _previous: PromptActionState,
  formData: FormData
): Promise<PromptActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifyPromptActor(projectId, APPROVERS);
  if (!access.ok) return access.state;
  const ids = releaseIds(formData);
  if (!ids.ok) return ids.state;
  const purpose = field(formData, "purpose");
  const expectedVersion = integerField(formData, "expected_version");
  if (!validPurpose(purpose) || expectedVersion === null || expectedVersion < 0) {
    return invalid("用途或当前绑定版本无效。");
  }
  const idempotencyKey = commandKey(formData);
  if (!idempotencyKey) return invalid("Idempotency-Key 无效，请刷新页面后重试。");
  const inventoryFailure = await verifyBindingSelection({
    projectId,
    programId: ids.programId,
    releaseId: ids.releaseId,
    purpose,
    expectedVersion
  });
  if (inventoryFailure) return inventoryFailure;
  const response = await runtimeRequest<PromptProgramBindingResponse>(
    `/v1/projects/${encodeURIComponent(projectId)}/prompt-program-bindings`,
    {
      method: "POST",
      idempotencyKey,
      body: {
        program_id: ids.programId,
        release_id: ids.releaseId,
        purpose,
        expected_version: expectedVersion
      }
    }
  );
  if (!response.ok) return commandFailure(response, "Prompt 绑定创建失败。");
  if (!isPromptProgramBindingResponse(response.data)) {
    return upstreamInvalid("Prompt 绑定接口返回了无法识别的响应。");
  }
  if (
    response.data.project_id !== projectId
    || response.data.program_id !== ids.programId
    || response.data.release_id !== ids.releaseId
    || response.data.purpose !== purpose
    || response.data.binding_version !== expectedVersion + 1
  ) {
    return upstreamInvalid("Prompt 绑定接口返回了不一致的绑定身份。");
  }
  revalidateProject(projectId);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原绑定结果。" : "冻结发布版本已绑定。",
    binding: {
      id: response.data.id,
      version: response.data.binding_version,
      releaseHash: response.data.release_hash
    }
  };
}

export async function diffPromptReleaseAction(
  _previous: PromptActionState,
  formData: FormData
): Promise<PromptActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifyPromptActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const ids = releaseIds(formData);
  if (!ids.ok) return ids.state;
  const baselineReleaseId = field(formData, "baseline_release_id");
  const expectedVersion = positiveStateVersion(formData);
  const fixedVariables = parseJsonObjectField(formData, "fixed_variables", "固定输入");
  if (!UUID_PATTERN.test(baselineReleaseId) || expectedVersion === null) {
    return invalid("基线发布版本或状态版本无效。");
  }
  if (!fixedVariables.ok) return invalid(fixedVariables.error);
  const idempotencyKey = commandKey(formData);
  if (!idempotencyKey) return invalid("Idempotency-Key 无效，请刷新页面后重试。");
  const response = await runtimeRequest<PromptProgramDiffResponse>(
    releaseCommandPath(projectId, ids.programId, ids.releaseId, "diff"),
    {
      method: "POST",
      idempotencyKey,
      body: {
        baseline_release_id: baselineReleaseId,
        fixed_variables: fixedVariables.value,
        expected_version: expectedVersion
      }
    }
  );
  if (!response.ok) return commandFailure(response, "Prompt 发布版本差异计算失败。");
  if (!isPromptProgramDiffResponse(response.data)) {
    return upstreamInvalid("Prompt 差异接口返回了无法识别的响应。");
  }
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原 Diff 结果。" : "固定输入差异已计算。",
    diff: response.data
  };
}

async function transitionRelease(
  formData: FormData,
  projectId: string,
  command: "approve" | "freeze" | "retire",
  successMessage: string
): Promise<PromptActionState> {
  const ids = releaseIds(formData);
  if (!ids.ok) return ids.state;
  const expectedVersion = positiveStateVersion(formData);
  if (expectedVersion === null) return invalid("发布版本状态版本无效。");
  const idempotencyKey = commandKey(formData);
  if (!idempotencyKey) return invalid("Idempotency-Key 无效，请刷新页面后重试。");
  const response = await runtimeRequest<TransitionedPromptProgramResponse>(
    releaseCommandPath(projectId, ids.programId, ids.releaseId, command),
    { method: "POST", idempotencyKey, body: { expected_version: expectedVersion } }
  );
  if (!response.ok) return commandFailure(response, `Prompt 发布版本 ${command} 失败。`);
  if (!isTransitionedPromptProgramResponse(response.data)) {
    return upstreamInvalid("Prompt 状态接口返回了无法识别的响应。");
  }
  revalidateProject(projectId);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原状态变更结果。" : successMessage,
    release: releaseResult(response.data.release),
    ...(response.data.admitted_test_evidence_hash
      ? { admittedEvidenceHash: response.data.admitted_test_evidence_hash }
      : {})
  };
}

function releaseIds(formData: FormData):
  | { ok: true; programId: string; releaseId: string }
  | { ok: false; state: PromptActionState } {
  const programId = field(formData, "program_id");
  const releaseId = field(formData, "release_id");
  if (!UUID_PATTERN.test(programId) || !UUID_PATTERN.test(releaseId)) {
    return { ok: false, state: invalid("程序或发布版本 ID 无效。") };
  }
  return { ok: true, programId, releaseId };
}

function positiveStateVersion(formData: FormData): number | null {
  const version = integerField(formData, "expected_version");
  return version !== null && version > 0 ? version : null;
}

function releaseCommandPath(
  projectId: string,
  programId: string,
  releaseId: string,
  command: "tests" | "approve" | "freeze" | "retire" | "diff"
): string {
  return `${promptBase(projectId)}/${encodeURIComponent(programId)}/releases/`
    + `${encodeURIComponent(releaseId)}/${command}`;
}

function revalidateProject(projectId: string): void {
  revalidatePath(`/projects/${projectId}`);
}

async function verifyBootstrapSelection({
  projectId,
  programId,
  kind,
  purpose,
  release
}: {
  projectId: string;
  programId?: string;
  kind: PromptProgramKind;
  purpose: string;
  release: PromptReleasePayload;
}): Promise<PromptActionState | null> {
  const catalogResponse = await runtimeRequest<PromptBootstrapCatalog>(
    `/v1/projects/${encodeURIComponent(projectId)}/prompt-bootstrap`
  );
  if (!catalogResponse.ok) {
    return commandFailure(catalogResponse, "冻结 Prompt 基线目录校验失败。");
  }
  if (!isPromptBootstrapCatalog(catalogResponse.data)) {
    return upstreamInvalid("Prompt 基线目录接口返回了无法识别的响应。");
  }
  const inventory = catalogResponse.data.items.find((item) => item.program_kind === kind);
  if (
    !inventory
    || inventory.purpose !== purpose
    || inventory.test_set_id !== release.test_set_id
    || inventory.test_set_version !== release.test_set_version
    || inventory.test_set_hash !== release.test_set_hash
    || inventory.variable_schema_version !== release.schemas.variable_schema_version
    || !sameJson(inventory.variable_schema, release.schemas.variable_schema)
    || inventory.input_schema_version !== release.schemas.input_schema_version
    || !sameJson(inventory.input_schema, release.schemas.input_schema)
    || inventory.output_schema_version !== release.schemas.output_schema_version
    || !sameJson(inventory.output_schema, release.schemas.output_schema)
    || inventory.application_output_schema_version
      !== release.schemas.application_output_schema_version
    || !sameJson(
      inventory.application_output_schema,
      release.schemas.application_output_schema
    )
    || inventory.model_policy_version !== release.model_policy.version
    || !sameJson(inventory.model_policy, release.model_policy.policy)
  ) {
    return invalid("用途或测试集已偏离冻结目录，请刷新页面后重试。");
  }
  if (!programId) return null;

  const programResponse = await runtimeRequest<PromptProgramSummary>(
    `${promptBase(projectId)}/${encodeURIComponent(programId)}`
  );
  if (!programResponse.ok) {
    return commandFailure(programResponse, "Prompt 程序归属校验失败。");
  }
  if (!isPromptProgramSummary(programResponse.data)) {
    return upstreamInvalid("Prompt 程序接口返回了无法识别的响应。");
  }
  if (
    programResponse.data.id !== programId
    || programResponse.data.project_id !== projectId
    || programResponse.data.program_kind !== kind
    || programResponse.data.purpose !== purpose
  ) {
    return invalid("Prompt 程序与冻结目录不一致，不能创建新发布版本。");
  }
  return null;
}

function sameJson(left: unknown, right: unknown): boolean {
  return canonicalJson(left) === canonicalJson(right);
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    const objectValue = value as Record<string, unknown>;
    return `{${Object.keys(objectValue).sort().map((key) => (
      `${JSON.stringify(key)}:${canonicalJson(objectValue[key])}`
    )).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

async function verifyBindingSelection({
  projectId,
  programId,
  releaseId,
  purpose,
  expectedVersion
}: {
  projectId: string;
  programId: string;
  releaseId: string;
  purpose: string;
  expectedVersion: number;
}): Promise<PromptActionState | null> {
  const releaseResponse = await runtimeRequest<PromptProgramRelease>(
    `${promptBase(projectId)}/${encodeURIComponent(programId)}/releases/${encodeURIComponent(releaseId)}`
  );
  if (!releaseResponse.ok) {
    return commandFailure(releaseResponse, "冻结发布版本归属校验失败。");
  }
  if (!isPromptProgramRelease(releaseResponse.data)) {
    return upstreamInvalid("Prompt 发布版本接口返回了无法识别的响应。");
  }
  const release = releaseResponse.data;
  if (
    release.project_id !== projectId
    || release.program_id !== programId
    || release.id !== releaseId
    || release.purpose !== purpose
    || release.state.status !== "frozen"
  ) {
    return invalid("用途或冻结发布版本身份已变化，请刷新页面后重试。");
  }
  const bindingsResponse = await runtimeRequest<PromptProgramBindingOptionPage>(
    `/v1/projects/${encodeURIComponent(projectId)}/prompt-program-bindings`,
    { query: { program_kind: release.program_kind, limit: 200, offset: 0 } }
  );
  if (!bindingsResponse.ok) {
    return commandFailure(bindingsResponse, "当前 Prompt 绑定目录校验失败。");
  }
  if (!isPromptProgramBindingOptionPage(bindingsResponse.data)) {
    return upstreamInvalid("Prompt 绑定目录接口返回了无法识别的响应。");
  }
  if (
    bindingsResponse.data.offset !== 0
    || bindingsResponse.data.items.length !== bindingsResponse.data.total
  ) {
    return upstreamInvalid("Prompt 绑定目录不完整，无法安全计算当前版本。");
  }
  const matches = bindingsResponse.data.items.filter((item) => (
    item.project_id === projectId
    && item.program_kind === release.program_kind
    && item.purpose === purpose
  ));
  if (matches.length > 1) {
    return upstreamInvalid("Prompt 绑定目录包含重复的当前用途。");
  }
  const authoritativeVersion = matches[0]?.binding_version || 0;
  if (authoritativeVersion !== expectedVersion) {
    return invalid("当前绑定版本已变化，请刷新页面后重试。");
  }
  return null;
}
