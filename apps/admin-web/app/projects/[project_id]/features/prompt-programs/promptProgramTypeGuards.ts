import { difyWorkflowPurposes, promptProgramKinds } from "./promptProgramKinds";
import type {
  CompiledPrompt,
  CreatedPromptProgramResponse,
  CreatedPromptReleaseResponse,
  DifyWorkflowRuntimeCard,
  DifyWorkflowRuntimePage,
  PromptContextSlot,
  PromptFlow,
  PromptFlowPage,
  PromptProgramBindingOption,
  PromptProgramBindingOptionPage,
  PromptProgramBindingResponse,
  PromptProgramDiffResponse,
  PromptProgramPage,
  PromptProgramRelease,
  PromptProgramReleaseDetail,
  PromptProgramSummary,
  PromptReleasePage,
  PromptReleaseState,
  PromptRenderPreview,
  PromptTestJobResponse,
  PromptTestRun,
  PromptTestRunPage,
  PromptTestRuntimeOption,
  PromptTestRuntimeOptionPage,
  PromptWorkingDraft,
  TransitionedPromptProgramResponse
} from "./promptProgramTypes";

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

export function isPromptFlowPage(value: unknown): value is PromptFlowPage {
  return record(value)
    && Array.isArray(value.items)
    && value.items.every(isPromptFlow)
    && nonNegativeInteger(value.total)
    && value.total === value.items.length;
}

export function isDifyWorkflowRuntimePage(
  value: unknown
): value is DifyWorkflowRuntimePage {
  return record(value)
    && ["native", "dify"].includes(String(value.runtime_backend))
    && Array.isArray(value.items)
    && value.items.every(isDifyWorkflowRuntimeCard)
    && nonNegativeInteger(value.total)
    && value.total === value.items.length;
}

export function isPromptWorkingDraft(value: unknown): value is PromptWorkingDraft {
  if (!record(value)) return false;
  return [
    value.project_id,
    value.program_id,
    value.display_name,
    value.system_template,
    value.user_template,
    value.base_release_id,
    value.updated_by,
    value.updated_at
  ].every(nonEmptyString)
    && positiveInteger(value.revision)
    && isHash(value.draft_hash)
    && (value.candidate_release_id === null || nonEmptyString(value.candidate_release_id));
}

export function isPromptProgramReleaseDetail(
  value: unknown
): value is PromptProgramReleaseDetail {
  if (!record(value)
    || !nonEmptyString(value.system_template)
    || !nonEmptyString(value.user_template)) return false;
  return isPromptProgramRelease(value);
}

export function isPromptRenderPreview(value: unknown): value is PromptRenderPreview {
  return record(value)
    && [value.fixture_id, value.fixture_label].every(nonEmptyString)
    && record(value.input_value)
    && isCompiledPrompt(value.draft)
    && (value.current === null || isCompiledPrompt(value.current))
    && (value.current_release_version === null || positiveInteger(value.current_release_version));
}

export function isPromptTestRunPage(value: unknown): value is PromptTestRunPage {
  return record(value)
    && Array.isArray(value.items)
    && value.items.every(isPromptTestRun)
    && nonNegativeInteger(value.total)
    && value.total === value.items.length;
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
    && ["draft", "tested", "approved", "frozen", "retired"].includes(String(value.status))
    && (value.evidence_ref === null || nonEmptyString(value.evidence_ref));
}

function isPromptFlow(value: unknown): value is PromptFlow {
  if (!record(value)) return false;
  return [value.flow_key, value.purpose, value.display_name, value.description].every(nonEmptyString)
    && isPromptProgramKind(value.program_kind)
    && ["synthetic_lab", "question_and_content", "measurement_and_recommendation"].includes(String(value.group))
    && typeof value.configurable === "boolean"
    && Array.isArray(value.context_slots)
    && value.context_slots.every(isPromptContextSlot)
    && (value.program === null || isPromptProgramSummary(value.program))
    && (value.draft === null || isPromptWorkingDraft(value.draft))
    && (value.latest_release_version === null || positiveInteger(value.latest_release_version))
    && (value.current_release_id === null || nonEmptyString(value.current_release_id))
    && (value.current_release_version === null || positiveInteger(value.current_release_version))
    && (value.candidate_status === null || ["draft", "tested", "approved", "frozen", "retired"].includes(String(value.candidate_status)))
    && (value.latest_test_job_id === null || nonEmptyString(value.latest_test_job_id))
    && (value.latest_test_status === null || nonEmptyString(value.latest_test_status))
    && (value.latest_test_score === null || nonNegativeInteger(value.latest_test_score));
}

function isPromptContextSlot(value: unknown): value is PromptContextSlot {
  return record(value)
    && [value.key, value.label, value.description, value.insertion].every(nonEmptyString)
    && value.source === "runtime_task";
}

function isDifyWorkflowRuntimeCard(value: unknown): value is DifyWorkflowRuntimeCard {
  if (!record(value)) return false;
  const nullableStrings = [
    value.release_id,
    value.release_hash,
    value.prompt_program_id,
    value.prompt_release_id,
    value.prompt_release_hash,
    value.prompt_system_template,
    value.prompt_user_template,
    value.dify_app_id,
    value.dify_workflow_id,
    value.dsl_hash,
    value.configured_model,
    value.model_provider,
    value.activated_at,
    value.last_attempt_status,
    value.last_attempt_kind,
    value.last_attempt_at,
    value.last_error_code,
    value.last_error_message,
    value.console_url,
    value.published_workflow_hash,
    value.published_snapshot_hash,
    value.published_at,
    value.observed_at,
    value.sync_error
  ];
  return difyWorkflowPurposes.includes(
    String(value.purpose) as typeof difyWorkflowPurposes[number]
  )
    && ["native", "dify"].includes(String(value.backend))
    && [
      "not_configured",
      "active",
      "blocked_secret",
      "blocked_prompt_retired",
      "stale_prompt"
    ].includes(String(value.activation_status))
    && nullableStrings.every((item) => item === null || typeof item === "string")
    && [value.published_prompt_nodes, value.published_input_variables, value.published_graph_nodes]
      .every(Array.isArray)
    && ["not_observed", "cached", "current", "unreachable"].includes(
      String(value.sync_status)
    )
    && [value.release_version, value.binding_version].every(
      (item) => item === null || positiveInteger(item)
    );
}

function isCompiledPrompt(value: unknown): value is CompiledPrompt {
  return record(value)
    && [value.system_prompt, value.user_prompt].every(nonEmptyString)
    && [value.system_prompt_hash, value.user_prompt_hash].every(isHash);
}

function isPromptTestRun(value: unknown): value is PromptTestRun {
  if (!record(value)) return false;
  return [
    value.job_id,
    value.project_id,
    value.program_id,
    value.release_id,
    value.status,
    value.requested_at
  ].every(nonEmptyString)
    && positiveInteger(value.release_version)
    && (value.finished_at === null || nonEmptyString(value.finished_at))
    && (value.passed === null || typeof value.passed === "boolean")
    && (value.score === null || nonNegativeInteger(value.score))
    && (value.result_ref === null || nonEmptyString(value.result_ref))
    && (value.error_code === null || nonEmptyString(value.error_code));
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
