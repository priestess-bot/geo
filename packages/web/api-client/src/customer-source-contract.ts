type UnknownObject = { [key: string]: unknown };

export function isSourceStratum(value: unknown): boolean {
  const record = objectValue(value);
  if (!record) return false;
  const configured = objectValue(record.configured_model);
  const reported = objectValue(record.reported_model);
  const contractVersion = record.source_contract_version;
  const legacy = contractVersion === "geo-observation-source-v2";
  const current = contractVersion === "geo-observation-source-v3";
  const detailsValid = legacy
    ? record.platform_detail === null && record.surface_detail === null
    : current
      && (record.platform === "other"
        ? text(record.platform_detail)
        : record.platform_detail === null)
      && (record.surface === "other"
        ? text(record.surface_detail)
        : record.surface_detail === null);
  return Boolean(
    captureMethodValue(record.capture_method)
    && detailsValid
    && strings(
      record,
      "platform",
      "surface",
      "surface_kind",
      "engine",
      "locale",
      "region",
      "language",
      "device",
      "client_kind",
      "search_mode"
    )
    && typeof record.search_enabled === "boolean"
    && isModelIdentity(configured)
    && isModelIdentity(reported)
  );
}

function isModelIdentity(record: UnknownObject | null): boolean {
  return Boolean(
    record
    && (
      record.state === "disclosed"
      || record.state === "not_disclosed"
      || record.state === "not_applicable"
    )
    && (record.value === null || text(record.value))
  );
}

function objectValue(value: unknown): UnknownObject | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as UnknownObject
    : null;
}

function strings(record: UnknownObject, ...keys: string[]): boolean {
  return keys.every((key) => text(record[key]));
}

function text(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function captureMethodValue(value: unknown): boolean {
  return value === "official_report_import"
    || value === "manual_ui"
    || value === "provider_api"
    || value === "proxy_grounded_api"
    || value === "synthetic"
    || value === "unknown";
}
