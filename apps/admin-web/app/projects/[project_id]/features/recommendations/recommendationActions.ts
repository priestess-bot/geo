"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest } from "../../../../runtime";
import {
  boundedReason,
  commandFailure,
  commandPath,
  draftResult,
  field,
  invalid,
  parseCommandFields,
  recommendationPath,
  recommendationResult,
  upstreamInvalid,
  UUID_PATTERN,
  verifyRecommendationActor,
  type RecommendationCommandFields
} from "./recommendationActionSupport";
import {
  isApprovedRecommendationResponse,
  isInvalidatedRecommendationResponse,
  isPreparedDraftActionResponse,
  isRecommendationCommandResponse,
  isReviewedRecommendationResponse
} from "./recommendationTypeGuards";
import {
  inputChangeReasons,
  type ApprovedRecommendationResponse,
  type InvalidatedRecommendationResponse,
  type PreparedDraftActionResponse,
  type RecommendationActionState,
  type RecommendationCommandResponse,
  type ReviewedRecommendationResponse
} from "./recommendationTypes";

const CONTRIBUTORS = ["owner", "admin", "analyst"] as const;
const APPROVERS = ["owner", "admin"] as const;

export async function submitRecommendationAction(
  _previous: RecommendationActionState,
  formData: FormData
): Promise<RecommendationActionState> {
  const parsed = parseCommandFields(formData);
  if (!parsed.ok) return parsed.state;
  const access = await verifyRecommendationActor(parsed.value.projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  return simpleCommand(parsed.value, "submit", "Recommendation 已提交审核。");
}

export async function reviewRecommendationAction(
  _previous: RecommendationActionState,
  formData: FormData
): Promise<RecommendationActionState> {
  const parsed = parseCommandFields(formData);
  if (!parsed.ok) return parsed.state;
  const access = await verifyRecommendationActor(parsed.value.projectId, APPROVERS);
  if (!access.ok) return access.state;
  const notes = field(formData, "notes");
  if (!notes || notes.length > 20_000) return invalid("审核记录为空或超过 20000 字符。");
  const response = await runtimeRequest<ReviewedRecommendationResponse>(
    commandPath(parsed.value, "review"),
    {
      method: "POST",
      idempotencyKey: parsed.value.idempotencyKey,
      body: {
        expected_version: parsed.value.expectedVersion,
        notes
      }
    }
  );
  if (!response.ok) return commandFailure(response, "Recommendation 审核失败。");
  if (!isReviewedRecommendationResponse(response.data)) {
    return upstreamInvalid("Recommendation 审核接口返回了无法识别的响应。");
  }
  revalidateProject(parsed.value.projectId);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原审核结果。" : "当前证据版本已审核。",
    recommendation: recommendationResult(response.data)
  };
}

export async function approveRecommendationAction(
  _previous: RecommendationActionState,
  formData: FormData
): Promise<RecommendationActionState> {
  const parsed = parseCommandFields(formData);
  if (!parsed.ok) return parsed.state;
  const access = await verifyRecommendationActor(parsed.value.projectId, APPROVERS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<ApprovedRecommendationResponse>(
    commandPath(parsed.value, "approve"),
    {
      method: "POST",
      idempotencyKey: parsed.value.idempotencyKey,
      body: { expected_version: parsed.value.expectedVersion }
    }
  );
  if (!response.ok) return commandFailure(response, "Recommendation 批准失败。");
  if (!isApprovedRecommendationResponse(response.data)) {
    return upstreamInvalid("Recommendation 批准接口返回了无法识别的响应。");
  }
  revalidateProject(parsed.value.projectId);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原批准结果。" : "已批准并仅创建未启动草稿。",
    recommendation: recommendationResult(response.data),
    ...(response.data.downstream_draft
      ? { draft: draftResult(response.data.downstream_draft) }
      : {}),
    actionBoundary: response.data.action_boundary
  };
}

export async function rejectRecommendationAction(
  _previous: RecommendationActionState,
  formData: FormData
): Promise<RecommendationActionState> {
  const parsed = parseCommandFields(formData);
  if (!parsed.ok) return parsed.state;
  const access = await verifyRecommendationActor(parsed.value.projectId, APPROVERS);
  if (!access.ok) return access.state;
  return reasonedCommand(formData, parsed.value, "reject", "Recommendation 已拒绝。");
}

export async function expireRecommendationAction(
  _previous: RecommendationActionState,
  formData: FormData
): Promise<RecommendationActionState> {
  const parsed = parseCommandFields(formData);
  if (!parsed.ok) return parsed.state;
  const access = await verifyRecommendationActor(parsed.value.projectId, APPROVERS);
  if (!access.ok) return access.state;
  return invalidateCommand(formData, parsed.value, "expire", "Recommendation 已过期。");
}

export async function reconcileRecommendationStaleAction(
  _previous: RecommendationActionState,
  formData: FormData
): Promise<RecommendationActionState> {
  const parsed = parseCommandFields(formData);
  if (!parsed.ok) return parsed.state;
  const access = await verifyRecommendationActor(parsed.value.projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const changeReason = field(formData, "change_reason");
  if (!inputChangeReasons.some((value) => value === changeReason)) {
    return invalid("输入变化原因无效。");
  }
  return invalidationRequest(
    parsed.value,
    "reconcile-stale",
    {
      expected_version: parsed.value.expectedVersion,
      change_reason: changeReason
    },
    "输入 lineage 已重新核对。"
  );
}

export async function prepareRecommendationDraftAction(
  _previous: RecommendationActionState,
  formData: FormData
): Promise<RecommendationActionState> {
  const parsed = parseCommandFields(formData);
  if (!parsed.ok) return parsed.state;
  const access = await verifyRecommendationActor(parsed.value.projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const draftId = field(formData, "draft_id");
  if (!UUID_PATTERN.test(draftId)) return invalid("关联草稿 ID 无效。");
  const changeReason = field(formData, "change_reason");
  if (!inputChangeReasons.some((value) => value === changeReason)) {
    return invalid("输入变化原因无效。");
  }
  const response = await runtimeRequest<PreparedDraftActionResponse>(
    `${recommendationPath(parsed.value)}/drafts/${encodeURIComponent(draftId)}/prepare-action`,
    {
      method: "POST",
      idempotencyKey: parsed.value.idempotencyKey,
      body: {
        expected_version: parsed.value.expectedVersion,
        change_reason: changeReason
      }
    }
  );
  if (!response.ok) return commandFailure(response, "草稿来源复核失败。");
  if (!isPreparedDraftActionResponse(response.data)) {
    return upstreamInvalid("草稿来源复核接口返回了无法识别的响应。");
  }
  revalidateProject(parsed.value.projectId);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原复核结果。" : "草稿来源复核通过，仍未执行或发布。",
    recommendation: recommendationResult(response.data),
    draft: draftResult(response.data.draft, response.data.authorized),
    actionBoundary: response.data.action_boundary
  };
}

async function simpleCommand(
  fields: RecommendationCommandFields,
  command: "submit",
  success: string
): Promise<RecommendationActionState> {
  const response = await runtimeRequest<RecommendationCommandResponse>(
    commandPath(fields, command),
    {
      method: "POST",
      idempotencyKey: fields.idempotencyKey,
      body: { expected_version: fields.expectedVersion }
    }
  );
  if (!response.ok) return commandFailure(response, "Recommendation 状态变更失败。");
  if (!isRecommendationCommandResponse(response.data)) {
    return upstreamInvalid("Recommendation 状态接口返回了无法识别的响应。");
  }
  revalidateProject(fields.projectId);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原状态结果。" : success,
    recommendation: recommendationResult(response.data)
  };
}

async function reasonedCommand(
  formData: FormData,
  fields: RecommendationCommandFields,
  command: "reject",
  success: string
): Promise<RecommendationActionState> {
  const reason = boundedReason(formData);
  if (!reason) return invalid("原因不能为空且不能超过 5000 字符。");
  const response = await runtimeRequest<RecommendationCommandResponse>(
    commandPath(fields, command),
    {
      method: "POST",
      idempotencyKey: fields.idempotencyKey,
      body: { expected_version: fields.expectedVersion, reason }
    }
  );
  if (!response.ok) return commandFailure(response, "Recommendation 拒绝失败。");
  if (!isRecommendationCommandResponse(response.data)) {
    return upstreamInvalid("Recommendation 拒绝接口返回了无法识别的响应。");
  }
  revalidateProject(fields.projectId);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原拒绝结果。" : success,
    recommendation: recommendationResult(response.data)
  };
}

async function invalidateCommand(
  formData: FormData,
  fields: RecommendationCommandFields,
  command: "expire",
  success: string
): Promise<RecommendationActionState> {
  const reason = boundedReason(formData);
  if (!reason) return invalid("原因不能为空且不能超过 5000 字符。");
  return invalidationRequest(
    fields,
    command,
    { expected_version: fields.expectedVersion, reason },
    success
  );
}

async function invalidationRequest(
  fields: RecommendationCommandFields,
  command: "expire" | "reconcile-stale",
  body: Record<string, unknown>,
  success: string
): Promise<RecommendationActionState> {
  const response = await runtimeRequest<InvalidatedRecommendationResponse>(
    commandPath(fields, command),
    { method: "POST", idempotencyKey: fields.idempotencyKey, body }
  );
  if (!response.ok) return commandFailure(response, "Recommendation 失效处理失败。");
  if (!isInvalidatedRecommendationResponse(response.data)) {
    return upstreamInvalid("Recommendation 失效接口返回了无法识别的响应。");
  }
  revalidateProject(fields.projectId);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原失效结果。" : success,
    recommendation: recommendationResult(response.data),
    cancelledOutboxCount: response.data.cancelled_outbox_ids.length
  };
}

function revalidateProject(projectId: string): void {
  revalidatePath(`/projects/${projectId}`);
}
