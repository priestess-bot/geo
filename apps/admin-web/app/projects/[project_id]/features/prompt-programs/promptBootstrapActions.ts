"use server";

import { runtimeRequest } from "../../../../runtime";
import {
  commandFailure,
  commandKey,
  field,
  validHash,
  verifyPromptActor
} from "./promptProgramActionSupport";
import {
  isPromptBootstrapDraftBatch,
  isPromptBootstrapEvaluation,
  type PromptBootstrapActionState,
  type PromptBootstrapDraftBatch,
  type PromptBootstrapEvaluation,
  type PromptBootstrapEvaluationState
} from "./promptBootstrapTypes";
import { promptProgramKinds, type PromptActionState } from "./promptProgramTypes";

const MANAGERS = ["owner", "admin"] as const;

export async function createPromptBootstrapDraftsAction(
  _previous: PromptBootstrapActionState,
  formData: FormData
): Promise<PromptBootstrapActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifyPromptActor(projectId, MANAGERS);
  if (!access.ok) return actionError(access.state);
  const catalogHash = field(formData, "catalog_hash");
  const idempotencyKey = commandKey(formData);
  if (!validHash(catalogHash) || !idempotencyKey) {
    return invalidAction("Catalog SHA-256 或 Idempotency-Key 无效。");
  }
  const response = await runtimeRequest<PromptBootstrapDraftBatch>(
    `${bootstrapBase(projectId)}/drafts`,
    {
      method: "POST",
      idempotencyKey,
      body: { catalog_hash: catalogHash }
    }
  );
  if (!response.ok) return actionError(commandFailure(response, "基线 Draft 创建失败。"));
  if (!isPromptBootstrapDraftBatch(response.data) || response.data.catalog_hash !== catalogHash) {
    return invalidUpstreamAction("基线 Draft 接口返回了不安全或无法识别的响应。");
  }
  return {
    kind: "success",
    message: response.data.failed_count
      ? "批次已完成，但部分 Draft 创建失败；可使用同一 Key 安全重试。"
      : `${promptProgramKinds.length} 个基线定义已创建或恢复为未批准 Draft。`,
    batch: response.data
  };
}

export async function evaluatePromptBootstrapAction(
  _previous: PromptBootstrapEvaluationState,
  formData: FormData
): Promise<PromptBootstrapEvaluationState> {
  const projectId = field(formData, "project_id");
  const access = await verifyPromptActor(projectId, MANAGERS);
  if (!access.ok) return evaluationError(access.state);
  const programKind = field(formData, "program_kind");
  const catalogHash = field(formData, "catalog_hash");
  const specHash = field(formData, "spec_hash");
  const testSetHash = field(formData, "test_set_hash");
  const outputs = parseOutputs(formData);
  if (!promptProgramKinds.some((kind) => kind === programKind)
    || ![catalogHash, specHash, testSetHash].every(validHash)
    || !outputs.ok) {
    return invalidEvaluation(outputs.ok
      ? "Kind 或冻结 SHA-256 无效。"
      : outputs.error);
  }
  const response = await runtimeRequest<PromptBootstrapEvaluation>(
    `${bootstrapBase(projectId)}/evaluate`,
    {
      method: "POST",
      body: {
        program_kind: programKind,
        catalog_hash: catalogHash,
        spec_hash: specHash,
        test_set_hash: testSetHash,
        outputs: outputs.value
      }
    }
  );
  if (!response.ok) return evaluationError(commandFailure(response, "离线目录评估失败。"));
  if (!isPromptBootstrapEvaluation(response.data)
    || response.data.catalog_hash !== catalogHash
    || response.data.spec_hash !== specHash
    || response.data.test_set_hash !== testSetHash
    || response.data.program_kind !== programKind) {
    return invalidUpstreamEvaluation("离线目录评估接口返回了不安全或无法识别的响应。");
  }
  return {
    kind: "success",
    message: response.data.passed ? "5 个固定 Fixture 全部通过。" : "评估已完成，但当前输出未达到目录门槛。",
    evaluation: response.data
  };
}

function parseOutputs(formData: FormData): { ok: true; value: Record<string, Record<string, unknown>> } | {
  ok: false;
  error: string;
} {
  const raw = field(formData, "outputs");
  if (!raw || raw.length > 1_000_000) return { ok: false, error: "Outputs JSON 为空或超过 1000000 字符。" };
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!record(parsed) || Object.keys(parsed).length !== 5 || !Object.values(parsed).every(record)) {
      return { ok: false, error: "Outputs 必须是恰含 5 个 Fixture object 的 JSON object。" };
    }
    return { ok: true, value: parsed as Record<string, Record<string, unknown>> };
  } catch {
    return { ok: false, error: "Outputs 不是有效 JSON。" };
  }
}

function bootstrapBase(projectId: string): string {
  return `/v1/projects/${encodeURIComponent(projectId)}/prompt-bootstrap`;
}

function actionError(state: PromptActionState): PromptBootstrapActionState {
  return { kind: "error", message: state.message || "基线 Draft 操作失败。", ...problemFields(state) };
}

function evaluationError(state: PromptActionState): PromptBootstrapEvaluationState {
  return { kind: "error", message: state.message || "离线目录评估失败。", ...problemFields(state) };
}

function problemFields(state: PromptActionState) {
  return {
    ...(state.status === undefined ? {} : { status: state.status }),
    ...(state.correlationId ? { correlationId: state.correlationId } : {})
  };
}

function invalidAction(message: string): PromptBootstrapActionState {
  return { kind: "error", status: 422, message: `输入无效：${message}` };
}

function invalidEvaluation(message: string): PromptBootstrapEvaluationState {
  return { kind: "error", status: 422, message: `输入无效：${message}` };
}

function invalidUpstreamAction(message: string): PromptBootstrapActionState {
  return { kind: "error", status: 502, message };
}

function invalidUpstreamEvaluation(message: string): PromptBootstrapEvaluationState {
  return { kind: "error", status: 502, message };
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
