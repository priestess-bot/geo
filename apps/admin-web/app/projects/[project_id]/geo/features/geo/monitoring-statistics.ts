import { createHash } from "node:crypto";

import type { ObservationSourceStratumCreate } from "@geo/types/geo";

interface SourceStratumCanonicalValue {
  capture_method: ObservationSourceStratumCreate["capture_method"];
  platform: ObservationSourceStratumCreate["platform"];
  platform_detail?: string | null;
  surface: ObservationSourceStratumCreate["surface"];
  surface_kind: ObservationSourceStratumCreate["surface_kind"];
  surface_detail?: string | null;
  engine: string;
  configured_model: ObservationSourceStratumCreate["configured_model"];
  reported_model: ObservationSourceStratumCreate["reported_model"];
  locale: string;
  region: string;
  language: string;
  device: ObservationSourceStratumCreate["device"];
  client_kind: ObservationSourceStratumCreate["client_kind"];
  search_enabled: boolean;
  search_mode: ObservationSourceStratumCreate["search_mode"];
}

export function sourceStratumHash(stratum: ObservationSourceStratumCreate): string {
  return createHash("sha256")
    .update(canonicalJson(sourceStratumCanonicalValue(stratum)), "utf8")
    .digest("hex");
}

export function sourceStratumLabel(stratum: ObservationSourceStratumCreate): string {
  const model = stratum.reported_model.value
    || stratum.configured_model.value
    || stratum.reported_model.state;
  const platform = detailLabel(stratum.platform, stratum.platform_detail);
  const surface = detailLabel(stratum.surface, stratum.surface_detail);
  return `${captureMethodLabel(stratum.capture_method)} · ${platform} / ${surface} · ${model}`;
}

function sourceStratumCanonicalValue(
  stratum: ObservationSourceStratumCreate
): SourceStratumCanonicalValue {
  const value: SourceStratumCanonicalValue = {
    capture_method: stratum.capture_method,
    platform: stratum.platform,
    surface: stratum.surface,
    surface_kind: stratum.surface_kind,
    engine: stratum.engine,
    configured_model: stratum.configured_model,
    reported_model: stratum.reported_model,
    locale: stratum.locale,
    region: stratum.region,
    language: stratum.language,
    device: stratum.device,
    client_kind: stratum.client_kind,
    search_enabled: stratum.search_enabled,
    search_mode: stratum.search_mode
  };
  if (stratum.source_contract_version !== "geo-observation-source-v2") {
    value.platform_detail = stratum.platform_detail;
    value.surface_detail = stratum.surface_detail;
  }
  return value;
}

function detailLabel(value: string, detail: string | null): string {
  return detail ? `${value} (${detail})` : value;
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "number") {
    return JSON.stringify(value);
  }
  if (typeof value === "string") return asciiJsonString(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object") {
    return `{${Object.entries(value)
      .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
      .map(([key, item]) => `${asciiJsonString(key)}:${canonicalJson(item)}`)
      .join(",")}}`;
  }
  throw new TypeError("monitoring source stratum contains a non-JSON value");
}

function asciiJsonString(value: string): string {
  return JSON.stringify(value).replace(/[\u0080-\uffff]/g, (character) =>
    `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`
  );
}

function captureMethodLabel(value: string): string {
  return ({
    manual_ui: "人工消费者界面",
    provider_api: "Provider API",
    proxy_grounded_api: "Grounded Proxy API"
  } as Record<string, string>)[value] || value;
}
