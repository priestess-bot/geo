export type EngineeringAxis = "planned" | "implemented" | "verified" | "deployed";

export type EngineeringWorkItem = {
  id: string;
  title: string;
  axes: Record<EngineeringAxis, boolean>;
  blockers: string[];
  evidence_urls: string[];
  observed_at: string;
  freshness: "fresh" | "stale" | "unknown";
};
