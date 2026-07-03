type RuntimeRequestOptions = {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | undefined | null>;
  cache?: RequestCache;
};

export type RuntimeResult<T> = {
  ok: boolean;
  data?: T;
  error?: string;
  status?: number;
};

export function apiBase(): string {
  return process.env.API_INTERNAL_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://api:8000";
}

export function adminActorId(): string {
  return process.env.GENO_ADMIN_ACTOR_ID || "runtime-console";
}

export function customerWebBaseUrl(): string {
  return process.env.CUSTOMER_WEB_BASE_URL || process.env.NEXT_PUBLIC_CUSTOMER_WEB_BASE_URL || "http://localhost:3000";
}

export function customerInvitationUrl(invitationId: string, inviteToken: string): string {
  const url = new URL("/", customerWebBaseUrl());
  url.searchParams.set("invitation_id", invitationId);
  url.searchParams.set("invite_token", inviteToken);
  return url.toString();
}

export function actorHeaders(extra?: HeadersInit): HeadersInit {
  return {
    "X-GENO-Actor-Id": adminActorId(),
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

export async function runtimeRequest<T>(path: string, options: RuntimeRequestOptions = {}): Promise<RuntimeResult<T>> {
  const headers: HeadersInit = options.body
    ? actorHeaders({ "Content-Type": "application/json" })
    : actorHeaders();
  try {
    const response = await fetch(runtimeUrl(path, options.query), {
      method: options.method || "GET",
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
      cache: options.cache || "no-store"
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" && payload && "detail" in payload ? String(payload.detail) : String(payload);
      return { ok: false, error: detail || `Runtime request failed with ${response.status}`, status: response.status };
    }
    return { ok: true, data: payload as T, status: response.status };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "Runtime API unavailable" };
  }
}

export function lines(value: FormDataEntryValue | null): string[] {
  return String(value || "")
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function parseJsonObject(value: FormDataEntryValue | null, fieldName: string): RuntimeResult<Record<string, unknown>> {
  const raw = String(value || "").trim();
  if (!raw) {
    return { ok: true, data: {} };
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      return { ok: false, error: `${fieldName} must be a JSON object` };
    }
    return { ok: true, data: parsed as Record<string, unknown> };
  } catch {
    return { ok: false, error: `${fieldName} must be valid JSON` };
  }
}
