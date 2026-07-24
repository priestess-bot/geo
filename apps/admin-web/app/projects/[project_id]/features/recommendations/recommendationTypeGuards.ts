import {
  inputChangeReasons,
  recommendationStatuses,
  recommendationTypes,
  type ApprovedRecommendationResponse,
  type EvidenceGraph,
  type InputVersion,
  type InvalidatedRecommendationResponse,
  type LinkedDraft,
  type PreparedDraftActionResponse,
  type Recommendation,
  type RecommendationCommandResponse,
  type RecommendationPage,
  type RecommendationWorkflow,
  type ReviewedRecommendationResponse,
  type VersionedEvidenceRef
} from "./recommendationTypes";

const inputKinds = new Set([
  "observation", "comparison", "fact", "rule_version", "prompt_release",
  "model_call", "method_version", "content_version", "question_version", "surface_release"
]);
const draftKinds = new Set(["experiment_plan", "question_set", "content_brief", "sampling_plan"]);
const draftStatuses = new Set([
  "draft", "started", "blocked_source_stale", "blocked_source_expired"
]);

export function isRecommendationPage(value: unknown): value is RecommendationPage {
  return record(value)
    && Array.isArray(value.items)
    && value.items.every(isRecommendationWorkflow)
    && nonNegativeInteger(value.total)
    && positiveInteger(value.limit)
    && nonNegativeInteger(value.offset);
}

export function isRecommendationWorkflow(value: unknown): value is RecommendationWorkflow {
  return record(value)
    && isRecommendation(value.recommendation)
    && Array.isArray(value.drafts)
    && value.drafts.every(isLinkedDraft);
}

export function isRecommendationCommandResponse(
  value: unknown
): value is RecommendationCommandResponse {
  if (!isRecommendationWorkflow(value)) return false;
  const candidate = value as unknown as Record<string, unknown>;
  return typeof candidate.replayed === "boolean";
}

export function isReviewedRecommendationResponse(
  value: unknown
): value is ReviewedRecommendationResponse {
  if (!isRecommendationCommandResponse(value)) return false;
  const candidate = value as unknown as Record<string, unknown>;
  const review = candidate.review;
  return record(review)
    && [
      review.id,
      review.recommendation_id,
      review.evidence_graph_hash,
      review.reviewed_by,
      review.notes,
      review.reviewed_at
    ].every(nonEmptyString)
    && positiveInteger(review.recommendation_version);
}

export function isApprovedRecommendationResponse(
  value: unknown
): value is ApprovedRecommendationResponse {
  if (!isRecommendationCommandResponse(value)) return false;
  const candidate = value as unknown as Record<string, unknown>;
  return candidate.action_boundary === "draft_only_unstarted"
    && (candidate.downstream_draft === null || isLinkedDraft(candidate.downstream_draft));
}

export function isInvalidatedRecommendationResponse(
  value: unknown
): value is InvalidatedRecommendationResponse {
  if (!isRecommendationCommandResponse(value)) return false;
  const candidate = value as unknown as Record<string, unknown>;
  return Array.isArray(candidate.cancelled_outbox_ids)
    && candidate.cancelled_outbox_ids.every(nonEmptyString);
}

export function isPreparedDraftActionResponse(
  value: unknown
): value is PreparedDraftActionResponse {
  if (!isRecommendationCommandResponse(value)) return false;
  const candidate = value as unknown as Record<string, unknown>;
  return candidate.authorized === true
    && candidate.action_boundary === "source_checked_draft_only"
    && isLinkedDraft(candidate.draft);
}

export function isInputVersion(value: unknown): value is InputVersion {
  return record(value)
    && inputKinds.has(String(value.kind))
    && [value.resource_id, value.version].every(nonEmptyString)
    && hash(value.sha256);
}

export function isInputChangeReason(value: unknown): boolean {
  return inputChangeReasons.some((candidate) => candidate === value);
}

function isRecommendation(value: unknown): value is Recommendation {
  if (!record(value)) return false;
  return [
    value.id,
    value.project_id,
    value.valid_until,
    value.created_by,
    value.created_at,
    value.updated_at
  ].every(nonEmptyString)
    && recommendationTypes.some((candidate) => candidate === value.recommendation_type)
    && recommendationStatuses.some((candidate) => candidate === value.status)
    && positiveInteger(value.version)
    && (value.proposed_draft_kind === null || draftKinds.has(String(value.proposed_draft_kind)))
    && isEvidenceGraph(value.evidence)
    && hash(value.evidence_graph_hash)
    && hash(value.input_fingerprint)
    && Array.isArray(value.input_versions)
    && value.input_versions.every(isInputVersion)
    && (value.approval === null || isApproval(value.approval));
}

function isEvidenceGraph(value: unknown): value is EvidenceGraph {
  if (!record(value) || !record(value.scope) || !record(value.decision)) return false;
  const scope = value.scope;
  const decision = value.decision;
  return evidenceArray(value.observations, isObservationRef)
    && evidenceArray(value.metric_comparisons, isMetricComparisonRef)
    && evidenceArray(value.facts, (item) => booleanFields(item, "approved", "retired"))
    && evidenceArray(value.rules, (item) => booleanFields(item, "active"))
    && evidenceArray(
      value.prompt_releases,
      (item) => booleanFields(item, "approved", "frozen")
    )
    && evidenceArray(value.model_calls, isModelCallRef)
    && evidenceArray(value.contents, (item) => booleanFields(item, "current"))
    && evidenceArray(value.questions, (item) => booleanFields(item, "active"))
    && evidenceArray(value.surfaces, (item) => booleanFields(item, "active"))
    && nonEmptyString(scope.project_id)
    && nonEmptyString(scope.applicable_version)
    && optionalString(scope.campaign_id)
    && optionalString(scope.question_or_cluster_ref)
    && optionalString(scope.surface_ref)
    && optionalString(scope.content_asset_ref)
    && optionalString(scope.url_ref)
    && [decision.risk, decision.effort, decision.business_value, decision.confidence]
      .every(nonEmptyString)
    && stringArray(decision.impact_chain, true)
    && stringArray(decision.counterevidence)
    && stringArray(decision.validation_plan, true)
    && stringArray(decision.stale_conditions, true);
}

function isEvidenceRef(value: unknown): value is VersionedEvidenceRef {
  return record(value)
    && [value.project_id, value.resource_id, value.version].every(nonEmptyString)
    && hash(value.sha256)
    && record(value.locator)
    && Object.keys(value.locator).length > 0
    && Object.values(value.locator).every(nonEmptyString)
    && typeof value.valid === "boolean";
}

function isObservationRef(value: unknown): boolean {
  if (!isEvidenceRef(value)) return false;
  const candidate = value as unknown as Record<string, unknown>;
  return [candidate.capture_method, candidate.question_resource_id, candidate.surface_resource_id]
      .every(nonEmptyString)
    && ["real_observation", "official_projection", "synthetic"]
      .includes(String(candidate.evidence_class))
    && typeof candidate.eligible === "boolean";
}

function isMetricComparisonRef(value: unknown): boolean {
  if (!isEvidenceRef(value)) return false;
  const candidate = value as unknown as Record<string, unknown>;
  return stringArray(candidate.observation_resource_ids, true)
    && nonEmptyString(candidate.method_version)
    && hash(candidate.method_sha256)
    && typeof candidate.sufficient_evidence === "boolean";
}

function isModelCallRef(value: unknown): boolean {
  if (!isEvidenceRef(value)) return false;
  const candidate = value as unknown as Record<string, unknown>;
  return [candidate.prompt_release_resource_id, candidate.model_identity].every(nonEmptyString)
    && typeof candidate.succeeded === "boolean";
}

function booleanFields(value: unknown, ...names: string[]): boolean {
  if (!isEvidenceRef(value)) return false;
  const candidate = value as unknown as Record<string, unknown>;
  return names.every((name) => typeof candidate[name] === "boolean");
}

function evidenceArray(
  value: unknown,
  guard: (item: unknown) => boolean
): boolean {
  return Array.isArray(value) && value.every(guard);
}

function isApproval(value: unknown): boolean {
  return record(value)
    && [value.id, value.approved_by, value.approved_at, value.valid_until]
      .every(nonEmptyString)
    && positiveInteger(value.recommendation_version)
    && hash(value.frozen_input_fingerprint)
    && hash(value.frozen_evidence_graph_hash);
}

function isLinkedDraft(value: unknown): value is LinkedDraft {
  if (!record(value)) return false;
  return [
    value.id,
    value.recommendation_id,
    value.approval_id,
    value.created_at
  ].every(nonEmptyString)
    && positiveInteger(value.recommendation_version)
    && draftKinds.has(String(value.kind))
    && draftStatuses.has(String(value.status))
    && hash(value.frozen_input_fingerprint)
    && hash(value.frozen_evidence_graph_hash)
    && optionalString(value.started_at)
    && optionalString(value.blocked_at)
    && optionalString(value.blocked_reason)
    && value.draft_only === true
    && value.enqueued === false
    && value.executed === false
    && value.published === false;
}

function record(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringArray(value: unknown, required = false): boolean {
  return Array.isArray(value)
    && (!required || value.length > 0)
    && value.every(nonEmptyString);
}

function optionalString(value: unknown): boolean {
  return value === null || nonEmptyString(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function hash(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}
