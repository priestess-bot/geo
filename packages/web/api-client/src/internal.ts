import type { EngineeringWorkItemsResponse } from "@geo/types/internal";
import {
  geoApiUrl,
  mergeClientRequestInit,
  performRuntimeHttpRequest,
  type GeoApiClientOptions,
  type RuntimeHttpResult
} from "./transport";

export class InternalApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly options: GeoApiClientOptions = {}
  ) {}

  listEngineeringWorkItems(): Promise<RuntimeHttpResult<EngineeringWorkItemsResponse>> {
    return performRuntimeHttpRequest(
      geoApiUrl(this.baseUrl, "/v1/engineering/work-items"),
      mergeClientRequestInit(this.options),
      this.options.fetcher
    );
  }
}
