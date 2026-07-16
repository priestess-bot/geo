import type { RuntimeHttpResult } from "@geo/api-client/transport";
import type { MeasurementWindow } from "@geo/types/geo";
import { geoClient } from "../../client";
import { emptyResource, type GeoSection, type GeoSelection, type GeoWorkspaceData, type Resource } from "./model";

type SearchValue = string | string[] | undefined;
type SearchParams = { [key: string]: SearchValue };

function one(value: SearchValue): string | undefined { return Array.isArray(value) ? value[0] : value; }
function section(value: string | undefined): GeoSection {
  return value === "observations" || value === "destinations" || value === "placement" ? value : "campaigns";
}
function window(value: string | undefined): MeasurementWindow {
  return value === "t28" || value === "t56" || value === "t84" || value === "ad_hoc" ? value : "baseline";
}
function resource<T>(result: RuntimeHttpResult<T>, fallback: T): Resource<T> {
  if (result.ok) return emptyResource(result.data);
  return {
    data: fallback,
    failure: {
      status: result.status, code: result.error.code, detail: result.error.detail,
      correlationId: result.error.correlation_id || result.response.correlationId,
      retryable: result.error.retryable === true || !result.status || result.status >= 500
    }
  };
}
async function optional<T>(id: string | undefined, load: (id: string) => Promise<RuntimeHttpResult<T>>, fallback: T): Promise<Resource<T>> {
  return id ? resource(await load(id), fallback) : emptyResource(fallback);
}

export async function loadGeoWorkspace(projectId: string, params: SearchParams): Promise<GeoWorkspaceData> {
  const client = await geoClient();
  const requested: GeoSelection = {
    section: section(one(params.geo_section) || one(params.section)), placementStage: one(params.placement_stage) === "generation" || one(params.placement_stage) === "publication" ? one(params.placement_stage) as "generation" | "publication" : "intake",
    measurementWindow: window(one(params.measurement_window)),
    campaignId: one(params.campaign_id), protocolId: one(params.protocol_id), destinationId: one(params.destination_id),
    opportunityId: one(params.opportunity_id), briefVersionId: one(params.brief_version_id), attemptId: one(params.attempt_id),
    skillId: one(params.skill_id), bundleId: one(params.bundle_id), jobId: one(params.job_id), versionId: one(params.version_id),
    publicationId: one(params.publication_id), submissionId: one(params.submission_id)
  };
  const [campaigns, destinations, protocols, metrics, reports, skills, bindings] = await Promise.all([
    client.listCampaigns(projectId), client.listDestinations(projectId), client.listProtocols(projectId),
    client.listMetrics(projectId), client.listReports(projectId), client.listPromptSkills(projectId),
    client.listPromptBindings(projectId)
  ]);
  const top = {
    campaigns: resource(campaigns, []), destinations: resource(destinations, []), protocols: resource(protocols, []),
    metrics: resource(metrics, []), reports: resource(reports, []), skills: resource(skills, []), bindings: resource(bindings, [])
  };
  const selection: GeoSelection = {
    ...requested,
    campaignId: requested.campaignId || top.campaigns.data[0]?.id,
    protocolId: requested.protocolId || top.protocols.data[0]?.id,
    destinationId: requested.destinationId || top.destinations.data[0]?.id,
    skillId: requested.skillId || top.skills.data[0]?.id
  };
  const [queries, protocolQueries, citationTargets, opportunities, policyReviews, observations, suggestions, briefs, releases] = await Promise.all([
    optional(selection.campaignId, (id) => client.listMonitoringQueries(projectId, id), []),
    optional(selection.protocolId, (id) => client.listProtocolQueries(projectId, id), []),
    optional(selection.protocolId, (id) => client.listCitationTargets(projectId, id), []),
    optional(selection.campaignId, (id) => client.listOpportunities(projectId, id), []),
    optional(selection.destinationId, (id) => client.listPolicyReviews(projectId, id), []),
    optional(selection.protocolId, (id) => client.listObservations(projectId, id, selection.measurementWindow), []),
    optional(selection.protocolId, (id) => client.listSuggestions(projectId, id), []),
    optional(selection.opportunityId, (id) => client.listBriefVersions(projectId, id), []),
    optional(selection.skillId, (id) => client.listPromptReleases(projectId, id), [])
  ]);
  selection.opportunityId ||= opportunities.data[0]?.id;
  if (!requested.opportunityId && selection.opportunityId) {
    const nextBriefs = await client.listBriefVersions(projectId, selection.opportunityId);
    Object.assign(briefs, resource(nextBriefs, []));
  }
  selection.briefVersionId ||= briefs.data[0]?.id;
  const [attempts, bundles, packages] = await Promise.all([
    optional(selection.briefVersionId, (id) => client.listEvidenceAttempts(projectId, id), []),
    optional(selection.briefVersionId, (id) => client.listPromptBundles(projectId, id), []),
    optional(selection.opportunityId, (id) => client.listPackageVersions(projectId, id), [])
  ]);
  selection.attemptId ||= attempts.data[0]?.id;
  selection.bundleId ||= bundles.data[0]?.id;
  selection.versionId ||= packages.data[0]?.id;
  const [attempt, evidenceItems, bundle, job, jobEvents, packageVersion, claims, reviews, exports, publications] = await Promise.all([
    optional(selection.attemptId, (id) => client.getEvidenceAttempt(projectId, id), null),
    optional(selection.attemptId, (id) => client.listEvidenceItems(projectId, id), []),
    optional(selection.bundleId, (id) => client.getPromptBundle(projectId, id), null),
    optional(selection.jobId, (id) => client.getJob(id), null),
    optional(selection.jobId, (id) => client.listJobEvents(projectId, id), []),
    optional(selection.versionId, (id) => client.getPackageVersion(projectId, id), null),
    optional(selection.versionId, (id) => client.listClaims(projectId, id), []),
    optional(selection.versionId, (id) => client.listReviews(projectId, id), []),
    optional(selection.versionId, (id) => client.listExports(projectId, id), []),
    optional(selection.versionId, (id) => client.listPublications(projectId, id), [])
  ]);
  selection.publicationId ||= publications.data[0]?.id;
  const submissions = await optional(selection.publicationId, (id) => client.listSubmissions(projectId, id), []);
  selection.submissionId ||= submissions.data[0]?.id;
  const [submission, measurements] = await Promise.all([
    optional(selection.submissionId, (id) => client.getSubmission(projectId, id), null),
    optional(selection.submissionId, (id) => client.listMeasurements(projectId, id), [])
  ]);
  return { ...top, selection, queries, protocolQueries, citationTargets, opportunities, policyReviews, observations, suggestions, briefs, attempts,
    attempt, evidenceItems, releases, bundles, bundle, job, jobEvents, packages, packageVersion, claims, reviews,
    exports, publications, submissions, submission, measurements };
}
