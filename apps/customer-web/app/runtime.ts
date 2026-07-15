import { cookies } from "next/headers";

import { CustomerApiClient } from "@geo/api-client/customer";
import {
  GEO_CSRF_COOKIE,
  GEO_CSRF_HEADER,
  GEO_SESSION_COOKIE
} from "@geo/auth";
import { resolveCounterpartPortalUrl } from "@geo/auth/portal-url";
import {
  isAuthIdentity,
  parseAuthError,
  type AuthErrorEnvelope,
  type AuthIdentity
} from "@geo/types/auth";
import {
  runtimeGuardHeaders,
  type RuntimeErrorEnvelope,
  type RuntimeHttpResult,
  type RuntimeRequestGuards,
  type RuntimeResponseMetadata
} from "@geo/api-client/transport";
import type { CustomerApiPath } from "@geo/types/customer";

export type RuntimeRequestOptions = RuntimeRequestGuards & {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | undefined | null>;
  cache?: RequestCache;
  actorId?: string;
  includeCsrfProof?: boolean;
};

export type RuntimePage<T = Record<string, unknown>> = {
  total_count: number;
  limit?: number;
  offset?: number;
  records: T[];
};

export type PortalBundle = {
  access?: { project_id?: string; member_user_id?: string };
  project?: {
    project?: { id?: string; name?: string; target_brand?: string; status?: string };
    tenant?: { name?: string };
    competitors?: Array<{ canonical_name?: string; official_domains?: string[] }>;
    prompt_count?: number;
  };
  launch_config?: { launch_config?: { customer_email?: string; primary_domain?: string; status?: string } & Record<string, unknown> } | null;
  score_weight_config?: { score_weight_config?: { formula_version?: string } & Record<string, unknown> } | null;
  lifecycle_events?: RuntimePage;
  audit_events?: RuntimePage;
};

export type PortalAccessResponse = {
  accepted_invitation?: Record<string, unknown>;
  bundle?: PortalBundle;
};

export type AuthorizedProject = {
  project?: { id?: string; name?: string; target_brand?: string; status?: string };
  tenant?: { name?: string };
  competitors?: Array<{ canonical_name?: string; official_domains?: string[] }>;
  prompt_count?: number;
};

export type SessionPortalResponse = PortalAccessResponse & {
  authenticated: boolean;
  authorized_projects: AuthorizedProject[];
  selection_status: "selected" | "fallback" | "empty";
  error?: AuthErrorEnvelope;
};

export type RuntimeResult<T> =
  | {
      ok: true;
      data: T;
      status: number;
      response: RuntimeResponseMetadata;
    }
  | {
      ok: false;
      error: AuthErrorEnvelope;
      problem: RuntimeErrorEnvelope;
      status?: number;
      response: RuntimeResponseMetadata;
    };

export type PortalRuntimeData = {
  scores: RuntimePage;
  evidence: RuntimePage;
  collectionRuns: RuntimePage;
  graphs: RuntimePage;
  reports: RuntimePage;
  reportJobs: RuntimePage;
  actions: RuntimePage;
  traceability: Record<string, unknown> | null;
  errors: Array<{ resource: string; error: AuthErrorEnvelope }>;
};

export type GeoCustomerSummary = {
  campaigns: Array<{ id?: string; name?: string; status?: string; product_name?: string }>;
  verified_placements: Array<{ id?: string; published_url?: string; published_at?: string; campaign_id?: string; destination_name?: string }>;
  measurement_windows: Array<{ campaign_id?: string; window_key?: string; due_at?: string; status?: string; confounded?: boolean; recommendation_share?: number | null; product_mention_share?: number | null; placement_citation_share?: number | null }>;
};

type RuntimePageLoad = {
  page: RuntimePage;
  failure?: { resource: string; error: AuthErrorEnvelope };
};

type StableCustomerProjectPage = {
  items: Array<{
    project_id: string;
    display_name: string;
    market_code: string;
    status: string;
  }>;
  total: number;
  limit: number;
  offset: number;
};

const SURFACE_PROJECT_PAGE_SIZE = 100;
const MAX_AUTHORIZED_PROJECTS = 5000;

export function apiBase(): string {
  return process.env.API_CUSTOMER_BASE_URL
    || process.env.API_INTERNAL_BASE_URL
    || process.env.NEXT_PUBLIC_API_BASE_URL
    || "http://customer-api:8000";
}

export function adminWebBaseUrl(): string {
  return resolveCounterpartPortalUrl({
    configuredValue: process.env.ADMIN_WEB_BASE_URL,
    developmentFallback: "http://localhost:3001/login",
    environmentName: "ADMIN_WEB_BASE_URL",
    nodeEnv: process.env.NODE_ENV,
    publicDevelopmentValue: process.env.NEXT_PUBLIC_ADMIN_WEB_BASE_URL
  });
}

async function actorHeaders(
  extra?: HeadersInit,
  includeCsrfProof = true
): Promise<HeadersInit> {
  const cookieStore = await cookies();
  const sessionToken = cookieStore.get(GEO_SESSION_COOKIE)?.value || "";
  const csrfToken = cookieStore.get(GEO_CSRF_COOKIE)?.value || "";
  if (sessionToken) {
    const cookieHeader = [
      `${GEO_SESSION_COOKIE}=${encodeURIComponent(sessionToken)}`,
      ...(csrfToken ? [`${GEO_CSRF_COOKIE}=${encodeURIComponent(csrfToken)}`] : [])
    ].join("; ");
    return {
      Cookie: cookieHeader,
      ...(csrfToken && includeCsrfProof
        ? { [GEO_CSRF_HEADER]: csrfToken }
        : {}),
      ...(extra || {})
    };
  }
  return { ...(extra || {}) };
}

export async function runtimeHttpRequest<T>(
  path: CustomerApiPath,
  options: RuntimeRequestOptions = {}
): Promise<RuntimeHttpResult<T>> {
  const hasBody = options.body !== undefined;
  const commandHeaders = runtimeGuardHeaders(options);
  const headers = await actorHeaders(
    {
      ...(hasBody ? { "Content-Type": "application/json" } : {}),
      ...commandHeaders
    },
    options.includeCsrfProof
  );
  const client = new CustomerApiClient(apiBase(), { headers, cache: options.cache || "no-store" });
  return client.call<T>(path, options.query, {
    method: options.method || "GET",
    body: hasBody ? JSON.stringify(options.body) : undefined
  });
}

export async function runtimeRequest<T>(
  path: CustomerApiPath,
  options: RuntimeRequestOptions = {}
): Promise<RuntimeResult<T>> {
  const result = await runtimeHttpRequest<T>(path, options);
  if (result.ok) {
    return result;
  }
  const legacyError = result.status === undefined
    ? {
        code: "auth_upstream_unavailable",
        detail: "Runtime API unavailable",
        correlation_id: result.error.correlation_id
      }
    : result.error;
  const fallbackCode = result.status === undefined ? "auth_upstream_unavailable" : "auth_request_failed";
  return {
    ...result,
    error: parseAuthError(
      legacyError,
      fallbackCode,
      legacyError.detail,
      legacyError.correlation_id
    ),
    problem: result.error
  };
}

export async function loadGeoCustomerSummary(projectId: string, actorId?: string): Promise<GeoCustomerSummary | null> {
  const response = await runtimeRequest<GeoCustomerSummary>("/v1/geo/customer-summary", { query: { project_id: projectId }, actorId });
  return response.ok && response.data ? response.data : null;
}

export async function loadSessionPortal(projectId?: string): Promise<SessionPortalResponse> {
  const authResponse = await runtimeRequest<AuthIdentity>("/v1/auth/me", {
    includeCsrfProof: false
  });
  if (!authResponse.ok) {
    return {
      authenticated: false,
      authorized_projects: [],
      selection_status: "empty",
      ...(authResponse.status === 401 ? {} : { error: authResponse.error })
    };
  }
  if (!isAuthIdentity(authResponse.data)) {
    return {
      authenticated: false,
      authorized_projects: [],
      selection_status: "empty",
      error: {
        code: "auth_request_failed",
        detail: "The authentication service returned an invalid session scope.",
        correlation_id: ""
      }
    };
  }
  const actorId = authResponse.data.actor_id;
  const projectPage = await loadAllCustomerProjects();
  if (!projectPage.ok) {
    return {
      authenticated: true,
      authorized_projects: [],
      selection_status: "empty",
      error: projectPage.error,
      bundle: { access: { member_user_id: actorId } }
    };
  }
  const authorizedProjects = projectPage.data;
  const requested = projectId ? authorizedProjects.find((record) => record.project?.id === projectId) : undefined;
  const selected = requested || authorizedProjects[0];
  const selectedProjectId = selected?.project?.id || "";
  if (!selectedProjectId) {
    return {
      authenticated: true,
      authorized_projects: authorizedProjects,
      selection_status: "empty",
      bundle: { access: { member_user_id: actorId } }
    };
  }
  const [launch, scoreWeight, lifecycleEvents, auditEvents] = await Promise.all([
    runtimeRequest<Record<string, unknown>>("/v1/project-launch-configs/runtime", { query: { project_id: selectedProjectId } }),
    runtimeRequest<Record<string, unknown>>("/v1/score-weight-configs/runtime", { query: { project_id: selectedProjectId } }),
    runtimeRequest<RuntimePage>("/v1/projects/runtime/lifecycle-events", { query: { project_id: selectedProjectId, limit: 50 } }),
    runtimeRequest<RuntimePage>("/v1/audit-events/runtime", { query: { project_id: selectedProjectId, limit: 50 } })
  ]);
  return {
    authenticated: true,
    authorized_projects: authorizedProjects,
    selection_status: projectId && !requested ? "fallback" : "selected",
    bundle: {
      access: { project_id: selectedProjectId, member_user_id: actorId },
      project: selected,
      launch_config: launch.ok ? launch.data : null,
      score_weight_config: scoreWeight.ok ? scoreWeight.data : null,
      lifecycle_events: lifecycleEvents.ok ? lifecycleEvents.data : { total_count: 0, records: [] },
      audit_events: auditEvents.ok ? auditEvents.data : { total_count: 0, records: [] }
    }
  };
}

async function loadAllCustomerProjects(): Promise<RuntimeResult<AuthorizedProject[]>> {
  const records: AuthorizedProject[] = [];
  const projectIds = new Set<string>();
  let expectedTotal: number | null = null;
  let offset = 0;
  while (expectedTotal === null || records.length < expectedTotal) {
    const page = await runtimeRequest<StableCustomerProjectPage>("/v1/projects", {
      query: { limit: SURFACE_PROJECT_PAGE_SIZE, offset }
    });
    if (!page.ok) {
      return page;
    }
    const totalCount = page.data.total;
    if (!Number.isInteger(totalCount) || totalCount < 0 || totalCount > MAX_AUTHORIZED_PROJECTS) {
      return projectPaginationFailure("The customer project scope count is invalid.");
    }
    if (expectedTotal === null) {
      expectedTotal = totalCount;
    } else if (expectedTotal !== totalCount) {
      return projectPaginationFailure("The customer project scope changed while it was loading.");
    }
    if (!Array.isArray(page.data.items) || page.data.items.length > SURFACE_PROJECT_PAGE_SIZE) {
      return projectPaginationFailure("The customer project page is invalid.");
    }
    if (page.data.items.length === 0 && records.length < expectedTotal) {
      return projectPaginationFailure("The customer project list ended before its declared total.");
    }
    for (const item of page.data.items) {
      const recordProjectId = item.project_id;
      if (!recordProjectId || projectIds.has(recordProjectId)) {
        return projectPaginationFailure("The customer project list contains an invalid or duplicate project.");
      }
      projectIds.add(recordProjectId);
      records.push({
        project: {
          id: item.project_id,
          name: item.display_name,
          status: item.status
        }
      });
    }
    if (records.length > expectedTotal) {
      return projectPaginationFailure("The customer project list exceeds its declared total.");
    }
    offset = records.length;
  }
  return { ok: true, data: records, status: 200, response: {} };
}

function projectPaginationFailure(detail: string): RuntimeResult<AuthorizedProject[]> {
  const problem: RuntimeErrorEnvelope = {
    code: "runtime_invalid_page",
    detail,
    correlation_id: ""
  };
  return {
    ok: false,
    error: { code: "auth_request_failed", detail, correlation_id: "" },
    problem,
    status: 502,
    response: {}
  };
}

async function loadPage(
  path: CustomerApiPath,
  projectId: string,
  actorId?: string,
  extra?: Record<string, string | number>
): Promise<RuntimePageLoad> {
  const response = await runtimeRequest<RuntimePage>(path, {
    actorId,
    query: { project_id: projectId, limit: 10, ...(extra || {}) }
  });
  return response.ok
    ? { page: response.data }
    : {
        page: { total_count: 0, records: [] },
        failure: { resource: path, error: response.error }
      };
}

export async function loadPortalRuntimeData(projectId: string, actorId?: string): Promise<PortalRuntimeData> {
  const [scores, evidence, collectionRuns, graphs, reports, reportJobs, actions, traceability] = await Promise.all([
    loadPage("/v1/visibility-scores/runtime", projectId, actorId, { limit: 20 }),
    loadPage("/v1/evidence-runs/runtime", projectId, actorId, { limit: 20 }),
    loadPage("/v1/collection-runs/runtime", projectId, actorId),
    loadPage("/v1/citation-graphs/runtime", projectId, actorId),
    loadPage("/v1/reports/runtime", projectId, actorId),
    loadPage("/v1/report-export-jobs/runtime", projectId, actorId),
    loadPage("/v1/action-plans/runtime", projectId, actorId),
    runtimeRequest<Record<string, unknown>>("/v1/traceability/runtime", { actorId, query: { project_id: projectId } })
  ]);
  const errors = [
    scores.failure,
    evidence.failure,
    collectionRuns.failure,
    graphs.failure,
    reports.failure,
    reportJobs.failure,
    actions.failure,
    ...(traceability.ok ? [] : [{ resource: "/v1/traceability/runtime", error: traceability.error }])
  ].filter((failure): failure is { resource: string; error: AuthErrorEnvelope } => Boolean(failure));
  return {
    scores: scores.page,
    evidence: evidence.page,
    collectionRuns: collectionRuns.page,
    graphs: graphs.page,
    reports: reports.page,
    reportJobs: reportJobs.page,
    actions: actions.page,
    traceability: traceability.ok ? traceability.data : null,
    errors
  };
}

export function latestScore(scores: RuntimePage): number | undefined {
  const first = scores.records[0] as { snapshot?: { final_score?: unknown; score?: unknown } } | undefined;
  const raw = first?.snapshot?.final_score ?? first?.snapshot?.score;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return raw > 1 ? raw / 100 : raw;
  }
  return undefined;
}

export function pct(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "暂无数据";
  }
  return `${Math.round(value * 100)}%`;
}
