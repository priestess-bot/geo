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
  portal_token?: string | null;
  portal_token_record?: Record<string, unknown>;
  accepted_invitation?: Record<string, unknown>;
  bundle?: PortalBundle;
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

function actorHeaders(actorId?: string, extra?: HeadersInit): HeadersInit {
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

async function runtimeRequest<T>(path: string, options: RuntimeRequestOptions = {}): Promise<T | null> {
  try {
    const response = await fetch(runtimeUrl(path, options.query), {
      method: options.method || "GET",
      headers: options.body ? actorHeaders(options.actorId, { "Content-Type": "application/json" }) : actorHeaders(options.actorId),
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

export async function loadPortal(params: {
  portalToken?: string;
  invitationId?: string;
  inviteToken?: string;
  acceptedBy?: string;
}): Promise<PortalAccessResponse | null> {
  const body = params.portalToken
    ? { portal_token: params.portalToken }
    : params.invitationId && params.inviteToken
      ? {
          invitation_id: params.invitationId,
          invite_token: params.inviteToken,
          accepted_by: params.acceptedBy || null
        }
      : null;
  if (!body) {
    return null;
  }
  return runtimeRequest<PortalAccessResponse>("/v1/customer-portal/access", {
    method: "POST",
    body
  });
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
