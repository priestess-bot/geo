import { cookies } from "next/headers";

import { CustomerApiClient, type CustomerApiResult } from "@geo/api-client/customer";
import { GEO_SESSION_COOKIE } from "@geo/auth";
import { resolveCounterpartPortalUrl } from "@geo/auth/portal-url";
import type { AuthIdentity } from "@geo/types/auth";
import type {
  CustomerCampaign,
  CustomerCampaignReadModel,
  CustomerProblemDetails,
  CustomerProjectPage,
  CustomerProjectSummary,
  CustomerWorkflowCReportPage
} from "@geo/types/customer";

export type SelectionStatus =
  | "selected"
  | "unselected"
  | "unauthorized"
  | "empty"
  | "error";

export type SessionPortalResponse = Readonly<{
  authenticated: boolean;
  projects: CustomerProjectSummary[];
  selectedProject: CustomerProjectSummary | null;
  roles: string[];
  selectionStatus: SelectionStatus;
  problem?: CustomerProblemDetails;
}>;

export type CampaignPortalResponse = Readonly<{
  campaigns: CustomerCampaign[];
  selectedCampaign: CustomerCampaign | null;
  selectionStatus: SelectionStatus;
  problem?: CustomerProblemDetails;
}>;

export type ResourceState<T> =
  | Readonly<{ status: "ready"; data: T }>
  | Readonly<{ status: "error"; problem: CustomerProblemDetails }>;

export type CustomerGeoReadModel = ResourceState<CustomerCampaignReadModel>;
export type CustomerWorkflowCReports = ResourceState<CustomerWorkflowCReportPage>;

const PROJECT_PAGE_SIZE = 100;
const MAX_AUTHORIZED_PROJECTS = 5000;

export function apiBase(): string {
  return process.env.API_CUSTOMER_BASE_URL
    || process.env.NEXT_PUBLIC_API_BASE_URL
    || "http://customer-api:8000";
}

export function adminWebBaseUrl(): string {
  return resolveCounterpartPortalUrl({
    configuredValue: process.env.ADMIN_WEB_BASE_URL,
    deploymentEnvironment: process.env.GEO_DEPLOYMENT_ENVIRONMENT,
    developmentFallback: "http://localhost:3001/login",
    environmentName: "ADMIN_WEB_BASE_URL",
    nodeEnv: process.env.NODE_ENV,
    publicDevelopmentValue: process.env.NEXT_PUBLIC_ADMIN_WEB_BASE_URL
  });
}

export async function loadSessionPortal(projectId?: string): Promise<SessionPortalResponse> {
  const client = await customerClient();
  const [identity, projects] = await Promise.all([
    client.currentIdentity(),
    loadAllCustomerProjects(client)
  ]);

  if (!identity.ok) {
    return {
      authenticated: false,
      projects: [],
      selectedProject: null,
      roles: [],
      selectionStatus: "empty",
      ...(identity.problem.status === 401 ? {} : { problem: identity.problem })
    };
  }
  if (!projects.ok) {
    return {
      authenticated: true,
      projects: [],
      selectedProject: null,
      roles: identity.data.roles,
      selectionStatus: "error",
      problem: projects.problem
    };
  }
  return selectedSession(identity.data, projects.data, projectId);
}

export async function loadCampaignPortal(
  projectId: string,
  campaignId?: string
): Promise<CampaignPortalResponse> {
  const result = await (await customerClient()).listGeoCampaigns(projectId);
  if (!result.ok) {
    return {
      campaigns: [],
      selectedCampaign: null,
      selectionStatus: "error",
      problem: result.problem
    };
  }
  if (!result.data.length) {
    return { campaigns: [], selectedCampaign: null, selectionStatus: "empty" };
  }
  if (!campaignId) {
    return {
      campaigns: result.data,
      selectedCampaign: null,
      selectionStatus: "unselected"
    };
  }
  const selected = result.data.find((campaign) => campaign.id === campaignId) || null;
  return {
    campaigns: result.data,
    selectedCampaign: selected,
    selectionStatus: selected ? "selected" : "unauthorized"
  };
}

export async function loadCustomerGeoReadModel(
  projectId: string,
  campaignId: string
): Promise<CustomerGeoReadModel> {
  return resource(
    await (await customerClient()).getGeoCampaignReadModel(projectId, campaignId)
  );
}

export async function loadCustomerWorkflowCReports(
  projectId: string,
  campaignId: string
): Promise<CustomerWorkflowCReports> {
  return resource(
    await (await customerClient()).listWorkflowCApprovedReports(projectId, campaignId)
  );
}

export function resourceProblems(
  ...models: ReadonlyArray<ResourceState<unknown>>
): CustomerProblemDetails[] {
  return models.flatMap((model) => model.status === "error" ? [model.problem] : []);
}

async function customerClient(): Promise<CustomerApiClient> {
  const cookieStore = await cookies();
  const sessionToken = cookieStore.get(GEO_SESSION_COOKIE)?.value || "";
  const headers = sessionToken
    ? { Cookie: `${GEO_SESSION_COOKIE}=${encodeURIComponent(sessionToken)}` }
    : undefined;
  return new CustomerApiClient(apiBase(), { headers, cache: "no-store" });
}

async function loadAllCustomerProjects(
  client: CustomerApiClient
): Promise<CustomerApiResult<CustomerProjectSummary[]>> {
  const projects: CustomerProjectSummary[] = [];
  const projectIds = new Set<string>();
  let expectedTotal: number | null = null;
  let offset = 0;

  while (expectedTotal === null || projects.length < expectedTotal) {
    const page = await client.listProjects(PROJECT_PAGE_SIZE, offset);
    if (!page.ok) return page;
    const problem = paginationProblem(page.data, expectedTotal, projects.length, projectIds);
    if (problem) return { ok: false, problem, response: page.response };
    expectedTotal = page.data.total;
    for (const project of page.data.items) {
      projectIds.add(project.project_id);
      projects.push(project);
    }
    offset = projects.length;
  }
  return { ok: true, data: projects, status: 200, response: {} };
}

function paginationProblem(
  page: CustomerProjectPage,
  expectedTotal: number | null,
  loadedCount: number,
  projectIds: Set<string>
): CustomerProblemDetails | null {
  const invalidTotal = page.total > MAX_AUTHORIZED_PROJECTS
    || (expectedTotal !== null && expectedTotal !== page.total);
  const duplicate = page.items.some((project) => projectIds.has(project.project_id));
  const endedEarly = page.items.length === 0 && loadedCount < page.total;
  const overflow = loadedCount + page.items.length > page.total;
  if (!invalidTotal && !duplicate && !endedEarly && !overflow) return null;
  return {
    type: "urn:geo:problem:invalid-customer-project-page",
    title: "Invalid project scope",
    status: 502,
    detail: "The Customer API returned an inconsistent authorized project list.",
    instance: "/v1/projects",
    request_id: ""
  };
}

function selectedSession(
  identity: AuthIdentity,
  projects: CustomerProjectSummary[],
  projectId?: string
): SessionPortalResponse {
  if (!projects.length) {
    return {
      authenticated: true,
      projects,
      selectedProject: null,
      roles: identity.roles,
      selectionStatus: "empty"
    };
  }
  if (!projectId) {
    return {
      authenticated: true,
      projects,
      selectedProject: null,
      roles: identity.roles,
      selectionStatus: "unselected"
    };
  }
  const selectedProject = projects.find((project) => project.project_id === projectId) || null;
  return {
    authenticated: true,
    projects,
    selectedProject,
    roles: identity.roles,
    selectionStatus: selectedProject ? "selected" : "unauthorized"
  };
}

function resource<T>(result: CustomerApiResult<T>): ResourceState<T> {
  return result.ok
    ? { status: "ready", data: result.data }
    : { status: "error", problem: result.problem };
}
