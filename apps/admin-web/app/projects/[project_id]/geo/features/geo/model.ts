import type {
  BriefVersionView, CampaignPlacementReadinessView, CampaignView, ClaimView, DestinationPolicyView,
  DestinationView, EvidenceAttemptView,
  EvidenceItemView, ExportView, JobStatus, MeasurementView, MeasurementWindow, MetricView,
  KnowledgeQuestionCandidateView, KnowledgeQuestionFactView, KnowledgeQuestionGenerationView,
  KnowledgeQuestionSetView,
  MonitoringObservationView, MonitoringProtocolView, MonitoringQueryView, MonitoringReportView,
  OpportunityPromptReleaseBindingView, OpportunityView, PackageVersionView, PlacementJobEventView,
  PromptBundleDetail, PromptBundleView,
  PromptReleaseView, PromptSimulationView, PromptSkillView, PromptTaskBindingView, ProtocolQueryView, PublicationView,
  QuerySuggestionView, ReviewView, SubmissionView, VerifiedCitationTargetView
} from "@geo/types/geo";

export type GeoSection = "campaigns" | "observations" | "destinations" | "placement";
export type LoadFailure = { status?: number; code: string; detail: string; correlationId?: string; retryable: boolean; };
export type Resource<T> = { data: T; failure: null } | { data: T; failure: LoadFailure };
export type GeoSelection = {
  section: GeoSection; placementStage: "brief" | "evidence" | "generation" | "review" | "publication" | "simulation"; measurementWindow: MeasurementWindow; campaignId?: string; protocolId?: string;
  destinationId?: string; opportunityId?: string; briefVersionId?: string; attemptId?: string;
  skillId?: string; bundleId?: string; jobId?: string; versionId?: string;
  publicationId?: string; submissionId?: string;
  simulationId?: string;
  questionGenerationJobId?: string;
};
export type GeoWorkspaceData = {
  selection: GeoSelection;
  canonicalHref?: string;
  campaigns: Resource<CampaignView[]>; destinations: Resource<DestinationView[]>;
  protocols: Resource<MonitoringProtocolView[]>; metrics: Resource<MetricView[]>;
  reports: Resource<MonitoringReportView[]>; skills: Resource<PromptSkillView[]>;
  simulations: Resource<PromptSimulationView[]>;
  questionFacts: Resource<KnowledgeQuestionFactView[]>;
  questionGenerations: Resource<KnowledgeQuestionGenerationView[]>;
  questionCandidates: Resource<KnowledgeQuestionCandidateView[]>;
  questionSets: Resource<KnowledgeQuestionSetView[]>;
  bindings: Resource<PromptTaskBindingView[]>; queries: Resource<MonitoringQueryView[]>;
  protocolQueries: Resource<ProtocolQueryView[]>;
  citationTargets: Resource<VerifiedCitationTargetView[]>;
  opportunities: Resource<OpportunityView[]>; policyReviews: Resource<DestinationPolicyView[]>;
  placementReadiness: Resource<CampaignPlacementReadinessView | null>;
  promptBinding: Resource<OpportunityPromptReleaseBindingView | null>;
  promptBindingHistory: Resource<OpportunityPromptReleaseBindingView[]>;
  observations: Resource<MonitoringObservationView[]>; suggestions: Resource<QuerySuggestionView[]>;
  briefs: Resource<BriefVersionView[]>; attempts: Resource<EvidenceAttemptView[]>;
  attempt: Resource<EvidenceAttemptView | null>; evidenceItems: Resource<EvidenceItemView[]>;
  releases: Resource<PromptReleaseView[]>; bundles: Resource<PromptBundleView[]>;
  bundle: Resource<PromptBundleDetail | null>; job: Resource<JobStatus | null>;
  jobEvents: Resource<PlacementJobEventView[]>; packages: Resource<PackageVersionView[]>;
  packageVersion: Resource<PackageVersionView | null>; claims: Resource<ClaimView[]>;
  reviews: Resource<ReviewView[]>; exports: Resource<ExportView[]>;
  publications: Resource<PublicationView[]>; submissions: Resource<SubmissionView[]>;
  submission: Resource<SubmissionView | null>; measurements: Resource<MeasurementView[]>;
  simulation: Resource<PromptSimulationView | null>;
};

export const emptyResource = <T,>(data: T): Resource<T> => ({ data, failure: null });
