export type AttributionEventType = "session_start" | "page_view" | "click" | "direct";

export interface AttributionClientConfig {
  collectorBaseUrl: string;
  projectId: string;
  collectorId: string;
  writeKey: string;
  consentSchemaVersion: string;
  consent: () => boolean;
  fetch?: typeof globalThis.fetch;
}

export interface AttributionEventInput {
  eventType: AttributionEventType;
  sourceEventId?: string;
  occurredAt?: Date;
  traceToken?: string;
  utm?: Partial<Record<"source" | "medium" | "campaign" | "term" | "content", string>>;
}

export interface AttributionReceipt {
  project_id: string;
  session_id: string;
  touch_id?: string | null;
  replayed: boolean;
}

export function createAttributionClient(config: AttributionClientConfig) {
  const fetcher = config.fetch ?? globalThis.fetch.bind(globalThis);
  const storageKey = `geo:attribution-session:${config.projectId}:${config.collectorId}`;

  function sessionId(): string {
    const existing = globalThis.sessionStorage?.getItem(storageKey);
    if (existing) return existing;
    const created = globalThis.crypto.randomUUID();
    globalThis.sessionStorage?.setItem(storageKey, created);
    return created;
  }

  async function track(input: AttributionEventInput): Promise<AttributionReceipt> {
    if (!config.consent()) {
      throw new Error("Attribution consent has not been granted");
    }
    const response = await fetcher(
      `${config.collectorBaseUrl.replace(/\/$/, "")}/v1/collect/${config.projectId}/${config.collectorId}/events`,
      {
        method: "POST",
        credentials: "omit",
        keepalive: true,
        headers: {
          "Content-Type": "application/json",
          "X-GEO-Write-Key": config.writeKey,
        },
        body: JSON.stringify({
          client_session_id: sessionId(),
          source_event_id: input.sourceEventId ?? globalThis.crypto.randomUUID(),
          event_type: input.eventType,
          occurred_at: (input.occurredAt ?? new Date()).toISOString(),
          consent: true,
          consent_schema_version: config.consentSchemaVersion,
          trace_token: input.traceToken ?? null,
          utm: input.utm ?? {},
        }),
      },
    );
    if (!response.ok) {
      const problem = (await response.json().catch(() => null)) as { detail?: string } | null;
      throw new Error(problem?.detail ?? `Attribution collector returned HTTP ${response.status}`);
    }
    return (await response.json()) as AttributionReceipt;
  }

  return { track };
}
