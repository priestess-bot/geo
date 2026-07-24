const RECOMMENDATION_ID = "00000000-0000-4000-8000-000000000801";
const CREATOR_ID = "00000000-0000-4000-8000-000000000802";
const APPROVAL_ID = "00000000-0000-4000-8000-000000000803";
const DRAFT_ID = "00000000-0000-4000-8000-000000000804";
const OBSERVATION_ID = "00000000-0000-4000-8000-000000000805";
const QUESTION_ID = "00000000-0000-4000-8000-000000000806";
const SURFACE_ID = "00000000-0000-4000-8000-000000000807";
const RECOMMENDATION_PROMPT_BINDING_ID = "00000000-0000-4000-8000-000000000811";
const ARBITER_PROMPT_BINDING_ID = "00000000-0000-4000-8000-000000000812";
const RUNTIME_MANIFEST_ID = "00000000-0000-4000-8000-000000000813";
const RECOMMENDATION_RUNTIME_ID = "00000000-0000-4000-8000-000000000814";
const ARBITER_RUNTIME_ID = "00000000-0000-4000-8000-000000000815";
const GENERATION_JOB_ID = "00000000-0000-4000-8000-000000000816";
const HASHES = {
  graph: "a".repeat(64),
  input: "b".repeat(64),
  observation: "c".repeat(64),
  method: "d".repeat(64),
  fact: "e".repeat(64),
  rule: "f".repeat(64),
  prompt: "1".repeat(64),
  content: "2".repeat(64),
  question: "3".repeat(64),
  surface: "4".repeat(64)
};

let mode = "normal";
let status = "in_review";
let version = 2;
let approval = null;
let drafts = [];

export function resetRecommendationFixture() {
  mode = "normal";
  status = "in_review";
  version = 2;
  approval = null;
  drafts = [];
}

export function handleRecommendationFixture({
  actorId,
  now,
  path,
  payload,
  projectId,
  query,
  request,
  response,
  send
}) {
  if (path === "/__recommendation_mode" && request.method === "POST") {
    mode = ["normal", "empty", "partial-unavailable", "unavailable"].includes(payload?.mode)
      ? payload.mode
      : "normal";
    send(response, { mode });
    return true;
  }
  if (path === `/v1/projects/${projectId}/prompt-program-bindings`
    && request.method === "GET") {
    const kind = query?.program_kind === "arbiter" ? "arbiter" : "recommendation";
    const item = promptBindingOption(projectId, kind);
    send(response, { items: [item], total: 1, limit: 100, offset: 0 });
    return true;
  }
  if (path === `/v1/projects/${projectId}/model-gateway/options`
    && request.method === "GET") {
    send(response, {
      items: [
        runtimeOption(RECOMMENDATION_RUNTIME_ID, "recommendations.recommendation", "gpt-5.2"),
        runtimeOption(ARBITER_RUNTIME_ID, "synthetic_lab.arbiter", "gemini-2.5-pro")
      ],
      current_manifest_id: RUNTIME_MANIFEST_ID
    });
    return true;
  }
  const base = `/v1/projects/${projectId}/recommendations`;
  if (!path.startsWith(base)) return false;
  if (mode === "unavailable" || (mode === "partial-unavailable" && path === base)) {
    send(response, { detail: "Recommendation persistence is unavailable" }, 503);
    return true;
  }
  if (path === base && request.method === "GET") {
    const items = mode === "empty" ? [] : [workflow(projectId, now)];
    send(response, { items, total: items.length, limit: 200, offset: 0 });
    return true;
  }
  if (path === `${base}/${RECOMMENDATION_ID}` && request.method === "GET") {
    send(response, workflow(projectId, now));
    return true;
  }
  if (path === `${base}/generation-jobs` && request.method === "POST") {
    if (payload?.prompt_binding_id !== RECOMMENDATION_PROMPT_BINDING_ID
      || payload?.model?.runtime_selection_id !== RECOMMENDATION_RUNTIME_ID
      || "provider" in (payload?.model || {})
      || "adapter_release_id" in (payload?.model || {})
      || "model_release_id" in (payload?.model || {})) {
      send(response, { detail: "Generation selectors are invalid" }, 422);
      return true;
    }
    send(response, generationJob(projectId));
    return true;
  }
  const command = path.match(new RegExp(`^${base}/${RECOMMENDATION_ID}/(submit|review|approve|reject|expire|reconcile-stale)$`));
  if (command && request.method === "POST") {
    send(response, commandResponse(command[1], projectId, actorId, now, payload));
    return true;
  }
  if (path === `${base}/${RECOMMENDATION_ID}/drafts/${DRAFT_ID}/prepare-action`
    && request.method === "POST") {
    send(response, {
      ...workflow(projectId, now),
      replayed: false,
      draft: drafts[0],
      authorized: true,
      action_boundary: "source_checked_draft_only"
    });
    return true;
  }
  send(response, { detail: "Recommendation fixture route not found" }, 404);
  return true;
}

function promptBindingOption(projectId, kind) {
  const bindingId = kind === "arbiter"
    ? ARBITER_PROMPT_BINDING_ID
    : RECOMMENDATION_PROMPT_BINDING_ID;
  return {
    id: bindingId,
    project_id: projectId,
    purpose: kind === "arbiter" ? "synthetic_lab.arbiter" : "recommendations.recommendation",
    program_kind: kind,
    program_id: kind === "arbiter"
      ? "00000000-0000-4000-8000-000000000821"
      : "00000000-0000-4000-8000-000000000822",
    release_id: kind === "arbiter"
      ? "00000000-0000-4000-8000-000000000823"
      : "00000000-0000-4000-8000-000000000824",
    release_version: 3,
    release_hash: kind === "arbiter" ? "8".repeat(64) : "7".repeat(64),
    frozen_state_id: kind === "arbiter"
      ? "00000000-0000-4000-8000-000000000825"
      : "00000000-0000-4000-8000-000000000826",
    binding_version: 2,
    bound_by: CREATOR_ID,
    bound_at: "2026-07-23T01:00:00Z"
  };
}

function runtimeOption(selectionId, purpose, model) {
  return {
    selection_id: selectionId,
    manifest_id: RUNTIME_MANIFEST_ID,
    provider: purpose === "synthetic_lab.arbiter" ? "gemini" : "openai",
    adapter_release_id: `${purpose.replaceAll(".", "-")}-adapter-r3`,
    model_release_id: `${purpose.replaceAll(".", "-")}-model-r5`,
    configured_model: model,
    capture_method: "provider_api",
    allowed_purposes: [purpose],
    allowed_search_modes: [null, "web"]
  };
}

function generationJob(projectId) {
  return {
    id: GENERATION_JOB_ID,
    project_id: projectId,
    status: "queued",
    version: 1,
    input_hash: "5".repeat(64),
    evidence_input_hash: "6".repeat(64),
    consumed_model_calls: 0,
    maximum_model_calls: 2,
    cancel_requested: false,
    error_code: null,
    valid_until: "2027-01-31T00:00:00Z",
    prompt: {
      binding_id: RECOMMENDATION_PROMPT_BINDING_ID,
      binding_version: 2,
      frozen_state_id: "00000000-0000-4000-8000-000000000826",
      frozen_state_version: 4,
      release_id: "00000000-0000-4000-8000-000000000824",
      release_version: 3,
      release_hash: "7".repeat(64),
      program_kind: "recommendation",
      purpose: "recommendation"
    },
    model: {
      runtime_selection_id: RECOMMENDATION_RUNTIME_ID,
      runtime_manifest_id: RUNTIME_MANIFEST_ID,
      runtime_manifest_hash: "2".repeat(64),
      runtime_option_id: RECOMMENDATION_RUNTIME_ID,
      runtime_option_hash: "3".repeat(64),
      provider: "openai",
      adapter_release_id: "recommendations-recommendation-adapter-r3",
      adapter_release_hash: "9".repeat(64),
      model_release_id: "recommendations-recommendation-model-r5",
      model_release_hash: "0".repeat(64),
      configured_model: "gpt-5.2",
      policy_version_id: "00000000-0000-4000-8000-000000000827",
      policy_version_hash: "1".repeat(64),
      capture_method: "provider_api",
      search_mode: null
    },
    arbiter_prompt: null,
    arbiter_model: null,
    result: null,
    model_call_ids: [],
    insufficient_reasons: [],
    replayed: false
  };
}

function commandResponse(command, projectId, actorId, now, payload) {
  if (command === "submit") {
    status = "in_review";
    version += 1;
    return { ...workflow(projectId, now), replayed: false };
  }
  if (command === "review") {
    return {
      ...workflow(projectId, now),
      replayed: false,
      review: {
        id: "00000000-0000-4000-8000-000000000808",
        recommendation_id: RECOMMENDATION_ID,
        recommendation_version: version,
        evidence_graph_hash: HASHES.graph,
        reviewed_by: actorId,
        notes: payload.notes,
        reviewed_at: now
      }
    };
  }
  if (command === "approve") {
    status = "approved";
    version += 1;
    approval = approvalView(actorId, now);
    drafts = [draftView(now)];
    return {
      ...workflow(projectId, now),
      replayed: false,
      downstream_draft: drafts[0],
      action_boundary: "draft_only_unstarted"
    };
  }
  if (command === "reject") {
    status = "rejected";
    version += 1;
    return { ...workflow(projectId, now), replayed: false };
  }
  status = command === "expire" ? "expired" : "stale";
  version += 1;
  drafts = drafts.map((draft) => ({
    ...draft,
    status: status === "expired" ? "blocked_source_expired" : "blocked_source_stale",
    blocked_at: now,
    blocked_reason: payload.reason || payload.change_reason
  }));
  return {
    ...workflow(projectId, now),
    replayed: false,
    cancelled_outbox_ids: []
  };
}

function workflow(projectId, now) {
  return {
    recommendation: recommendation(projectId, now),
    drafts
  };
}

function recommendation(projectId, now) {
  return {
    id: RECOMMENDATION_ID,
    project_id: projectId,
    recommendation_type: "experiment",
    status,
    version,
    proposed_draft_kind: "experiment_plan",
    valid_until: "2027-01-31T00:00:00Z",
    created_by: CREATOR_ID,
    created_at: now,
    updated_at: now,
    evidence: evidenceGraph(projectId),
    evidence_graph_hash: HASHES.graph,
    input_fingerprint: HASHES.input,
    input_versions: [{
      kind: "observation",
      resource_id: OBSERVATION_ID,
      version: "capture-v1",
      sha256: HASHES.observation
    }],
    approval
  };
}

function evidenceGraph(projectId) {
  const reference = (resourceId, sha256) => ({
    project_id: projectId,
    resource_id: resourceId,
    version: "v1",
    sha256,
    locator: { environment: "live-staging", account: "redacted-fixture" },
    valid: true
  });
  return {
    scope: {
      project_id: projectId,
      applicable_version: "project-v7",
      campaign_id: null,
      question_or_cluster_ref: "robotic-mower-au",
      surface_ref: "openai-api-au",
      content_asset_ref: null,
      url_ref: null
    },
    decision: {
      impact_chain: ["Observed citation gap", "Test an evidence-backed answer"],
      risk: "Low: draft only",
      effort: "Medium",
      business_value: "Improve answer absorption for a weak AU question cluster",
      confidence: "0.86",
      counterevidence: ["One comparison remains inconclusive"],
      validation_plan: ["Run a frozen paired experiment"],
      stale_conditions: ["Observation or Fact version changes"]
    },
    observations: [{
      ...reference(OBSERVATION_ID, HASHES.observation),
      capture_method: "provider_api",
      evidence_class: "real_observation",
      question_resource_id: QUESTION_ID,
      surface_resource_id: SURFACE_ID,
      eligible: true
    }],
    metric_comparisons: [{
      ...reference("00000000-0000-4000-8000-000000000809", HASHES.method),
      observation_resource_ids: [OBSERVATION_ID],
      method_version: "wilson-v1",
      method_sha256: HASHES.method,
      sufficient_evidence: true
    }],
    facts: [{ ...reference("fact-au-mower", HASHES.fact), approved: true, retired: false }],
    rules: [{ ...reference("recommendation-rule-v1", HASHES.rule), active: true }],
    prompt_releases: [{ ...reference("recommendation-prompt-v1", HASHES.prompt), approved: true, frozen: true }],
    model_calls: [],
    contents: [{ ...reference("content-asset-v4", HASHES.content), current: true }],
    questions: [{ ...reference(QUESTION_ID, HASHES.question), active: true }],
    surfaces: [{ ...reference(SURFACE_ID, HASHES.surface), active: true }]
  };
}

function approvalView(actorId, now) {
  return {
    id: APPROVAL_ID,
    approved_by: actorId,
    approved_at: now,
    recommendation_version: version,
    frozen_input_fingerprint: HASHES.input,
    frozen_evidence_graph_hash: HASHES.graph,
    valid_until: "2027-01-31T00:00:00Z"
  };
}

function draftView(now) {
  return {
    id: DRAFT_ID,
    recommendation_id: RECOMMENDATION_ID,
    recommendation_version: version,
    approval_id: APPROVAL_ID,
    kind: "experiment_plan",
    status: "draft",
    frozen_input_fingerprint: HASHES.input,
    frozen_evidence_graph_hash: HASHES.graph,
    created_at: now,
    started_at: null,
    blocked_at: null,
    blocked_reason: null,
    draft_only: true,
    enqueued: false,
    executed: false,
    published: false
  };
}
