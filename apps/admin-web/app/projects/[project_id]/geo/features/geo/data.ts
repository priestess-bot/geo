import type { RuntimeHttpResult } from "@geo/api-client/transport";
import type { MeasurementWindow, PromptSimulationView } from "@geo/types/geo";
import { geoClient } from "../../client";
import {
  emptyResource,
  type GeoSection,
  type GeoSelection,
  type GeoWorkspaceData,
  type Resource
} from "./model";

type SearchValue = string | string[] | undefined;
type SearchParams = { [key: string]: SearchValue };

function one(value: SearchValue): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function section(value: string | undefined): GeoSection {
  return value === "observations" || value === "destinations" || value === "placement"
    ? value
    : "campaigns";
}

function window(value: string | undefined): MeasurementWindow {
  return value === "t28" || value === "t56" || value === "t84" || value === "ad_hoc"
    ? value
    : "baseline";
}

function placementStage(value: string | undefined): GeoSelection["placementStage"] {
  return value === "evidence"
    || value === "generation"
    || value === "review"
    || value === "publication"
    || value === "simulation"
    ? value
    : "brief";
}

function resource<T>(result: RuntimeHttpResult<T>, fallback: T): Resource<T> {
  if (result.ok) return emptyResource(result.data);
  return {
    data: fallback,
    failure: {
      status: result.status,
      code: result.error.code,
      detail: result.error.detail,
      correlationId: result.error.correlation_id || result.response.correlationId,
      retryable: result.error.retryable === true || !result.status || result.status >= 500
    }
  };
}

async function optional<T>(
  id: string | undefined,
  load: (id: string) => Promise<RuntimeHttpResult<T>>,
  fallback: T
): Promise<Resource<T>> {
  return id ? resource(await load(id), fallback) : emptyResource(fallback);
}

function requestedId<T extends { id: string }>(
  requested: string | undefined,
  source: Resource<T[]>,
  invalidate: () => void
): string | undefined {
  if (!requested) return undefined;
  if (source.failure) return requested;
  if (source.data.some((item) => item.id === requested)) return requested;
  invalidate();
  return undefined;
}

export async function loadGeoWorkspace(
  projectId: string,
  params: SearchParams
): Promise<GeoWorkspaceData> {
  const client = await geoClient();
  const requested: GeoSelection = {
    section: section(one(params.geo_section) || one(params.section)),
    placementStage: placementStage(one(params.placement_stage)),
    measurementWindow: window(one(params.measurement_window)),
    campaignId: one(params.campaign_id),
    protocolId: one(params.protocol_id),
    destinationId: one(params.destination_id),
    opportunityId: one(params.opportunity_id),
    briefVersionId: one(params.brief_version_id),
    attemptId: one(params.attempt_id),
    skillId: one(params.skill_id),
    bundleId: one(params.bundle_id),
    jobId: one(params.job_id),
    versionId: one(params.version_id),
    publicationId: one(params.publication_id),
    submissionId: one(params.submission_id),
    simulationId: one(params.simulation_id),
    questionGenerationJobId: one(params.question_generation_job_id)
  };
  let invalidDeepLink = false;
  const invalidate = () => { invalidDeepLink = true; };

  const [campaignResult, destinationResult, skillResult, bindingResult, questionFactResult] = await Promise.all([
    client.listCampaigns(projectId),
    client.listDestinations(projectId),
    client.listPromptSkills(projectId),
    client.listPromptBindings(projectId),
    client.listKnowledgeQuestionFacts(projectId)
  ]);
  const campaigns = resource(campaignResult, []);
  const destinations = resource(destinationResult, []);
  const skills = resource(skillResult, []);
  const bindings = resource(bindingResult, []);
  const questionFacts = resource(questionFactResult, []);
  const selection: GeoSelection = {
    section: requested.section,
    placementStage: requested.placementStage,
    measurementWindow: requested.measurementWindow,
    campaignId: requestedId(requested.campaignId, campaigns, invalidate)
  };

  const campaignId = selection.campaignId;
  selection.skillId = campaignId
    ? requestedId(requested.skillId, skills, invalidate)
    : undefined;
  if (!campaignId && requested.skillId) invalidate();
  const campaignResourcesPromise = campaignId
    ? Promise.all([
          optional(campaignId, (id) => client.listProtocols(projectId, id), []),
          optional(campaignId, (id) => client.listMetrics(projectId, id), []),
          optional(campaignId, (id) => client.listReports(projectId, id), []),
          optional(campaignId, (id) => client.listMonitoringQueries(projectId, id), []),
          optional(campaignId, (id) => client.listOpportunities(projectId, id), []),
          optional(campaignId, (id) => client.getCampaignPlacementReadiness(projectId, id), null),
          optional(campaignId, (id) => client.listPromptSimulations(projectId, id), []),
          optional(campaignId, (id) => client.listKnowledgeQuestionGenerations(projectId, id), []),
          optional(campaignId, (id) => client.listKnowledgeQuestionSets(projectId, id), [])
        ])
    : Promise.resolve([
          emptyResource<GeoWorkspaceData["protocols"]["data"]>([]),
          emptyResource<GeoWorkspaceData["metrics"]["data"]>([]),
          emptyResource<GeoWorkspaceData["reports"]["data"]>([]),
          emptyResource<GeoWorkspaceData["queries"]["data"]>([]),
          emptyResource<GeoWorkspaceData["opportunities"]["data"]>([]),
          emptyResource<GeoWorkspaceData["placementReadiness"]["data"]>(null),
          emptyResource<GeoWorkspaceData["simulations"]["data"]>([]),
          emptyResource<GeoWorkspaceData["questionGenerations"]["data"]>([]),
          emptyResource<GeoWorkspaceData["questionSets"]["data"]>([])
        ] as const);
  const legacySimulationsPromise = client.listPromptSimulations(projectId)
    .then((result) => resource(result, []));
  const [campaignResources, legacySimulations] = await Promise.all([
    campaignResourcesPromise,
    legacySimulationsPromise
  ]);
  const [protocols, metrics, reports, queries, opportunities, placementReadiness,
    currentSimulations, questionGenerations, questionSets] = campaignResources;
  const simulations = mergeSimulationResources(currentSimulations, legacySimulations);

  selection.protocolId = requestedId(requested.protocolId, protocols, invalidate);
  selection.opportunityId = requestedId(requested.opportunityId, opportunities, invalidate);
  selection.simulationId = requestedId(requested.simulationId, simulations, invalidate);
  const selectedSimulation = simulations.data.find((item) => item.id === selection.simulationId);
  const selectedSimulationCampaignId = selectedSimulation
    ? selectedSimulation.campaign_id || undefined
    : campaignId;
  selection.questionGenerationJobId = requested.questionGenerationJobId
    ? requestedQuestionGeneration(requested.questionGenerationJobId, questionGenerations, invalidate)
    : questionGenerations.data[0]?.job_id;
  const opportunity = opportunities.data.find((item) => item.id === selection.opportunityId);
  selection.destinationId = opportunity?.destination_id;
  if (requested.destinationId && requested.destinationId !== selection.destinationId) invalidate();

  const [protocolQueries, citationTargets, observations, suggestions, briefs, packages,
    promptBinding, promptBindingHistory, releases, policyReviews] = await Promise.all([
    optional(selection.protocolId, (id) => client.listProtocolQueries(projectId, campaignId!, id), []),
    optional(selection.protocolId, (id) => client.listCitationTargets(projectId, campaignId!, id), []),
    optional(
      selection.protocolId,
      (id) => client.listObservations(projectId, campaignId!, id, selection.measurementWindow),
      []
    ),
    optional(selection.protocolId, (id) => client.listSuggestions(projectId, campaignId!, id), []),
    optional(
      selection.opportunityId,
      (id) => client.listBriefVersions(projectId, campaignId!, id),
      []
    ),
    optional(
      selection.opportunityId,
      (id) => client.listPackageVersions(projectId, campaignId!, id),
      []
    ),
    optional(
      selection.opportunityId,
      (id) => client.getOpportunityPromptBinding(projectId, campaignId!, id),
      null
    ),
    optional(
      selection.opportunityId,
      (id) => client.listOpportunityPromptBindings(projectId, campaignId!, id),
      []
    ),
    optional(selection.skillId, (id) => client.listPromptReleases(projectId, id), []),
    optional(
      selection.destinationId,
      (id) => client.listPolicyReviews(projectId, campaignId!, id),
      []
    )
  ]);
  const questionCandidates = await optional(
    selection.questionGenerationJobId,
    (id) => client.listKnowledgeQuestionCandidates(projectId, campaignId!, id),
    []
  );

  selection.briefVersionId = requestedId(requested.briefVersionId, briefs, invalidate);
  selection.versionId = requestedId(requested.versionId, packages, invalidate);
  const [attempts, bundles] = await Promise.all([
    optional(
      selection.briefVersionId,
      (id) => client.listEvidenceAttempts(projectId, campaignId!, id),
      []
    ),
    optional(
      selection.briefVersionId,
      (id) => client.listPromptBundles(projectId, campaignId!, id),
      []
    )
  ]);
  selection.attemptId = requestedId(requested.attemptId, attempts, invalidate);
  selection.bundleId = requestedId(requested.bundleId, bundles, invalidate);
  selection.jobId = campaignId && selectedSimulation?.campaign_id !== null ? requested.jobId : undefined;
  if (requested.jobId && !selection.jobId) invalidate();

  const [attempt, evidenceItems, bundle, job, jobEvents, packageVersion, claims, reviews,
    exports, publications, simulation] = await Promise.all([
    optional(selection.attemptId, (id) => client.getEvidenceAttempt(projectId, campaignId!, id), null),
    optional(selection.attemptId, (id) => client.listEvidenceItems(projectId, campaignId!, id), []),
    optional(selection.bundleId, (id) => client.getPromptBundle(projectId, campaignId!, id), null),
    optional(selection.jobId, (id) => client.getJob(id, campaignId!), null),
    optional(selection.jobId, (id) => client.listJobEvents(projectId, campaignId!, id), []),
    optional(selection.versionId, (id) => client.getPackageVersion(projectId, campaignId!, id), null),
    optional(selection.versionId, (id) => client.listClaims(projectId, campaignId!, id), []),
    optional(selection.versionId, (id) => client.listReviews(projectId, campaignId!, id), []),
    optional(selection.versionId, (id) => client.listExports(projectId, campaignId!, id), []),
    optional(selection.versionId, (id) => client.listPublications(projectId, campaignId!, id), []),
    optional(
      selection.simulationId,
      (id) => selectedSimulationCampaignId
        ? client.getPromptSimulation(projectId, selectedSimulationCampaignId, id)
        : client.getPromptSimulation(projectId, id),
      null
    )
  ]);
  selection.publicationId = requestedId(requested.publicationId, publications, invalidate);
  const submissions = await optional(
    selection.publicationId,
    (id) => client.listSubmissions(projectId, campaignId!, id),
    []
  );
  selection.submissionId = requestedId(requested.submissionId, submissions, invalidate);
  const [submission, measurements] = await Promise.all([
    optional(selection.submissionId, (id) => client.getSubmission(projectId, campaignId!, id), null),
    optional(selection.submissionId, (id) => client.listMeasurements(projectId, campaignId!, id), [])
  ]);

  const workspace: GeoWorkspaceData = {
    selection,
    campaigns,
    destinations,
    protocols,
    metrics,
    reports,
    skills,
    simulations,
    questionFacts,
    questionGenerations,
    questionCandidates,
    questionSets,
    bindings,
    queries,
    protocolQueries,
    citationTargets,
    opportunities,
    policyReviews,
    placementReadiness,
    promptBinding,
    promptBindingHistory,
    observations,
    suggestions,
    briefs,
    attempts,
    attempt,
    evidenceItems,
    releases,
    bundles,
    bundle,
    job,
    jobEvents,
    packages,
    packageVersion,
    claims,
    reviews,
    exports,
    publications,
    submissions,
    submission,
    measurements,
    simulation
  };
  if (invalidDeepLink) workspace.canonicalHref = canonicalHref(projectId, selection);
  return workspace;
}

function mergeSimulationResources(
  current: Resource<PromptSimulationView[]>,
  legacy: Resource<PromptSimulationView[]>
): Resource<PromptSimulationView[]> {
  const byId = new Map<string, PromptSimulationView>();
  for (const item of [...current.data, ...legacy.data]) {
    if (!byId.has(item.id)) byId.set(item.id, item);
  }
  const data = [...byId.values()];
  const failure = current.failure || legacy.failure;
  return failure ? { data, failure } : emptyResource(data);
}

function canonicalHref(projectId: string, selection: GeoSelection): string {
  const params = new URLSearchParams({
    tab: "geo",
    geo_section: selection.section,
    placement_stage: selection.placementStage,
    measurement_window: selection.measurementWindow
  });
  const optionalParams: Array<[string, string | undefined]> = [
    ["campaign_id", selection.campaignId],
    ["protocol_id", selection.protocolId],
    ["destination_id", selection.destinationId],
    ["opportunity_id", selection.opportunityId],
    ["brief_version_id", selection.briefVersionId],
    ["attempt_id", selection.attemptId],
    ["skill_id", selection.skillId],
    ["bundle_id", selection.bundleId],
    ["job_id", selection.jobId],
    ["version_id", selection.versionId],
    ["publication_id", selection.publicationId],
    ["submission_id", selection.submissionId],
    ["simulation_id", selection.simulationId],
    ["question_generation_job_id", selection.questionGenerationJobId]
  ];
  for (const [key, value] of optionalParams) {
    if (value) params.set(key, value);
  }
  return `/projects/${encodeURIComponent(projectId)}?${params.toString()}`;
}

function requestedQuestionGeneration(
  requested: string,
  source: Resource<Array<{ job_id: string }>>,
  invalidate: () => void
): string | undefined {
  if (source.failure) return requested;
  if (source.data.some((item) => item.job_id === requested)) return requested;
  invalidate();
  return undefined;
}
