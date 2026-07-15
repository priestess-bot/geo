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
export interface MonitoringQueryView extends MonitoringQueryCreate { id: string; project_id: string; status: string; }

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
  id: string; project_id: string; brief_id: string; version_number: number; base_version_id: string | null;
  goals: JsonObject; constraints: JsonObject; content_hash: string;
}
export interface EvidenceAttemptView {
  id: string; project_id: string; brief_version_id: string; attempt_number: number;
  status: string; pack_hash: string | null; failure_reason: string | null;
}
export interface EvidenceItemView {
  id: string; item_type: string; subject_entity_id: string | null; subject_role: string;
  snapshot_hash: string; usage_rights: string; confidentiality: string;
  public_disclosure_allowed: boolean; public_source_url: string | null; public_source_title: string | null;
  citation_label: string | null; quotation_allowed: boolean; attribution_required: boolean;
}
export interface AsyncResourceCreated { resource: EvidenceAttemptView; job_id: string; status: JobState; status_url: string; }

export interface PromptSkillCreate { skill_key: string; }
export interface PromptSkillView { id: string; project_id: string; skill_key: string; status: string; }
export interface PromptReleaseCreate { source: string; output_schema: JsonObject; client_variable_names?: string[]; }
export interface PromptReleaseView { id: string; project_id: string; skill_version_id: string; release_number: number; release_hash: string; }
export interface PromptTaskBindingCreate { template_release_id: string; }
export interface PromptTaskBindingView { project_id: string; selected_at: string; selected_by: string; task_key: string; template_release_id: string; }
export interface PromptBundleCreate {
  evidence_pack_attempt_id: string; model_policy_hash: string; template_release_id: string; variables: JsonObject;
}
export interface PromptBundleView {
  artifact_status: string; brief_version_id: string; bundle_hash: string; evidence_pack_attempt_id: string;
  id: string; project_id: string; storage_key: string; storage_uri: string | null; template_release_id: string;
}
export interface PromptBundleDetail extends PromptBundleView { manifest: JsonObject; }
export interface GenerationCreate { configured_model?: string; model_call_budget?: number; }
export interface JobAccepted { job_id: string; status: JobState; status_url: string; }
export interface JobStatus {
  id: string; kind: string; status: JobState; created_at: string; updated_at: string;
  error_code?: string | null; result_details?: JsonObject | null; result_ref?: string | null;
}
export interface PlacementJobView { id: string; kind: string; project_id: string; status: JobState; }
export interface PlacementJobEventView {
  id: string; job_id: string; project_id: string; event_type: string; details: JsonObject;
  fencing_generation: number | null; worker_id: string; created_at: string;
}

export interface PackageVersionView {
  id: string; project_id: string; package_id: string; prompt_bundle_id: string; version_number: number;
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
  id: string; project_id: string; package_version_id: string; destination_id: string; destination_key: string;
  publication_channel: string; publication_attempt: number; policy_basis: string | null;
  restricted_policy_acknowledged: boolean; idempotency_key: string; status: string;
}
export interface SubmissionCreate { provider_submission_id?: string | null; submitted_url?: string | null; }
export interface SubmissionView {
  id: string; project_id: string; publication_request_id: string; status: string;
  provider_submission_id?: string | null; submitted_url?: string | null;
  url_backfilled_at?: string | null; url_backfilled_by?: string | null; verification_result?: JsonObject | null;
}
export interface StateReasonCreate { reason: string; }
export interface SubmissionUrlCreate { submitted_url: string; }
export interface MeasurementCreate {
  monitoring_query_id: string; measured_at: string; citation_present: boolean; result_snapshot_uri: string;
  metrics?: JsonObject; recommendation_position?: number | null;
}
export interface MeasurementView extends MeasurementCreate { id: string; project_id: string; submission_id: string; }

export interface MonitoringProtocolCreate {
  campaign_id: string; market_profile_id: string; name: string;
  platform: "chatgpt_search" | "google_ai_overviews" | "google_search" | "perplexity" | "gemini" | "other";
  locale: string; device: "desktop" | "mobile" | "tablet"; sample_size: number; window_days: number;
}
export interface MonitoringProtocolView extends MonitoringProtocolCreate {
  id: string; project_id: string; status: "draft" | "approved" | "frozen"; protocol_hash: string | null;
  created_at: string; approved_at: string | null; frozen_at: string | null;
}
export interface ObservationCitationCreate {
  url: string; verification_status: "passed" | "failed" | "unknown"; title?: string | null;
  destination_id?: string | null; submission_id?: string | null; verified_at?: string | null;
}
export interface ObservationCitationView {
  id: string; url: string; verification_status: "passed" | "failed" | "unknown"; verified_placement: boolean;
  title: string | null; destination_id: string | null; submission_id: string | null;
}
export interface MonitoringObservationCreate {
  monitoring_query_id: string; measurement_window: MeasurementWindow; sample_index: number;
  result_status: "succeeded" | "failed"; eligible: boolean; url_verification_status: "passed" | "failed" | "unknown";
  configured_model: string; ui_surface: string; observed_at: string; raw_answer?: string | null;
  citations?: ObservationCitationCreate[]; competitor_mentioned?: boolean; primary_product_mentioned?: boolean;
  recommendation_present?: boolean; provider_reported_model?: string | null; artifact_uri?: string | null;
  artifact_hash?: string | null; confounding_factors?: string[]; ineligible_reasons?: string[];
  raw_result?: JsonObject; ui_metadata?: JsonObject;
}
export interface MonitoringObservationView extends MonitoringObservationCreate {
  id: string; project_id: string; protocol_id: string; campaign_id: string; citations: ObservationCitationView[];
  payload_hash: string; replayed: boolean; created_at: string; raw_result: JsonObject; ui_metadata: JsonObject;
  confounding_factors: string[]; ineligible_reasons: string[]; competitor_mentioned: boolean;
  primary_product_mentioned: boolean; recommendation_present: boolean; artifact_uri: string | null;
  artifact_hash: string | null; provider_reported_model: string | null; raw_answer: string | null;
}
export interface MetricView {
  id: string; project_id: string; protocol_id: string; campaign_id: string; measurement_window: MeasurementWindow;
  expected_sample_count: number; eligible_sample_count: number; recommendation_share: number; product_mention_share: number;
  placement_citation_share: number; qualified_destination_coverage: number; verified_placement_coverage: number;
  competitive_delta: number; status: "complete" | "confounded"; confounded_reasons: string[];
  method_version: string; computed_at: string;
}
export interface QuerySuggestionCreate { query_text: string; query_kind: QueryKind; rationale: string; }
export interface QuerySuggestionView extends QuerySuggestionCreate {
  id: string; project_id: string; protocol_id: string; status: "suggested" | "approved" | "rejected";
  monitoring_query_id: string | null; created_at: string;
}
export interface ProtocolQueryView { id: string; project_id: string; protocol_id: string; monitoring_query_id: string; query_text: string; query_kind: string; locale: string; ordinal: number; }
export interface MonitoringReportCreate { metric_snapshot_id: string; title: string; }
export interface MonitoringReportView {
  id: string; project_id: string; protocol_id: string; campaign_id: string; metric_snapshot_id: string;
  title: string; body: string; methodology_statement: string; report_hash: string;
  status: "draft" | "approved"; generated_at: string; approved_at: string | null;
}
