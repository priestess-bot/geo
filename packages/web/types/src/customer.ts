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
