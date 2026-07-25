import {
  workflowCReportMetricKeys,
  type MetricProtocol,
  type MetricProtocolPage,
  type SemanticMetricsJobReceipt,
  type StatisticalAnalysisJobReceipt,
  type StatisticalProtocol,
  type StatisticalProtocolPage,
  type WorkflowCApprovedSafePayload,
  type WorkflowCReport,
  type WorkflowCReportPage
} from "./workflowCControlTypes";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const HASH_PATTERN = /^[0-9a-f]{64}$/;
const DECIMAL_PATTERN = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const protocolStatuses = new Set(["draft", "in_review", "approved", "retired"]);
const reportStatuses = new Set([
  "draft",
  "in_review",
  "approved",
  "stale",
  "superseded",
  "revoked"
]);
const reportMetricKeys = new Set<string>(workflowCReportMetricKeys);
const countMetricKeys = new Set(["source_domain_diversity", "source_type_diversity"]);
const signedMetricKeys = new Set(["competitor_relative_position", "sentiment"]);
const safePayloadKeys = new Set([
  "headline",
  "summary",
  "methodology",
  "warnings",
  "metrics",
  "mention_rate",
  "recommendation_rate"
]);

export function isMetricProtocolPage(value: unknown): value is MetricProtocolPage {
  return page(value, isMetricProtocol);
}

export function isMetricProtocol(value: unknown): value is MetricProtocol {
  return protocolBase(value)
    && HASH_PATTERN.test(String(value.protocol_hash))
    && !("kind" in value);
}

export function isStatisticalProtocolPage(value: unknown): value is StatisticalProtocolPage {
  return page(value, isStatisticalProtocol);
}

export function isStatisticalProtocol(value: unknown): value is StatisticalProtocol {
  return protocolBase(value)
    && (value.kind === "comparison_plan" || value.kind === "drift_protocol")
    && HASH_PATTERN.test(String(value.definition_hash));
}

export function isWorkflowCReportPage(value: unknown): value is WorkflowCReportPage {
  return page(value, isWorkflowCReport);
}

export function isWorkflowCReport(value: unknown): value is WorkflowCReport {
  if (!record(value)) return false;
  return [value.report_id, value.project_id, value.campaign_id, value.monitoring_report_id, value.actor_id]
    .every(uuid)
    && positiveInteger(value.version)
    && reportStatuses.has(String(value.status))
    && [
      value.monitoring_report_hash,
      value.semantic_snapshot_hash,
      value.approved_safe_payload_hash,
      value.version_hash
    ].every(sha256)
    && (value.source_kind === "provider_api" || value.source_kind === "proxy_grounded_api")
    && isApprovedSafePayload(value.approved_safe_payload)
    && nullableString(value.reason)
    && nonEmptyString(value.occurred_at);
}

export function isApprovedSafePayload(value: unknown): value is WorkflowCApprovedSafePayload {
  if (!record(value) || !onlyKeys(value, safePayloadKeys) || !boundedString(value.headline, 1, 200)) {
    return false;
  }
  if (!optionalBoundedString(value.summary, 2_000)
    || !optionalBoundedString(value.methodology, 2_000)) return false;
  if (value.warnings !== undefined && (
    !Array.isArray(value.warnings)
    || value.warnings.length > 20
    || !value.warnings.every((item) => boundedString(item, 1, 500))
  )) return false;
  if (value.metrics !== undefined && !safeMetrics(value.metrics)) return false;
  return [value.mention_rate, value.recommendation_rate]
    .every((item) => item === undefined || isWorkflowCReportMetricValue("recommendation_rate", item));
}

export function isSemanticMetricsJobReceipt(value: unknown): value is SemanticMetricsJobReceipt {
  return record(value)
    && uuid(value.job_id)
    && value.status === "queued"
    && boundedString(value.status_url, 1, 1_000)
    && uuid(value.manifest_id)
    && sha256(value.manifest_hash)
    && typeof value.replayed === "boolean";
}

export function isStatisticalAnalysisJobReceipt(
  value: unknown
): value is StatisticalAnalysisJobReceipt {
  return record(value)
    && uuid(value.job_id)
    && value.status === "queued"
    && boundedString(value.status_url, 1, 1_000)
    && sha256(value.spec_hash)
    && typeof value.replayed === "boolean";
}

function protocolBase(value: unknown): value is Record<string, unknown> {
  if (!record(value)) return false;
  return [value.id, value.project_id, value.series_id].every(uuid)
    && positiveInteger(value.version)
    && (value.supersedes_protocol_id === null || uuid(value.supersedes_protocol_id))
    && protocolStatuses.has(String(value.status))
    && record(value.definition)
    && nonEmptyString(value.created_by)
    && [value.submitted_by, value.approved_by, value.retired_by, value.decision_reason]
      .every(nullableString)
    && positiveInteger(value.aggregate_version)
    && nonEmptyString(value.created_at)
    && nonEmptyString(value.updated_at)
    && [value.submitted_at, value.approved_at, value.retired_at].every(nullableString);
}

function safeMetrics(value: unknown): boolean {
  if (!record(value) || Object.keys(value).length > workflowCReportMetricKeys.length) return false;
  return Object.entries(value).every(([key, item]) => (
    reportMetricKeys.has(key) && isWorkflowCReportMetricValue(key, item)
  ));
}

export function isWorkflowCReportMetricValue(key: string, value: unknown): boolean {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return false;
    if (countMetricKeys.has(key)) return value >= 0 && Number.isSafeInteger(value);
    if (signedMetricKeys.has(key)) return value >= -1 && value <= 1;
    return value >= 0 && value <= 1;
  }
  if (typeof value !== "string" || value.length > 64 || !DECIMAL_PATTERN.test(value)) {
    return false;
  }
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [integer, fraction = ""] = unsigned.split(".");
  const fractionalPartIsZero = fraction.replaceAll("0", "") === "";
  const decimalIsZero = integer === "0" && fractionalPartIsZero;
  const nonNegative = !negative || decimalIsZero;
  if (countMetricKeys.has(key)) return nonNegative && fractionalPartIsZero;
  const magnitudeAtMostOne = integer === "0" || (integer === "1" && fractionalPartIsZero);
  if (signedMetricKeys.has(key)) return magnitudeAtMostOne;
  return nonNegative && magnitudeAtMostOne;
}

function page<T>(value: unknown, guard: (item: unknown) => item is T): boolean {
  return record(value)
    && nonNegativeInteger(value.total)
    && Array.isArray(value.items)
    && value.items.every(guard)
    && value.total >= value.items.length;
}

function onlyKeys(value: Record<string, unknown>, allowed: Set<string>): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function uuid(value: unknown): boolean {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

function sha256(value: unknown): boolean {
  return typeof value === "string" && HASH_PATTERN.test(value);
}

function boundedString(value: unknown, minimum: number, maximum: number): value is string {
  return typeof value === "string" && value.trim().length >= minimum && value.length <= maximum;
}

function nonEmptyString(value: unknown): value is string {
  return boundedString(value, 1, 5_000);
}

function optionalBoundedString(value: unknown, maximum: number): boolean {
  return value === undefined || boundedString(value, 1, maximum);
}

function nullableString(value: unknown): boolean {
  return value === null || nonEmptyString(value);
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
