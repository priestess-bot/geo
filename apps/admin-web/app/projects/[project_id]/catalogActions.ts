"use server";

import { createHash } from "node:crypto";
import { revalidatePath } from "next/cache";

import { runtimeRequest, type RuntimeResult } from "../../runtime";
import { isCatalogProject, type CatalogProject } from "../projectTypes";
import {
  confidentialityValues,
  entityTypes,
  genericEvidenceItemTypes,
  isCatalogEntity,
  isEvidenceItem,
  isMarketProfile,
  subjectRoles,
  usageRightsValues,
  type CatalogActionState,
  type CatalogEntity,
  type Confidentiality,
  type CreateEntityRequest,
  type CreateEvidenceRequest,
  type CreateMarketProfileRequest,
  type EntityType,
  type EvidenceItem,
  type GenericEvidenceItemType,
  type MarketProfile,
  type SubjectRole,
  type UpdateProjectRequest,
  type UsageRights
} from "./catalogTypes";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function updateProjectAction(
  _previous: CatalogActionState,
  formData: FormData
): Promise<CatalogActionState> {
  const projectId = required(formData, "project_id");
  const name = required(formData, "name");
  const status = required(formData, "status");
  if (!projectId || !name || name.length > 200 || !isProjectStatus(status)) {
    return invalid("项目名称或状态无效。");
  }
  const payload: UpdateProjectRequest = { name, status };
  const response = await runtimeRequest<CatalogProject>(projectPath(projectId), {
    method: "PATCH",
    body: payload
  });
  return finish(response, isCatalogProject, projectId, "项目设置已更新。", "项目更新失败。");
}

export async function createEntityAction(
  _previous: CatalogActionState,
  formData: FormData
): Promise<CatalogActionState> {
  const projectId = required(formData, "project_id");
  const entityType = required(formData, "entity_type");
  const canonicalName = required(formData, "canonical_name");
  const attributes = jsonObject(formData, "attributes", "实体属性");
  if (!projectId || !includes(entityTypes, entityType) || !canonicalName || canonicalName.length > 300) {
    return invalid("项目、实体类型和规范名称不能为空。");
  }
  if (!attributes.ok) return invalid(attributes.error);
  const canonicalUrl = required(formData, "canonical_url") || null;
  if (canonicalUrl && canonicalUrl.length > 2000) return invalid("规范 URL 不能超过 2000 个字符。");
  const payload: CreateEntityRequest = {
    entity_type: entityType as EntityType,
    canonical_name: canonicalName,
    canonical_url: canonicalUrl,
    attributes: attributes.value
  };
  const response = await runtimeRequest<CatalogEntity>(`${projectPath(projectId)}/entities`, {
    method: "POST",
    body: payload
  });
  return finish(response, isCatalogEntity, projectId, "实体已添加。", "实体创建失败。");
}

export async function createMarketProfileAction(
  _previous: CatalogActionState,
  formData: FormData
): Promise<CatalogActionState> {
  const projectId = required(formData, "project_id");
  const marketCode = required(formData, "market_code").toUpperCase();
  const locale = required(formData, "locale");
  const timezone = required(formData, "timezone");
  const rules = jsonObject(formData, "rules", "市场规则");
  if (!projectId || !/^[A-Z]{2}$/.test(marketCode) || !locale || !timezone) {
    return invalid("市场代码必须为两个字母，locale 和 timezone 均为必填项。");
  }
  if (!rules.ok) return invalid(rules.error);
  const payload: CreateMarketProfileRequest = {
    market_code: marketCode,
    locale,
    timezone,
    rules: rules.value
  };
  const response = await runtimeRequest<MarketProfile>(`${projectPath(projectId)}/market-profiles`, {
    method: "POST",
    body: payload
  });
  return finish(response, isMarketProfile, projectId, "市场配置已添加。", "市场配置创建失败。");
}

export async function createEvidenceAction(
  _previous: CatalogActionState,
  formData: FormData
): Promise<CatalogActionState> {
  const parsed = evidencePayload(formData);
  if (!parsed.ok) return invalid(parsed.error);
  const response = await runtimeRequest<EvidenceItem>(
    `${projectPath(parsed.projectId)}/evidence-items`,
    { method: "POST", body: parsed.value }
  );
  return finish(response, isEvidenceItem, parsed.projectId, "证据已录入。", "证据录入失败。");
}

function evidencePayload(formData: FormData):
  | { ok: true; projectId: string; value: CreateEvidenceRequest }
  | { ok: false; error: string } {
  const projectId = required(formData, "project_id");
  const itemType = required(formData, "item_type");
  const sourceId = required(formData, "source_id");
  const subjectRole = required(formData, "subject_role");
  const subjectEntityId = required(formData, "subject_entity_id") || null;
  const text = required(formData, "snapshot_text");
  const revisionKind = required(formData, "revision_kind");
  const revisionValue = required(formData, "revision_value");
  const usageRights = required(formData, "usage_rights");
  const confidentiality = required(formData, "confidentiality");
  const locator = jsonObject(formData, "locator", "证据定位信息");
  if (!projectId || !UUID_PATTERN.test(sourceId) || !includes(genericEvidenceItemTypes, itemType)) {
    return { ok: false, error: "项目、证据类型和有效的 Source UUID 均为必填项。" };
  }
  if (!includes(subjectRoles, subjectRole)) return { ok: false, error: "事实主体角色无效。" };
  if ((subjectRole === "neutral") !== (subjectEntityId === null)) {
    return { ok: false, error: "neutral 证据不能绑定实体，其他主体角色必须绑定实体。" };
  }
  if (subjectEntityId && !UUID_PATTERN.test(subjectEntityId)) return { ok: false, error: "主体实体 ID 无效。" };
  if (!text || Buffer.byteLength(text, "utf8") > 32768) return { ok: false, error: "证据描述不能为空且不能超过 32 KiB。" };
  if (!isRevisionKind(revisionKind) || !revisionValue) return { ok: false, error: "来源版本类型和值不能为空。" };
  if (!includes(usageRightsValues, usageRights) || !includes(confidentialityValues, confidentiality)) {
    return { ok: false, error: "使用权或机密级别无效。" };
  }
  if (!locator.ok) return locator;
  const disclosureAllowed = checked(formData, "disclosure_allowed");
  const citation: CreateEvidenceRequest["public_citation"] = {
    disclosure_allowed: disclosureAllowed,
    source_url: required(formData, "source_url") || null,
    source_title: required(formData, "source_title") || null,
    label: required(formData, "citation_label") || null,
    quotation_allowed: checked(formData, "quotation_allowed"),
    attribution_required: checked(formData, "attribution_required")
  };
  if (disclosureAllowed && (!citation.source_url || !citation.source_title || !citation.label)) {
    return { ok: false, error: "允许公开披露时，公开 URL、标题和引用标签均为必填项。" };
  }
  return {
    ok: true,
    projectId,
    value: {
      item_type: itemType as GenericEvidenceItemType,
      source_id: sourceId,
      subject_entity_id: subjectEntityId,
      subject_role: subjectRole as SubjectRole,
      locator: locator.value,
      snapshot: {
        kind: "text",
        text,
        sha256: createHash("sha256").update(text, "utf8").digest("hex")
      },
      source_revision: { kind: revisionKind, value: revisionValue },
      usage_rights: usageRights as UsageRights,
      confidentiality: confidentiality as Confidentiality,
      public_citation: citation
    }
  };
}

function finish<T>(
  response: RuntimeResult<T>,
  guard: (value: unknown) => value is T,
  projectId: string,
  success: string,
  fallback: string
): CatalogActionState {
  if (!response.ok) {
    return {
      kind: "error",
      status: response.status,
      message: `${failureLabel(response.status)}${response.error || fallback}`,
      ...(response.problem.correlation_id
        ? { correlationId: response.problem.correlation_id }
        : {})
    };
  }
  if (!guard(response.data)) {
    return {
      kind: "error",
      status: 502,
      message: "Catalog 接口返回了无法识别的响应。",
      ...(response.response.correlationId
        ? { correlationId: response.response.correlationId }
        : {})
    };
  }
  revalidatePath(`/projects/${projectId}`);
  return { kind: "success", message: success };
}

function jsonObject(
  formData: FormData,
  name: string,
  label: string
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const raw = required(formData, name);
  if (!raw) return { ok: true, value: {} };
  try {
    const value = JSON.parse(raw) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return { ok: false, error: `${label}必须是 JSON object。` };
    }
    return { ok: true, value: value as Record<string, unknown> };
  } catch {
    return { ok: false, error: `${label}不是有效 JSON。` };
  }
}

function projectPath(projectId: string): string {
  return `/v1/projects/${encodeURIComponent(projectId)}`;
}

function required(formData: FormData, name: string): string {
  return String(formData.get(name) || "").trim();
}

function checked(formData: FormData, name: string): boolean {
  return formData.get(name) === "on";
}

function includes<T extends readonly string[]>(values: T, value: string): value is T[number] {
  return values.some((candidate) => candidate === value);
}

function isProjectStatus(value: string): value is "active" | "paused" | "archived" {
  return value === "active" || value === "paused" || value === "archived";
}

function isRevisionKind(value: string): value is "row_version" | "content_hash" | "report_version" {
  return value === "row_version" || value === "content_hash" || value === "report_version";
}

function invalid(message: string): CatalogActionState {
  return { kind: "error", status: 422, message };
}

function failureLabel(status: number | undefined): string {
  if (status === 401) return "登录已失效：";
  if (status === 403) return "权限不足：";
  if (status === 409) return "状态冲突：";
  if (status === 422) return "输入无效：";
  return "";
}
