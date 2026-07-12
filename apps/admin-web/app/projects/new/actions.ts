"use server";

import { adminActorId, customerInvitationUrl, lines, runtimeRequest } from "../../runtime";

export type CreateProjectActionState = {
  ok: boolean;
  error?: string;
  projectId?: string;
  projectName?: string;
  inviteUrl?: string;
  invitationId?: string;
  rawInviteToken?: string;
};

type RuntimeProjectCreateResponse = {
  project_id?: string;
  bootstrap?: { project?: { name?: string; target_brand?: string } };
  customer_invitation?: { invitation?: { id?: string; invite_token?: string; email?: string } };
};

function requiredString(formData: FormData, key: string, fallback: string): string {
  return String(formData.get(key) || fallback).trim();
}

export async function createProjectAction(
  _previousState: CreateProjectActionState,
  formData: FormData
): Promise<CreateProjectActionState> {
  const competitorsFromRows = formData
    .getAll("competitor_name")
    .map((item) => String(item || "").trim())
    .filter(Boolean);
  const competitorDomainsFromRows = formData
    .getAll("competitor_domain")
    .map((item) => String(item || "").trim())
    .filter(Boolean);
  const competitors = competitorsFromRows.length ? competitorsFromRows : lines(formData.get("competitors"));
  if (competitors.length < 3 || competitors.length > 5) {
    return { ok: false, error: "竞品名称需要填写 3 到 5 个。" };
  }
  const timezone = requiredString(formData, "timezone", "UTC");
  const payload = {
    tenant_name: requiredString(formData, "tenant_name", "客户组织"),
    project_name: requiredString(formData, "project_name", "客户品牌 GEO 项目"),
    target_brand: requiredString(formData, "target_brand", "客户品牌"),
    category: requiredString(formData, "category", "产品与服务"),
    market_code: requiredString(formData, "market_code", "GLOBAL").toUpperCase(),
    market_name: requiredString(formData, "market_name", "Global"),
    locale: requiredString(formData, "locale", "en"),
    timezone,
    currency: requiredString(formData, "currency", "USD").toUpperCase(),
    primary_language: requiredString(formData, "primary_language", "English"),
    cities: lines(formData.get("cities")),
    industry_code: requiredString(formData, "industry_code", "dtc_ecommerce"),
    industry_name: requiredString(formData, "industry_name", "DTC / e-commerce"),
    prompt_version: "project_prompts_v1",
    score_formula_version: "visibility_v1.0",
    competitors,
    brand_official_domains: lines(formData.get("brand_official_domains")),
    brand_parent_company: String(formData.get("brand_parent_company") || "").trim() || null,
    brand_product_lines: lines(formData.get("brand_product_lines")),
    owner_user_id: requiredString(formData, "owner_user_id", adminActorId()),
    customer_email: String(formData.get("customer_email") || "").trim() || null,
    competitor_domains: competitorDomainsFromRows.length ? competitorDomainsFromRows : lines(formData.get("competitor_domains")),
    collection_mode: requiredString(formData, "collection_mode", "api"),
    launch_status: "draft",
    schedule: { frequency: "weekly", timezone },
    external_connectors: {},
    create_customer_invitation: true
  };
  const response = await runtimeRequest<RuntimeProjectCreateResponse>("/v1/projects/runtime", {
    method: "POST",
    body: payload
  });
  if (!response.ok || !response.data?.project_id) {
    return { ok: false, error: response.error || "项目创建失败。" };
  }
  const invitation = response.data.customer_invitation?.invitation;
  const invitationId = invitation?.id;
  const rawInviteToken = invitation?.invite_token;
  const inviteUrl =
    invitationId && rawInviteToken
      ? customerInvitationUrl(invitationId, rawInviteToken)
      : undefined;
  return {
    ok: true,
    projectId: response.data.project_id,
    projectName: response.data.bootstrap?.project?.target_brand || response.data.bootstrap?.project?.name,
    invitationId,
    rawInviteToken,
    inviteUrl
  };
}
