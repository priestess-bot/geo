import { createServer } from "node:http";

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
const BRAND_ID = "00000000-0000-4000-8000-000000000070";
const SKILL_ID = "00000000-0000-4000-8000-000000000071";
const SKILL_VERSION_ID = "00000000-0000-4000-8000-000000000072";
const RELEASE_ID = "00000000-0000-4000-8000-000000000073";
const BINDING_ID = "00000000-0000-4000-8000-000000000074";
const BINDING_ANCHOR_ID = "00000000-0000-4000-8000-000000000079";
const BRIEF_ID = "00000000-0000-4000-8000-000000000075";
const ATTEMPT_ID = "00000000-0000-4000-8000-000000000076";
const BUNDLE_ID = "00000000-0000-4000-8000-000000000077";
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
const NOW = "2026-07-19T02:00:00Z";
const HASH = "a".repeat(64);
const SOURCE_STRATUM_HASH = "e748f50aa9fef8795a832a9e9b5e3734e5ce49fa0fa8534572f8efabc7cf300f";
const SOURCE_STRATA_INVENTORY_HASH = "583e31e9a30b562582c503d872c35014db6d7b41d4c5fac5446eaf47a7e4937b";
const PROJECT_EXPORT_JOB_ID = "00000000-0000-4000-8000-000000000401";

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
let questionCandidateStatus = "pending_review";
let questionCandidateNotes = null;
let questionSetStatus = null;
let questionSimulation = null;
let questionProtocol;

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
  const base = {
    job_id: QUESTION_JOB_ID,
    project_id: PROJECT_ID,
    campaign_id: CAMPAIGN_A_ID,
    status: "succeeded",
    input_hash: "1a".repeat(32),
    dimension_count: 1
  };
  return created ? { ...base, fact_input_count: 1, entity_input_count: 0 } : {
    ...base,
    error_code: null,
    configured_model: "deepseek-v4-flash",
    model_call_budget: 60,
    adapter_release: "project-native-rag-v1",
    semantic_duplicate_threshold: 0.92,
    artifact_uri: `s3://geo-fixture/question-generations/${QUESTION_JOB_ID}.json`,
    artifact_hash: "9a".repeat(32),
    candidate_count: 2,
    supported_dimension_count: 1,
    possible_duplicate_count: 1,
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
    turn_index: 1,
    parent_candidate_id: null,
    query_text_hash: "2a".repeat(32),
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
    variant_index: 2,
    query_text: "What reliable robot mower suits a medium lawn in Australia?",
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

function questionSet() {
  if (questionSetStatus === null) return null;
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
    dimension_count: 1,
    covered_dimension_count: 1,
    possible_duplicate_count: 0,
    coverage_ratio: 1,
    duplicate_ratio: 0,
    content_hash: questionSetStatus === "frozen" ? "3a".repeat(32) : null,
    created_at: NOW,
    approved_at: questionSetStatus === "draft" ? null : NOW,
    frozen_at: questionSetStatus === "frozen" ? NOW : null,
    items: [{
      id: QUESTION_SET_ITEM_ID,
      ordinal: 1,
      question_candidate_id: QUESTION_CANDIDATE_ID,
      dimension_key: "au-homeowner-consideration-chatgpt",
      query_text_snapshot: "Which robotic mower is reliable for a medium Australian lawn?",
      query_text_hash: "2a".repeat(32),
      query_kind_snapshot: "recommendation",
      query_cluster_key: "robot-mower-reliability-au",
      source_lineage_hash: "4a".repeat(32)
    }]
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

async function body(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  if (!chunks.length) return null;
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
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
      questionCandidateStatus = "pending_review";
      questionCandidateNotes = null;
      questionSetStatus = null;
      questionSimulation = null;
      questionProtocol = draftQuestionProtocol();
      return send(response, { reset: true });
    }
    return send(response, requests);
  }

  const payload = request.method === "GET" || request.method === "HEAD" ? null : await body(request);
  if (request.method !== "GET" && request.method !== "HEAD") {
    requests.push({ method: request.method, path, query: Object.fromEntries(url.searchParams), body: payload });
  }
  if (path === "/__verification_semantics" && request.method === "POST") {
    verificationShouldPass = payload?.approved_content === true;
    return send(response, { approved_content: verificationShouldPass });
  }

  const base = `/v1/projects/${PROJECT_ID}`;
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
  if (path === `${base}/members`) return send(response, { items: [{ membership_id: "00000000-0000-4000-8000-000000000004", project_id: PROJECT_ID, identity_id: ACTOR_ID, issuer: "browser-fixture", subject: ACTOR_ID, email: "owner@example.test", display_name: "Fixture Owner", role: "owner", status: "active", created_at: NOW }], total: 1, limit: 100, offset: 0 });
  if (path === "/v1/auth/me") return send(response, { actor_id: ACTOR_ID, tenant_id: TENANT_ID, project_ids: [PROJECT_ID], roles: ["owner"] });
  if (path === `${base}/project-exports` && request.method === "POST") {
    return send(response, {
      job_id: PROJECT_EXPORT_JOB_ID,
      project_id: PROJECT_ID,
      campaign_id: payload.campaign_id,
      audience: "admin",
      status: "succeeded",
      content_hash: "f".repeat(64),
      manifest_hash: "e".repeat(64),
      byte_count: 26,
      file_count: 20,
      created_at: NOW,
      finalized_at: NOW,
      error_code: null,
      download_url: `${base}/project-exports/${PROJECT_EXPORT_JOB_ID}/download`
    }, 202);
  }
  if (path === `${base}/project-exports/${PROJECT_EXPORT_JOB_ID}/download`) {
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
      return send(response, questionGeneration(true), 202);
    }
    return send(response, questionGenerationCreated ? [questionGeneration()] : []);
  }
  if (path === `${questionBase}/question-candidates`) {
    const generationJobId = url.searchParams.get("generation_job_id");
    return send(response, questionGenerationCreated && generationJobId === QUESTION_JOB_ID
      ? questionCandidates() : []);
  }
  if (path === `${questionBase}/question-candidates/${QUESTION_CANDIDATE_ID}`
    && request.method === "PATCH") {
    questionCandidateStatus = payload.decision;
    questionCandidateNotes = payload.notes;
    return send(response, questionCandidates()[0]);
  }
  if (path === `${questionBase}/question-candidates/${QUESTION_DUPLICATE_ID}`
    && request.method === "PATCH") {
    return send(response, {
      ...questionCandidates()[1],
      workflow_status: payload.decision,
      review_notes: payload.notes,
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
    return send(response, questionSimulation ? [questionSimulation] : []);
  }
  if (path === `${base}/geo/prompt-simulations/${QUESTION_SIMULATION_ID}`) {
    return send(response, questionSimulation || {}, questionSimulation ? 200 : 404);
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
  if (path === `${base}/monitoring-protocols/${PROTOCOL_A_ID}/query-suggestions`) return send(response, []);
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
