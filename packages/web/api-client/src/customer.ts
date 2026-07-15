import type { CustomerApiPath, CustomerProjectSummary } from "@geo/types/customer";
import {
  geoApiUrl,
  mergeClientRequestInit,
  performRuntimeHttpRequest,
  type GeoApiClientOptions,
  type GeoApiQuery,
  type RuntimeHttpResult
} from "./transport";

export class CustomerApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly options: GeoApiClientOptions = {}
  ) {}

  listProjects(): Promise<RuntimeHttpResult<{ items: CustomerProjectSummary[] }>> {
    return this.call("/v1/projects");
  }

  call<T>(
    path: CustomerApiPath,
    query?: GeoApiQuery,
    init?: RequestInit
  ): Promise<RuntimeHttpResult<T>> {
    return performRuntimeHttpRequest(
      geoApiUrl(this.baseUrl, path, query),
      mergeClientRequestInit(this.options, init),
      this.options.fetcher
    );
  }
}
