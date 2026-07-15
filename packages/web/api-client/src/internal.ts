import type { EngineeringWorkItem } from "@geo/types/internal";
import { requestJson } from "./transport";

export class InternalApiClient {
  constructor(private readonly baseUrl: string) {}

  listEngineeringWorkItems(): Promise<{ items: EngineeringWorkItem[] }> {
    return requestJson(this.baseUrl, "/v1/engineering/work-items");
  }
}
