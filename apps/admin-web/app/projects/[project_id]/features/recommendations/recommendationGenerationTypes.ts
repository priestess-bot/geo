export type RecommendationGenerationJob = Readonly<{
  id: string;
  project_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "rejected_stale_input";
  version: number;
  input_hash: string;
  evidence_input_hash: string;
  consumed_model_calls: number;
  maximum_model_calls: number;
  cancel_requested: boolean;
  error_code: string | null;
  valid_until: string;
  prompt: Readonly<{
    binding_id: string;
    binding_version: number;
    release_id: string;
    release_hash: string;
  }>;
  model: Readonly<{
    runtime_selection_id: string;
    runtime_manifest_id: string;
    runtime_manifest_hash: string;
    runtime_option_id: string;
    runtime_option_hash: string;
    provider: string;
    adapter_release_id: string;
    adapter_release_hash: string;
    model_release_id: string;
    model_release_hash: string;
    configured_model: string;
  }>;
  replayed: boolean;
}>;

export type RecommendationPromptBindingOption = Readonly<{
  id: string;
  project_id: string;
  purpose: string;
  program_kind: "recommendation" | "arbiter";
  program_id: string;
  release_id: string;
  release_version: number;
  release_hash: string;
  frozen_state_id: string;
  binding_version: number;
  bound_by: string;
  bound_at: string;
}>;

export type RecommendationPromptBindingPage = Readonly<{
  items: RecommendationPromptBindingOption[];
  total: number;
  limit: number;
  offset: number;
}>;

export type RecommendationModelRuntimeOption = Readonly<{
  selection_id: string;
  manifest_id: string;
  provider: string;
  adapter_release_id: string;
  model_release_id: string;
  configured_model: string;
  capture_method: string;
  allowed_purposes: string[];
  allowed_search_modes: Array<string | null>;
}>;

export type RecommendationModelRuntimeOptions = Readonly<{
  items: RecommendationModelRuntimeOption[];
  current_manifest_id: string | null;
}>;

export type RecommendationGenerationCatalog = Readonly<{
  recommendationPrompts: RecommendationPromptBindingOption[];
  arbiterPrompts: RecommendationPromptBindingOption[];
  runtimes: RecommendationModelRuntimeOption[];
  recommendationPromptProblem?: string;
  arbiterPromptProblem?: string;
  runtimeProblem?: string;
}>;

export type RecommendationGenerationActionState = Readonly<{
  kind: "idle" | "success" | "error";
  message?: string;
  status?: number;
  correlationId?: string;
  job?: RecommendationGenerationJob;
}>;

export const initialGenerationActionState: RecommendationGenerationActionState = {
  kind: "idle"
};

export function isRecommendationGenerationJob(
  value: unknown
): value is RecommendationGenerationJob {
  if (!record(value) || !record(value.prompt) || !record(value.model)) return false;
  return [value.id, value.project_id, value.input_hash, value.evidence_input_hash]
      .every(nonEmptyString)
    && [value.input_hash, value.evidence_input_hash].every(hash)
    && ["queued", "running", "succeeded", "failed", "cancelled", "rejected_stale_input"]
      .includes(String(value.status))
    && positiveInteger(value.version)
    && typeof value.cancel_requested === "boolean"
    && typeof value.replayed === "boolean"
    && [value.prompt.binding_id, value.prompt.release_id, value.prompt.release_hash]
      .every(nonEmptyString)
    && [
      value.model.runtime_selection_id,
      value.model.runtime_manifest_id,
      value.model.runtime_option_id,
      value.model.provider,
      value.model.adapter_release_id,
      value.model.model_release_id
    ].every(nonEmptyString)
    && [value.model.runtime_manifest_hash, value.model.runtime_option_hash].every(hash);
}

export function isRecommendationPromptBindingPage(
  value: unknown
): value is RecommendationPromptBindingPage {
  return record(value)
    && Array.isArray(value.items)
    && value.items.every(isRecommendationPromptBindingOption)
    && nonNegativeInteger(value.total)
    && positiveInteger(value.limit)
    && nonNegativeInteger(value.offset);
}

export function isRecommendationModelRuntimeOptions(
  value: unknown
): value is RecommendationModelRuntimeOptions {
  return record(value)
    && Array.isArray(value.items)
    && value.items.every(isRecommendationModelRuntimeOption)
    && (value.current_manifest_id === null || nonEmptyString(value.current_manifest_id));
}

function isRecommendationPromptBindingOption(
  value: unknown
): value is RecommendationPromptBindingOption {
  if (!record(value)) return false;
  return [
    value.id,
    value.project_id,
    value.purpose,
    value.program_id,
    value.release_id,
    value.release_hash,
    value.frozen_state_id,
    value.bound_by,
    value.bound_at
  ].every(nonEmptyString)
    && ["recommendation", "arbiter"].includes(String(value.program_kind))
    && positiveInteger(value.release_version)
    && positiveInteger(value.binding_version)
    && hash(value.release_hash);
}

function isRecommendationModelRuntimeOption(
  value: unknown
): value is RecommendationModelRuntimeOption {
  if (!record(value)) return false;
  return [
    value.selection_id,
    value.manifest_id,
    value.provider,
    value.adapter_release_id,
    value.model_release_id,
    value.configured_model,
    value.capture_method
  ].every(nonEmptyString)
    && Array.isArray(value.allowed_purposes)
    && value.allowed_purposes.every(nonEmptyString)
    && Array.isArray(value.allowed_search_modes)
    && value.allowed_search_modes.length > 0
    && value.allowed_search_modes.every((item) => item === null || nonEmptyString(item));
}

function record(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function hash(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}
