export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export type JsonObject = { [key: string]: JsonValue };

export type PublicationChannel =
  | "owned_site" | "productreview" | "youtube" | "reddit" | "amazon"
  | "ozbargain" | "tiktok" | "instagram" | "quora" | "other";
export type QueryKind = "recommendation" | "comparison" | "research" | "support";
export type MeasurementWindow = "baseline" | "t28" | "t56" | "t84" | "ad_hoc";
export type JobState = "queued" | "running" | "finalizing" | "retry_wait" | "succeeded" | "failed" | "dead_lettered" | "cancelled";

export interface CampaignCreate {
  destination_ids: string[];
  market_profile_id: string;
  name: string;
  objective?: string;
  opportunity_rationale: string;
  primary_product_entity_id: string;
}
export interface CampaignView {
  id: string; project_id: string; market_profile_id: string; primary_product_entity_id: string;
  name: string; objective: string; status: string;
}
export interface CampaignCreated { campaign: CampaignView; opportunities: OpportunityView[]; }
export interface MonitoringQueryCreate { market_profile_id: string; query_text: string; query_kind: QueryKind; locale: string; }
export interface MonitoringQueryView extends MonitoringQueryCreate {
  id: string; project_id: string; campaign_id: string; status: string;
}

export interface DestinationCreate {
  publication_channel: PublicationChannel; destination_key: string; canonical_url: string;
  destination_account_id?: string | null; operation_mode?: "manual" | "assisted" | "api";
}
export interface DestinationView extends DestinationCreate {
  id: string; project_id: string; canonical_host: string; allowed_hosts: string[]; policy_status: string;
}
export interface DestinationPolicyReviewCreate {
  status: "approved" | "restricted" | "prohibited"; allowed_hosts: string[];
  disclosure_requirements?: JsonObject; identity_requirements?: JsonObject; rules?: JsonObject;
}
export interface DestinationPolicyView extends DestinationPolicyReviewCreate {
  id: string; project_id: string; destination_id: string; version_number: number;
  reviewed_by: string; reviewed_at: string;
}
export interface OpportunityView {
  id: string; project_id: string; campaign_id: string; destination_id: string;
  opportunity_ref: string; rationale: string; status: string;
  allowed_commands: Array<"qualify" | "block" | "reopen" | "cancel">;
}
export interface OpportunityStateCommand { reason?: string | null; }

export interface ConsumerExperienceInput { description: string; disclosure: string; source: string; usage_rights: string; }
export interface BriefVersionCreate {
  primary_brand_entity_id: string; goals: JsonObject; base_version_id?: string | null;
  allowed_subject_entity_ids?: string[]; compared_entity_ids?: string[]; constraints?: JsonObject;
  authenticity_risks?: Array<"synthetic_testimonial" | "fake_persona" | "unsupported_first_person_experience" | "hidden_commercial_relationship">;
  consumer_experience?: ConsumerExperienceInput | null;
}
export interface BriefVersionView {
  id: string; project_id: string; campaign_id: string; opportunity_id: string; destination_id: string;
  brief_id: string; version_number: number; base_version_id: string | null;
  goals: JsonObject; constraints: JsonObject; content_hash: string;
}
export interface EvidenceAttemptView {
  id: string; project_id: string; campaign_id: string; opportunity_id: string; destination_id: string;
  brief_version_id: string; attempt_number: number;
  status: string; pack_hash: string | null; failure_reason: string | null;
}
export interface EvidenceKnowledgeLineageView {
  lineage_contract_version: "legacy-relational-v1" | "knowledge-fact-evidence-v1";
  project_id: string; pipeline_run_id: string; knowledge_source_id: string;
  knowledge_document_id: string; knowledge_chunk_id: string; knowledge_fact_id: string;
  evidence_item_id: string; evidence_title: string; promoted_by: string; promoted_at: string;
  source_content_hash: string; document_cleaned_text_hash: string; chunk_text_hash: string;
  fact_statement_hash: string; evidence_snapshot_hash: string;
  idempotency_key: string; promotion_request_hash: string;
}
export interface EvidenceItemView {
  id: string; item_type: string; subject_entity_id: string | null; subject_role: string;
  snapshot_hash: string; usage_rights: string; confidentiality: string;
  public_disclosure_allowed: boolean; public_source_url: string | null; public_source_title: string | null;
  citation_label: string | null; quotation_allowed: boolean; attribution_required: boolean;
  knowledge_lineage: EvidenceKnowledgeLineageView | null;
}
export interface AsyncResourceCreated { resource: EvidenceAttemptView; job_id: string; status: JobState; status_url: string; }

export interface PromptSkillCreate { skill_key: string; }
export interface PromptSkillView { id: string; project_id: string; skill_key: string; status: string; }
export type PromptReleaseStatus = "draft" | "approved" | "revoked";
export interface PromptReleaseCreate {
  source: string; system_template: string; user_template: string;
  output_schema: JsonObject; client_variable_names?: string[];
}
export interface PromptReleaseView {
  id: string; project_id: string; skill_version_id: string; release_number: number; release_hash: string;
  skill_key: string; skill_version: number; status: PromptReleaseStatus; state_version: number;
  approved_by: string | null; approved_at: string | null; revoked_by: string | null;
  revoked_at: string | null; state_reason: string | null;
  source_text: string; system_template: string; user_template: string; variable_schema: JsonObject;
  output_schema: JsonObject; compiler_version: string;
}
export interface PromptReleaseTransition {
  expected_state_version: number; reason?: string | null;
}
export interface PromptTaskBindingCreate { template_release_id: string; }
export interface PromptTaskBindingView { project_id: string; selected_at: string; selected_by: string; task_key: string; template_release_id: string; }
export interface OpportunityPromptReleaseBindingCreate {
  template_release_id: string; reason?: string | null; expected_binding_version: number;
}
export interface OpportunityPromptReleaseBindingView {
  id: string; project_id: string; campaign_id: string; opportunity_id: string; destination_id: string;
  binding_version: number; previous_binding_id: string | null; status: "unbound" | "bound";
  changed_by: string | null; changed_at: string; reason: string | null; template_release_id: string | null;
  skill_key: string | null; skill_version_id: string | null;
  release_version: number | null; release_hash: string | null;
}
export type ChannelReadinessReason =
  | "missing_opportunity" | "duplicate_channel" | "campaign_owner_mismatch"
  | "opportunity_blocked" | "opportunity_not_generation_ready"
  | "destination_policy_missing" | "destination_policy_not_approved"
  | "prompt_binding_missing" | "prompt_release_draft" | "prompt_release_revoked"
  | "brief_missing" | "evidence_pack_missing" | "evidence_pack_not_ready"
  | "evidence_items_missing";
export interface CampaignChannelReadinessView {
  publication_channel: PublicationChannel; ready: boolean; reasons: ChannelReadinessReason[];
  opportunity_id: string | null; destination_id: string | null; prompt_binding_id: string | null;
  template_release_id: string | null; release_version: number | null; release_hash: string | null;
  brief_version_id: string | null; evidence_pack_attempt_id: string | null;
}
export interface CampaignPlacementReadinessView {
  project_id: string; campaign_id: string; ready_count: number; is_ready: boolean;
  channels: CampaignChannelReadinessView[];
}
export interface PromptBundleCreate {
  campaign_id: string; opportunity_id: string; prompt_release_binding_id: string;
  confirmed_release_hash: string; evidence_pack_attempt_id: string; model_policy_hash: string;
  variables: JsonObject;
}
export interface PromptBundleView {
  artifact_status: string; brief_version_id: string; bundle_hash: string; evidence_pack_attempt_id: string;
  id: string; project_id: string; campaign_id: string; opportunity_id: string; destination_id: string;
  prompt_release_binding_id: string | null; storage_key: string; storage_uri: string | null;
  prompt_release_binding_version: number | null;
  template_release_id: string; skill_version_id: string; release_version: number; release_hash: string;
}
export interface PromptBundleDetail extends PromptBundleView { manifest: JsonObject; }
export interface GenerationCreate { configured_model?: string; model_call_budget?: number; }
export type PromptSimulationAuthenticityMode =
  | "brand_authored" | "fake_persona" | "synthetic_testimonial";
export type PromptSimulationPurpose = "content_preview" | "geo_question_test";
export interface PromptSimulationCreate {
  campaign_id: string; opportunity_id: string; destination_id: string;
  prompt_release_binding_id: string; confirmed_release_hash: string; primary_brand_entity_id: string;
  product_entity_id: string; authenticity_mode?: PromptSimulationAuthenticityMode;
  evidence_item_ids: string[]; goals: JsonObject;
  constraints?: JsonObject; variables?: JsonObject; model_policy_hash?: string;
  configured_model?: string; model_call_budget?: number;
  simulation_purpose?: PromptSimulationPurpose;
  question_set_id?: string | null; confirmed_question_set_hash?: string | null;
  question_set_item_id?: string | null;
}
export interface PromptSimulationView {
  id: string; project_id: string; campaign_id: string | null; opportunity_id: string | null; destination_id: string;
  destination_policy_version_id: string | null; template_release_id: string;
  prompt_release_binding_id: string | null; prompt_release_binding_version: number | null;
  skill_version_id: string; release_version: number; release_hash: string;
  primary_brand_entity_id: string; product_entity_id: string; requested_by: string;
  authenticity_mode: PromptSimulationAuthenticityMode;
  input_hash: string; test_only: true; publication_eligible: false; created_at: string;
  generation_job_id: string; generation_status: JobState; configured_model: string;
  model_call_budget: number; artifact_status: string; artifact_uri: string | null;
  storage_key: string | null; output_hash: string | null; manifest_hash: string | null;
  model_response_hash: string | null; input_snapshot: JsonObject | null;
  artifact_manifest: JsonObject | null;
  simulation_purpose: PromptSimulationPurpose;
  question_set_id: string | null; question_set_hash: string | null;
  question_set_item_id: string | null; question_candidate_id: string | null;
}
export interface PromptSimulationCreated {
  simulation: PromptSimulationView; job_id: string; status: JobState; status_url: string;
}
export interface JobAccepted { job_id: string; status: JobState; status_url: string; }
export interface JobStatus {
  id: string; kind: string; status: JobState; campaign_id?: string | null;
  created_at: string; updated_at: string;
  error_code?: string | null; result_details?: JsonObject | null; result_ref?: string | null;
}
export interface PlacementJobView {
  id: string; kind: string; project_id: string; campaign_id: string | null; status: JobState;
}
export interface PlacementJobEventView {
  id: string; job_id: string; project_id: string; event_type: string; details: JsonObject;
  fencing_generation: number | null; worker_id: string; created_at: string;
}

export interface PackageVersionView {
  id: string; project_id: string; campaign_id: string; opportunity_id: string; destination_id: string;
  package_id: string; prompt_bundle_id: string; version_number: number;
  base_version_id: string | null; content_json: JsonObject; rendered_text: string; content_hash: string;
  workflow_status: string; generated_by_job_id: string | null; edited_by: string | null; edit_reason: string | null;
}
export interface ClaimView {
  id: string; project_id: string; package_version_id: string; claim_kind: string; claim_text: string;
  evidence_item_ids: string[]; support_status: string;
}
export interface ReviewCreate {
  decision: "approved" | "needs_revision" | "rejected" | "blocked";
  claim_inventory_complete: boolean; extracted_claim_support_confirmed: boolean; notes?: string | null; score?: number | null;
}
export interface ReviewView extends ReviewCreate {
  id: string; package_version_id: string; project_id: string; reviewer_id: string;
  submitted_for_review_by: string; reviewed_at?: string | null;
}
export interface ReviewSubmissionView { id: string; package_version_id: string; project_id: string; submitted_at: string; submitted_by: string; }
export interface PackageEdit {
  base_content_hash: string; base_version_id: string; content_json: JsonObject; reason: string; rendered_text: string;
  claims: PackageClaimEdit[];
}
export interface PackageClaimEdit {
  text: string; kind: "factual" | "comparative" | "experience" | "non_factual";
  support_status: "supported" | "unsupported" | "conflict" | "not_required";
  evidence_item_ids: string[];
}
export interface ExportView {
  id: string; project_id: string; package_version_id: string; export_format: string; content_hash: string;
  storage_key: string; artifact_uri: string | null; artifact_status: string; requested_by: string; exported_at: string;
  package_version: PackageVersionView; claims: ClaimView[];
}
export interface PublicationCreate {
  destination_id: string; policy_basis?: string | null; publication_attempt?: number; restricted_policy_acknowledged?: boolean;
}
export interface PublicationView {
  id: string; project_id: string; campaign_id: string; opportunity_id: string;
  package_version_id: string; destination_id: string; destination_key: string;
  publication_channel: string; publication_attempt: number; policy_basis: string | null;
  restricted_policy_acknowledged: boolean; idempotency_key: string; status: string;
}
export interface SubmissionCreate { provider_submission_id?: string | null; submitted_url?: string | null; }
export interface SubmissionView {
  id: string; project_id: string; campaign_id: string; opportunity_id: string; destination_id: string;
  publication_request_id: string; status: string;
  idempotency_key: string; submitted_by: string;
  provider_submission_id?: string | null; submitted_url?: string | null;
  url_backfilled_at?: string | null; url_backfilled_by?: string | null; verification_result?: JsonObject | null;
}
export interface PublicationVerificationCheckView {
  name: "input_contract" | "public_url" | "redirect_policy" | "http_2xx" | "html_response"
    | "approved_content" | "required_disclosures" | "expected_links";
  passed: boolean; failure_code: string | null;
}
export interface PublicationVerificationFailureView {
  code: string; disposition: "retryable" | "permanent"; check: string; retryable: boolean;
}
export interface PublicationVerificationAttemptView {
  id: string; project_id: string; campaign_id: string; opportunity_id: string;
  submission_id: string; job_id: string; attempt_number: number;
  verifier_version: "publication-url-verifier-v2";
  outcome: "passed" | "failed" | "retryable_error" | "permanent_error";
  checked_at: string; status_code: number | null; final_url: string | null;
  metadata_hash: string | null; body_hash: string | null; visible_text_hash: string | null;
  content_rule_hash: string | null; verification_rule_hash: string | null;
  redirect_count: number; checks: PublicationVerificationCheckView[];
  failures: PublicationVerificationFailureView[]; error_code: string | null;
  failure_disposition: "retryable" | "permanent" | null; result_hash: string; created_at: string;
}
export interface StateReasonCreate { reason: string; }
export interface SubmissionUrlCreate { submitted_url: string; }
export interface MeasurementCreate {
  monitoring_query_id: string; measured_at: string; citation_present: boolean; result_snapshot_uri: string;
  metrics?: JsonObject; recommendation_position?: number | null;
}
export interface MeasurementView extends MeasurementCreate {
  id: string; project_id: string; campaign_id: string; submission_id: string;
}
export interface MeasurementCollectionTaskView {
  id: string; project_id: string; job_id: string; submission_id: string; protocol_id: string;
  measurement_window: "t28" | "t56" | "t84"; expected_sample_count: number;
  actual_sample_count: number; scheduled_for: string; status: "open" | "completed" | "cancelled";
  opened_at: string; completed_at: string | null; cancelled_at: string | null;
  acted_by: string | null; state_reason: string | null;
}

export type ObservationCaptureMethod =
  | "official_report_import" | "manual_ui" | "provider_api" | "proxy_grounded_api"
  | "synthetic" | "unknown";
export type OperatorObservationCaptureMethod =
  | "manual_ui" | "provider_api" | "proxy_grounded_api";
export type ObservationPlatform =
  | "openai" | "google" | "perplexity" | "microsoft" | "kimi" | "anthropic" | "other";
export type ObservationSurface =
  | "chatgpt_search" | "google_search" | "google_ai_overviews" | "google_ai_mode"
  | "gemini" | "perplexity_answer" | "bing_search" | "bing_copilot" | "claude_ai"
  | "openai_api" | "google_gemini_api" | "perplexity_api" | "kimi_api" | "anthropic_api"
  | "microsoft_foundry_bing_grounding" | "google_vertex_grounding"
  | "google_generative_ai_performance_report" | "bing_ai_performance_report"
  | "internal_benchmark" | "other";
export type ObservationSurfaceKind =
  | "consumer_ui" | "official_report" | "provider_api" | "grounded_proxy"
  | "internal_benchmark" | "other";
export type ObservationModelState = "disclosed" | "not_disclosed" | "not_applicable";
export type ObservationDevice =
  | "desktop" | "mobile" | "tablet" | "api" | "internal_worker" | "report";
export type ObservationClientKind =
  | "browser" | "native_app" | "api" | "internal_worker" | "report_import";
export type ObservationSearchMode =
  | "disabled" | "live_web" | "grounded_web" | "automatic" | "not_applicable";
export interface ObservationModelIdentity {
  state: ObservationModelState; value: string | null;
}
export interface ObservationRunParameters {
  engine: string; locale: string; region: string; language: string; device: ObservationDevice;
  client_kind: ObservationClientKind; search_enabled: boolean; search_mode: ObservationSearchMode;
  prompt_text: string; follow_up_prompts: string[]; adapter_name: string | null;
  adapter_version: string | null; provider_request_id: string | null;
}
export interface ObservationRunParametersView {
  engine: string | null; locale: string | null; region: string | null; language: string | null;
  device: ObservationDevice | null; client_kind: ObservationClientKind | null;
  search_enabled: boolean | null; search_mode: ObservationSearchMode | null;
  prompt_text: string | null; follow_up_prompts: string[]; adapter_name: string | null;
  adapter_version: string | null; provider_request_id: string | null;
}
export type ObservationRawEvidence =
  | { kind: "answer"; answer: string }
  | { kind: "inline_response"; inline_response: JsonObject }
  | { kind: "artifact"; artifact_uri: string; artifact_hash: string };
export interface ObservationSourceCreate {
  platform: ObservationPlatform; surface: ObservationSurface; surface_kind: ObservationSurfaceKind;
  platform_detail: string | null; surface_detail: string | null;
  configured_model: ObservationModelIdentity; reported_model: ObservationModelIdentity;
  run: ObservationRunParameters; raw_evidence: ObservationRawEvidence;
}
export interface ObservationSourceStratumCreate {
  capture_method: ObservationCaptureMethod; platform: ObservationPlatform;
  platform_detail: string | null; surface: ObservationSurface;
  surface_kind: ObservationSurfaceKind; surface_detail: string | null;
  source_contract_version?: "geo-observation-source-v2" | "geo-observation-source-v3";
  locale: string; region: string;
  language: string; device: ObservationDevice; client_kind: ObservationClientKind;
  search_enabled: boolean; search_mode: ObservationSearchMode; engine: string;
  configured_model: ObservationModelIdentity; reported_model: ObservationModelIdentity;
}
export interface MonitoringProtocolCreate {
  campaign_id: string; market_profile_id: string; name: string;
  platform: "chatgpt_search" | "google_ai_overviews" | "google_ai_mode" | "google_search"
    | "perplexity" | "perplexity_answer" | "gemini" | "bing_search" | "bing_copilot" | "claude_ai" | "other";
  locale: string; device: "desktop" | "mobile" | "tablet"; sample_size: number;
  minimum_valid_repeats: number;
  window_days: number; source_strata: ObservationSourceStratumCreate[];
}
export interface MonitoringProtocolView extends Omit<MonitoringProtocolCreate, "minimum_valid_repeats"> {
  minimum_valid_repeats: number | null;
  id: string; project_id: string; status: "draft" | "approved" | "frozen"; protocol_hash: string | null;
  created_at: string; approved_at: string | null; frozen_at: string | null;
  source_strata_hash: string | null; statistics_method_version: string | null;
  statistics_contract_version: string;
  question_set_id: string | null; question_set_hash: string | null;
  question_set_bound_by: string | null; question_set_bound_at: string | null;
}

export type KnowledgeQuestionFunnel = "awareness" | "consideration" | "decision" | "retention";
export type KnowledgeQuestionBrandScope = "brand" | "non_brand" | "competitor";
export type KnowledgeQuestionPlatform =
  | "chatgpt_search" | "google_ai_overviews" | "google_search"
  | "perplexity" | "gemini" | "other";
export interface KnowledgeQuestionFactView {
  id: string; project_id: string; pipeline_run_id: string; source_id: string;
  source_title: string; chunk_id: string; statement: string; statement_hash: string;
  status: string; lifecycle_status: string; extractor_release: string;
  reviewed_by: string | null; review_notes: string | null;
  reviewed_at: string | null; created_at: string;
}
export interface KnowledgeQuestionDimensionCreate {
  dimension_key?: string; turn_index: 1 | 2 | 3; parent_dimension_key?: string | null;
  persona: string; scenario: string; intent: string; funnel: KnowledgeQuestionFunnel;
  region: string; language: string; brand_scope: KnowledgeQuestionBrandScope;
  platform: KnowledgeQuestionPlatform; query_kind: QueryKind; subject: string;
  competitor_entity_id?: string | null;
}
export interface KnowledgeQuestionGenerationCreate {
  configured_model?: "deepseek-v4-flash"; model_call_budget?: number;
  semantic_duplicate_threshold?: number; fact_candidate_ids: string[];
  graph_entity_ids: string[]; dimensions: KnowledgeQuestionDimensionCreate[];
}
export interface KnowledgeQuestionGenerationCreated {
  job_id: string; project_id: string; campaign_id: string; status: JobState;
  input_hash: string; dimension_count: number; fact_input_count: number;
  entity_input_count: number;
}
export interface KnowledgeQuestionGenerationView {
  job_id: string; project_id: string; campaign_id: string; status: JobState;
  input_hash: string; error_code: string | null; configured_model: string;
  execution_backend: "dify" | "native" | null; actual_model: string | null;
  model_call_budget: number; adapter_release: string;
  semantic_duplicate_threshold: number; artifact_uri: string | null;
  artifact_hash: string | null; dimension_count: number | null;
  candidate_count: number | null; supported_dimension_count: number | null;
  possible_duplicate_count: number | null; generated_at: string | null; created_at: string;
}
export type KnowledgeQuestionDedupStatus =
  | "unique" | "possible_duplicate" | "exact_duplicate";
export type KnowledgeQuestionReviewStatus = "pending_review" | "approved" | "rejected";
export interface KnowledgeQuestionCandidateView {
  id: string; project_id: string; campaign_id: string; generated_by_job_id: string;
  dimension_key: string; variant_index: number; turn_index: 1 | 2 | 3;
  parent_candidate_id: string | null; query_text: string; query_text_hash: string;
  semantic_fingerprint: string; dedup_status: KnowledgeQuestionDedupStatus;
  nearest_candidate_id: string | null; nearest_similarity: number | null;
  workflow_status: KnowledgeQuestionReviewStatus; review_notes: string | null;
  reviewed_at: string | null; fact_source_ids: string[]; entity_source_ids: string[];
  created_at: string;
}
export interface KnowledgeQuestionCandidateReview {
  decision: "approved" | "rejected"; notes: string;
}
export interface KnowledgeQuestionSetCreate {
  name: string; generation_job_id: string; candidate_ids: string[];
  series_id?: string | null; previous_version_id?: string | null;
}
export interface KnowledgeQuestionSetItemView {
  id: string; ordinal: number; question_candidate_id: string; dimension_key: string;
  query_text_snapshot: string; query_text_hash: string; query_kind_snapshot: QueryKind;
  query_cluster_key: string; source_lineage_hash: string;
}
export interface KnowledgeQuestionSetView {
  id: string; project_id: string; campaign_id: string; series_id: string;
  previous_version_id: string | null; version_number: number; generated_by_job_id: string;
  name: string; status: "draft" | "approved" | "frozen";
  dimension_count: number; covered_dimension_count: number; possible_duplicate_count: number;
  coverage_ratio: number; duplicate_ratio: number; content_hash: string | null;
  created_at: string; approved_at: string | null; frozen_at: string | null;
  items: KnowledgeQuestionSetItemView[];
}
export interface MonitoringProtocolQuestionSetBindingCreate {
  campaign_id: string; question_set_id: string; confirmed_content_hash: string;
}
export interface ObservationCitationCreate {
  url: string; title?: string | null; submission_id?: string | null;
}
export interface ObservationCitationView {
  id: string; citation_index: number; url: string; verification_status: "passed" | "failed" | "unknown"; verified_placement: boolean;
  title: string | null; destination_id: string | null; submission_id: string | null;
}
export interface MonitoringObservationCreate {
  campaign_id: string; monitoring_query_id: string; measurement_window: MeasurementWindow;
  sample_index: number; result_status: "succeeded" | "failed";
  capture_method: OperatorObservationCaptureMethod; requested_eligible: boolean;
  operator_ineligible_reasons: string[];
  url_verification_status: "passed" | "failed" | "unknown"; observed_at: string;
  citations: ObservationCitationCreate[]; competitor_mentioned: boolean;
  primary_product_mentioned: boolean; recommendation_present: boolean;
  source: ObservationSourceCreate;
}
export interface ObservationRawEvidenceView {
  kind: "answer" | "inline_response" | "artifact" | "legacy_unknown";
  answer: string | null; inline_response: JsonObject | null;
  artifact_uri: string | null; artifact_hash: string | null; artifact_verified: boolean;
}
export interface ObservationSourceView extends Omit<ObservationSourceCreate, "raw_evidence" | "run"> {
  capture_method: ObservationCaptureMethod; raw_evidence: ObservationRawEvidenceView;
  run: ObservationRunParametersView;
  source_contract_version: string; citations_captured: boolean; source_job_id: string | null;
  model_call_log_id: string | null; test_only: boolean; publication_eligible: boolean;
  source_badge: string;
}
export interface MonitoringObservationView extends Omit<MonitoringObservationCreate, "capture_method" | "source" | "operator_ineligible_reasons"> {
  id: string; project_id: string; protocol_id: string; eligible: boolean;
  capture_method: ObservationCaptureMethod;
  ineligible_reasons: string[]; source: ObservationSourceView;
  source_stratum: ObservationSourceStratumCreate | null; source_stratum_hash: string | null;
  captured_by: string; query_cluster_key: string | null;
  citations: ObservationCitationView[]; payload_hash: string; replayed: boolean; created_at: string;
  configured_model: string | null; ui_surface: string; provider_reported_model: string | null;
  raw_answer: string | null; artifact_uri: string | null; artifact_hash: string | null;
  raw_result: JsonObject; ui_metadata: JsonObject; confounding_factors: string[];
}
export interface OfficialReportRowCreate {
  row_index: number; row_data: JsonObject; requested_eligible?: boolean;
  operator_ineligible_reasons?: string[];
}
export interface OfficialReportImportCreate {
  campaign_id: string; platform: ObservationPlatform;
  surface: "google_generative_ai_performance_report" | "bing_ai_performance_report";
  platform_detail?: string | null; surface_detail?: string | null;
  artifact: Extract<ObservationRawEvidence, { kind: "artifact" }>;
  parser_name: string; parser_version: string; report_period_start: string;
  report_period_end: string; account_ref: string; rows: OfficialReportRowCreate[];
}
export interface OfficialReportRowView {
  id: string; row_index: number; row_data: JsonObject; eligible: boolean;
  ineligible_reasons: string[]; row_hash: string;
  created_at: string;
}
export interface OfficialReportImportView extends Omit<OfficialReportImportCreate, "artifact" | "rows"> {
  id: string; project_id: string; capture_method: "official_report_import";
  artifact_uri: string; artifact_hash: string; payload_hash: string; imported_by: string;
  rows: OfficialReportRowView[]; created_at: string; replayed: boolean;
}
export interface BinaryEstimateView {
  numerator: number; denominator: number; share: number; ci_low: number; ci_high: number;
}
export interface QueryMetricResultView {
  monitoring_query_id: string; query_text_snapshot: string; query_cluster_key: string;
  expected_sample_count: number; sampled_sample_count: number; valid_sample_count: number;
  invalid_sample_count: number; missing_sample_count: number; meets_threshold: boolean;
  invalid_reason_counts: Record<string, number>; confounding_factors: string[];
  recommendation: BinaryEstimateView; product_mention: BinaryEstimateView;
  placement_citation: BinaryEstimateView; competitor: BinaryEstimateView;
  competitive_delta: number;
}
export interface MetricCompute {
  campaign_id: string; measurement_window: MeasurementWindow;
  source_stratum_hash: string; query_cluster_key: string;
}
export interface MetricView {
  id: string; project_id: string; protocol_id: string; campaign_id: string; measurement_window: MeasurementWindow;
  capture_method: ObservationCaptureMethod; source_stratum: ObservationSourceStratumCreate | null;
  source_stratum_hash: string | null; statistics_contract_version: string;
  query_cluster_key: string | null; analysis_stratum_hash: string | null;
  observation_membership_version: string | null; observation_membership_hash: string | null;
  observation_membership_count: number | null;
  minimum_valid_repeats: number | null; expected_sample_count: number;
  sampled_sample_count: number | null; eligible_sample_count: number;
  invalid_sample_count: number | null; missing_sample_count: number | null;
  sampling_completion_ratio: number | null; valid_completion_ratio: number | null;
  query_count: number | null; sufficient_query_count: number | null;
  invalid_reason_counts: Record<string, number>; declared_confounding_factors: string[];
  query_results: QueryMetricResultView[];
  recommendation_share: number; recommendation_ci_low: number | null; recommendation_ci_high: number | null;
  product_mention_share: number; product_mention_ci_low: number | null; product_mention_ci_high: number | null;
  placement_citation_share: number; placement_citation_ci_low: number | null; placement_citation_ci_high: number | null;
  recommendation_query_min: number | null; recommendation_query_max: number | null;
  product_mention_query_min: number | null; product_mention_query_max: number | null;
  placement_citation_query_min: number | null; placement_citation_query_max: number | null;
  worst_query_id: string | null; selected_destination_ids: string[];
  qualified_destination_ids: string[]; verified_destination_ids: string[];
  qualified_destination_coverage: number; verified_placement_coverage: number;
  competitive_delta: number;
  status: "complete" | "confounded" | "insufficient_evidence";
  confounded_reasons: string[]; method_version: string; input_hash: string;
  result_hash: string | null; computed_at: string;
}
export interface QuerySuggestionCreate {
  campaign_id: string; query_text: string; query_kind: QueryKind; rationale: string;
  query_cluster_key: string;
}
export interface QuerySuggestionView {
  id: string; project_id: string; protocol_id: string; status: "suggested" | "approved" | "rejected";
  query_text: string; query_kind: string; rationale: string; query_cluster_key: string | null;
  monitoring_query_id: string | null; created_at: string;
}
export interface ProtocolQueryView { id: string; project_id: string; protocol_id: string; monitoring_query_id: string; query_text: string; query_kind: string; locale: string; ordinal: number; query_cluster_key: string | null; question_set_item_id?: string | null; question_candidate_id?: string | null; }
export interface VerifiedCitationTargetView {
  submission_id: string; destination_id: string; destination_key: string;
  publication_channel: string; url: string; verified_at: string;
}
export interface MonitoringReportCreate { campaign_id: string; metric_snapshot_id: string; title: string; }
export interface MonitoringReportView {
  id: string; project_id: string; protocol_id: string; campaign_id: string; metric_snapshot_id: string;
  title: string; body: string; methodology_statement: string; report_hash: string;
  status: "draft" | "approved"; generated_at: string; approved_at: string | null;
}
