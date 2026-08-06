import { createServer } from "node:http";

import {
  handleSyntheticLabFixture,
  resetSyntheticLabFixture,
  syntheticRuntimeOptions
} from "./synthetic-lab-fixture.mjs";
import {
  handleRecommendationFixture,
  recommendationRuntimeOptions,
  resetRecommendationFixture
} from "./recommendation-fixture.mjs";
import {
  handlePromptBootstrapFixture,
  resetPromptBootstrapFixture
} from "./prompt-bootstrap-fixture.mjs";

const PORT = Number(process.env.GEO_BROWSER_FIXTURE_PORT || 3199);
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const TENANT_ID = "00000000-0000-4000-8000-000000000002";
const ACTOR_ID = "00000000-0000-4000-8000-000000000003";
const MARKET_ID = "00000000-0000-4000-8000-000000000010";
const PRODUCT_ID = "00000000-0000-4000-8000-000000000011";
const DESTINATION_A_ID = "00000000-0000-4000-8000-000000000021";
const DESTINATION_B_ID = "00000000-0000-4000-8000-000000000022";
const CAMPAIGN_A_ID = "00000000-0000-4000-8000-000000000031";
const CAMPAIGN_B_ID = "00000000-0000-4000-8000-000000000032";
const PROTOCOL_A_ID = "00000000-0000-4000-8000-000000000041";
const PROTOCOL_DRAFT_ID = "00000000-0000-4000-8000-000000000042";
const OPPORTUNITY_A_ID = "00000000-0000-4000-8000-000000000051";
const QUERY_A_ID = "00000000-0000-4000-8000-000000000061";
const PROTOCOL_QUERY_A_ID = "00000000-0000-4000-8000-000000000062";
const LEGACY_SUGGESTION_ID = "00000000-0000-4000-8000-000000000063";
const BRAND_ID = "00000000-0000-4000-8000-000000000070";
const SKILL_ID = "00000000-0000-4000-8000-000000000071";
const SKILL_VERSION_ID = "00000000-0000-4000-8000-000000000072";
const RELEASE_ID = "00000000-0000-4000-8000-000000000073";
const BINDING_ID = "00000000-0000-4000-8000-000000000074";
const BINDING_ANCHOR_ID = "00000000-0000-4000-8000-000000000079";
const BRIEF_ID = "00000000-0000-4000-8000-000000000075";
const ATTEMPT_ID = "00000000-0000-4000-8000-000000000076";
const BUNDLE_ID = "00000000-0000-4000-8000-000000000077";
const LEGACY_BUNDLE_ID = "00000000-0000-4000-8000-000000000078";
const SOURCE_ID = "00000000-0000-4000-8000-000000000101";
const PIPELINE_RUN_ID = "00000000-0000-4000-8000-000000000102";
const DOCUMENT_ID = "00000000-0000-4000-8000-000000000103";
const CHUNK_ID = "00000000-0000-4000-8000-000000000104";
const FACT_ID = "00000000-0000-4000-8000-000000000105";
const EVIDENCE_ID = "00000000-0000-4000-8000-000000000106";
const EVIDENCE_JOB_ID = "00000000-0000-4000-8000-000000000107";
const PACKAGE_ID = "00000000-0000-4000-8000-000000000111";
const PACKAGE_VERSION_ID = "00000000-0000-4000-8000-000000000112";
const PUBLICATION_ID = "00000000-0000-4000-8000-000000000113";
const SUBMISSION_ID = "00000000-0000-4000-8000-000000000114";
const QUESTION_JOB_ID = "00000000-0000-4000-8000-000000000131";
const QUESTION_CANDIDATE_ID = "00000000-0000-4000-8000-000000000132";
const QUESTION_DUPLICATE_ID = "00000000-0000-4000-8000-000000000133";
const QUESTION_SET_ID = "00000000-0000-4000-8000-000000000134";
const QUESTION_SET_ITEM_ID = "00000000-0000-4000-8000-000000000135";
const QUESTION_SIMULATION_ID = "00000000-0000-4000-8000-000000000136";
const QUESTION_SIMULATION_JOB_ID = "00000000-0000-4000-8000-000000000137";
const LEGACY_SIMULATION_ID = "00000000-0000-4000-8000-000000000138";
const LEGACY_SIMULATION_JOB_ID = "00000000-0000-4000-8000-000000000139";
const NOW = "2026-07-19T02:00:00Z";
const HASH = "a".repeat(64);
const SOURCE_STRATUM_HASH = "e748f50aa9fef8795a832a9e9b5e3734e5ce49fa0fa8534572f8efabc7cf300f";
const SOURCE_STRATA_INVENTORY_HASH = "583e31e9a30b562582c503d872c35014db6d7b41d4c5fac5446eaf47a7e4937b";
const PROJECT_EXPORT_JOB_ID = "00000000-0000-4000-8000-000000000401";
const PROMPT_PROGRAM_ID = "00000000-0000-4000-8000-000000000501";
const PROMPT_BASE_RELEASE_ID = "00000000-0000-4000-8000-000000000502";
const PROMPT_CANDIDATE_RELEASE_ID = "00000000-0000-4000-8000-000000000503";
const PROMPT_OWNER_ID = "00000000-0000-4000-8000-000000000504";
const PROMPT_EVIDENCE_ID = "00000000-0000-4000-8000-000000000505";
const PROMPT_BINDING_ID = "00000000-0000-4000-8000-000000000506";
const PROMPT_RUNTIME_SELECTION_ID = "00000000-0000-4000-8000-000000000510";
const SECRET_REFERENCE_ID = "00000000-0000-4000-8000-000000000601";
const SECRET_ACTOR_B_ID = "00000000-0000-4000-8000-000000000602";

const requests = [];
const observations = [];
const bundles = [];
const metricSnapshots = [];
let promptBinding = unboundBinding();
let factStatus = "pending_review";
let factReviewNotes = null;
let promotedEvidence = null;
let evidencePackRebuilt = false;
let submittedUrl = null;
let submissionStatus = "awaiting_url";
let verificationShouldPass = false;
let verificationAttemptNumber = 0;
const publicationVerificationAttempts = [];
let questionGenerationCreated = false;
let questionGenerationMode = "single_scenario";
let questionCandidateStatus = "pending_review";
let questionCandidateNotes = null;
let questionSetStatus = null;
let coverageIncludedIds = [];
const questionCandidateEdits = new Map();
let questionSimulation = null;
let questionProtocol;
let projectExportJobStatus = "succeeded";
let projectExportErrorCode = null;
let promptCandidateStatus = "draft";
let promptCandidateStateVersion = 1;
let promptCandidateEvidenceRef = null;
let promptCandidateCreated = false;
let promptWorkspaceInitialized = true;
let promptCurrentReleaseId = PROMPT_BASE_RELEASE_ID;
let promptCurrentReleaseVersion = 1;
let promptDraft = initialPromptDraft();
const promptWorkspaceTestRuns = [];
let promptNextReleaseVersion = 3;
const additionalPromptReleases = [];
let secretActorId = ACTOR_ID;
let secretRole = "owner";
let secretUnavailable = false;
let secretReference = null;
let secretAggregateVersion = 0;
let secretCurrentVersion = null;
const secretVersions = [];
const secretAudits = [];
let difyRuntimeScenario = "default";

function secretReferenceView() {
  if (!secretReference) return null;
  const latest = secretVersions[secretVersions.length - 1];
  const status = secretCurrentVersion !== null
    ? "active"
    : secretVersions.some((item) => item.status === "pending")
      ? "pending"
      : secretVersions.every((item) => item.status === "revoked")
        ? "revoked"
        : "inactive";
  return {
    reference_id: secretReference.reference_id,
    purpose: secretReference.purpose,
    status,
    aggregate_version: secretAggregateVersion,
    current_version: secretCurrentVersion,
    latest_version: latest.version,
    master_key_version: latest.masterKeyVersion,
    fingerprint: latest.fingerprint,
    created_at: secretReference.createdAt,
    updated_at: NOW
  };
}

function secretVersionView(version, replayed = false) {
  const item = secretVersions.find((candidate) => candidate.version === version);
  return item ? {
    reference_id: SECRET_REFERENCE_ID,
    version: item.version,
    status: item.status,
    aggregate_version: secretAggregateVersion,
    master_key_version: item.masterKeyVersion,
    fingerprint: item.fingerprint,
    created_at: item.createdAt,
    verified_at: item.verifiedAt,
    activated_at: item.activatedAt,
    revoked_at: item.revokedAt,
    replayed
  } : null;
}

function appendSecretAudit(version, action) {
  const item = secretVersions.find((candidate) => candidate.version === version);
  secretAudits.push({
    reference_id: SECRET_REFERENCE_ID,
    version,
    action,
    master_key_version: item.masterKeyVersion,
    fingerprint: item.fingerprint,
    occurred_at: NOW
  });
}

function promptProgram() {
  return {
    id: PROMPT_PROGRAM_ID,
    project_id: PROJECT_ID,
    program_kind: "generation",
    purpose: "synthetic_lab.generation",
    owner_id: PROMPT_OWNER_ID
  };
}

function promptRelease({ id, version, status, stateVersion, evidenceRef = null }) {
  const suffix = version % 10;
  return {
    id,
    project_id: PROJECT_ID,
    program_id: PROMPT_PROGRAM_ID,
    program_kind: "generation",
    purpose: "synthetic_lab.generation",
    version,
    owner_id: PROMPT_OWNER_ID,
    release_hash: String(suffix || 1).repeat(64),
    system_template_hash: "a".repeat(63) + String(suffix || 1),
    user_template_hash: "b".repeat(63) + String(suffix || 1),
    variable_schema_version: "variables-v1",
    input_schema_version: "input-v1",
    output_schema_version: "output-v1",
    output_schema_hash: "d".repeat(63) + String(suffix || 1),
    application_output_schema_version: "application-output-v1",
    application_output_schema_hash: "e".repeat(63) + String(suffix || 1),
    model_policy_version: "fixture-policy-v1",
    model_policy_hash: "c".repeat(63) + String(suffix || 1),
    test_set_id: "00000000-0000-4000-8000-000000000507",
    test_set_version: 1,
    test_set_hash: "9".repeat(64),
    compiler_version: "geo-prompt-compiler-v2",
    state: {
      id: `00000000-0000-4000-8000-${String(510 + version).padStart(12, "0")}`,
      version: stateVersion,
      status,
      acted_by: status === "draft" ? PROMPT_OWNER_ID : ACTOR_ID,
      acted_at: NOW,
      evidence_ref: evidenceRef
    }
  };
}

function promptReleases() {
  return [
    ...additionalPromptReleases,
    ...(promptCandidateCreated ? [promptRelease({
      id: PROMPT_CANDIDATE_RELEASE_ID,
      version: 2,
      status: promptCandidateStatus,
      stateVersion: promptCandidateStateVersion,
      evidenceRef: promptCandidateEvidenceRef
    })] : []),
    promptRelease({
      id: PROMPT_BASE_RELEASE_ID,
      version: 1,
      status: "frozen",
      stateVersion: 4,
      evidenceRef: `approval:${PROMPT_EVIDENCE_ID}:${"d".repeat(64)}`
    })
  ];
}

function initialPromptDraft() {
  return {
    project_id: PROJECT_ID,
    program_id: PROMPT_PROGRAM_ID,
    display_name: "候选测评生成",
    system_template: "You write concise Australian English reviews for {{channel}}. Use only the supplied evidence.",
    user_template: "Create four candidates for {{subject_id}} in this scenario: {{scenario}}.",
    revision: 1,
    draft_hash: "6".repeat(64),
    base_release_id: PROMPT_BASE_RELEASE_ID,
    candidate_release_id: null,
    updated_by: ACTOR_ID,
    updated_at: NOW
  };
}

function promptReleaseDetail(release) {
  if (!release) return null;
  return {
    ...release,
    system_template: release.id === PROMPT_BASE_RELEASE_ID
      ? "You write concise Australian English reviews for {{channel}}. Use only the supplied evidence."
      : promptDraft.system_template,
    user_template: release.id === PROMPT_BASE_RELEASE_ID
      ? "Create four candidates for {{subject_id}} in this scenario: {{scenario}}."
      : promptDraft.user_template
  };
}

function promptFlows() {
  const configured = {
    flow_key: "synthetic_lab.generation",
    purpose: "synthetic_lab.generation",
    program_kind: "generation",
    group: "synthetic_lab",
    display_name: promptDraft.display_name,
    description: "为测评 Case 生成四个澳洲英文候选。",
    configurable: true,
    context_slots: [
      { key: "subject_id", label: "目标主体", description: "当前任务冻结的产品或品牌主体。", insertion: "{{subject_id}}", source: "runtime_task" },
      { key: "channel", label: "渠道", description: "测评对应的平台渠道。", insertion: "{{channel}}", source: "runtime_task" },
      { key: "scenario", label: "测评场景", description: "当前 Case 的消费场景。", insertion: "{{scenario}}", source: "runtime_task" },
      { key: "approved_facts", label: "批准 Fact", description: "当前主体已批准的 Fact。", insertion: "{{approved_facts}}", source: "runtime_task" },
      { key: "request_json", label: "请求数据", description: "当前任务冻结的完整 JSON 输入。", insertion: "{{request_json}}", source: "runtime_task" }
    ],
    program: promptWorkspaceInitialized ? promptProgram() : null,
    draft: promptWorkspaceInitialized ? promptDraft : null,
    latest_release_version: promptWorkspaceInitialized ? (promptCandidateCreated ? 2 : 1) : null,
    current_release_id: promptWorkspaceInitialized ? promptCurrentReleaseId : null,
    current_release_version: promptWorkspaceInitialized ? promptCurrentReleaseVersion : null,
    candidate_status: promptWorkspaceInitialized && promptDraft.candidate_release_id ? promptCandidateStatus : null,
    latest_test_job_id: promptWorkspaceTestRuns[0]?.job_id || null,
    latest_test_status: promptWorkspaceTestRuns[0]?.status || null,
    latest_test_score: promptWorkspaceTestRuns[0]?.score || null
  };
  const questionAndContent = [
    ["knowledge.question_generation", "测试问题生成", "从冻结维度、Fact 和实体生成 GEO 测试问题。", "question_generation"],
    ["knowledge.rag_grounding", "RAG 问题约束", "根据检索证据约束问题与事实边界。", "rag_grounding"],
    ["placements.generation", "投放内容生成", "根据 Brief、证据和落地页策略生成内容草稿。", "placement_generation"],
    ["placements.simulation", "投放 Prompt 仿真", "在发布前检查投放 Prompt 的拼接与输出预览。", "placement_simulation"]
  ].map(([flowKey, displayName, description, programKind]) => ({
    flow_key: flowKey,
    purpose: flowKey,
    program_kind: programKind,
    group: "question_and_content",
    display_name: displayName,
    description,
    configurable: true,
    context_slots: [
      { key: "request_json", label: "请求数据", description: "当前任务冻结的完整 JSON 输入。", insertion: "{{request_json}}", source: "runtime_task" },
      { key: "facts", label: "事实摘要", description: "允许引用的冻结 Fact 摘要。", insertion: "{{facts}}", source: "runtime_task" },
      { key: "evidence", label: "证据", description: "当前任务冻结的 Fact、来源和证据引用。", insertion: "{{evidence}}", source: "runtime_task" }
    ],
    // The browser fixture intentionally shares the single deterministic
    // editable Draft endpoint. Production gives each flow its own Program;
    // the fixture's responsibility is to verify that all four flows are
    // presented as editable/testable instead of unavailable placeholders.
    program: promptWorkspaceInitialized ? { ...promptProgram(), program_kind: programKind, purpose: flowKey } : null,
    draft: promptWorkspaceInitialized ? { ...promptDraft, display_name: displayName } : null,
    latest_release_version: promptWorkspaceInitialized ? (promptCandidateCreated ? 2 : 1) : null,
    current_release_id: promptWorkspaceInitialized ? promptCurrentReleaseId : null,
    current_release_version: promptWorkspaceInitialized ? promptCurrentReleaseVersion : null,
    candidate_status: promptWorkspaceInitialized && promptDraft.candidate_release_id ? promptCandidateStatus : null,
    latest_test_job_id: promptWorkspaceTestRuns[0]?.job_id || null,
    latest_test_status: promptWorkspaceTestRuns[0]?.status || null,
    latest_test_score: promptWorkspaceTestRuns[0]?.score || null
  }));
  return [configured, ...questionAndContent];
}

function difyWorkflowRuntimes() {
  const workflows = [
    ["knowledge.question_generation", "测试问题生成"],
    ["knowledge.rag_grounding", "知识依据生成"],
    ["placements.generation", "投放内容生成"],
    ["placements.simulation", "投放内容仿真"],
    ["synthetic_lab.generation", "合成候选生成"],
    ["synthetic_lab.claim_extraction", "Claim 提取"],
    ["synthetic_lab.conflict_check", "知识冲突检查"],
    ["synthetic_lab.revision", "候选修订"],
    ["synthetic_lab.style_profile", "风格画像生成"],
    ["recommendations.recommendation", "证据建议生成"]
  ];
  return workflows.map(([purpose, label], index) => {
    const runtime = {
      purpose,
      backend: "dify",
      activation_status: "active",
      release_id: `00000000-0000-4000-8000-${String(700 + index).padStart(12, "0")}`,
      release_version: 1,
      release_hash: "a".repeat(64),
      prompt_program_id: PROMPT_PROGRAM_ID,
      prompt_release_id: PROMPT_BASE_RELEASE_ID,
      prompt_release_hash: "b".repeat(64),
      prompt_system_template: null,
      prompt_user_template: null,
      dify_app_id: `fixture-app-${index}`,
      dify_workflow_id: `fixture-workflow-${index}`,
      dsl_hash: "c".repeat(64),
      configured_model: "deepseek-chat",
      model_provider: "langgenius/deepseek/deepseek",
      binding_version: 1,
      activated_at: NOW,
      last_attempt_status: "succeeded",
      last_attempt_kind: "canary",
      last_attempt_at: NOW,
      last_error_code: null,
      last_error_message: null,
      console_url: `http://localhost:15000/app/fixture-app-${index}/workflow`,
      published_workflow_hash: "d".repeat(64),
      published_snapshot_hash: "e".repeat(64),
      published_prompt_nodes: [{
        node_id: `llm-${index}`,
        title: label,
        model_provider: "langgenius/deepseek/deepseek",
        model_name: "deepseek-chat",
        model_mode: "chat",
        completion_params: { temperature: 0.1 },
        messages: [
          { role: "system", text: `Dify 托管的 ${label} System Prompt。` },
          { role: "user", text: "请使用 {{#geo_start.geo_context_json#}} 完成任务。" }
        ]
      }],
      published_input_variables: [{
        name: "geo_context_json", label: "业务上下文 JSON", type: "paragraph",
        required: true, description: "当前任务的结构化业务数据。"
      }],
      published_graph_nodes: [
        { node_id: "start", type: "start", title: "输入" },
        { node_id: `llm-${index}`, type: "llm", title: label }
      ],
      published_at: NOW,
      observed_at: NOW,
      sync_status: "current",
      sync_error: null
    };
    if (difyRuntimeScenario === "style-drifted" && purpose === "synthetic_lab.style_profile") {
      return {
        ...runtime,
        sync_status: "drifted",
        sync_error: "Dify 已发布工作流与冻结快照不一致。"
      };
    }
    if (difyRuntimeScenario === "recommendation-blocked" && purpose === "recommendations.recommendation") {
      return {
        ...runtime,
        activation_status: "blocked_secret",
        sync_error: "冻结的 Dify API 凭据已撤销。"
      };
    }
    if (difyRuntimeScenario === "migration-pending" && [
      "synthetic_lab.style_profile",
      "recommendations.recommendation"
    ].includes(purpose)) {
      return {
        ...runtime,
        backend: "native",
        activation_status: "not_configured",
        release_id: null,
        release_version: null,
        release_hash: null,
        prompt_program_id: null,
        prompt_release_id: null,
        prompt_release_hash: null,
        dify_app_id: null,
        dify_workflow_id: null,
        dsl_hash: null,
        configured_model: null,
        model_provider: null,
        binding_version: null,
        activated_at: null,
        last_attempt_status: null,
        last_attempt_kind: null,
        last_attempt_at: null,
        console_url: null,
        published_workflow_hash: null,
        published_snapshot_hash: null,
        published_prompt_nodes: [],
        published_input_variables: [],
        published_graph_nodes: [],
        published_at: null,
        observed_at: null,
        sync_status: "not_observed",
        sync_error: null
      };
    }
    return runtime;
  });
}

function packageVersion() {
  return {
    id: PACKAGE_VERSION_ID, project_id: PROJECT_ID, campaign_id: CAMPAIGN_A_ID,
    opportunity_id: OPPORTUNITY_A_ID, destination_id: DESTINATION_A_ID,
    package_id: PACKAGE_ID, prompt_bundle_id: BUNDLE_ID, version_number: 1,
    base_version_id: null, workflow_status: "approved",
    content_json: { title: "Fixture mower review" },
    rendered_text: "Fixture mower review with governed product evidence.",
    content_hash: "6".repeat(64), edited_by: ACTOR_ID,
    edit_reason: "Fixture approval", generated_by_job_id: null
  };
}

function publicationSubmission() {
  const latest = publicationVerificationAttempts[0] || null;
  return {
    id: SUBMISSION_ID, project_id: PROJECT_ID, campaign_id: CAMPAIGN_A_ID,
    opportunity_id: OPPORTUNITY_A_ID, destination_id: DESTINATION_A_ID,
    publication_request_id: PUBLICATION_ID, status: submissionStatus,
    idempotency_key: "fixture-submission", submitted_by: ACTOR_ID,
    provider_submission_id: "fixture-manual-post", submitted_url: submittedUrl,
    url_backfilled_at: submittedUrl ? NOW : null,
    url_backfilled_by: submittedUrl ? ACTOR_ID : null,
    verification_result: latest ? {
      schema_version: "publication-verification-projection-v2",
      attempt_id: latest.id, outcome: latest.outcome,
      verifier_version: latest.verifier_version, result_hash: latest.result_hash
    } : null
  };
}

function verificationAttempt(passed) {
  verificationAttemptNumber += 1;
  const failedCheck = "approved_content";
  const checks = [
    "input_contract", "public_url", "redirect_policy", "http_2xx",
    "html_response", "approved_content", "required_disclosures", "expected_links"
  ].map((name) => ({
    name,
    passed: passed || name !== failedCheck,
    failure_code: !passed && name === failedCheck ? "approved_content_missing" : null
  }));
  return {
    id: `00000000-0000-4000-8000-${String(200 + verificationAttemptNumber).padStart(12, "0")}`,
    project_id: PROJECT_ID, campaign_id: CAMPAIGN_A_ID,
    opportunity_id: OPPORTUNITY_A_ID, submission_id: SUBMISSION_ID,
    job_id: `00000000-0000-4000-8000-${String(300 + verificationAttemptNumber).padStart(12, "0")}`,
    attempt_number: 1, verifier_version: "publication-url-verifier-v2",
    outcome: passed ? "passed" : "failed", checked_at: NOW,
    status_code: 200, final_url: submittedUrl, metadata_hash: "7".repeat(64),
    body_hash: "8".repeat(64), visible_text_hash: "9".repeat(64),
    content_rule_hash: "b".repeat(64), verification_rule_hash: "c".repeat(64),
    redirect_count: 0, checks,
    failures: passed ? [] : [{
      code: "approved_content_missing", disposition: "permanent",
      check: failedCheck, retryable: false
    }],
    error_code: passed ? null : "approved_content_missing",
    failure_disposition: passed ? null : "permanent",
    result_hash: (passed ? "e" : "d").repeat(64), created_at: NOW
  };
}

function unboundBinding() {
  return {
    id: BINDING_ANCHOR_ID,
    project_id: PROJECT_ID,
    campaign_id: CAMPAIGN_A_ID,
    opportunity_id: OPPORTUNITY_A_ID,
    destination_id: DESTINATION_A_ID,
    binding_version: 1,
    previous_binding_id: null,
    status: "unbound",
    changed_by: null,
    changed_at: NOW,
    reason: "Opportunity created explicitly unbound",
    template_release_id: null,
    skill_key: null,
    skill_version_id: null,
    release_version: null,
    release_hash: null
  };
}

const campaigns = [
  {
    id: CAMPAIGN_A_ID,
    project_id: PROJECT_ID,
    market_profile_id: MARKET_ID,
    primary_product_entity_id: PRODUCT_ID,
    name: "AU Baseline Campaign",
    objective: "recommendation_influence",
    status: "active"
  },
  {
    id: CAMPAIGN_B_ID,
    project_id: PROJECT_ID,
    market_profile_id: MARKET_ID,
    primary_product_entity_id: PRODUCT_ID,
    name: "Next Campaign",
    objective: "recommendation_influence",
    status: "active"
  }
];

const destinations = [
  {
    id: DESTINATION_A_ID,
    project_id: PROJECT_ID,
    publication_channel: "owned_site",
    destination_key: "brand-site-au",
    canonical_url: "https://example.test/au",
    canonical_host: "example.test",
    allowed_hosts: ["example.test"],
    destination_account_id: null,
    operation_mode: "manual",
    policy_status: "approved"
  },
  {
    id: DESTINATION_B_ID,
    project_id: PROJECT_ID,
    publication_channel: "reddit",
    destination_key: "reddit-au",
    canonical_url: "https://www.reddit.com/r/example",
    canonical_host: "www.reddit.com",
    allowed_hosts: ["www.reddit.com"],
    destination_account_id: null,
    operation_mode: "manual",
    policy_status: "approved"
  }
];

const protocol = {
  id: PROTOCOL_A_ID,
  project_id: PROJECT_ID,
  campaign_id: CAMPAIGN_A_ID,
  market_profile_id: MARKET_ID,
  name: "OpenAI AU frozen baseline",
  platform: "chatgpt_search",
  locale: "en-AU",
  device: "desktop",
  sample_size: 3,
  minimum_valid_repeats: 3,
  window_days: 28,
  status: "frozen",
  protocol_hash: HASH,
  created_at: NOW,
  approved_at: NOW,
  frozen_at: NOW,
  source_strata: [{
    capture_method: "manual_ui",
    platform: "openai",
    platform_detail: null,
    surface: "chatgpt_search",
    surface_kind: "consumer_ui",
    surface_detail: null,
    source_contract_version: "geo-observation-source-v2",
    engine: "openai",
    configured_model: { state: "not_disclosed", value: null },
    reported_model: { state: "not_disclosed", value: null },
    locale: "en-AU",
    region: "AU",
    language: "en",
    device: "desktop",
    client_kind: "browser",
    search_enabled: true,
    search_mode: "live_web"
  }],
  source_strata_hash: SOURCE_STRATA_INVENTORY_HASH,
  statistics_method_version: "geo-observation-statistics-v2",
  statistics_contract_version: "geo-observation-statistics-v2",
  question_set_id: null,
  question_set_hash: null,
  question_set_bound_by: null,
  question_set_bound_at: null
};

function draftQuestionProtocol() {
  return {
    ...protocol,
    id: PROTOCOL_DRAFT_ID,
    name: "GEO question evaluation draft",
    status: "draft",
    protocol_hash: null,
    approved_at: null,
    frozen_at: null,
    question_set_id: null,
    question_set_hash: null,
    question_set_bound_by: null,
    question_set_bound_at: null
  };
}

questionProtocol = draftQuestionProtocol();

function questionGeneration(created = false) {
  const coverage = questionGenerationMode === "coverage_pack";
  const base = {
    job_id: QUESTION_JOB_ID,
    project_id: PROJECT_ID,
    campaign_id: CAMPAIGN_A_ID,
    status: "succeeded",
    input_hash: "1a".repeat(32),
    dimension_count: coverage ? 100 : 1,
    generation_mode: questionGenerationMode,
    coverage_profile: coverage ? "au-cross-engine-balanced-v1" : null,
    target_count: coverage ? 100 : null
  };
  return created ? { ...base, fact_input_count: 1, entity_input_count: 0 } : {
    ...base,
    error_code: null,
    configured_model: "deepseek-v4-flash",
    execution_backend: coverage ? "hybrid" : "dify",
    actual_model: "deepseek-chat",
    model_call_budget: 60,
    adapter_release: "project-native-rag-v1",
    semantic_duplicate_threshold: 0.92,
    artifact_uri: `s3://geo-fixture/question-generations/${QUESTION_JOB_ID}.json`,
    artifact_hash: "9a".repeat(32),
    product_entity_id: coverage ? PRODUCT_ID : null,
    product_category: coverage ? "robotic_lawn_mower" : null,
    product_name_snapshot: coverage ? "Fixture Mower" : null,
    coverage_profile_hash: coverage ? "8a".repeat(32) : null,
    candidate_count: coverage ? 100 : 2,
    supported_dimension_count: coverage ? 100 : 1,
    possible_duplicate_count: coverage ? 0 : 1,
    batch_count: coverage ? 10 : 1,
    completed_batch_count: coverage ? 10 : 1,
    checkpoint_candidate_count: coverage ? 100 : 2,
    generated_at: NOW,
    created_at: NOW
  };
}

function questionCandidates() {
  const common = {
    project_id: PROJECT_ID,
    campaign_id: CAMPAIGN_A_ID,
    generated_by_job_id: QUESTION_JOB_ID,
    dimension_key: "au-homeowner-consideration-chatgpt",
    ordinal: 1,
    turn_index: 1,
    parent_candidate_id: null,
    query_text_hash: "2a".repeat(32),
    original_query_text: "Which robotic mower is reliable for a medium Australian lawn?",
    original_query_text_hash: "2a".repeat(32),
    revision_id: null,
    revision_number: null,
    was_edited: false,
    brand_scope: "non_brand",
    coverage_role: null,
    topic_cluster: null,
    funnel: "consideration",
    query_kind: "recommendation",
    subject: "robotic lawn mower",
    fact_source_ids: [FACT_ID],
    entity_source_ids: [],
    created_at: NOW
  };
  return [{
    ...common,
    id: QUESTION_CANDIDATE_ID,
    variant_index: 1,
    query_text: "Which robotic mower is reliable for a medium Australian lawn?",
    semantic_fingerprint: "reliable robotic mower for medium Australian lawn",
    dedup_status: "unique",
    nearest_candidate_id: null,
    nearest_similarity: null,
    workflow_status: questionCandidateStatus,
    review_notes: questionCandidateNotes,
    reviewed_at: questionCandidateStatus === "pending_review" ? null : NOW
  }, {
    ...common,
    id: QUESTION_DUPLICATE_ID,
    ordinal: 1,
    variant_index: 2,
    query_text: "What reliable robot mower suits a medium lawn in Australia?",
    original_query_text: "What reliable robot mower suits a medium lawn in Australia?",
    query_text_hash: "2b".repeat(32),
    semantic_fingerprint: "reliable robotic mower for medium Australian lawn",
    dedup_status: "possible_duplicate",
    nearest_candidate_id: QUESTION_CANDIDATE_ID,
    nearest_similarity: 0.9472,
    workflow_status: "pending_review",
    review_notes: null,
    reviewed_at: null
  }];
}

const COVERAGE_TOPICS = [
  "buying_priorities", "property_fit", "setup_installation", "performance",
  "navigation_coverage", "safety_control", "maintenance", "reliability",
  "ownership_cost", "local_support"
];

function coverageCandidates() {
  return Array.from({ length: 100 }, (_, offset) => {
    const ordinal = offset + 1;
    const local = offset % 10;
    const topic = COVERAGE_TOPICS[Math.floor(offset / 10)];
    const role = local < 5
      ? "category_benchmark"
      : local < 9 ? "product_fit" : "brand_control";
    const id = `00000000-0000-4000-9000-${String(ordinal).padStart(12, "0")}`;
    const original = role === "brand_control"
      ? `How suitable is Fixture Mower for ${topic} in Australia?`
      : `Which robotic mower option suits ${topic} need ${ordinal} in Australia?`;
    const edited = questionCandidateEdits.get(id);
    const text = edited || original;
    return {
      id,
      project_id: PROJECT_ID,
      campaign_id: CAMPAIGN_A_ID,
      generated_by_job_id: QUESTION_JOB_ID,
      dimension_key: `au-cross-engine-balanced-v1:${topic}:${role}:${local + 1}`,
      ordinal,
      variant_index: 1,
      turn_index: 1,
      parent_candidate_id: null,
      query_text: text,
      query_text_hash: `${(ordinal % 10).toString(16)}`.repeat(64),
      original_query_text: original,
      original_query_text_hash: "a".repeat(64),
      revision_id: edited ? `10000000-0000-4000-9000-${String(ordinal).padStart(12, "0")}` : null,
      revision_number: edited ? 1 : null,
      was_edited: Boolean(edited),
      semantic_fingerprint: `${topic} ${ordinal}`,
      dedup_status: "unique",
      nearest_candidate_id: null,
      nearest_similarity: null,
      workflow_status: "pending_review",
      review_notes: null,
      reviewed_at: null,
      brand_scope: role === "brand_control" ? "brand" : "non_brand",
      coverage_role: role,
      topic_cluster: topic,
      funnel: local === 0 || local === 5 ? "awareness"
        : local === 4 ? "retention" : local >= 8 ? "decision" : "consideration",
      query_kind: local < 2 || local === 5 ? "recommendation"
        : local === 2 || local === 7 ? "comparison" : local === 4 ? "support" : "research",
      subject: role === "brand_control" ? "Fixture Mower" : "robot lawn mower",
      fact_source_ids: [FACT_ID],
      entity_source_ids: [],
      created_at: NOW
    };
  });
}

function questionSet() {
  if (questionSetStatus === null) return null;
  const coverage = questionGenerationMode === "coverage_pack";
  const included = coverage
    ? coverageCandidates().filter((item) => coverageIncludedIds.includes(item.id))
    : questionCandidates().slice(0, 1);
  return {
    id: QUESTION_SET_ID,
    project_id: PROJECT_ID,
    campaign_id: CAMPAIGN_A_ID,
    series_id: QUESTION_SET_ID,
    previous_version_id: null,
    version_number: 1,
    generated_by_job_id: QUESTION_JOB_ID,
    name: "AU robotic mower evaluation",
    status: questionSetStatus,
    dimension_count: coverage ? 100 : 1,
    covered_dimension_count: included.length,
    possible_duplicate_count: 0,
    coverage_ratio: included.length / (coverage ? 100 : 1),
    duplicate_ratio: 0,
    content_hash: questionSetStatus === "frozen" ? "3a".repeat(32) : null,
    created_at: NOW,
    approved_at: questionSetStatus === "draft" ? null : NOW,
    frozen_at: questionSetStatus === "frozen" ? NOW : null,
    items: included.map((candidate, index) => ({
      id: coverage
        ? `20000000-0000-4000-9000-${String(index + 1).padStart(12, "0")}`
        : QUESTION_SET_ITEM_ID,
      ordinal: index + 1,
      question_candidate_id: candidate.id,
      dimension_key: candidate.dimension_key,
      query_text_snapshot: candidate.query_text,
      query_text_hash: candidate.query_text_hash,
      query_kind_snapshot: candidate.query_kind,
      query_cluster_key: candidate.topic_cluster || "robot-mower-reliability-au",
      source_lineage_hash: "4a".repeat(32),
      brand_scope_snapshot: candidate.brand_scope,
      coverage_role_snapshot: candidate.coverage_role,
      topic_cluster_snapshot: candidate.topic_cluster,
      funnel_snapshot: candidate.funnel
    }))
  };
}

function createQuestionSimulation(payload) {
  const set = questionSet();
  const item = set.items[0];
  return {
    id: QUESTION_SIMULATION_ID,
    project_id: PROJECT_ID,
    campaign_id: CAMPAIGN_A_ID,
    opportunity_id: OPPORTUNITY_A_ID,
    destination_id: DESTINATION_A_ID,
    destination_policy_version_id: null,
    template_release_id: RELEASE_ID,
    prompt_release_binding_id: BINDING_ID,
    prompt_release_binding_version: 2,
    skill_version_id: SKILL_VERSION_ID,
    release_version: 5,
    release_hash: "d".repeat(64),
    primary_brand_entity_id: BRAND_ID,
    product_entity_id: PRODUCT_ID,
    requested_by: ACTOR_ID,
    authenticity_mode: payload.authenticity_mode,
    input_hash: "5a".repeat(32),
    test_only: true,
    publication_eligible: false,
    created_at: NOW,
    generation_job_id: QUESTION_SIMULATION_JOB_ID,
    generation_status: "succeeded",
    configured_model: payload.configured_model,
    model_call_budget: payload.model_call_budget,
    artifact_status: "finalized",
    artifact_uri: `s3://geo-fixture/prompt-simulations/${QUESTION_SIMULATION_ID}.json`,
    storage_key: `prompt-simulations/${QUESTION_SIMULATION_ID}.json`,
    output_hash: "6a".repeat(32),
    manifest_hash: "7a".repeat(32),
    model_response_hash: "8a".repeat(32),
    simulation_purpose: "geo_question_test",
    question_set_id: QUESTION_SET_ID,
    question_set_hash: set.content_hash,
    question_set_item_id: QUESTION_SET_ITEM_ID,
    question_candidate_id: QUESTION_CANDIDATE_ID,
    input_snapshot: {
      brief: {
        goals: payload.goals,
        constraints: payload.constraints
      },
      evidence_items: payload.evidence_item_ids.map((id) => ({ id })),
      client_variables: payload.variables,
      question_binding: {
        question_set_id: QUESTION_SET_ID,
        question_set_hash: set.content_hash,
        item_id: QUESTION_SET_ITEM_ID,
        candidate_id: QUESTION_CANDIDATE_ID,
        question_text: item.query_text_snapshot,
        dimension_key: item.dimension_key,
        source_fact_ids: [FACT_ID],
        source_entity_ids: []
      }
    },
    artifact_manifest: {
      question_binding: { question_set_id: QUESTION_SET_ID, item_id: QUESTION_SET_ITEM_ID },
      output: {
        rendered_text: "Fixture Mower is one evidence-grounded option for the stated lawn scenario.",
        claims: [{ text: "Supports the evaluated lawn scenario", evidence_item_ids: [EVIDENCE_ID] }]
      }
    }
  };
}

function legacySimulation() {
  return {
    id: LEGACY_SIMULATION_ID,
    project_id: PROJECT_ID,
    campaign_id: null,
    opportunity_id: null,
    destination_id: DESTINATION_A_ID,
    destination_policy_version_id: null,
    template_release_id: RELEASE_ID,
    prompt_release_binding_id: null,
    prompt_release_binding_version: null,
    skill_version_id: SKILL_VERSION_ID,
    release_version: 2,
    release_hash: "9a".repeat(32),
    primary_brand_entity_id: BRAND_ID,
    product_entity_id: PRODUCT_ID,
    requested_by: ACTOR_ID,
    authenticity_mode: "synthetic_testimonial",
    input_hash: "9b".repeat(32),
    test_only: true,
    publication_eligible: false,
    created_at: "2025-12-01T02:00:00Z",
    generation_job_id: LEGACY_SIMULATION_JOB_ID,
    generation_status: "succeeded",
    configured_model: "legacy-fixture-model",
    model_call_budget: 1,
    artifact_status: "finalized",
    artifact_uri: `s3://geo-fixture/prompt-simulations/${LEGACY_SIMULATION_ID}.json`,
    storage_key: `prompt-simulations/${LEGACY_SIMULATION_ID}.json`,
    output_hash: "9c".repeat(32),
    manifest_hash: "9d".repeat(32),
    model_response_hash: "9e".repeat(32),
    input_snapshot: { binding_contract_version: "legacy-v1" },
    artifact_manifest: {
      binding_contract_version: "legacy-v1",
      output: {
        rendered_text: "Migrated legacy simulation remains available for audit and download.",
        claims: []
      }
    },
    simulation_purpose: "content_preview",
    question_set_id: null,
    question_set_hash: null,
    question_set_item_id: null,
    question_candidate_id: null
  };
}

function send(response, value, status = 200) {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "X-Correlation-ID": "browser-fixture"
  });
  response.end(JSON.stringify(value));
}

function sendZip(response) {
  response.writeHead(200, {
    "Content-Type": "application/zip",
    "Content-Disposition": `attachment; filename="geo-project-export-${PROJECT_EXPORT_JOB_ID}.zip"`,
    ETag: "f".repeat(64)
  });
  response.end(Buffer.from("fixture-project-export-zip"));
}

function sendSimulationArtifact(response, simulation) {
  response.writeHead(200, {
    "Content-Type": "application/json",
    "Content-Disposition": `attachment; filename="geo-prompt-simulation-${simulation.id}.json"`,
    ETag: simulation.manifest_hash,
    "X-GEO-Test-Only": "true",
    "X-GEO-Publication-Eligible": "false"
  });
  response.end(JSON.stringify({
    schema_version: "geo-prompt-simulation-artifact-v1",
    simulation_id: simulation.id,
    output: simulation.artifact_manifest.output
  }));
}

async function body(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  if (!chunks.length) return null;
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function loggedRequestBody(path, payload) {
  if (!path.includes("/secrets") || !payload || typeof payload !== "object" || Array.isArray(payload)) {
    return payload;
  }
  return Object.fromEntries(Object.entries(payload).map(([key, value]) => [
    key,
    key === "secret_value" ? "[REDACTED]" : value
  ]));
}

function readiness(campaignId) {
  const channels = ["owned_site", "productreview", "youtube", "reddit", "amazon", "ozbargain", "tiktok", "instagram", "quora"];
  return {
    project_id: PROJECT_ID,
    campaign_id: campaignId,
    ready_count: promptBinding.status === "bound" ? 1 : 0,
    is_ready: false,
    channels: channels.map((publication_channel) => ({
      publication_channel,
      ready: publication_channel === "owned_site" && campaignId === CAMPAIGN_A_ID && promptBinding.status === "bound",
      reasons: publication_channel === "owned_site" && campaignId === CAMPAIGN_A_ID
        ? (promptBinding.status === "bound" ? [] : ["prompt_binding_missing"])
        : ["missing_opportunity"],
      opportunity_id: publication_channel === "owned_site" && campaignId === CAMPAIGN_A_ID
        ? OPPORTUNITY_A_ID
        : null,
      destination_id: publication_channel === "owned_site" && campaignId === CAMPAIGN_A_ID
        ? DESTINATION_A_ID
        : null,
      prompt_binding_id: publication_channel === "owned_site" ? promptBinding.id : null,
      template_release_id: publication_channel === "owned_site" ? promptBinding.template_release_id : null,
      release_version: publication_channel === "owned_site" ? promptBinding.release_version : null,
      release_hash: publication_channel === "owned_site" ? promptBinding.release_hash : null,
      brief_version_id: publication_channel === "owned_site" && campaignId === CAMPAIGN_A_ID ? BRIEF_ID : null,
      evidence_pack_attempt_id: publication_channel === "owned_site" && campaignId === CAMPAIGN_A_ID ? ATTEMPT_ID : null
    }))
  };
}

function observationResponse(payload, protocolId) {
  const raw = payload.source.raw_evidence;
  const sourceStratum = {
    capture_method: payload.capture_method,
    platform: payload.source.platform,
    surface: payload.source.surface,
    surface_kind: payload.source.surface_kind,
    engine: payload.source.run.engine,
    configured_model: payload.source.configured_model,
    reported_model: payload.source.reported_model,
    locale: payload.source.run.locale,
    region: payload.source.run.region,
    language: payload.source.run.language,
    device: payload.source.run.device,
    client_kind: payload.source.run.client_kind,
    search_enabled: payload.source.run.search_enabled,
    search_mode: payload.source.run.search_mode
  };
  return {
    ...payload,
    id: "00000000-0000-4000-8000-000000000081",
    project_id: PROJECT_ID,
    protocol_id: protocolId,
    eligible: true,
    ineligible_reasons: [],
    configured_model: payload.source.configured_model.value,
    provider_reported_model: payload.source.reported_model.value,
    raw_answer: raw.kind === "answer" ? raw.answer : raw.kind === "inline_response" ? JSON.stringify(raw.inline_response) : null,
    raw_result: raw.kind === "inline_response" ? raw.inline_response : {},
    artifact_uri: raw.kind === "artifact" ? raw.artifact_uri : null,
    artifact_hash: raw.kind === "artifact" ? raw.artifact_hash : null,
    ui_surface: payload.source.surface,
    ui_metadata: {},
    confounding_factors: [],
    source: {
      ...payload.source,
      capture_method: payload.capture_method,
      raw_evidence: {
        kind: raw.kind,
        answer: raw.kind === "answer" ? raw.answer : null,
        inline_response: raw.kind === "inline_response" ? raw.inline_response : null,
        artifact_uri: raw.kind === "artifact" ? raw.artifact_uri : null,
        artifact_hash: raw.kind === "artifact" ? raw.artifact_hash : null,
        artifact_verified: raw.kind === "artifact"
      },
      source_contract_version: "geo-observation-source-v2",
      citations_captured: true,
      source_job_id: null,
      model_call_log_id: null,
      test_only: false,
      publication_eligible: true,
      source_badge: "Provider API · OpenAI API"
    },
    source_stratum: sourceStratum,
    source_stratum_hash: SOURCE_STRATUM_HASH,
    query_cluster_key: "robot-mower-recommendation",
    captured_by: ACTOR_ID,
    citations: payload.citations.map((citation, index) => ({
      id: `00000000-0000-4000-8000-${String(90 + index).padStart(12, "0")}`,
      citation_index: index,
      url: citation.url,
      title: citation.title || null,
      destination_id: null,
      submission_id: citation.submission_id || null,
      verification_status: "unknown",
      verified_placement: false
    })),
    payload_hash: "c".repeat(64),
    replayed: false,
    created_at: NOW
  };
}

function knowledgeFact() {
  return {
    id: FACT_ID,
    project_id: PROJECT_ID,
    pipeline_run_id: PIPELINE_RUN_ID,
    source_id: SOURCE_ID,
    source_title: "Fixture product specification",
    chunk_id: CHUNK_ID,
    statement: "Fixture Mower supports medium Australian lawns with governed boundary wire guidance.",
    statement_hash: "4".repeat(64),
    status: factStatus,
    lifecycle_status: "active",
    extractor_release: "project-native-rag-v1",
    reviewed_by: factStatus === "approved" ? ACTOR_ID : null,
    review_notes: factReviewNotes,
    reviewed_at: factStatus === "approved" ? NOW : null,
    created_at: NOW
  };
}

function catalogEvidence() {
  const evidence = promotedEvidence || promotedEvidenceView();
  return {
    ...evidence,
    source_id: SOURCE_ID,
    locator: {
      pipeline_run_id: PIPELINE_RUN_ID,
      document_id: DOCUMENT_ID,
      chunk_id: CHUNK_ID,
      fact_id: FACT_ID
    }
  };
}

function factEvidenceLineage() {
  return {
    project_id: PROJECT_ID,
    pipeline_run_id: PIPELINE_RUN_ID,
    knowledge_source_id: SOURCE_ID,
    knowledge_document_id: DOCUMENT_ID,
    knowledge_chunk_id: CHUNK_ID,
    knowledge_fact_id: FACT_ID,
    evidence_item_id: EVIDENCE_ID,
    evidence_title: promotedEvidence?.title || "Fixture governed mower fact",
    promoted_by: ACTOR_ID,
    promoted_at: NOW,
    idempotency_key: `knowledge-fact-evidence:${PROJECT_ID}:${FACT_ID}`,
    promotion_request_hash: "5".repeat(64),
    lineage_contract_version: "knowledge-fact-evidence-v1",
    source_content_hash: "1".repeat(64),
    document_cleaned_text_hash: "2".repeat(64),
    chunk_text_hash: "3".repeat(64),
    fact_statement_hash: "4".repeat(64),
    evidence_snapshot_hash: "6".repeat(64)
  };
}

function promotedEvidenceView(payload = {}) {
  const publicCitation = payload.public_citation || {};
  return {
    id: EVIDENCE_ID,
    project_id: PROJECT_ID,
    title: payload.title || "Fixture governed mower fact",
    item_type: "approved_fact",
    subject_entity_id: payload.subject_entity_id || PRODUCT_ID,
    subject_role: payload.subject_role || "product",
    snapshot: {
      kind: "text",
      text: knowledgeFact().statement,
      uri: null,
      sha256: "6".repeat(64)
    },
    source_revision: { kind: "content_hash", value: "1".repeat(64) },
    usage_rights: payload.usage_rights || "public_reference",
    confidentiality: payload.confidentiality || "public",
    public_citation: {
      disclosure_allowed: publicCitation.disclosure_allowed ?? true,
      source_url: publicCitation.source_url || "https://example.test/mower/specification",
      source_title: publicCitation.source_title || "Fixture product specification",
      label: publicCitation.label || "Fixture product specification",
      quotation_allowed: publicCitation.quotation_allowed ?? false,
      attribution_required: publicCitation.attribution_required ?? true
    },
    eligible_for_generation: true,
    eligible_for_publication: true,
    created_at: NOW
  };
}

function evidenceProposal() {
  const fact = knowledgeFact();
  return {
    project_id: PROJECT_ID,
    promotable: factStatus === "approved" && !promotedEvidence,
    blockers: factStatus === "approved" ? [] : ["fact_not_approved"],
    fact: {
      id: fact.id,
      status: fact.status,
      statement: fact.statement,
      statement_hash: fact.statement_hash,
      reviewed_by: fact.reviewed_by,
      reviewed_at: fact.reviewed_at
    },
    source: {
      id: SOURCE_ID,
      title: "Fixture product specification",
      source_kind: "url",
      source_url: "https://example.test/mower/specification",
      status: "ready",
      content_hash: "1".repeat(64)
    },
    document: {
      id: DOCUMENT_ID,
      parser_version: "fixture-html-v1",
      cleaned_text_hash: "2".repeat(64)
    },
    chunk: {
      id: CHUNK_ID,
      chunk_index: 0,
      text: fact.statement,
      text_hash: "3".repeat(64),
      status: "active"
    },
    existing: promotedEvidence
      ? { evidence: promotedEvidence, lineage: factEvidenceLineage() }
      : null,
    defaults: {
      title: "Fixture governed mower fact",
      source_url: "https://example.test/mower/specification",
      source_title: "Fixture product specification",
      citation_label: "Fixture product specification"
    }
  };
}

function evidencePackItem() {
  const evidence = promotedEvidence || promotedEvidenceView();
  return {
    id: EVIDENCE_ID,
    item_type: evidence.item_type,
    subject_entity_id: evidence.subject_entity_id,
    subject_role: evidence.subject_role,
    snapshot_hash: evidence.snapshot.sha256,
    usage_rights: evidence.usage_rights,
    confidentiality: evidence.confidentiality,
    public_disclosure_allowed: evidence.public_citation.disclosure_allowed,
    public_source_url: evidence.public_citation.source_url,
    public_source_title: evidence.public_citation.source_title,
    citation_label: evidence.public_citation.label,
    quotation_allowed: evidence.public_citation.quotation_allowed,
    attribution_required: evidence.public_citation.attribution_required,
    knowledge_lineage: factEvidenceLineage()
  };
}

function insufficientMetric(payload) {
  const estimate = { numerator: 0, denominator: 0, share: 0, ci_low: 0, ci_high: 0 };
  return {
    id: "00000000-0000-4000-8000-000000000121",
    project_id: PROJECT_ID,
    protocol_id: PROTOCOL_A_ID,
    campaign_id: CAMPAIGN_A_ID,
    measurement_window: payload.measurement_window,
    capture_method: "manual_ui",
    source_stratum: protocol.source_strata[0],
    source_stratum_hash: payload.source_stratum_hash,
    statistics_contract_version: "geo-observation-statistics-v2",
    query_cluster_key: payload.query_cluster_key,
    analysis_stratum_hash: "8".repeat(64),
    observation_membership_version: "metric-observation-membership-v1",
    observation_membership_hash: "a1".repeat(32),
    observation_membership_count: 0,
    minimum_valid_repeats: 3,
    expected_sample_count: 3,
    sampled_sample_count: 0,
    eligible_sample_count: 0,
    invalid_sample_count: 0,
    missing_sample_count: 3,
    sampling_completion_ratio: 0,
    valid_completion_ratio: 0,
    query_count: 1,
    sufficient_query_count: 0,
    invalid_reason_counts: {},
    declared_confounding_factors: [],
    query_results: [{
      monitoring_query_id: QUERY_A_ID,
      query_text_snapshot: "Which robotic mower is best for a medium Australian lawn?",
      query_cluster_key: payload.query_cluster_key,
      expected_sample_count: 3,
      sampled_sample_count: 0,
      valid_sample_count: 0,
      invalid_sample_count: 0,
      missing_sample_count: 3,
      meets_threshold: false,
      invalid_reason_counts: {},
      confounding_factors: [],
      recommendation: estimate,
      product_mention: estimate,
      placement_citation: estimate,
      competitor: estimate,
      competitive_delta: 0
    }],
    recommendation_share: 0,
    recommendation_ci_low: 0,
    recommendation_ci_high: 0,
    product_mention_share: 0,
    product_mention_ci_low: 0,
    product_mention_ci_high: 0,
    placement_citation_share: 0,
    placement_citation_ci_low: 0,
    placement_citation_ci_high: 0,
    recommendation_query_min: 0,
    recommendation_query_max: 0,
    product_mention_query_min: 0,
    product_mention_query_max: 0,
    placement_citation_query_min: 0,
    placement_citation_query_max: 0,
    worst_query_id: QUERY_A_ID,
    selected_destination_ids: [DESTINATION_A_ID],
    qualified_destination_ids: [DESTINATION_A_ID],
    verified_destination_ids: [],
    qualified_destination_coverage: 1,
    verified_placement_coverage: 0,
    competitive_delta: 0,
    status: "insufficient_evidence",
    confounded_reasons: ["insufficient_valid_repeats"],
    method_version: "geo-observation-statistics-v2",
    input_hash: "7".repeat(64),
    result_hash: "9".repeat(64),
    computed_at: NOW
  };
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url || "/", `http://${request.headers.host || "127.0.0.1"}`);
  const path = url.pathname;
  if (path === "/health") return send(response, { status: "ok" });
  if (path === "/__prompt-workspace" && request.method === "DELETE") {
    promptWorkspaceInitialized = false;
    return send(response, { initialized: false });
  }
  if (path === "/__requests") {
    if (request.method === "DELETE") {
      requests.length = 0;
      observations.length = 0;
      bundles.length = 0;
      metricSnapshots.length = 0;
      promptBinding = unboundBinding();
      factStatus = "pending_review";
      factReviewNotes = null;
      promotedEvidence = null;
      evidencePackRebuilt = false;
      submittedUrl = null;
      submissionStatus = "awaiting_url";
      verificationShouldPass = false;
      verificationAttemptNumber = 0;
      publicationVerificationAttempts.length = 0;
      questionGenerationCreated = false;
      questionGenerationMode = "single_scenario";
      questionCandidateStatus = "pending_review";
      questionCandidateNotes = null;
      questionSetStatus = null;
      coverageIncludedIds = [];
      questionCandidateEdits.clear();
      questionSimulation = null;
      questionProtocol = draftQuestionProtocol();
      projectExportJobStatus = "succeeded";
      projectExportErrorCode = null;
      promptCandidateStatus = "draft";
      promptCandidateStateVersion = 1;
      promptCandidateEvidenceRef = null;
      promptCandidateCreated = false;
      promptWorkspaceInitialized = true;
      promptCurrentReleaseId = PROMPT_BASE_RELEASE_ID;
      promptCurrentReleaseVersion = 1;
      promptDraft = initialPromptDraft();
      promptWorkspaceTestRuns.length = 0;
      promptNextReleaseVersion = 3;
      additionalPromptReleases.length = 0;
      secretActorId = ACTOR_ID;
      secretRole = "owner";
      secretUnavailable = false;
      secretReference = null;
      secretAggregateVersion = 0;
      secretCurrentVersion = null;
      secretVersions.length = 0;
      secretAudits.length = 0;
      difyRuntimeScenario = "default";
      resetSyntheticLabFixture();
      resetRecommendationFixture();
      resetPromptBootstrapFixture();
      return send(response, { reset: true });
    }
    return send(response, requests);
  }
  if (path === "/__legacy_prompt_bundle" && request.method === "POST") {
    const legacyBundle = {
      id: LEGACY_BUNDLE_ID,
      project_id: PROJECT_ID,
      campaign_id: CAMPAIGN_A_ID,
      opportunity_id: OPPORTUNITY_A_ID,
      destination_id: DESTINATION_A_ID,
      brief_version_id: BRIEF_ID,
      evidence_pack_attempt_id: ATTEMPT_ID,
      prompt_release_binding_id: null,
      prompt_release_binding_version: null,
      template_release_id: RELEASE_ID,
      skill_version_id: SKILL_VERSION_ID,
      release_version: 1,
      release_hash: "c".repeat(64),
      bundle_hash: "b".repeat(64),
      storage_key: `prompt-bundles/${LEGACY_BUNDLE_ID}.json`,
      storage_uri: `s3://geo-fixture/prompt-bundles/${LEGACY_BUNDLE_ID}.json`,
      artifact_status: "finalized"
    };
    bundles.push(legacyBundle);
    return send(response, legacyBundle, 201);
  }

  const payload = request.method === "GET" || request.method === "HEAD" ? null : await body(request);
  if (request.method !== "GET" && request.method !== "HEAD") {
    requests.push({
      method: request.method,
      path,
      query: Object.fromEntries(url.searchParams),
      body: loggedRequestBody(path, payload),
      idempotency_key: request.headers["idempotency-key"] || null
    });
  }
  if (path === "/__verification_semantics" && request.method === "POST") {
    verificationShouldPass = payload?.approved_content === true;
    return send(response, { approved_content: verificationShouldPass });
  }
  if (path === "/__dify_runtime_scenario" && request.method === "POST") {
    const scenario = String(payload?.scenario || "");
    if (!["default", "style-drifted", "recommendation-blocked", "migration-pending"].includes(scenario)) {
      return send(response, { detail: "unsupported Dify runtime scenario" }, 422);
    }
    difyRuntimeScenario = scenario;
    return send(response, { scenario });
  }
  if (path === "/__project_export_status" && request.method === "POST") {
    projectExportJobStatus = payload?.status || "succeeded";
    projectExportErrorCode = payload?.error_code || null;
    return send(response, { status: projectExportJobStatus, error_code: projectExportErrorCode });
  }
  if (path === "/__secret_mode" && request.method === "POST") {
    if (payload.actor_id === "actor-a") secretActorId = ACTOR_ID;
    if (payload.actor_id === "actor-b") secretActorId = SECRET_ACTOR_B_ID;
    if (payload.role) secretRole = payload.role;
    if (typeof payload.unavailable === "boolean") secretUnavailable = payload.unavailable;
    return send(response, {
      actor_id: secretActorId,
      role: secretRole,
      unavailable: secretUnavailable
    });
  }

  const base = `/v1/projects/${PROJECT_ID}`;
  if (path === `/v1/jobs/${PROJECT_EXPORT_JOB_ID}`) return send(response, {
    id: PROJECT_EXPORT_JOB_ID,
    kind: "project.export",
    status: projectExportJobStatus,
    created_at: NOW,
    updated_at: NOW,
    result_ref: projectExportJobStatus === "succeeded" ? "project-export.zip" : null,
    error_code: projectExportErrorCode,
    result_details: null
  });
  if (path === "/v1/projects") {
    return send(response, { items: [{ id: PROJECT_ID, key: "geo-browser", name: "GEO Browser Fixture", role: "owner" }], total: 1, limit: 100, offset: 0 });
  }
  if (path === base) return send(response, { id: PROJECT_ID, tenant_id: TENANT_ID, name: "GEO Browser Fixture", status: "active", created_at: NOW, updated_at: NOW });
  if (path === `${base}/entities`) return send(response, [
    { id: PRODUCT_ID, project_id: PROJECT_ID, entity_type: "product", canonical_name: "Fixture Mower", canonical_url: "https://example.test/mower", attributes: {}, status: "active", created_at: NOW },
    { id: BRAND_ID, project_id: PROJECT_ID, entity_type: "brand", canonical_name: "Fixture Brand", canonical_url: "https://example.test", attributes: {}, status: "active", created_at: NOW }
  ]);
  if (path === `${base}/market-profiles`) return send(response, [{ id: MARKET_ID, project_id: PROJECT_ID, market_code: "AU", locale: "en-AU", timezone: "Australia/Sydney", rules: {}, status: "active", created_at: NOW }]);
  if (path === `${base}/evidence-items`) return send(response, promotedEvidence ? [catalogEvidence()] : []);
  if (path === `${base}/invitations`) return send(response, { items: [], total: 0, limit: 100, offset: 0 });
  if (path === `${base}/members`) return send(response, { items: [{ membership_id: "00000000-0000-4000-8000-000000000004", project_id: PROJECT_ID, identity_id: secretActorId, issuer: "browser-fixture", subject: secretActorId, email: "owner@example.test", display_name: "Fixture Owner", role: secretRole, status: "active", created_at: NOW }], total: 1, limit: 100, offset: 0 });
  if (path === "/v1/auth/me") return send(response, { actor_id: secretActorId, tenant_id: TENANT_ID, project_ids: [PROJECT_ID], roles: [secretRole] });
  if (path === `${base}/connectors` && request.method === "GET") return send(response, {
    definitions: [], connections: [], scopes: [], runs: [], connection_tests: []
  });
  if (path === `${base}/browser-capture` && request.method === "GET") return send(response, {
    surface_releases: [], egress_endpoints: [], profiles: [], egress_tests: [],
    drift_events: [], tasks: [], sessions: []
  });
  if (path === `${base}/external-data/reports` && request.method === "GET") return send(response, []);
  if (path === `${base}/attribution` && request.method === "GET") return send(response, {
    policies: [], collectors: [], counts: {}, snapshots: []
  });
  if (path === `${base}/sampling/admission-policies` && request.method === "GET") return send(response, {
    items: [], total: 0
  });
  if (request.method === "GET" && new Set([
    `${base}/alerts`,
    `${base}/sampling/admission-options`,
    `${base}/sampling/suite-input-options`,
    `${base}/sampling/suites`,
    `${base}/sampling/runs`,
    `${base}/analysis/semantic-metrics`,
    `${base}/analysis/metric-protocols`,
    `${base}/analysis/statistical-protocols`,
    `${base}/analysis/comparisons`,
    `${base}/analysis/drift`,
    `${base}/sampling/manual-evidence-imports`,
    `${base}/sampling/surface-parser-releases`,
    `${base}/analysis/reports`
  ]).has(path)) return send(response, { items: [], total: 0 });
  if (path === `${base}/external-data/operational-alert-inputs` && request.method === "GET") return send(response, [{
    id: "00000000-0000-4000-8000-000000000701",
    source_kind: "browser_surface_drift",
    source_id: "00000000-0000-4000-8000-000000000702",
    source_version: 1,
    signal_kind: "browser_build",
    severity: "critical",
    reason_code: "browser_build_drift",
    action_path: `${base.replace("/v1", "")}?tab=external-data&section=browser`,
    payload: { release_suspended: true },
    input_hash: "f".repeat(64),
    observed_at: NOW,
    created_at: NOW
  }]);
  if (path === `${base}/model-gateway/options` && request.method === "GET") {
    const synthetic = syntheticRuntimeOptions();
    const recommendation = recommendationRuntimeOptions();
    const currentManifestId = recommendation.current_manifest_id;
    return send(response, {
      current_manifest_id: currentManifestId,
      items: [...synthetic.items, ...recommendation.items].map((item) => ({
        ...item,
        manifest_id: currentManifestId
      }))
    });
  }
  if (handleSyntheticLabFixture({
    actorId: secretActorId,
    now: NOW,
    path,
    payload,
    projectId: PROJECT_ID,
    request,
    response,
    send
  })) return;
  if (handleRecommendationFixture({
    actorId: secretActorId,
    now: NOW,
    path,
    payload,
    projectId: PROJECT_ID,
    request,
    query: Object.fromEntries(url.searchParams),
    response,
    send
  })) return;
  if (path.endsWith("/prompt-bootstrap/drafts") && request.method === "POST") {
    promptWorkspaceInitialized = true;
  }
  if (handlePromptBootstrapFixture({
    actorId: secretActorId,
    now: NOW,
    path,
    payload,
    projectId: PROJECT_ID,
    request,
    response,
    role: secretRole,
    send
  })) return;
  const secretBase = `${base}/secrets`;
  if (path.startsWith(secretBase) && secretUnavailable) {
    return send(response, { detail: "Secret Store persistence is unavailable" }, 503);
  }
  if (path.startsWith(secretBase) && secretRole !== "owner" && secretRole !== "admin") {
    return send(response, { detail: "Secret Store requires owner or admin" }, 403);
  }
  if (path === secretBase) {
    if (request.method === "POST") {
      if (secretReference) return send(response, { detail: "Secret reference already exists" }, 409);
      if ((payload.reference_id && payload.reference_id !== SECRET_REFERENCE_ID) || !payload.purpose || !payload.secret_value) {
        return send(response, { detail: "Secret request is invalid" }, 422);
      }
      secretReference = {
        reference_id: SECRET_REFERENCE_ID,
        purpose: payload.purpose,
        createdAt: NOW
      };
      secretAggregateVersion = 1;
      secretVersions.push({
        version: 1,
        status: "pending",
        createdBy: secretActorId,
        createdAt: NOW,
        verifiedAt: null,
        activatedAt: null,
        revokedAt: null,
        masterKeyVersion: 7,
        fingerprint: "6".repeat(64)
      });
      appendSecretAudit(1, "reference_created");
      appendSecretAudit(1, "version_staged");
      return send(response, secretVersionView(1), 201);
    }
    const limit = Number(url.searchParams.get("limit") || 20);
    const offset = Number(url.searchParams.get("offset") || 0);
    const items = secretReference ? [secretReferenceView()].slice(offset, offset + limit) : [];
    return send(response, { items, total: secretReference ? 1 : 0, limit, offset });
  }
  if (path === `${secretBase}/audit-events`) {
    const limit = Number(url.searchParams.get("limit") || 50);
    const offset = Number(url.searchParams.get("offset") || 0);
    return send(response, {
      items: secretAudits.slice(offset, offset + limit),
      total: secretAudits.length,
      limit,
      offset
    });
  }
  if (path === `${secretBase}/${SECRET_REFERENCE_ID}`) {
    return send(response, secretReferenceView() || { detail: "Secret reference not found" }, secretReference ? 200 : 404);
  }
  if (path === `${secretBase}/${SECRET_REFERENCE_ID}/versions` && request.method === "POST") {
    if (!secretReference) return send(response, { detail: "Secret reference not found" }, 404);
    if (Number(payload.expected_version) !== secretAggregateVersion) {
      return send(response, { detail: "Secret aggregate changed" }, 409);
    }
    if (!payload.secret_value || secretCurrentVersion === null || secretVersions.some((item) => item.status === "pending")) {
      return send(response, { detail: "Secret rotation is not allowed" }, 409);
    }
    const version = secretVersions.length + 1;
    secretAggregateVersion += 1;
    secretVersions.push({
      version,
      status: "pending",
      createdBy: secretActorId,
      createdAt: NOW,
      verifiedAt: null,
      activatedAt: null,
      revokedAt: null,
      masterKeyVersion: 6 + version,
      fingerprint: String(5 + version).repeat(64)
    });
    appendSecretAudit(version, "version_staged");
    return send(response, secretVersionView(version), 201);
  }
  const secretCommand = path.match(new RegExp(`^${secretBase}/${SECRET_REFERENCE_ID}/versions/(\\d+)/(verify|activate|revoke)$`));
  if (secretCommand && request.method === "POST") {
    const version = Number(secretCommand[1]);
    const command = secretCommand[2];
    const item = secretVersions.find((candidate) => candidate.version === version);
    if (!item) return send(response, { detail: "Secret version not found" }, 404);
    if (Number(payload.expected_version) !== secretAggregateVersion) {
      return send(response, { detail: "Secret aggregate changed" }, 409);
    }
    if (command === "verify") {
      if (item.status !== "pending" || item.verifiedAt) {
        return send(response, { detail: "Secret version cannot be verified" }, 409);
      }
      secretAggregateVersion += 1;
      item.verifiedAt = NOW;
      appendSecretAudit(version, "version_verified");
      return send(response, secretVersionView(version));
    }
    if (command === "activate") {
      if (item.status !== "pending" || !item.verifiedAt) {
        return send(response, { detail: "Secret version cannot be activated" }, 409);
      }
      if (item.createdBy === secretActorId) {
        return send(response, { detail: "Secret creator cannot activate the same version" }, 403);
      }
      const previous = secretVersions.find((candidate) => candidate.version === secretCurrentVersion);
      if (previous) previous.status = "superseded";
      secretAggregateVersion += 1;
      item.status = "active";
      item.activatedAt = NOW;
      secretCurrentVersion = version;
      appendSecretAudit(version, "version_activated");
      return send(response, secretVersionView(version));
    }
    if (item.status === "revoked") {
      return send(response, { detail: "Secret version is already revoked" }, 409);
    }
    secretAggregateVersion += 1;
    item.status = "revoked";
    item.revokedAt = NOW;
    if (secretCurrentVersion === version) secretCurrentVersion = null;
    appendSecretAudit(version, "version_revoked");
    return send(response, secretVersionView(version));
  }
  if (path === `${base}/prompt-flows` && request.method === "GET") {
    const items = promptFlows();
    return send(response, { items, total: items.length });
  }
  if (path === `${base}/dify-workflows` && request.method === "GET") {
    const items = difyWorkflowRuntimes();
    return send(response, { runtime_backend: "dify", items, total: items.length });
  }
  if (path === `${base}/prompt-programs/${PROMPT_PROGRAM_ID}/draft`) {
    if (request.method === "PUT") {
      if (payload.expected_revision !== promptDraft.revision) {
        return send(response, { detail: "Prompt working draft changed after it was read" }, 409);
      }
      promptDraft = {
        ...promptDraft,
        display_name: payload.display_name,
        system_template: payload.system_template,
        user_template: payload.user_template,
        revision: promptDraft.revision + 1,
        draft_hash: "7".repeat(64),
        candidate_release_id: null,
        updated_at: new Date().toISOString()
      };
      return send(response, promptDraft);
    }
    return send(response, promptDraft);
  }
  if (path === `${base}/prompt-programs/${PROMPT_PROGRAM_ID}/render-preview` && request.method === "POST") {
    return send(response, {
      fixture_id: payload.fixture_id || "generation-autonomous-au",
      fixture_label: "澳洲自主测评场景",
      input_value: { subject_id: "fixture-product", channel: "reddit", scenario: "weekend garden care" },
      draft: {
        system_prompt: promptDraft.system_template.replace("{{channel}}", "reddit"),
        user_prompt: promptDraft.user_template
          .replaceAll("{{subject_id}}", "fixture-product")
          .replace("{{scenario}}", "weekend garden care"),
        system_prompt_hash: "1".repeat(64),
        user_prompt_hash: "2".repeat(64)
      },
      current: {
        system_prompt: "You write concise Australian English reviews for reddit. Use only the supplied evidence.",
        user_prompt: "Create four candidates for fixture-product in this scenario: weekend garden care.",
        system_prompt_hash: "3".repeat(64),
        user_prompt_hash: "4".repeat(64)
      },
      current_release_version: promptCurrentReleaseVersion
    });
  }
  if (path === `${base}/prompt-programs/${PROMPT_PROGRAM_ID}/suite-runs` && request.method === "POST") {
    if (payload.expected_revision !== promptDraft.revision) {
      return send(response, { detail: "Prompt working draft changed before testing" }, 409);
    }
    promptCandidateCreated = true;
    promptCandidateStatus = "draft";
    promptCandidateStateVersion = 1;
    promptDraft = { ...promptDraft, candidate_release_id: PROMPT_CANDIDATE_RELEASE_ID };
    const run = {
      job_id: "00000000-0000-4000-8000-000000000509",
      project_id: PROJECT_ID,
      program_id: PROMPT_PROGRAM_ID,
      release_id: PROMPT_CANDIDATE_RELEASE_ID,
      release_version: 2,
      status: "queued",
      requested_at: new Date().toISOString(),
      finished_at: null,
      passed: null,
      score: null,
      result_ref: null,
      error_code: null
    };
    promptWorkspaceTestRuns.unshift(run);
    const candidate = promptReleases().find((item) => item.id === PROMPT_CANDIDATE_RELEASE_ID);
    return send(response, {
      draft: promptDraft,
      candidate_release: candidate,
      job: {
        job_id: run.job_id,
        project_id: PROJECT_ID,
        release_id: PROMPT_CANDIDATE_RELEASE_ID,
        release_hash: candidate.release_hash,
        test_set_id: candidate.test_set_id,
        test_set_version: candidate.test_set_version,
        test_set_hash: candidate.test_set_hash,
        input_hash: "8".repeat(64),
        status: "queued",
        replayed: false
      }
    }, 202);
  }
  if (path === `${base}/prompt-programs/${PROMPT_PROGRAM_ID}/test-runs` && request.method === "GET") {
    const queued = promptWorkspaceTestRuns.find((item) => item.status === "queued");
    if (queued) {
      queued.status = "succeeded";
      queued.finished_at = new Date().toISOString();
      queued.passed = true;
      queued.score = 100;
      queued.result_ref = "s3://fixture/prompt-tests/passed.json";
      promptCandidateStatus = "tested";
      promptCandidateStateVersion = 2;
      promptCandidateEvidenceRef = `prompt-test:${PROMPT_EVIDENCE_ID}:${"d".repeat(64)}`;
    }
    return send(response, { items: promptWorkspaceTestRuns, total: promptWorkspaceTestRuns.length });
  }
  if (path === `${base}/prompt-programs/${PROMPT_PROGRAM_ID}/publish` && request.method === "POST") {
    if (payload.expected_revision !== promptDraft.revision || promptCandidateStatus !== "tested") {
      return send(response, { detail: "Publishing requires the exact current draft to pass its fixed suite" }, 409);
    }
    promptCandidateStatus = "frozen";
    promptCandidateStateVersion = 4;
    promptCurrentReleaseId = PROMPT_CANDIDATE_RELEASE_ID;
    promptCurrentReleaseVersion = 2;
    promptDraft = {
      ...promptDraft,
      base_release_id: PROMPT_CANDIDATE_RELEASE_ID,
      candidate_release_id: null,
      updated_at: new Date().toISOString()
    };
    const release = promptReleases().find((item) => item.id === PROMPT_CANDIDATE_RELEASE_ID);
    return send(response, {
      draft: promptDraft,
      release,
      binding: {
        id: PROMPT_BINDING_ID,
        project_id: PROJECT_ID,
        purpose: "synthetic_lab.generation",
        program_kind: "generation",
        program_id: PROMPT_PROGRAM_ID,
        release_id: PROMPT_CANDIDATE_RELEASE_ID,
        release_version: 2,
        release_hash: release.release_hash,
        frozen_state_id: release.state.id,
        binding_version: 2,
        bound_by: ACTOR_ID,
        bound_at: new Date().toISOString()
      }
    });
  }
  if (path === `${base}/prompt-programs`) {
    if (request.method === "POST") {
      const program = {
        ...promptProgram(),
        id: "00000000-0000-4000-8000-000000000520",
        program_kind: payload.program_kind,
        purpose: payload.purpose,
        owner_id: ACTOR_ID
      };
      const release = {
        ...promptRelease({
          id: "00000000-0000-4000-8000-000000000521",
          version: 1,
          status: "draft",
          stateVersion: 1
        }),
        program_id: program.id,
        program_kind: program.program_kind,
        purpose: program.purpose,
        owner_id: ACTOR_ID
      };
      return send(response, { program, release, replayed: false }, 201);
    }
    return send(response, { items: [promptProgram()], total: 1, limit: 12, offset: 0 });
  }
  if (path === `${base}/prompt-program-test-options` && request.method === "GET") {
    return send(response, {
      items: [{
        runtime_selection_id: PROMPT_RUNTIME_SELECTION_ID,
        runtime_selection_hash: "1".repeat(64),
        runtime_manifest_id: "00000000-0000-4000-8000-000000000511",
        runtime_manifest_hash: "2".repeat(64),
        provider: "openai",
        adapter_release_id: "openai-adapter-v1",
        adapter_release_hash: "3".repeat(64),
        model_release_id: "openai-model-v1",
        model_release_hash: "4".repeat(64),
        configured_model: "gpt-fixture",
        capture_method: "provider_api",
        policy_version_id: "00000000-0000-4000-8000-000000000512",
        policy_version_hash: "5".repeat(64)
      }],
      total: 1
    });
  }
  if (path === `${base}/prompt-programs/${PROMPT_PROGRAM_ID}`) {
    return send(response, promptProgram());
  }
  if (path === `${base}/prompt-programs/${PROMPT_PROGRAM_ID}/releases`) {
    if (request.method === "POST") {
      const version = promptNextReleaseVersion;
      promptNextReleaseVersion += 1;
      const release = promptRelease({
        id: `00000000-0000-4000-8000-${String(520 + version).padStart(12, "0")}`,
        version,
        status: "draft",
        stateVersion: 1
      });
      additionalPromptReleases.unshift(release);
      return send(response, { release, replayed: false }, 201);
    }
    const releases = promptReleases();
    return send(response, { items: releases, total: releases.length, limit: 200, offset: 0 });
  }
  const promptReleaseRead = path.match(new RegExp(`^${base}/prompt-programs/${PROMPT_PROGRAM_ID}/releases/([^/]+)$`));
  if (promptReleaseRead) {
    const release = promptReleases().find((item) => item.id === promptReleaseRead[1]);
    return send(response, promptReleaseDetail(release) || { detail: "Prompt Release not found" }, release ? 200 : 404);
  }
  const promptCommand = path.match(new RegExp(`^${base}/prompt-programs/${PROMPT_PROGRAM_ID}/releases/([^/]+)/(tests|approve|freeze|retire|diff)$`));
  if (promptCommand && request.method === "POST") {
    const releaseId = promptCommand[1];
    const command = promptCommand[2];
    if (releaseId !== PROMPT_CANDIDATE_RELEASE_ID) {
      return send(response, { detail: "Fixture commands target candidate v2" }, 409);
    }
    if (command === "tests") {
      if (promptCandidateStatus !== "draft") return send(response, { detail: "Release is not draft" }, 409);
      if (payload.runtime_selection_id !== PROMPT_RUNTIME_SELECTION_ID
          || "runtime_manifest_id" in payload
          || "adapter_release_id" in payload
          || "model_release_id" in payload
          || "provider" in payload) {
        return send(response, { detail: "Prompt test runtime selection contract changed" }, 422);
      }
      promptCandidateStatus = "tested";
      promptCandidateStateVersion += 1;
      const evidenceHash = "d".repeat(64);
      promptCandidateEvidenceRef = `prompt-test:${PROMPT_EVIDENCE_ID}:${evidenceHash}`;
      return send(response, {
        job_id: "00000000-0000-4000-8000-000000000509",
        project_id: PROJECT_ID,
        release_id: PROMPT_CANDIDATE_RELEASE_ID,
        release_hash: "b".repeat(64),
        test_set_id: payload.test_set_id,
        test_set_version: payload.test_set_version,
        test_set_hash: payload.test_set_hash,
        input_hash: "e".repeat(64),
        status: "queued",
        replayed: false
      }, 202);
    }
    if (command === "approve") {
      if (promptCandidateStatus !== "tested") return send(response, { detail: "Release is not tested" }, 409);
      promptCandidateStatus = "approved";
      promptCandidateStateVersion += 1;
      return send(response, {
        release: promptReleases().find((item) => item.id === PROMPT_CANDIDATE_RELEASE_ID),
        admitted_test_evidence_hash: "d".repeat(64),
        replayed: false
      });
    }
    if (command === "freeze") {
      if (promptCandidateStatus !== "approved") return send(response, { detail: "Release is not approved" }, 409);
      promptCandidateStatus = "frozen";
      promptCandidateStateVersion += 1;
      return send(response, {
        release: promptReleases().find((item) => item.id === PROMPT_CANDIDATE_RELEASE_ID),
        admitted_test_evidence_hash: null,
        replayed: false
      });
    }
    if (command === "retire") {
      if (promptCandidateStatus !== "frozen") return send(response, { detail: "Release is not frozen" }, 409);
      promptCandidateStatus = "retired";
      promptCandidateStateVersion += 1;
      return send(response, {
        release: promptReleases().find((item) => item.id === PROMPT_CANDIDATE_RELEASE_ID),
        admitted_test_evidence_hash: null,
        replayed: false
      });
    }
    const baseRelease = promptReleases().find((item) => item.id === payload.baseline_release_id);
    const candidate = promptReleases().find((item) => item.id === PROMPT_CANDIDATE_RELEASE_ID);
    if (!baseRelease || !candidate) return send(response, { detail: "Diff releases not found" }, 404);
    return send(response, {
      base_release_id: baseRelease.id,
      base_release_hash: baseRelease.release_hash,
      candidate_release_id: candidate.id,
      candidate_release_hash: candidate.release_hash,
      changed_fields: ["user_template"],
      fixed_input_hash: "e".repeat(64),
      base_system_hash: "1".repeat(64),
      candidate_system_hash: "2".repeat(64),
      base_user_hash: "3".repeat(64),
      candidate_user_hash: "4".repeat(64),
      replayed: false
    });
  }
  if (path === `${base}/prompt-program-bindings` && request.method === "GET") {
    return send(response, { items: [], total: 0, limit: 200, offset: 0 });
  }
  if (path === `${base}/prompt-program-bindings` && request.method === "POST") {
    if (promptCandidateStatus !== "frozen") return send(response, { detail: "Release is not frozen" }, 409);
    return send(response, {
      id: PROMPT_BINDING_ID,
      project_id: PROJECT_ID,
      purpose: payload.purpose,
      program_kind: "generation",
      program_id: PROMPT_PROGRAM_ID,
      release_id: PROMPT_CANDIDATE_RELEASE_ID,
      release_version: 2,
      release_hash: promptReleases().find((item) => item.id === PROMPT_CANDIDATE_RELEASE_ID).release_hash,
      frozen_state_id: promptReleases().find((item) => item.id === PROMPT_CANDIDATE_RELEASE_ID).state.id,
      binding_version: Number(payload.expected_version || 0) + 1,
      bound_by: ACTOR_ID,
      bound_at: NOW,
      replayed: false
    });
  }
  if (path === `${base}/project-exports` && request.method === "POST") {
    return send(response, {
      job_id: PROJECT_EXPORT_JOB_ID,
      project_id: PROJECT_ID,
      campaign_id: payload.campaign_id,
      audience: "admin",
      status: projectExportJobStatus,
      content_hash: "f".repeat(64),
      manifest_hash: "e".repeat(64),
      byte_count: 26,
      file_count: 20,
      created_at: NOW,
      finalized_at: projectExportJobStatus === "succeeded" ? NOW : null,
      error_code: projectExportErrorCode,
      download_url: projectExportJobStatus === "succeeded"
        ? `${base}/project-exports/${PROJECT_EXPORT_JOB_ID}/download`
        : null
    }, 202);
  }
  if (path === `${base}/project-exports/${PROJECT_EXPORT_JOB_ID}/download`) {
    if (projectExportJobStatus !== "succeeded") {
      return send(response, { detail: "project export artifact is not ready" }, 409);
    }
    return sendZip(response);
  }

  const knowledgeBase = `${base}/knowledge`;
  if (path === `${knowledgeBase}/sources`) return send(response, [{
    id: SOURCE_ID, project_id: PROJECT_ID, source_kind: "url",
    title: "Fixture product specification",
    source_url: "https://example.test/mower/specification", filename: null,
    media_type: "text/html", status: "ready", content_hash: "1".repeat(64),
    error_code: null, error_detail: null, content_bytes: 2048,
    created_at: NOW, updated_at: NOW
  }]);
  if (path === `${knowledgeBase}/pipeline-runs`) return send(response, [{
    id: PIPELINE_RUN_ID, project_id: PROJECT_ID, source_id: SOURCE_ID,
    source_title: "Fixture product specification", status: "succeeded",
    input_hash: "1".repeat(64), error_code: null, error_detail: null,
    started_at: NOW, completed_at: NOW, created_at: NOW,
    job_id: null, job_status: null
  }]);
  if (path === `${knowledgeBase}/pipeline-runs/${PIPELINE_RUN_ID}/stages`) return send(response, []);
  if (path === `${knowledgeBase}/chunks`) return send(response, [{
    id: CHUNK_ID, pipeline_run_id: PIPELINE_RUN_ID, source_id: SOURCE_ID,
    source_title: "Fixture product specification", document_id: DOCUMENT_ID,
    chunk_index: 0, text: knowledgeFact().statement, text_hash: "3".repeat(64),
    char_count: knowledgeFact().statement.length, status: "active",
    quality_flags: [], created_at: NOW
  }]);
  if (path === `${knowledgeBase}/fact-candidates`) return send(response, [knowledgeFact()]);
  if (path === `${knowledgeBase}/quality-findings`) return send(response, []);
  if (path === `${knowledgeBase}/dashboard`) return send(response, {
    sources: 1, succeeded_runs: 1, failed_runs: 0, active_chunks: 1,
    pending_facts: factStatus === "pending_review" ? 1 : 0, open_findings: 0
  });
  if (path === `${knowledgeBase}/fact-candidates/${FACT_ID}` && request.method === "PATCH") {
    factStatus = payload.decision;
    factReviewNotes = payload.notes || null;
    return send(response, knowledgeFact());
  }
  if (path === `${knowledgeBase}/fact-candidates/${FACT_ID}/evidence-proposal`) {
    return send(response, evidenceProposal());
  }
  if (path === `${knowledgeBase}/fact-candidates/${FACT_ID}/evidence` && request.method === "POST") {
    const outcome = promotedEvidence ? "existing" : "created";
    promotedEvidence ||= promotedEvidenceView(payload);
    return send(response, {
      outcome,
      evidence: promotedEvidence,
      lineage: factEvidenceLineage()
    }, outcome === "created" ? 201 : 200);
  }

  const questionBase = `${knowledgeBase}/campaigns/${CAMPAIGN_A_ID}`;
  if (path === `${questionBase}/question-generations`) {
    if (request.method === "POST") {
      questionGenerationCreated = true;
      questionGenerationMode = payload?.generation_mode || "single_scenario";
      return send(response, questionGeneration(true), 202);
    }
    return send(response, questionGenerationCreated ? [questionGeneration()] : []);
  }
  if (path === `${questionBase}/question-candidates`) {
    const generationJobId = url.searchParams.get("generation_job_id");
    return send(response, questionGenerationCreated && generationJobId === QUESTION_JOB_ID
      ? questionGenerationMode === "coverage_pack" ? coverageCandidates() : questionCandidates()
      : []);
  }
  if (path.match(new RegExp(`${questionBase}/question-candidates/[^/]+/text$`))
    && request.method === "PATCH") {
    const candidateId = path.split("/").at(-2);
    questionCandidateEdits.set(candidateId, payload.query_text);
    return send(response, { outcome: "revised", query_text: payload.query_text });
  }
  if (path === `${questionBase}/question-candidates/${QUESTION_CANDIDATE_ID}`
    && request.method === "PATCH") {
    questionCandidateStatus = payload.decision;
    questionCandidateNotes = payload.notes || null;
    return send(response, questionCandidates()[0]);
  }
  if (path === `${questionBase}/question-candidates/${QUESTION_DUPLICATE_ID}`
    && request.method === "PATCH") {
    return send(response, {
      ...questionCandidates()[1],
      workflow_status: payload.decision,
      review_notes: payload.notes || null,
      reviewed_at: NOW
    });
  }
  if (path === `${questionBase}/question-sets`) {
    if (request.method === "POST") {
      questionSetStatus = "draft";
      return send(response, questionSet(), 201);
    }
    const set = questionSet();
    return send(response, set ? [set] : []);
  }
  if (path === `${questionBase}/question-sets/finalize-coverage-pack`
    && request.method === "POST") {
    coverageIncludedIds = payload.included_candidate_ids;
    questionSetStatus = "frozen";
    return send(response, questionSet(), 201);
  }
  if (path === `${questionBase}/question-sets/${QUESTION_SET_ID}/approve`
    && request.method === "POST") {
    questionSetStatus = "approved";
    return send(response, questionSet());
  }
  if (path === `${questionBase}/question-sets/${QUESTION_SET_ID}/freeze`
    && request.method === "POST") {
    questionSetStatus = "frozen";
    return send(response, questionSet());
  }

  if (path === `${base}/geo/campaigns`) return send(response, campaigns);
  if (path === `${base}/geo/destinations`) return send(response, destinations);
  if (path === `${base}/geo/prompt-skills`) return send(response, [{ id: SKILL_ID, project_id: PROJECT_ID, skill_key: "placement.owned_site.article", status: "active" }]);
  if (path === `${base}/geo/prompt-task-bindings`) return send(response, []);
  if (path === `${base}/geo/prompt-skills/${SKILL_ID}/releases`) return send(response, [{
    id: RELEASE_ID,
    project_id: PROJECT_ID,
    skill_version_id: SKILL_VERSION_ID,
    skill_key: "placement.owned_site.article",
    skill_version: 3,
    release_number: 5,
    release_hash: "d".repeat(64),
    status: "approved",
    state_version: 2,
    approved_by: ACTOR_ID,
    approved_at: NOW,
    revoked_by: null,
    revoked_at: null,
    state_reason: "browser fixture approval",
    source_text: "fixture source",
    system_template: "Use governed evidence only.",
    user_template: "Write the channel draft.",
    variable_schema: {},
    output_schema: { type: "object" },
    compiler_version: "fixture-1"
  }]);

  const campaignId = url.searchParams.get("campaign_id");
  if (path === `${base}/monitoring-protocols`) return send(response,
    campaignId === CAMPAIGN_A_ID ? [protocol, questionProtocol] : []);
  if (path === `${base}/monitoring-metrics`) return send(response, metricSnapshots);
  if (path === `${base}/monitoring-reports`) return send(response, []);

  const campaignMatch = path.match(new RegExp(`^${base}/geo/campaigns/([^/]+)/(monitoring-queries|opportunities|placement-readiness)$`));
  if (campaignMatch) {
    const selectedCampaign = campaignMatch[1];
    if (campaignMatch[2] === "monitoring-queries") return send(response, selectedCampaign === CAMPAIGN_A_ID ? [{ id: QUERY_A_ID, project_id: PROJECT_ID, campaign_id: CAMPAIGN_A_ID, market_profile_id: MARKET_ID, query_text: "Which robotic mower is best for a medium Australian lawn?", query_kind: "recommendation", locale: "en-AU", status: "active" }] : []);
    if (campaignMatch[2] === "opportunities") return send(response, selectedCampaign === CAMPAIGN_A_ID ? [{ id: OPPORTUNITY_A_ID, project_id: PROJECT_ID, campaign_id: CAMPAIGN_A_ID, destination_id: DESTINATION_A_ID, opportunity_ref: "owned-site-au", rationale: "Fixture opportunity", status: "qualified", allowed_commands: ["block", "cancel"] }] : []);
    return send(response, readiness(selectedCampaign));
  }
  if (path === `${base}/geo/prompt-simulations`) {
    if (request.method === "POST") {
      questionSimulation = createQuestionSimulation(payload);
      return send(response, {
        simulation: questionSimulation,
        job_id: QUESTION_SIMULATION_JOB_ID,
        status: "succeeded",
        status_url: `/v1/jobs/${QUESTION_SIMULATION_JOB_ID}`
      }, 201);
    }
    if (campaignId === null) return send(response, [legacySimulation()]);
    return send(response,
      campaignId === CAMPAIGN_A_ID && questionSimulation ? [questionSimulation] : []);
  }
  if (path === `${base}/geo/prompt-simulations/${QUESTION_SIMULATION_ID}`) {
    const found = campaignId === CAMPAIGN_A_ID ? questionSimulation : null;
    return send(response, found || {}, found ? 200 : 404);
  }
  if (path === `${base}/geo/prompt-simulations/${LEGACY_SIMULATION_ID}`) {
    const found = campaignId === null ? legacySimulation() : null;
    return send(response, found || {}, found ? 200 : 404);
  }
  if (path === `${base}/geo/prompt-simulations/${QUESTION_SIMULATION_ID}/artifact`) {
    if (campaignId !== CAMPAIGN_A_ID || !questionSimulation) return send(response, {}, 404);
    return sendSimulationArtifact(response, questionSimulation);
  }
  if (path === `${base}/geo/prompt-simulations/${LEGACY_SIMULATION_ID}/artifact`) {
    if (campaignId !== null) return send(response, {}, 404);
    return sendSimulationArtifact(response, legacySimulation());
  }
  if (path === `/v1/jobs/${QUESTION_SIMULATION_JOB_ID}`) return send(response, {
    id: QUESTION_SIMULATION_JOB_ID,
    kind: "prompt_simulation.generate",
    status: "succeeded",
    campaign_id: CAMPAIGN_A_ID,
    created_at: NOW,
    updated_at: NOW,
    error_code: null,
    result_details: { test_only: true, publication_eligible: false },
    result_ref: QUESTION_SIMULATION_ID
  });
  if (path === `${base}/geo/jobs/${QUESTION_SIMULATION_JOB_ID}/events`) return send(response, []);

  if (path === `${base}/monitoring-protocols/${PROTOCOL_A_ID}/queries`) return send(response, [{ id: PROTOCOL_QUERY_A_ID, project_id: PROJECT_ID, protocol_id: PROTOCOL_A_ID, monitoring_query_id: QUERY_A_ID, query_text: "Which robotic mower is best for a medium Australian lawn?", query_kind: "recommendation", locale: "en-AU", ordinal: 1, query_cluster_key: "robot-mower-recommendation" }]);
  if (path === `${base}/monitoring-protocols/${PROTOCOL_A_ID}/citation-targets`) return send(response, []);
  if (path === `${base}/monitoring-protocols/${PROTOCOL_A_ID}/query-suggestions`) return send(response, [{
    id: LEGACY_SUGGESTION_ID,
    project_id: PROJECT_ID,
    protocol_id: PROTOCOL_A_ID,
    status: "suggested",
    query_text: "Which legacy mower recommendation should be retained?",
    query_kind: "recommendation",
    rationale: "Migrated before query clusters became mandatory.",
    query_cluster_key: null,
    monitoring_query_id: null,
    created_at: "2025-12-01T02:00:00Z"
  }]);
  if (path === `${base}/monitoring-protocols/${PROTOCOL_DRAFT_ID}/question-set-binding`
    && request.method === "POST") {
    const set = questionSet();
    questionProtocol = {
      ...questionProtocol,
      question_set_id: set.id,
      question_set_hash: set.content_hash,
      question_set_bound_by: ACTOR_ID,
      question_set_bound_at: NOW
    };
    return send(response, questionProtocol);
  }
  if (path === `${base}/monitoring-protocols/${PROTOCOL_A_ID}/metrics` && request.method === "POST") {
    const metric = insufficientMetric(payload);
    metricSnapshots.splice(0, metricSnapshots.length, metric);
    return send(response, metric, 201);
  }
  if (path === `${base}/monitoring-protocols/${PROTOCOL_A_ID}/observations`) {
    if (request.method === "POST") {
      const item = observationResponse(payload, PROTOCOL_A_ID);
      observations.push(item);
      return send(response, item, 201);
    }
    return send(response, observations.filter((item) => item.campaign_id === campaignId));
  }

  if (path === `${base}/geo/campaigns/${CAMPAIGN_A_ID}/opportunities/${OPPORTUNITY_A_ID}/prompt-release-binding`) return send(response, promptBinding);
  if (path === `${base}/geo/campaigns/${CAMPAIGN_A_ID}/opportunities/${OPPORTUNITY_A_ID}/prompt-release-bindings`) {
    if (request.method === "POST") {
      promptBinding = {
        id: BINDING_ID,
        project_id: PROJECT_ID,
        campaign_id: CAMPAIGN_A_ID,
        opportunity_id: OPPORTUNITY_A_ID,
        destination_id: DESTINATION_A_ID,
        binding_version: 2,
        previous_binding_id: BINDING_ANCHOR_ID,
        status: "bound",
        changed_by: ACTOR_ID,
        changed_at: NOW,
        reason: payload.reason,
        template_release_id: RELEASE_ID,
        skill_key: "placement.owned_site.article",
        skill_version_id: SKILL_VERSION_ID,
        release_version: 5,
        release_hash: "d".repeat(64)
      };
      return send(response, promptBinding, 201);
    }
    return send(response, promptBinding.status === "bound"
      ? [promptBinding, unboundBinding()]
      : [promptBinding]);
  }
  if (path === `${base}/geo/opportunities/${OPPORTUNITY_A_ID}/brief-versions`) return send(response, [{
    id: BRIEF_ID,
    project_id: PROJECT_ID,
    campaign_id: CAMPAIGN_A_ID,
    opportunity_id: OPPORTUNITY_A_ID,
    destination_id: DESTINATION_A_ID,
    brief_id: "00000000-0000-4000-8000-000000000078",
    version_number: 1,
    base_version_id: null,
    goals: { audience: "Australian consumers", intent: "product recommendation", deliverable: "owned-site article" },
    constraints: {},
    content_hash: "f".repeat(64)
  }]);
  if (path === `${base}/geo/brief-versions/${BRIEF_ID}/evidence-pack-attempts`) {
    const attempt = { id: ATTEMPT_ID, project_id: PROJECT_ID, campaign_id: CAMPAIGN_A_ID, opportunity_id: OPPORTUNITY_A_ID, destination_id: DESTINATION_A_ID, brief_version_id: BRIEF_ID, attempt_number: 1, status: "ready", pack_hash: "e".repeat(64), failure_reason: null };
    if (request.method === "POST") {
      evidencePackRebuilt = true;
      return send(response, {
        resource: attempt,
        job_id: EVIDENCE_JOB_ID,
        status: "succeeded",
        status_url: `/v1/jobs/${EVIDENCE_JOB_ID}`
      }, 201);
    }
    return send(response, [attempt]);
  }
  if (path === `${base}/geo/evidence-pack-attempts/${ATTEMPT_ID}`) return send(response, { id: ATTEMPT_ID, project_id: PROJECT_ID, campaign_id: CAMPAIGN_A_ID, opportunity_id: OPPORTUNITY_A_ID, destination_id: DESTINATION_A_ID, brief_version_id: BRIEF_ID, attempt_number: 1, status: "ready", pack_hash: "e".repeat(64), failure_reason: null });
  if (path === `${base}/geo/evidence-pack-attempts/${ATTEMPT_ID}/items`) return send(response, promotedEvidence && evidencePackRebuilt ? [evidencePackItem()] : []);
  if (path === `/v1/jobs/${EVIDENCE_JOB_ID}`) return send(response, {
    id: EVIDENCE_JOB_ID, kind: "evidence_pack", status: "succeeded",
    campaign_id: CAMPAIGN_A_ID, created_at: NOW, updated_at: NOW,
    error_code: null, result_details: {}, result_ref: ATTEMPT_ID
  });
  if (path === `${base}/geo/jobs/${EVIDENCE_JOB_ID}/events`) return send(response, []);
  if (path === `${base}/geo/brief-versions/${BRIEF_ID}/prompt-bundles`) {
    if (request.method === "POST") {
      const bundle = {
        id: BUNDLE_ID,
        project_id: PROJECT_ID,
        campaign_id: CAMPAIGN_A_ID,
        opportunity_id: OPPORTUNITY_A_ID,
        destination_id: DESTINATION_A_ID,
        brief_version_id: BRIEF_ID,
        evidence_pack_attempt_id: ATTEMPT_ID,
        prompt_release_binding_id: BINDING_ID,
        prompt_release_binding_version: 2,
        template_release_id: RELEASE_ID,
        skill_version_id: SKILL_VERSION_ID,
        release_version: 5,
        release_hash: "d".repeat(64),
        bundle_hash: "1".repeat(64),
        storage_key: `prompt-bundles/${BUNDLE_ID}.json`,
        storage_uri: `s3://geo-fixture/prompt-bundles/${BUNDLE_ID}.json`,
        artifact_status: "finalized"
      };
      bundles.push(bundle);
      return send(response, bundle, 201);
    }
    return send(response, bundles);
  }
  if (path === `${base}/geo/opportunities/${OPPORTUNITY_A_ID}/package-versions`) return send(response, [packageVersion()]);
  if (path === `${base}/geo/package-versions/${PACKAGE_VERSION_ID}`) return send(response, packageVersion());
  if (path === `${base}/geo/package-versions/${PACKAGE_VERSION_ID}/claims`) return send(response, []);
  if (path === `${base}/geo/package-versions/${PACKAGE_VERSION_ID}/reviews`) return send(response, []);
  if (path === `${base}/geo/package-versions/${PACKAGE_VERSION_ID}/exports`) return send(response, []);
  if (path === `${base}/geo/package-versions/${PACKAGE_VERSION_ID}/publication-requests`) return send(response, [{
    id: PUBLICATION_ID, project_id: PROJECT_ID, campaign_id: CAMPAIGN_A_ID,
    opportunity_id: OPPORTUNITY_A_ID, package_version_id: PACKAGE_VERSION_ID,
    destination_id: DESTINATION_A_ID, destination_key: "brand-site-au",
    publication_channel: "owned_site", publication_attempt: 1,
    policy_basis: null, restricted_policy_acknowledged: false,
    idempotency_key: "fixture-publication", status: submissionStatus === "verified" ? "published" : "publishing"
  }]);
  if (path === `${base}/geo/publication-requests/${PUBLICATION_ID}/submissions`) return send(response, [publicationSubmission()]);
  if (path === `${base}/geo/submissions/${SUBMISSION_ID}`) return send(response, publicationSubmission());
  if (path === `${base}/geo/submissions/${SUBMISSION_ID}/url` && request.method === "POST") {
    submittedUrl = payload.submitted_url;
    submissionStatus = "submitted";
    return send(response, publicationSubmission());
  }
  if (path === `${base}/geo/submissions/${SUBMISSION_ID}/verification-attempts`) {
    return send(response, publicationVerificationAttempts);
  }
  if (path === `${base}/geo/submissions/${SUBMISSION_ID}/verification-jobs` && request.method === "POST") {
    const attempt = verificationAttempt(verificationShouldPass);
    publicationVerificationAttempts.unshift(attempt);
    submissionStatus = verificationShouldPass ? "verified" : "failed";
    return send(response, {
      job_id: attempt.job_id,
      status: verificationShouldPass ? "succeeded" : "failed",
      status_url: `${base}/geo/jobs/${attempt.job_id}/events?campaign_id=${CAMPAIGN_A_ID}`
    }, 202);
  }
  if (path === `${base}/geo/submissions/${SUBMISSION_ID}/measurements`) return send(response, []);
  if (path === `${base}/geo/measurement-collection-tasks`) return send(response, []);
  if (path === `${base}/geo/destinations/${DESTINATION_A_ID}/policy-reviews`) return send(response, []);

  return send(response, []);
});

server.listen(PORT, "127.0.0.1");
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
