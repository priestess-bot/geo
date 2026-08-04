import type { SyntheticBoundary, SyntheticChannel } from "./syntheticLabTypes";
import {
  hasSyntheticBoundary,
  hasUuidFields,
  isHash,
  isUuid,
  nonEmptyString,
  nullableHash,
  nullableString,
  positiveInteger,
  safeRecord,
  stringArray
} from "./syntheticLabTypePrimitives";

export type SyntheticClaimAssessment = Readonly<{
  claim_hash: string;
  status: "current_approved" | "derived_or_unknown" | "explicit_conflict" | "subject_mixup";
  fact_id: string | null;
  fact_hash: string | null;
  expected_subject_id: string | null;
  observed_subject_id: string | null;
  output_annotation: string | null;
  evidence_refs: string[];
}>;

export type SyntheticCandidateEvaluation = Readonly<{
  id: string;
  candidate_id: string;
  candidate_output_hash: string;
  style_score: number;
  style_passed: boolean;
  disposition: "pass" | "warning" | "revise";
  correctable_issue_codes: string[];
  soft_issue_codes: string[];
  warning_codes: string[];
  claim_assessments: SyntheticClaimAssessment[];
  provider: string;
  configured_model: string;
  evidence_artifact_hash: string;
}>;

export type SyntheticCandidateRevision = Readonly<{
  id: string;
  round_number: number;
  parent_candidate_id: string;
  parent_output_hash: string;
  revised_candidate_id: string;
  revised_output_hash: string;
  issue_codes: string[];
  provider: string;
  configured_model: string;
}>;

export type SyntheticGenerationBatch = Readonly<{
  id: string;
  batch_number: number;
  kind: "initial" | "regenerated";
  scenario_mode: "autonomous_scenario" | "guided_scenario";
  candidate_count: number;
  provider: string;
  configured_model: string;
}>;

export type SyntheticReviewResult = SyntheticBoundary & Readonly<{
  job_id: string;
  project_id: string;
  review_run_id: string;
  run_origin: "direct" | "regression";
  input_snapshot_id: string | null;
  review_suite_version_id: string | null;
  review_case_id: string | null;
  scenario_id: string;
  case_key: string;
  channel: SyntheticChannel;
  scenario_mode: "autonomous_scenario" | "guided_scenario";
  competitor_scenario: boolean;
  style_pass_threshold: number;
  runtime_selection_id: string;
  profile_version_id: string;
  fact_snapshot_id: string;
  generation_goal: string | null;
  channel_style_version_id: string | null;
  channel_style_version_number: number | null;
  channel_style_hash: string | null;
  knowledge_snapshot_hash: string | null;
  knowledge_context_items: ReadonlyArray<Readonly<{
    evidence_id: string;
    kind: "approved_fact" | "citation";
    subject_entity_id: string;
    subject_name: string;
    summary: string;
    snapshot_hash: string;
    source_title: string | null;
    source_url: string | null;
    trace_href: string;
    matched: boolean;
    conflicting: boolean;
  }>>;
  final_text: string | null;
  status: "passed" | "completed_with_warning" | "failed";
  warning_codes: string[];
  failure_code: string | null;
  resolution_candidate_id: string;
  result_hash: string;
  batches: SyntheticGenerationBatch[];
  evaluations: SyntheticCandidateEvaluation[];
  revisions: SyntheticCandidateRevision[];
  model_call_ids: string[];
  workflow_attempt_ids: string[];
}>;

export function isSyntheticReviewResult(value: unknown): value is SyntheticReviewResult {
  if (!safeRecord(value) || !hasSyntheticBoundary(value)) return false;
  return hasUuidFields(value, [
    "job_id", "project_id", "review_run_id", "scenario_id",
    "runtime_selection_id", "profile_version_id",
    "fact_snapshot_id", "resolution_candidate_id"
  ])
    && ["direct", "regression"].includes(String(value.run_origin))
    && [value.input_snapshot_id, value.review_suite_version_id, value.review_case_id,
      value.channel_style_version_id].every((item) => item === null || isUuid(item))
    && nonEmptyString(value.case_key)
    && isChannel(value.channel)
    && ["autonomous_scenario", "guided_scenario"].includes(String(value.scenario_mode))
    && typeof value.competitor_scenario === "boolean"
    && typeof value.style_pass_threshold === "number"
    && value.style_pass_threshold >= 0 && value.style_pass_threshold <= 5
    && (value.generation_goal === null || nonEmptyString(value.generation_goal))
    && (value.channel_style_version_number === null
      || positiveInteger(value.channel_style_version_number))
    && nullableHash(value.channel_style_hash)
    && nullableHash(value.knowledge_snapshot_hash)
    && Array.isArray(value.knowledge_context_items)
    && value.knowledge_context_items.every(isKnowledgeContextItem)
    && (value.final_text === null || nonEmptyString(value.final_text))
    && ["passed", "completed_with_warning", "failed"].includes(String(value.status))
    && stringArray(value.warning_codes)
    && nullableString(value.failure_code)
    && isHash(value.result_hash)
    && Array.isArray(value.batches) && value.batches.every(isGenerationBatch)
    && Array.isArray(value.evaluations) && value.evaluations.every(isCandidateEvaluation)
    && Array.isArray(value.revisions) && value.revisions.every(isCandidateRevision)
    && Array.isArray(value.model_call_ids) && value.model_call_ids.every(nonEmptyString)
    && Array.isArray(value.workflow_attempt_ids)
    && value.workflow_attempt_ids.every(nonEmptyString);
}

function isGenerationBatch(value: unknown): value is SyntheticGenerationBatch {
  return safeRecord(value)
    && hasUuidFields(value, ["id"])
    && positiveInteger(value.batch_number)
    && ["initial", "regenerated"].includes(String(value.kind))
    && ["autonomous_scenario", "guided_scenario"].includes(String(value.scenario_mode))
    && positiveInteger(value.candidate_count)
    && nonEmptyString(value.provider)
    && nonEmptyString(value.configured_model);
}

function isCandidateEvaluation(value: unknown): value is SyntheticCandidateEvaluation {
  return safeRecord(value)
    && hasUuidFields(value, ["id", "candidate_id"])
    && isHash(value.candidate_output_hash)
    && typeof value.style_score === "number" && value.style_score >= 0 && value.style_score <= 5
    && typeof value.style_passed === "boolean"
    && ["pass", "warning", "revise"].includes(String(value.disposition))
    && stringArray(value.correctable_issue_codes)
    && stringArray(value.soft_issue_codes)
    && stringArray(value.warning_codes)
    && Array.isArray(value.claim_assessments)
    && value.claim_assessments.every(isClaimAssessment)
    && nonEmptyString(value.provider)
    && nonEmptyString(value.configured_model)
    && isHash(value.evidence_artifact_hash);
}

function isClaimAssessment(value: unknown): value is SyntheticClaimAssessment {
  return safeRecord(value)
    && isHash(value.claim_hash)
    && [
      "current_approved", "derived_or_unknown", "explicit_conflict", "subject_mixup"
    ].includes(String(value.status))
    && (value.fact_id === null || nonEmptyString(value.fact_id))
    && nullableHash(value.fact_hash)
    && (value.expected_subject_id === null || nonEmptyString(value.expected_subject_id))
    && (value.observed_subject_id === null || nonEmptyString(value.observed_subject_id))
    && nullableString(value.output_annotation)
    && stringArray(value.evidence_refs);
}

function isKnowledgeContextItem(value: unknown): boolean {
  return safeRecord(value) && hasUuidFields(value, ["evidence_id", "subject_entity_id"])
    && ["approved_fact", "citation"].includes(String(value.kind))
    && nonEmptyString(value.subject_name) && nonEmptyString(value.summary)
    && isHash(value.snapshot_hash)
    && nullableString(value.source_title) && nullableString(value.source_url)
    && nonEmptyString(value.trace_href)
    && typeof value.matched === "boolean" && typeof value.conflicting === "boolean";
}

function isCandidateRevision(value: unknown): value is SyntheticCandidateRevision {
  return safeRecord(value)
    && hasUuidFields(value, ["id", "parent_candidate_id", "revised_candidate_id"])
    && positiveInteger(value.round_number) && value.round_number <= 2
    && isHash(value.parent_output_hash)
    && isHash(value.revised_output_hash)
    && stringArray(value.issue_codes)
    && nonEmptyString(value.provider)
    && nonEmptyString(value.configured_model);
}

function isChannel(value: unknown): value is SyntheticChannel {
  return [
    "owned_site", "amazon", "youtube", "tiktok", "instagram",
    "productreview", "reddit", "ozbargain", "quora"
  ].includes(String(value));
}
