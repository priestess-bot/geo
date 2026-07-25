export type ProtocolStatus = "draft" | "in_review" | "approved" | "retired";

export type MetricProtocol = Readonly<{
  id: string;
  project_id: string;
  series_id: string;
  version: number;
  supersedes_protocol_id: string | null;
  status: ProtocolStatus;
  protocol_hash: string;
  definition: Record<string, unknown>;
  created_by: string;
  submitted_by: string | null;
  approved_by: string | null;
  retired_by: string | null;
  decision_reason: string | null;
  aggregate_version: number;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  approved_at: string | null;
  retired_at: string | null;
}>;

export type MetricProtocolPage = Readonly<{ items: MetricProtocol[]; total: number }>;

export type StatisticalProtocol = Readonly<{
  id: string;
  project_id: string;
  series_id: string;
  version: number;
  supersedes_protocol_id: string | null;
  kind: "comparison_plan" | "drift_protocol";
  status: ProtocolStatus;
  definition_hash: string;
  definition: Record<string, unknown>;
  created_by: string;
  submitted_by: string | null;
  approved_by: string | null;
  retired_by: string | null;
  decision_reason: string | null;
  aggregate_version: number;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  approved_at: string | null;
  retired_at: string | null;
}>;

export type StatisticalProtocolPage = Readonly<{
  items: StatisticalProtocol[];
  total: number;
}>;

export const workflowCReportMetricKeys = [
  "brand_mention",
  "product_mention",
  "recommendation",
  "recommendation_strength",
  "competitor_mention",
  "competitor_relative_position",
  "sentiment",
  "fact_accuracy",
  "explicit_conflict",
  "subject_mixup",
  "key_fact_omission",
  "citation_entailment",
  "citation_position",
  "citation_order",
  "verified_url_hit",
  "source_domain_diversity",
  "source_type_diversity",
  "approved_corpus_absorption",
  "mention",
  "recommendation_rate"
] as const;

export type WorkflowCReportMetricKey = (typeof workflowCReportMetricKeys)[number];
export type WorkflowCReportMetricValue = number | string;

export type WorkflowCApprovedSafePayload = Readonly<{
  headline: string;
  summary?: string;
  methodology?: string;
  warnings?: string[];
  metrics?: Partial<Record<WorkflowCReportMetricKey, WorkflowCReportMetricValue>>;
  mention_rate?: WorkflowCReportMetricValue;
  recommendation_rate?: WorkflowCReportMetricValue;
}>;

export type WorkflowCReport = Readonly<{
  report_id: string;
  project_id: string;
  version: number;
  status: "draft" | "in_review" | "approved" | "stale" | "superseded" | "revoked";
  campaign_id: string;
  monitoring_report_id: string;
  monitoring_report_hash: string;
  semantic_snapshot_hash: string;
  source_kind: "provider_api" | "proxy_grounded_api";
  approved_safe_payload: WorkflowCApprovedSafePayload;
  approved_safe_payload_hash: string;
  version_hash: string;
  actor_id: string;
  reason: string | null;
  occurred_at: string;
}>;

export type WorkflowCReportPage = Readonly<{ items: WorkflowCReport[]; total: number }>;

export type SemanticMetricsJobReceipt = Readonly<{
  job_id: string;
  status: "queued";
  status_url: string;
  manifest_id: string;
  manifest_hash: string;
  replayed: boolean;
}>;

export type StatisticalAnalysisJobReceipt = Readonly<{
  job_id: string;
  status: "queued";
  status_url: string;
  spec_hash: string;
  replayed: boolean;
}>;
