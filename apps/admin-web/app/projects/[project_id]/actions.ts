"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import { adminActorId, apiBase, actorHeaders, customerInvitationUrl, runtimeRequest } from "../../runtime";

export type ProjectActionState = {
  ok: boolean;
  message?: string;
  error?: string;
  details?: Array<[string, string]>;
  inviteUrl?: string;
  rawInviteToken?: string;
};

type InvitationResponse = {
  invitation?: { id?: string; invite_token?: string; email?: string };
};

type InvitationPageResponse = {
  records?: Array<{ invitation?: { id?: string; email?: string; role?: string; status?: string } }>;
};

type RuntimeProjectResponse = {
  project?: { id?: string; name?: string; target_brand?: string; status?: string };
};

type EntityResponse = {
  entity?: { id?: string; canonical_name?: string; status?: string };
};

type PromptResponse = {
  prompt?: { id?: string; text?: string; status?: string };
};

type KnowledgePipelineResponse = {
  knowledge_pipeline_run?: { id?: string; status?: string };
  knowledge_import_job?: { id?: string; status?: string };
};

type KnowledgeQualityRiskResponse = {
  quality_gate_run?: { id?: string; gate_key?: string; status?: string; accepted_expires_at?: string };
};

type KnowledgeApplicationResponse = {
  knowledge_pipeline_run?: { id?: string; status?: string };
  fact_extraction_job?: { id?: string; status?: string; max_facts?: number };
  prompt_generation_job?: { id?: string; status?: string; requested_count?: number };
  content_generation_job?: { id?: string; status?: string; content_type?: string };
};

type KnowledgePromptTemplateResponse = {
  prompt_generation_template?: { id?: string; template_key?: string; template_version?: string; name?: string };
};

type KnowledgeFactReviewResponse = {
  knowledge_fact?: { id?: string; status?: string };
  fact_candidate?: { id?: string; status?: string };
  approved_fact?: { id?: string; status?: string };
};

type PromptCandidateReviewResponse = {
  prompt_candidate?: { id?: string; review_status?: string };
};

type PromptCandidateImportResponse = {
  prompt_import?: { prompt_count?: number; prompt_version?: string };
};

type ConnectorSecretResponse = {
  connector_secret?: { id?: string; provider?: string; secret_ref?: string; status?: string; raw_secret?: string };
};

type ConnectorTestResponse = {
  connector_test?: { provider?: string; status?: string; message?: string; secret_ref?: string | null };
};

type ConnectorSecretRevealResponse = {
  secret_ref?: string;
  raw_secret?: string;
};

type ScoreWeightProfileResponse = {
  score_weight_profile?: { profile_key?: string; name?: string };
};

type ManualBackfillResponse = {
  answer_run_id?: string;
  raw_payload_hash?: string;
  citation_count?: number;
  evidence_asset_count?: number;
};

type HumanReviewResponse = {
  human_review?: { id?: string; target_type?: string; review_status?: string };
};

type ReportManagementResponse = {
  report_export?: { id?: string; management_status?: string; status?: string };
  management_event?: { id?: string; status?: string };
};

type ReportExportJobResponse = {
  report_export_job?: { id?: string; status?: string; artifact_type?: string };
};

type BrandAssetResponse = {
  brand_asset?: { id?: string; asset_url?: string; status?: string };
  asset?: { id?: string; asset_url?: string; status?: string };
};

type SavedViewResponse = {
  saved_view?: { id?: string; name?: string; view_type?: string };
};

type FidelityCheckResponse = {
  fidelity_check?: { id?: string; status?: string };
};

type ActionRecommendationResponse = {
  action_recommendation?: { id?: string; status?: string; customer_visible?: boolean };
};

type ContentDraftReviewResponse = {
  content_draft?: { id?: string; review_status?: string; title?: string };
  human_review?: { id?: string; review_status?: string };
};

type ManualDistributionBackfillResponse = {
  manual_distribution_record?: { id?: string; status?: string; target_url?: string };
};

type FixtureCollectionResponse = {
  record_count?: number;
  success_count?: number;
  failure_count?: number;
  persistence?: {
    analysis?: {
      enabled?: boolean;
      score_snapshot_id?: string;
      report_export_id?: string;
      final_score?: number;
      action_recommendations?: number;
      content_drafts?: number;
      traceability_bundle_id?: string;
    };
  };
};

function projectId(formData: FormData): string {
  return String(formData.get("project_id") || "").trim();
}

function value(formData: FormData, key: string): string {
  return String(formData.get(key) || "").trim();
}

function lines(raw: string): string[] {
  return raw
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function numberValue(formData: FormData, key: string, fallback: number): number {
  const parsed = Number(value(formData, key));
  return Number.isFinite(parsed) ? parsed : fallback;
}

function jsonObjectValue(formData: FormData, key: string): { data?: Record<string, unknown>; error?: string } {
  const raw = value(formData, key);
  if (!raw) {
    return { data: {} };
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      return { error: `${key} 必须是 JSON 对象。` };
    }
    return { data: parsed as Record<string, unknown> };
  } catch {
    return { error: `${key} 不是有效的 JSON。` };
  }
}

function jsonArrayValue(formData: FormData, key: string): { data?: Array<Record<string, unknown>>; error?: string } {
  const raw = value(formData, key);
  if (!raw) {
    return { data: [] };
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed) || parsed.some((item) => !item || Array.isArray(item) || typeof item !== "object")) {
      return { error: `${key} 必须是由 JSON 对象组成的数组。` };
    }
    return { data: parsed as Array<Record<string, unknown>> };
  } catch {
    return { error: `${key} 不是有效的 JSON。` };
  }
}

async function runtimeMultipartRequest<T>(path: string, body: FormData): Promise<{ ok: boolean; data?: T; error?: string; status?: number }> {
  try {
    const response = await fetch(new URL(path, apiBase()).toString(), {
      method: "POST",
      headers: await actorHeaders(),
      body,
      cache: "no-store"
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" && payload && "detail" in payload ? String(payload.detail) : String(payload);
      return { ok: false, error: detail || `Runtime request failed with ${response.status}`, status: response.status };
    }
    return { ok: true, data: payload as T, status: response.status };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "Runtime API unavailable" };
  }
}

const scoreComponentKeys = [
  "MentionScore",
  "RecommendationScore",
  "PositionScore",
  "CitationScore",
  "LocalRelevanceScore",
  "SentimentScore",
  "FreshnessScore",
  "CompetitorShareScore"
] as const;

function connectorModelAllowed(provider: string, mode: string, model: string): boolean {
  const key = `${provider}:${mode}`;
  const matrix: Record<string, string[]> = {
    "openai:official_api": ["gpt-4.1-mini", "gpt-4o-mini"],
    "openai:deepseek_fallback": ["deepseek-v4-flash"],
    "openai:disabled": ["disabled"],
    "perplexity:official_api": ["sonar", "sonar-pro"],
    "perplexity:deepseek_fallback": ["deepseek-v4-flash"],
    "perplexity:disabled": ["disabled"],
    "google_ai_mode:manual_backfill": ["google_ai_mode_manual_backfill", "google_ai_mode"],
    "google_ai_mode:browser_or_serp": ["google_ai_mode_browser", "serp_provider"],
    "google_ai_mode:disabled": ["disabled"]
  };
  return (matrix[key] || []).includes(model);
}

function connectorModelValue(formData: FormData, provider: string, prefix: string, fallback: string): string {
  const mode = value(formData, `${prefix}_mode`);
  const model = value(formData, `${prefix}_model`) || fallback;
  if (connectorModelAllowed(provider, mode, model)) {
    return model;
  }
  const defaults: Record<string, string> = {
    "openai:official_api": "gpt-4.1-mini",
    "openai:deepseek_fallback": "deepseek-v4-flash",
    "openai:disabled": "disabled",
    "perplexity:official_api": "sonar",
    "perplexity:deepseek_fallback": "deepseek-v4-flash",
    "perplexity:disabled": "disabled",
    "google_ai_mode:manual_backfill": "google_ai_mode_manual_backfill",
    "google_ai_mode:browser_or_serp": "serp_provider",
    "google_ai_mode:disabled": "disabled"
  };
  return defaults[`${provider}:${mode}`] || fallback;
}

function revalidateProject(projectId: string): void {
  if (projectId) {
    revalidatePath(`/projects/${projectId}`);
  }
}

async function maybeSaveConnectorSecret(
  formData: FormData,
  provider: string,
  prefix: string
): Promise<{ secretRef?: string; error?: string }> {
  const rawSecret = value(formData, `${prefix}_raw_secret`);
  if (!rawSecret) {
    return {};
  }
  const pid = projectId(formData);
  const response = await runtimeRequest<ConnectorSecretResponse>("/v1/connectors/runtime/secrets", {
    method: "POST",
    body: {
      project_id: pid,
      provider,
      raw_secret: rawSecret,
      purpose: "api_key",
      metadata: {
        created_from: "admin_web_launch_config",
        mode: value(formData, `${prefix}_mode`),
        model: value(formData, `${prefix}_model`)
      },
      updated_by: adminActorId(),
      reason: "admin_web_launch_config_secret_save"
    }
  });
  if (!response.ok) {
    return { error: response.error || `${connectorLabel(provider)}密钥保存失败。` };
  }
  return {
    secretRef: response.data?.connector_secret?.secret_ref
      || (response.data?.connector_secret?.id ? `connector-secret:${response.data.connector_secret.id}` : undefined)
  };
}

function connectorStatusAfterSecret(formData: FormData, prefix: string, secretRef: string | undefined, fallback: string): string {
  const current = value(formData, `${prefix}_status`) || fallback;
  if (secretRef && ["not_configured", "failed", ""].includes(current)) {
    return "ready";
  }
  return current;
}

function connectorLabel(provider: string): string {
  const labels: Record<string, string> = {
    openai: "OpenAI 连接器",
    perplexity: "Perplexity 连接器",
    google_ai_mode: "Google AI Mode"
  };
  return labels[provider] || "连接器";
}

export async function updateProjectAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const payload = {
    project_id: projectId(formData),
    tenant_name: value(formData, "tenant_name"),
    name: value(formData, "name"),
    target_brand: value(formData, "target_brand"),
    category: value(formData, "category"),
    updated_by: adminActorId(),
    reason: "admin_web_project_update"
  };
  const response = await runtimeRequest<RuntimeProjectResponse>("/v1/projects/runtime", {
    method: "PATCH",
    body: payload
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "项目基础配置保存失败。" };
  }
  revalidateProject(payload.project_id);
  return { ok: true, message: `项目已保存：${response.data?.project?.target_brand || payload.name}` };
}

export async function saveProjectAndBrandAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const projectPayload = {
    project_id: pid,
    tenant_name: value(formData, "tenant_name"),
    name: value(formData, "name"),
    target_brand: value(formData, "target_brand"),
    category: value(formData, "category"),
    updated_by: adminActorId(),
    reason: "admin_web_project_brand_update"
  };
  const projectResponse = await runtimeRequest<RuntimeProjectResponse>("/v1/projects/runtime", {
    method: "PATCH",
    body: projectPayload
  });
  if (!projectResponse.ok) {
    return { ok: false, error: projectResponse.error || "项目基础配置保存失败。" };
  }
  const brandResponse = await runtimeRequest<EntityResponse>("/v1/project-entities/runtime/brand", {
    method: "POST",
    body: {
      project_id: pid,
      canonical_name: value(formData, "canonical_name") || projectPayload.target_brand,
      official_domains: lines(value(formData, "official_domains")),
      parent_company: value(formData, "parent_company") || null,
      product_lines: lines(value(formData, "product_lines")),
      status: value(formData, "brand_status") || "active",
      updated_by: adminActorId(),
      reason: "admin_web_project_brand_update"
    }
  });
  if (!brandResponse.ok) {
    return { ok: false, error: brandResponse.error || "品牌配置保存失败；项目基础字段已保存。" };
  }
  revalidateProject(pid);
  return { ok: true, message: `项目与品牌已保存：${projectPayload.target_brand}` };
}

export async function projectLifecycleAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const action = value(formData, "action");
  const response = await runtimeRequest<RuntimeProjectResponse>("/v1/projects/runtime/action", {
    method: "POST",
    body: {
      project_id: projectId(formData),
      action,
      updated_by: adminActorId(),
      reason: `admin_web_project_${action}`
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "项目状态操作失败。" };
  }
  revalidateProject(projectId(formData));
  return { ok: true, message: action === "archive" ? "项目已归档。" : "项目已恢复为暂停中。" };
}

export async function projectStatusAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const action = value(formData, "action");
  if (action === "archive" || action === "restore") {
    return projectLifecycleAction(_previousState, formData);
  }
  if (action === "activate" && value(formData, "activation_blockers")) {
    return {
      ok: false,
      error: `启动条件未满足：${value(formData, "activation_blockers").split(/\r?\n/).filter(Boolean).join("、")}`
    };
  }
  const lifecycleAction = action === "activate" ? "start" : action;
  if (!["start", "pause"].includes(lifecycleAction)) {
    return { ok: false, error: "未知项目状态操作。" };
  }
  const response = await runtimeRequest<RuntimeProjectResponse>("/v1/projects/runtime/action", {
    method: "POST",
    body: {
      project_id: pid,
      action: lifecycleAction,
      updated_by: adminActorId(),
      reason: `admin_web_project_${action}`
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "项目状态操作失败。" };
  }
  revalidateProject(pid);
  return { ok: true, message: lifecycleAction === "start" ? "项目已切换为运行中。" : "项目已切换为暂停中。" };
}

export async function saveScoreWeightProfileAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const weights = Object.fromEntries(scoreComponentKeys.map((key) => [key, numberValue(formData, `weight_${key}`, 0)]));
  const profileKey = value(formData, "profile_key") || `custom_${Date.now()}`;
  const response = await runtimeRequest<ScoreWeightProfileResponse>("/v1/score-weight-profiles/runtime", {
    method: "POST",
    body: {
      profile_key: profileKey,
      name: value(formData, "profile_name") || profileKey,
      description: value(formData, "profile_description"),
      base_formula_version: value(formData, "base_formula_version") || "visibility_v1.0",
      weights,
      updated_by: adminActorId(),
      status: "active"
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "评分方案保存失败。" };
  }
  revalidateProject(pid);
  return { ok: true, message: `评分方案已保存：${response.data?.score_weight_profile?.name || value(formData, "profile_name")}，可在下拉框选择后保存启动配置。` };
}

export async function saveLaunchConfigAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const openaiSecret = await maybeSaveConnectorSecret(formData, "openai", "connector_openai");
  const perplexitySecret = await maybeSaveConnectorSecret(formData, "perplexity", "connector_perplexity");
  const googleSecret = await maybeSaveConnectorSecret(formData, "google_ai_mode", "connector_google_ai_mode");
  const secretError = openaiSecret.error || perplexitySecret.error || googleSecret.error;
  if (secretError) {
    return { ok: false, error: secretError };
  }
  const schedule = {
    cadence: value(formData, "schedule_cadence") || "weekly",
    weekday: value(formData, "schedule_weekday") || "monday",
    timezone: value(formData, "timezone") || "UTC"
  };
  const externalConnectors = {
    openai: {
      status: connectorStatusAfterSecret(formData, "connector_openai", openaiSecret.secretRef, "not_configured"),
      mode: value(formData, "connector_openai_mode") || "official_api",
      model: connectorModelValue(formData, "openai", "connector_openai", "gpt-4.1-mini"),
      env_var: value(formData, "connector_openai_env_var") || "OPENAI_API_KEY",
      secret_ref: openaiSecret.secretRef || value(formData, "connector_openai_secret_ref") || null,
      notes: value(formData, "connector_openai_notes")
    },
    perplexity: {
      status: connectorStatusAfterSecret(formData, "connector_perplexity", perplexitySecret.secretRef, "not_configured"),
      mode: value(formData, "connector_perplexity_mode") || "official_api",
      model: connectorModelValue(formData, "perplexity", "connector_perplexity", "sonar"),
      env_var: value(formData, "connector_perplexity_env_var") || "PERPLEXITY_API_KEY",
      secret_ref: perplexitySecret.secretRef || value(formData, "connector_perplexity_secret_ref") || null,
      notes: value(formData, "connector_perplexity_notes")
    },
    google_ai_mode: {
      status: connectorStatusAfterSecret(formData, "connector_google_ai_mode", googleSecret.secretRef, "manual_ready"),
      mode: value(formData, "connector_google_ai_mode_mode") || "manual_backfill",
      model: connectorModelValue(formData, "google_ai_mode", "connector_google_ai_mode", "google_ai_mode_manual_backfill"),
      env_var: value(formData, "connector_google_ai_mode_env_var") || "GOOGLE_MANUAL_BACKFILL",
      secret_ref: googleSecret.secretRef || value(formData, "connector_google_ai_mode_secret_ref") || null,
      notes: value(formData, "connector_google_ai_mode_notes")
    }
  };
  const payload = {
    project_id: pid,
    customer_email: value(formData, "customer_email"),
    primary_domain: value(formData, "primary_domain"),
    competitor_domains: lines(value(formData, "competitor_domains_snapshot")),
    locale: value(formData, "locale") || "en",
    country_code: value(formData, "country_code") || "GLOBAL",
    timezone: value(formData, "timezone") || "UTC",
    collection_mode: value(formData, "collection_mode") || "api",
    schedule,
    external_connectors: externalConnectors,
    scoring_profile: value(formData, "scoring_profile") || "visibility_v1.0",
    status: value(formData, "status") || "draft",
    metadata: { updated_from: "admin_web_project_detail" },
    created_by: adminActorId(),
    updated_by: adminActorId(),
    reason: "admin_web_launch_config_save"
  };
  const response = await runtimeRequest<Record<string, unknown>>("/v1/project-launch-configs/runtime", {
    method: "POST",
    body: payload
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "启动配置保存失败。" };
  }
  revalidateProject(payload.project_id);
  return { ok: true, message: "启动配置已保存。" };
}

export async function testConnectorAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const provider = value(formData, "provider");
  const prefix = provider === "perplexity"
    ? "connector_perplexity"
    : provider === "google_ai_mode"
      ? "connector_google_ai_mode"
      : "connector_openai";
  const response = await runtimeRequest<ConnectorTestResponse>("/v1/connectors/runtime/test", {
    method: "POST",
    body: {
      project_id: pid,
      provider,
      mode: value(formData, `${prefix}_mode`),
      model: value(formData, `${prefix}_model`),
      raw_secret: value(formData, `${prefix}_raw_secret`) || null,
      secret_ref: value(formData, `${prefix}_secret_ref`) || null,
      tested_by: adminActorId(),
      reason: "admin_web_connector_test"
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "连接器测试失败。" };
  }
  revalidateProject(pid);
  const result = response.data?.connector_test;
  if (result?.status) {
    formData.set(`${prefix}_status`, result.status);
  }
  if (result?.secret_ref) {
    formData.set(`${prefix}_secret_ref`, result.secret_ref);
  }
  formData.set(`${prefix}_raw_secret`, "");
  const saveState = await saveLaunchConfigAction({ ok: false }, formData);
  if (!saveState.ok) {
    return saveState;
  }
  return {
    ok: true,
    message: `${connectorLabel(provider)}测试完成：${result?.message || result?.status || "已更新"}`,
    details: [
      ["状态", result?.status || "unknown"],
      ["Secret ref", result?.secret_ref || "未写入"]
    ]
  };
}

export async function revealConnectorSecretAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const provider = value(formData, "provider");
  const prefix = provider === "perplexity"
    ? "connector_perplexity"
    : provider === "google_ai_mode"
      ? "connector_google_ai_mode"
      : "connector_openai";
  const secretRef = value(formData, "secret_ref") || value(formData, `${prefix}_secret_ref`);
  if (!secretRef) {
    return { ok: false, error: "没有可显示的已保存 API key。" };
  }
  const query = new URLSearchParams({ project_id: projectId(formData), secret_ref: secretRef });
  const response = await runtimeRequest<ConnectorSecretRevealResponse>(`/v1/connectors/runtime/secrets/reveal?${query.toString()}`);
  if (!response.ok) {
    return { ok: false, error: response.error || "API key 显示失败。" };
  }
  return {
    ok: true,
    message: "已显示保存的 API key，仅用于当前配置检查。",
    details: [["Secret ref", response.data?.secret_ref || secretRef], ["API key", response.data?.raw_secret || ""]]
  };
}

export async function savePromptAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const payload = {
    project_id: projectId(formData),
    prompt_id: value(formData, "prompt_id"),
    text: value(formData, "text"),
    intent_type: value(formData, "intent_type"),
    city: value(formData, "city"),
    language: value(formData, "language") || "en",
    target_brand: value(formData, "target_brand"),
    competitors: lines(value(formData, "competitors")),
    priority: numberValue(formData, "priority", 1),
    intent_weight: numberValue(formData, "intent_weight", 1),
    prompt_version: value(formData, "prompt_version") || "project_prompts_v1",
    status: value(formData, "status") || "active",
    updated_by: adminActorId(),
    reason: "admin_web_prompt_update"
  };
  const response = await runtimeRequest<PromptResponse>("/v1/prompts/runtime", {
    method: "PATCH",
    body: payload
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "Prompt 保存失败。" };
  }
  revalidateProject(payload.project_id);
  return { ok: true, message: `Prompt 已保存：${response.data?.prompt?.text || payload.text}` };
}

export async function saveBrandEntityAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const payload = {
    project_id: projectId(formData),
    canonical_name: value(formData, "canonical_name"),
    official_domains: lines(value(formData, "official_domains")),
    parent_company: value(formData, "parent_company") || null,
    product_lines: lines(value(formData, "product_lines")),
    status: value(formData, "status") || "active",
    updated_by: adminActorId(),
    reason: "admin_web_brand_entity_save"
  };
  const response = await runtimeRequest<EntityResponse>("/v1/project-entities/runtime/brand", {
    method: "POST",
    body: payload
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "品牌实体保存失败。" };
  }
  revalidateProject(payload.project_id);
  return { ok: true, message: `品牌已保存：${response.data?.entity?.canonical_name || payload.canonical_name}` };
}

export async function saveCompetitorEntityAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const payload = {
    project_id: projectId(formData),
    competitor_id: value(formData, "competitor_id") || null,
    canonical_name: value(formData, "canonical_name"),
    official_domains: lines(value(formData, "official_domains")),
    parent_company: value(formData, "parent_company") || null,
    product_lines: lines(value(formData, "product_lines")),
    status: value(formData, "status") || "active",
    updated_by: adminActorId(),
    reason: "admin_web_competitor_entity_save"
  };
  const response = await runtimeRequest<EntityResponse>("/v1/project-entities/runtime/competitors", {
    method: "POST",
    body: payload
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "竞品保存失败。" };
  }
  revalidateProject(payload.project_id);
  return { ok: true, message: `竞品已保存：${response.data?.entity?.canonical_name || payload.canonical_name}` };
}

export async function saveMemberAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const response = await runtimeRequest<Record<string, unknown>>("/v1/project-members/runtime", {
    method: "POST",
    body: {
      project_id: pid,
      user_id: value(formData, "user_id"),
      role: value(formData, "role") || "viewer",
      updated_by: adminActorId(),
      reason: "admin_web_project_member_save"
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "成员保存失败。" };
  }
  revalidateProject(pid);
  return { ok: true, message: "成员已保存。" };
}

export async function deleteMemberAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const userId = value(formData, "user_id");
  const pid = projectId(formData);
  const response = await runtimeRequest<Record<string, unknown>>("/v1/project-members/runtime", {
    method: "DELETE",
    body: {
      project_id: pid,
      user_id: userId,
      deleted_by: adminActorId(),
      reason: "admin_web_project_member_delete"
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "成员删除失败。" };
  }
  revalidateProject(pid);
  return { ok: true, message: `成员已删除：${userId}` };
}

export async function importPromptsAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const csvContent = value(formData, "csv_content");
  const response = await runtimeRequest<{ prompt_import?: { prompt_count?: number; prompt_ids?: string[] } }>("/v1/prompts/runtime/import.csv", {
    method: "POST",
    body: {
      project_id: pid,
      csv_content: csvContent,
      imported_by: adminActorId(),
      max_rows: Number(value(formData, "max_rows") || "100")
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "Prompt 导入失败。" };
  }
  revalidateProject(pid);
  redirect(`/projects/${pid}?tab=prompts&prompt_tab=config&prompt_limit=${value(formData, "prompt_limit") || "20"}&prompt_imported=${response.data?.prompt_import?.prompt_count ?? 0}`);
}

export async function createKnowledgePipelineAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const sourceMode = value(formData, "source_mode") || "pasted_text";
  const isUrlSource = ["url", "url_batch", "site_crawl", "sitemap"].includes(sourceMode);
  const sourceUrls = lines(value(formData, "source_urls") || value(formData, "source_url"));
  const uploadedFiles = (formData.getAll("source_files").length
    ? formData.getAll("source_files")
    : formData.getAll("source_file"))
    .filter((item): item is File => item instanceof File && item.size > 0);
  if (sourceMode === "file") {
    if (!uploadedFiles.length) {
      return { ok: false, error: "请至少选择一个要导入的知识库文件。" };
    }
    if (uploadedFiles.length > 20) {
      return { ok: false, error: "单次最多导入 20 个文件，请拆分后重试。" };
    }
    const oversized = uploadedFiles.find((file) => file.size > 50 * 1024 * 1024);
    if (oversized) {
      return { ok: false, error: `文件 ${oversized.name} 超过 50 MB 上限。` };
    }
  }
  if (isUrlSource && !sourceUrls.length) {
    return { ok: false, error: "请至少填写一个公网 URL。" };
  }
  if (["pasted_text", "csv"].includes(sourceMode) && !(value(formData, "source_text") || value(formData, "csv_content"))) {
    return { ok: false, error: sourceMode === "csv" ? "请填写 CSV 内容。" : "请填写要导入的文本。" };
  }
  const crawlMode = sourceMode === "sitemap" ? "sitemap" : sourceMode === "site_crawl" ? "site_depth" : sourceMode === "url_batch" ? "url_batch" : "single_url";
  const importSourceMode = sourceMode === "sitemap" ? "site_crawl" : sourceMode;
  const runResponse = await runtimeRequest<KnowledgePipelineResponse>("/v1/knowledge/pipeline-runs/runtime", {
    method: "POST",
    body: {
      project_id: pid,
      run_type: value(formData, "run_type") || "full_ingestion",
      entry_source: sourceMode === "file" ? "file" : isUrlSource ? (sourceMode === "site_crawl" || sourceMode === "sitemap" ? "site" : "url") : sourceMode === "csv" ? "csv" : "text",
      market_code: value(formData, "market_code") || "GLOBAL",
      locale: value(formData, "locale") || "en",
      city: value(formData, "city") || null,
      created_by: adminActorId(),
      metadata: { created_from: "admin_web_knowledge_pipeline" }
    }
  });
  if (!runResponse.ok) {
    return { ok: false, error: runResponse.error || "知识库流水线创建失败。" };
  }
  const pipelineRunId = runResponse.data?.knowledge_pipeline_run?.id || "";
  if (!pipelineRunId) {
    return { ok: false, error: "知识库流水线创建失败：缺少 pipeline_run_id。" };
  }
  const sourceConfig =
    isUrlSource
      ? {
          urls: sourceUrls,
          crawl_mode: crawlMode,
          max_pages: numberValue(formData, "max_pages", 1),
          depth_limit: numberValue(formData, "depth_limit", 0),
          include_patterns: lines(value(formData, "include_patterns")),
          exclude_patterns: lines(value(formData, "exclude_patterns")),
          respect_robots: value(formData, "respect_robots") !== "0",
          market_code: value(formData, "market_code") || "GLOBAL",
          locale: value(formData, "locale") || "en",
          city: value(formData, "city") || null
        }
      : sourceMode === "file"
        ? {
            title: value(formData, "title") || "知识库文件导入",
            adapter_engine: value(formData, "adapter_engine") || "auto",
            market_code: value(formData, "market_code") || "GLOBAL",
            locale: value(formData, "locale") || "en",
            city: value(formData, "city") || null
          }
      : {
          title: value(formData, "title") || "知识库导入",
          text: value(formData, "source_text") || value(formData, "csv_content"),
          market_code: value(formData, "market_code") || "GLOBAL",
          locale: value(formData, "locale") || "en",
          city: value(formData, "city") || null
        };
  const jobResponse = await runtimeRequest<KnowledgePipelineResponse>("/v1/knowledge/import-jobs/runtime", {
    method: "POST",
    body: {
      project_id: pid,
      pipeline_run_id: pipelineRunId,
      source_mode: importSourceMode,
      requested_by: adminActorId(),
      source_config: sourceConfig,
      priority: 0
    }
  });
  if (!jobResponse.ok) {
    return { ok: false, error: jobResponse.error || "知识库导入任务创建失败。" };
  }
  const importJobId = jobResponse.data?.knowledge_import_job?.id || "";
  if (sourceMode === "file" && importJobId) {
    const rejectedFiles: string[] = [];
    let acceptedFileCount = 0;
    for (const uploadedFile of uploadedFiles) {
      const uploadPayload = new FormData();
      uploadPayload.set("project_id", pid);
      uploadPayload.set("pipeline_run_id", pipelineRunId);
      uploadPayload.set("market_code", value(formData, "market_code") || "GLOBAL");
      uploadPayload.set("locale", value(formData, "locale") || "en");
      uploadPayload.set("city", value(formData, "city") || "");
      uploadPayload.set("adapter_engine", value(formData, "adapter_engine") || "auto");
      uploadPayload.set("defer_start", "1");
      uploadPayload.set("file", uploadedFile);
      const uploadResponse = await runtimeMultipartRequest<KnowledgePipelineResponse>(
        `/v1/knowledge/import-jobs/runtime/${encodeURIComponent(importJobId)}/files`,
        uploadPayload
      );
      if (!uploadResponse.ok) {
        rejectedFiles.push(`${uploadedFile.name}: ${uploadResponse.error || "预检查或上传失败"}`);
      } else {
        acceptedFileCount += 1;
      }
    }
    if (acceptedFileCount === 0) {
      return {
        ok: false,
        error: `所有文件均未通过来源预检：${rejectedFiles.join("；")}`,
        details: [["Pipeline", pipelineRunId], ["导入任务", importJobId]]
      };
    }
    const startResponse = await runtimeRequest<KnowledgePipelineResponse>(
      `/v1/knowledge/pipeline-runs/runtime/${encodeURIComponent(pipelineRunId)}/start?project_id=${encodeURIComponent(pid)}`,
      { method: "POST", body: {} }
    );
    if (!startResponse.ok) {
      return { ok: false, error: startResponse.error || "知识库 Pipeline 启动失败。" };
    }
    revalidateProject(pid);
    redirect(
      `/projects/${pid}?tab=knowledge&knowledge_tab=processing&pipeline_run_id=${encodeURIComponent(pipelineRunId)}`
      + `&source_uploaded=${acceptedFileCount}&source_rejected=${rejectedFiles.length}`
    );
  } else if (isUrlSource && importJobId) {
    const urlResponse = await runtimeRequest<KnowledgePipelineResponse>(
      `/v1/knowledge/import-jobs/runtime/${encodeURIComponent(importJobId)}/urls`,
      {
        method: "POST",
        body: {
          project_id: pid,
          urls: sourceUrls,
          crawl_mode: crawlMode,
          crawl_depth: numberValue(formData, "depth_limit", 0),
          max_pages: numberValue(formData, "max_pages", 1),
          include_patterns: lines(value(formData, "include_patterns")),
          exclude_patterns: lines(value(formData, "exclude_patterns")),
          respect_robots: value(formData, "respect_robots") !== "0"
        }
      }
    );
    if (!urlResponse.ok) {
      return { ok: false, error: urlResponse.error || "知识库 URL 预检查失败。" };
    }
  }
  if (sourceMode !== "file") {
    const startResponse = await runtimeRequest<KnowledgePipelineResponse>(`/v1/knowledge/pipeline-runs/runtime/${encodeURIComponent(pipelineRunId)}/start?project_id=${encodeURIComponent(pid)}`, {
      method: "POST",
      body: {}
    });
    if (!startResponse.ok) {
      return { ok: false, error: startResponse.error || "知识库 Pipeline 启动失败。" };
    }
  }
  revalidateProject(pid);
  redirect(`/projects/${pid}?tab=knowledge&knowledge_tab=processing&pipeline_run_id=${encodeURIComponent(pipelineRunId)}`);
}

export async function createKnowledgeMaintenanceRunAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const sourcePipelineRunId = value(formData, "source_pipeline_run_id");
  const runType = value(formData, "run_type") || "reparse";
  if (!sourcePipelineRunId) {
    return { ok: false, error: "请选择作为输入的历史 Pipeline。" };
  }
  if (!["reparse", "rechunk", "reindex", "fact_refresh", "full_rebuild"].includes(runType)) {
    return { ok: false, error: "不支持的知识库重跑类型。" };
  }
  const createResponse = await runtimeRequest<KnowledgePipelineResponse>("/v1/knowledge/pipeline-runs/runtime", {
    method: "POST",
    body: {
      project_id: pid,
      run_type: runType,
      entry_source: "mixed",
      market_code: value(formData, "market_code") || "GLOBAL",
      locale: value(formData, "locale") || "en",
      city: value(formData, "city") || null,
      created_by: adminActorId(),
      metadata: {
        source_pipeline_run_id: sourcePipelineRunId,
        adapter_engine: value(formData, "adapter_engine") || "auto",
        chunk_profile_version: value(formData, "chunk_profile_version") || "geo_chunk_profile_v1",
        cleaner_profile_version: value(formData, "cleaner_profile_version") || "geo_cleaner_v1",
        embedding_model: "BAAI/bge-m3",
        embedding_model_version: "bge-m3-local-v1",
        model: "deepseek-v4-flash"
      }
    }
  });
  if (!createResponse.ok || !createResponse.data?.knowledge_pipeline_run?.id) {
    return { ok: false, error: createResponse.error || "知识库重跑任务创建失败。" };
  }
  const runId = createResponse.data.knowledge_pipeline_run.id;
  const startResponse = await runtimeRequest<KnowledgePipelineResponse>(
    `/v1/knowledge/pipeline-runs/runtime/${encodeURIComponent(runId)}/start?project_id=${encodeURIComponent(pid)}`,
    { method: "POST", body: {} }
  );
  if (!startResponse.ok) {
    return { ok: false, error: startResponse.error || "知识库重跑任务启动失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `知识库 ${runType} 已入队。`,
    details: [["Pipeline", runId], ["Source Pipeline", sourcePipelineRunId]]
  };
}

export async function reviewKnowledgeFactAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const factId = value(formData, "knowledge_fact_id");
  const response = await runtimeRequest<KnowledgeFactReviewResponse>(`/v1/knowledge-facts/runtime/${encodeURIComponent(factId)}/review`, {
    method: "PATCH",
    body: {
      project_id: pid,
      review_status: value(formData, "review_status") || "approved",
      reviewed_by: adminActorId(),
      decision: value(formData, "decision") || "knowledge fact reviewed",
      notes: value(formData, "notes") || null
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "知识事实审核失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `知识事实审核已保存：${response.data?.knowledge_fact?.status || value(formData, "review_status")}`
  };
}

export async function reviewKnowledgeFactCandidateAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const candidateId = value(formData, "fact_candidate_id");
  const response = await runtimeRequest<KnowledgeFactReviewResponse>(`/v1/knowledge/fact-candidates/runtime/${encodeURIComponent(candidateId)}/review`, {
    method: "PATCH",
    body: {
      project_id: pid,
      review_status: value(formData, "review_status") || "approved",
      reviewed_by: adminActorId(),
      decision: value(formData, "decision") || "knowledge fact candidate reviewed",
      notes: value(formData, "notes") || null,
      merged_into_fact_id: value(formData, "merged_into_fact_id") || null
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "候选事实审核失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: response.data?.approved_fact?.id
      ? `候选事实已批准并写入正式事实：${response.data.approved_fact.id}`
      : `候选事实审核已保存：${response.data?.fact_candidate?.status || value(formData, "review_status")}`
  };
}

export async function acceptKnowledgeQualityRiskAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const gateRunId = value(formData, "quality_gate_run_id");
  const expiresAt = value(formData, "expires_at");
  const reason = value(formData, "reason");
  if (!gateRunId) {
    return { ok: false, error: "请选择可以接受风险的质量门禁。" };
  }
  if (!expiresAt) {
    return { ok: false, error: "请填写风险接受到期时间。" };
  }
  const parsedExpiry = new Date(expiresAt);
  if (Number.isNaN(parsedExpiry.valueOf()) || parsedExpiry.valueOf() <= Date.now()) {
    return { ok: false, error: "风险接受到期时间必须晚于当前时间。" };
  }
  const response = await runtimeRequest<KnowledgeQualityRiskResponse>(
    `/v1/knowledge/quality-gate-runs/runtime/${encodeURIComponent(gateRunId)}/accept-risk`,
    {
      method: "POST",
      body: {
        project_id: pid,
        reason,
        expires_at: parsedExpiry.toISOString()
      }
    }
  );
  if (!response.ok) {
    return { ok: false, error: response.error || "质量风险接受失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `已接受 ${response.data?.quality_gate_run?.gate_key || "质量门禁"} 的风险，到期后必须重新处理。`
  };
}

export async function retryKnowledgePipelineStageAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const stageId = value(formData, "pipeline_stage_id");
  if (!stageId) {
    return { ok: false, error: "请选择可重试的失败阶段。" };
  }
  const response = await runtimeRequest<{ requeued_job_count?: number; knowledge_pipeline_stage?: { stage_key?: string } }>(
    `/v1/knowledge/pipeline-stages/runtime/${encodeURIComponent(stageId)}/retry?project_id=${encodeURIComponent(pid)}`,
    { method: "POST", body: {} }
  );
  if (!response.ok) {
    return { ok: false, error: response.error || "知识库阶段重试失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `阶段 ${response.data?.knowledge_pipeline_stage?.stage_key || stageId} 已重新入队。`,
    details: [["重新入队任务", String(response.data?.requeued_job_count || 0)]]
  };
}

export async function disableKnowledgeChunkAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const chunkId = value(formData, "knowledge_chunk_id");
  const reason = value(formData, "reason");
  if (!chunkId || reason.length < 3) {
    return { ok: false, error: "请选择 Chunk，并填写至少 3 个字符的禁用原因。" };
  }
  const response = await runtimeRequest<{ knowledge_chunk?: { id?: string; status?: string } }>(
    `/v1/knowledge/chunks/runtime/${encodeURIComponent(chunkId)}/disable`,
    {
      method: "POST",
      body: { project_id: pid, reason }
    }
  );
  if (!response.ok) {
    return { ok: false, error: response.error || "Chunk 禁用失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `Chunk 已禁用：${response.data?.knowledge_chunk?.id || chunkId}`
  };
}

export async function createKnowledgeFactExtractionAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const sourcePipelineRunId = value(formData, "source_pipeline_run_id");
  if (!sourcePipelineRunId) {
    return { ok: false, error: "请选择包含 active embedded Chunk 的来源 Pipeline。" };
  }
  const response = await runtimeRequest<KnowledgeApplicationResponse>("/v1/knowledge/fact-extraction-jobs/runtime", {
    method: "POST",
    body: {
      project_id: pid,
      source_pipeline_run_id: sourcePipelineRunId,
      import_job_id: value(formData, "import_job_id") || null,
      fact_kinds: lines(value(formData, "fact_kinds") || "brand\ncompetitor\nmarket\nsource"),
      max_facts: numberValue(formData, "max_facts", 20),
      model: "deepseek-v4-flash",
      prompt_version: "knowledge_fact_extraction_v1",
      chunk_filter: {
        source_asset_id: value(formData, "source_asset_id") || null,
        chunk_type: value(formData, "chunk_type") || null,
        quality_flag: value(formData, "quality_flag") || null
      }
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "事实抽取任务创建失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: "事实抽取任务已入队；候选结果必须经过人工审核。",
    details: [
      ["Pipeline", response.data?.knowledge_pipeline_run?.id || "无"],
      ["事实抽取任务", response.data?.fact_extraction_job?.id || "无"]
    ]
  };
}

export async function createKnowledgePromptGenerationAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const templateSelection = value(formData, "prompt_template_id") || "brand_visibility_prompt_v1::v1";
  const [templateKey, selectedTemplateVersion] = templateSelection.split("::", 2);
  const response = await runtimeRequest<KnowledgeApplicationResponse>("/v1/knowledge/prompt-generation-jobs/runtime", {
    method: "POST",
    body: {
      project_id: pid,
      target_platform: value(formData, "target_platform") || "chatgpt",
      intent_type: value(formData, "intent_type") || "brand_visibility",
      city: value(formData, "city") || null,
      requested_count: numberValue(formData, "quantity", 10),
      model: value(formData, "model") || "deepseek-v4-flash",
      template_key: templateKey || "brand_visibility_prompt_v1",
      template_version: selectedTemplateVersion || value(formData, "prompt_template_version") || "v1",
      source_fact_filter: {
        fact_kind: value(formData, "source_fact_kind") || null,
        market_code: value(formData, "source_market_code") || null,
        city: value(formData, "source_city") || null,
        competitor: value(formData, "competitor") || null
      },
      source_chunk_filter: {
        source_asset_id: value(formData, "source_asset_id") || null,
        chunk_type: value(formData, "source_chunk_type") || null,
        quality_flag: value(formData, "source_quality_flag") || null,
        query: value(formData, "source_chunk_query") || null
      }
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "知识应用生成失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: "Prompt 生成任务已入队；完成后候选会进入人工审核队列。",
    details: [
      ["Pipeline", response.data?.knowledge_pipeline_run?.id || "无"],
      ["Prompt 任务", response.data?.prompt_generation_job?.id || "无"],
      ["请求数量", String(response.data?.prompt_generation_job?.requested_count ?? numberValue(formData, "quantity", 10))]
    ]
  };
}

export async function generateKnowledgeContentAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const response = await runtimeRequest<KnowledgeApplicationResponse>("/v1/knowledge/content-generation-jobs/runtime", {
    method: "POST",
    body: {
      project_id: pid,
      content_type: value(formData, "content_type") || "faq",
      target_platform: value(formData, "target_platform") || "website",
      target_city: value(formData, "target_city") || null,
      tone: value(formData, "tone") || "clear",
      required_citations: numberValue(formData, "required_citations", 1),
      forbidden_claims: lines(value(formData, "forbidden_claims")),
      target_audience: value(formData, "target_audience") || "一般客户",
      source_action_id: value(formData, "source_action_id") || null,
      source_report_id: value(formData, "source_report_id") || null,
      source_retest_id: value(formData, "source_retest_id") || null,
      source_gap_type: value(formData, "source_gap_type") || null,
      model: value(formData, "model") || "deepseek-v4-flash",
      template_version: value(formData, "template_version") || "geo_content_draft_v1"
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "GEO 文案生成任务创建失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: "GEO 文案生成任务已入队；草稿生成后必须人工审核。",
    details: [
      ["Pipeline", response.data?.knowledge_pipeline_run?.id || "无"],
      ["内容任务", response.data?.content_generation_job?.id || "无"],
      ["文案类型", response.data?.content_generation_job?.content_type || value(formData, "content_type") || "faq"]
    ]
  };
}

export async function saveKnowledgePromptTemplateAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const outputSchema = jsonObjectValue(formData, "output_schema");
  const modelConfig = jsonObjectValue(formData, "model_config");
  const evaluationSet = jsonArrayValue(formData, "evaluation_set");
  const parseError = outputSchema.error || modelConfig.error || evaluationSet.error;
  if (parseError) {
    return { ok: false, error: parseError };
  }
  const response = await runtimeRequest<KnowledgePromptTemplateResponse>(
    "/v1/knowledge/prompt-generation-templates/runtime",
    {
      method: "POST",
      body: {
        project_id: pid,
        template_key: value(formData, "template_key"),
        template_version: value(formData, "template_version") || "v1",
        name: value(formData, "name"),
        template_body: value(formData, "template_body"),
        status: value(formData, "status") || "draft",
        description: value(formData, "description"),
        system_prompt: value(formData, "system_prompt") || null,
        user_prompt_template: value(formData, "user_prompt_template") || null,
        input_variables: lines(value(formData, "input_variables")),
        output_schema: outputSchema.data || {},
        model_config: modelConfig.data || {},
        evaluation_set: evaluationSet.data || [],
        metadata: { source: "admin_web_prompt_template_editor" }
      }
    }
  );
  if (!response.ok) {
    return { ok: false, error: response.error || "Prompt 生成模板保存失败。" };
  }
  revalidateProject(pid);
  const template = response.data?.prompt_generation_template;
  return {
    ok: true,
    message: `模板已保存：${template?.name || template?.template_key || "未命名"} · ${template?.template_version || "v1"}`
  };
}

export async function reviewPromptCandidateAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const candidateId = value(formData, "prompt_candidate_id");
  const response = await runtimeRequest<PromptCandidateReviewResponse>(`/v1/knowledge/prompt-candidates/runtime/${encodeURIComponent(candidateId)}/review`, {
    method: "PATCH",
    body: {
      project_id: pid,
      review_status: value(formData, "review_status") || "approved",
      reviewed_by: adminActorId(),
      decision: value(formData, "decision") || "prompt candidate reviewed",
      notes: value(formData, "notes") || null,
      edited_text: value(formData, "edited_text") || null
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "Prompt 候选审核失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `Prompt 候选已更新：${response.data?.prompt_candidate?.review_status || value(formData, "review_status")}`
  };
}

export async function importApprovedPromptCandidatesAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const response = await runtimeRequest<PromptCandidateImportResponse>("/v1/knowledge/prompt-candidates/runtime/import-approved", {
    method: "POST",
    body: {
      project_id: pid,
      imported_by: adminActorId(),
      prompt_candidate_ids: lines(value(formData, "prompt_candidate_ids")),
      prompt_version: value(formData, "prompt_version") || null
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "Prompt 候选导入失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `已导入 Prompt：${response.data?.prompt_import?.prompt_count ?? 0} 条`,
    details: [["Prompt version", response.data?.prompt_import?.prompt_version || "自动生成"]]
  };
}

export async function saveConnectorSecretAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const provider = value(formData, "provider");
  const response = await runtimeRequest<ConnectorSecretResponse>("/v1/connectors/runtime/secrets", {
    method: "POST",
    body: {
      project_id: pid,
      provider,
      raw_secret: value(formData, "raw_secret"),
      purpose: value(formData, "purpose") || "api_key",
      metadata: {
        created_from: "admin_web_project_detail",
        label: value(formData, "label")
      },
      updated_by: adminActorId(),
      reason: "admin_web_connector_secret_save"
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "连接器密钥保存失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `连接器密钥已保存：${response.data?.connector_secret?.provider || provider}`,
    details: [["状态", response.data?.connector_secret?.status || "masked"]]
  };
}

export async function importManualBackfillAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const response = await runtimeRequest<{ record_count?: number; records?: unknown[] }>("/v1/evidence-runs/runtime/manual-backfill/import.csv", {
    method: "POST",
    body: {
      project_id: pid,
      csv_content: value(formData, "csv_content"),
      submitted_by: adminActorId(),
      max_rows: Number(value(formData, "max_rows") || "120"),
      notes: value(formData, "notes") || "admin_web_google_manual_backfill"
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "Google 手工补录导入失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: "Google 手工补录已写入证据链。",
    details: [["导入记录", String(response.data?.record_count ?? response.data?.records?.length ?? 0)]]
  };
}

export async function submitManualBackfillAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const promptQuestionId = value(formData, "prompt_question_id");
  const response = await runtimeRequest<ManualBackfillResponse>("/v1/evidence-runs/runtime/manual-backfill", {
    method: "POST",
    body: {
      prompt_question_id: promptQuestionId,
      platform: value(formData, "platform") || "google",
      surface: value(formData, "surface") || "google_ai_mode",
      answer_text: value(formData, "answer_text"),
      citation_urls: lines(value(formData, "citation_urls")),
      screenshot_url: value(formData, "screenshot_url") || null,
      html_snapshot_url: value(formData, "html_snapshot_url") || null,
      answer_present: value(formData, "answer_present") !== "0",
      surface_triggered: value(formData, "surface_triggered") !== "0",
      sample_index: Number(value(formData, "sample_index") || "1"),
      sample_size: Number(value(formData, "sample_size") || "1"),
      device: value(formData, "device") || "desktop",
      account_state: value(formData, "account_state") || null,
      submitted_by: adminActorId(),
      notes: value(formData, "notes") || "admin_web_single_manual_backfill"
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "单条手工补录失败。" };
  }
  return {
    ok: true,
    message: "单条手工补录已写入。",
    details: [
      ["Answer run", response.data?.answer_run_id || "未返回"],
      ["Citation", String(response.data?.citation_count ?? 0)],
      ["Evidence asset", String(response.data?.evidence_asset_count ?? 0)]
    ]
  };
}

export async function recordHumanReviewAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const response = await runtimeRequest<HumanReviewResponse>("/v1/human-reviews/runtime", {
    method: "POST",
    body: {
      project_id: pid,
      target_type: value(formData, "target_type"),
      target_id: value(formData, "target_id"),
      review_status: value(formData, "review_status") || "approved",
      decision: value(formData, "decision"),
      reviewer_id: adminActorId(),
      notes: value(formData, "notes") || null,
      payload: {
        created_from: "admin_web_project_detail",
        correction: value(formData, "correction")
      }
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "人工复核保存失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `人工复核已保存：${response.data?.human_review?.review_status || "recorded"}`,
    details: [["复核 ID", response.data?.human_review?.id || "未返回"]]
  };
}

export async function updateReportManagementAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const reportExportId = value(formData, "report_export_id");
  const status = value(formData, "status");
  const response = await runtimeRequest<ReportManagementResponse>(`/v1/reports/runtime/${encodeURIComponent(reportExportId)}/management-events`, {
    method: "POST",
    body: {
      status,
      updated_by: adminActorId(),
      note: value(formData, "note") || `admin_web_report_${status}`
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "报告状态更新失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `报告状态已更新：${status}`,
    details: [["报告 ID", reportExportId]]
  };
}

export async function enqueueReportJobAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const response = await runtimeRequest<ReportExportJobResponse>("/v1/report-export-jobs/runtime", {
    method: "POST",
    body: {
      project_id: pid,
      report_export_id: value(formData, "report_export_id") || null,
      artifact_type: value(formData, "artifact_type") || "pdf",
      template: value(formData, "template") || "standard",
      filters: {},
      sort: value(formData, "sort") || "collected_at_desc",
      requested_by: adminActorId(),
      reason: "admin_web_report_export_job_enqueue"
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "报告任务创建失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `报告任务已创建：${response.data?.report_export_job?.id || "created"}`,
    details: [["状态", response.data?.report_export_job?.status || "queued"]]
  };
}

export async function updateReportJobStatusAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const jobId = value(formData, "job_id");
  const response = await runtimeRequest<ReportExportJobResponse>(`/v1/report-export-jobs/runtime/${encodeURIComponent(jobId)}/status`, {
    method: "POST",
    body: {
      status: value(formData, "status"),
      updated_by: adminActorId(),
      report_export_id: value(formData, "report_export_id") || null,
      artifact_url: value(formData, "artifact_url") || null,
      error_message: value(formData, "error_message") || null,
      reason: "admin_web_report_job_status_update"
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "报告任务状态更新失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `报告任务状态已更新：${response.data?.report_export_job?.status || value(formData, "status")}`,
    details: [["任务 ID", jobId]]
  };
}

export async function saveBrandAssetAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const response = await runtimeRequest<BrandAssetResponse>("/v1/project-brand-assets/runtime", {
    method: "POST",
    body: {
      project_id: pid,
      asset_type: value(formData, "asset_type") || "image",
      asset_url: value(formData, "asset_url"),
      category: value(formData, "category") || "brand",
      preview_url: value(formData, "preview_url") || null,
      source_filename: value(formData, "source_filename") || null,
      source_content_type: value(formData, "source_content_type") || null,
      content_hash: value(formData, "content_hash") || null,
      storage_version: value(formData, "storage_version") || null,
      status: value(formData, "status") || "active",
      uploaded_by: adminActorId(),
      metadata: { created_from: "admin_web_project_detail" },
      reason: "admin_web_brand_asset_save"
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "品牌资产保存失败。" };
  }
  revalidateProject(pid);
  return { ok: true, message: `品牌资产已保存：${response.data?.brand_asset?.id || response.data?.asset?.id || "created"}` };
}

export async function saveSavedViewAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const response = await runtimeRequest<SavedViewResponse>("/v1/runtime-saved-views", {
    method: "POST",
    body: {
      project_id: pid,
      name: value(formData, "name"),
      view_type: value(formData, "view_type") || "project_detail",
      filters: { tab: value(formData, "target_tab") || "status" },
      sort: value(formData, "sort") || "created_at_desc",
      query_path: `/projects/${pid}?tab=${value(formData, "target_tab") || "status"}`,
      export_path: value(formData, "export_path") || "",
      created_by: adminActorId()
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "保存视图失败。" };
  }
  revalidateProject(pid);
  return { ok: true, message: `视图已保存：${response.data?.saved_view?.name || value(formData, "name")}` };
}

export async function createFidelityCheckAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const response = await runtimeRequest<FidelityCheckResponse>("/v1/fidelity-checks/runtime", {
    method: "POST",
    body: {
      project_id: pid,
      report_export_id: value(formData, "report_export_id") || null,
      checked_by: adminActorId()
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "质量检查创建失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `质量检查已创建：${response.data?.fidelity_check?.id || "created"}`,
    details: [["状态", response.data?.fidelity_check?.status || "pending"]]
  };
}

export async function updateActionRecommendationAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const actionId = value(formData, "action_id");
  const customerVisibleRaw = value(formData, "customer_visible");
  const response = await runtimeRequest<ActionRecommendationResponse>(`/v1/action-plans/runtime/${encodeURIComponent(actionId)}`, {
    method: "PATCH",
    body: {
      project_id: pid,
      status: value(formData, "status") || "open",
      owner_id: value(formData, "owner_id") || null,
      customer_visible: customerVisibleRaw ? customerVisibleRaw === "1" : null,
      visibility_note: value(formData, "visibility_note") || null,
      updated_by: adminActorId(),
      reason: "admin_web_action_recommendation_update"
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "行动计划更新失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `行动计划已更新：${response.data?.action_recommendation?.status || value(formData, "status")}`,
    details: [["Action ID", actionId]]
  };
}

export async function reviewContentDraftAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const draftId = value(formData, "content_draft_id");
  const reviewStatus = value(formData, "review_status") || "approved";
  if (!pid || !draftId) {
    return { ok: false, error: "project_id 和 content_draft_id 必填。" };
  }
  const response = await runtimeRequest<ContentDraftReviewResponse>(`/v1/knowledge/content-drafts/runtime/${encodeURIComponent(draftId)}/review`, {
    method: "PATCH",
    body: {
      project_id: pid,
      review_status: reviewStatus,
      reviewer_id: adminActorId(),
      decision: value(formData, "decision") || `content draft ${reviewStatus}`,
      notes: value(formData, "notes") || null,
      payload: {
        source: "admin_web_content_workbench",
        visibility: value(formData, "visibility") || "internal_review"
      }
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "内容草稿审核失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `内容草稿审核状态已更新：${response.data?.content_draft?.review_status || reviewStatus}`,
    details: [
      ["Draft ID", response.data?.content_draft?.id || draftId],
      ["Review ID", response.data?.human_review?.id || "已记录"]
    ]
  };
}

export async function backfillManualDistributionAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const distributionId = value(formData, "distribution_record_id");
  const targetUrl = value(formData, "target_url");
  if (!pid || !distributionId || !targetUrl) {
    return { ok: false, error: "project_id、distribution_record_id 和 target_url 必填。" };
  }
  const response = await runtimeRequest<ManualDistributionBackfillResponse>(
    `/v1/manual-distribution-records/runtime/${encodeURIComponent(distributionId)}/backfill`,
    {
      method: "PATCH",
      body: {
        project_id: pid,
        target_url: targetUrl,
        status: value(formData, "status") || "url_backfilled",
        checked_by: adminActorId(),
        notes: value(formData, "notes") || null
      }
    }
  );
  if (!response.ok) {
    return { ok: false, error: response.error || "Distribution 回填失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `Distribution 已回填：${response.data?.manual_distribution_record?.status || "url_backfilled"}`,
    details: [
      ["Distribution ID", response.data?.manual_distribution_record?.id || distributionId],
      ["URL", response.data?.manual_distribution_record?.target_url || targetUrl]
    ]
  };
}

export async function runFixtureE2EAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const cities = lines(value(formData, "cities"));
  const response = await runtimeRequest<FixtureCollectionResponse>("/v1/collection-runs/runtime/fixture", {
    method: "POST",
    body: {
      project_id: projectId(formData),
      prompt_limit: Number(value(formData, "prompt_limit") || "1"),
      cities: cities.length ? cities : ["Global"],
      sample_size: Number(value(formData, "sample_size") || "3"),
      persist_analysis: value(formData, "persist_analysis") !== "0",
      requested_by: adminActorId(),
      reason: "admin_web_fixture_e2e_run"
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "本地全流程测试触发失败。" };
  }
  const analysis = response.data?.persistence?.analysis || {};
  return {
    ok: true,
    message: "本地全流程测试已完成并写入当前项目。",
    details: [
      ["采集记录", String(response.data?.record_count ?? 0)],
      ["成功 / 失败", `${response.data?.success_count ?? 0} / ${response.data?.failure_count ?? 0}`],
      ["评分快照", String(analysis.score_snapshot_id || "未生成")],
      ["报告", String(analysis.report_export_id || "未生成")],
      ["最终分数", analysis.final_score === undefined ? "无" : String(analysis.final_score)],
      ["行动建议", String(analysis.action_recommendations ?? 0)],
      ["内容草稿", String(analysis.content_drafts ?? 0)],
      ["Traceability", String(analysis.traceability_bundle_id || "未生成")]
    ]
  };
}

export async function enqueueCollectionAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const response = await runtimeRequest<{
    collection_job?: { id?: string; status?: string };
    queue_dispatch?: { status?: string; message_id?: string | null };
  }>("/v1/collection-jobs/runtime", {
    method: "POST",
    body: {
      project_id: pid,
      prompt_limit: Number(value(formData, "prompt_limit") || "10"),
      sample_size: Number(value(formData, "sample_size") || "1"),
      cities: lines(value(formData, "cities")),
      max_attempts: 3,
      requested_by: adminActorId()
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "正式采集任务创建失败。" };
  }
  revalidateProject(pid);
  return {
    ok: true,
    message: `正式采集任务已入队：${response.data?.collection_job?.id || "queued"}`,
    details: [
      ["任务状态", response.data?.collection_job?.status || "queued"],
      ["队列投递", response.data?.queue_dispatch?.status || "unknown"]
    ]
  };
}

export async function cancelCollectionAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const jobId = value(formData, "collection_job_id");
  const response = await runtimeRequest<{ collection_job?: { id?: string; status?: string } }>(
    `/v1/collection-jobs/runtime/${encodeURIComponent(jobId)}/cancel?project_id=${encodeURIComponent(pid)}`,
    { method: "POST" }
  );
  if (!response.ok) {
    return { ok: false, error: response.error || "采集任务取消失败。" };
  }
  revalidateProject(pid);
  return { ok: true, message: `采集任务已取消：${response.data?.collection_job?.id || jobId}` };
}

export async function createInvitationAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const email = String(formData.get("email") || "").trim().toLowerCase();
  const replaceConfirmed = value(formData, "replace_existing_pending") === "1";
  const pendingInvitationIdsFromForm = lines(value(formData, "existing_pending_invitation_ids"));
  const pendingLookup = await runtimeRequest<InvitationPageResponse>("/v1/project-member-invitations/runtime", {
    query: { project_id: pid, status: "pending", limit: 50 }
  });
  if (!pendingLookup.ok) {
    return { ok: false, error: pendingLookup.error || "无法检查已有待处理邀请，未生成新的邀请。" };
  }
  const pendingInvitationIdsFromApi = (pendingLookup.data?.records || [])
    .map((record) => record.invitation || {})
    .filter((invitation) => {
      const invitationEmail = String(invitation.email || "").trim().toLowerCase();
      const role = String(invitation.role || "viewer").trim().toLowerCase();
      const status = String(invitation.status || "").trim().toLowerCase();
      return invitationEmail === email && role === "viewer" && status === "pending";
    })
    .map((invitation) => String(invitation.id || "").trim())
    .filter(Boolean);
  const pendingInvitationIds = Array.from(new Set([...pendingInvitationIdsFromForm, ...pendingInvitationIdsFromApi]));
  if (pendingInvitationIds.length && !replaceConfirmed) {
    return {
      ok: false,
      error: "已存在待处理邀请。请确认旧邀请 token 失效后再生成新的邀请。"
    };
  }
  for (const invitationId of pendingInvitationIds) {
    const revokeResponse = await runtimeRequest<InvitationResponse>("/v1/project-member-invitations/runtime/action", {
      method: "POST",
      body: {
        project_id: pid,
        invitation_id: invitationId,
        action: "revoke",
        updated_by: adminActorId(),
        reason: "admin_web_customer_invitation_replace_existing_pending"
      }
    });
    if (!revokeResponse.ok) {
      return { ok: false, error: revokeResponse.error || "旧邀请失效失败，未生成新的邀请。" };
    }
  }
  const payload = {
    project_id: pid,
    email,
    role: "viewer",
    invited_by: adminActorId(),
    metadata: {
      created_from: "admin_web_project_detail",
      replaced_pending_invitation_ids: pendingInvitationIds
    },
    reason: "admin_web_customer_invitation_create"
  };
  const response = await runtimeRequest<InvitationResponse>("/v1/project-member-invitations/runtime", {
    method: "POST",
    body: payload
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "客户邀请创建失败。" };
  }
  revalidateProject(payload.project_id);
  const invitation = response.data?.invitation;
  const inviteUrl =
    invitation?.id && invitation?.invite_token
      ? customerInvitationUrl(invitation.id, invitation.invite_token)
      : undefined;
  const replacedCount = pendingInvitationIds.length;
  return {
    ok: true,
    message: replacedCount
      ? `旧邀请已失效，新的邀请已创建：${invitation?.email || payload.email}`
      : `邀请已创建：${invitation?.email || payload.email}`,
    details: replacedCount
      ? [
          ["已失效旧邀请数", String(replacedCount)],
          ["新邀请 ID", invitation?.id || "未返回"]
        ]
      : undefined,
    inviteUrl,
    rawInviteToken: invitation?.invite_token
  };
}

export async function invitationAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const pid = projectId(formData);
  const action = value(formData, "action") || "revoke";
  const invitationId = value(formData, "invitation_id");
  const response = await runtimeRequest<InvitationResponse>("/v1/project-member-invitations/runtime/action", {
    method: "POST",
    body: {
      project_id: pid,
      invitation_id: invitationId,
      action,
      updated_by: adminActorId(),
      reason: `admin_web_invitation_${action}`
    }
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "邀请操作失败。" };
  }
  revalidateProject(pid);
  return { ok: true, message: action === "expire" ? "邀请已过期。" : "邀请已撤销。" };
}
