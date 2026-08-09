import type {
  AdmissionPolicy,
  AdmissionPolicyPage,
  AdmissionRuntimeOptionPage,
  AlertPage,
  AlertRecord,
  BrowserCaptureInventory,
  BrowserCaptureReadiness,
  ComparisonFamily,
  ComparisonFamilyPage,
  DriftReport,
  DriftReportPage,
  ManualEvidenceImportPage,
  NotificationProjection,
  SamplingRunDetail,
  SamplingRunPage,
  SamplingSuite,
  SamplingSuiteInputOptionPage,
  SamplingSuitePage,
  SemanticMetricSnapshot,
  SemanticMetricSnapshotPage,
  SurfaceParserReleasePage
} from "./workflowCTypes";

const captureMethods = new Set([
  "provider_api",
  "proxy_grounded_api",
  "manual_ui",
  "automated_ui"
]);
const conclusions = new Set([
  "win",
  "equivalent",
  "loss",
  "inconclusive",
  "insufficient_evidence"
]);
const alertStatuses = new Set(["open", "acknowledged", "suppressed", "resolved"]);
const admissionStatuses = new Set([
  "draft",
  "pending_review",
  "approved",
  "assessed_no_basis",
  "revoked"
]);
const authorizationStates = new Set([
  "approved",
  "not_assessed",
  "assessed_no_basis",
  "expired",
  "revoked"
]);
const consumerSurfaces = new Set([
  "google_ai_overviews",
  "google_ai_mode",
  "bing_copilot"
]);
const surfaceParseOutcomes = new Set([
  "captured",
  "surface_not_present",
  "consent_required",
  "login_required",
  "access_blocked",
  "geo_mismatch",
  "egress_changed",
  "parser_failed",
  "timeout"
]);
const surfaceBlockReasons = new Set([
  "consent",
  "login",
  "captcha",
  "rate_limit",
  "ban",
  "geo_mismatch",
  "egress_changed",
  "timeout",
  "selector_drift",
  "page_incomplete",
  "invalid_artifact",
  "wrong_surface"
]);
const outcomeBySurfaceBlockReason = new Map([
  ["consent", "consent_required"],
  ["login", "login_required"],
  ["captcha", "access_blocked"],
  ["rate_limit", "access_blocked"],
  ["ban", "access_blocked"],
  ["geo_mismatch", "geo_mismatch"],
  ["egress_changed", "egress_changed"],
  ["timeout", "timeout"],
  ["selector_drift", "parser_failed"],
  ["page_incomplete", "parser_failed"],
  ["invalid_artifact", "parser_failed"],
  ["wrong_surface", "parser_failed"]
]);

export function isBrowserCaptureReadiness(
  value: unknown
): value is BrowserCaptureReadiness {
  return record(value) && Array.isArray(value.items) && value.items.every((item) =>
    record(item)
    && consumerSurfaces.has(String(item.surface))
    && ["blocked", "ready", "live_verified", "fidelity_accepted"].includes(
      String(item.state)
    )
    && Array.isArray(item.blocking_reasons)
    && item.blocking_reasons.every((reason) => typeof reason === "string")
    && integer(item.captured_count)
  );
}

export function isBrowserCaptureInventory(
  value: unknown
): value is BrowserCaptureInventory {
  return record(value)
    && Array.isArray(value.egress_endpoints)
    && value.egress_endpoints.every((item) =>
      record(item) && uuid(item.id) && strings(item, ["name", "endpoint_host", "status"])
      && integer(item.endpoint_port)
    )
    && Array.isArray(value.egress_tests)
    && value.egress_tests.every((item) =>
      record(item) && uuid(item.id) && uuid(item.endpoint_id) && typeof item.status === "string"
    )
    && Array.isArray(value.profiles)
    && value.profiles.every((item) =>
      record(item) && uuid(item.id) && strings(item, ["version", "account_cohort", "status"])
    );
}

export function isAdmissionPolicyPage(value: unknown): value is AdmissionPolicyPage {
  return record(value)
    && integer(value.total)
    && Array.isArray(value.items)
    && value.items.every(isAdmissionPolicy);
}

export function isAdmissionPolicy(value: unknown): value is AdmissionPolicy {
  return record(value)
    && uuid(value.id)
    && uuid(value.project_id)
    && captureMethods.has(String(value.capture_method))
    && admissionStatuses.has(String(value.status))
    && authorizationStates.has(String(value.effective_authorization_state))
    && strings(value, [
      "platform",
      "adapter_release",
      "location_control",
      "location_evidence_hash",
      "authorization_reference",
      "valid_until",
      "definition_hash",
      "policy_version",
      "created_by",
      "created_at"
    ])
    && integer(value.revision)
    && integer(value.aggregate_version)
    && Array.isArray(value.authorized_purposes)
    && value.authorized_purposes.every((item) => typeof item === "string");
}

export function isAdmissionRuntimeOptionPage(
  value: unknown
): value is AdmissionRuntimeOptionPage {
  return record(value) && integer(value.total) && Array.isArray(value.items)
    && value.items.every((item) => record(item)
      && strings(item, [
        "option_key",
        "display_name",
        "platform",
        "adapter_release",
        "location_control",
        "location_evidence_hash",
        "authorization_reference"
      ])
      && captureMethods.has(String(item.capture_method))
      && Array.isArray(item.allowed_purposes)
      && item.allowed_purposes.every((purpose) => typeof purpose === "string"));
}

export function isSamplingSuite(value: unknown): value is SamplingSuite {
  if (!record(value) || !uuid(value.id) || !uuid(value.project_id)) return false;
  const source = value.source_stratum;
  return record(source)
    && captureMethods.has(String(source.capture_method))
    && strings(source, ["platform", "surface", "configured_model", "reported_model", "adapter_release", "locale", "region", "stratum_hash", "location_control", "location_evidence_hash", "requested_locale", "requested_language"])
    && Array.isArray(value.questions)
    && value.questions.every((item) => record(item) && strings(item, ["question_id", "question_version", "text_hash"]))
    && Array.isArray(value.question_set_item_ids)
    && value.question_set_item_ids.length === value.questions.length
    && value.question_set_item_ids.every((item) => typeof item === "string" && item.length > 0)
    && integer(value.repetitions)
    && integer(value.minimum_valid_repeats)
    && integer(value.planned_task_count)
    && typeof value.suite_hash === "string";
}

export function isSamplingSuitePage(value: unknown): value is SamplingSuitePage {
  return record(value) && integer(value.total) && Array.isArray(value.items)
    && value.items.every(isSamplingSuite);
}

export function isSamplingSuiteInputOptionPage(
  value: unknown
): value is SamplingSuiteInputOptionPage {
  return record(value) && integer(value.total) && Array.isArray(value.items)
    && value.items.every((item) => record(item)
      && strings(item, [
        "option_key",
        "display_name",
        "question_set_id",
        "question_set_version",
        "question_set_hash",
        "admission_policy_hash"
      ])
      && uuid(item.admission_policy_id)
      && integer(item.question_count)
      && Array.isArray(item.question_set_item_ids)
      && item.question_set_item_ids.length === item.question_count
      && item.question_set_item_ids.every((questionId) => typeof questionId === "string" && questionId.length > 0)
      && record(item.source_stratum)
      && captureMethods.has(String(item.source_stratum.capture_method)));
}

export function isSamplingRunPage(value: unknown): value is SamplingRunPage {
  return record(value) && integer(value.total) && Array.isArray(value.items)
    && value.items.every((item) => record(item)
      && uuid(item.id)
      && uuid(item.suite_id)
      && uuid(item.admission_policy_id)
      && strings(item, ["suite_hash", "admission_policy_hash", "status", "created_at"]));
}

export function isSamplingRunDetail(value: unknown): value is SamplingRunDetail {
  if (!record(value) || !isSamplingSuite(value.suite) || !record(value.run)) return false;
  const run = value.run;
  if (!uuid(run.id) || run.suite_id !== value.suite.id || !Array.isArray(run.planned_task_keys)) {
    return false;
  }
  if (!uuid(run.admission_policy_id)
    || !strings(run, [
      "admission_policy_hash",
      "admission_policy_version",
      "authorization_valid_until"
    ])) return false;
  if (!Array.isArray(value.tasks) || !value.tasks.every((item) => {
    return record(item)
      && uuid(item.id)
      && item.run_id === run.id
      && captureMethods.has(String(item.capture_method))
      && typeof item.task_key === "string"
      && typeof item.status === "string"
      && Array.isArray(item.attempt_ids)
      && item.attempt_ids.every(uuid);
  })) return false;
  if (!Array.isArray(value.attempts) || !value.attempts.every((item) => {
    return record(item)
      && uuid(item.id)
      && item.run_id === run.id
      && !["lease_token", "lease_owner", "lease_expires_at", "fencing_generation"].some((key) => key in item)
      && typeof item.job_status === "string";
  })) return false;
  if (!Array.isArray(value.observations) || !value.observations.every((item) => {
    if (!record(item) || !record(item.evidence)) return false;
    const evidence = item.evidence;
    return uuid(item.id)
      && item.run_id === run.id
      && (item.evidence_status === "complete" || item.evidence_status === "ineligible")
      && !["answer_text", "raw_artifact_uri", "manifest_reference"].some((key) => key in evidence)
      && strings(evidence, ["raw_manifest_hash", "derived_manifest_hash", "derived_content_hash", "governance_policy_hash", "derived_summary", "evidence_locator", "result_parameters_hash"])
      && typeof item.observation_hash === "string";
  })) return false;
  const assessment = value.assessment;
  return record(assessment)
    && assessment.run_id === run.id
    && integer(assessment.planned_task_count)
    && integer(assessment.valid_task_count)
    && integer(assessment.invalid_task_count)
    && integer(assessment.missing_task_count)
    && (assessment.status === "complete" || assessment.status === "insufficient_evidence");
}

export function isManualEvidenceImportPage(value: unknown): value is ManualEvidenceImportPage {
  return record(value) && integer(value.total) && Array.isArray(value.items)
    && value.items.every((item) => record(item)
      && uuid(item.id)
      && uuid(item.project_id)
      && uuid(item.run_id)
      && uuid(item.task_id)
      && uuid(item.artifact_manifest_id)
      && uuid(item.capture_session_id)
      && strings(item, [
        "task_key",
        "artifact_manifest_hash",
        "artifact_content_hash",
        "governance_policy_hash",
        "evidence_kind",
        "device",
        "locale",
        "captured_at",
        "submitted_by",
        "submitted_at",
        "status",
        "definition_hash"
      ])
      && integer(item.aggregate_version)
      && (item.surface_parse === null || isSurfaceParseSummary(item.surface_parse)));
}

export function isSurfaceParserReleasePage(
  value: unknown
): value is SurfaceParserReleasePage {
  return record(value)
    && integer(value.total)
    && Array.isArray(value.items)
    && value.items.every((item) => record(item)
      && uuid(item.id)
      && strings(item, [
        "release_key",
        "release_version",
        "release_hash",
        "platform",
        "surface",
        "artifact_schema_version",
        "parser_engine_version",
        "status",
        "evidence_scope"
      ])
      && sha256(item.release_hash)
      && consumerSurfaces.has(String(item.surface))
      && (item.status === "candidate" || item.status === "fixture_ready")
      && item.automated_capture_eligible === false
      && item.evidence_scope === "fixture_or_manual_non_live");
}

export function isSemanticMetricSnapshot(value: unknown): value is SemanticMetricSnapshot {
  if (!record(value) || !uuid(value.project_id) || !Array.isArray(value.results)) return false;
  if (!strings(value, ["input_set_hash", "suite_hash", "stratum_hash", "snapshot_hash", "computed_at"])) {
    return false;
  }
  if (!value.results.every((item) => {
    return record(item)
      && strings(item, ["metric_key", "metric_version", "estimate", "result_hash"])
      && integer(item.denominator)
      && integer(item.valid_input_count)
      && integer(item.invalid_input_count)
      && integer(item.missing_input_count)
      && (item.status === "complete" || item.status === "insufficient_evidence")
      && Array.isArray(item.evidence_locators);
  })) return false;
  const performance = value.performance;
  return record(performance)
    && strings(performance, ["worst_question_id", "worst_question_score", "worst_cluster", "worst_cluster_score"])
    && Array.isArray(performance.questions)
    && Array.isArray(performance.clusters);
}

export function isSemanticMetricSnapshotPage(
  value: unknown
): value is SemanticMetricSnapshotPage {
  return record(value) && integer(value.total) && Array.isArray(value.items)
    && value.items.every(isSemanticMetricSnapshot);
}

export function isComparisonFamily(value: unknown): value is ComparisonFamily {
  return record(value)
    && uuid(value.project_id)
    && strings(value, ["family", "alpha", "correction_method", "family_hash"])
    && Array.isArray(value.results)
    && value.results.every((item) => {
      return record(item)
        && strings(item, ["comparison_id", "completion_ratio", "point_estimate", "result_hash"])
        && conclusions.has(String(item.conclusion))
        && integer(item.valid_pair_count)
        && integer(item.planned_pair_count)
        && record(item.adjusted_interval)
        && strings(item.adjusted_interval, ["low", "high"]);
    });
}

export function isComparisonFamilyPage(value: unknown): value is ComparisonFamilyPage {
  return record(value) && integer(value.total) && Array.isArray(value.items)
    && value.items.every(isComparisonFamily);
}

export function isDriftReport(value: unknown): value is DriftReport {
  return record(value)
    && uuid(value.project_id)
    && strings(value, ["baseline_input_hash", "current_input_hash", "method_version", "report_hash"])
    && arrays(value, ["model_drift", "source_drift", "effect_drift", "unmatched_baseline_strata", "unmatched_current_strata"]);
}

export function isDriftReportPage(value: unknown): value is DriftReportPage {
  return record(value) && integer(value.total) && Array.isArray(value.items)
    && value.items.every(isDriftReport);
}

export function isAlertPage(value: unknown): value is AlertPage {
  return record(value)
    && integer(value.total)
    && Array.isArray(value.items)
    && value.items.every(isAlertRecord);
}

export function isAlertRecord(value: unknown): value is AlertRecord {
  return record(value)
    && uuid(value.id)
    && uuid(value.project_id)
    && alertStatuses.has(String(value.status))
    && (value.severity === "info" || value.severity === "warning" || value.severity === "critical")
    && integer(value.version)
    && record(value.rule)
    && strings(value.rule, ["rule_key", "kind", "severity"])
    && record(value.scope)
    && strings(value.scope, ["resource_kind", "resource_key"])
    && Array.isArray(value.dispositions)
    && Array.isArray(value.evidence);
}

export function isNotificationPage(value: unknown): value is NotificationProjection[] {
  return Array.isArray(value) && value.every((item) => {
    return record(item)
      && uuid(item.id)
      && uuid(item.alert_id)
      && (item.channel === "admin_inbox" || item.channel === "local_smtp" || item.channel === "internal_webhook")
      && strings(item, ["topic", "idempotency_key", "payload_hash", "created_at"])
      && record(item.summary);
  });
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function uuid(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f-]{36}$/i.test(value);
}

function integer(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isSurfaceParseSummary(value: unknown): boolean {
  if (!record(value)) return false;
  const forbidden = [
    "answer_text",
    "answer_blocks",
    "citations",
    "citation_urls",
    "final_url",
    "raw_artifact_uri"
  ];
  return forbidden.every((key) => !(key in value))
    && uuid(value.parser_release_id)
    && strings(value, [
      "parser_release_hash",
      "platform",
      "surface",
      "capture_kind",
      "outcome",
      "citation_set_hash",
      "locator_set_hash",
      "parser_result_hash",
      "summary_hash"
    ])
    && consumerSurfaces.has(String(value.surface))
    && value.capture_kind === "manual_ui"
    && surfaceParseOutcomes.has(String(value.outcome))
    && (value.block_reason === null || surfaceBlockReasons.has(String(value.block_reason)))
    && typeof value.content_eligible === "boolean"
    && value.automated_capture === false
    && value.live_capture_eligible === false
    && (value.answer_text_hash === null || sha256(value.answer_text_hash))
    && integer(value.answer_character_count)
    && integer(value.citation_count)
    && [
      value.parser_release_hash,
      value.citation_set_hash,
      value.locator_set_hash,
      value.parser_result_hash,
      value.summary_hash
    ].every(sha256)
    && surfaceSummaryStateIsConsistent(value);
}

function surfaceSummaryStateIsConsistent(value: Record<string, unknown>): boolean {
  if (value.outcome === "captured") {
    return value.block_reason === null
      && value.content_eligible === true
      && sha256(value.answer_text_hash)
      && Number(value.answer_character_count) > 0;
  }
  if (value.outcome === "surface_not_present") {
    return value.block_reason === null
      && value.content_eligible === true
      && value.answer_text_hash === null
      && value.answer_character_count === 0
      && value.citation_count === 0;
  }
  return typeof value.block_reason === "string"
    && outcomeBySurfaceBlockReason.get(value.block_reason) === value.outcome
    && value.content_eligible === false
    && value.answer_text_hash === null
    && value.answer_character_count === 0
    && value.citation_count === 0;
}

function sha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function strings(value: Record<string, unknown>, keys: string[]): boolean {
  return keys.every((key) => typeof value[key] === "string" && String(value[key]).length > 0);
}

function arrays(value: Record<string, unknown>, keys: string[]): boolean {
  return keys.every((key) => Array.isArray(value[key]));
}
