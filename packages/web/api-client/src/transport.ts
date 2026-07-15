export type RuntimeRequestGuards = Readonly<{
  ifMatch?: string;
  idempotencyKey?: string;
}>;

export type RuntimeResponseMetadata = Readonly<{
  etag?: string;
  location?: string;
  retryAfter?: string;
  correlationId?: string;
  requestId?: string;
}>;

export type RuntimeErrorEnvelope = Readonly<{
  code: string;
  detail: string;
  correlation_id: string;
  retryable?: boolean;
  details?: unknown;
}>;

export type RuntimeHttpResult<T> =
  | {
      ok: true;
      data: T;
      status: number;
      response: RuntimeResponseMetadata;
    }
  | {
      ok: false;
      error: RuntimeErrorEnvelope;
      status?: number;
      response: RuntimeResponseMetadata;
    };

export type RuntimeFetch = (input: string | URL, init?: RequestInit) => Promise<Response>;

export type GeoApiClientOptions = Readonly<{
  headers?: HeadersInit;
  fetcher?: RuntimeFetch;
  cache?: RequestCache;
}>;

export type GeoApiQuery = Record<string, string | number | boolean | undefined | null>;

export function runtimeGuardHeaders(guards: RuntimeRequestGuards): Record<string, string> {
  const headers: Record<string, string> = {};
  if (guards.ifMatch !== undefined) {
    headers["If-Match"] = validHeaderValue(guards.ifMatch, "If-Match");
  }
  if (guards.idempotencyKey !== undefined) {
    headers["Idempotency-Key"] = validHeaderValue(guards.idempotencyKey, "Idempotency-Key");
  }
  return headers;
}

export function readRuntimeResponseMetadata(
  headers: Headers,
  payload?: unknown
): RuntimeResponseMetadata {
  const record = objectRecord(payload);
  const errorRecord = runtimeErrorRecord(payload);
  const payloadCorrelationId = nonEmptyString(record?.correlation_id)
    || nonEmptyString(errorRecord?.correlation_id);
  const headerCorrelationId = nonEmptyString(headers.get("X-Correlation-ID"));
  const requestId = nonEmptyString(headers.get("X-GEO-Request-Id"))
    || nonEmptyString(headers.get("X-Request-Id"));
  return compactMetadata({
    etag: nonEmptyString(headers.get("ETag")),
    location: nonEmptyString(headers.get("Location")),
    retryAfter: nonEmptyString(headers.get("Retry-After")),
    correlationId: payloadCorrelationId || headerCorrelationId || requestId,
    requestId
  });
}

export function parseRuntimeError(
  payload: unknown,
  status: number,
  response: RuntimeResponseMetadata
): RuntimeErrorEnvelope {
  const record = runtimeErrorRecord(payload);
  const rawDetail = record?.detail;
  const explicitDetails = record?.details;
  const detail = nonEmptyString(rawDetail)
    || nonEmptyString(typeof payload === "string" ? payload : undefined)
    || `Runtime request failed with ${status}`;
  const correlationId = nonEmptyString(record?.correlation_id)
    || response.correlationId
    || response.requestId
    || "";
  const retryable = typeof record?.retryable === "boolean" ? record.retryable : undefined;
  return {
    code: nonEmptyString(record?.code) || `runtime_http_${status}`,
    detail,
    correlation_id: correlationId,
    ...(retryable === undefined ? {} : { retryable }),
    ...(explicitDetails !== undefined
      ? { details: explicitDetails }
      : rawDetail !== undefined && typeof rawDetail !== "string"
        ? { details: rawDetail }
        : {})
  };
}

export async function performRuntimeHttpRequest<T>(
  input: string | URL,
  init: RequestInit,
  fetcher: RuntimeFetch = fetch
): Promise<RuntimeHttpResult<T>> {
  try {
    const rawResponse = await fetcher(input, init);
    const payload = await readRuntimePayload(rawResponse);
    const response = readRuntimeResponseMetadata(rawResponse.headers, payload);
    if (!rawResponse.ok) {
      return {
        ok: false,
        error: parseRuntimeError(payload, rawResponse.status, response),
        status: rawResponse.status,
        response
      };
    }
    return {
      ok: true,
      data: payload as T,
      status: rawResponse.status,
      response
    };
  } catch (error) {
    return {
      ok: false,
      error: {
        code: "runtime_upstream_unavailable",
        detail: error instanceof Error && error.message ? error.message : "Runtime API unavailable",
        correlation_id: "",
        retryable: true
      },
      response: {}
    };
  }
}

/** Builds an API URL from a client-owned, typed path and serializable query values. */
export function geoApiUrl(baseUrl: string, path: string, query?: GeoApiQuery): URL {
  const url = new URL(path, baseUrl);
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && String(value).length > 0) {
      url.searchParams.set(key, String(value));
    }
  }
  return url;
}

export function mergeClientRequestInit(
  options: GeoApiClientOptions,
  init?: RequestInit
): RequestInit {
  return {
    ...init,
    headers: {
      ...(options.headers || {}),
      ...(init?.headers || {})
    },
    cache: init?.cache || options.cache || "no-store"
  };
}

async function readRuntimePayload(response: Response): Promise<unknown> {
  if (response.status === 204 || response.status === 205) {
    return undefined;
  }
  const raw = await response.text();
  if (!raw) {
    return undefined;
  }
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.toLowerCase().includes("json")) {
    return raw;
  }
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return raw;
  }
}

function validHeaderValue(value: string, name: string): string {
  if (!value.trim() || /[\r\n]/.test(value)) {
    throw new TypeError(`${name} must be a non-empty single-line value`);
  }
  return value;
}

function objectRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function runtimeErrorRecord(payload: unknown): Record<string, unknown> | undefined {
  const record = objectRecord(payload);
  if (!record || nonEmptyString(record.code) || typeof record.detail === "string") {
    return record;
  }
  return objectRecord(record.detail) || record;
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function compactMetadata(
  metadata: Record<keyof RuntimeResponseMetadata, string | undefined>
): RuntimeResponseMetadata {
  return Object.fromEntries(
    Object.entries(metadata).filter((entry): entry is [string, string] => entry[1] !== undefined)
  );
}
