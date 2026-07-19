"use server";

import { randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { runtimeRequest, type RuntimeResult } from "../../runtime";
import type { KnowledgeActionState } from "./knowledgeTypes";

type Created = { pipeline_run?: { id?: string }; pipeline_run_id?: string };

export async function importKnowledgeSource(
  _previous: KnowledgeActionState,
  form: FormData
): Promise<KnowledgeActionState> {
  const projectId = field(form, "project_id");
  const sourceKind = field(form, "source_kind") || "url";
  const title = field(form, "title");
  if (!projectId || !title) return error("项目和来源标题不能为空。", 422);
  const body: Record<string, unknown> = {
    source_kind: sourceKind,
    title,
    source_url: field(form, "source_url") || null,
    filename: field(form, "filename") || null,
    media_type: field(form, "media_type") || (sourceKind === "url" ? "text/html" : "text/plain")
  };
  if (sourceKind === "text") body.content_text = field(form, "content_text");
  if (sourceKind === "file") {
    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) return error("请选择要导入的文件。", 422);
    if (file.size > 5 * 1024 * 1024) return error("文件不能超过 5 MB。", 422);
    body.filename = file.name;
    body.media_type = file.type || "text/plain";
    body.content_base64 = Buffer.from(await file.arrayBuffer()).toString("base64");
  }
  const response = await runtimeRequest<Created>(path(projectId, "/sources"), {
    method: "POST",
    body,
    idempotencyKey: field(form, "idempotency_key") || randomUUID()
  });
  if (!response.ok) return failure(response, "知识来源导入失败。");
  const runId = response.data?.pipeline_run?.id || response.data?.pipeline_run_id || "";
  revalidatePath(`/projects/${projectId}`);
  redirect(`/projects/${projectId}?tab=knowledge&knowledge_tab=processing&pipeline_run_id=${encodeURIComponent(runId)}`);
}

export async function reprocessKnowledgeSource(
  _previous: KnowledgeActionState,
  form: FormData
): Promise<KnowledgeActionState> {
  const projectId = field(form, "project_id");
  const sourceId = field(form, "source_id");
  const response = await runtimeRequest<Created>(path(projectId, `/sources/${encodeURIComponent(sourceId)}/reprocess`), {
    method: "POST",
    idempotencyKey: randomUUID()
  });
  if (!response.ok) return failure(response, "重新处理失败。");
  revalidatePath(`/projects/${projectId}`);
  return { kind: "success", message: "已创建新的知识处理任务。" };
}

export async function disableKnowledgeChunk(
  _previous: KnowledgeActionState,
  form: FormData
): Promise<KnowledgeActionState> {
  const projectId = field(form, "project_id");
  const chunkId = field(form, "chunk_id");
  const response = await runtimeRequest(path(projectId, `/chunks/${encodeURIComponent(chunkId)}/disable`), { method: "POST" });
  if (!response.ok) return failure(response, "Chunk 禁用失败。");
  revalidatePath(`/projects/${projectId}`);
  return { kind: "success", message: "Chunk 已禁用，不再进入后续事实与证据使用。" };
}

export async function reviewKnowledgeFact(
  _previous: KnowledgeActionState,
  form: FormData
): Promise<KnowledgeActionState> {
  const projectId = field(form, "project_id");
  const factId = field(form, "fact_id");
  const response = await runtimeRequest(path(projectId, `/fact-candidates/${encodeURIComponent(factId)}`), {
    method: "PATCH",
    body: { decision: field(form, "decision"), notes: field(form, "notes") }
  });
  if (!response.ok) return failure(response, "事实审核失败。");
  revalidatePath(`/projects/${projectId}`);
  return { kind: "success", message: "事实候选审核状态已更新。" };
}

export async function promoteKnowledgeFactEvidence(
  _previous: KnowledgeActionState,
  form: FormData
): Promise<KnowledgeActionState> {
  const projectId = field(form, "project_id");
  const factId = field(form, "fact_id");
  const [subjectRole, subjectEntityId = ""] = field(form, "subject_assignment").split(":", 2);
  const allowedRoles = new Set(["primary_brand", "competitor", "market", "product", "neutral"]);
  if (!projectId || !factId || !allowedRoles.has(subjectRole)) {
    return error("项目、Fact 与主体信息不能为空。", 422);
  }
  if ((subjectRole === "neutral") !== !subjectEntityId) {
    return error("中立证据不能绑定实体，其他主体角色必须绑定实体。", 422);
  }
  const response = await runtimeRequest<{ outcome: "created" | "existing" }>(
    path(projectId, `/fact-candidates/${encodeURIComponent(factId)}/evidence`),
    {
      method: "POST",
      idempotencyKey: `knowledge-fact-evidence:${projectId}:${factId}`,
      body: {
        title: field(form, "title"),
        subject_entity_id: subjectEntityId || null,
        subject_role: subjectRole,
        usage_rights: field(form, "usage_rights"),
        confidentiality: field(form, "confidentiality"),
        public_citation: {
          disclosure_allowed: form.get("disclosure_allowed") === "on",
          source_url: field(form, "source_url") || null,
          source_title: field(form, "source_title") || null,
          label: field(form, "citation_label") || null,
          quotation_allowed: form.get("quotation_allowed") === "on",
          attribution_required: form.get("attribution_required") === "on"
        }
      }
    }
  );
  if (!response.ok) return failure(response, "Fact 提升为 Evidence 失败。");
  revalidatePath(`/projects/${projectId}`);
  return {
    kind: "success",
    message: response.data?.outcome === "existing"
      ? "该 Fact 已有正式 Evidence，已返回同一条追溯链。"
      : "Fact 已提升为正式 Evidence。"
  };
}

export async function reviewKnowledgeFinding(
  _previous: KnowledgeActionState,
  form: FormData
): Promise<KnowledgeActionState> {
  const projectId = field(form, "project_id");
  const findingId = field(form, "finding_id");
  const response = await runtimeRequest(path(projectId, `/quality-findings/${encodeURIComponent(findingId)}`), {
    method: "PATCH",
    body: { decision: field(form, "decision") }
  });
  if (!response.ok) return failure(response, "质检状态更新失败。");
  revalidatePath(`/projects/${projectId}`);
  return { kind: "success", message: "质检发现已完成处置。" };
}

function path(projectId: string, suffix: string): string {
  return `/v1/projects/${encodeURIComponent(projectId)}/knowledge${suffix}`;
}

function field(form: FormData, name: string): string {
  return String(form.get(name) || "").trim();
}

function error(message: string, status?: number): KnowledgeActionState {
  return { kind: "error", message, status };
}

function failure(
  response: Extract<RuntimeResult<unknown>, { ok: false }>, fallback: string
): KnowledgeActionState {
  return {
    kind: "error",
    status: response.status,
    message: response.error || fallback,
    ...(response.problem.correlation_id ? { correlationId: response.problem.correlation_id } : {})
  };
}
