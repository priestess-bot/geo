import type {
  AsyncResourceCreated, BriefVersionCreate, BriefVersionView, CampaignCreate, CampaignCreated,
  CampaignPlacementReadinessView, CampaignView,
  ClaimView, DestinationCreate, DestinationPolicyReviewCreate, DestinationPolicyView, DestinationView,
  EvidenceAttemptView, EvidenceItemView, ExportView, GenerationCreate, JobAccepted, JobStatus,
  KnowledgeQuestionCandidateEdit, KnowledgeQuestionCandidateReview,
  KnowledgeQuestionCandidateView, KnowledgeQuestionCoverageProfileView,
  KnowledgeQuestionFactView, KnowledgeQuestionGenerationCreate, KnowledgeQuestionGenerationCreated,
  KnowledgeQuestionGenerationView,
  KnowledgeQuestionCoverageFinalize, KnowledgeQuestionSetCreate, KnowledgeQuestionSetView,
  MeasurementCollectionTaskView, MeasurementCreate, MeasurementView, MeasurementWindow, MetricCompute, MetricView, MonitoringObservationCreate,
  MonitoringObservationView, MonitoringProtocolCreate, MonitoringProtocolQuestionSetBindingCreate,
  MonitoringProtocolView, MonitoringQueryCreate,
  MonitoringQueryView, MonitoringReportCreate, MonitoringReportView,
  OfficialReportImportCreate, OfficialReportImportView,
  OpportunityPromptReleaseBindingCreate, OpportunityPromptReleaseBindingView,
  OpportunityStateCommand, OpportunityView,
  PackageEdit, PackageVersionView, PlacementJobEventView, PlacementJobView, PromptBundleCreate,
  PromptBundleDetail, PromptBundleView, PromptReleaseCreate, PromptReleaseTransition, PromptReleaseView, PromptSkillCreate,
  PromptSimulationCreate, PromptSimulationCreated, PromptSimulationView, PromptSkillView,
  PromptTaskBindingCreate, PromptTaskBindingView, PublicationCreate, PublicationView,
  PublicationVerificationAttemptView,
  ProtocolQueryView, QuerySuggestionCreate, QuerySuggestionView, ReviewCreate, ReviewSubmissionView, ReviewView,
  StateReasonCreate, SubmissionCreate, SubmissionUrlCreate, SubmissionView, VerifiedCitationTargetView
} from "@geo/types/geo";
import {
  geoApiUrl, mergeClientRequestInit, performRuntimeHttpRequest, runtimeGuardHeaders,
  type GeoApiClientOptions, type RuntimeHttpResult, type RuntimeRequestGuards
} from "./transport";

type HttpOptions<TBody> = RuntimeRequestGuards & { method?: "GET" | "POST" | "PUT" | "PATCH"; body?: TBody; query?: { [key: string]: string | number | boolean | undefined | null }; };

export class GeoAdminApiClient {
  constructor(private readonly baseUrl: string, private readonly options: GeoApiClientOptions = {}) {}

  private request<TResponse, TBody = never>(path: string, options: HttpOptions<TBody> = {}): Promise<RuntimeHttpResult<TResponse>> {
    const hasBody = options.body !== undefined;
    const init = mergeClientRequestInit(this.options, {
      method: options.method || "GET",
      headers: { ...(hasBody ? { "Content-Type": "application/json" } : {}), ...runtimeGuardHeaders(options) },
      body: hasBody ? JSON.stringify(options.body) : undefined
    });
    return performRuntimeHttpRequest(geoApiUrl(this.baseUrl, path, options.query), init, this.options.fetcher);
  }

  listCampaigns(projectId: string) { return this.request<CampaignView[]>(`/v1/projects/${projectId}/geo/campaigns`); }
  createCampaign(projectId: string, body: CampaignCreate, guards: RuntimeRequestGuards) { return this.request<CampaignCreated, CampaignCreate>(`/v1/projects/${projectId}/geo/campaigns`, { method: "POST", body, ...guards }); }
  getCampaign(projectId: string, campaignId: string) { return this.request<CampaignView>(`/v1/projects/${projectId}/geo/campaigns/${campaignId}`); }
  listMonitoringQueries(projectId: string, campaignId: string) { return this.request<MonitoringQueryView[]>(`/v1/projects/${projectId}/geo/campaigns/${campaignId}/monitoring-queries`); }
  createMonitoringQuery(projectId: string, campaignId: string, body: MonitoringQueryCreate, guards: RuntimeRequestGuards) { return this.request<MonitoringQueryView, MonitoringQueryCreate>(`/v1/projects/${projectId}/geo/campaigns/${campaignId}/monitoring-queries`, { method: "POST", body, ...guards }); }
  listOpportunities(projectId: string, campaignId: string) { return this.request<OpportunityView[]>(`/v1/projects/${projectId}/geo/campaigns/${campaignId}/opportunities`); }
  getCampaignPlacementReadiness(projectId: string, campaignId: string) { return this.request<CampaignPlacementReadinessView>(`/v1/projects/${projectId}/geo/campaigns/${campaignId}/placement-readiness`); }
  transitionOpportunity(projectId: string, campaignId: string, opportunityId: string, command: string, body: OpportunityStateCommand, guards: RuntimeRequestGuards) { return this.request<OpportunityView, OpportunityStateCommand>(`/v1/projects/${projectId}/geo/opportunities/${opportunityId}/transitions/${command}`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }
  listOpportunityPromptBindings(projectId: string, campaignId: string, opportunityId: string) { return this.request<OpportunityPromptReleaseBindingView[]>(`/v1/projects/${projectId}/geo/campaigns/${campaignId}/opportunities/${opportunityId}/prompt-release-bindings`); }
  getOpportunityPromptBinding(projectId: string, campaignId: string, opportunityId: string) { return this.request<OpportunityPromptReleaseBindingView | null>(`/v1/projects/${projectId}/geo/campaigns/${campaignId}/opportunities/${opportunityId}/prompt-release-binding`); }
  bindOpportunityPromptRelease(projectId: string, campaignId: string, opportunityId: string, body: OpportunityPromptReleaseBindingCreate, guards: RuntimeRequestGuards) { return this.request<OpportunityPromptReleaseBindingView, OpportunityPromptReleaseBindingCreate>(`/v1/projects/${projectId}/geo/campaigns/${campaignId}/opportunities/${opportunityId}/prompt-release-bindings`, { method: "POST", body, ...guards }); }

  listKnowledgeQuestionFacts(projectId: string) { return this.request<KnowledgeQuestionFactView[]>(`/v1/projects/${projectId}/knowledge/fact-candidates`); }
  listKnowledgeQuestionGenerations(projectId: string, campaignId: string) { return this.request<KnowledgeQuestionGenerationView[]>(`/v1/projects/${projectId}/knowledge/campaigns/${campaignId}/question-generations`); }
  createKnowledgeQuestionGeneration(projectId: string, campaignId: string, body: KnowledgeQuestionGenerationCreate, guards: RuntimeRequestGuards) { return this.request<KnowledgeQuestionGenerationCreated, KnowledgeQuestionGenerationCreate>(`/v1/projects/${projectId}/knowledge/campaigns/${campaignId}/question-generations`, { method: "POST", body, ...guards }); }
  resumeKnowledgeQuestionCoveragePack(projectId: string, campaignId: string, generationJobId: string, guards: RuntimeRequestGuards) { return this.request<KnowledgeQuestionGenerationView>(`/v1/projects/${projectId}/knowledge/campaigns/${campaignId}/question-generations/${generationJobId}/resume`, { method: "POST", ...guards }); }
  getDefaultKnowledgeQuestionCoverageProfile(projectId: string, campaignId: string) { return this.request<KnowledgeQuestionCoverageProfileView>(`/v1/projects/${projectId}/knowledge/campaigns/${campaignId}/question-coverage-profiles/default`); }
  listKnowledgeQuestionCandidates(projectId: string, campaignId: string, generationJobId: string) { return this.request<KnowledgeQuestionCandidateView[]>(`/v1/projects/${projectId}/knowledge/campaigns/${campaignId}/question-candidates`, { query: { generation_job_id: generationJobId } }); }
  editKnowledgeQuestionCandidate(projectId: string, campaignId: string, candidateId: string, body: KnowledgeQuestionCandidateEdit, guards: RuntimeRequestGuards) { return this.request(`/v1/projects/${projectId}/knowledge/campaigns/${campaignId}/question-candidates/${candidateId}/text`, { method: "PATCH", body, ...guards }); }
  reviewKnowledgeQuestionCandidate(projectId: string, campaignId: string, candidateId: string, body: KnowledgeQuestionCandidateReview, guards: RuntimeRequestGuards) { return this.request<KnowledgeQuestionCandidateView, KnowledgeQuestionCandidateReview>(`/v1/projects/${projectId}/knowledge/campaigns/${campaignId}/question-candidates/${candidateId}`, { method: "PATCH", body, ...guards }); }
  listKnowledgeQuestionSets(projectId: string, campaignId: string) { return this.request<KnowledgeQuestionSetView[]>(`/v1/projects/${projectId}/knowledge/campaigns/${campaignId}/question-sets`); }
  createKnowledgeQuestionSet(projectId: string, campaignId: string, body: KnowledgeQuestionSetCreate, guards: RuntimeRequestGuards) { return this.request<KnowledgeQuestionSetView, KnowledgeQuestionSetCreate>(`/v1/projects/${projectId}/knowledge/campaigns/${campaignId}/question-sets`, { method: "POST", body, ...guards }); }
  finalizeKnowledgeQuestionCoveragePack(projectId: string, campaignId: string, body: KnowledgeQuestionCoverageFinalize, guards: RuntimeRequestGuards) { return this.request<KnowledgeQuestionSetView, KnowledgeQuestionCoverageFinalize>(`/v1/projects/${projectId}/knowledge/campaigns/${campaignId}/question-sets/finalize-coverage-pack`, { method: "POST", body, ...guards }); }
  approveKnowledgeQuestionSet(projectId: string, campaignId: string, questionSetId: string, guards: RuntimeRequestGuards) { return this.request<KnowledgeQuestionSetView>(`/v1/projects/${projectId}/knowledge/campaigns/${campaignId}/question-sets/${questionSetId}/approve`, { method: "POST", ...guards }); }
  freezeKnowledgeQuestionSet(projectId: string, campaignId: string, questionSetId: string, guards: RuntimeRequestGuards) { return this.request<KnowledgeQuestionSetView>(`/v1/projects/${projectId}/knowledge/campaigns/${campaignId}/question-sets/${questionSetId}/freeze`, { method: "POST", ...guards }); }

  listDestinations(projectId: string) { return this.request<DestinationView[]>(`/v1/projects/${projectId}/geo/destinations`); }
  createDestination(projectId: string, body: DestinationCreate, guards: RuntimeRequestGuards) { return this.request<DestinationView, DestinationCreate>(`/v1/projects/${projectId}/geo/destinations`, { method: "POST", body, ...guards }); }
  listPolicyReviews(projectId: string, campaignId: string, destinationId: string) { return this.request<DestinationPolicyView[]>(`/v1/projects/${projectId}/geo/destinations/${destinationId}/policy-reviews`, { query: campaignQuery(campaignId) }); }
  createPolicyReview(projectId: string, campaignId: string, destinationId: string, body: DestinationPolicyReviewCreate, guards: RuntimeRequestGuards) { return this.request<DestinationPolicyView, DestinationPolicyReviewCreate>(`/v1/projects/${projectId}/geo/destinations/${destinationId}/policy-reviews`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }

  listBriefVersions(projectId: string, campaignId: string, opportunityId: string) { return this.request<BriefVersionView[]>(`/v1/projects/${projectId}/geo/opportunities/${opportunityId}/brief-versions`, { query: campaignQuery(campaignId) }); }
  createBriefVersion(projectId: string, campaignId: string, opportunityId: string, body: BriefVersionCreate, guards: RuntimeRequestGuards) { return this.request<BriefVersionView, BriefVersionCreate>(`/v1/projects/${projectId}/geo/opportunities/${opportunityId}/brief-versions`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }
  listEvidenceAttempts(projectId: string, campaignId: string, briefVersionId: string) { return this.request<EvidenceAttemptView[]>(`/v1/projects/${projectId}/geo/brief-versions/${briefVersionId}/evidence-pack-attempts`, { query: campaignQuery(campaignId) }); }
  buildEvidenceAttempt(projectId: string, campaignId: string, briefVersionId: string, guards: RuntimeRequestGuards) { return this.request<AsyncResourceCreated>(`/v1/projects/${projectId}/geo/brief-versions/${briefVersionId}/evidence-pack-attempts`, { method: "POST", query: campaignQuery(campaignId), ...guards }); }
  getEvidenceAttempt(projectId: string, campaignId: string, attemptId: string) { return this.request<EvidenceAttemptView>(`/v1/projects/${projectId}/geo/evidence-pack-attempts/${attemptId}`, { query: campaignQuery(campaignId) }); }
  listEvidenceItems(projectId: string, campaignId: string, attemptId: string) { return this.request<EvidenceItemView[]>(`/v1/projects/${projectId}/geo/evidence-pack-attempts/${attemptId}/items`, { query: campaignQuery(campaignId) }); }

  listPromptSkills(projectId: string) { return this.request<PromptSkillView[]>(`/v1/projects/${projectId}/geo/prompt-skills`); }
  createPromptSkill(projectId: string, body: PromptSkillCreate, guards: RuntimeRequestGuards) { return this.request<PromptSkillView, PromptSkillCreate>(`/v1/projects/${projectId}/geo/prompt-skills`, { method: "POST", body, ...guards }); }
  listPromptReleases(projectId: string, skillId: string) { return this.request<PromptReleaseView[]>(`/v1/projects/${projectId}/geo/prompt-skills/${skillId}/releases`); }
  createPromptRelease(projectId: string, skillId: string, body: PromptReleaseCreate, guards: RuntimeRequestGuards) { return this.request<PromptReleaseView, PromptReleaseCreate>(`/v1/projects/${projectId}/geo/prompt-skills/${skillId}/releases`, { method: "POST", body, ...guards }); }
  transitionPromptRelease(projectId: string, releaseId: string, command: "approve" | "revoke", body: PromptReleaseTransition, guards: RuntimeRequestGuards) { return this.request<PromptReleaseView, PromptReleaseTransition>(`/v1/projects/${projectId}/geo/prompt-releases/${releaseId}/transitions/${command}`, { method: "POST", body, ...guards }); }
  installDefaultPromptCatalog(projectId: string, guards: RuntimeRequestGuards) { return this.request<PromptTaskBindingView[]>(`/v1/projects/${projectId}/geo/prompt-catalog/defaults`, { method: "PUT", ...guards }); }
  listPromptBindings(projectId: string) { return this.request<PromptTaskBindingView[]>(`/v1/projects/${projectId}/geo/prompt-task-bindings`); }
  bindPromptTask(projectId: string, taskKey: string, body: PromptTaskBindingCreate, guards: RuntimeRequestGuards) { return this.request<PromptTaskBindingView, PromptTaskBindingCreate>(`/v1/projects/${projectId}/geo/prompt-task-bindings/${encodeURIComponent(taskKey)}`, { method: "PUT", body, ...guards }); }
  listPromptBundles(projectId: string, campaignId: string, briefVersionId: string) { return this.request<PromptBundleView[]>(`/v1/projects/${projectId}/geo/brief-versions/${briefVersionId}/prompt-bundles`, { query: campaignQuery(campaignId) }); }
  createPromptBundle(projectId: string, campaignId: string, briefVersionId: string, body: PromptBundleCreate, guards: RuntimeRequestGuards) { return this.request<PromptBundleView, PromptBundleCreate>(`/v1/projects/${projectId}/geo/brief-versions/${briefVersionId}/prompt-bundles`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }
  getPromptBundle(projectId: string, campaignId: string, bundleId: string) { return this.request<PromptBundleDetail>(`/v1/projects/${projectId}/geo/prompt-bundles/${bundleId}`, { query: campaignQuery(campaignId) }); }

  createGenerationJob(projectId: string, campaignId: string, bundleId: string, body: GenerationCreate, guards: RuntimeRequestGuards) { return this.request<JobAccepted, GenerationCreate>(`/v1/projects/${projectId}/geo/prompt-bundles/${bundleId}/generation-jobs`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }
  listPromptSimulations(projectId: string, campaignId?: string) { return this.request<PromptSimulationView[]>(`/v1/projects/${projectId}/geo/prompt-simulations`, campaignId === undefined ? {} : { query: campaignQuery(campaignId) }); }
  getPromptSimulation(projectId: string, simulationId: string): Promise<RuntimeHttpResult<PromptSimulationView>>;
  getPromptSimulation(projectId: string, campaignId: string, simulationId: string): Promise<RuntimeHttpResult<PromptSimulationView>>;
  getPromptSimulation(projectId: string, campaignOrSimulationId: string, simulationId?: string) { const requestedSimulationId = simulationId ?? campaignOrSimulationId; return this.request<PromptSimulationView>(`/v1/projects/${projectId}/geo/prompt-simulations/${requestedSimulationId}`, simulationId === undefined ? {} : { query: campaignQuery(campaignOrSimulationId) }); }
  createPromptSimulation(projectId: string, campaignId: string, body: PromptSimulationCreate, guards: RuntimeRequestGuards) { return this.request<PromptSimulationCreated, PromptSimulationCreate>(`/v1/projects/${projectId}/geo/prompt-simulations`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }
  getJob(jobId: string, campaignId: string) { return this.request<JobStatus>(`/v1/jobs/${jobId}`, { query: campaignQuery(campaignId) }); }
  getPlacementJob(projectId: string, jobId: string, campaignId?: string | null) { return this.request<PlacementJobView>(`/v1/projects/${projectId}/geo/jobs/${jobId}`, { query: jobCampaignQuery(campaignId) }); }
  listJobEvents(projectId: string, campaignId: string | null, jobId: string) { return this.request<PlacementJobEventView[]>(`/v1/projects/${projectId}/geo/jobs/${jobId}/events`, { query: jobCampaignQuery(campaignId) }); }
  cancelJob(projectId: string, campaignId: string | null, jobId: string, guards: RuntimeRequestGuards) { return this.request<PlacementJobView>(`/v1/projects/${projectId}/geo/jobs/${jobId}/cancel`, { method: "POST", query: jobCampaignQuery(campaignId), ...guards }); }
  retryJob(projectId: string, campaignId: string | null, jobId: string, guards: RuntimeRequestGuards) { return this.request<PlacementJobView>(`/v1/projects/${projectId}/geo/jobs/${jobId}/retry-now`, { method: "POST", query: jobCampaignQuery(campaignId), ...guards }); }
  replayJob(projectId: string, campaignId: string | null, jobId: string, guards: RuntimeRequestGuards) { return this.request<PlacementJobView>(`/v1/projects/${projectId}/geo/jobs/${jobId}/replays`, { method: "POST", query: jobCampaignQuery(campaignId), ...guards }); }

  listPackageVersions(projectId: string, campaignId: string, opportunityId: string) { return this.request<PackageVersionView[]>(`/v1/projects/${projectId}/geo/opportunities/${opportunityId}/package-versions`, { query: campaignQuery(campaignId) }); }
  getPackageVersion(projectId: string, campaignId: string, versionId: string) { return this.request<PackageVersionView>(`/v1/projects/${projectId}/geo/package-versions/${versionId}`, { query: campaignQuery(campaignId) }); }
  listClaims(projectId: string, campaignId: string, versionId: string) { return this.request<ClaimView[]>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/claims`, { query: campaignQuery(campaignId) }); }
  submitReview(projectId: string, campaignId: string, versionId: string, guards: RuntimeRequestGuards) { return this.request<ReviewSubmissionView>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/submit-review`, { method: "POST", query: campaignQuery(campaignId), ...guards }); }
  listReviews(projectId: string, campaignId: string, versionId: string) { return this.request<ReviewView[]>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/reviews`, { query: campaignQuery(campaignId) }); }
  reviewPackage(projectId: string, campaignId: string, versionId: string, body: ReviewCreate, guards: RuntimeRequestGuards) { return this.request<ReviewView, ReviewCreate>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/reviews`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }
  editPackage(projectId: string, campaignId: string, packageId: string, body: PackageEdit, guards: RuntimeRequestGuards) { return this.request<PackageVersionView, PackageEdit>(`/v1/projects/${projectId}/geo/packages/${packageId}/versions`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }
  listExports(projectId: string, campaignId: string, versionId: string) { return this.request<ExportView[]>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/exports`, { query: campaignQuery(campaignId) }); }
  createExport(projectId: string, campaignId: string, versionId: string, guards: RuntimeRequestGuards) { return this.request<ExportView>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/exports`, { method: "POST", query: campaignQuery(campaignId), ...guards }); }

  listPublications(projectId: string, campaignId: string, versionId: string) { return this.request<PublicationView[]>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/publication-requests`, { query: campaignQuery(campaignId) }); }
  createPublication(projectId: string, campaignId: string, versionId: string, body: PublicationCreate, guards: RuntimeRequestGuards) { return this.request<PublicationView, PublicationCreate>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/publication-requests`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }
  transitionPublication(projectId: string, campaignId: string, publicationId: string, command: string, body: StateReasonCreate, guards: RuntimeRequestGuards) { return this.request<PublicationView, StateReasonCreate>(`/v1/projects/${projectId}/geo/publication-requests/${publicationId}/${command}`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }
  listSubmissions(projectId: string, campaignId: string, publicationId: string) { return this.request<SubmissionView[]>(`/v1/projects/${projectId}/geo/publication-requests/${publicationId}/submissions`, { query: campaignQuery(campaignId) }); }
  createSubmission(projectId: string, campaignId: string, publicationId: string, body: SubmissionCreate, guards: RuntimeRequestGuards) { return this.request<SubmissionView, SubmissionCreate>(`/v1/projects/${projectId}/geo/publication-requests/${publicationId}/submissions`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }
  getSubmission(projectId: string, campaignId: string, submissionId: string) { return this.request<SubmissionView>(`/v1/projects/${projectId}/geo/submissions/${submissionId}`, { query: campaignQuery(campaignId) }); }
  setSubmissionUrl(projectId: string, campaignId: string, submissionId: string, body: SubmissionUrlCreate, guards: RuntimeRequestGuards) { return this.request<SubmissionView, SubmissionUrlCreate>(`/v1/projects/${projectId}/geo/submissions/${submissionId}/url`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }
  blockSubmission(projectId: string, campaignId: string, submissionId: string, body: StateReasonCreate, guards: RuntimeRequestGuards) { return this.request<SubmissionView, StateReasonCreate>(`/v1/projects/${projectId}/geo/submissions/${submissionId}/block`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }
  verifySubmission(projectId: string, campaignId: string, submissionId: string, guards: RuntimeRequestGuards) { return this.request<JobAccepted>(`/v1/projects/${projectId}/geo/submissions/${submissionId}/verification-jobs`, { method: "POST", query: campaignQuery(campaignId), ...guards }); }
  listSubmissionVerificationAttempts(projectId: string, campaignId: string, submissionId: string) { return this.request<PublicationVerificationAttemptView[]>(`/v1/projects/${projectId}/geo/submissions/${submissionId}/verification-attempts`, { query: campaignQuery(campaignId) }); }
  listMeasurements(projectId: string, campaignId: string, submissionId: string) { return this.request<MeasurementView[]>(`/v1/projects/${projectId}/geo/submissions/${submissionId}/measurements`, { query: campaignQuery(campaignId) }); }
  createMeasurement(projectId: string, campaignId: string, submissionId: string, body: MeasurementCreate, guards: RuntimeRequestGuards) { return this.request<MeasurementView, MeasurementCreate>(`/v1/projects/${projectId}/geo/submissions/${submissionId}/measurements`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }
  listMeasurementCollectionTasks(projectId: string, campaignId: string, submissionId?: string) { return this.request<MeasurementCollectionTaskView[]>(`/v1/projects/${projectId}/geo/measurement-collection-tasks`, { query: { campaign_id: campaignId, submission_id: submissionId } }); }
  completeMeasurementCollectionTask(projectId: string, campaignId: string, taskId: string, guards: RuntimeRequestGuards) { return this.request<MeasurementCollectionTaskView>(`/v1/projects/${projectId}/geo/measurement-collection-tasks/${taskId}/complete`, { method: "POST", query: campaignQuery(campaignId), ...guards }); }
  cancelMeasurementCollectionTask(projectId: string, campaignId: string, taskId: string, body: StateReasonCreate, guards: RuntimeRequestGuards) { return this.request<MeasurementCollectionTaskView, StateReasonCreate>(`/v1/projects/${projectId}/geo/measurement-collection-tasks/${taskId}/cancel`, { method: "POST", body, query: campaignQuery(campaignId), ...guards }); }

  listProtocols(projectId: string, campaignId: string) { return this.request<MonitoringProtocolView[]>(`/v1/projects/${projectId}/monitoring-protocols`, { query: campaignQuery(campaignId) }); }
  createProtocol(projectId: string, body: MonitoringProtocolCreate, guards: RuntimeRequestGuards) { return this.request<MonitoringProtocolView, MonitoringProtocolCreate>(`/v1/projects/${projectId}/monitoring-protocols`, { method: "POST", body, ...guards }); }
  approveProtocol(projectId: string, campaignId: string, protocolId: string, guards: RuntimeRequestGuards) { return this.request<MonitoringProtocolView>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/approve`, { method: "POST", query: campaignQuery(campaignId), ...guards }); }
  freezeProtocol(projectId: string, campaignId: string, protocolId: string, guards: RuntimeRequestGuards) { return this.request<MonitoringProtocolView>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/freeze`, { method: "POST", query: campaignQuery(campaignId), ...guards }); }
  bindProtocolQuestionSet(projectId: string, protocolId: string, body: MonitoringProtocolQuestionSetBindingCreate, guards: RuntimeRequestGuards) { return this.request<MonitoringProtocolView, MonitoringProtocolQuestionSetBindingCreate>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/question-set-binding`, { method: "POST", body, ...guards }); }
  listProtocolQueries(projectId: string, campaignId: string, protocolId: string) { return this.request<ProtocolQueryView[]>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/queries`, { query: campaignQuery(campaignId) }); }
  listCitationTargets(projectId: string, campaignId: string, protocolId: string) { return this.request<VerifiedCitationTargetView[]>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/citation-targets`, { query: campaignQuery(campaignId) }); }
  listObservations(projectId: string, campaignId: string, protocolId: string, window: MeasurementWindow) { return this.request<MonitoringObservationView[]>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/observations`, { query: { campaign_id: campaignId, measurement_window: window } }); }
  importObservation(projectId: string, protocolId: string, body: MonitoringObservationCreate, guards: RuntimeRequestGuards) { return this.request<MonitoringObservationView, MonitoringObservationCreate>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/observations`, { method: "POST", body, ...guards }); }
  importOfficialReport(projectId: string, body: OfficialReportImportCreate, guards: RuntimeRequestGuards) { return this.request<OfficialReportImportView, OfficialReportImportCreate>(`/v1/projects/${projectId}/monitoring-official-report-imports`, { method: "POST", body, ...guards }); }
  listSuggestions(projectId: string, campaignId: string, protocolId: string) { return this.request<QuerySuggestionView[]>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/query-suggestions`, { query: campaignQuery(campaignId) }); }
  createSuggestion(projectId: string, protocolId: string, body: QuerySuggestionCreate, guards: RuntimeRequestGuards) { return this.request<QuerySuggestionView, QuerySuggestionCreate>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/query-suggestions`, { method: "POST", body, ...guards }); }
  approveSuggestion(projectId: string, campaignId: string, protocolId: string, suggestionId: string, guards: RuntimeRequestGuards) { return this.request<ProtocolQueryView>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/query-suggestions/${suggestionId}/approve`, { method: "POST", query: campaignQuery(campaignId), ...guards }); }
  listMetrics(projectId: string, campaignId: string) { return this.request<MetricView[]>(`/v1/projects/${projectId}/monitoring-metrics`, { query: campaignQuery(campaignId) }); }
  computeMetrics(projectId: string, protocolId: string, body: MetricCompute, guards: RuntimeRequestGuards) { return this.request<MetricView, MetricCompute>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/metrics`, { method: "POST", body, ...guards }); }
  listReports(projectId: string, campaignId: string) { return this.request<MonitoringReportView[]>(`/v1/projects/${projectId}/monitoring-reports`, { query: campaignQuery(campaignId) }); }
  createReport(projectId: string, body: MonitoringReportCreate, guards: RuntimeRequestGuards) { return this.request<MonitoringReportView, MonitoringReportCreate>(`/v1/projects/${projectId}/monitoring-reports`, { method: "POST", body, ...guards }); }
  approveReport(projectId: string, campaignId: string, reportId: string, guards: RuntimeRequestGuards) { return this.request<MonitoringReportView>(`/v1/projects/${projectId}/monitoring-reports/${reportId}/approve`, { method: "POST", query: campaignQuery(campaignId), ...guards }); }
}

function campaignQuery(campaignId: string) { return { campaign_id: campaignId }; }
function jobCampaignQuery(campaignId?: string | null) { return campaignId ? campaignQuery(campaignId) : {}; }
