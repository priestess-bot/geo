import type {
  MetricProtocolPage,
  StatisticalProtocolPage,
  WorkflowCReportPage
} from "./workflowCControlTypes";
import type { QuestionStep, QuestionWorkspaceData } from "./questionWorkspaceData";

export const workflowViews = [
  "overview",
  "questions",
  "admission",
  "sampling",
  "protocols",
  "metrics",
  "comparisons",
  "drift",
  "reports",
  "alerts"
] as const;

export type WorkflowView = (typeof workflowViews)[number];
export type CaptureMethod = "provider_api" | "proxy_grounded_api" | "manual_ui" | "automated_ui";
export type EvidenceStatus = "complete" | "ineligible";
export type EvidenceConclusion =
  | "win"
  | "equivalent"
  | "loss"
  | "inconclusive"
  | "insufficient_evidence";
export type AdmissionPolicyStatus =
  | "draft"
  | "pending_review"
  | "approved"
  | "assessed_no_basis"
  | "revoked";
export type AuthorizationState =
  | "approved"
  | "not_assessed"
  | "assessed_no_basis"
  | "expired"
  | "revoked";

export type LoadProblem = Readonly<{
  status?: number;
  detail: string;
  correlationId?: string;
}>;

export type Resource<T> = Readonly<{
  data: T | null;
  problem?: LoadProblem;
}>;

export type BrowserCaptureSurface =
  | "google_ai_overviews"
  | "google_ai_mode"
  | "bing_copilot";

export type BrowserCaptureReadinessItem = Readonly<{
  surface: BrowserCaptureSurface;
  state: "blocked" | "ready" | "live_verified" | "fidelity_accepted";
  blocking_reasons: string[];
  surface_release_id: string | null;
  release_version: string | null;
  profile_version_id: string | null;
  egress_endpoint_id: string | null;
  captured_count: number;
}>;

export type BrowserCaptureReadiness = Readonly<{
  items: BrowserCaptureReadinessItem[];
}>;

export type BrowserCaptureInventory = Readonly<{
  egress_endpoints: Array<Readonly<{
    id: string;
    name: string;
    endpoint_host: string;
    endpoint_port: number;
    network_type: string;
    status: string;
  }>>;
  egress_tests: Array<Readonly<{
    id: string;
    endpoint_id: string;
    status: string;
    eligible?: boolean;
    outcome?: string;
    error_class?: string;
  }>>;
  profiles: Array<Readonly<{
    id: string;
    version: string;
    account_cohort: string;
    status: string;
  }>>;
}>;

export type SamplingSourceStratum = Readonly<{
  platform: string;
  surface: string;
  configured_model: string;
  reported_model: string;
  capture_method: CaptureMethod;
  adapter_release: string;
  locale: string;
  region: string;
  language: string;
  search_mode: string;
  account_cohort: string;
  egress_policy_category: string;
  location_control: "country" | "market_language" | "language_only" | "not_controlled";
  location_evidence_hash: string;
  requested_country: string | null;
  requested_region: string | null;
  requested_locale: string;
  requested_language: string;
  effective_country: string | null;
  effective_region: string | null;
  effective_locale: string | null;
  effective_language: string | null;
  stratum_hash: string;
}>;

export type SamplingSuite = Readonly<{
  id: string;
  project_id: string;
  question_set_id: string;
  question_set_version: string;
  question_set_hash: string;
  adapter_release_id: string;
  adapter_release_hash: string;
  model_release_id: string;
  model_release_hash: string;
  route_policy_id: string;
  route_policy_hash: string;
  runtime_manifest_id: string;
  runtime_manifest_hash: string;
  runtime_option_id: string;
  runtime_option_hash: string;
  admission_policy_id: string;
  admission_policy_hash: string;
  questions: Array<Readonly<{
    question_id: string;
    question_version: string;
    text_hash: string;
  }>>;
  question_set_item_ids: string[];
  source_stratum: SamplingSourceStratum;
  repetitions: number;
  statistics_method_version: string;
  minimum_valid_repeats: number;
  planned_task_count: number;
  frozen_by: string;
  frozen_at: string;
  suite_hash: string;
}>;

export type SamplingRun = Readonly<{
  id: string;
  project_id: string;
  suite_id: string;
  suite_hash: string;
  admission_policy_id: string;
  admission_policy_hash: string;
  admission_grant_hash: string;
  purpose: string;
  authorization_reference: string;
  authorization_valid_until: string;
  admission_policy_version: string;
  reserved_task_count: number;
  planned_task_keys: string[];
  status: "planned" | "running" | "completed";
  admitted_not_before: string;
  created_at: string;
  version: number;
}>;

export type AdmissionPolicy = Readonly<{
  id: string;
  project_id: string;
  revision: number;
  supersedes_policy_id: string | null;
  platform: string;
  capture_method: CaptureMethod;
  adapter_release: string;
  location_control: SamplingSourceStratum["location_control"];
  location_evidence_hash: string;
  authorization_reference: string;
  authorized_purposes: string[];
  valid_until: string;
  quota_remaining: number;
  daily_task_limit: number;
  minimum_request_interval_seconds: number;
  max_concurrency: number;
  next_allowed_at: string;
  status: AdmissionPolicyStatus;
  effective_authorization_state: AuthorizationState;
  definition_hash: string;
  policy_version: string;
  created_by: string;
  created_at: string;
  submitted_by: string | null;
  submitted_at: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_reason: string | null;
  revoked_by: string | null;
  revoked_at: string | null;
  revocation_reason: string | null;
  aggregate_version: number;
}>;

export type AdmissionPolicyPage = Readonly<{
  items: AdmissionPolicy[];
  total: number;
}>;

export type AdmissionRuntimeOption = Readonly<{
  option_key: string;
  display_name: string;
  platform: string;
  capture_method: CaptureMethod;
  adapter_release: string;
  location_control: SamplingSourceStratum["location_control"];
  location_evidence_hash: string;
  authorization_reference: string;
  allowed_purposes: string[];
}>;

export type AdmissionRuntimeOptionPage = Readonly<{
  items: AdmissionRuntimeOption[];
  total: number;
}>;

export type SamplingSuiteInputOption = Readonly<{
  option_key: string;
  display_name: string;
  question_set_id: string;
  question_set_version: string;
  question_set_hash: string;
  question_count: number;
  question_set_item_ids: string[];
  admission_policy_id: string;
  admission_policy_hash: string;
  source_stratum: SamplingSourceStratum;
}>;

export type SamplingSuiteInputOptionPage = Readonly<{
  items: SamplingSuiteInputOption[];
  total: number;
}>;

export type SamplingSuitePage = Readonly<{ items: SamplingSuite[]; total: number }>;
export type SamplingRunPage = Readonly<{ items: SamplingRun[]; total: number }>;

export type SamplingTask = Readonly<{
  id: string;
  project_id: string;
  run_id: string;
  task_key: string;
  question_id: string;
  question_version: string;
  repetition: number;
  capture_method: CaptureMethod;
  source_stratum_hash: string;
  status: string;
  attempt_ids: string[];
  max_attempts: number;
  version: number;
}>;

export type SamplingAttempt = Readonly<{
  id: string;
  project_id: string;
  run_id: string;
  task_id: string;
  task_key: string;
  ordinal: number;
  job_status: string;
  record_version: number;
  attempt_count: number;
  provider_response_id: string | null;
  egress_verification_id: string | null;
  raw_artifact_hash: string | null;
  actual_location: SamplingActualLocation | null;
  terminal_status: string | null;
}>;

export type SamplingActualLocation = Readonly<{
  location_control: SamplingSourceStratum["location_control"];
  location_evidence_hash: string;
  requested_country: string | null;
  requested_region: string | null;
  requested_locale: string;
  requested_language: string;
  effective_country: string | null;
  effective_region: string | null;
  effective_locale: string | null;
  effective_language: string | null;
}>;

export type ObservationEvidence = Readonly<{
  raw_manifest_hash: string;
  derived_manifest_hash: string;
  derived_content_hash: string;
  governance_policy_hash: string;
  derived_summary: string;
  evidence_locator: string;
  provider_response_id: string | null;
  egress_verification_id: string | null;
  result_parameters_hash: string;
}>;

export type SamplingObservation = Readonly<{
  id: string;
  project_id: string;
  run_id: string;
  task_id: string;
  task_key: string;
  winning_attempt_id: string;
  source_stratum_hash: string;
  actual_location: SamplingActualLocation | null;
  evidence_status: EvidenceStatus;
  ineligible_reasons: string[];
  evidence: ObservationEvidence;
  observed_at: string;
  observation_hash: string;
}>;

export type SamplingAssessment = Readonly<{
  run_id: string;
  planned_task_count: number;
  valid_task_count: number;
  invalid_task_count: number;
  missing_task_count: number;
  valid_completion_ratio: string;
  sufficient_question_count: number;
  question_count: number;
  status: "complete" | "insufficient_evidence";
  denominator_hash: string;
}>;

export type SamplingRunDetail = Readonly<{
  run: SamplingRun;
  suite: SamplingSuite;
  tasks: SamplingTask[];
  attempts: SamplingAttempt[];
  observations: SamplingObservation[];
  assessment: SamplingAssessment;
}>;

export type ManualEvidenceImport = Readonly<{
  id: string;
  project_id: string;
  run_id: string;
  task_id: string;
  task_key: string;
  attempt_id: string;
  expected_task_version: number;
  artifact_manifest_id: string;
  artifact_manifest_hash: string;
  artifact_content_hash: string;
  governance_policy_hash: string;
  capture_session_id: string;
  evidence_kind: "screenshot" | "html_export" | "transcript_export";
  device: "desktop" | "mobile" | "tablet";
  locale: string;
  captured_at: string;
  submitted_by: string;
  submitted_at: string;
  status: "pending_review" | "approved" | "rejected" | "committed";
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_reason: string | null;
  committed_at: string | null;
  aggregate_version: number;
  definition_hash: string;
  surface_parse: SurfaceParseSummary | null;
}>;

export type ManualEvidenceImportPage = Readonly<{
  items: ManualEvidenceImport[];
  total: number;
}>;

export type SurfaceParserRelease = Readonly<{
  id: string;
  release_key: string;
  release_version: string;
  release_hash: string;
  platform: string;
  surface: "google_ai_overviews" | "google_ai_mode" | "bing_copilot";
  artifact_schema_version: string;
  parser_engine_version: string;
  status: "candidate" | "fixture_ready";
  automated_capture_eligible: false;
  evidence_scope: "fixture_or_manual_non_live";
}>;

export type SurfaceParserReleasePage = Readonly<{
  items: SurfaceParserRelease[];
  total: number;
}>;

export type SurfaceParseSummary = Readonly<{
  parser_release_id: string;
  parser_release_hash: string;
  platform: string;
  surface: SurfaceParserRelease["surface"];
  capture_kind: "manual_ui";
  outcome: "captured" | "surface_not_present" | "consent_required"
    | "login_required" | "access_blocked" | "geo_mismatch"
    | "egress_changed" | "parser_failed" | "timeout";
  block_reason: string | null;
  content_eligible: boolean;
  automated_capture: false;
  live_capture_eligible: false;
  answer_text_hash: string | null;
  answer_character_count: number;
  citation_count: number;
  citation_set_hash: string;
  locator_set_hash: string;
  parser_result_hash: string;
  summary_hash: string;
}>;

export type EvidenceLocator = Readonly<{
  kind: "answer_span" | "citation" | "fact";
  reference_id: string;
  version: string | null;
  content_hash: string | null;
  start: number | null;
  end: number | null;
  redacted_quote_hash: string | null;
}>;

export type SemanticMetricResult = Readonly<{
  metric_key: string;
  metric_version: string;
  value_kind: string;
  numerator: string;
  denominator: number;
  estimate: string;
  interval: Readonly<{ method: string; confidence_level: string | null; low: string; high: string }>;
  valid_input_count: number;
  invalid_input_count: number;
  missing_input_count: number;
  status: "complete" | "insufficient_evidence";
  judge_version: string | null;
  judge_version_hash: string | null;
  rule_versions_hash: string;
  evidence_locators: EvidenceLocator[];
  breakdown: Record<string, string>;
  result_hash: string;
}>;

export type SemanticMetricSnapshot = Readonly<{
  project_id: string;
  input_set_hash: string;
  suite_hash: string;
  stratum_hash: string;
  results: SemanticMetricResult[];
  performance: Readonly<{
    questions: Array<Readonly<{ question_id: string; question_cluster: string; score: string; planned_slot_count: number }>>;
    clusters: Array<Readonly<{ question_cluster: string; score: string; planned_slot_count: number }>>;
    worst_question_id: string;
    worst_question_score: string;
    worst_cluster: string;
    worst_cluster_score: string;
    negative_gain: null | Readonly<{
      compared_question_count: number;
      affected_question_count: number;
      mean_negative_gain: string;
      range_low: string;
      range_high: string;
      worst_question_id: string | null;
      worst_question_delta: string | null;
    }>;
  }>;
  computed_at: string;
  snapshot_hash: string;
}>;

export type SemanticMetricSnapshotPage = Readonly<{
  items: SemanticMetricSnapshot[];
  total: number;
}>;

export type ComparisonResult = Readonly<{
  comparison_id: string;
  family: string;
  protocol_frozen_hash: string;
  input_hash: string;
  stratum_hash: string;
  valid_pair_count: number;
  planned_pair_count: number;
  completion_ratio: string;
  point_estimate: string;
  raw_interval: Readonly<{ method: string; alpha: string; low: string; high: string }>;
  adjusted_interval: Readonly<{ method: string; alpha: string; low: string; high: string }>;
  raw_p_value: string;
  adjusted_p_value: string;
  a_priori_design_power: string;
  power_plan_hash: string;
  power_method_version: string;
  conclusion: EvidenceConclusion;
  result_hash: string;
}>;

export type ComparisonFamily = Readonly<{
  project_id: string;
  family: string;
  alpha: string;
  correction_method: string;
  results: ComparisonResult[];
  family_hash: string;
}>;

export type ComparisonFamilyPage = Readonly<{ items: ComparisonFamily[]; total: number }>;

export type DriftReport = Readonly<{
  project_id: string;
  model_drift: Array<Record<string, unknown>>;
  source_drift: Array<Record<string, unknown>>;
  effect_drift: Array<Record<string, unknown>>;
  unmatched_baseline_strata: string[];
  unmatched_current_strata: string[];
  baseline_input_hash: string;
  current_input_hash: string;
  method_version: string;
  report_hash: string;
}>;

export type DriftReportPage = Readonly<{ items: DriftReport[]; total: number }>;

export type AlertDisposition = Readonly<{
  disposition: string;
  from_status: string;
  to_status: string;
  actor_id: string;
  occurred_at: string;
  reason: string;
  command_key: string;
  resulting_version: number;
  suppressed_until: string | null;
  command_hash: string;
}>;

export type AlertRecord = Readonly<{
  id: string;
  project_id: string;
  rule: Readonly<{ id: string; rule_key: string; version: number; kind: string; severity: string; parameters: Record<string, unknown>; frozen_by: string; frozen_at: string }>;
  rule_hash: string;
  scope: Readonly<{ resource_kind: string; resource_key: string; dimensions: Record<string, string> }>;
  trigger_values: Record<string, unknown>;
  trigger_snapshot_hash: string;
  evidence: Array<Readonly<{ kind: string; resource_id: string; version: string; sha256: string; locator: string | null }>>;
  severity: "info" | "warning" | "critical";
  dedupe_key: string;
  status: "open" | "acknowledged" | "suppressed" | "resolved";
  opened_at: string;
  updated_at: string;
  version: number;
  dispositions: AlertDisposition[];
  suppressed_until: string | null;
  suppression_reason: string | null;
  replayed: boolean;
}>;

export type NotificationProjection = Readonly<{
  id: string;
  project_id: string;
  alert_id: string;
  alert_version: number;
  channel: "admin_inbox" | "local_smtp" | "internal_webhook";
  topic: string;
  idempotency_key: string;
  created_at: string;
  payload_hash: string;
  summary: Record<string, unknown>;
}>;

export type AlertPage = Readonly<{ items: AlertRecord[]; total: number }>;
export type { WorkflowCWorkspaceData } from "./workflowCWorkspaceTypes";
export type WorkflowCActionState = Readonly<{
  kind: "idle" | "success" | "error";
  message?: string;
  status?: number;
  correlationId?: string;
  alert?: Readonly<{ id: string; status: AlertRecord["status"]; version: number }>;
  policy?: Readonly<{
    id: string;
    status: AdmissionPolicyStatus;
    version: number;
  }>;
}>;

export const initialWorkflowCActionState: WorkflowCActionState = { kind: "idle" };
