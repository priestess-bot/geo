import { headers } from "next/headers";
import { resolveCounterpartPortalUrl } from "@geo/auth/portal-url";
import {
  performRuntimeHttpRequest,
  runtimeGuardHeaders,
  type RuntimeErrorEnvelope,
  type RuntimeHttpResult,
  type RuntimeRequestGuards,
  type RuntimeResponseMetadata
} from "@geo/api-client/transport";

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
  return process.env.GEO_ADMIN_ACTOR_ID || "runtime-console";
}

export function customerWebBaseUrl(): string {
  return resolveCounterpartPortalUrl({
    configuredValue: process.env.CUSTOMER_WEB_BASE_URL,
    deploymentEnvironment: process.env.GEO_DEPLOYMENT_ENVIRONMENT,
    developmentFallback: "http://localhost:3000/",
    environmentName: "CUSTOMER_WEB_BASE_URL",
    nodeEnv: process.env.NODE_ENV,
    publicDevelopmentValue: process.env.NEXT_PUBLIC_CUSTOMER_WEB_BASE_URL
  });
}

export function adminDevToolsEnabled(): boolean {
  return String(process.env.GEO_ADMIN_DEV_TOOLS_ENABLED || "").trim().toLowerCase() === "1";
}

export function customerInvitationUrl(invitationId: string, _inviteToken?: string): string {
  const url = new URL("/", customerWebBaseUrl());
  url.searchParams.set("invitation_id", invitationId);
  return url.toString();
}

export async function actorHeaders(extra?: HeadersInit): Promise<HeadersInit> {
  const authorization = (await headers()).get("authorization") || "";
  if (authorization) {
    return { Authorization: authorization, ...(extra || {}) };
  }
  if (process.env.GEO_AUTH_MODE === "development") {
    return {
      "X-GEO-Actor-ID": adminActorId(),
      "X-GEO-Tenant-ID": process.env.GEO_ADMIN_TENANT_ID || "",
      ...(extra || {})
    };
  }
  return { ...(extra || {}) };
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
