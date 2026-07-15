"use server";

import type { MeasurementWindow, ObservationCitationCreate, PublicationChannel, QueryKind } from "@geo/types/geo";
import { checked, client, finish, guards, isActionError, jsonObject, lines, numberValue, type ActionResult, value } from "./action-utils";

export async function createCampaign(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id");
  const api = await client();
  return finish(projectId, await api.createCampaign(projectId, {
    name: value(form, "name"), market_profile_id: value(form, "market_profile_id"),
    primary_product_entity_id: value(form, "primary_product_entity_id"),
    destination_ids: form.getAll("destination_ids").map(String).filter(Boolean),
    objective: value(form, "objective") || "recommendation_influence",
    opportunity_rationale: value(form, "opportunity_rationale")
  }, guards(form)), "Campaign 已创建，并为所选渠道建立投放任务");
}

export async function createMonitoringQuery(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id");
  const api = await client();
  return finish(projectId, await api.createMonitoringQuery(projectId, campaignId, {
    market_profile_id: value(form, "market_profile_id"), query_text: value(form, "query_text"),
    query_kind: value(form, "query_kind") as QueryKind, locale: value(form, "locale")
  }, guards(form)), "消费者查询已加入 Campaign");
}

export async function createProtocol(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.createProtocol(projectId, {
    campaign_id: value(form, "campaign_id"), market_profile_id: value(form, "market_profile_id"),
    name: value(form, "name"), platform: value(form, "platform") as "chatgpt_search",
    locale: value(form, "locale"), device: value(form, "device") as "desktop" | "mobile" | "tablet",
    sample_size: numberValue(form, "sample_size", 3), window_days: numberValue(form, "window_days", 28)
  }, guards(form)), "监测协议已创建");
}

export async function changeProtocol(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), protocolId = value(form, "protocol_id"), command = value(form, "command");
  const api = await client();
  const result = command === "freeze" ? api.freezeProtocol(projectId, protocolId, guards(form)) : api.approveProtocol(projectId, protocolId, guards(form));
  return finish(projectId, await result, command === "freeze" ? "监测协议已冻结" : "监测协议已批准");
}

export async function createSuggestion(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), protocolId = value(form, "protocol_id"), api = await client();
  return finish(projectId, await api.createSuggestion(projectId, protocolId, {
    query_text: value(form, "query_text"), query_kind: value(form, "query_kind") as QueryKind,
    rationale: value(form, "rationale")
  }, guards(form)), "查询建议已保存");
}

export async function approveSuggestion(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.approveSuggestion(projectId, value(form, "protocol_id"), value(form, "suggestion_id"), guards(form)), "查询建议已批准并写入监测查询");
}

export async function importObservation(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), protocolId = value(form, "protocol_id"), api = await client();
  let verifiedCitations: ObservationCitationCreate[];
  try {
    verifiedCitations = form.getAll("verified_citation_targets").map((raw) => {
      const parsed = JSON.parse(String(raw)) as { url?: unknown; submission_id?: unknown };
      if (typeof parsed.url !== "string" || typeof parsed.submission_id !== "string") throw new Error("invalid citation target");
      return { url: parsed.url, submission_id: parsed.submission_id };
    });
  } catch {
    return { error: "已验证引用选项无效，请刷新页面后重试", status: 422, code: "invalid_citation_target" };
  }
  const verifiedUrls = new Set(verifiedCitations.map((item) => item.url));
  const citations: ObservationCitationCreate[] = [
    ...verifiedCitations,
    ...lines(form, "citation_urls").filter((url) => !verifiedUrls.has(url)).map((url) => ({ url })),
  ];
  return finish(projectId, await api.importObservation(projectId, protocolId, {
    monitoring_query_id: value(form, "monitoring_query_id"), measurement_window: value(form, "measurement_window") as MeasurementWindow,
    sample_index: numberValue(form, "sample_index", 1), result_status: value(form, "result_status") as "succeeded" | "failed",
    eligible: checked(form, "eligible"), url_verification_status: value(form, "url_verification_status") as "passed" | "failed" | "unknown",
    configured_model: value(form, "configured_model"), provider_reported_model: value(form, "provider_reported_model") || null,
    ui_surface: value(form, "ui_surface"), observed_at: value(form, "observed_at"), raw_answer: value(form, "raw_answer") || null,
    citations,
    recommendation_present: checked(form, "recommendation_present"), primary_product_mentioned: checked(form, "primary_product_mentioned"),
    competitor_mentioned: checked(form, "competitor_mentioned"), artifact_uri: value(form, "artifact_uri") || null,
    confounding_factors: lines(form, "confounding_factors"), ineligible_reasons: lines(form, "ineligible_reasons"),
    raw_result: { import_method: "admin_manual" }, ui_metadata: { operator_surface: "admin_web" }
  }, guards(form)), "原始观察样本与引用已保存");
}

export async function computeMetrics(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.computeMetrics(projectId, value(form, "protocol_id"), value(form, "measurement_window") as MeasurementWindow, guards(form)), "指标快照已计算");
}

export async function createReport(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.createReport(projectId, { metric_snapshot_id: value(form, "metric_snapshot_id"), title: value(form, "title") }, guards(form)), "监测报告已生成");
}

export async function approveReport(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.approveReport(projectId, value(form, "report_id"), guards(form)), "监测报告已批准");
}

export async function createDestination(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.createDestination(projectId, {
    publication_channel: value(form, "publication_channel") as PublicationChannel,
    destination_key: value(form, "destination_key"), canonical_url: value(form, "canonical_url"),
    destination_account_id: value(form, "destination_account_id") || null, operation_mode: value(form, "operation_mode") as "manual" | "assisted" | "api"
  }, guards(form)), "渠道目的地已创建");
}

export async function reviewDestination(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), destinationId = value(form, "destination_id"), api = await client();
  const rules = jsonObject(form, "rules"), identity = jsonObject(form, "identity_requirements"), disclosure = jsonObject(form, "disclosure_requirements");
  if (isActionError(rules)) return rules; if (isActionError(identity)) return identity; if (isActionError(disclosure)) return disclosure;
  return finish(projectId, await api.createPolicyReview(projectId, destinationId, {
    status: value(form, "status") as "approved" | "restricted" | "prohibited", allowed_hosts: lines(form, "allowed_hosts"),
    rules, identity_requirements: identity, disclosure_requirements: disclosure
  }, guards(form)), "渠道政策复核已保存");
}

export async function transitionOpportunity(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.transitionOpportunity(projectId, value(form, "opportunity_id"), value(form, "command"),
    { reason: value(form, "reason") || null }, guards(form)), "投放机会状态已更新");
}
