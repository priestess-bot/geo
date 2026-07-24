export const recommendationTypes = [
  "hard_blocker",
  "gap",
  "experiment",
  "optional",
  "no_change",
  "insufficient_evidence"
] as const;

export const recommendationStatuses = [
  "draft",
  "in_review",
  "approved",
  "rejected",
  "stale",
  "expired"
] as const;

export const inputChangeReasons = [
  "fact_retired",
  "data_refreshed",
  "alert_resolved",
  "method_replaced",
  "content_version_changed",
  "prompt_release_changed",
  "input_added_or_removed"
] as const;

export type RecommendationType = (typeof recommendationTypes)[number];
export type RecommendationStatus = (typeof recommendationStatuses)[number];
export type InputChangeReason = (typeof inputChangeReasons)[number];
export type DraftKind = "experiment_plan" | "question_set" | "content_brief" | "sampling_plan";
export type DraftStatus = "draft" | "started" | "blocked_source_stale" | "blocked_source_expired";
export type InputKind =
  | "observation"
  | "comparison"
  | "fact"
  | "rule_version"
  | "prompt_release"
  | "model_call"
  | "method_version"
  | "content_version"
  | "question_version"
  | "surface_release";

export type InputVersion = Readonly<{
  kind: InputKind;
  resource_id: string;
  version: string;
  sha256: string;
}>;

export type EvidenceScope = Readonly<{
  project_id: string;
  applicable_version: string;
  campaign_id: string | null;
  question_or_cluster_ref: string | null;
  surface_ref: string | null;
  content_asset_ref: string | null;
  url_ref: string | null;
}>;

export type RecommendationDecision = Readonly<{
  impact_chain: string[];
  risk: string;
  effort: string;
  business_value: string;
  confidence: string;
  counterevidence: string[];
  validation_plan: string[];
  stale_conditions: string[];
}>;

export type VersionedEvidenceRef = Readonly<{
  project_id: string;
  resource_id: string;
  version: string;
  sha256: string;
  locator: Record<string, string>;
  valid: boolean;
}>;

export type ObservationRef = VersionedEvidenceRef & Readonly<{
  capture_method: string;
  evidence_class: "real_observation" | "official_projection" | "synthetic";
  question_resource_id: string;
  surface_resource_id: string;
  eligible: boolean;
}>;

export type MetricComparisonRef = VersionedEvidenceRef & Readonly<{
  observation_resource_ids: string[];
  method_version: string;
  method_sha256: string;
  sufficient_evidence: boolean;
}>;

export type FactRef = VersionedEvidenceRef & Readonly<{ approved: boolean; retired: boolean }>;
export type RuleRef = VersionedEvidenceRef & Readonly<{ active: boolean }>;
export type PromptReleaseRef = VersionedEvidenceRef & Readonly<{ approved: boolean; frozen: boolean }>;
export type ModelCallRef = VersionedEvidenceRef & Readonly<{
  prompt_release_resource_id: string;
  model_identity: string;
  succeeded: boolean;
}>;
export type ContentRef = VersionedEvidenceRef & Readonly<{ current: boolean }>;
export type QuestionRef = VersionedEvidenceRef & Readonly<{ active: boolean }>;
export type SurfaceRef = VersionedEvidenceRef & Readonly<{ active: boolean }>;

export type EvidenceGraph = Readonly<{
  scope: EvidenceScope;
  decision: RecommendationDecision;
  observations: ObservationRef[];
  metric_comparisons: MetricComparisonRef[];
  facts: FactRef[];
  rules: RuleRef[];
  prompt_releases: PromptReleaseRef[];
  model_calls: ModelCallRef[];
  contents: ContentRef[];
  questions: QuestionRef[];
  surfaces: SurfaceRef[];
}>;

export type RecommendationApproval = Readonly<{
  id: string;
  approved_by: string;
  approved_at: string;
  recommendation_version: number;
  frozen_input_fingerprint: string;
  frozen_evidence_graph_hash: string;
  valid_until: string;
}>;

export type Recommendation = Readonly<{
  id: string;
  project_id: string;
  recommendation_type: RecommendationType;
  status: RecommendationStatus;
  version: number;
  proposed_draft_kind: DraftKind | null;
  valid_until: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  evidence: EvidenceGraph;
  evidence_graph_hash: string;
  input_fingerprint: string;
  input_versions: InputVersion[];
  approval: RecommendationApproval | null;
}>;

export type LinkedDraft = Readonly<{
  id: string;
  recommendation_id: string;
  recommendation_version: number;
  approval_id: string;
  kind: DraftKind;
  status: DraftStatus;
  frozen_input_fingerprint: string;
  frozen_evidence_graph_hash: string;
  created_at: string;
  started_at: string | null;
  blocked_at: string | null;
  blocked_reason: string | null;
  draft_only: true;
  enqueued: false;
  executed: false;
  published: false;
}>;

export type RecommendationWorkflow = Readonly<{
  recommendation: Recommendation;
  drafts: LinkedDraft[];
}>;

export type RecommendationPage = Readonly<{
  items: RecommendationWorkflow[];
  total: number;
  limit: number;
  offset: number;
}>;

export type RecommendationCommandResponse = RecommendationWorkflow & Readonly<{
  replayed: boolean;
}>;

export type ReviewedRecommendationResponse = RecommendationCommandResponse & Readonly<{
  review: Readonly<{
    id: string;
    recommendation_id: string;
    recommendation_version: number;
    evidence_graph_hash: string;
    reviewed_by: string;
    notes: string;
    reviewed_at: string;
  }>;
}>;

export type ApprovedRecommendationResponse = RecommendationCommandResponse & Readonly<{
  downstream_draft: LinkedDraft | null;
  action_boundary: "draft_only_unstarted";
}>;

export type InvalidatedRecommendationResponse = RecommendationCommandResponse & Readonly<{
  cancelled_outbox_ids: string[];
}>;

export type PreparedDraftActionResponse = RecommendationCommandResponse & Readonly<{
  draft: LinkedDraft;
  authorized: true;
  action_boundary: "source_checked_draft_only";
}>;

export type RecommendationFilters = Readonly<{
  status: RecommendationStatus | "all";
  type: RecommendationType | "all";
}>;

export type RecommendationLoadProblem = Readonly<{
  status?: number;
  detail: string;
  correlationId?: string;
}>;

export type RecommendationWorkspaceData = Readonly<{
  page: RecommendationPage;
  sourceTotal: number;
  filters: RecommendationFilters;
  listProblem?: RecommendationLoadProblem;
  selectedProblem?: RecommendationLoadProblem;
  selected: RecommendationWorkflow | null;
  generationCatalog: RecommendationGenerationCatalog;
}>;

export type RecommendationActionState = Readonly<{
  kind: "idle" | "success" | "error";
  message?: string;
  status?: number;
  correlationId?: string;
  recommendation?: Readonly<{
    id: string;
    status: RecommendationStatus;
    version: number;
    evidenceGraphHash: string;
  }>;
  draft?: Readonly<{
    id: string;
    kind: DraftKind;
    status: DraftStatus;
    authorized?: boolean;
  }>;
  actionBoundary?: "draft_only_unstarted" | "source_checked_draft_only";
  cancelledOutboxCount?: number;
}>;

export const initialRecommendationActionState: RecommendationActionState = { kind: "idle" };
import type { RecommendationGenerationCatalog } from "./recommendationGenerationTypes";
