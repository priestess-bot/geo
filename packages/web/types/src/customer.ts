import type {
  ObservationCaptureMethod,
  ObservationSourceStratumCreate
} from "./geo";

export type CustomerProjectSummary = Readonly<{
  project_id: string;
  display_name: string;
  market_code: string;
  role: string;
  status: string;
}>;

export type CustomerProjectPage = Readonly<{
  items: CustomerProjectSummary[];
  total: number;
  limit: number;
  offset: number;
}>;

export type MeasurementWindow = "baseline" | "t28" | "t56" | "t84" | "ad_hoc";
export type MeasurementStatus = "complete" | "confounded" | "insufficient_evidence";

export type CustomerGeoMetric = Readonly<{
  id: string;
  project_id: string;
  protocol_id: string;
  campaign_id: string;
  measurement_window: MeasurementWindow;
  capture_method: ObservationCaptureMethod;
  source_stratum: ObservationSourceStratumCreate | null;
  source_stratum_hash: string | null;
  statistics_contract_version: string;
  query_cluster_key: string | null;
  analysis_stratum_hash: string | null;
  minimum_valid_repeats: number | null;
  expected_sample_count: number;
  sampled_sample_count: number | null;
  eligible_sample_count: number;
  invalid_sample_count: number | null;
  missing_sample_count: number | null;
  sampling_completion_ratio: number | null;
  valid_completion_ratio: number | null;
  query_count: number | null;
  sufficient_query_count: number | null;
  invalid_reason_counts: Record<string, number>;
  declared_confounding_factors: string[];
  query_results: CustomerQueryMetricResult[];
  recommendation_share: number;
  recommendation_ci_low: number | null;
  recommendation_ci_high: number | null;
  product_mention_share: number;
  product_mention_ci_low: number | null;
  product_mention_ci_high: number | null;
  placement_citation_share: number;
  placement_citation_ci_low: number | null;
  placement_citation_ci_high: number | null;
  recommendation_query_min: number | null;
  recommendation_query_max: number | null;
  product_mention_query_min: number | null;
  product_mention_query_max: number | null;
  placement_citation_query_min: number | null;
  placement_citation_query_max: number | null;
  worst_query_id: string | null;
  selected_destination_ids: string[];
  qualified_destination_ids: string[];
  verified_destination_ids: string[];
  qualified_destination_coverage: number;
  verified_placement_coverage: number;
  competitive_delta: number;
  status: MeasurementStatus;
  confounded_reasons: string[];
  method_version: string;
  input_hash: string;
  result_hash: string | null;
  observation_membership_version: string | null;
  observation_membership_hash: string | null;
  observation_membership_count: number | null;
  computed_at: string;
}>;

export type CustomerBinaryEstimate = Readonly<{
  numerator: number;
  denominator: number;
  share: number;
  ci_low: number;
  ci_high: number;
}>;

export type CustomerQueryMetricResult = Readonly<{
  monitoring_query_id: string;
  query_text_snapshot: string;
  query_cluster_key: string;
  expected_sample_count: number;
  sampled_sample_count: number;
  valid_sample_count: number;
  invalid_sample_count: number;
  missing_sample_count: number;
  meets_threshold: boolean;
  invalid_reason_counts: Record<string, number>;
  confounding_factors: string[];
  recommendation: CustomerBinaryEstimate;
  product_mention: CustomerBinaryEstimate;
  placement_citation: CustomerBinaryEstimate;
  competitor: CustomerBinaryEstimate;
  competitive_delta: number;
}>;

export type CustomerGeoSummary = Readonly<{
  project_id: string;
  campaign_id: string;
  campaign_name: string;
  campaign_objective: string;
  campaign_status: string;
  frozen_protocol_count: number;
  measurement_window_count: number;
  verified_url_count: number;
  approved_report_count: number;
  latest_metrics: CustomerGeoMetric[];
  interpretation: string;
}>;

export type CustomerCampaign = Readonly<{
  id: string;
  project_id: string;
  name: string;
  objective: string;
  status: string;
  approved_report_count: number;
  latest_approved_at: string | null;
}>;

export type CustomerMeasurementWindow = Readonly<{
  protocol_id: string;
  campaign_id: string;
  measurement_window: MeasurementWindow;
  expected_sample_count: number;
  eligible_sample_count: number;
  status: MeasurementStatus;
  confounded_reasons: string[];
  computed_at: string;
}>;

export type CustomerVerifiedUrl = Readonly<{
  campaign_id: string;
  protocol_ids: string[];
  url: string;
  title: string | null;
  destination_id: string | null;
  first_verified_at: string;
  observation_count: number;
}>;

export type CustomerApprovedReport = Readonly<{
  id: string;
  project_id: string;
  protocol_id: string;
  campaign_id: string;
  metric_snapshot_id: string;
  title: string;
  body: string;
  methodology_statement: string;
  report_hash: string;
  status: "approved";
  generated_at: string;
  approved_at: string;
}>;

export type CustomerApprovedMeasurement = Readonly<{
  report: CustomerApprovedReport;
  snapshot: CustomerGeoMetric;
  snapshot_contract: "statistics_v2" | "legacy_unknown";
}>;

export type CustomerWorkflowCReportSourceKind =
  | "provider_api"
  | "proxy_grounded_api"
  | "automated_ui";

export type CustomerWorkflowCMetricKey =
  | "mention"
  | "mention_rate"
  | "recommendation_rate"
  | "brand_mention"
  | "product_mention"
  | "recommendation"
  | "recommendation_strength"
  | "competitor_mention"
  | "competitor_relative_position"
  | "sentiment"
  | "fact_accuracy"
  | "explicit_conflict"
  | "subject_mixup"
  | "key_fact_omission"
  | "citation_entailment"
  | "citation_position"
  | "citation_order"
  | "verified_url_hit"
  | "source_domain_diversity"
  | "source_type_diversity"
  | "approved_corpus_absorption";

export type CustomerWorkflowCMetricValue = number | string;

export type CustomerWorkflowCReportPayload = Readonly<{
  headline: string;
  summary?: string;
  methodology?: string;
  metrics?: Partial<Record<CustomerWorkflowCMetricKey, CustomerWorkflowCMetricValue>>;
  warnings?: string[];
  mention_rate?: CustomerWorkflowCMetricValue;
  recommendation_rate?: CustomerWorkflowCMetricValue;
}>;

export type CustomerWorkflowCReport = Readonly<{
  id: string;
  project_id: string;
  campaign_id: string;
  semantic_snapshot_hash: string;
  report_hash: string;
  source_kind: CustomerWorkflowCReportSourceKind;
  approved_safe_payload: CustomerWorkflowCReportPayload;
  approved_at: string;
}>;

export type CustomerWorkflowCReportPage = Readonly<{
  items: CustomerWorkflowCReport[];
  total: number;
}>;

export type CustomerCampaignReadModel = Readonly<{
  campaign: CustomerCampaign;
  summary: CustomerGeoSummary;
  approved_measurements: CustomerApprovedMeasurement[];
  verified_urls: CustomerVerifiedUrl[];
}>;

export type CustomerProblemDetails = Readonly<{
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string;
  request_id: string;
  errors?: unknown[] | null;
}>;

export type CustomerGeoResource =
  | "summary"
  | "metrics"
  | "measurement-windows"
  | "verified-urls"
  | "reports"
  | "workflow-c-reports";

export type CustomerApiPath =
  | "/v1/auth/me"
  | "/v1/projects"
  | `/v1/projects/${string}/geo/${CustomerGeoResource}`
  | `/v1/projects/${string}/geo/campaigns`
  | `/v1/projects/${string}/geo/campaigns/${string}/read-model`;
