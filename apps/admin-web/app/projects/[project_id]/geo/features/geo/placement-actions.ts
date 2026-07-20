"use server";

import type {
  JsonObject,
  PromptSimulationAuthenticityMode,
  PromptSimulationPurpose
} from "@geo/types/geo";
import { checked, client, finish, guards, isActionError, jsonArray, jsonObject, lines, numberValue, type ActionResult, value } from "./action-utils";
import type { PackageClaimEdit } from "@geo/types/geo";

function isPackageClaimEdit(item: unknown): item is PackageClaimEdit {
  if (item === null || typeof item !== "object" || Array.isArray(item)) return false;
  const claim = item as Partial<PackageClaimEdit>;
  return typeof claim.text === "string"
    && ["factual", "comparative", "experience", "non_factual"].includes(String(claim.kind))
    && ["supported", "unsupported", "conflict", "not_required"].includes(String(claim.support_status))
    && Array.isArray(claim.evidence_item_ids)
    && claim.evidence_item_ids.every((id) => typeof id === "string");
}

export async function createBrief(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), structured = !value(form, "goals");
  const goals = structured ? {
    audience: value(form, "audience"), intent: value(form, "intent"),
    deliverable: value(form, "deliverable"), value_propositions: lines(form, "value_propositions")
  } : jsonObject(form, "goals");
  const constraints = structured ? {
    unsupported_superlatives: checked(form, "unsupported_superlatives"),
    public_citations_required: checked(form, "public_citations_required"),
    commercial_disclosure_required: checked(form, "commercial_disclosure_required"),
    maximum_words: numberValue(form, "maximum_words", 500)
  } : jsonObject(form, "constraints");
  if (isActionError(goals)) return goals; if (isActionError(constraints)) return constraints;
  const api = await client(), description = value(form, "consumer_experience_description");
  return finish(projectId, await api.createBriefVersion(projectId, campaignId, value(form, "opportunity_id"), {
    primary_brand_entity_id: value(form, "primary_brand_entity_id"), base_version_id: value(form, "base_version_id") || null,
    allowed_subject_entity_ids: multiValues(form, "allowed_subject_entity_ids"),
    compared_entity_ids: multiValues(form, "compared_entity_ids"),
    goals, constraints, consumer_experience: description ? {
      description, source: value(form, "consumer_experience_source"), usage_rights: value(form, "consumer_experience_usage_rights"),
      disclosure: value(form, "consumer_experience_disclosure")
    } : null
  }, guards(form)), "Brief 新版本已创建");
}

function multiValues(form: FormData, field: string): string[] {
  return form.getAll(field).flatMap((item) => String(item).split(/\r?\n|,/)).map((item) => item.trim()).filter(Boolean);
}

export async function buildEvidence(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), api = await client();
  const result = await api.buildEvidenceAttempt(projectId, campaignId, value(form, "brief_version_id"), guards(form));
  const outcome = finish(projectId, result, "Evidence Pack 构建任务已创建");
  return result.ok ? {
    ...outcome,
    nextHref: `/projects/${projectId}?tab=geo&geo_section=placement&placement_stage=evidence&campaign_id=${result.data.resource.campaign_id}&opportunity_id=${result.data.resource.opportunity_id}&brief_version_id=${result.data.resource.brief_version_id}&attempt_id=${result.data.resource.id}&job_id=${result.data.job_id}`
  } : outcome;
}

export async function createPromptSkill(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.createPromptSkill(projectId, { skill_key: value(form, "skill_key") }, guards(form)), "Prompt Skill 已创建");
}

export async function installDefaultPromptCatalog(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.installDefaultPromptCatalog(projectId, guards(form)), "九平台默认 Prompt Catalog 已安装");
}

export async function createPromptRelease(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), outputSchema = jsonObject(form, "output_schema");
  if (isActionError(outputSchema)) return outputSchema;
  const api = await client();
  return finish(projectId, await api.createPromptRelease(projectId, value(form, "skill_id"), {
    source: value(form, "source"), system_template: value(form, "system_template"),
    user_template: value(form, "user_template"), output_schema: outputSchema,
    client_variable_names: lines(form, "client_variable_names")
  }, guards(form)), "不可变 Prompt Release 已创建");
}

export async function transitionPromptRelease(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id");
  const command = value(form, "command") as "approve" | "revoke";
  const api = await client();
  return finish(projectId, await api.transitionPromptRelease(
    projectId,
    value(form, "release_id"),
    command,
    {
      expected_state_version: numberValue(form, "expected_state_version"),
      reason: value(form, "reason") || null
    },
    guards(form)
  ), command === "approve" ? "Prompt Release 已批准" : "Prompt Release 已撤销");
}

export async function bindOpportunityPromptRelease(
  _state: ActionResult,
  form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id");
  const api = await client();
  return finish(projectId, await api.bindOpportunityPromptRelease(
    projectId,
    campaignId,
    value(form, "opportunity_id"),
    {
      template_release_id: value(form, "template_release_id"),
      reason: value(form, "reason") || null,
      expected_binding_version: numberValue(form, "expected_binding_version")
    },
    guards(form)
  ), "Opportunity 已追加 Prompt Release 绑定");
}

export async function createPromptBundle(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), variables = jsonObject(form, "variables");
  if (isActionError(variables)) return variables;
  if (!checked(form, "confirm_prompt_release")) {
    return { error: "必须确认当前 Opportunity 的 Prompt Release identity", status: 422, code: "prompt_release_confirmation_required" };
  }
  const api = await client();
  return finish(projectId, await api.createPromptBundle(projectId, campaignId, value(form, "brief_version_id"), {
    campaign_id: campaignId,
    opportunity_id: value(form, "opportunity_id"),
    prompt_release_binding_id: value(form, "prompt_release_binding_id"),
    confirmed_release_hash: value(form, "confirmed_release_hash"),
    evidence_pack_attempt_id: value(form, "evidence_pack_attempt_id"),
    model_policy_hash: value(form, "model_policy_hash"), variables
  }, guards(form)), "Prompt Bundle 工件已冻结");
}

export async function createGenerationJob(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), api = await client();
  const bundleId = value(form, "bundle_id");
  const result = await api.createGenerationJob(projectId, campaignId, bundleId, {
    configured_model: value(form, "configured_model") || "deepseek-v4-flash",
    model_call_budget: numberValue(form, "model_call_budget", 2)
  }, guards(form));
  const outcome = finish(projectId, result, "文案生成任务已排队");
  return result.ok ? { ...outcome, nextHref: `/projects/${projectId}?tab=geo&geo_section=placement&campaign_id=${campaignId}&bundle_id=${bundleId}&job_id=${result.data.job_id}` } : outcome;
}

export async function createPromptSimulation(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id");
  const structured = !value(form, "goals");
  const goals = structured ? {
    intent: value(form, "intent"), audience: value(form, "audience"), deliverable: value(form, "deliverable")
  } : jsonObject(form, "goals");
  const constraints = structured ? {
    test_only: true,
    unsupported_superlatives: checked(form, "unsupported_superlatives"),
    public_citations_required: checked(form, "public_citations_required")
  } : jsonObject(form, "constraints");
  const variables = jsonObject(form, "variables");
  if (isActionError(goals)) return goals;
  if (isActionError(constraints)) return constraints;
  if (isActionError(variables)) return variables;
  const destinationId = value(form, "destination_id");
  const bindingId = value(form, "prompt_release_binding_id");
  const confirmedReleaseHash = value(form, "confirmed_release_hash");
  if (!destinationId || !bindingId || !/^[0-9a-f]{64}$/.test(confirmedReleaseHash)) {
    return { error: "请选择已经绑定 Prompt Release 的投放渠道", status: 422, code: "invalid_destination_release" };
  }
  const evidenceItemIds = form.getAll("evidence_item_ids").map(String).map((item) => item.trim()).filter(Boolean);
  if (!evidenceItemIds.length) {
    return { error: "至少选择一条可生成证据", status: 422, code: "missing_simulation_evidence" };
  }
  const simulationPurpose = (value(form, "simulation_purpose") || "content_preview") as
    PromptSimulationPurpose;
  const questionBinding = simulationPurpose === "geo_question_test"
    ? jsonObject(form, "question_binding")
    : {};
  if (isActionError(questionBinding)) return questionBinding;
  const questionSetId = typeof questionBinding.question_set_id === "string"
    ? questionBinding.question_set_id : undefined;
  const confirmedQuestionSetHash = typeof questionBinding.confirmed_question_set_hash === "string"
    ? questionBinding.confirmed_question_set_hash : undefined;
  const questionSetItemId = typeof questionBinding.question_set_item_id === "string"
    ? questionBinding.question_set_item_id : undefined;
  if (simulationPurpose === "geo_question_test"
    && (!questionSetId || !confirmedQuestionSetHash || !questionSetItemId)) {
    return {
      error: "内部 GEO 仿真必须选择冻结 QuestionSet 中的问题。",
      status: 422,
      code: "question_binding_required"
    };
  }
  const api = await client();
  const result = await api.createPromptSimulation(projectId, campaignId, {
    campaign_id: campaignId,
    opportunity_id: value(form, "opportunity_id"),
    destination_id: destinationId,
    prompt_release_binding_id: bindingId,
    confirmed_release_hash: confirmedReleaseHash,
    primary_brand_entity_id: value(form, "primary_brand_entity_id"),
    product_entity_id: value(form, "product_entity_id"),
    authenticity_mode: value(form, "authenticity_mode") as PromptSimulationAuthenticityMode,
    evidence_item_ids: evidenceItemIds,
    goals,
    constraints,
    variables,
    model_policy_hash: value(form, "model_policy_hash"),
    configured_model: value(form, "configured_model") || "deepseek-v4-flash",
    model_call_budget: numberValue(form, "model_call_budget", 2),
    simulation_purpose: simulationPurpose,
    ...(simulationPurpose === "geo_question_test" ? {
      question_set_id: questionSetId,
      confirmed_question_set_hash: confirmedQuestionSetHash,
      question_set_item_id: questionSetItemId
    } : {})
  }, guards(form));
  const outcome = finish(projectId, result, simulationPurpose === "geo_question_test"
    ? "内部 GEO 问题仿真任务已排队"
    : "TEST ONLY 文案预览任务已排队");
  return result.ok ? {
    ...outcome,
    nextHref: `/projects/${projectId}?tab=geo&geo_section=placement&placement_stage=simulation&campaign_id=${campaignId}&opportunity_id=${value(form, "opportunity_id")}&simulation_id=${result.data.simulation.id}&job_id=${result.data.job_id}`
  } : outcome;
}

export async function controlJob(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), jobId = value(form, "job_id"), command = value(form, "command"), api = await client();
  const result = command === "cancel" ? api.cancelJob(projectId, campaignId, jobId, guards(form))
    : command === "replay" ? api.replayJob(projectId, campaignId, jobId, guards(form)) : api.retryJob(projectId, campaignId, jobId, guards(form));
  return finish(projectId, await result, `任务已执行 ${command}`);
}

export async function submitPackageReview(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), api = await client();
  return finish(projectId, await api.submitReview(projectId, campaignId, value(form, "version_id"), guards(form)), "版本已提交双人复核");
}

export async function reviewPackage(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), api = await client();
  return finish(projectId, await api.reviewPackage(projectId, campaignId, value(form, "version_id"), {
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
  return finish(projectId, await api.editPackage(projectId, value(form, "campaign_id"), value(form, "package_id"), {
    base_version_id: value(form, "base_version_id"), base_content_hash: value(form, "base_content_hash"),
    content_json: contentJson, rendered_text: value(form, "rendered_text"), reason: value(form, "reason"),
    claims: editedClaims
  }, { ...guards(form), ifMatch: value(form, "base_content_hash") }), "编辑已创建新版本，旧审批未被复用");
}

export async function createExport(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), api = await client();
  return finish(projectId, await api.createExport(projectId, campaignId, value(form, "version_id"), guards(form)), "不可变导出工件已创建；未产生发布任务");
}

export async function createPublication(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), api = await client();
  return finish(projectId, await api.createPublication(projectId, campaignId, value(form, "version_id"), {
    destination_id: value(form, "destination_id"), policy_basis: value(form, "policy_basis") || null,
    publication_attempt: numberValue(form, "publication_attempt", 1), restricted_policy_acknowledged: checked(form, "restricted_policy_acknowledged")
  }, guards(form)), "显式待发布任务已创建");
}

export async function transitionPublication(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), api = await client();
  return finish(projectId, await api.transitionPublication(projectId, campaignId, value(form, "publication_id"), value(form, "command"),
    { reason: value(form, "reason") }, guards(form)), "发布任务状态已更新");
}

export async function createSubmission(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), api = await client();
  return finish(projectId, await api.createSubmission(projectId, campaignId, value(form, "publication_id"), {
    provider_submission_id: value(form, "provider_submission_id") || null, submitted_url: value(form, "submitted_url") || null
  }, guards(form)), "人工投放提交记录已创建");
}

export async function setSubmissionUrl(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), api = await client();
  return finish(projectId, await api.setSubmissionUrl(projectId, campaignId, value(form, "submission_id"), { submitted_url: value(form, "submitted_url") }, guards(form)), "公开 URL 已回填");
}

export async function blockSubmission(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), api = await client();
  return finish(projectId, await api.blockSubmission(projectId, campaignId, value(form, "submission_id"), { reason: value(form, "reason") }, guards(form)), "提交记录已阻断");
}

export async function verifySubmission(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), api = await client();
  const submissionId = value(form, "submission_id"), result = await api.verifySubmission(projectId, campaignId, submissionId, guards(form));
  const outcome = finish(projectId, result, "公开 URL 验证任务已排队");
  return result.ok ? { ...outcome, nextHref: `/projects/${projectId}?tab=geo&geo_section=placement&campaign_id=${campaignId}&submission_id=${submissionId}&job_id=${result.data.job_id}` } : outcome;
}

export async function createMeasurement(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), metrics = value(form, "metrics") ? jsonObject(form, "metrics") : {
    product_mentioned: checked(form, "product_mentioned"),
    recommendation_present: checked(form, "recommendation_present")
  };
  if (isActionError(metrics)) return metrics;
  const api = await client();
  return finish(projectId, await api.createMeasurement(projectId, value(form, "campaign_id"), value(form, "submission_id"), {
    monitoring_query_id: value(form, "monitoring_query_id"), measured_at: value(form, "measured_at"),
    citation_present: checked(form, "citation_present"), result_snapshot_uri: value(form, "result_snapshot_uri"),
    recommendation_position: value(form, "recommendation_position") ? numberValue(form, "recommendation_position") : null,
    metrics: metrics as JsonObject
  }, guards(form)), "投放效果测量已记录");
}

export async function completeMeasurementCollectionTask(
  _state: ActionResult, form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), api = await client();
  return finish(projectId, await api.completeMeasurementCollectionTask(
    projectId, campaignId, value(form, "task_id"), guards(form)
  ), "测量采集待办已完成");
}

export async function cancelMeasurementCollectionTask(
  _state: ActionResult, form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), api = await client();
  return finish(projectId, await api.cancelMeasurementCollectionTask(
    projectId, campaignId, value(form, "task_id"), { reason: value(form, "reason") }, guards(form)
  ), "测量采集待办已取消");
}
