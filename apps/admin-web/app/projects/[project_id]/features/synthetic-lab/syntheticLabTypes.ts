export const syntheticChannels = [
  "owned_site",
  "amazon",
  "youtube",
  "tiktok",
  "instagram",
  "productreview",
  "reddit",
  "ozbargain",
  "quora"
] as const;

export type SyntheticChannel = (typeof syntheticChannels)[number];
export type SyntheticBoundary = Readonly<{
  synthetic: true;
  test_only: true;
  publication_eligible: false;
}>;

export type SyntheticPage<T> = SyntheticBoundary & Readonly<{
  items: T[];
  total: number;
  limit: number;
  offset: number;
}>;

export type CollectionAuthorization = SyntheticBoundary & Readonly<{
  id: string;
  project_id: string;
  channel: SyntheticChannel;
  adapter_release: string;
  version_number: number;
  state: "not_assessed" | "assessed_no_basis" | "approved" | "expired" | "revoked";
  effective_state: "not_assessed" | "assessed_no_basis" | "approved" | "expired" | "revoked";
  evidence_reference_hash: string | null;
  allowed_purposes: string[];
  max_requests_per_period: number | null;
  period_seconds: number | null;
  max_concurrency: number | null;
  expires_at: string | null;
  record_hash: string;
  replayed: boolean;
}>;

export type StyleSource = SyntheticBoundary & Readonly<{
  id: string;
  project_id: string;
  source_id: string;
  revision_number: number;
  channel: SyntheticChannel;
  access_mode: "public" | "authenticated" | "manual_import";
  locale: "en-AU";
  source_locator_hash: string;
  status: "draft" | "active" | "suspended" | "retired";
  replayed: boolean;
}>;

export type StyleProfile = SyntheticBoundary & Readonly<{
  id: string;
  project_id: string;
  profile_id: string;
  version_number: number;
  state_version: number;
  channel: SyntheticChannel;
  locale: "en-AU";
  corpus_hash: string;
  profile_hash: string;
  prompt_release_id: string;
  prompt_release_hash: string;
  approved_sample_count: number;
  status: "draft" | "in_review" | "approved" | "frozen" | "rejected" | "superseded";
  replayed: boolean;
}>;

export type ReviewSuite = SyntheticBoundary & Readonly<{
  id: string;
  project_id: string;
  suite_id: string;
  version_number: number;
  state_version: number;
  channel: SyntheticChannel;
  case_count: number;
  case_set_hash: string;
  status: "draft" | "frozen" | "retired";
  replayed: boolean;
}>;

export type ReviewCase = SyntheticBoundary & Readonly<{
  id: string;
  project_id: string;
  review_suite_version_id: string;
  review_suite_version_number: number;
  state_version: number;
  case_key: string;
  ordinal: number;
  mode: "autonomous_scenario" | "guided_scenario";
  channel: SyntheticChannel;
  competitor_scenario: boolean;
  content_hash: string;
  replayed: boolean;
}>;

export type WarningSummary = Readonly<{
  warning_count: number;
  candidate_count: number;
  warning_ratio: number;
  by_code: Readonly<Record<string, number>>;
  by_channel: Readonly<Record<string, number>>;
  by_scenario_mode: Readonly<Record<string, number>>;
  by_competitor: Readonly<Record<string, number>>;
  by_model: Readonly<Record<string, number>>;
  by_question_cluster: Readonly<Record<string, number>>;
}>;

export type SyntheticJob = SyntheticBoundary & Readonly<{
  id: string;
  project_id: string;
  kind: "style_collection" | "style_profile_build" | "candidate_generation" | "candidate_revision" | "corpus_finalize" | "offline_experiment";
  status: "queued" | "running" | "finalizing" | "retry_wait" | "succeeded" | "failed" | "dead_lettered" | "cancelled";
  version: number;
  input_hash: string;
  fencing_generation: number;
  cancel_requested: boolean;
  result_hash: string | null;
  replayed: boolean;
  warning_summary?: WarningSummary;
}>;

export type StyleCollectionAdmission = SyntheticBoundary & Readonly<{
  disposition: "accepted" | "b_track" | "rejected";
  reason_code: string;
  may_issue_network_request: boolean;
  job: SyntheticJob | null;
}>;

export type StyleLoginSecretReference = Readonly<{
  reference_id: string;
  purpose: string;
  status: "pending" | "active" | "revoked" | "inactive";
  current_version: number | null;
}>;

export type StyleLoginSecretPage = Readonly<{
  items: StyleLoginSecretReference[];
  total: number;
  limit: number;
  offset: number;
}>;

export type ManualImportResult = SyntheticBoundary & Readonly<{
  id: string;
  project_id: string;
  request_id: string;
  channel: SyntheticChannel;
  locale: "en-AU";
  row_count: number;
  accepted_count: number;
  rejected_count: number;
  duplicate_row_count: number;
  input_hash: string;
  manifest_hash: string;
  row_errors: ReadonlyArray<Readonly<{
    row_number: number;
    code: string;
    message: string;
    evidence_hash: string;
  }>>;
  replayed: boolean;
}>;

export type ManualImportPreviewSummary = SyntheticBoundary & Readonly<{
  id: string;
  project_id: string;
  style_source_revision_id: string;
  channel: SyntheticChannel;
  filename: string;
  import_format: "text" | "csv" | "jsonl";
  status: "pending" | "approved" | "rejected" | "expired";
  version: number;
  submitted_by: string;
  submitted_at: string;
  expires_at: string;
  row_count: number;
  selectable_count: number;
  blocked_count: number;
  preview_manifest_hash: string;
  replayed: boolean;
}>;

export type ManualImportPreview = ManualImportPreviewSummary & Readonly<{
  rows: ReadonlyArray<Readonly<{
    row_number: number;
    redacted_text: string;
    source_rights: "owned" | "licensed" | "public_reference" | "authorized_manual_capture";
    detected_codes: string[];
    blocking_codes: string[];
    disposition: "ready_for_review" | "blocked" | "duplicate";
    selectable: boolean;
  }>>;
}>;

export type SyntheticResourceOption = Readonly<{
  id: string;
  label: string;
  kind: "sample" | "prompt_binding" | "question_set" | "fact_snapshot" | "profile" | "review_job" | "corpus_candidate" | "corpus_approved";
  status: string;
  channel: SyntheticChannel | null;
}>;

export type SyntheticResourceInventory = SyntheticBoundary & Readonly<{
  samples: SyntheticResourceOption[];
  prompt_bindings: SyntheticResourceOption[];
  question_sets: SyntheticResourceOption[];
  fact_snapshots: SyntheticResourceOption[];
  profiles: SyntheticResourceOption[];
  review_jobs: SyntheticResourceOption[]; candidate_corpora: SyntheticResourceOption[]; approved_corpora: SyntheticResourceOption[];
}>;

export type SyntheticRuntimeOption = Readonly<{
  selection_id: string;
  manifest_id: string;
  provider: string;
  adapter_release_id: string;
  model_release_id: string;
  configured_model: string;
  capture_method: "provider_api" | "proxy_grounded_api";
  allowed_purposes: string[];
  allowed_search_modes: Array<string | null>;
}>;

export type SyntheticRuntimeOptions = Readonly<{
  current_manifest_id: string | null;
  items: SyntheticRuntimeOption[];
}>;

export type SyntheticLoadProblem = Readonly<{
  status?: number;
  detail: string;
  correlationId?: string;
}>;

export type SyntheticWorkspaceData = Readonly<{
  authorizations: SyntheticPage<CollectionAuthorization>;
  authorizationsProblem?: SyntheticLoadProblem;
  sources: SyntheticPage<StyleSource>;
  sourcesProblem?: SyntheticLoadProblem;
  importPreviews: SyntheticPage<ManualImportPreviewSummary>;
  importPreviewsProblem?: SyntheticLoadProblem;
  selectedImportPreview: ManualImportPreview | null;
  importPreviewProblem?: SyntheticLoadProblem;
  inventory: SyntheticResourceInventory;
  inventoryProblem?: SyntheticLoadProblem;
  runtimeOptions: SyntheticRuntimeOptions;
  runtimeOptionsProblem?: SyntheticLoadProblem;
  loginSecrets: StyleLoginSecretReference[];
  loginSecretsProblem?: SyntheticLoadProblem;
  profiles: SyntheticPage<StyleProfile>;
  profilesProblem?: SyntheticLoadProblem;
  suites: SyntheticPage<ReviewSuite>;
  suitesProblem?: SyntheticLoadProblem;
  selectedSuiteId: string | null;
  selectedCases: SyntheticPage<ReviewCase>;
  casesProblem?: SyntheticLoadProblem;
  selectedJob: SyntheticJob | null;
  jobProblem?: SyntheticLoadProblem;
}>;

export type SyntheticActionState = Readonly<{
  kind: "idle" | "success" | "error";
  message?: string;
  status?: number;
  correlationId?: string;
  responseToken?: string;
  nextHref?: string;
  job?: SyntheticJob;
  importResult?: ManualImportResult;
  importPreview?: ManualImportPreview;
}>;

export const initialSyntheticActionState: SyntheticActionState = { kind: "idle" };
const HASH_PATTERN = /^[0-9a-f]{64}$/;
const FORBIDDEN_FIELDS = new Set([
  "authorization",
  "authorization_header",
  "authorization_value",
  "cookie",
  "cookies",
  "credential",
  "credentials",
  "debug_trace",
  "model_response",
  "password",
  "plaintext",
  "raw_text",
  "secret",
  "secret_value",
  "session_token",
  "storage_state"
]);

export function isAuthorizationPage(value: unknown): value is SyntheticPage<CollectionAuthorization> {
  return isPage(value, isAuthorization);
}

export function isStyleSourcePage(value: unknown): value is SyntheticPage<StyleSource> {
  return isPage(value, isStyleSource);
}

export function isManualImportPreviewPage(
  value: unknown
): value is SyntheticPage<ManualImportPreviewSummary> {
  return isPage(value, isManualImportPreviewSummary);
}

export function isManualImportPreview(value: unknown): value is ManualImportPreview {
  if (!isManualImportPreviewSummary(value)) return false;
  const rows = (value as ManualImportPreviewSummary & { rows?: unknown }).rows;
  return Array.isArray(rows)
    && rows.every((row) => safeRecord(row)
      && positiveInteger(row.row_number)
      && nonEmptyString(row.redacted_text)
      && ["owned", "licensed", "public_reference", "authorized_manual_capture"].includes(String(row.source_rights))
      && stringArray(row.detected_codes)
      && stringArray(row.blocking_codes)
      && ["ready_for_review", "blocked", "duplicate"].includes(String(row.disposition))
      && typeof row.selectable === "boolean");
}

export function isSyntheticResourceInventory(value: unknown): value is SyntheticResourceInventory {
  if (!safeRecord(value) || !boundary(value)) return false;
  return [
    "samples", "prompt_bindings", "question_sets", "fact_snapshots", "profiles",
    "review_jobs", "candidate_corpora", "approved_corpora"
  ]
    .every((name) => Array.isArray(value[name]) && value[name].every(isResourceOption));
}

export function isSyntheticRuntimeOptions(value: unknown): value is SyntheticRuntimeOptions {
  return safeRecord(value)
    && (value.current_manifest_id === null || nonEmptyString(value.current_manifest_id))
    && Array.isArray(value.items)
    && value.items.every((item) => safeRecord(item)
      && ids(item, ["selection_id", "manifest_id"])
      && [item.provider, item.adapter_release_id, item.model_release_id, item.configured_model]
        .every(nonEmptyString)
      && ["provider_api", "proxy_grounded_api"].includes(String(item.capture_method))
      && stringArray(item.allowed_purposes)
      && Array.isArray(item.allowed_search_modes)
      && item.allowed_search_modes.length > 0
      && item.allowed_search_modes.every((mode) => mode === null || nonEmptyString(mode)));
}

export function isStyleProfilePage(value: unknown): value is SyntheticPage<StyleProfile> {
  return isPage(value, isStyleProfile);
}

export function isReviewSuitePage(value: unknown): value is SyntheticPage<ReviewSuite> {
  return isPage(value, isReviewSuite);
}

export function isReviewCasePage(value: unknown): value is SyntheticPage<ReviewCase> {
  return isPage(value, isReviewCase);
}

export function isAuthorization(value: unknown): value is CollectionAuthorization {
  if (!safeRecord(value) || !boundary(value)) return false;
  return ids(value, ["id", "project_id"])
    && isChannel(value.channel)
    && nonEmptyString(value.adapter_release)
    && positiveInteger(value.version_number)
    && ["not_assessed", "assessed_no_basis", "approved", "expired", "revoked"].includes(String(value.state))
    && ["not_assessed", "assessed_no_basis", "approved", "expired", "revoked"].includes(String(value.effective_state))
    && nullableHash(value.evidence_reference_hash)
    && stringArray(value.allowed_purposes)
    && nullablePositiveInteger(value.max_requests_per_period)
    && nullablePositiveInteger(value.period_seconds)
    && nullablePositiveInteger(value.max_concurrency)
    && nullableString(value.expires_at)
    && isHash(value.record_hash)
    && typeof value.replayed === "boolean";
}

export function isStyleSource(value: unknown): value is StyleSource {
  if (!safeRecord(value) || !boundary(value)) return false;
  return ids(value, ["id", "project_id", "source_id"])
    && positiveInteger(value.revision_number)
    && isChannel(value.channel)
    && ["public", "authenticated", "manual_import"].includes(String(value.access_mode))
    && value.locale === "en-AU"
    && isHash(value.source_locator_hash)
    && ["draft", "active", "suspended", "retired"].includes(String(value.status))
    && typeof value.replayed === "boolean";
}

export function isStyleProfile(value: unknown): value is StyleProfile {
  if (!safeRecord(value) || !boundary(value)) return false;
  return ids(value, ["id", "project_id", "profile_id", "prompt_release_id"])
    && positiveInteger(value.version_number)
    && positiveInteger(value.state_version)
    && isChannel(value.channel)
    && value.locale === "en-AU"
    && [value.corpus_hash, value.profile_hash, value.prompt_release_hash].every(isHash)
    && nonNegativeInteger(value.approved_sample_count)
    && ["draft", "in_review", "approved", "frozen", "rejected", "superseded"].includes(String(value.status))
    && typeof value.replayed === "boolean";
}

export function isReviewSuite(value: unknown): value is ReviewSuite {
  if (!safeRecord(value) || !boundary(value)) return false;
  return ids(value, ["id", "project_id", "suite_id"])
    && positiveInteger(value.version_number)
    && positiveInteger(value.state_version)
    && isChannel(value.channel)
    && nonNegativeInteger(value.case_count)
    && isHash(value.case_set_hash)
    && ["draft", "frozen", "retired"].includes(String(value.status))
    && typeof value.replayed === "boolean";
}

export function isReviewCase(value: unknown): value is ReviewCase {
  if (!safeRecord(value) || !boundary(value)) return false;
  return ids(value, ["id", "project_id", "review_suite_version_id"])
    && positiveInteger(value.review_suite_version_number)
    && positiveInteger(value.state_version)
    && nonEmptyString(value.case_key)
    && positiveInteger(value.ordinal)
    && ["autonomous_scenario", "guided_scenario"].includes(String(value.mode))
    && isChannel(value.channel)
    && typeof value.competitor_scenario === "boolean"
    && isHash(value.content_hash)
    && typeof value.replayed === "boolean";
}

export function isSyntheticJob(value: unknown): value is SyntheticJob {
  if (!safeRecord(value) || !boundary(value)) return false;
  return ids(value, ["id", "project_id"])
    && ["style_collection", "style_profile_build", "candidate_generation", "candidate_revision", "corpus_finalize", "offline_experiment"].includes(String(value.kind))
    && ["queued", "running", "finalizing", "retry_wait", "succeeded", "failed", "dead_lettered", "cancelled"].includes(String(value.status))
    && positiveInteger(value.version)
    && isHash(value.input_hash)
    && nonNegativeInteger(value.fencing_generation)
    && typeof value.cancel_requested === "boolean"
    && nullableHash(value.result_hash)
    && typeof value.replayed === "boolean"
    && (value.warning_summary === undefined || isWarningSummary(value.warning_summary));
}

export function isStyleCollectionAdmission(value: unknown): value is StyleCollectionAdmission {
  if (!safeRecord(value) || !boundary(value)) return false;
  const disposition = String(value.disposition);
  return ["accepted", "b_track", "rejected"].includes(disposition)
    && nonEmptyString(value.reason_code)
    && typeof value.may_issue_network_request === "boolean"
    && (value.job === null || isSyntheticJob(value.job))
    && (disposition === "accepted") === (value.job !== null && value.may_issue_network_request === true);
}

export function isStyleLoginSecretPage(value: unknown): value is StyleLoginSecretPage {
  return safeRecord(value)
    && Array.isArray(value.items)
    && value.items.every((item) => safeRecord(item)
      && nonEmptyString(item.reference_id)
      && nonEmptyString(item.purpose)
      && ["pending", "active", "revoked", "inactive"].includes(String(item.status))
      && (item.current_version === null || positiveInteger(item.current_version)))
    && nonNegativeInteger(value.total)
    && positiveInteger(value.limit)
    && nonNegativeInteger(value.offset);
}

export function isManualImportResult(value: unknown): value is ManualImportResult {
  if (!safeRecord(value) || !boundary(value)) return false;
  return ids(value, ["id", "project_id", "request_id"])
    && isChannel(value.channel)
    && value.locale === "en-AU"
    && positiveInteger(value.row_count)
    && [value.accepted_count, value.rejected_count, value.duplicate_row_count].every(nonNegativeInteger)
    && [value.input_hash, value.manifest_hash].every(isHash)
    && Array.isArray(value.row_errors)
    && value.row_errors.every((item) => safeRecord(item)
      && positiveInteger(item.row_number)
      && nonEmptyString(item.code)
      && nonEmptyString(item.message)
      && isHash(item.evidence_hash))
    && typeof value.replayed === "boolean";
}

function isManualImportPreviewSummary(value: unknown): value is ManualImportPreviewSummary {
  if (!safeRecord(value) || !boundary(value)) return false;
  return ids(value, ["id", "project_id", "style_source_revision_id", "submitted_by"])
    && isChannel(value.channel)
    && nonEmptyString(value.filename)
    && ["text", "csv", "jsonl"].includes(String(value.import_format))
    && ["pending", "approved", "rejected", "expired"].includes(String(value.status))
    && positiveInteger(value.version)
    && nonEmptyString(value.submitted_at)
    && nonEmptyString(value.expires_at)
    && positiveInteger(value.row_count)
    && nonNegativeInteger(value.selectable_count)
    && nonNegativeInteger(value.blocked_count)
    && isHash(value.preview_manifest_hash)
    && typeof value.replayed === "boolean";
}

function isResourceOption(value: unknown): value is SyntheticResourceOption {
  return safeRecord(value)
    && ids(value, ["id"])
    && nonEmptyString(value.label)
    && [
      "sample", "prompt_binding", "question_set", "fact_snapshot", "profile",
      "review_job", "corpus_candidate", "corpus_approved"
    ].includes(String(value.kind))
    && nonEmptyString(value.status)
    && (value.channel === null || isChannel(value.channel));
}

function isPage<T>(value: unknown, guard: (item: unknown) => item is T): value is SyntheticPage<T> {
  return safeRecord(value)
    && boundary(value)
    && Array.isArray(value.items)
    && value.items.every(guard)
    && nonNegativeInteger(value.total)
    && positiveInteger(value.limit)
    && nonNegativeInteger(value.offset);
}

function isWarningSummary(value: unknown): value is WarningSummary {
  if (!safeRecord(value)) return false;
  if (!nonNegativeInteger(value.warning_count) || !nonNegativeInteger(value.candidate_count)) {
    return false;
  }
  const countsConsistent = value.warning_count <= value.candidate_count
    && (value.candidate_count === 0
      ? value.warning_count === 0 && value.warning_ratio === 0
      : typeof value.warning_ratio === "number"
        && Math.abs(value.warning_ratio - value.warning_count / value.candidate_count) < 0.000001);
  return countsConsistent
    && typeof value.warning_ratio === "number"
    && value.warning_ratio >= 0
    && value.warning_ratio <= 1
    && [value.by_code, value.by_channel, value.by_scenario_mode, value.by_competitor, value.by_model, value.by_question_cluster].every(countRecord);
}

function countRecord(value: unknown): boolean {
  return safeRecord(value) && Object.values(value).every(nonNegativeInteger);
}

function safeRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  return Object.keys(value).every((key) => !FORBIDDEN_FIELDS.has(key.toLowerCase()));
}

function boundary(value: Record<string, unknown>): boolean {
  return value.synthetic === true
    && value.test_only === true
    && value.publication_eligible === false;
}

function ids(value: Record<string, unknown>, names: string[]): boolean {
  return names.every((name) => typeof value[name] === "string" && UUID_PATTERN.test(value[name]));
}

function isChannel(value: unknown): value is SyntheticChannel {
  return syntheticChannels.some((channel) => channel === value);
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(nonEmptyString);
}

function isHash(value: unknown): value is string {
  return typeof value === "string" && HASH_PATTERN.test(value);
}

function nullableHash(value: unknown): boolean {
  return value === null || isHash(value);
}

function nullableString(value: unknown): boolean {
  return value === null || nonEmptyString(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function nullablePositiveInteger(value: unknown): boolean {
  return value === null || positiveInteger(value);
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
