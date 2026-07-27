"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import { verifyPromptActor } from "./promptProgramActionSupport";
import {
  isPromptProgramRelease,
  isPromptRenderPreview,
  isPromptTestJobResponse,
  isPromptTestRunPage,
  isPromptWorkingDraft,
  type PromptProgramBindingOption,
  type PromptProgramRelease,
  type PromptRenderPreview,
  type PromptTestJobResponse,
  type PromptTestRunPage,
  type PromptWorkingDraft
} from "./promptProgramTypes";
import {
  isPromptBootstrapCatalog,
  isPromptBootstrapDraftBatch,
  type PromptBootstrapCatalog,
  type PromptBootstrapDraftBatch
} from "./promptBootstrapTypes";

type ActionResult<T> =
  | Readonly<{ ok: true; data: T }>
  | Readonly<{ ok: false; message: string; status?: number; correlationId?: string }>;

export type PromptSuiteResult = Readonly<{
  draft: PromptWorkingDraft;
  candidate_release: PromptProgramRelease;
  job: PromptTestJobResponse;
}>;

export type PromptPublishResult = Readonly<{
  draft: PromptWorkingDraft;
  release: PromptProgramRelease;
  binding: PromptProgramBindingOption;
}>;

export async function initializePromptWorkspaceAction(input: Readonly<{
  projectId: string;
}>): Promise<ActionResult<PromptBootstrapDraftBatch>> {
  const access = await verifyPromptActor(input.projectId, ["owner", "admin"]);
  if (!access.ok) return actionStateFailure(access.state);
  const base = `/v1/projects/${encodeURIComponent(input.projectId)}/prompt-bootstrap`;
  const catalog = await runtimeRequest<PromptBootstrapCatalog>(base);
  if (!catalog.ok) return requestFailure(catalog, "默认 Prompt 目录加载失败。");
  if (!isPromptBootstrapCatalog(catalog.data)) return invalidResponse();
  const response = await runtimeRequest<PromptBootstrapDraftBatch>(`${base}/drafts`, {
    method: "POST",
    idempotencyKey: `prompt-workspace-bootstrap:${input.projectId}:${catalog.data.catalog_hash}`,
    body: { catalog_hash: catalog.data.catalog_hash }
  });
  if (!response.ok) return requestFailure(response, "默认 Prompt 初始化失败。");
  if (!isPromptBootstrapDraftBatch(response.data)) return invalidResponse();
  revalidateProject(input.projectId);
  return { ok: true, data: response.data };
}

export async function savePromptDraftAction(input: Readonly<{
  projectId: string;
  programId: string;
  displayName: string;
  systemTemplate: string;
  userTemplate: string;
  expectedRevision: number;
}>): Promise<ActionResult<PromptWorkingDraft>> {
  const access = await verifyPromptActor(input.projectId, ["owner", "admin", "analyst"]);
  if (!access.ok) return actionStateFailure(access.state);
  const response = await runtimeRequest<PromptWorkingDraft>(draftPath(input), {
    method: "PUT",
    body: {
      display_name: input.displayName,
      system_template: input.systemTemplate,
      user_template: input.userTemplate,
      expected_revision: input.expectedRevision
    }
  });
  if (!response.ok) return requestFailure(response, "草稿保存失败。");
  if (!isPromptWorkingDraft(response.data)) return invalidResponse();
  return { ok: true, data: response.data };
}

export async function renderPromptDraftAction(input: Readonly<{
  projectId: string;
  programId: string;
  fixtureId?: string;
}>): Promise<ActionResult<PromptRenderPreview>> {
  const response = await runtimeRequest<PromptRenderPreview>(
    `${draftPath(input).replace(/\/draft$/, "")}/render-preview`,
    { method: "POST", body: { fixture_id: input.fixtureId || null } }
  );
  if (!response.ok) return requestFailure(response, "Prompt 拼接预览失败。");
  if (!isPromptRenderPreview(response.data)) return invalidResponse();
  return { ok: true, data: response.data };
}

export async function runPromptSuiteAction(input: Readonly<{
  projectId: string;
  programId: string;
  runtimeSelectionId: string;
  expectedRevision: number;
  idempotencyKey: string;
}>): Promise<ActionResult<PromptSuiteResult>> {
  const access = await verifyPromptActor(input.projectId, ["owner", "admin", "analyst"]);
  if (!access.ok) return actionStateFailure(access.state);
  const response = await runtimeRequest<PromptSuiteResult>(
    `${draftPath(input).replace(/\/draft$/, "")}/suite-runs`,
    {
      method: "POST",
      idempotencyKey: input.idempotencyKey,
      body: {
        runtime_selection_id: input.runtimeSelectionId,
        expected_revision: input.expectedRevision
      }
    }
  );
  if (!response.ok) return requestFailure(response, "固定测试集启动失败。");
  if (!isPromptSuiteResult(response.data)) return invalidResponse();
  revalidateProject(input.projectId);
  return { ok: true, data: response.data };
}

export async function loadPromptTestRunsAction(input: Readonly<{
  projectId: string;
  programId: string;
}>): Promise<ActionResult<PromptTestRunPage>> {
  const response = await runtimeRequest<PromptTestRunPage>(
    `${draftPath(input).replace(/\/draft$/, "")}/test-runs`,
    { query: { limit: 20 } }
  );
  if (!response.ok) return requestFailure(response, "测试结果刷新失败。");
  if (!isPromptTestRunPage(response.data)) return invalidResponse();
  return { ok: true, data: response.data };
}

export async function publishPromptDraftAction(input: Readonly<{
  projectId: string;
  programId: string;
  expectedRevision: number;
  idempotencyKey: string;
}>): Promise<ActionResult<PromptPublishResult>> {
  const access = await verifyPromptActor(input.projectId, ["owner", "admin"]);
  if (!access.ok) return actionStateFailure(access.state);
  const response = await runtimeRequest<PromptPublishResult>(
    `${draftPath(input).replace(/\/draft$/, "")}/publish`,
    {
      method: "POST",
      idempotencyKey: input.idempotencyKey,
      body: { expected_revision: input.expectedRevision }
    }
  );
  if (!response.ok) return requestFailure(response, "Prompt 发布失败。");
  if (!isPromptPublishResult(response.data)) return invalidResponse();
  revalidateProject(input.projectId);
  return { ok: true, data: response.data };
}

function draftPath(input: { projectId: string; programId: string }): string {
  return `/v1/projects/${encodeURIComponent(input.projectId)}/prompt-programs/${encodeURIComponent(input.programId)}/draft`;
}

function isPromptSuiteResult(value: unknown): value is PromptSuiteResult {
  return record(value)
    && isPromptWorkingDraft(value.draft)
    && isPromptProgramRelease(value.candidate_release)
    && isPromptTestJobResponse(value.job);
}

function isPromptPublishResult(value: unknown): value is PromptPublishResult {
  return record(value)
    && isPromptWorkingDraft(value.draft)
    && isPromptProgramRelease(value.release)
    && isBinding(value.binding);
}

function isBinding(value: unknown): value is PromptProgramBindingOption {
  return record(value)
    && [value.id, value.project_id, value.purpose, value.program_id, value.release_id].every(nonEmpty)
    && positive(value.release_version)
    && positive(value.binding_version);
}

function requestFailure(
  response: RuntimeResult<unknown>,
  fallback: string
): ActionResult<never> {
  return {
    ok: false,
    message: response.ok ? fallback : response.error || fallback,
    ...(!response.ok && response.status !== undefined ? { status: response.status } : {}),
    ...(!response.ok && response.problem.correlation_id
      ? { correlationId: response.problem.correlation_id }
      : {})
  };
}

function actionStateFailure(value: Readonly<{
  message?: string;
  status?: number;
  correlationId?: string;
}>): ActionResult<never> {
  return {
    ok: false,
    message: value.message || "当前操作不可用。",
    ...(value.status === undefined ? {} : { status: value.status }),
    ...(value.correlationId ? { correlationId: value.correlationId } : {})
  };
}

function invalidResponse(): ActionResult<never> {
  return { ok: false, message: "Prompt 工作台接口返回了无法识别的响应。", status: 502 };
}

function revalidateProject(projectId: string): void {
  revalidatePath(`/projects/${encodeURIComponent(projectId)}`);
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function nonEmpty(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function positive(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}
