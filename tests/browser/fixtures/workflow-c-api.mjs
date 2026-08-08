import http from "node:http";

const PORT = Number(process.env.GEO_WORKFLOW_C_FIXTURE_PORT || "3299");
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const TENANT_ID = "00000000-0000-4000-8000-000000000002";
const SUITE_ID = "00000000-0000-4000-8000-000000000701";
const RUN_ID = "00000000-0000-4000-8000-000000000702";
const ALERT_ID = "00000000-0000-4000-8000-000000000703";
const POLICY_ID = "00000000-0000-4000-8000-000000000704";
const QUESTION_SET_ID = "00000000-0000-4000-8000-000000000705";
const ADAPTER_RELEASE_ID = "00000000-0000-4000-8000-000000000706";
const MODEL_RELEASE_ID = "00000000-0000-4000-8000-000000000707";
const ROUTE_POLICY_ID = "00000000-0000-4000-8000-000000000708";
const RUNTIME_MANIFEST_ID = "00000000-0000-4000-8000-000000000709";
const RUNTIME_OPTION_ID = "00000000-0000-4000-8000-000000000710";
const MANUAL_SUITE_ID = "00000000-0000-4000-8000-000000000750";
const MANUAL_RUN_ID = "00000000-0000-4000-8000-000000000751";
const MANUAL_TASK_ID = "00000000-0000-4000-8000-000000000752";
const MANUAL_IMPORT_ID = "00000000-0000-4000-8000-000000000753";
const AIO_PARSER_RELEASE_ID = "00000000-0000-4000-8000-000000000760";
const IDENTITY_ID = "00000000-0000-4000-8000-000000000770";
const METRIC_PROTOCOL_ID = "00000000-0000-4000-8000-000000000771";
const COMPARISON_PROTOCOL_ID = "00000000-0000-4000-8000-000000000772";
const DRIFT_PROTOCOL_ID = "00000000-0000-4000-8000-000000000773";
const REPORT_ID = "00000000-0000-4000-8000-000000000774";
const REPORT_MAKER_ID = "00000000-0000-4000-8000-000000000775";
const CAMPAIGN_ID = "00000000-0000-4000-8000-000000000776";
const MONITORING_REPORT_ID = "00000000-0000-4000-8000-000000000777";
const ACTOR_ID = "workflow-c-owner";
const NOW = "2026-07-23T02:30:00.000Z";
const HASH = {
  suite: "1".repeat(64),
  stratum: "2".repeat(64),
  denominator: "3".repeat(64),
  metric: "a".repeat(64),
  comparison: "b".repeat(64),
  drift: "c".repeat(64),
  evidence: "d".repeat(64),
  trigger: "e".repeat(64),
  rule: "f".repeat(64)
};

let requests = [];
let alert;
let notifications;
let metricProtocols;
let statisticalProtocols;
let workflowCReports;
let browserCaptureBootstrapped;

function reset() {
  requests = [];
  alert = baseAlert();
  notifications = [];
  notifications = ["admin_inbox", "local_smtp", "internal_webhook"].map((channel, index) => (
    notification(channel, index + 1, 1)
  ));
  metricProtocols = [metricProtocol()];
  statisticalProtocols = [comparisonProtocol(), driftProtocol()];
  workflowCReports = [workflowCReport()];
  browserCaptureBootstrapped = false;
}

function browserReadiness() {
  const surfaces = ["google_ai_overviews", "google_ai_mode", "bing_copilot"];
  return {
    items: surfaces.map((surface, index) => ({
      surface,
      state: "blocked",
      blocking_reasons: browserCaptureBootstrapped ? ["needs_au_egress"] : ["needs_adapter"],
      surface_release_id: browserCaptureBootstrapped ? uuid(810 + index) : null,
      release_version: browserCaptureBootstrapped ? "2026-08-07.1" : null,
      profile_version_id: browserCaptureBootstrapped ? uuid(814) : null,
      egress_endpoint_id: null,
      captured_count: 0
    }))
  };
}

function browserInventory() {
  return {
    surface_releases: [],
    egress_endpoints: [],
    profiles: browserCaptureBootstrapped ? [{
      id: uuid(814),
      version: "au-anonymous-desktop-2026-08-07.1",
      account_cohort: "clean_anonymous",
      status: "approved"
    }] : [],
    egress_tests: [],
    drift_events: [],
    tasks: [],
    sessions: []
  };
}

const taskKeys = Array.from({ length: 10 }, (_, index) => `fixture-question|repeat-${index + 1}`);
const suite = {
  id: SUITE_ID,
  project_id: PROJECT_ID,
  question_set_id: QUESTION_SET_ID,
  question_set_version: "question-set-au-v1",
  question_set_hash: "4".repeat(64),
  adapter_release_id: ADAPTER_RELEASE_ID,
  adapter_release_hash: "5".repeat(64),
  model_release_id: MODEL_RELEASE_ID,
  model_release_hash: "6".repeat(64),
  route_policy_id: ROUTE_POLICY_ID,
  route_policy_hash: "7".repeat(64),
  runtime_manifest_id: RUNTIME_MANIFEST_ID,
  runtime_manifest_hash: "8".repeat(64),
  runtime_option_id: RUNTIME_OPTION_ID,
  runtime_option_hash: "9".repeat(64),
  admission_policy_id: POLICY_ID,
  admission_policy_hash: "a".repeat(64),
  questions: [{ question_id: "best-accounting-platform-au", question_version: "v1", text_hash: "5".repeat(64) }],
  source_stratum: {
    platform: "openai",
    surface: "openai_api",
    configured_model: "gpt-fixture-2026-07",
    reported_model: "gpt-fixture-2026-07",
    capture_method: "provider_api",
    adapter_release: "openai-adapter-fixture-v1",
    locale: "en-AU",
    region: "AU",
    language: "en",
    search_mode: "grounded_web",
    account_cohort: "api-project",
    egress_policy_category: "provider-managed",
    location_control: "country",
    location_evidence_hash: "b".repeat(64),
    requested_country: "AU",
    requested_region: null,
    requested_locale: "en-AU",
    requested_language: "en",
    effective_country: "AU",
    effective_region: null,
    effective_locale: "en-AU",
    effective_language: "en",
    stratum_hash: HASH.stratum
  },
  repetitions: 10,
  statistics_method_version: "paired-bootstrap-v1",
  max_planned_tasks: 1000,
  max_daily_tasks: 1000,
  minimum_request_interval_seconds: 2,
  max_concurrency: 1,
  minimum_valid_repeats: 8,
  planned_task_count: 10,
  frozen_by: ACTOR_ID,
  frozen_at: NOW,
  suite_hash: HASH.suite
};

const tasks = taskKeys.map((taskKey, index) => ({
  id: uuid(710 + index),
  project_id: PROJECT_ID,
  run_id: RUN_ID,
  task_key: taskKey,
  question_id: "best-accounting-platform-au",
  question_version: "v1",
  repetition: index + 1,
  capture_method: "provider_api",
  source_stratum_hash: HASH.stratum,
  status: index === 9 ? "planned" : "succeeded",
  attempt_ids: index === 9 ? [] : [uuid(720 + index)],
  max_attempts: 3,
  version: index === 9 ? 1 : 3
}));

const attempts = tasks.slice(0, 9).map((task, index) => ({
  id: uuid(720 + index),
  project_id: PROJECT_ID,
  run_id: RUN_ID,
  task_id: task.id,
  task_key: task.task_key,
  ordinal: 1,
  job_status: "succeeded",
  record_version: 3,
  attempt_count: 1,
  provider_response_id: `provider-response-${index + 1}`,
  egress_verification_id: null,
  raw_artifact_hash: String(index + 1).repeat(64).slice(0, 64),
  actual_location: null,
  terminal_status: "succeeded"
}));

const derivedSummary = "Anonymous AU cohort summary: operators compared transparent pricing, local support, auditability, and evidence quality.";
const observations = tasks.slice(0, 9).map((task, index) => ({
  id: uuid(730 + index),
  project_id: PROJECT_ID,
  run_id: RUN_ID,
  task_id: task.id,
  task_key: task.task_key,
  winning_attempt_id: attempts[index].id,
  source_stratum_hash: HASH.stratum,
  actual_location: null,
  evidence_status: index === 8 ? "ineligible" : "complete",
  ineligible_reasons: index === 8 ? ["citation_entailment_missing"] : [],
  evidence: {
    raw_manifest_hash: String(index + 1).repeat(64).slice(0, 64),
    derived_manifest_hash: String((index + 2) % 10).repeat(64),
    derived_content_hash: String((index + 3) % 10).repeat(64),
    governance_policy_hash: "f".repeat(64),
    derived_summary: derivedSummary,
    evidence_locator: "json-pointer:/answer",
    provider_response_id: `provider-response-${index + 1}`,
    egress_verification_id: null,
    result_parameters_hash: "6".repeat(64)
  },
  observed_at: NOW,
  observation_hash: String((index + 1) % 10).repeat(64)
}));

const runDetail = {
  run: {
    id: RUN_ID,
    project_id: PROJECT_ID,
    suite_id: SUITE_ID,
    suite_hash: HASH.suite,
    admission_policy_id: POLICY_ID,
    admission_policy_hash: suite.admission_policy_hash,
    admission_grant_hash: "7".repeat(64),
    purpose: "frozen regression measurement",
    authorization_reference: "approval-workflow-c-fixture",
    authorization_valid_until: "2026-08-23T02:30:00.000Z",
    admission_policy_version: "sampling-admission-v1",
    reserved_task_count: 10,
    planned_task_keys: taskKeys,
    status: "completed",
    admitted_not_before: NOW,
    created_at: NOW,
    version: 3
  },
  suite,
  tasks,
  attempts,
  observations,
  assessment: {
    run_id: RUN_ID,
    planned_task_count: 10,
    valid_task_count: 8,
    invalid_task_count: 1,
    missing_task_count: 1,
    valid_completion_ratio: "0.8",
    sufficient_question_count: 1,
    question_count: 1,
    status: "complete",
    denominator_hash: HASH.denominator
  }
};

const surfaceParserReleases = [
  parserRelease(AIO_PARSER_RELEASE_ID, "google-ai-overviews-parser-v1", "google", "google_ai_overviews", "1"),
  parserRelease(uuid(761), "google-ai-mode-parser-v1", "google", "google_ai_mode", "2"),
  parserRelease(uuid(762), "bing-copilot-parser-v1", "bing", "bing_copilot", "3")
];

const manualSuite = {
  ...suite,
  id: MANUAL_SUITE_ID,
  suite_hash: "0".repeat(64),
  repetitions: 1,
  minimum_valid_repeats: 1,
  planned_task_count: 1,
  source_stratum: {
    ...suite.source_stratum,
    platform: "google",
    surface: "ai_overviews",
    configured_model: "consumer-ui-unreported",
    reported_model: "consumer-ui-unreported",
    capture_method: "manual_ui",
    adapter_release: "manual-ui-evidence-v1",
    search_mode: "consumer_search",
    account_cohort: "governed-manual-fixture",
    egress_policy_category: "not_proven",
    location_control: "not_controlled",
    location_evidence_hash: "0".repeat(64),
    requested_country: null,
    effective_country: null,
    effective_locale: null,
    effective_language: null,
    stratum_hash: "f".repeat(64)
  }
};

const manualTask = {
  ...tasks[0],
  id: MANUAL_TASK_ID,
  run_id: MANUAL_RUN_ID,
  task_key: "best-accounting-platform-au|manual-repeat-1",
  repetition: 1,
  capture_method: "manual_ui",
  source_stratum_hash: manualSuite.source_stratum.stratum_hash,
  status: "planned",
  attempt_ids: [],
  version: 1
};

const manualRunDetail = {
  run: {
    ...runDetail.run,
    id: MANUAL_RUN_ID,
    suite_id: MANUAL_SUITE_ID,
    suite_hash: manualSuite.suite_hash,
    reserved_task_count: 1,
    planned_task_keys: [manualTask.task_key],
    status: "planned",
    version: 1
  },
  suite: manualSuite,
  tasks: [manualTask],
  attempts: [],
  observations: [],
  assessment: {
    run_id: MANUAL_RUN_ID,
    planned_task_count: 1,
    valid_task_count: 0,
    invalid_task_count: 0,
    missing_task_count: 1,
    valid_completion_ratio: "0",
    sufficient_question_count: 0,
    question_count: 1,
    status: "insufficient_evidence",
    denominator_hash: "9".repeat(64)
  }
};

const manualEvidenceImport = {
  id: MANUAL_IMPORT_ID,
  project_id: PROJECT_ID,
  run_id: MANUAL_RUN_ID,
  task_id: MANUAL_TASK_ID,
  task_key: manualTask.task_key,
  attempt_id: uuid(754),
  expected_task_version: 1,
  artifact_manifest_id: uuid(755),
  artifact_manifest_hash: "1".repeat(64),
  artifact_content_hash: "2".repeat(64),
  governance_policy_hash: "3".repeat(64),
  capture_session_id: uuid(756),
  evidence_kind: "transcript_export",
  device: "desktop",
  locale: "en-AU",
  captured_at: NOW,
  submitted_by: "workflow-c-analyst",
  submitted_at: NOW,
  status: "pending_review",
  reviewed_by: null,
  reviewed_at: null,
  review_reason: null,
  committed_at: null,
  aggregate_version: 1,
  definition_hash: "4".repeat(64),
  surface_parse: {
    parser_release_id: AIO_PARSER_RELEASE_ID,
    parser_release_hash: "1".repeat(64),
    platform: "google",
    surface: "google_ai_overviews",
    capture_kind: "manual_ui",
    outcome: "captured",
    block_reason: null,
    content_eligible: true,
    automated_capture: false,
    live_capture_eligible: false,
    answer_text_hash: "5".repeat(64),
    answer_character_count: 137,
    citation_count: 3,
    citation_set_hash: "6".repeat(64),
    locator_set_hash: "7".repeat(64),
    parser_result_hash: "8".repeat(64),
    summary_hash: "9".repeat(64)
  }
};

const metricSnapshot = {
  project_id: PROJECT_ID,
  input_set_hash: "8".repeat(64),
  suite_hash: HASH.suite,
  stratum_hash: HASH.stratum,
  results: [
    metric("mention_rate", "0.75", 6, 8, "answer_span"),
    metric("recommendation_rate", "0.5", 4, 8, "answer_span"),
    metric("citation_entailment", "0.875", 7, 8, "citation"),
    metric("fact_accuracy", "0.625", 5, 8, "fact"),
    metric("answer_absorption", "0.58", 464, 800, "answer_span")
  ],
  performance: {
    questions: [{ question_id: "best-accounting-platform-au", question_cluster: "commercial-intent", score: "0.42", planned_slot_count: 10 }],
    clusters: [{ question_cluster: "commercial-intent", score: "0.42", planned_slot_count: 10 }],
    worst_question_id: "best-accounting-platform-au",
    worst_question_score: "0.42",
    worst_cluster: "commercial-intent",
    worst_cluster_score: "0.42",
    negative_gain: {
      compared_question_count: 10,
      affected_question_count: 3,
      mean_negative_gain: "-0.08",
      range_low: "-0.13",
      range_high: "-0.02",
      worst_question_id: "best-accounting-platform-au",
      worst_question_delta: "-0.21"
    }
  },
  computed_at: NOW,
  snapshot_hash: HASH.metric
};

const comparisonFamily = {
  project_id: PROJECT_ID,
  family: "approved-corpus-vs-candidate",
  alpha: "0.05",
  correction_method: "holm",
  results: ["win", "equivalent", "loss", "inconclusive", "insufficient_evidence"].map((conclusion, index) => ({
    comparison_id: `comparison-${conclusion}`,
    family: "approved-corpus-vs-candidate",
    protocol_frozen_hash: "9".repeat(64),
    input_hash: String(index + 1).repeat(64),
    stratum_hash: HASH.stratum,
    valid_pair_count: conclusion === "insufficient_evidence" ? 6 : 10,
    planned_pair_count: 10,
    completion_ratio: conclusion === "insufficient_evidence" ? "0.6" : "1",
    point_estimate: ["0.14", "0.01", "-0.12", "0.03", "0.05"][index],
    raw_interval: { method: "paired-bootstrap", alpha: "0.05", low: "-0.04", high: "0.18" },
    adjusted_interval: { method: "paired-bootstrap-holm", alpha: "0.01", low: "-0.08", high: "0.21" },
    raw_p_value: "0.04",
    adjusted_p_value: "0.08",
    holm_rank: index + 1,
    local_alpha: "0.01",
    a_priori_design_power: conclusion === "inconclusive" ? "0.42" : "0.82",
    power_plan_hash: "e".repeat(64),
    power_method_version: "paired-bootstrap-power-v1",
    conclusion,
    seed_hex: "1".repeat(64),
    bootstrap_iterations: 1000,
    result_hash: String(index + 3).repeat(64)
  })),
  family_hash: HASH.comparison
};

const driftReport = {
  project_id: PROJECT_ID,
  model_drift: [{ stratum_hash: HASH.stratum, prior_model: "fixture-v1", current_model: "fixture-v2", changed: true }],
  source_drift: [{ stratum_hash: HASH.stratum, jensen_shannon: "0.18", threshold: "0.10" }],
  effect_drift: [{ metric_key: "recommendation_rate", delta: "-0.12", interval_low: "-0.20", interval_high: "-0.03" }],
  unmatched_baseline_strata: ["baseline-only-" + "a".repeat(64)],
  unmatched_current_strata: ["current-only-" + "b".repeat(64)],
  baseline_input_hash: "0".repeat(64),
  current_input_hash: "1".repeat(64),
  method_version: "strict-stratum-drift-v1",
  report_hash: HASH.drift
};

function metric(key, estimate, numerator, denominator, locatorKind) {
  return {
    metric_key: key,
    metric_version: `${key}-v1`,
    value_kind: key === "answer_absorption" ? "ratio" : "binary_rate",
    input_set_hash: "8".repeat(64),
    stratum: { capture_method: "provider_api", locale: "en-AU", region: "AU" },
    stratum_hash: HASH.stratum,
    numerator: String(numerator),
    denominator,
    estimate,
    interval: { method: "wilson-95", confidence_level: "0.95", low: "0.31", high: "0.91" },
    valid_input_count: 8,
    invalid_input_count: 1,
    missing_input_count: 1,
    status: "complete",
    judge_version: key === "fact_accuracy" ? "metric-judge-release-v3" : null,
    judge_version_hash: key === "fact_accuracy" ? "2".repeat(64) : null,
    rule_versions: { metric_contract: "semantic-metrics-v1" },
    rule_versions_hash: "3".repeat(64),
    evidence_locators: [{
      kind: locatorKind,
      reference_id: observations[0].id,
      version: "observation-v1",
      content_hash: "c".repeat(64),
      start: 0,
      end: 68,
      redacted_quote_hash: "d".repeat(64)
    }],
    breakdown: { warning_share: "0.1", capture_method: "provider_api" },
    result_hash: key.padEnd(64, "0").slice(0, 64)
  };
}

function parserRelease(id, key, platform, surface, hashDigit) {
  return {
    id,
    release_key: key,
    release_version: "2026-07-24.1",
    release_hash: hashDigit.repeat(64),
    platform,
    surface,
    artifact_schema_version: "consumer-surface-artifact-v1",
    parser_engine_version: "consumer-surface-parser-v1",
    status: "fixture_ready",
    automated_capture_eligible: false,
    evidence_scope: "fixture_or_manual_non_live"
  };
}

function metricProtocol() {
  return {
    id: METRIC_PROTOCOL_ID,
    project_id: PROJECT_ID,
    series_id: METRIC_PROTOCOL_ID,
    version: 1,
    supersedes_protocol_id: null,
    status: "in_review",
    protocol_hash: "4".repeat(64),
    definition: { schema_version: 1, metric_suite: { minimum_valid_completion: "0.8" } },
    created_by: "workflow-c-maker",
    submitted_by: "workflow-c-maker",
    approved_by: null,
    retired_by: null,
    decision_reason: null,
    aggregate_version: 2,
    created_at: NOW,
    updated_at: NOW,
    submitted_at: NOW,
    approved_at: null,
    retired_at: null
  };
}

function comparisonProtocol() {
  return {
    id: COMPARISON_PROTOCOL_ID,
    project_id: PROJECT_ID,
    series_id: COMPARISON_PROTOCOL_ID,
    version: 1,
    supersedes_protocol_id: null,
    kind: "comparison_plan",
    status: "in_review",
    definition_hash: "5".repeat(64),
    definition: { schema_version: 1, kind: "comparison_plan", family: "fixture-family" },
    created_by: "workflow-c-maker",
    submitted_by: "workflow-c-maker",
    approved_by: null,
    retired_by: null,
    decision_reason: null,
    aggregate_version: 2,
    created_at: NOW,
    updated_at: NOW,
    submitted_at: NOW,
    approved_at: null,
    retired_at: null
  };
}

function driftProtocol() {
  return {
    ...comparisonProtocol(),
    id: DRIFT_PROTOCOL_ID,
    series_id: DRIFT_PROTOCOL_ID,
    kind: "drift_protocol",
    status: "approved",
    definition_hash: "6".repeat(64),
    definition: { schema_version: 1, kind: "drift_protocol", minimum_question_count: 3 },
    approved_by: "workflow-c-checker",
    decision_reason: "fixture protocol approved",
    aggregate_version: 3,
    approved_at: NOW
  };
}

function workflowCReport() {
  return {
    report_id: REPORT_ID,
    project_id: PROJECT_ID,
    version: 2,
    status: "in_review",
    campaign_id: CAMPAIGN_ID,
    monitoring_report_id: MONITORING_REPORT_ID,
    monitoring_report_hash: "7".repeat(64),
    semantic_snapshot_hash: HASH.metric,
    source_kind: "provider_api",
    approved_safe_payload: {
      headline: "Approved Australian evidence",
      summary: "Frozen aggregate prepared for customer review.",
      methodology: "Approved semantic metric snapshot.",
      warnings: ["One planned sample is missing."],
      metrics: { brand_mention: "0.75", recommendation: "0.5" }
    },
    approved_safe_payload_hash: "8".repeat(64),
    version_hash: "9".repeat(64),
    actor_id: REPORT_MAKER_ID,
    reason: null,
    occurred_at: NOW
  };
}

function baseAlert() {
  return {
    id: ALERT_ID,
    project_id: PROJECT_ID,
    rule: {
      id: "00000000-0000-4000-8000-000000000704",
      rule_key: "negative-gain-worst-question",
      version: 1,
      kind: "negative_question",
      severity: "critical",
      parameters: { practical_effect_threshold: "-0.05", minimum_valid_completion: "0.8" },
      frozen_by: ACTOR_ID,
      frozen_at: NOW
    },
    rule_hash: HASH.rule,
    scope: { resource_kind: "semantic_metric_snapshot", resource_key: HASH.metric, dimensions: { locale: "en-AU", region: "AU" } },
    trigger_values: { worst_question_delta: "-0.21", valid_completion_ratio: "0.8" },
    trigger_snapshot_hash: HASH.trigger,
    evidence: [{ kind: "metric_snapshot", resource_id: HASH.metric, version: "semantic-metrics-v1", sha256: HASH.evidence, locator: "performance.negative_gain" }],
    severity: "critical",
    dedupe_key: `negative-gain:${HASH.metric}`,
    status: "open",
    opened_at: NOW,
    updated_at: NOW,
    version: 1,
    dispositions: [],
    suppressed_until: null,
    suppression_reason: null,
    replayed: false
  };
}

function notification(channel, index, alertVersion) {
  return {
    id: uuid(800 + notificationsLength() + index),
    project_id: PROJECT_ID,
    alert_id: ALERT_ID,
    alert_version: alertVersion,
    channel,
    topic: `workflow-c.alert.${alert.status}`,
    idempotency_key: `${channel}:${ALERT_ID}:${alertVersion}`,
    created_at: NOW,
    payload_hash: String((index + alertVersion) % 10).repeat(64),
    summary: {
      alert_id: ALERT_ID,
      status: alert.status,
      severity: alert.severity,
      resource_kind: alert.scope.resource_kind,
      evidence_count: alert.evidence.length
    }
  };
}

function notificationsLength() {
  return Array.isArray(notifications) ? notifications.length : 0;
}

function uuid(suffix) {
  return `00000000-0000-4000-8000-${String(suffix).padStart(12, "0")}`;
}

function send(response, body, status = 200) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

function problem(response, status, detail) {
  send(response, {
    type: "about:blank",
    title: status === 409 ? "Conflict" : "Invalid request",
    status,
    detail,
    correlation_id: `workflow-c-fixture-${status}`
  }, status);
}

async function body(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8");
  return raw ? JSON.parse(raw) : {};
}

function transition(command, payload, idempotencyKey) {
  const fromStatus = alert.status;
  const nextVersion = alert.version + 1;
  const toStatus = command === "acknowledge"
    ? "acknowledged"
    : command === "suppress"
      ? "suppressed"
      : command === "unsuppress"
        ? "acknowledged"
        : "resolved";
  alert = {
    ...alert,
    status: toStatus,
    updated_at: payload.occurred_at,
    version: nextVersion,
    suppressed_until: command === "suppress" ? payload.suppressed_until : null,
    suppression_reason: command === "suppress" ? payload.reason : null,
    dispositions: [...alert.dispositions, {
      disposition: command,
      from_status: fromStatus,
      to_status: toStatus,
      actor_id: ACTOR_ID,
      occurred_at: payload.occurred_at,
      reason: payload.reason,
      command_key: idempotencyKey,
      resulting_version: nextVersion,
      suppressed_until: command === "suppress" ? payload.suppressed_until : null,
      command_hash: String(nextVersion % 10).repeat(64)
    }]
  };
  const emitted = ["admin_inbox", "local_smtp", "internal_webhook"].map((channel, index) => notification(channel, index + 1, alert.version));
  notifications = [...notifications, ...emitted];
  return { alert, notifications: emitted, replayed: false };
}

function transitionProtocol(items, protocolId, command, payload) {
  const index = items.findIndex((item) => item.id === protocolId);
  const current = items[index];
  if (!current || payload.expected_aggregate_version !== current.aggregate_version) return null;
  const status = command === "submit" ? "in_review" : command === "approve" ? "approved" : "retired";
  const updated = {
    ...current,
    status,
    aggregate_version: current.aggregate_version + 1,
    updated_at: NOW,
    submitted_by: command === "submit" ? ACTOR_ID : current.submitted_by,
    submitted_at: command === "submit" ? NOW : current.submitted_at,
    approved_by: command === "approve" ? ACTOR_ID : current.approved_by,
    approved_at: command === "approve" ? NOW : current.approved_at,
    retired_by: command === "retire" ? ACTOR_ID : current.retired_by,
    retired_at: command === "retire" ? NOW : current.retired_at,
    decision_reason: command === "submit" ? current.decision_reason : payload.reason
  };
  items[index] = updated;
  return updated;
}

function transitionReport(command, payload) {
  const current = workflowCReports[0];
  if (!current || payload.expected_version !== current.version) return null;
  const status = command === "submit" ? "in_review" : command === "approve" ? "approved" : command;
  const updated = {
    ...current,
    version: current.version + 1,
    status,
    actor_id: IDENTITY_ID,
    reason: payload.reason || null,
    occurred_at: NOW,
    version_hash: String((current.version + 1) % 10).repeat(64)
  };
  workflowCReports[0] = updated;
  return updated;
}

function acceptedJob(kind) {
  const index = kind === "semantic" ? 781 : kind === "comparison" ? 782 : 783;
  const receipt = {
    job_id: uuid(index),
    status: "queued",
    status_url: `/v1/jobs/${uuid(index)}`,
    replayed: false
  };
  return kind === "semantic"
    ? { ...receipt, manifest_id: uuid(784), manifest_hash: "a".repeat(64) }
    : { ...receipt, spec_hash: "b".repeat(64) };
}

reset();

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
  const path = url.pathname;
  if (path === "/health") return send(response, { ok: true });
  if (path === "/__requests" && request.method === "GET") return send(response, requests);
  if (path === "/__requests" && request.method === "DELETE") {
    reset();
    return send(response, { ok: true });
  }
  const payload = request.method === "POST" ? await body(request) : null;
  requests.push({ method: request.method, path, payload, idempotency_key: request.headers["idempotency-key"] || null });

  if (path === "/v1/auth/me") return send(response, { actor_id: ACTOR_ID, tenant_id: TENANT_ID, project_ids: [PROJECT_ID], roles: ["owner"] });
  const base = `/v1/projects/${PROJECT_ID}`;
  if (path === base) return send(response, {
    id: PROJECT_ID,
    tenant_id: TENANT_ID,
    name: "Workflow C Browser Fixture",
    status: "active",
    created_at: NOW,
    updated_at: NOW
  });
  if (path === `${base}/entities`) return send(response, []);
  if (path === `${base}/market-profiles`) return send(response, []);
  if (path === `${base}/evidence-items`) return send(response, []);
  if (path === `${base}/invitations`) return send(response, {
    items: [], total: 0, limit: 100, offset: 0
  });
  if (path === `/v1/projects/${PROJECT_ID}/members`) return send(response, {
    items: [{
      membership_id: uuid(4), project_id: PROJECT_ID, identity_id: IDENTITY_ID,
      issuer: "workflow-c-fixture", subject: ACTOR_ID, email: "owner@example.test",
      display_name: "Workflow C Owner", role: "owner", status: "active", created_at: NOW
    }],
    total: 1, limit: 100, offset: 0
  });
  if (path === `${base}/sampling/admission-policies`) return send(response, { items: [], total: 0 });
  if (path === `${base}/browser-capture/readiness` && request.method === "GET") {
    return send(response, browserReadiness());
  }
  if (path === `${base}/browser-capture` && request.method === "GET") {
    return send(response, browserInventory());
  }
  if (path === `${base}/browser-capture/bootstrap` && request.method === "POST") {
    browserCaptureBootstrapped = true;
    return send(response, {
      surface_releases: [],
      profile: {
        id: uuid(814), project_id: PROJECT_ID,
        version: "au-anonymous-desktop-2026-08-07.1",
        browser_release: "playwright:1.60.0/chromium", device_class: "desktop",
        viewport: { width: 1440, height: 1000 }, locale: "en-AU",
        timezone: "Australia/Sydney", geolocation: null, location_permission: false,
        safe_search: "moderate", account_cohort: "clean_anonymous",
        storage_secret_reference_id: null, storage_secret_purpose: null,
        storage_secret_version: null, profile_hash: "1".repeat(64), status: "approved",
        created_by: IDENTITY_ID, created_at: NOW, approved_by: IDENTITY_ID, approved_at: NOW
      }
    });
  }
  if (path === `${base}/sampling/admission-options`) return send(response, { items: [], total: 0 });
  if (path === `${base}/sampling/suite-input-options`) return send(response, { items: [], total: 0 });
  if (path === `${base}/sampling/suites`) return send(response, { items: [suite, manualSuite], total: 2 });
  if (path === `${base}/sampling/runs`) return send(response, { items: [runDetail.run, manualRunDetail.run], total: 2 });
  if (path === `${base}/sampling/manual-evidence-imports`) return send(response, { items: [manualEvidenceImport], total: 1 });
  if (path === `${base}/sampling/surface-parser-releases`) return send(response, { items: surfaceParserReleases, total: surfaceParserReleases.length });
  if (path === `${base}/sampling/suites/${SUITE_ID}`) return send(response, suite);
  if (path === `${base}/sampling/suites/${MANUAL_SUITE_ID}`) return send(response, manualSuite);
  if (path === `${base}/sampling/runs/${RUN_ID}`) return send(response, runDetail);
  if (path === `${base}/sampling/runs/${MANUAL_RUN_ID}`) return send(response, manualRunDetail);
  if (path === `${base}/analysis/metric-protocols` && request.method === "GET") {
    return send(response, { items: metricProtocols, total: metricProtocols.length });
  }
  if (path === `${base}/analysis/statistical-protocols` && request.method === "GET") {
    return send(response, { items: statisticalProtocols, total: statisticalProtocols.length });
  }
  if (path === `${base}/analysis/reports` && request.method === "GET") {
    return send(response, { items: workflowCReports, total: workflowCReports.length });
  }
  if (path === `${base}/analysis/metric-protocols` && request.method === "POST") {
    const created = {
      ...metricProtocol(),
      id: uuid(790 + metricProtocols.length),
      series_id: uuid(790 + metricProtocols.length),
      status: "draft",
      definition: payload.definition,
      created_by: ACTOR_ID,
      submitted_by: null,
      submitted_at: null,
      aggregate_version: 1
    };
    metricProtocols.push(created);
    return send(response, created, 201);
  }
  if (path === `${base}/analysis/statistical-protocols` && request.method === "POST") {
    const created = {
      ...comparisonProtocol(),
      id: uuid(795 + statisticalProtocols.length),
      series_id: uuid(795 + statisticalProtocols.length),
      kind: payload.definition.kind,
      status: "draft",
      definition: payload.definition,
      created_by: ACTOR_ID,
      submitted_by: null,
      submitted_at: null,
      aggregate_version: 1
    };
    statisticalProtocols.push(created);
    return send(response, created, 201);
  }
  if (path === `${base}/analysis/reports` && request.method === "POST") {
    const created = {
      ...workflowCReport(),
      report_id: uuid(799 + workflowCReports.length),
      version: 1,
      status: "draft",
      campaign_id: payload.campaign_id,
      monitoring_report_id: payload.monitoring_report_id,
      monitoring_report_hash: payload.monitoring_report_hash,
      semantic_snapshot_hash: payload.semantic_snapshot_hash,
      source_kind: payload.source_kind,
      approved_safe_payload: payload.approved_safe_payload,
      actor_id: IDENTITY_ID
    };
    workflowCReports.push(created);
    return send(response, created, 201);
  }
  const metricProtocolMatch = path.match(new RegExp(`^${base}/analysis/metric-protocols/([^/]+)/(submit|approve|retire)$`));
  if (metricProtocolMatch && request.method === "POST") {
    if (payload.reason === "fixture-force-conflict") {
      return problem(response, 409, "Metric Protocol version conflict");
    }
    const updated = transitionProtocol(metricProtocols, metricProtocolMatch[1], metricProtocolMatch[2], payload);
    return updated ? send(response, updated) : problem(response, 409, "Metric Protocol version conflict");
  }
  const statisticalProtocolMatch = path.match(new RegExp(`^${base}/analysis/statistical-protocols/([^/]+)/(submit|approve|retire)$`));
  if (statisticalProtocolMatch && request.method === "POST") {
    const updated = transitionProtocol(statisticalProtocols, statisticalProtocolMatch[1], statisticalProtocolMatch[2], payload);
    return updated ? send(response, updated) : problem(response, 409, "Statistical Protocol version conflict");
  }
  const reportMatch = path.match(new RegExp(`^${base}/analysis/reports/${REPORT_ID}/(submit|approve|stale|revoke)$`));
  if (reportMatch && request.method === "POST") {
    if (payload.reason === "fixture-force-unavailable") {
      return problem(response, 503, "Workflow C Report service unavailable");
    }
    const updated = transitionReport(reportMatch[1], payload);
    return updated ? send(response, updated) : problem(response, 409, "Workflow C Report version conflict");
  }
  if (path === `${base}/analysis/semantic-metrics/jobs` && request.method === "POST") {
    return send(response, acceptedJob("semantic"), 202);
  }
  if (path === `${base}/analysis/comparisons/jobs` && request.method === "POST") {
    return send(response, acceptedJob("comparison"), 202);
  }
  if (path === `${base}/analysis/drift/jobs` && request.method === "POST") {
    return send(response, acceptedJob("drift"), 202);
  }
  if (path === `${base}/analysis/semantic-metrics`) return send(response, { items: [metricSnapshot], total: 1 });
  if (path === `${base}/analysis/semantic-metrics/${HASH.metric}`) return send(response, metricSnapshot);
  if (path === `${base}/analysis/comparisons`) return send(response, { items: [comparisonFamily], total: 1 });
  if (path === `${base}/analysis/comparisons/${HASH.comparison}`) return send(response, comparisonFamily);
  if (path === `${base}/analysis/drift`) return send(response, { items: [driftReport], total: 1 });
  if (path === `${base}/analysis/drift/${HASH.drift}`) return send(response, driftReport);
  if (path === `${base}/alerts` && request.method === "GET") return send(response, { items: [alert], total: 1 });
  if (path === `${base}/alerts/${ALERT_ID}/notifications` && request.method === "GET") return send(response, notifications);
  const match = path.match(new RegExp(`^${base}/alerts/${ALERT_ID}/(acknowledge|suppress|unsuppress|resolve)$`));
  if (match && request.method === "POST") {
    if (payload.expected_version !== alert.version) return problem(response, 409, "Alert version conflict");
    return send(response, transition(match[1], payload, String(request.headers["idempotency-key"] || "fixture-command")));
  }
  return problem(response, 404, `No fixture route for ${request.method} ${path}`);
});

server.listen(PORT, "127.0.0.1");

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
