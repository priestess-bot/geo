import { cookies } from "next/headers";

import { resolveCounterpartPortalUrl } from "./_auth/portalUrl";
import {
  performRuntimeHttpRequest,
  runtimeGuardHeaders,
  type RuntimeErrorEnvelope,
  type RuntimeHttpResult,
  type RuntimeRequestGuards,
  type RuntimeResponseMetadata
} from "./_runtime/contracts";

export type RuntimeRequestOptions = RuntimeRequestGuards & {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | undefined | null>;
  cache?: RequestCache;
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
      error: string;
      problem: RuntimeErrorEnvelope;
      status?: number;
      response: RuntimeResponseMetadata;
    };

type ParseJsonResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string };

export function apiBase(): string {
  return process.env.API_INTERNAL_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://api:8000";
}

export function adminActorId(): string {
  return process.env.GENO_ADMIN_ACTOR_ID || "runtime-console";
}

export function customerWebBaseUrl(): string {
  return resolveCounterpartPortalUrl({
    configuredValue: process.env.CUSTOMER_WEB_BASE_URL,
    developmentFallback: "http://localhost:3000/",
    environmentName: "CUSTOMER_WEB_BASE_URL",
    nodeEnv: process.env.NODE_ENV,
    publicDevelopmentValue: process.env.NEXT_PUBLIC_CUSTOMER_WEB_BASE_URL
  });
}

export function adminDevToolsEnabled(): boolean {
  return String(process.env.GENO_ADMIN_DEV_TOOLS_ENABLED || "").trim().toLowerCase() === "1";
}

export function customerInvitationUrl(invitationId: string, _inviteToken?: string): string {
  const url = new URL("/", customerWebBaseUrl());
  url.searchParams.set("invitation_id", invitationId);
  return url.toString();
}

export async function hasRuntimeSession(): Promise<boolean> {
  const cookieStore = await cookies();
  return Boolean(cookieStore.get("GENO_RUNTIME_SESSION")?.value);
}

export async function actorHeaders(extra?: HeadersInit): Promise<HeadersInit> {
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
  return { "X-GENO-Actor-Id": adminActorId(), ...(extra || {}) };
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

export async function runtimeHttpRequest<T>(
  path: string,
  options: RuntimeRequestOptions = {}
): Promise<RuntimeHttpResult<T>> {
  const hasBody = options.body !== undefined;
  const commandHeaders = runtimeGuardHeaders(options);
  const headers = await actorHeaders({
    ...(hasBody ? { "Content-Type": "application/json" } : {}),
    ...commandHeaders
  });
  return performRuntimeHttpRequest<T>(runtimeUrl(path, options.query), {
    method: options.method || "GET",
    headers,
    body: hasBody ? JSON.stringify(options.body) : undefined,
    cache: options.cache || "no-store"
  });
}

export async function runtimeRequest<T>(
  path: string,
  options: RuntimeRequestOptions = {}
): Promise<RuntimeResult<T>> {
  const result = await runtimeHttpRequest<T>(path, options);
  if (result.ok) {
    return result;
  }
  return {
    ...result,
    error: result.error.detail,
    problem: result.error
  };
}

export function lines(value: FormDataEntryValue | null): string[] {
  return String(value || "")
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function parseJsonObject(
  value: FormDataEntryValue | null,
  fieldName: string
): ParseJsonResult<Record<string, unknown>> {
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
