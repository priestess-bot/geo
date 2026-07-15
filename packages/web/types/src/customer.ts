export type CustomerProjectSummary = {
  project_id: string;
  display_name: string;
  market_code: string;
  status: string;
};

export type CustomerPlacementSummary = {
  opportunity_id: string;
  publication_channel: string;
  destination_key: string;
  workflow_status: string;
  verified_url?: string;
};

export type CustomerApiPath =
  | "/v1/auth/me"
  | "/v1/projects"
  | "/v1/geo/customer-summary"
  | "/v1/project-launch-configs/runtime"
  | "/v1/score-weight-configs/runtime"
  | "/v1/projects/runtime"
  | "/v1/projects/runtime/lifecycle-events"
  | "/v1/audit-events/runtime"
  | "/v1/visibility-scores/runtime"
  | "/v1/evidence-runs/runtime"
  | "/v1/collection-runs/runtime"
  | "/v1/citation-graphs/runtime"
  | "/v1/reports/runtime"
  | "/v1/report-export-jobs/runtime"
  | "/v1/action-plans/runtime"
  | "/v1/traceability/runtime";
