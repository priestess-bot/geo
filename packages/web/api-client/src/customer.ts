import { isAuthIdentity, type AuthIdentity } from "@geo/types/auth";
import type {
  CustomerApprovedReport,
  CustomerApiPath,
  CustomerCampaign,
  CustomerCampaignReadModel,
  CustomerGeoMetric,
  CustomerGeoResource,
  CustomerGeoSummary,
  CustomerMeasurementWindow,
  CustomerProblemDetails,
  CustomerProjectPage,
  CustomerVerifiedUrl
} from "@geo/types/customer";

import { isSourceStratum } from "./customer-source-contract";
import {
  geoApiUrl,
  mergeClientRequestInit,
  performRuntimeHttpRequest,
  type GeoApiClientOptions,
  type GeoApiQuery,
  type RuntimeErrorEnvelope,
  type RuntimeResponseMetadata
} from "./transport";

export type CustomerApiResult<T> =
  | Readonly<{
      ok: true;
      data: T;
      status: number;
      response: RuntimeResponseMetadata;
    }>
  | Readonly<{
      ok: false;
      problem: CustomerProblemDetails;
      response: RuntimeResponseMetadata;
    }>;

type ResponseGuard<T> = (value: unknown) => value is T;

export class CustomerApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly options: GeoApiClientOptions = {}
  ) {}

  currentIdentity(): Promise<CustomerApiResult<AuthIdentity>> {
    return this.get("/v1/auth/me", undefined, isAuthIdentity);
  }

  listProjects(limit = 100, offset = 0): Promise<CustomerApiResult<CustomerProjectPage>> {
    return this.get("/v1/projects", { limit, offset }, isCustomerProjectPage);
  }

  listGeoCampaigns(projectId: string): Promise<CustomerApiResult<CustomerCampaign[]>> {
    return this.get(this.campaignsPath(projectId), undefined, isCampaignList);
  }

  getGeoCampaignReadModel(
    projectId: string,
    campaignId: string
  ): Promise<CustomerApiResult<CustomerCampaignReadModel>> {
    return this.get(
      this.campaignReadModelPath(projectId, campaignId),
      undefined,
      isCampaignReadModel
    );
  }

  getGeoSummary(
    projectId: string,
    campaignId: string
  ): Promise<CustomerApiResult<CustomerGeoSummary>> {
    return this.get(this.geoPath(projectId, "summary"), campaignQuery(campaignId), isGeoSummary);
  }

  listGeoMetrics(
    projectId: string,
    campaignId: string
  ): Promise<CustomerApiResult<CustomerGeoMetric[]>> {
    return this.get(this.geoPath(projectId, "metrics"), campaignQuery(campaignId), isMetricList);
  }

  listMeasurementWindows(
    projectId: string,
    campaignId: string
  ): Promise<CustomerApiResult<CustomerMeasurementWindow[]>> {
    return this.get(
      this.geoPath(projectId, "measurement-windows"),
      campaignQuery(campaignId),
      isMeasurementWindowList
    );
  }

  listVerifiedUrls(
    projectId: string,
    campaignId: string
  ): Promise<CustomerApiResult<CustomerVerifiedUrl[]>> {
    return this.get(
      this.geoPath(projectId, "verified-urls"),
      campaignQuery(campaignId),
      isVerifiedUrlList
    );
  }

  listApprovedReports(
    projectId: string,
    campaignId: string
  ): Promise<CustomerApiResult<CustomerApprovedReport[]>> {
    return this.get(
      this.geoPath(projectId, "reports"),
      campaignQuery(campaignId),
      isApprovedReportList
    );
  }

  private geoPath(projectId: string, resource: CustomerGeoResource): CustomerApiPath {
    return `/v1/projects/${encodeURIComponent(projectId)}/geo/${resource}`;
  }

  private campaignsPath(projectId: string): CustomerApiPath {
    return `/v1/projects/${encodeURIComponent(projectId)}/geo/campaigns`;
  }

  private campaignReadModelPath(projectId: string, campaignId: string): CustomerApiPath {
    return `/v1/projects/${encodeURIComponent(projectId)}/geo/campaigns/${encodeURIComponent(campaignId)}/read-model`;
  }

  private async get<T>(
    path: CustomerApiPath,
    query: GeoApiQuery | undefined,
    guard: ResponseGuard<T>
  ): Promise<CustomerApiResult<T>> {
    const result = await performRuntimeHttpRequest<unknown>(
      geoApiUrl(this.baseUrl, path, query),
      mergeClientRequestInit(this.options, { method: "GET" }),
      this.options.fetcher
    );
    if (!result.ok) {
      return {
        ok: false,
        problem: customerProblem(result.error, result.status, path),
        response: result.response
      };
    }
    if (!guard(result.data)) {
      return {
        ok: false,
        problem: {
          type: "urn:geo:problem:invalid-customer-contract",
          title: "Invalid Customer API response",
          status: 502,
          detail: "The Customer API returned data outside its stable contract.",
          instance: path,
          request_id: result.response.requestId || ""
        },
        response: result.response
      };
    }
    return {
      ok: true,
      data: result.data,
      status: result.status,
      response: result.response
    };
  }
}

function customerProblem(
  error: RuntimeErrorEnvelope,
  status: number | undefined,
  path: string
): CustomerProblemDetails {
  const resolvedStatus = error.status || status || 503;
  return {
    type: error.type || `urn:geo:problem:${error.code}`,
    title: error.title || (resolvedStatus === 503 ? "Service Unavailable" : "Request Failed"),
    status: resolvedStatus,
    detail: error.detail,
    instance: error.instance || path,
    request_id: error.request_id || error.correlation_id,
    ...(error.errors !== undefined ? { errors: error.errors } : {})
  };
}

function campaignQuery(campaignId: string): GeoApiQuery {
  return { campaign_id: campaignId };
}

function isCampaignList(value: unknown): value is CustomerCampaign[] {
  return Array.isArray(value) && value.every(isCampaign);
}

function isCampaign(value: unknown): value is CustomerCampaign {
  const record = objectValue(value);
  return Boolean(
    record
    && strings(record, "id", "project_id", "name", "objective", "status")
    && integer(record.approved_report_count)
    && (record.latest_approved_at === null || text(record.latest_approved_at))
  );
}

function isCampaignReadModel(value: unknown): value is CustomerCampaignReadModel {
  const record = objectValue(value);
  return Boolean(
    record
    && isCampaign(record.campaign)
    && isGeoSummary(record.summary)
    && Array.isArray(record.approved_measurements)
    && record.approved_measurements.every((item) => {
      const approved = objectValue(item);
      return Boolean(
        approved
        && isApprovedReport(approved.report)
        && isMetric(approved.snapshot)
        && (
          (
            approved.snapshot_contract === "statistics_v2"
            && objectValue(approved.snapshot)?.statistics_contract_version
              === "geo-observation-statistics-v2"
          )
          || (
            approved.snapshot_contract === "legacy_unknown"
            && objectValue(approved.snapshot)?.statistics_contract_version === "legacy-v1"
          )
        )
      );
    })
    && isVerifiedUrlList(record.verified_urls)
  );
}

function isCustomerProjectPage(value: unknown): value is CustomerProjectPage {
  const record = objectValue(value);
  return Boolean(
    record
    && integer(record.total)
    && integer(record.limit)
    && integer(record.offset)
    && Array.isArray(record.items)
    && record.items.every((item) => {
      const project = objectValue(item);
      return Boolean(
        project
        && text(project.project_id)
        && text(project.display_name)
        && text(project.market_code)
        && text(project.role)
        && text(project.status)
      );
    })
  );
}

function isGeoSummary(value: unknown): value is CustomerGeoSummary {
  const record = objectValue(value);
  return Boolean(
    record
    && text(record.project_id)
    && strings(
      record,
      "campaign_id",
      "campaign_name",
      "campaign_objective",
      "campaign_status"
    )
    && integer(record.frozen_protocol_count)
    && integer(record.measurement_window_count)
    && integer(record.verified_url_count)
    && integer(record.approved_report_count)
    && Array.isArray(record.latest_metrics)
    && record.latest_metrics.every(isMetric)
    && text(record.interpretation)
  );
}

function isMetricList(value: unknown): value is CustomerGeoMetric[] {
  return Array.isArray(value) && value.every(isMetric);
}

function isMetric(value: unknown): value is CustomerGeoMetric {
  const record = objectValue(value);
  const common = Boolean(
    record
    && strings(
      record,
      "id",
      "project_id",
      "protocol_id",
      "campaign_id",
      "statistics_contract_version",
      "method_version",
      "input_hash",
      "computed_at"
    )
    && windowValue(record.measurement_window)
    && captureMethodValue(record.capture_method)
    && (record.source_stratum === null || isSourceStratum(record.source_stratum))
    && nullableText(record.source_stratum_hash)
    && nullableText(record.query_cluster_key)
    && nullableText(record.analysis_stratum_hash)
    && nullableInteger(record.minimum_valid_repeats)
    && integers(record, "expected_sample_count", "eligible_sample_count")
    && nullableInteger(record.sampled_sample_count)
    && nullableInteger(record.invalid_sample_count)
    && nullableInteger(record.missing_sample_count)
    && nullableNumber(record.sampling_completion_ratio)
    && nullableNumber(record.valid_completion_ratio)
    && nullableInteger(record.query_count)
    && nullableInteger(record.sufficient_query_count)
    && integerRecord(record.invalid_reason_counts)
    && stringArray(record.declared_confounding_factors)
    && Array.isArray(record.query_results)
    && record.query_results.every(isQueryMetricResult)
    && numbers(
      record,
      "recommendation_share",
      "product_mention_share",
      "placement_citation_share",
      "qualified_destination_coverage",
      "verified_placement_coverage",
      "competitive_delta"
    )
    && nullableNumber(record.recommendation_ci_low)
    && nullableNumber(record.recommendation_ci_high)
    && nullableNumber(record.product_mention_ci_low)
    && nullableNumber(record.product_mention_ci_high)
    && nullableNumber(record.placement_citation_ci_low)
    && nullableNumber(record.placement_citation_ci_high)
    && nullableNumber(record.recommendation_query_min)
    && nullableNumber(record.recommendation_query_max)
    && nullableNumber(record.product_mention_query_min)
    && nullableNumber(record.product_mention_query_max)
    && nullableNumber(record.placement_citation_query_min)
    && nullableNumber(record.placement_citation_query_max)
    && nullableText(record.worst_query_id)
    && stringArray(record.selected_destination_ids)
    && stringArray(record.qualified_destination_ids)
    && stringArray(record.verified_destination_ids)
    && statusValue(record.status)
    && stringArray(record.confounded_reasons)
    && nullableText(record.result_hash)
    && nullableText(record.observation_membership_version)
    && nullableText(record.observation_membership_hash)
    && nullableInteger(record.observation_membership_count)
  );
  if (!common || !record) return false;
  if (record.statistics_contract_version === "legacy-v1") return true;
  if (record.statistics_contract_version !== "geo-observation-statistics-v2") return false;
  return record.method_version === "geo-observation-statistics-v2"
    && record.source_stratum !== null
    && text(record.source_stratum_hash)
    && text(record.query_cluster_key)
    && text(record.analysis_stratum_hash)
    && integer(record.minimum_valid_repeats)
    && integer(record.sampled_sample_count)
    && integer(record.invalid_sample_count)
    && integer(record.missing_sample_count)
    && finiteNumber(record.sampling_completion_ratio)
    && finiteNumber(record.valid_completion_ratio)
    && integer(record.query_count)
    && integer(record.sufficient_query_count)
    && finiteNumber(record.recommendation_ci_low)
    && finiteNumber(record.recommendation_ci_high)
    && finiteNumber(record.product_mention_ci_low)
    && finiteNumber(record.product_mention_ci_high)
    && finiteNumber(record.placement_citation_ci_low)
    && finiteNumber(record.placement_citation_ci_high)
    && finiteNumber(record.recommendation_query_min)
    && finiteNumber(record.recommendation_query_max)
    && finiteNumber(record.product_mention_query_min)
    && finiteNumber(record.product_mention_query_max)
    && finiteNumber(record.placement_citation_query_min)
    && finiteNumber(record.placement_citation_query_max)
    && text(record.worst_query_id)
    && text(record.result_hash);
}

function isQueryMetricResult(value: unknown): boolean {
  const record = objectValue(value);
  return Boolean(
    record
    && hasExactKeys(record, [
      "monitoring_query_id",
      "query_text_snapshot",
      "query_cluster_key",
      "expected_sample_count",
      "sampled_sample_count",
      "valid_sample_count",
      "invalid_sample_count",
      "missing_sample_count",
      "meets_threshold",
      "invalid_reason_counts",
      "confounding_factors",
      "recommendation",
      "product_mention",
      "placement_citation",
      "competitor",
      "competitive_delta"
    ])
    && strings(record, "monitoring_query_id", "query_text_snapshot", "query_cluster_key")
    && integers(
      record,
      "expected_sample_count",
      "sampled_sample_count",
      "valid_sample_count",
      "invalid_sample_count",
      "missing_sample_count"
    )
    && typeof record.meets_threshold === "boolean"
    && integerRecord(record.invalid_reason_counts)
    && stringArray(record.confounding_factors)
    && isBinaryEstimate(record.recommendation)
    && isBinaryEstimate(record.product_mention)
    && isBinaryEstimate(record.placement_citation)
    && isBinaryEstimate(record.competitor)
    && finiteNumber(record.competitive_delta)
  );
}

function isBinaryEstimate(value: unknown): boolean {
  const record = objectValue(value);
  return Boolean(
    record
    && hasExactKeys(record, ["numerator", "denominator", "share", "ci_low", "ci_high"])
    && integers(record, "numerator", "denominator")
    && numbers(record, "share", "ci_low", "ci_high")
  );
}

function isMeasurementWindowList(value: unknown): value is CustomerMeasurementWindow[] {
  return Array.isArray(value) && value.every((item) => {
    const record = objectValue(item);
    return Boolean(
      record
      && strings(record, "protocol_id", "campaign_id", "computed_at")
      && windowValue(record.measurement_window)
      && integers(record, "expected_sample_count", "eligible_sample_count")
      && statusValue(record.status)
      && stringArray(record.confounded_reasons)
    );
  });
}

function isVerifiedUrlList(value: unknown): value is CustomerVerifiedUrl[] {
  return Array.isArray(value) && value.every((item) => {
    const record = objectValue(item);
    return Boolean(
      record
      && strings(record, "campaign_id", "url", "first_verified_at")
      && stringArray(record.protocol_ids)
      && (record.title === null || text(record.title))
      && (record.destination_id === null || text(record.destination_id))
      && integer(record.observation_count)
    );
  });
}

function isApprovedReportList(value: unknown): value is CustomerApprovedReport[] {
  return Array.isArray(value) && value.every(isApprovedReport);
}

function isApprovedReport(value: unknown): value is CustomerApprovedReport {
  const record = objectValue(value);
  return Boolean(
    record
    && strings(
      record,
      "id",
      "project_id",
      "protocol_id",
      "campaign_id",
      "metric_snapshot_id",
      "title",
      "body",
      "methodology_statement",
      "report_hash",
      "generated_at",
      "approved_at"
    )
    && record.status === "approved"
  );
}

function objectValue(value: unknown): { [key: string]: unknown } | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as { [key: string]: unknown }
    : null;
}

function text(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function integer(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function nullableNumber(value: unknown): boolean {
  return value === null || finiteNumber(value);
}

function nullableInteger(value: unknown): boolean {
  return value === null || integer(value);
}

function nullableText(value: unknown): boolean {
  return value === null || text(value);
}

function integerRecord(value: unknown): boolean {
  const record = objectValue(value);
  return Boolean(record && Object.values(record).every(integer));
}

function hasExactKeys(record: { [key: string]: unknown }, keys: string[]): boolean {
  const actual = Object.keys(record).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === expected[index]);
}

function strings(record: { [key: string]: unknown }, ...keys: string[]): boolean {
  return keys.every((key) => text(record[key]));
}

function integers(record: { [key: string]: unknown }, ...keys: string[]): boolean {
  return keys.every((key) => integer(record[key]));
}

function numbers(record: { [key: string]: unknown }, ...keys: string[]): boolean {
  return keys.every((key) => finiteNumber(record[key]));
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function windowValue(value: unknown): boolean {
  return value === "baseline" || value === "t28" || value === "t56"
    || value === "t84" || value === "ad_hoc";
}

function captureMethodValue(value: unknown): boolean {
  return value === "official_report_import"
    || value === "manual_ui"
    || value === "provider_api"
    || value === "proxy_grounded_api"
    || value === "synthetic"
    || value === "unknown";
}

function statusValue(value: unknown): boolean {
  return ["complete", "confounded", "insufficient_evidence"].includes(String(value));
}
