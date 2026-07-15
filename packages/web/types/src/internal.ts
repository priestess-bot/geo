export type EngineeringAxis = "planned" | "implemented" | "verified" | "deployed";

export type EngineeringAxisStatus = "satisfied" | "pending" | "blocked" | "unavailable";

export type EngineeringEvidence = {
  label: string;
  url?: string;
};

export type EngineeringAxisState = {
  status: EngineeringAxisStatus;
  evidence: EngineeringEvidence[];
  observed_at?: string;
};

export type EngineeringWorkItem = {
  id: string;
  title: string;
  summary?: string;
  axes: Record<EngineeringAxis, EngineeringAxisState>;
  blockers: string[];
  observed_at: string;
  freshness: "fresh" | "stale" | "unknown";
};

export type EngineeringWorkItemsResponse = {
  items: EngineeringWorkItem[];
  observed_at?: string;
};
