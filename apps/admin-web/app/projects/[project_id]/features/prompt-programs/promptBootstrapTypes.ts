import {
  isPromptProgramRelease,
  isPromptProgramSummary,
  promptProgramKinds,
  type PromptProgramKind,
  type PromptProgramRelease,
  type PromptProgramSummary
} from "./promptProgramTypes";

export const bootstrapScenarios = [
  "positive",
  "negative",
  "prompt_injection",
  "subject_mixup",
  "fabricated_citation"
] as const;

export type BootstrapScenario = (typeof bootstrapScenarios)[number];

export type BootstrapRubricCriterion = Readonly<{
  code: string;
  description: string;
  weight: number;
  blocking: boolean;
}>;

export type BootstrapFixture = Readonly<{
  fixture_id: string;
  scenario: BootstrapScenario;
  description: string;
  input_value: Record<string, unknown>;
}>;

export type PromptBootstrapKindPreview = Readonly<{
  program_kind: PromptProgramKind;
  purpose: string;
  spec_version: string;
  spec_hash: string;
  test_set_id: string;
  test_set_version: number;
  test_set_hash: string;
  variable_schema_version: string;
  variable_schema: Record<string, unknown>;
  input_schema_version: string;
  input_schema: Record<string, unknown>;
  output_schema_version: string;
  output_schema: Record<string, unknown>;
  output_schema_hash: string;
  application_output_schema_version: string;
  application_output_schema: Record<string, unknown>;
  application_output_schema_hash: string;
  model_policy_version: string;
  model_policy: Record<string, unknown>;
  model_policy_hash: string;
  application_rules: string[];
  rubric: BootstrapRubricCriterion[];
  minimum_score: number;
  fixtures: BootstrapFixture[];
}>;

export type PromptBootstrapCatalog = Readonly<{
  catalog_version: string;
  catalog_hash: string;
  items: PromptBootstrapKindPreview[];
  external_model_calls: 0;
  automatic_transitions: false;
  batch_atomicity: "per_item";
  action_boundary: "draft_only_manual_test";
}>;

export type BootstrapCaseEvaluation = Readonly<{
  fixture_id: string;
  scenario: BootstrapScenario;
  output_hash: string;
  score: number;
  passed: boolean;
  error_code: string | null;
  failed_criteria: string[];
  blocking_failure: boolean;
}>;

export type PromptBootstrapEvaluation = Readonly<{
  catalog_hash: string;
  program_kind: PromptProgramKind;
  spec_hash: string;
  test_set_id: string;
  test_set_hash: string;
  rubric: BootstrapRubricCriterion[];
  minimum_score: number;
  case_results: BootstrapCaseEvaluation[];
  score: number;
  passed: boolean;
  result_hash: string;
  external_model_calls: 0;
  automatic_transitions: false;
}>;

export type BootstrapDraftFailure = Readonly<{
  code: "idempotency_conflict" | "version_conflict" | "persistence_unavailable"
    | "forbidden" | "not_found" | "rule_violation" | "application_unavailable";
  detail: string;
  retryable: boolean;
}>;

export type BootstrapDraftItem = Readonly<{
  program_kind: PromptProgramKind;
  spec_hash: string;
  test_set_hash: string;
  idempotency_key_hash: string;
  status: "created" | "replayed" | "failed";
  program: PromptProgramSummary | null;
  release: PromptProgramRelease | null;
  failure: BootstrapDraftFailure | null;
}>;

export type PromptBootstrapDraftBatch = Readonly<{
  catalog_hash: string;
  completion_status: "completed" | "partial_failure" | "failed";
  items: BootstrapDraftItem[];
  created_count: number;
  replayed_count: number;
  failed_count: number;
  atomic: false;
  safe_to_retry: true;
  action_boundary: "draft_only_no_approval_freeze_binding";
}>;

export type PromptBootstrapActionState = Readonly<{
  kind: "idle" | "success" | "error";
  message?: string;
  status?: number;
  correlationId?: string;
  batch?: PromptBootstrapDraftBatch;
}>;

export type PromptBootstrapEvaluationState = Readonly<{
  kind: "idle" | "success" | "error";
  message?: string;
  status?: number;
  correlationId?: string;
  evaluation?: PromptBootstrapEvaluation;
}>;

export const initialBootstrapActionState: PromptBootstrapActionState = { kind: "idle" };
export const initialBootstrapEvaluationState: PromptBootstrapEvaluationState = { kind: "idle" };

export function isPromptBootstrapCatalog(value: unknown): value is PromptBootstrapCatalog {
  if (!record(value) || !Array.isArray(value.items) || value.items.length !== promptProgramKinds.length) return false;
  const kinds = value.items.map((item) => record(item) ? item.program_kind : null);
  return nonEmptyString(value.catalog_version)
    && hash(value.catalog_hash)
    && value.items.every(isKindPreview)
    && promptProgramKinds.every((kind, index) => kinds[index] === kind)
    && value.external_model_calls === 0
    && value.automatic_transitions === false
    && value.batch_atomicity === "per_item"
    && value.action_boundary === "draft_only_manual_test";
}

export function isPromptBootstrapEvaluation(value: unknown): value is PromptBootstrapEvaluation {
  return record(value)
    && hash(value.catalog_hash)
    && promptProgramKinds.some((kind) => kind === value.program_kind)
    && hash(value.spec_hash)
    && nonEmptyString(value.test_set_id)
    && hash(value.test_set_hash)
    && Array.isArray(value.rubric)
    && value.rubric.every(isRubric)
    && boundedScore(value.minimum_score, 1)
    && Array.isArray(value.case_results)
    && value.case_results.length === 5
    && value.case_results.every(isCaseEvaluation)
    && boundedScore(value.score, 0)
    && typeof value.passed === "boolean"
    && hash(value.result_hash)
    && value.external_model_calls === 0
    && value.automatic_transitions === false;
}

export function isPromptBootstrapDraftBatch(value: unknown): value is PromptBootstrapDraftBatch {
  if (!record(value) || !Array.isArray(value.items) || value.items.length !== promptProgramKinds.length) return false;
  if (!value.items.every(isDraftItem)) return false;
  if (!promptProgramKinds.every((kind, index) => value.items[index].program_kind === kind)) return false;
  const created = value.items.filter((item) => item.status === "created").length;
  const replayed = value.items.filter((item) => item.status === "replayed").length;
  const failed = value.items.filter((item) => item.status === "failed").length;
  return hash(value.catalog_hash)
    && ["completed", "partial_failure", "failed"].includes(String(value.completion_status))
    && value.created_count === created
    && value.replayed_count === replayed
    && value.failed_count === failed
    && created + replayed + failed === promptProgramKinds.length
    && value.atomic === false
    && value.safe_to_retry === true
    && value.action_boundary === "draft_only_no_approval_freeze_binding";
}

function isKindPreview(value: unknown): value is PromptBootstrapKindPreview {
  if (!record(value)) return false;
  return promptProgramKinds.some((kind) => kind === value.program_kind)
    && [value.purpose, value.spec_version, value.test_set_id,
      value.variable_schema_version, value.input_schema_version,
      value.output_schema_version, value.application_output_schema_version,
      value.model_policy_version].every(nonEmptyString)
    && [value.spec_hash, value.test_set_hash, value.output_schema_hash,
      value.application_output_schema_hash, value.model_policy_hash].every(hash)
    && positiveInteger(value.test_set_version)
    && record(value.variable_schema)
    && record(value.input_schema)
    && record(value.output_schema)
    && record(value.application_output_schema)
    && record(value.model_policy)
    && stringArray(value.application_rules, true)
    && Array.isArray(value.rubric)
    && value.rubric.length > 0
    && value.rubric.every(isRubric)
    && value.rubric.reduce((sum, item) => sum + Number(item.weight), 0) === 100
    && boundedScore(value.minimum_score, 1)
    && Array.isArray(value.fixtures)
    && value.fixtures.length === 5
    && value.fixtures.every(isFixture)
    && bootstrapScenarios.every((scenario) => value.fixtures.some(
      (item: BootstrapFixture) => item.scenario === scenario
    ));
}

function isRubric(value: unknown): value is BootstrapRubricCriterion {
  return record(value)
    && nonEmptyString(value.code)
    && nonEmptyString(value.description)
    && boundedScore(value.weight, 1)
    && typeof value.blocking === "boolean";
}

function isFixture(value: unknown): value is BootstrapFixture {
  return record(value)
    && nonEmptyString(value.fixture_id)
    && bootstrapScenarios.some((scenario) => scenario === value.scenario)
    && nonEmptyString(value.description)
    && record(value.input_value);
}

function isCaseEvaluation(value: unknown): value is BootstrapCaseEvaluation {
  return record(value)
    && nonEmptyString(value.fixture_id)
    && bootstrapScenarios.some((scenario) => scenario === value.scenario)
    && hash(value.output_hash)
    && boundedScore(value.score, 0)
    && typeof value.passed === "boolean"
    && (value.error_code === null || nonEmptyString(value.error_code))
    && stringArray(value.failed_criteria)
    && typeof value.blocking_failure === "boolean";
}

function isDraftItem(value: unknown): value is BootstrapDraftItem {
  if (!record(value)) return false;
  const statusValid = ["created", "replayed", "failed"].includes(String(value.status));
  const shared = promptProgramKinds.some((kind) => kind === value.program_kind)
    && [value.spec_hash, value.test_set_hash, value.idempotency_key_hash].every(hash)
    && statusValid;
  if (!shared) return false;
  if (value.status === "failed") {
    return value.program === null && value.release === null && isDraftFailure(value.failure);
  }
  return isPromptProgramSummary(value.program)
    && isPromptProgramRelease(value.release)
    && value.program.program_kind === value.program_kind
    && value.release.program_kind === value.program_kind
    && value.release.program_id === value.program.id
    && value.release.project_id === value.program.project_id
    && value.release.state.status === "draft"
    && value.failure === null;
}

function isDraftFailure(value: unknown): value is BootstrapDraftFailure {
  return record(value)
    && ["idempotency_conflict", "version_conflict", "persistence_unavailable", "forbidden",
      "not_found", "rule_violation", "application_unavailable"].includes(String(value.code))
    && nonEmptyString(value.detail)
    && typeof value.retryable === "boolean";
}

function record(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function hash(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function boundedScore(value: unknown, minimum: number): value is number {
  return typeof value === "number" && value >= minimum && value <= 100;
}

function stringArray(value: unknown, required = false): value is string[] {
  return Array.isArray(value)
    && (!required || value.length > 0)
    && value.every(nonEmptyString);
}
