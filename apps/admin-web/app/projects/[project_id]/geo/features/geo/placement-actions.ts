"use server";

import type { JsonObject } from "@geo/types/geo";
import { checked, client, finish, guards, isActionError, jsonArray, jsonObject, lines, numberValue, type ActionResult, value } from "./action-utils";
import type { PackageClaimEdit } from "@geo/types/geo";

function isPackageClaimEdit(item: unknown): item is PackageClaimEdit {
  if (item === null || typeof item !== "object" || Array.isArray(item)) return false;
  const claim = item as Record<string, unknown>;
  return typeof claim.text === "string"
    && ["factual", "comparative", "experience", "non_factual"].includes(String(claim.kind))
    && ["supported", "unsupported", "conflict", "not_required"].includes(String(claim.support_status))
    && Array.isArray(claim.evidence_item_ids)
    && claim.evidence_item_ids.every((id) => typeof id === "string");
}

export async function createBrief(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), goals = jsonObject(form, "goals"), constraints = jsonObject(form, "constraints");
  if (isActionError(goals)) return goals; if (isActionError(constraints)) return constraints;
  const api = await client(), description = value(form, "consumer_experience_description");
  return finish(projectId, await api.createBriefVersion(projectId, value(form, "opportunity_id"), {
    primary_brand_entity_id: value(form, "primary_brand_entity_id"), base_version_id: value(form, "base_version_id") || null,
    allowed_subject_entity_ids: lines(form, "allowed_subject_entity_ids"), compared_entity_ids: lines(form, "compared_entity_ids"),
    goals, constraints, consumer_experience: description ? {
      description, source: value(form, "consumer_experience_source"), usage_rights: value(form, "consumer_experience_usage_rights"),
      disclosure: value(form, "consumer_experience_disclosure")
    } : null
  }, guards(form)), "Brief 新版本已创建");
}

export async function buildEvidence(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  const result = await api.buildEvidenceAttempt(projectId, value(form, "brief_version_id"), guards(form));
  const outcome = finish(projectId, result, "Evidence Pack 构建任务已创建");
  return result.ok ? { ...outcome, nextHref: `/projects/${projectId}/geo?section=placement&brief_version_id=${result.data.resource.brief_version_id}&attempt_id=${result.data.resource.id}&job_id=${result.data.job_id}` } : outcome;
}

export async function createPromptSkill(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.createPromptSkill(projectId, { skill_key: value(form, "skill_key") }, guards(form)), "Prompt Skill 已创建");
}

export async function createPromptRelease(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), outputSchema = jsonObject(form, "output_schema");
  if (isActionError(outputSchema)) return outputSchema;
  const api = await client();
  return finish(projectId, await api.createPromptRelease(projectId, value(form, "skill_id"), {
    source: value(form, "source"), output_schema: outputSchema, client_variable_names: lines(form, "client_variable_names")
  }, guards(form)), "不可变 Prompt Release 已创建");
}

export async function bindPromptTask(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.bindPromptTask(projectId, value(form, "task_key"), { template_release_id: value(form, "template_release_id") }, guards(form)), "任务已绑定 Prompt Release");
}

export async function createPromptBundle(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), variables = jsonObject(form, "variables");
  if (isActionError(variables)) return variables;
  const api = await client();
  return finish(projectId, await api.createPromptBundle(projectId, value(form, "brief_version_id"), {
    evidence_pack_attempt_id: value(form, "evidence_pack_attempt_id"), template_release_id: value(form, "template_release_id"),
    model_policy_hash: value(form, "model_policy_hash"), variables
  }, guards(form)), "Prompt Bundle 工件已冻结");
}

export async function createGenerationJob(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  const bundleId = value(form, "bundle_id");
  const result = await api.createGenerationJob(projectId, bundleId, {
    configured_model: value(form, "configured_model") || "deepseek-chat",
    model_call_budget: numberValue(form, "model_call_budget", 3)
  }, guards(form));
  const outcome = finish(projectId, result, "文案生成任务已排队");
  return result.ok ? { ...outcome, nextHref: `/projects/${projectId}/geo?section=placement&bundle_id=${bundleId}&job_id=${result.data.job_id}` } : outcome;
}

export async function controlJob(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), jobId = value(form, "job_id"), command = value(form, "command"), api = await client();
  const result = command === "cancel" ? api.cancelJob(projectId, jobId, guards(form))
    : command === "replay" ? api.replayJob(projectId, jobId, guards(form)) : api.retryJob(projectId, jobId, guards(form));
  return finish(projectId, await result, `任务已执行 ${command}`);
}

export async function submitPackageReview(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.submitReview(projectId, value(form, "version_id"), guards(form)), "版本已提交双人复核");
}

export async function reviewPackage(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.reviewPackage(projectId, value(form, "version_id"), {
    decision: value(form, "decision") as "approved" | "needs_revision" | "rejected" | "blocked",
    claim_inventory_complete: checked(form, "claim_inventory_complete"),
    extracted_claim_support_confirmed: checked(form, "extracted_claim_support_confirmed"),
    notes: value(form, "notes") || null, score: value(form, "score") ? numberValue(form, "score") : null
  }, guards(form)), "人工复核结论已保存");
}

export async function editPackage(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), contentJson = jsonObject(form, "content_json"), claims = jsonArray(form, "claims");
  if (isActionError(contentJson)) return contentJson; if (isActionError(claims)) return claims;
  const editedClaims = claims.filter(isPackageClaimEdit);
  if (!claims.length || editedClaims.length !== claims.length) {
    return { error: "claims 必须是非空且结构完整的 Claim 清单", status: 422, code: "invalid_claim_inventory" };
  }
  const api = await client();
  return finish(projectId, await api.editPackage(projectId, value(form, "package_id"), {
    base_version_id: value(form, "base_version_id"), base_content_hash: value(form, "base_content_hash"),
    content_json: contentJson, rendered_text: value(form, "rendered_text"), reason: value(form, "reason"),
    claims: editedClaims
  }, { ...guards(form), ifMatch: value(form, "base_content_hash") }), "编辑已创建新版本，旧审批未被复用");
}

export async function createExport(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.createExport(projectId, value(form, "version_id"), guards(form)), "不可变导出工件已创建；未产生发布任务");
}

export async function createPublication(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.createPublication(projectId, value(form, "version_id"), {
    destination_id: value(form, "destination_id"), policy_basis: value(form, "policy_basis") || null,
    publication_attempt: numberValue(form, "publication_attempt", 1), restricted_policy_acknowledged: checked(form, "restricted_policy_acknowledged")
  }, guards(form)), "显式待发布任务已创建");
}

export async function transitionPublication(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.transitionPublication(projectId, value(form, "publication_id"), value(form, "command"),
    { reason: value(form, "reason") }, guards(form)), "发布任务状态已更新");
}

export async function createSubmission(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.createSubmission(projectId, value(form, "publication_id"), {
    provider_submission_id: value(form, "provider_submission_id") || null, submitted_url: value(form, "submitted_url") || null
  }, guards(form)), "人工投放提交记录已创建");
}

export async function setSubmissionUrl(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.setSubmissionUrl(projectId, value(form, "submission_id"), { submitted_url: value(form, "submitted_url") }, guards(form)), "公开 URL 已回填");
}

export async function blockSubmission(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.blockSubmission(projectId, value(form, "submission_id"), { reason: value(form, "reason") }, guards(form)), "提交记录已阻断");
}

export async function verifySubmission(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  const submissionId = value(form, "submission_id"), result = await api.verifySubmission(projectId, submissionId, guards(form));
  const outcome = finish(projectId, result, "公开 URL 验证任务已排队");
  return result.ok ? { ...outcome, nextHref: `/projects/${projectId}/geo?section=placement&submission_id=${submissionId}&job_id=${result.data.job_id}` } : outcome;
}

export async function createMeasurement(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), metrics = jsonObject(form, "metrics");
  if (isActionError(metrics)) return metrics;
  const api = await client();
  return finish(projectId, await api.createMeasurement(projectId, value(form, "submission_id"), {
    monitoring_query_id: value(form, "monitoring_query_id"), measured_at: value(form, "measured_at"),
    citation_present: checked(form, "citation_present"), result_snapshot_uri: value(form, "result_snapshot_uri"),
    recommendation_position: value(form, "recommendation_position") ? numberValue(form, "recommendation_position") : null,
    metrics: metrics as JsonObject
  }, guards(form)), "投放效果测量已记录");
}
