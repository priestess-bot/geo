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
export type MeasurementStatus = "complete" | "confounded";

export type CustomerGeoMetric = Readonly<{
  id: string;
  project_id: string;
  protocol_id: string;
  campaign_id: string;
  measurement_window: MeasurementWindow;
  expected_sample_count: number;
  eligible_sample_count: number;
  recommendation_share: number;
  product_mention_share: number;
  placement_citation_share: number;
  qualified_destination_coverage: number;
  verified_placement_coverage: number;
  competitive_delta: number;
  status: MeasurementStatus;
  confounded_reasons: string[];
  method_version: string;
  computed_at: string;
}>;

export type CustomerGeoSummary = Readonly<{
  project_id: string;
  campaign_id: string | null;
  frozen_protocol_count: number;
  measurement_window_count: number;
  verified_url_count: number;
  approved_report_count: number;
  latest_metrics: CustomerGeoMetric[];
  interpretation: string;
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
  | "reports";

export type CustomerApiPath =
  | "/v1/auth/me"
  | "/v1/projects"
  | `/v1/projects/${string}/geo/${CustomerGeoResource}`;
