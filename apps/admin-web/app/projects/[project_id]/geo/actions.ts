"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest } from "../../../runtime";

function value(formData: FormData, key: string): string {
  return String(formData.get(key) || "").trim();
}

function lines(formData: FormData, key: string): string[] {
  return value(formData, key).split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean);
}

function refresh(projectId: string): void {
  revalidatePath(`/projects/${projectId}/geo`);
}

export async function createGeoProduct(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const response = await runtimeRequest("/v1/geo/products", {
    method: "POST",
    body: {
      project_id: projectId,
      name: value(formData, "name"),
      canonical_url: value(formData, "canonical_url"),
      category: value(formData, "category"),
      market_code: value(formData, "market_code") || "AU",
      facts: { source_url: value(formData, "canonical_url"), summary: value(formData, "facts") }
    }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function createGeoCampaign(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const response = await runtimeRequest("/v1/geo/campaigns", {
    method: "POST",
    body: {
      project_id: projectId,
      product_id: value(formData, "product_id"),
      name: value(formData, "name"),
      market_code: value(formData, "market_code") || "AU",
      forbidden_claims: lines(formData, "forbidden_claims")
    }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function createGeoQuery(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const campaignId = value(formData, "campaign_id");
  const response = await runtimeRequest(`/v1/geo/campaigns/${encodeURIComponent(campaignId)}/queries`, {
    method: "POST",
    body: { project_id: projectId, query_text: value(formData, "query_text"), platform: value(formData, "platform"), device: "desktop", sample_size: 3 }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function approveGeoQuery(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const queryId = value(formData, "query_id");
  const response = await runtimeRequest(`/v1/geo/campaigns/queries/${encodeURIComponent(queryId)}/approve`, { method: "POST", query: { project_id: projectId } });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function importGeoObservation(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const response = await runtimeRequest("/v1/geo/observations/manual-imports", {
    method: "POST",
    body: {
      project_id: projectId,
      campaign_query_id: value(formData, "campaign_query_id"),
      observation_phase: value(formData, "observation_phase") || "baseline",
      sample_index: Number(value(formData, "sample_index") || 1),
      raw_answer: value(formData, "raw_answer"),
      citations: lines(formData, "citation_urls").map((url) => ({ url })),
      artifact_url: value(formData, "artifact_url") || null,
      visible_model: value(formData, "visible_model") || null
    }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function createGeoDestination(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const response = await runtimeRequest("/v1/geo/destinations", {
    method: "POST",
    body: {
      project_id: projectId, publisher_id: value(formData, "publisher_id"), name: value(formData, "name"),
      destination_url: value(formData, "destination_url"), task_type: value(formData, "task_type"),
      task_key: value(formData, "task_key"), ownership_kind: value(formData, "ownership_kind"),
      operation_mode: "manual_submission", public_disclosure_required: true,
      policy_snapshot: { notes: value(formData, "policy_notes"), requires_disclosure: true, automated_posting: "prohibited" }
    }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function reviewGeoPublisher(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const response = await runtimeRequest(`/v1/geo/publishers/${encodeURIComponent(value(formData, "publisher_id"))}/review`, {
    method: "POST",
    body: { project_id: projectId, status: value(formData, "status"), policy_snapshot: {
      reviewed_rules: value(formData, "reviewed_rules"), identity_requirement: value(formData, "identity_requirement"), automated_posting: "prohibited"
    } }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function qualifyGeoDestination(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const destinationId = value(formData, "destination_id");
  const response = await runtimeRequest(`/v1/geo/destinations/${encodeURIComponent(destinationId)}/qualify`, { method: "POST", query: { project_id: projectId } });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function createGeoOpportunity(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const response = await runtimeRequest("/v1/geo/placement-opportunities", {
    method: "POST",
    body: {
      project_id: projectId, campaign_id: value(formData, "campaign_id"), destination_id: value(formData, "destination_id"),
      campaign_query_id: value(formData, "campaign_query_id") || null, title: value(formData, "title"),
      rationale: value(formData, "rationale"), priority: value(formData, "priority") || "medium"
    }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function createGeoPromptTemplate(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const response = await runtimeRequest("/v1/geo/prompt-templates", {
    method: "POST", body: { project_id: projectId, task_key: value(formData, "task_key"), name: value(formData, "name") }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function createGeoPromptVersion(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const templateId = value(formData, "template_id");
  const response = await runtimeRequest(`/v1/geo/prompt-templates/${encodeURIComponent(templateId)}/versions`, {
    method: "POST",
    body: { project_id: projectId, version_number: 1, system_template: value(formData, "system_template"), user_template: value(formData, "user_template"), output_schema: { content_markdown: "publication-ready text only", claims: [{ text: "factual claim", evidence_ids: ["approved evidence id"] }] }, status: "draft" }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function publishGeoPromptTemplate(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const response = await runtimeRequest(`/v1/geo/prompt-templates/${encodeURIComponent(value(formData, "template_id"))}/publish`, { method: "POST", query: { project_id: projectId } });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function generateGeoPackage(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const opportunityId = value(formData, "opportunity_id");
  const response = await runtimeRequest(`/v1/geo/placement-opportunities/${encodeURIComponent(opportunityId)}/packages`, {
    method: "POST",
    body: {
      project_id: projectId, prompt_template_version_id: value(formData, "prompt_template_version_id"), generate_with_model: true, model: "deepseek-chat",
      idempotency_key: value(formData, "idempotency_key"),
      title: value(formData, "title") || null, disclosure_text: value(formData, "disclosure_text"), forbidden_claims: lines(formData, "forbidden_claims"),
      evidence: [{ source_url: value(formData, "evidence_url"), text: value(formData, "evidence_text"), source_kind: value(formData, "source_kind"),
        usage_rights: value(formData, "usage_rights"), subject: value(formData, "subject"), subject_role: value(formData, "subject_role"), public_disclosure_allowed: true }]
    }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function submitGeoPackageReview(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const response = await runtimeRequest(`/v1/geo/placement-packages/${encodeURIComponent(value(formData, "package_id"))}/submit-review`, { method: "POST", query: { project_id: projectId } });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function reviewGeoPackage(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const response = await runtimeRequest(`/v1/geo/placement-packages/${encodeURIComponent(value(formData, "package_id"))}/review`, {
    method: "POST",
    body: {
      project_id: projectId,
      decision: value(formData, "decision"),
      claim_inventory_complete: formData.get("claim_inventory_complete") === "on"
      ,qc_score: Number(value(formData, "qc_score") || 0), review_notes: value(formData, "review_notes")
    }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function reviseGeoPackage(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  let claimInventory: unknown;
  try {
    claimInventory = JSON.parse(value(formData, "claim_inventory") || "[]");
  } catch {
    return { error: "Claim Inventory 必须是有效 JSON" };
  }
  if (!Array.isArray(claimInventory) || claimInventory.length === 0) return { error: "Claim Inventory 必须是非空数组" };
  const response = await runtimeRequest(`/v1/geo/placement-packages/${encodeURIComponent(value(formData, "package_id"))}/versions`, {
    method: "POST",
    body: {
      project_id: projectId, base_content_hash: value(formData, "base_content_hash"), rendered_text: value(formData, "rendered_text"),
      reason: value(formData, "reason"), claim_inventory: claimInventory
    }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function createGeoSubmission(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const response = await runtimeRequest(`/v1/geo/placement-packages/${encodeURIComponent(value(formData, "package_id"))}/submissions`, {
    method: "POST", body: { project_id: projectId, submission_evidence_url: value(formData, "submission_evidence_url") || null, external_reference: value(formData, "external_reference") || null, notes: value(formData, "notes") }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function setGeoPublishedUrl(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const response = await runtimeRequest(`/v1/geo/submissions/${encodeURIComponent(value(formData, "submission_id"))}/published-url`, {
    method: "POST", body: { project_id: projectId, published_url: value(formData, "published_url") }
  });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}

export async function verifyGeoPublishedUrl(_previousState: { error?: string }, formData: FormData): Promise<{ error?: string }> {
  const projectId = value(formData, "project_id");
  const response = await runtimeRequest(`/v1/geo/submissions/${encodeURIComponent(value(formData, "submission_id"))}/verify-live`, { method: "POST", query: { project_id: projectId } });
  if (!response.ok) return { error: response.error };
  refresh(projectId);
  return {};
}
