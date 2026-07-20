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
      error: "至少选择一条已批准且仍为 active 的 Fact。",
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

export async function reviewQuestionCandidate(
  _state: ActionResult,
  form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id");
  const decision = value(form, "decision") as "approved" | "rejected";
  const notes = value(form, "notes");
  if (!notes) {
    return { error: "人工审核必须填写说明。", status: 422, code: "review_notes_required" };
  }
  const api = await client();
  return finish(projectId, await api.reviewKnowledgeQuestionCandidate(
    projectId,
    value(form, "campaign_id"),
    value(form, "candidate_id"),
    { decision, notes },
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
  ), "QuestionSet 草稿已创建");
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
    command === "approve" ? "QuestionSet 已批准" : "QuestionSet 已冻结且不可修改"
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
  ), "QuestionSet 已完整绑定到监测方案");
}
