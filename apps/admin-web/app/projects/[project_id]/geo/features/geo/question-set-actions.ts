"use server";

import type {
  KnowledgeQuestionBrandScope,
  KnowledgeQuestionFunnel,
  KnowledgeQuestionPlatform,
  QueryKind
} from "@geo/types/geo";
import {
  client,
  finish,
  guards,
  lines,
  numberValue,
  type ActionResult,
  value
} from "./action-utils";

function selected(form: FormData, key: string): string[] {
  return form.getAll(key).map(String).map((item) => item.trim()).filter(Boolean);
}

export async function createQuestionGeneration(
  _state: ActionResult,
  form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id");
  const campaignId = value(form, "campaign_id");
  const factCandidateIds = selected(form, "fact_candidate_ids");
  if (!factCandidateIds.length) {
    return {
      error: "至少选择一条已批准且当前有效的知识事实。",
      status: 422,
      code: "question_fact_required"
    };
  }
  const api = await client();
  return finish(projectId, await api.createKnowledgeQuestionGeneration(
    projectId,
    campaignId,
    {
      configured_model: "deepseek-v4-flash",
      model_call_budget: numberValue(form, "model_call_budget", 60),
      semantic_duplicate_threshold: numberValue(form, "semantic_duplicate_threshold", 0.92),
      fact_candidate_ids: factCandidateIds,
      graph_entity_ids: lines(form, "graph_entity_ids"),
      dimensions: [{
        turn_index: 1,
        parent_dimension_key: null,
        persona: value(form, "persona"),
        scenario: value(form, "scenario"),
        intent: value(form, "intent"),
        funnel: value(form, "funnel") as KnowledgeQuestionFunnel,
        region: value(form, "region"),
        language: value(form, "language"),
        brand_scope: value(form, "brand_scope") as KnowledgeQuestionBrandScope,
        platform: value(form, "platform") as KnowledgeQuestionPlatform,
        query_kind: value(form, "query_kind") as QueryKind,
        subject: value(form, "subject"),
        competitor_entity_id: value(form, "competitor_entity_id") || null
      }]
    },
    guards(form)
  ), "测试问题生成任务已排队");
}

export async function createQuestionCoveragePack(
  _state: ActionResult,
  form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id");
  const api = await client();
  return finish(projectId, await api.createKnowledgeQuestionGeneration(
    projectId,
    value(form, "campaign_id"),
    {
      generation_mode: "coverage_pack",
      configured_model: "deepseek-v4-flash",
      model_call_budget: numberValue(form, "model_call_budget", 60),
      semantic_duplicate_threshold: numberValue(
        form, "semantic_duplicate_threshold", 0.92
      ),
      coverage_profile: "au-cross-engine-balanced-v1",
      target_count: 100,
      custom_requirements: value(form, "custom_requirements")
    },
    guards(form)
  ), "100 题生成任务已排队；完成的批次会自动保留");
}

export async function resumeQuestionCoveragePack(
  _state: ActionResult,
  form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id");
  const api = await client();
  return finish(projectId, await api.resumeKnowledgeQuestionCoveragePack(
    projectId,
    value(form, "campaign_id"),
    value(form, "job_id"),
    guards(form)
  ), "任务已从保存的批次继续");
}

export async function editQuestionCandidate(
  _state: ActionResult,
  form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id");
  const api = await client();
  return finish(projectId, await api.editKnowledgeQuestionCandidate(
    projectId,
    value(form, "campaign_id"),
    value(form, "candidate_id"),
    { query_text: value(form, "query_text") },
    guards(form)
  ), "问题文字已更新");
}

export async function finalizeQuestionCoveragePack(
  _state: ActionResult,
  form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id");
  const includedCandidateIds = selected(form, "included_candidate_ids");
  if (includedCandidateIds.length < 90 || includedCandidateIds.length > 100) {
    return {
      error: "请保留 90 至 100 条问题后再冻结。",
      status: 422,
      code: "question_coverage_selection_invalid"
    };
  }
  const api = await client();
  return finish(projectId, await api.finalizeKnowledgeQuestionCoveragePack(
    projectId,
    value(form, "campaign_id"),
    {
      name: value(form, "name"),
      generation_job_id: value(form, "generation_job_id"),
      included_candidate_ids: includedCandidateIds
    },
    guards(form)
  ), `已冻结 ${includedCandidateIds.length} 条测试问题`);
}

export async function reviewQuestionCandidate(
  _state: ActionResult,
  form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id");
  const decision = value(form, "decision") as "approved" | "rejected";
  const api = await client();
  return finish(projectId, await api.reviewKnowledgeQuestionCandidate(
    projectId,
    value(form, "campaign_id"),
    value(form, "candidate_id"),
    { decision },
    guards(form)
  ), decision === "approved" ? "候选问题已批准" : "候选问题已拒绝");
}

export async function createQuestionSet(
  _state: ActionResult,
  form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id");
  const candidateIds = selected(form, "candidate_ids");
  if (!candidateIds.length) {
    return { error: "至少选择一个已批准候选。", status: 422, code: "question_candidates_required" };
  }
  const api = await client();
  return finish(projectId, await api.createKnowledgeQuestionSet(
    projectId,
    value(form, "campaign_id"),
    {
      name: value(form, "name"),
      generation_job_id: value(form, "generation_job_id"),
      candidate_ids: candidateIds,
      series_id: value(form, "series_id") || null,
      previous_version_id: value(form, "previous_version_id") || null
    },
    guards(form)
  ), "问题清单草稿已创建");
}

export async function transitionQuestionSet(
  _state: ActionResult,
  form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id");
  const campaignId = value(form, "campaign_id");
  const questionSetId = value(form, "question_set_id");
  const command = value(form, "command") as "approve" | "freeze";
  const api = await client();
  const result = command === "approve"
    ? api.approveKnowledgeQuestionSet(projectId, campaignId, questionSetId, guards(form))
    : api.freezeKnowledgeQuestionSet(projectId, campaignId, questionSetId, guards(form));
  return finish(
    projectId,
    await result,
    command === "approve" ? "问题清单已批准" : "问题清单已冻结且不可修改"
  );
}

export async function bindQuestionSetToProtocol(
  _state: ActionResult,
  form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id");
  const api = await client();
  return finish(projectId, await api.bindProtocolQuestionSet(
    projectId,
    value(form, "protocol_id"),
    {
      campaign_id: value(form, "campaign_id"),
      question_set_id: value(form, "question_set_id"),
      confirmed_content_hash: value(form, "confirmed_content_hash")
    },
    guards(form)
  ), "问题清单已完整绑定到监测方案");
}
