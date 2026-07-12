import { cookies } from "next/headers";

type RuntimeRequestOptions = {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | undefined | null>;
  cache?: RequestCache;
  actorId?: string;
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
  authorized_projects: AuthorizedProject[];
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
};

export function apiBase(): string {
  return process.env.API_INTERNAL_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://api:8000";
}

async function actorHeaders(actorId?: string, extra?: HeadersInit): Promise<HeadersInit> {
  const cookieStore = await cookies();
  const sessionToken = cookieStore.get("GENO_RUNTIME_SESSION")?.value || "";
  const csrfToken = cookieStore.get("GENO_CSRF_TOKEN")?.value || "";
  if (sessionToken) {
    return {
      "X-GENO-Session-Token": sessionToken,
      ...(csrfToken
        ? {
            "X-GENO-CSRF-Token": csrfToken,
            Cookie: `GENO_CSRF_TOKEN=${encodeURIComponent(csrfToken)}`
          }
        : {}),
      ...(extra || {})
    };
  }
  if ((process.env.GENO_RUNTIME_AUTH_MODE || "header") === "session") {
    return { ...(extra || {}) };
  }
  return {
    "X-GENO-Actor-Id": actorId || process.env.GENO_CUSTOMER_RUNTIME_ACTOR_ID || process.env.GENO_ADMIN_ACTOR_ID || "runtime-console",
    ...(extra || {})
  };
}

function runtimeUrl(path: string, query?: RuntimeRequestOptions["query"]): string {
  const url = new URL(path, apiBase());
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && String(value).length > 0) {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

export async function runtimeRequest<T>(path: string, options: RuntimeRequestOptions = {}): Promise<T | null> {
  try {
    const headers = options.body
      ? await actorHeaders(options.actorId, { "Content-Type": "application/json" })
      : await actorHeaders(options.actorId);
    const response = await fetch(runtimeUrl(path, options.query), {
      method: options.method || "GET",
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
      cache: options.cache || "no-store"
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export async function loadSessionPortal(projectId?: string): Promise<SessionPortalResponse | null> {
  const authResponse = await runtimeRequest<{ auth?: { actor_id?: string; project_ids?: string[] } }>("/v1/auth/me");
  if (!authResponse?.auth?.actor_id) {
    return null;
  }
  const projectPage = await runtimeRequest<RuntimePage<AuthorizedProject>>("/v1/projects/runtime", {
    query: { limit: 100 }
  });
  const authorizedProjects = projectPage?.records || [];
  const selected = authorizedProjects.find((record) => record.project?.id === projectId) || authorizedProjects[0];
  const selectedProjectId = selected?.project?.id || "";
  if (!selectedProjectId) {
    return { authorized_projects: authorizedProjects, bundle: { access: { member_user_id: authResponse.auth.actor_id } } };
  }
  const [launch, scoreWeight, lifecycleEvents, auditEvents] = await Promise.all([
    runtimeRequest<Record<string, unknown>>("/v1/project-launch-configs/runtime", { query: { project_id: selectedProjectId } }),
    runtimeRequest<Record<string, unknown>>("/v1/score-weight-configs/runtime", { query: { project_id: selectedProjectId } }),
    runtimeRequest<RuntimePage>("/v1/projects/runtime/lifecycle-events", { query: { project_id: selectedProjectId, limit: 50 } }),
    runtimeRequest<RuntimePage>("/v1/audit-events/runtime", { query: { project_id: selectedProjectId, limit: 50 } })
  ]);
  return {
    authorized_projects: authorizedProjects,
    bundle: {
      access: { project_id: selectedProjectId, member_user_id: authResponse.auth.actor_id },
      project: selected,
      launch_config: launch,
      score_weight_config: scoreWeight,
      lifecycle_events: lifecycleEvents || { total_count: 0, records: [] },
      audit_events: auditEvents || { total_count: 0, records: [] }
    }
  };
}

async function loadPage(
  path: string,
  projectId: string,
  actorId?: string,
  extra?: Record<string, string | number>
): Promise<RuntimePage> {
  return (
    (await runtimeRequest<RuntimePage>(path, {
      actorId,
      query: { project_id: projectId, limit: 10, ...(extra || {}) }
    })) || { total_count: 0, records: [] }
  );
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
  return { scores, evidence, collectionRuns, graphs, reports, reportJobs, actions, traceability };
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
