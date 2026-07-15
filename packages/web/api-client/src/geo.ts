import type {
  AsyncResourceCreated, BriefVersionCreate, BriefVersionView, CampaignCreate, CampaignCreated, CampaignView,
  ClaimView, DestinationCreate, DestinationPolicyReviewCreate, DestinationPolicyView, DestinationView,
  EvidenceAttemptView, EvidenceItemView, ExportView, GenerationCreate, JobAccepted, JobStatus,
  MeasurementCreate, MeasurementView, MeasurementWindow, MetricView, MonitoringObservationCreate,
  MonitoringObservationView, MonitoringProtocolCreate, MonitoringProtocolView, MonitoringQueryCreate,
  MonitoringQueryView, MonitoringReportCreate, MonitoringReportView, OpportunityStateCommand, OpportunityView,
  PackageEdit, PackageVersionView, PlacementJobEventView, PlacementJobView, PromptBundleCreate,
  PromptBundleDetail, PromptBundleView, PromptReleaseCreate, PromptReleaseView, PromptSkillCreate,
  PromptSkillView, PromptTaskBindingCreate, PromptTaskBindingView, PublicationCreate, PublicationView,
  ProtocolQueryView, QuerySuggestionCreate, QuerySuggestionView, ReviewCreate, ReviewSubmissionView, ReviewView,
  StateReasonCreate, SubmissionCreate, SubmissionUrlCreate, SubmissionView, VerifiedCitationTargetView
} from "@geo/types/geo";
import {
  geoApiUrl, mergeClientRequestInit, performRuntimeHttpRequest, runtimeGuardHeaders,
  type GeoApiClientOptions, type RuntimeHttpResult, type RuntimeRequestGuards
} from "./transport";

type HttpOptions<TBody> = RuntimeRequestGuards & { method?: "GET" | "POST" | "PUT"; body?: TBody; query?: { [key: string]: string | number | boolean | undefined | null }; };

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
  transitionOpportunity(projectId: string, opportunityId: string, command: string, body: OpportunityStateCommand, guards: RuntimeRequestGuards) { return this.request<OpportunityView, OpportunityStateCommand>(`/v1/projects/${projectId}/geo/opportunities/${opportunityId}/transitions/${command}`, { method: "POST", body, ...guards }); }

  listDestinations(projectId: string) { return this.request<DestinationView[]>(`/v1/projects/${projectId}/geo/destinations`); }
  createDestination(projectId: string, body: DestinationCreate, guards: RuntimeRequestGuards) { return this.request<DestinationView, DestinationCreate>(`/v1/projects/${projectId}/geo/destinations`, { method: "POST", body, ...guards }); }
  listPolicyReviews(projectId: string, destinationId: string) { return this.request<DestinationPolicyView[]>(`/v1/projects/${projectId}/geo/destinations/${destinationId}/policy-reviews`); }
  createPolicyReview(projectId: string, destinationId: string, body: DestinationPolicyReviewCreate, guards: RuntimeRequestGuards) { return this.request<DestinationPolicyView, DestinationPolicyReviewCreate>(`/v1/projects/${projectId}/geo/destinations/${destinationId}/policy-reviews`, { method: "POST", body, ...guards }); }

  listBriefVersions(projectId: string, opportunityId: string) { return this.request<BriefVersionView[]>(`/v1/projects/${projectId}/geo/opportunities/${opportunityId}/brief-versions`); }
  createBriefVersion(projectId: string, opportunityId: string, body: BriefVersionCreate, guards: RuntimeRequestGuards) { return this.request<BriefVersionView, BriefVersionCreate>(`/v1/projects/${projectId}/geo/opportunities/${opportunityId}/brief-versions`, { method: "POST", body, ...guards }); }
  listEvidenceAttempts(projectId: string, briefVersionId: string) { return this.request<EvidenceAttemptView[]>(`/v1/projects/${projectId}/geo/brief-versions/${briefVersionId}/evidence-pack-attempts`); }
  buildEvidenceAttempt(projectId: string, briefVersionId: string, guards: RuntimeRequestGuards) { return this.request<AsyncResourceCreated>(`/v1/projects/${projectId}/geo/brief-versions/${briefVersionId}/evidence-pack-attempts`, { method: "POST", ...guards }); }
  getEvidenceAttempt(projectId: string, attemptId: string) { return this.request<EvidenceAttemptView>(`/v1/projects/${projectId}/geo/evidence-pack-attempts/${attemptId}`); }
  listEvidenceItems(projectId: string, attemptId: string) { return this.request<EvidenceItemView[]>(`/v1/projects/${projectId}/geo/evidence-pack-attempts/${attemptId}/items`); }

  listPromptSkills(projectId: string) { return this.request<PromptSkillView[]>(`/v1/projects/${projectId}/geo/prompt-skills`); }
  createPromptSkill(projectId: string, body: PromptSkillCreate, guards: RuntimeRequestGuards) { return this.request<PromptSkillView, PromptSkillCreate>(`/v1/projects/${projectId}/geo/prompt-skills`, { method: "POST", body, ...guards }); }
  listPromptReleases(projectId: string, skillId: string) { return this.request<PromptReleaseView[]>(`/v1/projects/${projectId}/geo/prompt-skills/${skillId}/releases`); }
  createPromptRelease(projectId: string, skillId: string, body: PromptReleaseCreate, guards: RuntimeRequestGuards) { return this.request<PromptReleaseView, PromptReleaseCreate>(`/v1/projects/${projectId}/geo/prompt-skills/${skillId}/releases`, { method: "POST", body, ...guards }); }
  installDefaultPromptCatalog(projectId: string, guards: RuntimeRequestGuards) { return this.request<PromptTaskBindingView[]>(`/v1/projects/${projectId}/geo/prompt-catalog/defaults`, { method: "PUT", ...guards }); }
  listPromptBindings(projectId: string) { return this.request<PromptTaskBindingView[]>(`/v1/projects/${projectId}/geo/prompt-task-bindings`); }
  bindPromptTask(projectId: string, taskKey: string, body: PromptTaskBindingCreate, guards: RuntimeRequestGuards) { return this.request<PromptTaskBindingView, PromptTaskBindingCreate>(`/v1/projects/${projectId}/geo/prompt-task-bindings/${encodeURIComponent(taskKey)}`, { method: "PUT", body, ...guards }); }
  listPromptBundles(projectId: string, briefVersionId: string) { return this.request<PromptBundleView[]>(`/v1/projects/${projectId}/geo/brief-versions/${briefVersionId}/prompt-bundles`); }
  createPromptBundle(projectId: string, briefVersionId: string, body: PromptBundleCreate, guards: RuntimeRequestGuards) { return this.request<PromptBundleView, PromptBundleCreate>(`/v1/projects/${projectId}/geo/brief-versions/${briefVersionId}/prompt-bundles`, { method: "POST", body, ...guards }); }
  getPromptBundle(projectId: string, bundleId: string) { return this.request<PromptBundleDetail>(`/v1/projects/${projectId}/geo/prompt-bundles/${bundleId}`); }

  createGenerationJob(projectId: string, bundleId: string, body: GenerationCreate, guards: RuntimeRequestGuards) { return this.request<JobAccepted, GenerationCreate>(`/v1/projects/${projectId}/geo/prompt-bundles/${bundleId}/generation-jobs`, { method: "POST", body, ...guards }); }
  getJob(jobId: string) { return this.request<JobStatus>(`/v1/jobs/${jobId}`); }
  listJobEvents(projectId: string, jobId: string) { return this.request<PlacementJobEventView[]>(`/v1/projects/${projectId}/geo/jobs/${jobId}/events`); }
  cancelJob(projectId: string, jobId: string, guards: RuntimeRequestGuards) { return this.request<PlacementJobView>(`/v1/projects/${projectId}/geo/jobs/${jobId}/cancel`, { method: "POST", ...guards }); }
  retryJob(projectId: string, jobId: string, guards: RuntimeRequestGuards) { return this.request<PlacementJobView>(`/v1/projects/${projectId}/geo/jobs/${jobId}/retry-now`, { method: "POST", ...guards }); }
  replayJob(projectId: string, jobId: string, guards: RuntimeRequestGuards) { return this.request<PlacementJobView>(`/v1/projects/${projectId}/geo/jobs/${jobId}/replays`, { method: "POST", ...guards }); }

  listPackageVersions(projectId: string, opportunityId: string) { return this.request<PackageVersionView[]>(`/v1/projects/${projectId}/geo/opportunities/${opportunityId}/package-versions`); }
  getPackageVersion(projectId: string, versionId: string) { return this.request<PackageVersionView>(`/v1/projects/${projectId}/geo/package-versions/${versionId}`); }
  listClaims(projectId: string, versionId: string) { return this.request<ClaimView[]>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/claims`); }
  submitReview(projectId: string, versionId: string, guards: RuntimeRequestGuards) { return this.request<ReviewSubmissionView>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/submit-review`, { method: "POST", ...guards }); }
  listReviews(projectId: string, versionId: string) { return this.request<ReviewView[]>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/reviews`); }
  reviewPackage(projectId: string, versionId: string, body: ReviewCreate, guards: RuntimeRequestGuards) { return this.request<ReviewView, ReviewCreate>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/reviews`, { method: "POST", body, ...guards }); }
  editPackage(projectId: string, packageId: string, body: PackageEdit, guards: RuntimeRequestGuards) { return this.request<PackageVersionView, PackageEdit>(`/v1/projects/${projectId}/geo/packages/${packageId}/versions`, { method: "POST", body, ...guards }); }
  listExports(projectId: string, versionId: string) { return this.request<ExportView[]>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/exports`); }
  createExport(projectId: string, versionId: string, guards: RuntimeRequestGuards) { return this.request<ExportView>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/exports`, { method: "POST", ...guards }); }

  listPublications(projectId: string, versionId: string) { return this.request<PublicationView[]>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/publication-requests`); }
  createPublication(projectId: string, versionId: string, body: PublicationCreate, guards: RuntimeRequestGuards) { return this.request<PublicationView, PublicationCreate>(`/v1/projects/${projectId}/geo/package-versions/${versionId}/publication-requests`, { method: "POST", body, ...guards }); }
  transitionPublication(projectId: string, publicationId: string, command: string, body: StateReasonCreate, guards: RuntimeRequestGuards) { return this.request<PublicationView, StateReasonCreate>(`/v1/projects/${projectId}/geo/publication-requests/${publicationId}/${command}`, { method: "POST", body, ...guards }); }
  listSubmissions(projectId: string, publicationId: string) { return this.request<SubmissionView[]>(`/v1/projects/${projectId}/geo/publication-requests/${publicationId}/submissions`); }
  createSubmission(projectId: string, publicationId: string, body: SubmissionCreate, guards: RuntimeRequestGuards) { return this.request<SubmissionView, SubmissionCreate>(`/v1/projects/${projectId}/geo/publication-requests/${publicationId}/submissions`, { method: "POST", body, ...guards }); }
  getSubmission(projectId: string, submissionId: string) { return this.request<SubmissionView>(`/v1/projects/${projectId}/geo/submissions/${submissionId}`); }
  setSubmissionUrl(projectId: string, submissionId: string, body: SubmissionUrlCreate, guards: RuntimeRequestGuards) { return this.request<SubmissionView, SubmissionUrlCreate>(`/v1/projects/${projectId}/geo/submissions/${submissionId}/url`, { method: "POST", body, ...guards }); }
  blockSubmission(projectId: string, submissionId: string, body: StateReasonCreate, guards: RuntimeRequestGuards) { return this.request<SubmissionView, StateReasonCreate>(`/v1/projects/${projectId}/geo/submissions/${submissionId}/block`, { method: "POST", body, ...guards }); }
  verifySubmission(projectId: string, submissionId: string, guards: RuntimeRequestGuards) { return this.request<JobAccepted>(`/v1/projects/${projectId}/geo/submissions/${submissionId}/verification-jobs`, { method: "POST", ...guards }); }
  listMeasurements(projectId: string, submissionId: string) { return this.request<MeasurementView[]>(`/v1/projects/${projectId}/geo/submissions/${submissionId}/measurements`); }
  createMeasurement(projectId: string, submissionId: string, body: MeasurementCreate, guards: RuntimeRequestGuards) { return this.request<MeasurementView, MeasurementCreate>(`/v1/projects/${projectId}/geo/submissions/${submissionId}/measurements`, { method: "POST", body, ...guards }); }

  listProtocols(projectId: string) { return this.request<MonitoringProtocolView[]>(`/v1/projects/${projectId}/monitoring-protocols`); }
  createProtocol(projectId: string, body: MonitoringProtocolCreate, guards: RuntimeRequestGuards) { return this.request<MonitoringProtocolView, MonitoringProtocolCreate>(`/v1/projects/${projectId}/monitoring-protocols`, { method: "POST", body, ...guards }); }
  approveProtocol(projectId: string, protocolId: string, guards: RuntimeRequestGuards) { return this.request<MonitoringProtocolView>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/approve`, { method: "POST", ...guards }); }
  freezeProtocol(projectId: string, protocolId: string, guards: RuntimeRequestGuards) { return this.request<MonitoringProtocolView>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/freeze`, { method: "POST", ...guards }); }
  listProtocolQueries(projectId: string, protocolId: string) { return this.request<ProtocolQueryView[]>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/queries`); }
  listCitationTargets(projectId: string, protocolId: string) { return this.request<VerifiedCitationTargetView[]>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/citation-targets`); }
  listObservations(projectId: string, protocolId: string, window: MeasurementWindow) { return this.request<MonitoringObservationView[]>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/observations`, { query: { measurement_window: window } }); }
  importObservation(projectId: string, protocolId: string, body: MonitoringObservationCreate, guards: RuntimeRequestGuards) { return this.request<MonitoringObservationView, MonitoringObservationCreate>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/observations`, { method: "POST", body, ...guards }); }
  listSuggestions(projectId: string, protocolId: string) { return this.request<QuerySuggestionView[]>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/query-suggestions`); }
  createSuggestion(projectId: string, protocolId: string, body: QuerySuggestionCreate, guards: RuntimeRequestGuards) { return this.request<QuerySuggestionView, QuerySuggestionCreate>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/query-suggestions`, { method: "POST", body, ...guards }); }
  approveSuggestion(projectId: string, protocolId: string, suggestionId: string, guards: RuntimeRequestGuards) { return this.request<ProtocolQueryView>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/query-suggestions/${suggestionId}/approve`, { method: "POST", ...guards }); }
  listMetrics(projectId: string) { return this.request<MetricView[]>(`/v1/projects/${projectId}/monitoring-metrics`); }
  computeMetrics(projectId: string, protocolId: string, window: MeasurementWindow, guards: RuntimeRequestGuards) { return this.request<MetricView, { measurement_window: MeasurementWindow }>(`/v1/projects/${projectId}/monitoring-protocols/${protocolId}/metrics`, { method: "POST", body: { measurement_window: window }, ...guards }); }
  listReports(projectId: string) { return this.request<MonitoringReportView[]>(`/v1/projects/${projectId}/monitoring-reports`); }
  createReport(projectId: string, body: MonitoringReportCreate, guards: RuntimeRequestGuards) { return this.request<MonitoringReportView, MonitoringReportCreate>(`/v1/projects/${projectId}/monitoring-reports`, { method: "POST", body, ...guards }); }
  approveReport(projectId: string, reportId: string, guards: RuntimeRequestGuards) { return this.request<MonitoringReportView>(`/v1/projects/${projectId}/monitoring-reports/${reportId}/approve`, { method: "POST", ...guards }); }
}
