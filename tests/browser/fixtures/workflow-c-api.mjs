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

function reset() {
  requests = [];
  alert = baseAlert();
  notifications = [];
  notifications = ["admin_inbox", "local_smtp", "internal_webhook"].map((channel, index) => (
    notification(channel, index + 1, 1)
  ));
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
      membership_id: uuid(4), project_id: PROJECT_ID, identity_id: ACTOR_ID,
      issuer: "workflow-c-fixture", subject: ACTOR_ID, email: "owner@example.test",
      display_name: "Workflow C Owner", role: "owner", status: "active", created_at: NOW
    }],
    total: 1, limit: 100, offset: 0
  });
  if (path === `${base}/sampling/admission-policies`) return send(response, { items: [], total: 0 });
  if (path === `${base}/sampling/admission-options`) return send(response, { items: [], total: 0 });
  if (path === `${base}/sampling/suite-input-options`) return send(response, { items: [], total: 0 });
  if (path === `${base}/sampling/suites`) return send(response, { items: [suite], total: 1 });
  if (path === `${base}/sampling/runs`) return send(response, { items: [runDetail.run], total: 1 });
  if (path === `${base}/sampling/manual-evidence-imports`) return send(response, { items: [], total: 0 });
  if (path === `${base}/sampling/suites/${SUITE_ID}`) return send(response, suite);
  if (path === `${base}/sampling/runs/${RUN_ID}`) return send(response, runDetail);
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
