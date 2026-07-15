import { isAuthIdentity, type AuthIdentity } from "@geo/types/auth";
import type {
  CustomerApprovedReport,
  CustomerApiPath,
  CustomerGeoMetric,
  CustomerGeoResource,
  CustomerGeoSummary,
  CustomerMeasurementWindow,
  CustomerProblemDetails,
  CustomerProjectPage,
  CustomerVerifiedUrl
} from "@geo/types/customer";

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

  getGeoSummary(
    projectId: string,
    campaignId?: string
  ): Promise<CustomerApiResult<CustomerGeoSummary>> {
    return this.get(this.geoPath(projectId, "summary"), campaignQuery(campaignId), isGeoSummary);
  }

  listGeoMetrics(
    projectId: string,
    campaignId?: string
  ): Promise<CustomerApiResult<CustomerGeoMetric[]>> {
    return this.get(this.geoPath(projectId, "metrics"), campaignQuery(campaignId), isMetricList);
  }

  listMeasurementWindows(
    projectId: string,
    campaignId?: string
  ): Promise<CustomerApiResult<CustomerMeasurementWindow[]>> {
    return this.get(
      this.geoPath(projectId, "measurement-windows"),
      campaignQuery(campaignId),
      isMeasurementWindowList
    );
  }

  listVerifiedUrls(
    projectId: string,
    campaignId?: string
  ): Promise<CustomerApiResult<CustomerVerifiedUrl[]>> {
    return this.get(
      this.geoPath(projectId, "verified-urls"),
      campaignQuery(campaignId),
      isVerifiedUrlList
    );
  }

  listApprovedReports(
    projectId: string,
    campaignId?: string
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

function campaignQuery(campaignId?: string): GeoApiQuery | undefined {
  return campaignId ? { campaign_id: campaignId } : undefined;
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
    && (record.campaign_id === null || text(record.campaign_id))
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
  return Boolean(
    record
    && strings(record, "id", "project_id", "protocol_id", "campaign_id", "method_version", "computed_at")
    && windowValue(record.measurement_window)
    && integers(record, "expected_sample_count", "eligible_sample_count")
    && numbers(
      record,
      "recommendation_share",
      "product_mention_share",
      "placement_citation_share",
      "qualified_destination_coverage",
      "verified_placement_coverage",
      "competitive_delta"
    )
    && statusValue(record.status)
    && stringArray(record.confounded_reasons)
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
  return Array.isArray(value) && value.every((item) => {
    const record = objectValue(item);
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
  });
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

function strings(record: { [key: string]: unknown }, ...keys: string[]): boolean {
  return keys.every((key) => text(record[key]));
}

function integers(record: { [key: string]: unknown }, ...keys: string[]): boolean {
  return keys.every((key) => integer(record[key]));
}

function numbers(record: { [key: string]: unknown }, ...keys: string[]): boolean {
  return keys.every((key) => typeof record[key] === "number" && Number.isFinite(record[key]));
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function windowValue(value: unknown): boolean {
  return value === "baseline" || value === "t28" || value === "t56"
    || value === "t84" || value === "ad_hoc";
}

function statusValue(value: unknown): boolean {
  return value === "complete" || value === "confounded";
}
