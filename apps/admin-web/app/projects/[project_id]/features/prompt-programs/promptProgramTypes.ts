import type { PromptBootstrapCatalog } from "./promptBootstrapTypes";

export const primaryPromptProgramKinds = [
  "generation",
  "claim_extraction",
  "conflict_check",
  "revision",
  "style_judge",
  "arbiter",
  "metric_judge",
  "recommendation"
] as const;

export const auxiliaryPromptProgramKinds = [
  "style_profile",
  "offline_answer"
] as const;

export const promptProgramKinds = [
  ...primaryPromptProgramKinds,
  ...auxiliaryPromptProgramKinds
] as const;

export type PromptProgramKind = (typeof promptProgramKinds)[number];
export type PromptReleaseStatus = "draft" | "tested" | "approved" | "frozen";

export type PromptProgramSummary = Readonly<{
  id: string;
  project_id: string;
  program_kind: PromptProgramKind | "reference_translation";
  purpose: string;
  owner_id: string;
}>;

export type PromptReleaseState = Readonly<{
  id: string;
  version: number;
  status: PromptReleaseStatus;
  acted_by: string;
  acted_at: string;
  evidence_ref: string | null;
}>;

export type PromptProgramRelease = Readonly<{
  id: string;
  project_id: string;
  program_id: string;
  program_kind: PromptProgramSummary["program_kind"];
  purpose: string;
  version: number;
  owner_id: string;
  release_hash: string;
  system_template_hash: string;
  user_template_hash: string;
  variable_schema_version: string;
  input_schema_version: string;
  output_schema_version: string;
  output_schema_hash: string;
  application_output_schema_version: string;
  application_output_schema_hash: string;
  model_policy_version: string;
  model_policy_hash: string;
  test_set_id: string;
  test_set_version: number;
  test_set_hash: string;
  compiler_version: string;
  state: PromptReleaseState;
}>;

export type PromptProgramPage = Readonly<{
  items: PromptProgramSummary[];
  total: number;
  limit: number;
  offset: number;
}>;

export type PromptReleasePage = Readonly<{
  items: PromptProgramRelease[];
  total: number;
  limit: number;
  offset: number;
}>;

export type CreatedPromptProgramResponse = Readonly<{
  program: PromptProgramSummary;
  release: PromptProgramRelease;
  replayed: boolean;
}>;

export type CreatedPromptReleaseResponse = Readonly<{
  release: PromptProgramRelease;
  replayed: boolean;
}>;

export type PromptTestJobResponse = Readonly<{
  job_id: string;
  project_id: string;
  release_id: string;
  release_hash: string;
  test_set_id: string;
  test_set_version: number;
  test_set_hash: string;
  input_hash: string;
  status: "queued" | "running" | "finalizing" | "retry_wait" | "succeeded" | "failed" | "dead_lettered" | "cancelled";
  replayed: boolean;
}>;

export type PromptTestRuntimeOption = Readonly<{
  runtime_selection_id: string;
  runtime_selection_hash: string;
  runtime_manifest_id: string;
  runtime_manifest_hash: string;
  provider: string;
  adapter_release_id: string;
  adapter_release_hash: string;
  model_release_id: string;
  model_release_hash: string;
  configured_model: string;
  capture_method: "provider_api" | "proxy_grounded_api";
  policy_version_id: string;
  policy_version_hash: string;
}>;

export type PromptTestRuntimeOptionPage = Readonly<{
  items: PromptTestRuntimeOption[];
  total: number;
}>;

export type TransitionedPromptProgramResponse = Readonly<{
  release: PromptProgramRelease;
  admitted_test_evidence_hash: string | null;
  replayed: boolean;
}>;

export type PromptProgramDiffResponse = Readonly<{
  base_release_id: string;
  base_release_hash: string;
  candidate_release_id: string;
  candidate_release_hash: string;
  changed_fields: string[];
  fixed_input_hash: string;
  base_system_hash: string;
  candidate_system_hash: string;
  base_user_hash: string;
  candidate_user_hash: string;
  replayed: boolean;
}>;

export type PromptProgramBindingResponse = Readonly<{
  id: string;
  project_id: string;
  purpose: string;
  program_kind: PromptProgramSummary["program_kind"];
  program_id: string;
  release_id: string;
  release_version: number;
  release_hash: string;
  frozen_state_id: string;
  binding_version: number;
  bound_by: string;
  bound_at: string;
  replayed: boolean;
}>;

export type PromptProgramBindingOption = Readonly<
  Omit<PromptProgramBindingResponse, "replayed">
>;

export type PromptProgramBindingOptionPage = Readonly<{
  items: PromptProgramBindingOption[];
  total: number;
  limit: number;
  offset: number;
}>;

export type PromptLoadProblem = Readonly<{
  status?: number;
  detail: string;
  correlationId?: string;
}>;

export type PromptWorkspaceData = Readonly<{
  bootstrap: PromptBootstrapCatalog | null;
  bootstrapProblem?: PromptLoadProblem;
  selectedBootstrapKind: PromptProgramKind | null;
  testRuntimes: PromptTestRuntimeOption[];
  testRuntimesProblem?: PromptLoadProblem;
  bindings: PromptProgramBindingOptionPage;
  bindingsProblem?: PromptLoadProblem;
  programs: PromptProgramPage;
  programsProblem?: PromptLoadProblem;
  releases: PromptReleasePage;
  releasesProblem?: PromptLoadProblem;
  selectedProgram: PromptProgramSummary | null;
  selectedRelease: PromptProgramRelease | null;
}>;

export type PromptActionState = Readonly<{
  kind: "idle" | "success" | "error";
  message?: string;
  status?: number;
  correlationId?: string;
  nextHref?: string;
  release?: Readonly<{
    id: string;
    version: number;
    releaseHash: string;
    status: PromptReleaseStatus;
  }>;
  job?: Readonly<{
    id: string;
    status: PromptTestJobResponse["status"];
    inputHash: string;
    testSetHash: string;
  }>;
  admittedEvidenceHash?: string;
  binding?: Readonly<{
    id: string;
    version: number;
    releaseHash: string;
  }>;
  diff?: PromptProgramDiffResponse;
}>;

export const initialPromptActionState: PromptActionState = { kind: "idle" };

export function isPromptProgramPage(value: unknown): value is PromptProgramPage {
  return record(value)
    && Array.isArray(value.items)
    && value.items.every(isPromptProgramSummary)
    && pageNumbers(value);
}

export function isPromptReleasePage(value: unknown): value is PromptReleasePage {
  return record(value)
    && Array.isArray(value.items)
    && value.items.every(isPromptProgramRelease)
    && pageNumbers(value);
}

export function isCreatedPromptProgramResponse(
  value: unknown
): value is CreatedPromptProgramResponse {
  return record(value)
    && isPromptProgramSummary(value.program)
    && isPromptProgramRelease(value.release)
    && typeof value.replayed === "boolean";
}

export function isCreatedPromptReleaseResponse(
  value: unknown
): value is CreatedPromptReleaseResponse {
  return record(value)
    && isPromptProgramRelease(value.release)
    && typeof value.replayed === "boolean";
}

export function isPromptTestJobResponse(
  value: unknown
): value is PromptTestJobResponse {
  if (!record(value)) return false;
  return [value.job_id, value.project_id, value.release_id, value.test_set_id]
    .every(nonEmptyString)
    && [value.release_hash, value.test_set_hash, value.input_hash].every(isHash)
    && positiveInteger(value.test_set_version)
    && ["queued", "running", "finalizing", "retry_wait", "succeeded", "failed", "dead_lettered", "cancelled"].includes(String(value.status))
    && typeof value.replayed === "boolean";
}

export function isPromptTestRuntimeOptionPage(
  value: unknown
): value is PromptTestRuntimeOptionPage {
  return record(value)
    && Array.isArray(value.items)
    && value.items.every(isPromptTestRuntimeOption)
    && Number.isInteger(value.total)
    && Number(value.total) >= 0
    && value.total === value.items.length;
}

function isPromptTestRuntimeOption(value: unknown): value is PromptTestRuntimeOption {
  if (!record(value)) return false;
  return [
    value.runtime_selection_id,
    value.runtime_manifest_id,
    value.policy_version_id,
    value.provider,
    value.adapter_release_id,
    value.model_release_id,
    value.configured_model
  ].every(nonEmptyString)
    && ["provider_api", "proxy_grounded_api"].includes(String(value.capture_method))
    && [
      value.runtime_selection_hash,
      value.runtime_manifest_hash,
      value.adapter_release_hash,
      value.model_release_hash,
      value.policy_version_hash
    ].every(isHash);
}

export function isTransitionedPromptProgramResponse(
  value: unknown
): value is TransitionedPromptProgramResponse {
  return record(value)
    && isPromptProgramRelease(value.release)
    && (value.admitted_test_evidence_hash === null || isHash(value.admitted_test_evidence_hash))
    && typeof value.replayed === "boolean";
}

export function isPromptProgramDiffResponse(
  value: unknown
): value is PromptProgramDiffResponse {
  if (!record(value)) return false;
  return [
    value.base_release_id,
    value.candidate_release_id
  ].every(nonEmptyString)
    && [
      value.base_release_hash,
      value.candidate_release_hash,
      value.fixed_input_hash,
      value.base_system_hash,
      value.candidate_system_hash,
      value.base_user_hash,
      value.candidate_user_hash
    ].every(isHash)
    && Array.isArray(value.changed_fields)
    && value.changed_fields.every(nonEmptyString)
    && typeof value.replayed === "boolean";
}

export function isPromptProgramBindingResponse(
  value: unknown
): value is PromptProgramBindingResponse {
  if (!record(value)) return false;
  return [
    value.id,
    value.project_id,
    value.purpose,
    value.program_id,
    value.release_id,
    value.frozen_state_id,
    value.bound_by,
    value.bound_at
  ].every(nonEmptyString)
    && isPromptProgramKind(value.program_kind)
    && positiveInteger(value.release_version)
    && positiveInteger(value.binding_version)
    && isHash(value.release_hash)
    && typeof value.replayed === "boolean";
}

export function isPromptProgramBindingOptionPage(
  value: unknown
): value is PromptProgramBindingOptionPage {
  return record(value)
    && Array.isArray(value.items)
    && value.items.every(isPromptProgramBindingOption)
    && nonNegativeInteger(value.total)
    && positiveInteger(value.limit)
    && nonNegativeInteger(value.offset)
    && value.items.length <= value.limit
    && value.offset + value.items.length <= value.total;
}

function isPromptProgramBindingOption(value: unknown): value is PromptProgramBindingOption {
  if (!record(value)) return false;
  return [
    value.id,
    value.project_id,
    value.purpose,
    value.program_id,
    value.release_id,
    value.frozen_state_id,
    value.bound_by,
    value.bound_at
  ].every(nonEmptyString)
    && isPromptProgramKind(value.program_kind)
    && positiveInteger(value.release_version)
    && positiveInteger(value.binding_version)
    && isHash(value.release_hash);
}

export function isPromptProgramSummary(value: unknown): value is PromptProgramSummary {
  return record(value)
    && [value.id, value.project_id, value.purpose, value.owner_id].every(nonEmptyString)
    && isPromptProgramKind(value.program_kind);
}

export function isPromptProgramRelease(value: unknown): value is PromptProgramRelease {
  if (!record(value) || !record(value.state)) return false;
  return [
    value.id,
    value.project_id,
    value.program_id,
    value.purpose,
    value.owner_id,
    value.variable_schema_version,
    value.input_schema_version,
    value.output_schema_version,
    value.application_output_schema_version,
    value.model_policy_version,
    value.test_set_id,
    value.test_set_hash,
    value.compiler_version
  ].every(nonEmptyString)
    && isPromptProgramKind(value.program_kind)
    && positiveInteger(value.version)
    && positiveInteger(value.test_set_version)
    && isHash(value.test_set_hash)
    && [
      value.release_hash,
      value.system_template_hash,
      value.user_template_hash,
      value.model_policy_hash,
      value.output_schema_hash,
      value.application_output_schema_hash
    ].every(isHash)
    && isPromptReleaseState(value.state);
}

function isPromptReleaseState(value: unknown): value is PromptReleaseState {
  return record(value)
    && [value.id, value.acted_by, value.acted_at].every(nonEmptyString)
    && positiveInteger(value.version)
    && ["draft", "tested", "approved", "frozen"].includes(String(value.status))
    && (value.evidence_ref === null || nonEmptyString(value.evidence_ref));
}

function isPromptProgramKind(value: unknown): value is PromptProgramSummary["program_kind"] {
  return value === "reference_translation"
    || promptProgramKinds.some((kind) => kind === value);
}

function pageNumbers(value: Record<string, unknown>): boolean {
  return nonNegativeInteger(value.total)
    && positiveInteger(value.limit)
    && nonNegativeInteger(value.offset);
}

function isHash(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function record(value: unknown): value is Record<string, unknown> {
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
