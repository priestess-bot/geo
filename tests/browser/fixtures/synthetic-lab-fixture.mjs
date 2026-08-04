import { createHash } from "node:crypto";

const BOUNDARY = Object.freeze({
  synthetic: true,
  test_only: true,
  publication_eligible: false
});
const AUTHORIZATION_ID = "00000000-0000-4000-8000-000000000701";
const SOURCE_ID = "00000000-0000-4000-8000-000000000702";
const SOURCE_REVISION_ID = "00000000-0000-4000-8000-000000000703";
const MANUAL_SOURCE_ID = "00000000-0000-4000-8000-000000000721";
const MANUAL_SOURCE_REVISION_ID = "00000000-0000-4000-8000-000000000722";
const MANUAL_PREVIEW_ID = "00000000-0000-4000-8000-000000000723";
const MANUAL_IMPORT_ID = "00000000-0000-4000-8000-000000000724";
const MANUAL_REQUEST_ID = "00000000-0000-4000-8000-000000000725";
const MANUAL_SUBMITTER_ID = "00000000-0000-4000-8000-000000000003";
const PROFILE_ID = "00000000-0000-4000-8000-000000000704";
const PROFILE_VERSION_ID = "00000000-0000-4000-8000-000000000705";
const SUITE_ID = "00000000-0000-4000-8000-000000000706";
const SUITE_VERSION_ID = "00000000-0000-4000-8000-000000000707";
const CREATED_SUITE_ID = "00000000-0000-4000-8000-000000000726";
const CREATED_SUITE_VERSION_ID = "00000000-0000-4000-8000-000000000727";
const CASE_A_ID = "00000000-0000-4000-8000-000000000708";
const CASE_B_ID = "00000000-0000-4000-8000-000000000709";
const PROMPT_RELEASE_ID = "00000000-0000-4000-8000-000000000710";
const RUNTIME_SELECTION_ID = "00000000-0000-4000-8000-000000000713";
const FACT_SNAPSHOT_ID = "00000000-0000-4000-8000-000000000714";
const EXISTING_STYLE_COLLECTION_JOB_ID = "00000000-0000-4000-8000-000000000712";
const COMPLETED_REVIEW_JOB_A_ID = "00000000-0000-4000-8000-000000000716";
const COMPLETED_REVIEW_JOB_B_ID = "00000000-0000-4000-8000-000000000717";
const CANDIDATE_CORPUS_JOB_ID = "00000000-0000-4000-8000-000000000718";
const APPROVED_CORPUS_JOB_ID = "00000000-0000-4000-8000-000000000719";
const QUESTION_SET_ID = "00000000-0000-4000-8000-000000000720";
const DIRECT_SUBJECT_ID = "00000000-0000-4000-8000-000000000750";
const DIRECT_FACT_A_ID = "00000000-0000-4000-8000-000000000751";
const DIRECT_FACT_B_ID = "00000000-0000-4000-8000-000000000752";
const DIRECT_INPUT_SNAPSHOT_ID = "00000000-0000-4000-8000-000000000753";
const DIRECT_SCENARIO_ID = "00000000-0000-4000-8000-000000000754";
const SYNTHETIC_CHANNELS = [
  "owned_site", "amazon", "youtube", "tiktok", "instagram",
  "productreview", "reddit", "ozbargain", "quora"
];

let mode = "normal";
let authorizationState = "approved";
let authorizationVersion = 1;
let profileStatus = "frozen";
let previewStatus = "pending";
let suiteStatus = "draft";
let createdSuite = null;
const jobs = new Map();
const directJobPolls = new Map();
const editedChannelStyles = new Map();

export function resetSyntheticLabFixture() {
  mode = "normal";
  authorizationState = "approved";
  authorizationVersion = 1;
  profileStatus = "frozen";
  previewStatus = "pending";
  suiteStatus = "draft";
  createdSuite = null;
  jobs.clear();
  directJobPolls.clear();
  editedChannelStyles.clear();
}

export function handleSyntheticLabFixture({
  actorId,
  now,
  path,
  payload,
  projectId,
  request,
  response,
  send
}) {
  if (path === "/__synthetic_mode" && request.method === "POST") {
    mode = [
      "normal", "governance", "legacy_profile", "manual_approval_rejected",
      "manual_import_unavailable", "empty", "unavailable", "conflict"
    ].includes(payload?.mode)
      ? payload.mode
      : "normal";
    authorizationState = mode === "governance" ? "not_assessed" : "approved";
    profileStatus = mode === "governance" ? "in_review" : "frozen";
    send(response, { mode });
    return true;
  }
  const base = `/v1/projects/${projectId}/synthetic-lab`;
  if (path === `/v1/projects/${projectId}/model-gateway/options` && request.method === "GET") {
    send(response, syntheticRuntimeOptions());
    return true;
  }
  if (!path.startsWith(base)) return false;
  if (mode === "unavailable") {
    send(response, { detail: "Synthetic Lab persistence is unavailable" }, 503);
    return true;
  }
  if (mode === "conflict" && request.method === "POST") {
    send(response, { detail: "fixture version conflict", correlation_id: "synthetic-conflict" }, 409);
    return true;
  }
  const empty = mode === "empty";
  if (path === `${base}/direct-generation/options` && request.method === "GET") {
    send(response, directGenerationOptions(projectId, empty));
    return true;
  }
  if (path === `${base}/channel-styles` && request.method === "GET") {
    send(response, page(empty ? [] : channelStyles(projectId)));
    return true;
  }
  const channelStyleRoute = path.match(
    new RegExp(`^${base}/channel-styles/([^/]+)/versions$`)
  );
  if (channelStyleRoute && request.method === "POST") {
    const channel = channelStyleRoute[1];
    const current = channelStyles(projectId).find((item) => item.channel === channel);
    const idempotencyKey = request.headers["idempotency-key"];
    if (!SYNTHETIC_CHANNELS.includes(channel) || !current
        || payload?.expected_current_version !== current.version_number
        || typeof payload?.directive !== "string" || !payload.directive.trim()
        || typeof idempotencyKey !== "string" || !idempotencyKey) {
      send(response, { detail: "channel style version payload is invalid" }, 422);
      return true;
    }
    const next = channelStyle(projectId, channel, current.version_number + 1, payload.directive, current.id);
    editedChannelStyles.set(channel, next);
    send(response, next, 201);
    return true;
  }
  if (mode === "manual_import_unavailable"
      && path.startsWith(`${base}/sample-import-previews`)) {
    send(response, { detail: "manual import encryption or object storage is unavailable" }, 503);
    return true;
  }
  if (path === `${base}/authorizations` && request.method === "GET") {
    send(response, page(empty ? [] : [authorization(projectId)]));
    return true;
  }
  const authorizationCommand = path.match(new RegExp(`^${base}/authorizations/([^/]+)/(decision|revoke)$`));
  if (authorizationCommand && request.method === "POST") {
    authorizationState = authorizationCommand[2] === "revoke" ? "revoked" : payload.decision;
    authorizationVersion += 1;
    send(response, authorization(projectId, true));
    return true;
  }
  if (path === `${base}/style-sources`) {
    if (request.method === "GET") {
      send(response, page(empty ? [] : [source(projectId), manualSource(projectId)]));
    }
    else send(response, {
      ...source(projectId),
      id: SOURCE_REVISION_ID,
      source_id: payload.source_id,
      channel: payload.channel,
      access_mode: payload.access_mode,
      source_locator_hash: payload.source_locator_hash,
      replayed: false
    }, 201);
    return true;
  }
  if (path === `${base}/sample-import-previews` && request.method === "GET") {
    send(response, page(empty ? [] : [manualImportPreview(projectId, false)]));
    return true;
  }
  const previewRoute = path.match(new RegExp(`^${base}/sample-import-previews/([^/]+)$`));
  if (previewRoute && request.method === "GET") {
    if (previewRoute[1] !== MANUAL_PREVIEW_ID) {
      send(response, { detail: "manual import preview not found" }, 404);
    } else {
      send(response, manualImportPreview(projectId, true));
    }
    return true;
  }
  const previewApproval = path.match(
    new RegExp(`^${base}/sample-import-previews/([^/]+)/approve$`)
  );
  if (previewApproval && request.method === "POST") {
    if (previewApproval[1] !== MANUAL_PREVIEW_ID) {
      send(response, { detail: "manual import preview not found" }, 404);
    } else if (mode === "manual_approval_rejected") {
      send(response, { detail: "independent manual review was rejected by the service" }, 403);
    } else if (actorId === MANUAL_SUBMITTER_ID) {
      send(response, { detail: "manual import submitter cannot approve their own preview" }, 403);
    } else if (!payload?.au_english_verified || !payload?.anonymization_verified
        || JSON.stringify(payload?.selected_row_numbers) !== JSON.stringify([1])) {
      send(response, { detail: "manual import approval payload is invalid" }, 422);
    } else {
      previewStatus = "approved";
      send(response, manualImportResult(projectId));
    }
    return true;
  }
  if (path === `${base}/resource-inventory` && request.method === "GET") {
    send(response, {
      ...BOUNDARY,
      samples: [],
      prompt_bindings: [
        resourceOption("00000000-0000-4000-8000-000000000731", "synthetic_lab.generation · Dify binding v1", "prompt_binding", "frozen"),
        resourceOption("00000000-0000-4000-8000-000000000732", "synthetic_lab.claim_extraction · Dify binding v1", "prompt_binding", "frozen"),
        resourceOption("00000000-0000-4000-8000-000000000733", "synthetic_lab.conflict_check · Dify binding v1", "prompt_binding", "frozen"),
        resourceOption("00000000-0000-4000-8000-000000000734", "synthetic_lab.revision · Dify binding v1", "prompt_binding", "frozen"),
        resourceOption("00000000-0000-4000-8000-000000000735", "synthetic_lab.style_judge · native binding v1", "prompt_binding", "frozen"),
        resourceOption("00000000-0000-4000-8000-000000000736", "synthetic_lab.arbiter · native binding v1", "prompt_binding", "frozen")
      ],
      question_sets: [
        resourceOption(QUESTION_SET_ID, "Frozen AU buyer questions", "question_set", "frozen")
      ],
      fact_snapshots: [
        resourceOption(FACT_SNAPSHOT_ID, "Approved Fact snapshot", "fact_snapshot", "ready")
      ],
      profiles: mode === "legacy_profile" ? [] : [
        resourceOption(PROFILE_VERSION_ID, "Reddit profile v1", "profile", "frozen", "reddit")
      ],
      review_jobs: [
        resourceOption(
          COMPLETED_REVIEW_JOB_A_ID,
          "Reddit passed Review",
          "review_job",
          "passed",
          "reddit"
        ),
        resourceOption(
          COMPLETED_REVIEW_JOB_B_ID,
          "Reddit warning Review",
          "review_job",
          "completed_with_warning",
          "reddit"
        )
      ],
      candidate_corpora: [
        resourceOption(
          CANDIDATE_CORPUS_JOB_ID,
          "Candidate Corpus v1",
          "corpus_candidate",
          "new_candidate_corpus"
        )
      ],
      approved_corpora: [
        resourceOption(
          APPROVED_CORPUS_JOB_ID,
          "Approved Corpus v2",
          "corpus_approved",
          "current_approved_corpus"
        )
      ]
    });
    return true;
  }
  if (path === `${base}/sample-imports` && request.method === "POST") {
    send(response, {
      ...BOUNDARY,
      id: payload.manifest_id,
      project_id: projectId,
      request_id: payload.import_request_id,
      channel: payload.channel,
      locale: "en-AU",
      row_count: payload.rows.length,
      accepted_count: payload.rows.length,
      rejected_count: 0,
      duplicate_row_count: 0,
      input_hash: "4".repeat(64),
      manifest_hash: "5".repeat(64),
      row_errors: [],
      replayed: false
    }, 201);
    return true;
  }
  if (path === `${base}/style-profiles`) {
    if (request.method === "GET") send(response, page(empty ? [] : [profile(projectId)]));
    else send(response, {
      ...profile(projectId),
      id: payload.profile_id,
      profile_id: payload.profile_id,
      channel: payload.channel,
      corpus_hash: payload.corpus_hash,
      profile_hash: payload.profile_hash,
      prompt_release_id: payload.prompt_release_id,
      prompt_release_hash: payload.prompt_release_hash,
      approved_sample_count: payload.approved_sample_ids.length,
      status: "draft",
      build_verification_status: null,
      rebuild_required: false,
      replayed: false
    }, 201);
    return true;
  }
  const profileFreeze = path.match(new RegExp(`^${base}/style-profiles/([^/]+)/freeze$`));
  if (profileFreeze && request.method === "POST") {
    send(response, { ...profile(projectId), status: "frozen", approved_sample_count: payload.approved_sample_ids.length, replayed: false });
    return true;
  }
  if (path === `${base}/review-suites`) {
    if (request.method === "GET") {
      send(response, page(empty ? [] : [createdSuite, suite(projectId)].filter(Boolean)));
    }
    else {
      createdSuite = {
        ...BOUNDARY,
        id: CREATED_SUITE_VERSION_ID,
        project_id: projectId,
        suite_id: CREATED_SUITE_ID,
        version_number: 1,
        state_version: 1,
        channel: payload.channel,
        case_count: 0,
        case_set_hash: "0".repeat(64),
        status: "draft",
        replayed: false
      };
      send(response, createdSuite, 201);
    }
    return true;
  }
  const casesRoute = path.match(new RegExp(`^${base}/review-suites/([^/]+)/cases$`));
  if (casesRoute) {
    if (request.method === "GET") {
      send(response, page(empty || casesRoute[1] === CREATED_SUITE_VERSION_ID ? [] : cases(projectId)));
    }
    else send(response, {
      ...BOUNDARY,
      id: "00000000-0000-4000-8000-000000000711",
      project_id: projectId,
      review_suite_version_id: casesRoute[1],
      review_suite_version_number: 1,
      case_key: payload.case_key,
      ordinal: payload.ordinal,
      mode: payload.mode,
      channel: payload.channel,
      competitor_scenario: payload.competitor_scenario,
      content_hash: "6".repeat(64),
      replayed: false
    }, 201);
    return true;
  }
  const suiteFreeze = path.match(new RegExp(`^${base}/review-suites/([^/]+)/freeze$`));
  if (suiteFreeze && request.method === "POST") {
    suiteStatus = "frozen";
    send(response, { ...suite(projectId), status: suiteStatus, replayed: false });
    return true;
  }
  if (path === `${base}/jobs/style-collection` && request.method === "POST") {
    const validPayload = payload
      && payload.style_source_revision_id === SOURCE_REVISION_ID
      && payload.adapter_release === authorization(projectId).adapter_release
      && payload.login_secret_reference_id === null
      && Object.keys(payload).length === 3;
    if (!validPayload) {
      send(response, { detail: "style collection admission payload is invalid" }, 422);
      return true;
    }
    const idempotencyKey = request.headers["idempotency-key"];
    if (typeof idempotencyKey !== "string" || !idempotencyKey) {
      send(response, { detail: "style collection idempotency key is invalid" }, 422);
      return true;
    }
    const job = jobView({
      id: styleCollectionJobId(projectId, idempotencyKey),
      projectId,
      kind: "style_collection",
      status: "queued",
      version: 1,
      cancelRequested: false
    });
    jobs.set(job.id, job);
    send(response, {
      ...BOUNDARY,
      disposition: "accepted",
      reason_code: "live_collection_queued",
      may_issue_network_request: true,
      job
    }, 202);
    return true;
  }
  if (path === `${base}/jobs/direct-generation` && request.method === "POST") {
    const options = directGenerationOptions(projectId, false);
    const subject = options.subjects[0];
    const style = options.channel_styles.find((item) => item.channel === payload?.channel);
    const idempotencyKey = request.headers["idempotency-key"];
    const expectedKeys = [
      "channel", "channel_style_hash", "channel_style_version_id", "generation_goal",
      "include_competitor_context", "knowledge_snapshot_hash", "runtime_selection_id",
      "style_pass_threshold", "subject_entity_id"
    ];
    const valid = subject && style && typeof idempotencyKey === "string" && idempotencyKey
      && JSON.stringify(Object.keys(payload || {}).sort()) === JSON.stringify(expectedKeys)
      && payload.subject_entity_id === subject.id
      && payload.channel_style_version_id === style.id
      && payload.channel_style_hash === style.style_hash
      && payload.knowledge_snapshot_hash === subject.knowledge_snapshot_hash
      && payload.runtime_selection_id === RUNTIME_SELECTION_ID
      && typeof payload.generation_goal === "string" && payload.generation_goal.trim()
      && payload.style_pass_threshold === 4.2
      && payload.include_competitor_context === false;
    if (!valid) {
      send(response, { detail: "direct generation payload is invalid" }, 422);
      return true;
    }
    const job = jobView({
      id: executionJobId(projectId, idempotencyKey, "direct-generation"),
      projectId,
      kind: "candidate_generation",
      status: "queued",
      version: 1,
      cancelRequested: false
    });
    jobs.set(job.id, job);
    directJobPolls.set(job.id, 0);
    send(response, job, 202);
    return true;
  }
  const enqueue = path.match(new RegExp(`^${base}/jobs/(generation|revision|corpus|offline-experiment)$`));
  if (enqueue && request.method === "POST") {
    const kind = {
      generation: "candidate_generation",
      revision: "candidate_revision",
      corpus: "corpus_finalize",
      "offline-experiment": "offline_experiment"
    }[enqueue[1]];
    const idempotencyKey = request.headers["idempotency-key"];
    const forbiddenKeys = ["job_id", "input_hash", "outbox_id", "runtime_inputs"];
    if (typeof idempotencyKey !== "string" || !idempotencyKey
        || Object.keys(payload || {}).some((key) => forbiddenKeys.includes(key))) {
      send(response, { detail: "Synthetic execution admission payload is invalid" }, 422);
      return true;
    }
    const job = jobView({
      id: executionJobId(projectId, idempotencyKey, enqueue[1]),
      projectId,
      kind,
      status: "queued",
      version: 1,
      cancelRequested: false
    });
    jobs.set(job.id, job);
    send(response, job, 202);
    return true;
  }
  if (path === `${base}/jobs` && request.method === "GET") {
    const staticItems = empty ? [] : [
      jobView({
        id: COMPLETED_REVIEW_JOB_A_ID,
        projectId,
        kind: "candidate_generation",
        status: "succeeded",
        version: 3,
        cancelRequested: false,
        resultHash: "a".repeat(64)
      }),
      jobView({
        id: COMPLETED_REVIEW_JOB_B_ID,
        projectId,
        kind: "candidate_generation",
        status: "succeeded",
        version: 3,
        cancelRequested: false,
        resultHash: "b".repeat(64)
      }),
      jobView({
        id: EXISTING_STYLE_COLLECTION_JOB_ID,
        projectId,
        kind: "style_collection",
        status: "queued",
        version: 1,
        cancelRequested: false
      })
    ];
    const dynamicItems = [...jobs.values()];
    const merged = [...dynamicItems, ...staticItems.filter(
      (item) => !jobs.has(item.id)
    )];
    send(response, page(merged));
    return true;
  }
  const resultRoute = path.match(new RegExp(`^${base}/jobs/([^/]+)/result$`));
  if (resultRoute && request.method === "GET") {
    if (directJobPolls.has(resultRoute[1])) {
      send(response, directReviewResult(projectId, resultRoute[1]));
    } else if (![COMPLETED_REVIEW_JOB_A_ID, COMPLETED_REVIEW_JOB_B_ID].includes(resultRoute[1])) {
      send(response, { detail: "completed Review Case result is unavailable" }, 404);
    } else {
      send(response, reviewResult(projectId, resultRoute[1]));
    }
    return true;
  }
  const jobRoute = path.match(new RegExp(`^${base}/jobs/([^/]+)(?:/(cancel))?$`));
  if (jobRoute) {
    const completed = [COMPLETED_REVIEW_JOB_A_ID, COMPLETED_REVIEW_JOB_B_ID]
      .includes(jobRoute[1]);
    const current = jobs.get(jobRoute[1]) || jobView({
      id: jobRoute[1],
      projectId,
      kind: jobRoute[1] === EXISTING_STYLE_COLLECTION_JOB_ID ? "style_collection" : "candidate_generation",
      status: jobRoute[1] === EXISTING_STYLE_COLLECTION_JOB_ID ? "queued" : completed ? "succeeded" : "running",
      version: completed ? 3 : 1,
      cancelRequested: false,
      resultHash: completed ? (jobRoute[1] === COMPLETED_REVIEW_JOB_A_ID ? "a" : "b").repeat(64) : null
    });
    if (!jobRoute[2] && request.method === "GET" && directJobPolls.has(jobRoute[1])) {
      const pollCount = (directJobPolls.get(jobRoute[1]) || 0) + 1;
      directJobPolls.set(jobRoute[1], pollCount);
      const finished = pollCount >= 2;
      const progressed = {
        ...current,
        status: finished ? "succeeded" : "running",
        version: finished ? 3 : 2,
        result_hash: finished ? "7".repeat(64) : null
      };
      jobs.set(progressed.id, progressed);
      send(response, progressed);
    } else if (jobRoute[2] === "cancel" && request.method === "POST") {
      const cancelled = { ...current, status: "cancelled", version: current.version + 1, cancel_requested: true };
      jobs.set(cancelled.id, cancelled);
      send(response, cancelled);
    } else {
      send(response, current);
    }
    return true;
  }
  send(response, { detail: "Synthetic Lab fixture route not found", actor_id: actorId }, 404);
  return true;
}

function styleCollectionJobId(projectId, idempotencyKey) {
  const hash = createHash("sha256")
    .update(`${projectId}:${idempotencyKey}:style-collection-job`)
    .digest("hex");
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-5${hash.slice(13, 16)}-8${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

function executionJobId(projectId, idempotencyKey, route) {
  const hash = createHash("sha256")
    .update(`${projectId}:${idempotencyKey}:${route}:server-owned-job`)
    .digest("hex");
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-5${hash.slice(13, 16)}-8${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

function resourceOption(id, label, kind, status, channel = null) {
  return { id, label, kind, status, channel };
}

function page(items) {
  return { ...BOUNDARY, items, total: items.length, limit: 100, offset: 0 };
}

function directGenerationOptions(projectId, empty = false) {
  return {
    ...BOUNDARY,
    subjects: empty ? [] : [{
      id: DIRECT_SUBJECT_ID,
      name: "ADVINSYS TerraMow V600",
      canonical_url: "https://www.advinsys.com.au/products/terramow-v600",
      knowledge_snapshot_hash: "b".repeat(64),
      knowledge_items: directKnowledgeItems(projectId, false),
      competitor_knowledge_snapshot_hash: null,
      competitor_knowledge_items: []
    }],
    channel_styles: empty ? [] : channelStyles(projectId),
    has_competitor_knowledge: false
  };
}

function channelStyles(projectId) {
  return SYNTHETIC_CHANNELS.map(
    (channel) => editedChannelStyles.get(channel) || channelStyle(projectId, channel)
  );
}

function channelStyle(projectId, channel, version = 1, directive = null, previousVersionId = null) {
  const text = directive || `${channel} fixture style: write concise Australian English, use only supplied knowledge, and state uncertainty plainly.`;
  return {
    ...BOUNDARY,
    replayed: false,
    id: stableUuid(`${channel}:style-version:${version}`),
    project_id: projectId,
    style_id: stableUuid(`${channel}:style`),
    version_number: version,
    previous_version_id: previousVersionId,
    channel,
    locale: "en-AU",
    directive: text,
    provenance: version === 1 ? "manual_initial" : "manual_edit",
    calibration_status: "pending_sample_calibration",
    style_hash: createHash("sha256").update(`${channel}:${version}:${text}`).digest("hex")
  };
}

function directKnowledgeItems(projectId, matched) {
  return [
    directKnowledgeItem({
      evidenceId: DIRECT_FACT_A_ID,
      projectId,
      summary: "Triple-Cam AI Vision Robot Mower V600",
      hashCharacter: "c",
      matched
    }),
    directKnowledgeItem({
      evidenceId: DIRECT_FACT_B_ID,
      projectId,
      summary: "600 square metres (0.15 acre)",
      hashCharacter: "d",
      matched
    })
  ];
}

function directKnowledgeItem({ evidenceId, projectId, summary, hashCharacter, matched }) {
  return {
    evidence_id: evidenceId,
    kind: "approved_fact",
    subject_entity_id: DIRECT_SUBJECT_ID,
    subject_name: "ADVINSYS TerraMow V600",
    summary,
    snapshot_hash: hashCharacter.repeat(64),
    source_title: "ADVINSYS official product page",
    source_url: "https://www.advinsys.com.au/products/terramow-v600",
    trace_href: `/projects/${projectId}?tab=knowledge&knowledge_tab=trace&knowledge_fact_id=${evidenceId}`,
    matched,
    conflicting: false
  };
}

function stableUuid(seed) {
  const hash = createHash("sha256").update(seed).digest("hex");
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-5${hash.slice(13, 16)}-8${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

function authorization(projectId, replayed = false) {
  return {
    ...BOUNDARY,
    id: AUTHORIZATION_ID,
    project_id: projectId,
    channel: "reddit",
    adapter_release: "manual-import-v1-with-an-extraordinarily-long-release-identity-for-overflow-validation",
    version_number: authorizationVersion,
    state: authorizationState,
    effective_state: authorizationState,
    evidence_reference_hash: authorizationState === "approved" ? "1".repeat(64) : null,
    allowed_purposes: authorizationState === "approved" ? ["style_collection"] : [],
    max_requests_per_period: authorizationState === "approved" ? 20 : null,
    period_seconds: authorizationState === "approved" ? 60 : null,
    max_concurrency: authorizationState === "approved" ? 2 : null,
    expires_at: authorizationState === "approved" ? "2027-07-24T02:00:00Z" : null,
    record_hash: "a".repeat(64),
    replayed
  };
}

function source(projectId) {
  return {
    ...BOUNDARY,
    id: SOURCE_REVISION_ID,
    project_id: projectId,
    source_id: SOURCE_ID,
    revision_number: 1,
    channel: "reddit",
    access_mode: "public",
    locale: "en-AU",
    source_locator_hash: "b".repeat(64),
    status: "active",
    replayed: false
  };
}

function manualSource(projectId) {
  return {
    ...BOUNDARY,
    id: MANUAL_SOURCE_REVISION_ID,
    project_id: projectId,
    source_id: MANUAL_SOURCE_ID,
    revision_number: 1,
    channel: "reddit",
    access_mode: "manual_import",
    locale: "en-AU",
    source_locator_hash: "7".repeat(64),
    status: "active",
    replayed: false
  };
}

function manualImportPreview(projectId, includeRows) {
  const summary = {
    ...BOUNDARY,
    id: MANUAL_PREVIEW_ID,
    project_id: projectId,
    style_source_revision_id: MANUAL_SOURCE_REVISION_ID,
    channel: "reddit",
    filename: "australian-reddit-style-samples.txt",
    import_format: "text",
    status: previewStatus,
    version: previewStatus === "pending" ? 1 : 2,
    submitted_by: MANUAL_SUBMITTER_ID,
    submitted_at: "2026-07-24T02:00:00Z",
    expires_at: "2027-07-24T02:00:00Z",
    row_count: 2,
    selectable_count: 1,
    blocked_count: 1,
    preview_manifest_hash: "8".repeat(64),
    replayed: false
  };
  return includeRows ? {
    ...summary,
    rows: [
      {
        row_number: 1,
        redacted_text: "Easy setup and solid performance on a medium Australian lawn.",
        source_rights: "owned",
        detected_codes: ["en_au_confirmed"],
        blocking_codes: [],
        disposition: "ready_for_review",
        selectable: true
      },
      {
        row_number: 2,
        redacted_text: "[REDACTED] account-linked sample",
        source_rights: "public_reference",
        detected_codes: ["account_link_detected"],
        blocking_codes: ["restricted_identifier"],
        disposition: "blocked",
        selectable: false
      }
    ]
  } : summary;
}

function manualImportResult(projectId) {
  return {
    ...BOUNDARY,
    id: MANUAL_IMPORT_ID,
    project_id: projectId,
    request_id: MANUAL_REQUEST_ID,
    channel: "reddit",
    locale: "en-AU",
    row_count: 2,
    accepted_count: 1,
    rejected_count: 1,
    duplicate_row_count: 0,
    input_hash: "9".repeat(64),
    manifest_hash: "0".repeat(64),
    row_errors: [],
    replayed: false
  };
}

function profile(projectId) {
  return {
    ...BOUNDARY,
    id: PROFILE_VERSION_ID,
    project_id: projectId,
    profile_id: PROFILE_ID,
    version_number: 1,
    state_version: 1,
    channel: "reddit",
    locale: "en-AU",
    corpus_hash: "c".repeat(64),
    profile_hash: "d".repeat(64),
    prompt_release_id: PROMPT_RELEASE_ID,
    prompt_release_hash: "e".repeat(64),
    approved_sample_count: 240,
    status: profileStatus,
    build_verification_status: mode === "governance"
      ? null
      : mode === "legacy_profile" ? "legacy_unverified" : "verified",
    rebuild_required: mode === "legacy_profile",
    replayed: false
  };
}

function suite(projectId) {
  return {
    ...BOUNDARY,
    id: SUITE_VERSION_ID,
    project_id: projectId,
    suite_id: SUITE_ID,
    version_number: 1,
    state_version: 1,
    channel: "reddit",
    case_count: 2,
    case_set_hash: "f".repeat(64),
    status: suiteStatus,
    replayed: false
  };
}

function cases(projectId) {
  return [
    caseView(projectId, CASE_A_ID, 1, "autonomous_scenario", false, "au-mower-autonomous"),
    caseView(projectId, CASE_B_ID, 2, "guided_scenario", true, "au-mower-competitor-guided")
  ];
}

function caseView(projectId, id, ordinal, scenarioMode, competitor, key) {
  return {
    ...BOUNDARY,
    id,
    project_id: projectId,
    review_suite_version_id: SUITE_VERSION_ID,
    review_suite_version_number: 1,
    state_version: 1,
    case_key: key,
    ordinal,
    mode: scenarioMode,
    channel: "reddit",
    competitor_scenario: competitor,
    content_hash: String(ordinal).repeat(64),
    replayed: false
  };
}

export function syntheticRuntimeOptions() {
  return {
    current_manifest_id: "00000000-0000-4000-8000-000000000715",
    items: [{
      selection_id: RUNTIME_SELECTION_ID,
      manifest_id: "00000000-0000-4000-8000-000000000715",
      provider: "openai",
      adapter_release_id: "openai-responses-v1",
      model_release_id: "gpt-fixture-v1",
      configured_model: "gpt-fixture",
      capture_method: "provider_api",
      allowed_purposes: [
        "synthetic_lab.style_profile",
        "synthetic_lab.generation",
        "synthetic_lab.claim_extraction",
        "synthetic_lab.conflict_check",
        "synthetic_lab.revision",
        "synthetic_lab.style_judge",
        "synthetic_lab.arbiter",
        "synthetic_lab.offline_answer"
      ],
      allowed_search_modes: [null]
    }]
  };
}

function jobView({ id, projectId, kind, status, version, cancelRequested, resultHash = null }) {
  return {
    ...BOUNDARY,
    id,
    project_id: projectId,
    kind,
    status,
    version,
    input_hash: "9".repeat(64),
    fencing_generation: 1,
    cancel_requested: cancelRequested,
    result_hash: resultHash,
    replayed: false,
    warning_summary: {
      warning_count: 2,
      candidate_count: 5,
      warning_ratio: 0.4,
      by_code: { derived_or_unknown: 2 },
      by_channel: { reddit: 2 },
      by_scenario_mode: { autonomous_scenario: 1, guided_scenario: 1 },
      by_competitor: { competitor: 1, non_competitor: 1 },
      by_model: { "fixture-model-release-with-a-long-name": 2 },
      by_question_cluster: { "residential-mower-value-and-maintenance": 2 }
    }
  };
}

function reviewResult(projectId, jobId) {
  const warning = jobId === COMPLETED_REVIEW_JOB_B_ID;
  return {
    ...BOUNDARY,
    job_id: jobId,
    project_id: projectId,
    review_run_id: "00000000-0000-4000-8000-000000000737",
    run_origin: "regression",
    input_snapshot_id: null,
    review_suite_version_id: SUITE_VERSION_ID,
    review_case_id: warning ? CASE_B_ID : CASE_A_ID,
    scenario_id: warning ? CASE_B_ID : CASE_A_ID,
    case_key: warning ? "au-mower-competitor-guided" : "au-mower-autonomous",
    channel: "reddit",
    scenario_mode: warning ? "guided_scenario" : "autonomous_scenario",
    competitor_scenario: warning,
    style_pass_threshold: 4.2,
    runtime_selection_id: RUNTIME_SELECTION_ID,
    profile_version_id: PROFILE_VERSION_ID,
    fact_snapshot_id: FACT_SNAPSHOT_ID,
    generation_goal: null,
    channel_style_version_id: null,
    channel_style_version_number: null,
    channel_style_hash: null,
    knowledge_snapshot_hash: null,
    knowledge_context_items: [],
    final_text: warning
      ? "I compared it with the usual big-name option and found the setup straightforward. It handled a medium Australian lawn well, though long-term battery life is still unknown."
      : "Setup was straightforward and it handled a medium Australian lawn without fuss. The controls felt practical, and the cut stayed consistent across the yard.",
    status: warning ? "completed_with_warning" : "passed",
    warning_codes: warning ? ["derived_or_unknown"] : [],
    failure_code: null,
    resolution_candidate_id: "00000000-0000-4000-8000-000000000738",
    result_hash: (warning ? "b" : "a").repeat(64),
    batches: [{
      id: "00000000-0000-4000-8000-000000000739",
      batch_number: 1,
      kind: "initial",
      scenario_mode: warning ? "guided_scenario" : "autonomous_scenario",
      candidate_count: 4,
      provider: "dify",
      configured_model: "deepseek-chat"
    }],
    evaluations: [{
      id: "00000000-0000-4000-8000-000000000740",
      candidate_id: "00000000-0000-4000-8000-000000000738",
      candidate_output_hash: "c".repeat(64),
      style_score: warning ? 4.4 : 4.7,
      style_passed: true,
      disposition: warning ? "warning" : "pass",
      correctable_issue_codes: [],
      soft_issue_codes: [],
      warning_codes: warning ? ["derived_or_unknown"] : [],
      claim_assessments: [{
        claim_hash: "d".repeat(64),
        status: warning ? "derived_or_unknown" : "current_approved",
        fact_id: warning ? null : "00000000-0000-4000-8000-000000000741",
        fact_hash: warning ? null : "e".repeat(64),
        expected_subject_id: null,
        observed_subject_id: null,
        output_annotation: warning ? "derived_or_unknown" : null,
        evidence_refs: warning ? [] : [`evidence:00000000-0000-4000-8000-000000000741:${"e".repeat(64)}`]
      }],
      provider: "dify",
      configured_model: "deepseek-chat",
      evidence_artifact_hash: "f".repeat(64)
    }],
    revisions: warning ? [{
      id: "00000000-0000-4000-8000-000000000742",
      round_number: 1,
      parent_candidate_id: "00000000-0000-4000-8000-000000000743",
      parent_output_hash: "1".repeat(64),
      revised_candidate_id: "00000000-0000-4000-8000-000000000738",
      revised_output_hash: "c".repeat(64),
      issue_codes: ["style_below_threshold"],
      provider: "dify",
      configured_model: "deepseek-chat"
    }] : [],
    model_call_ids: [],
    workflow_attempt_ids: [
      "00000000-0000-4000-8000-000000000744",
      "00000000-0000-4000-8000-000000000745"
    ]
  };
}

function directReviewResult(projectId, jobId) {
  const style = channelStyle(projectId, "reddit");
  const finalCandidateId = stableUuid(`${jobId}:final-candidate`);
  return {
    ...BOUNDARY,
    job_id: jobId,
    project_id: projectId,
    review_run_id: stableUuid(`${jobId}:review-run`),
    run_origin: "direct",
    input_snapshot_id: DIRECT_INPUT_SNAPSHOT_ID,
    review_suite_version_id: null,
    review_case_id: null,
    scenario_id: DIRECT_SCENARIO_ID,
    case_key: `direct:${DIRECT_SCENARIO_ID}`,
    channel: "reddit",
    scenario_mode: "guided_scenario",
    competitor_scenario: false,
    style_pass_threshold: 4.2,
    runtime_selection_id: RUNTIME_SELECTION_ID,
    profile_version_id: style.style_id,
    fact_snapshot_id: DIRECT_INPUT_SNAPSHOT_ID,
    generation_goal: "Explain whether the TerraMow V600 fits a medium Australian lawn.",
    channel_style_version_id: style.id,
    channel_style_version_number: style.version_number,
    channel_style_hash: style.style_hash,
    knowledge_snapshot_hash: "b".repeat(64),
    knowledge_context_items: directKnowledgeItems(projectId, true),
    final_text: "For a medium Australian lawn, the TerraMow V600 is listed for up to 600 square metres. The triple-camera system is a documented feature, but real-world slope and wet-grass performance are not covered by the supplied facts.",
    status: "completed_with_warning",
    warning_codes: ["derived_or_unknown"],
    failure_code: null,
    resolution_candidate_id: finalCandidateId,
    result_hash: "7".repeat(64),
    batches: [{
      id: stableUuid(`${jobId}:batch`),
      batch_number: 1,
      kind: "initial",
      scenario_mode: "guided_scenario",
      candidate_count: 4,
      provider: "dify",
      configured_model: "gpt-fixture"
    }],
    evaluations: [{
      id: stableUuid(`${jobId}:evaluation`),
      candidate_id: finalCandidateId,
      candidate_output_hash: "8".repeat(64),
      style_score: 4.5,
      style_passed: true,
      disposition: "warning",
      correctable_issue_codes: [],
      soft_issue_codes: [],
      warning_codes: ["derived_or_unknown"],
      claim_assessments: [
        {
          claim_hash: "1".repeat(64),
          status: "current_approved",
          fact_id: DIRECT_FACT_B_ID,
          fact_hash: "d".repeat(64),
          expected_subject_id: null,
          observed_subject_id: null,
          output_annotation: null,
          evidence_refs: [`evidence:${DIRECT_FACT_B_ID}:${"d".repeat(64)}`]
        },
        {
          claim_hash: "2".repeat(64),
          status: "derived_or_unknown",
          fact_id: null,
          fact_hash: null,
          expected_subject_id: null,
          observed_subject_id: null,
          output_annotation: "derived_or_unknown",
          evidence_refs: []
        }
      ],
      provider: "openai",
      configured_model: "gpt-fixture",
      evidence_artifact_hash: "9".repeat(64)
    }],
    revisions: [],
    model_call_ids: [stableUuid(`${jobId}:model-call`)],
    workflow_attempt_ids: [
      stableUuid(`${jobId}:generation-attempt`),
      stableUuid(`${jobId}:claim-attempt`),
      stableUuid(`${jobId}:conflict-attempt`)
    ]
  };
}
