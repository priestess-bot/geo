import type { PromptBootstrapCatalog } from "./promptBootstrapTypes";
import { difyWorkflowPurposes, promptProgramKinds } from "./promptProgramKinds";

export {
  auxiliaryPromptProgramKinds,
  difyManagedPromptProgramKinds,
  difyWorkflowPurposes,
  nativeReviewPromptProgramKinds,
  primaryPromptProgramKinds,
  promptProgramKinds,
  reservedPromptProgramKinds,
  workflowPromptProgramKinds
} from "./promptProgramKinds";

export type PromptProgramKind = (typeof promptProgramKinds)[number];
export type PromptReleaseStatus = "draft" | "tested" | "approved" | "frozen" | "retired";

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

export type PromptProgramReleaseDetail = PromptProgramRelease & Readonly<{
  system_template: string;
  user_template: string;
}>;

export type PromptContextSlot = Readonly<{
  key: string;
  label: string;
  description: string;
  insertion: string;
  source: "runtime_task";
}>;

export type PromptWorkingDraft = Readonly<{
  project_id: string;
  program_id: string;
  display_name: string;
  system_template: string;
  user_template: string;
  revision: number;
  draft_hash: string;
  base_release_id: string;
  candidate_release_id: string | null;
  updated_by: string;
  updated_at: string;
}>;

export type PromptFlow = Readonly<{
  flow_key: string;
  purpose: string;
  program_kind: PromptProgramSummary["program_kind"];
  group: "synthetic_lab" | "question_and_content" | "measurement_and_recommendation";
  display_name: string;
  description: string;
  configurable: boolean;
  context_slots: PromptContextSlot[];
  program: PromptProgramSummary | null;
  draft: PromptWorkingDraft | null;
  latest_release_version: number | null;
  current_release_id: string | null;
  current_release_version: number | null;
  candidate_status: PromptReleaseStatus | null;
  latest_test_job_id: string | null;
  latest_test_status: string | null;
  latest_test_score: number | null;
}>;

export type PromptFlowPage = Readonly<{
  items: PromptFlow[];
  total: number;
}>;

export type CompiledPrompt = Readonly<{
  system_prompt: string;
  user_prompt: string;
  system_prompt_hash: string;
  user_prompt_hash: string;
}>;

export type PromptRenderPreview = Readonly<{
  fixture_id: string;
  fixture_label: string;
  input_value: Record<string, unknown>;
  draft: CompiledPrompt;
  current: CompiledPrompt | null;
  current_release_version: number | null;
}>;

export type PromptTestRun = Readonly<{
  job_id: string;
  project_id: string;
  program_id: string;
  release_id: string;
  release_version: number;
  status: string;
  requested_at: string;
  finished_at: string | null;
  passed: boolean | null;
  score: number | null;
  result_ref: string | null;
  error_code: string | null;
}>;

export type PromptTestRunPage = Readonly<{
  items: PromptTestRun[];
  total: number;
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

export type DifyWorkflowRuntimeCard = Readonly<{
  purpose: typeof difyWorkflowPurposes[number];
  backend: "native" | "dify";
  activation_status:
    | "not_configured"
    | "active"
    | "blocked_secret"
    | "blocked_prompt_retired"
    | "stale_prompt";
  release_id: string | null;
  release_version: number | null;
  release_hash: string | null;
  prompt_program_id: string | null;
  prompt_release_id: string | null;
  prompt_release_hash: string | null;
  prompt_system_template: string | null;
  prompt_user_template: string | null;
  dify_app_id: string | null;
  dify_workflow_id: string | null;
  dsl_hash: string | null;
  configured_model: string | null;
  model_provider: string | null;
  binding_version: number | null;
  activated_at: string | null;
  last_attempt_status: string | null;
  last_attempt_kind: string | null;
  last_attempt_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  console_url: string | null;
  published_workflow_hash: string | null;
  published_snapshot_hash: string | null;
  published_prompt_nodes: ReadonlyArray<Readonly<{
    node_id: string;
    title: string;
    model_provider: string;
    model_name: string;
    model_mode: string;
    completion_params: Record<string, unknown>;
    messages: ReadonlyArray<Readonly<{ role: string; text: string }>>;
  }>>;
  published_input_variables: ReadonlyArray<Readonly<{
    name: string;
    label: string;
    type: string;
    required: boolean;
    description: string;
  }>>;
  published_graph_nodes: ReadonlyArray<Readonly<{
    node_id: string;
    type: string;
    title: string;
  }>>;
  published_at: string | null;
  observed_at: string | null;
  sync_status: "not_observed" | "cached" | "current" | "drifted" | "unreachable";
  sync_error: string | null;
}>;

export type DifyWorkflowRuntimePage = Readonly<{
  runtime_backend: "native" | "dify";
  items: DifyWorkflowRuntimeCard[];
  total: number;
}>;

export type PromptWorkspaceData = Readonly<{
  flows: PromptFlowPage;
  flowsProblem?: PromptLoadProblem;
  selectedFlow: PromptFlow | null;
  selectedReleaseDetail: PromptProgramReleaseDetail | null;
  testRuns: PromptTestRunPage;
  testRunsProblem?: PromptLoadProblem;
  bootstrap: PromptBootstrapCatalog | null;
  bootstrapProblem?: PromptLoadProblem;
  selectedBootstrapKind: PromptProgramKind | null;
  testRuntimes: PromptTestRuntimeOption[];
  testRuntimesProblem?: PromptLoadProblem;
  workflowRuntimes: DifyWorkflowRuntimePage;
  workflowRuntimesProblem?: PromptLoadProblem;
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

export {
  isCreatedPromptProgramResponse,
  isCreatedPromptReleaseResponse,
  isDifyWorkflowRuntimePage,
  isPromptFlowPage,
  isPromptProgramBindingOptionPage,
  isPromptProgramBindingResponse,
  isPromptProgramDiffResponse,
  isPromptProgramPage,
  isPromptProgramRelease,
  isPromptProgramReleaseDetail,
  isPromptProgramSummary,
  isPromptReleasePage,
  isPromptRenderPreview,
  isPromptTestJobResponse,
  isPromptTestRunPage,
  isPromptTestRuntimeOptionPage,
  isPromptWorkingDraft,
  isTransitionedPromptProgramResponse
} from "./promptProgramTypeGuards";
