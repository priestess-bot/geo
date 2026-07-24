"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest } from "../../../../runtime";
import {
  field,
  UUID_PATTERN,
  verifyRecommendationActor
} from "./recommendationActionSupport";
import {
  isRecommendationGenerationJob,
  type RecommendationGenerationActionState,
  type RecommendationGenerationJob
} from "./recommendationGenerationTypes";

const CONTRIBUTORS = ["owner", "admin", "analyst"] as const;
const EVIDENCE_KINDS = new Set([
  "observation", "metric_comparison", "fact", "rule", "content", "question", "surface"
]);

export async function enqueueRecommendationGenerationAction(
  _previous: RecommendationGenerationActionState,
  formData: FormData
): Promise<RecommendationGenerationActionState> {
  const projectId = field(formData, "project_id");
  const idempotencyKey = field(formData, "idempotency_key");
  if (!UUID_PATTERN.test(projectId) || idempotencyKey.length < 16 || idempotencyKey.length > 200) {
    return invalid("项目或幂等键无效。");
  }
  const access = await verifyRecommendationActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const scope = jsonObject(field(formData, "scope"));
  const evidenceSelectors = selectors(field(formData, "evidence_selectors"));
  const promptBindingId = field(formData, "prompt_binding_id");
  const model = modelSelector(formData, "model_");
  const validUntil = validTimestamp(field(formData, "valid_until"));
  const minimum = Number(field(formData, "minimum_real_observations"));
  if (!scope || !evidenceSelectors || !UUID_PATTERN.test(promptBindingId) || !model
    || !validUntil || !Number.isSafeInteger(minimum) || minimum < 1 || minimum > 1000) {
    return invalid("Scope、证据选择器、Prompt、模型或有效期无效。");
  }
  delete scope.project_id;
  const arbiterEnabled = field(formData, "arbiter_enabled") === "on";
  const arbiterPrompt = field(formData, "arbiter_prompt_binding_id");
  const arbiterModel = arbiterEnabled ? modelSelector(formData, "arbiter_") : null;
  if (arbiterEnabled && (!UUID_PATTERN.test(arbiterPrompt) || !arbiterModel)) {
    return invalid("启用仲裁时必须选择完整的 Arbiter Prompt 和模型 Release。");
  }
  const response = await runtimeRequest<RecommendationGenerationJob>(
    `/v1/projects/${encodeURIComponent(projectId)}/recommendations/generation-jobs`,
    {
      method: "POST",
      idempotencyKey,
      body: {
        scope,
        evidence_selectors: evidenceSelectors,
        prompt_binding_id: promptBindingId,
        model,
        valid_until: validUntil,
        minimum_real_observations: minimum,
        arbiter_prompt_binding_id: arbiterEnabled ? arbiterPrompt : null,
        arbiter_model: arbiterModel
      }
    }
  );
  if (!response.ok) {
    return {
      kind: "error",
      ...(response.status === undefined ? {} : { status: response.status }),
      message: response.error || "Recommendation 生成任务入队失败。",
      ...(response.problem.correlation_id
        ? { correlationId: response.problem.correlation_id }
        : {})
    };
  }
  if (!isRecommendationGenerationJob(response.data)) {
    return { kind: "error", status: 502, message: "生成任务接口返回了无效响应。" };
  }
  revalidatePath(`/projects/${projectId}`);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原生成任务。" : "生成任务已进入 Durable Job 队列。",
    job: response.data
  };
}

function modelSelector(formData: FormData, prefix: string) {
  const runtimeSelectionId = field(formData, `${prefix}runtime_selection_id`);
  const rawSearchMode = field(formData, `${prefix}search_mode`);
  const searchMode = rawSearchMode === "__none__" ? null : rawSearchMode;
  if (!UUID_PATTERN.test(runtimeSelectionId)
    || (searchMode !== null && !/^[a-z][a-z0-9_.-]{0,63}$/.test(searchMode))) return null;
  return {
    runtime_selection_id: runtimeSelectionId,
    search_mode: searchMode
  };
}

function selectors(value: string): Array<{ kind: string; resource_id: string }> | null {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!Array.isArray(parsed) || !parsed.length) return null;
    const result = parsed.filter((item): item is { kind: string; resource_id: string } =>
      record(item) && EVIDENCE_KINDS.has(String(item.kind)) && nonEmptyString(item.resource_id)
    ).map((item) => ({ kind: item.kind, resource_id: item.resource_id.trim() }));
    const keys = result.map((item) => `${item.kind}:${item.resource_id}`);
    return result.length === parsed.length && new Set(keys).size === keys.length ? result : null;
  } catch {
    return null;
  }
}

function jsonObject(value: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(value) as unknown;
    return record(parsed) ? { ...parsed } : null;
  } catch {
    return null;
  }
}

function validTimestamp(value: string): string | null {
  const date = new Date(value);
  return value && !Number.isNaN(date.valueOf()) ? date.toISOString() : null;
}

function invalid(message: string): RecommendationGenerationActionState {
  return { kind: "error", status: 422, message };
}

function record(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}
