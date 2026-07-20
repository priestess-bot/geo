"use server";

import type {
  JsonObject, MeasurementWindow, ObservationCaptureMethod, ObservationCitationCreate,
  ObservationClientKind, ObservationDevice, ObservationModelState, ObservationPlatform,
  ObservationRawEvidence, ObservationSearchMode, ObservationSurface, ObservationSurfaceKind,
  OfficialReportRowCreate, OperatorObservationCaptureMethod, PublicationChannel, QueryKind
} from "@geo/types/geo";
import { checked, client, finish, guards, isActionError, jsonArray, jsonObject, lines, numberValue, type ActionResult, value } from "./action-utils";

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
  const sampleSize = numberValue(form, "sample_size", 3);
  const frozenMinimum = Math.max(3, Math.ceil(sampleSize * 0.8));
  return finish(projectId, await api.createProtocol(projectId, {
    campaign_id: value(form, "campaign_id"), market_profile_id: value(form, "market_profile_id"),
    name: value(form, "name"), platform: value(form, "platform") as "chatgpt_search",
    locale: value(form, "locale"), device: value(form, "protocol_device") as "desktop" | "mobile" | "tablet",
    sample_size: sampleSize,
    minimum_valid_repeats: numberValue(form, "minimum_valid_repeats", frozenMinimum),
    window_days: numberValue(form, "window_days", 28),
    source_strata: [{
      capture_method: value(form, "capture_method") as OperatorObservationCaptureMethod,
      platform: value(form, "source_platform") as ObservationPlatform,
      platform_detail: value(form, "stratum_platform_detail") || null,
      surface: value(form, "source_surface") as ObservationSurface,
      surface_kind: value(form, "source_surface_kind") as ObservationSurfaceKind,
      surface_detail: value(form, "stratum_surface_detail") || null,
      engine: value(form, "stratum_engine"),
      configured_model: {
        state: value(form, "stratum_configured_model_state") as ObservationModelState,
        value: value(form, "stratum_configured_model") || null
      },
      reported_model: {
        state: value(form, "stratum_reported_model_state") as ObservationModelState,
        value: value(form, "stratum_reported_model") || null
      },
      locale: value(form, "locale"), region: value(form, "region"),
      language: value(form, "language"), device: value(form, "source_device") as ObservationDevice,
      client_kind: value(form, "client_kind") as ObservationClientKind,
      search_enabled: checked(form, "search_enabled"),
      search_mode: value(form, "search_mode") as ObservationSearchMode
    }]
  }, guards(form)), "监测协议已创建");
}

export async function changeProtocol(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), campaignId = value(form, "campaign_id"), protocolId = value(form, "protocol_id"), command = value(form, "command");
  const api = await client();
  const result = command === "freeze" ? api.freezeProtocol(projectId, campaignId, protocolId, guards(form)) : api.approveProtocol(projectId, campaignId, protocolId, guards(form));
  return finish(projectId, await result, command === "freeze" ? "监测协议已冻结" : "监测协议已批准");
}

export async function createSuggestion(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), protocolId = value(form, "protocol_id"), api = await client();
  return finish(projectId, await api.createSuggestion(projectId, protocolId, {
    campaign_id: value(form, "campaign_id"), query_cluster_key: value(form, "query_cluster_key"),
    query_text: value(form, "query_text"), query_kind: value(form, "query_kind") as QueryKind,
    rationale: value(form, "rationale")
  }, guards(form)), "查询建议已保存");
}

export async function approveSuggestion(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.approveSuggestion(projectId, value(form, "campaign_id"), value(form, "protocol_id"), value(form, "suggestion_id"), guards(form)), "查询建议已批准并写入监测查询");
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
  const captureMethod = value(form, "capture_method") as OperatorObservationCaptureMethod;
  const rawEvidence = observationRawEvidence(form, captureMethod);
  if ("error" in rawEvidence) return rawEvidence;
  return finish(projectId, await api.importObservation(projectId, protocolId, {
    campaign_id: value(form, "campaign_id"),
    monitoring_query_id: value(form, "monitoring_query_id"), measurement_window: value(form, "measurement_window") as MeasurementWindow,
    sample_index: numberValue(form, "sample_index", 1), result_status: value(form, "result_status") as "succeeded" | "failed",
    capture_method: captureMethod, requested_eligible: checked(form, "requested_eligible"),
    operator_ineligible_reasons: lines(form, "operator_ineligible_reasons"),
    url_verification_status: value(form, "url_verification_status") as "passed" | "failed" | "unknown",
    observed_at: value(form, "observed_at"), citations,
    recommendation_present: checked(form, "recommendation_present"), primary_product_mentioned: checked(form, "primary_product_mentioned"),
    competitor_mentioned: checked(form, "competitor_mentioned"),
    source: {
      platform: value(form, "source_platform") as ObservationPlatform,
      surface: value(form, "source_surface") as ObservationSurface,
      surface_kind: value(form, "source_surface_kind") as ObservationSurfaceKind,
      platform_detail: value(form, "platform_detail") || null,
      surface_detail: value(form, "surface_detail") || null,
      configured_model: {
        state: value(form, "configured_model_state") as ObservationModelState,
        value: value(form, "configured_model") || null
      },
      reported_model: {
        state: value(form, "reported_model_state") as ObservationModelState,
        value: value(form, "provider_reported_model") || null
      },
      run: {
        engine: value(form, "engine"), locale: value(form, "locale"),
        region: value(form, "region"), language: value(form, "language"),
        device: value(form, "device") as ObservationDevice,
        client_kind: value(form, "client_kind") as ObservationClientKind,
        search_enabled: checked(form, "search_enabled"),
        search_mode: value(form, "search_mode") as ObservationSearchMode,
        prompt_text: value(form, "prompt_text"),
        follow_up_prompts: lines(form, "follow_up_prompts"),
        adapter_name: value(form, "adapter_name") || null,
        adapter_version: value(form, "adapter_version") || null,
        provider_request_id: value(form, "provider_request_id") || null
      },
      raw_evidence: rawEvidence
    }
  }, guards(form)), "原始观察样本与引用已保存");
}

export async function importOfficialReport(
  _state: ActionResult,
  form: FormData
): Promise<ActionResult> {
  const projectId = value(form, "project_id");
  const parsedRows = jsonArray(form, "report_rows");
  if (isActionError(parsedRows)) return parsedRows;
  const rows: OfficialReportRowCreate[] = [];
  for (const [index, item] of parsedRows.entries()) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return { error: "官方报告 rows 必须是 JSON 对象数组", status: 422, code: "invalid_official_report_rows" };
    }
    rows.push({ row_index: index, row_data: item as JsonObject });
  }
  if (!rows.length) {
    return { error: "官方报告至少需要一行", status: 422, code: "empty_official_report_rows" };
  }
  const api = await client();
  return finish(projectId, await api.importOfficialReport(projectId, {
    campaign_id: value(form, "campaign_id"),
    platform: value(form, "official_platform") as ObservationPlatform,
    surface: value(form, "official_surface") as "google_generative_ai_performance_report" | "bing_ai_performance_report",
    platform_detail: null,
    surface_detail: null,
    artifact: {
      kind: "artifact",
      artifact_uri: value(form, "artifact_uri"),
      artifact_hash: value(form, "artifact_hash")
    },
    parser_name: value(form, "parser_name"),
    parser_version: value(form, "parser_version"),
    report_period_start: value(form, "report_period_start"),
    report_period_end: value(form, "report_period_end"),
    account_ref: value(form, "account_ref"),
    rows
  }, guards(form)), "官方报告已按独立来源分母导入");
}

export async function computeMetrics(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.computeMetrics(projectId, value(form, "protocol_id"), {
    campaign_id: value(form, "campaign_id"),
    measurement_window: value(form, "measurement_window") as MeasurementWindow,
    source_stratum_hash: value(form, "source_stratum_hash"),
    query_cluster_key: value(form, "query_cluster_key")
  }, guards(form)), "指标快照已计算");
}

export async function createReport(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.createReport(projectId, { campaign_id: value(form, "campaign_id"), metric_snapshot_id: value(form, "metric_snapshot_id"), title: value(form, "title") }, guards(form)), "监测报告已生成");
}

export async function approveReport(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.approveReport(projectId, value(form, "campaign_id"), value(form, "report_id"), guards(form)), "监测报告已批准");
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
  const structured = !value(form, "rules");
  const rules = structured ? {
    manual_submission: checked(form, "manual_submission"),
    automated_posting: checked(form, "automated_posting"),
    original_context_required: checked(form, "original_context_required")
  } : jsonObject(form, "rules");
  const identity = structured ? {
    brand_identity: value(form, "brand_identity") || "disclosed",
    authorised_account_required: checked(form, "authorised_account_required")
  } : jsonObject(form, "identity_requirements");
  const disclosure = structured ? {
    commercial_relationship: value(form, "commercial_relationship") || "disclose_when_required",
    source_attribution_required: checked(form, "source_attribution_required")
  } : jsonObject(form, "disclosure_requirements");
  if (isActionError(rules)) return rules; if (isActionError(identity)) return identity; if (isActionError(disclosure)) return disclosure;
  return finish(projectId, await api.createPolicyReview(projectId, value(form, "campaign_id"), destinationId, {
    status: value(form, "status") as "approved" | "restricted" | "prohibited", allowed_hosts: lines(form, "allowed_hosts"),
    rules, identity_requirements: identity, disclosure_requirements: disclosure
  }, guards(form)), "渠道政策复核已保存");
}

export async function transitionOpportunity(_state: ActionResult, form: FormData): Promise<ActionResult> {
  const projectId = value(form, "project_id"), api = await client();
  return finish(projectId, await api.transitionOpportunity(projectId, value(form, "campaign_id"), value(form, "opportunity_id"), value(form, "command"),
    { reason: value(form, "reason") || null }, guards(form)), "投放机会状态已更新");
}

function observationRawEvidence(
  form: FormData,
  captureMethod: ObservationCaptureMethod
): ObservationRawEvidence | (ActionResult & { error: string }) {
  const artifactUri = value(form, "artifact_uri");
  const artifactHash = value(form, "artifact_hash");
  if (artifactUri || artifactHash) {
    if (!artifactUri || !artifactHash) {
      return { error: "工件 URL 与 SHA-256 必须同时填写", status: 422, code: "incomplete_raw_artifact" };
    }
    return { kind: "artifact", artifact_uri: artifactUri, artifact_hash: artifactHash };
  }
  const raw = value(form, "raw_answer");
  if (!raw) return { error: "必须保存原始回答、内联响应或不可变工件", status: 422, code: "raw_evidence_required" };
  if (captureMethod === "manual_ui") return { kind: "answer", answer: raw };
  const inline = jsonObject(form, "raw_answer");
  return isActionError(inline)
    ? { ...inline, error: inline.error || "内联响应不是有效 JSON 对象" }
    : { kind: "inline_response", inline_response: inline };
}
