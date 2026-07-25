import type {
  CustomerWorkflowCMetricKey,
  CustomerWorkflowCReport,
  CustomerWorkflowCReportPage,
  CustomerWorkflowCReportPayload,
  CustomerWorkflowCReportSourceKind
} from "@geo/types/customer";

type UnknownObject = { [key: string]: unknown };

const REPORT_KEYS = [
  "id",
  "project_id",
  "campaign_id",
  "semantic_snapshot_hash",
  "report_hash",
  "source_kind",
  "approved_safe_payload",
  "approved_at"
] as const;

const PAYLOAD_KEYS = new Set([
  "headline",
  "summary",
  "methodology",
  "metrics",
  "warnings",
  "mention_rate",
  "recommendation_rate"
]);

export const CUSTOMER_WORKFLOW_C_METRIC_KEYS = [
  "mention",
  "mention_rate",
  "recommendation_rate",
  "brand_mention",
  "product_mention",
  "recommendation",
  "recommendation_strength",
  "competitor_mention",
  "competitor_relative_position",
  "sentiment",
  "fact_accuracy",
  "explicit_conflict",
  "subject_mixup",
  "key_fact_omission",
  "citation_entailment",
  "citation_position",
  "citation_order",
  "verified_url_hit",
  "source_domain_diversity",
  "source_type_diversity",
  "approved_corpus_absorption"
] as const satisfies readonly CustomerWorkflowCMetricKey[];

const METRIC_KEYS = new Set<string>(CUSTOMER_WORKFLOW_C_METRIC_KEYS);
const COUNT_METRIC_KEYS = new Set<CustomerWorkflowCMetricKey>([
  "source_domain_diversity",
  "source_type_diversity"
]);
const SIGNED_METRIC_KEYS = new Set<CustomerWorkflowCMetricKey>([
  "competitor_relative_position",
  "sentiment"
]);
const DECIMAL_TEXT = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const LOWER_HEX_64 = /^[0-9a-f]{64}$/;
const UUID_TEXT = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function customerWorkflowCReportPageGuard(
  projectId: string,
  campaignId: string
): (value: unknown) => value is CustomerWorkflowCReportPage {
  return (value: unknown): value is CustomerWorkflowCReportPage => (
    isCustomerWorkflowCReportPage(value)
    && value.items.every((item) => (
      item.project_id === projectId && item.campaign_id === campaignId
    ))
  );
}

export function isCustomerWorkflowCReportPage(
  value: unknown
): value is CustomerWorkflowCReportPage {
  const record = objectValue(value);
  return Boolean(
    record
    && hasExactKeys(record, ["items", "total"])
    && Array.isArray(record.items)
    && record.items.every(isCustomerWorkflowCReport)
    && nonNegativeInteger(record.total)
    && record.total === record.items.length
  );
}

function isCustomerWorkflowCReport(value: unknown): value is CustomerWorkflowCReport {
  const record = objectValue(value);
  return Boolean(
    record
    && hasExactKeys(record, [...REPORT_KEYS])
    && uuidValue(record.id)
    && uuidValue(record.project_id)
    && uuidValue(record.campaign_id)
    && hashValue(record.semantic_snapshot_hash)
    && hashValue(record.report_hash)
    && sourceKind(record.source_kind)
    && isCustomerWorkflowCReportPayload(record.approved_safe_payload)
    && timestamp(record.approved_at)
  );
}

function isCustomerWorkflowCReportPayload(
  value: unknown
): value is CustomerWorkflowCReportPayload {
  const record = objectValue(value);
  if (!record || !Object.keys(record).every((key) => PAYLOAD_KEYS.has(key))) return false;
  if (!nonEmptyText(record.headline, 200)) return false;
  if (!optionalText(record.summary, 2_000) || !optionalText(record.methodology, 2_000)) {
    return false;
  }
  if (record.metrics !== undefined && !metricRecord(record.metrics)) return false;
  if (record.warnings !== undefined && !warningList(record.warnings)) return false;
  return optionalRatio(record.mention_rate) && optionalRatio(record.recommendation_rate);
}

function metricRecord(value: unknown): boolean {
  const record = objectValue(value);
  const keys = record ? Object.keys(record) : [];
  return Boolean(
    record
    && keys.length > 0
    && keys.length <= CUSTOMER_WORKFLOW_C_METRIC_KEYS.length
    && keys.every((key) => (
      METRIC_KEYS.has(key)
      && metricValueForKey(key as CustomerWorkflowCMetricKey, record[key])
    ))
  );
}

function warningList(value: unknown): boolean {
  return Array.isArray(value)
    && value.length > 0
    && value.length <= 20
    && value.every((item) => nonEmptyText(item, 500));
}

function optionalRatio(value: unknown): boolean {
  if (value === undefined) return true;
  return ratioValue(value);
}

function metricValueForKey(key: CustomerWorkflowCMetricKey, value: unknown): boolean {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return false;
    if (COUNT_METRIC_KEYS.has(key)) return value >= 0 && Number.isSafeInteger(value);
    if (SIGNED_METRIC_KEYS.has(key)) return value >= -1 && value <= 1;
    return value >= 0 && value <= 1;
  }
  const decimal = decimalText(value);
  if (!decimal) return false;
  if (COUNT_METRIC_KEYS.has(key)) {
    return decimalNonNegative(decimal) && decimalTextIsInteger(decimal);
  }
  if (SIGNED_METRIC_KEYS.has(key)) return decimalAbsoluteAtMostOne(decimal);
  return decimalNonNegative(decimal) && decimalAbsoluteAtMostOne(decimal);
}

function ratioValue(value: unknown): boolean {
  if (typeof value === "number") return Number.isFinite(value) && value >= 0 && value <= 1;
  const decimal = decimalText(value);
  return Boolean(
    decimal
    && decimalNonNegative(decimal)
    && decimalAbsoluteAtMostOne(decimal)
  );
}

type DecimalTextParts = Readonly<{
  negative: boolean;
  integer: string;
  fraction: string;
}>;

function decimalText(value: unknown): DecimalTextParts | null {
  if (typeof value !== "string" || value.length > 64 || !DECIMAL_TEXT.test(value)) return null;
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [integer, fraction = ""] = unsigned.split(".", 2);
  return { negative, integer, fraction };
}

function decimalNonNegative(value: DecimalTextParts): boolean {
  return !value.negative || decimalTextIsZero(value);
}

function decimalAbsoluteAtMostOne(value: DecimalTextParts): boolean {
  return value.integer === "0"
    || (value.integer === "1" && zeroDigits(value.fraction));
}

function decimalTextIsInteger(value: DecimalTextParts): boolean {
  return zeroDigits(value.fraction);
}

function decimalTextIsZero(value: DecimalTextParts): boolean {
  return value.integer === "0" && zeroDigits(value.fraction);
}

function zeroDigits(value: string): boolean {
  return value === "" || /^0+$/.test(value);
}

function sourceKind(value: unknown): value is CustomerWorkflowCReportSourceKind {
  return value === "provider_api" || value === "proxy_grounded_api" || value === "automated_ui";
}

function optionalText(value: unknown, maximum: number): boolean {
  return value === undefined || nonEmptyText(value, maximum);
}

function nonEmptyText(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= maximum;
}

function timestamp(value: unknown): value is string {
  return typeof value === "string"
    && value.trim().length > 0
    && /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    && Number.isFinite(Date.parse(value));
}

function hashValue(value: unknown): value is string {
  return typeof value === "string" && LOWER_HEX_64.test(value);
}

function uuidValue(value: unknown): value is string {
  return typeof value === "string" && UUID_TEXT.test(value);
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function objectValue(value: unknown): UnknownObject | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as UnknownObject
    : null;
}

function hasExactKeys(record: UnknownObject, keys: readonly string[]): boolean {
  const actual = Object.keys(record).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === expected[index]);
}
