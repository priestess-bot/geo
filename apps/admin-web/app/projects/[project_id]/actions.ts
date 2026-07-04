"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import { adminActorId, customerInvitationUrl, runtimeRequest } from "../../runtime";

export type ProjectActionState = {
  ok: boolean;
  message?: string;
  error?: string;
  details?: Array<[string, string]>;
  rawToken?: string;
  inviteUrl?: string;
  rawInviteToken?: string;
};

type TokenResponse = {
  raw_token?: string;
  portal_token?: { id?: string };
};

type InvitationResponse = {
  invitation?: { id?: string; invite_token?: string; email?: string };
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

function revalidateProject(projectId: string): void {
  if (projectId) {
    revalidatePath(`/projects/${projectId}`);
  }
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
    status: value(formData, "status"),
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
  return { ok: true, message: action === "archive" ? "项目已归档。" : "项目已恢复。" };
}

export async function saveLaunchConfigAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const schedule = {
    cadence: value(formData, "schedule_cadence") || "weekly",
    weekday: value(formData, "schedule_weekday") || "monday",
    timezone: value(formData, "timezone") || "Australia/Sydney"
  };
  const externalConnectors = {
    openai: {
      status: value(formData, "connector_openai_status") || "not_configured",
      mode: value(formData, "connector_openai_mode") || "env",
      model: value(formData, "connector_openai_model") || "gpt-4.1-mini",
      env_var: value(formData, "connector_openai_env_var") || "OPENAI_API_KEY",
      notes: value(formData, "connector_openai_notes")
    },
    perplexity: {
      status: value(formData, "connector_perplexity_status") || "not_configured",
      mode: value(formData, "connector_perplexity_mode") || "env",
      model: value(formData, "connector_perplexity_model") || "sonar",
      env_var: value(formData, "connector_perplexity_env_var") || "PERPLEXITY_API_KEY",
      notes: value(formData, "connector_perplexity_notes")
    },
    google_ai_mode: {
      status: value(formData, "connector_google_ai_mode_status") || "fixture_only",
      mode: value(formData, "connector_google_ai_mode_mode") || "manual_or_browser",
      model: value(formData, "connector_google_ai_mode_model") || "google_ai_mode",
      env_var: value(formData, "connector_google_ai_mode_env_var") || "GOOGLE_PLAYWRIGHT_ENABLED",
      notes: value(formData, "connector_google_ai_mode_notes")
    }
  };
  const payload = {
    project_id: projectId(formData),
    customer_email: value(formData, "customer_email"),
    primary_domain: value(formData, "primary_domain"),
    competitor_domains: lines(value(formData, "competitor_domains_snapshot")),
    locale: value(formData, "locale") || "en-AU",
    country_code: value(formData, "country_code") || "AU",
    timezone: value(formData, "timezone") || "Australia/Sydney",
    collection_mode: value(formData, "collection_mode") || "fixture",
    schedule,
    external_connectors: externalConnectors,
    scoring_profile: value(formData, "scoring_profile") || "au_visibility_v1",
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
    language: value(formData, "language") || "en-AU",
    target_brand: value(formData, "target_brand"),
    competitors: lines(value(formData, "competitors")),
    priority: numberValue(formData, "priority", 1),
    intent_weight: numberValue(formData, "intent_weight", 1),
    prompt_version: value(formData, "prompt_version") || "au_dtc_ecommerce_v1",
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
  redirect(`/projects/${pid}?tab=prompts&prompt_limit=${value(formData, "prompt_limit") || "20"}&prompt_imported=${response.data?.prompt_import?.prompt_count ?? 0}`);
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
      cities: cities.length ? cities : ["Sydney"],
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

export async function createPortalTokenAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const payload = {
    project_id: projectId(formData),
    member_user_id: String(formData.get("member_user_id") || "").trim(),
    invitation_id: String(formData.get("invitation_id") || "").trim() || null,
    issued_by: adminActorId(),
    metadata: { created_from: "admin_web" },
    reason: "admin_web_customer_portal_token_create"
  };
  const response = await runtimeRequest<TokenResponse>("/v1/customer-portal/tokens/runtime", {
    method: "POST",
    body: payload
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "门户 token 创建失败。" };
  }
  revalidateProject(payload.project_id);
  return {
    ok: true,
    message: `token 已创建：${response.data?.portal_token?.id || "created"}`,
    rawToken: response.data?.raw_token
  };
}

export async function revokePortalTokenAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const payload = {
    project_id: projectId(formData),
    token_id: String(formData.get("token_id") || "").trim(),
    revoked_by: adminActorId(),
    reason: "admin_web_customer_portal_token_revoke"
  };
  const response = await runtimeRequest<TokenResponse>("/v1/customer-portal/tokens/runtime/revoke", {
    method: "POST",
    body: payload
  });
  if (!response.ok) {
    return { ok: false, error: response.error || "门户 token 撤销失败。" };
  }
  revalidateProject(payload.project_id);
  return { ok: true, message: `token 已撤销：${response.data?.portal_token?.id || payload.token_id}` };
}

export async function createInvitationAction(
  _previousState: ProjectActionState,
  formData: FormData
): Promise<ProjectActionState> {
  const payload = {
    project_id: projectId(formData),
    email: String(formData.get("email") || "").trim(),
    role: "viewer",
    invited_by: adminActorId(),
    metadata: { created_from: "admin_web_project_detail" },
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
  return {
    ok: true,
    message: `邀请已创建：${invitation?.email || payload.email}`,
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
